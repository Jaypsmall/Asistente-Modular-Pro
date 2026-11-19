"""Inspección y rellenado seguro de campos AcroForm en PDFs."""

import re
import xml.etree.ElementTree as ET
from pathlib import Path


TIPOS_RELLENABLES = {"Text", "ComboBox", "ListBox", "CheckBox", "RadioButton"}
MAX_TEXTO_DOCUMENTO = 18000
ETIQUETA_CODIFICADA = re.compile(r"^[A-Za-zÁÉÍÓÚÜÑ]{2,}\d{2,}$")


def _cargar_pymupdf():
    try:
        import pymupdf
    except ImportError as e:
        raise RuntimeError("Instala PyMuPDF con: pip install PyMuPDF") from e
    return pymupdf


def _etiqueta_legible(etiqueta):
    texto = (etiqueta or "").strip()
    return bool(texto and not ETIQUETA_CODIFICADA.fullmatch(texto))


def campos_para_ia(campos, instruccion):
    """Limita las propuestas automáticas a campos de texto con etiquetas visibles."""
    menciona_otras = bool(re.search(r"\b(otra|otras|otro|otros)\b", instruccion, re.I))
    resultado = []
    for campo in campos:
        etiqueta = campo.get("etiqueta", "")
        etiqueta_normalizada = etiqueta.strip().casefold()
        if campo.get("tipo") != "Text" or not campo.get("apto_ia"):
            continue
        if etiqueta_normalizada.startswith(("otra ", "otro ")) and not menciona_otras:
            continue
        resultado.append(campo)
    return resultado


def inspeccionar_pdf(ruta_pdf):
    """Extrae campos interactivos y texto para que el modelo pueda mapear datos."""
    fitz = _cargar_pymupdf()
    campos_por_nombre = {}
    texto_paginas = []
    caracteres = 0

    with fitz.open(ruta_pdf) as documento:
        if documento.needs_pass:
            raise ValueError("El PDF está protegido con contraseña.")

        for numero_pagina, pagina in enumerate(documento, start=1):
            if caracteres < MAX_TEXTO_DOCUMENTO:
                texto = pagina.get_text("text")
                texto = texto[: MAX_TEXTO_DOCUMENTO - caracteres]
                if texto.strip():
                    texto_paginas.append(f"[Página {numero_pagina}]\n{texto}")
                    caracteres += len(texto)

            for widget in pagina.widgets() or ():
                tipo = widget.field_type_string or ""
                nombre = (widget.field_name or "").strip()
                if (
                    tipo not in TIPOS_RELLENABLES
                    or not nombre
                    or widget.field_flags & 1
                ):
                    continue

                campo = campos_por_nombre.get(nombre)
                if campo is None:
                    etiqueta = widget.field_label or nombre
                    segmentos = [
                        re.sub(r"\[\d+\]$", "", segmento)
                        for segmento in nombre.split(".")
                    ]
                    seccion = next(
                        (
                            segmento
                            for segmento in segmentos
                            if segmento in {"INTERESADO", "REPRESENTANTE", "ID_DEUDA", "DOMIC_NOTIFICACION", "DOCUMENTACIÓN"}
                        ),
                        "",
                    )
                    campo = {
                        "nombre": nombre,
                        "etiqueta": etiqueta,
                        "tipo": tipo,
                        "valor_actual": str(widget.field_value or ""),
                        "opciones": [],
                        "pagina": numero_pagina,
                        "seccion": seccion,
                        "apto_ia": tipo == "Text" and _etiqueta_legible(etiqueta),
                    }
                    campos_por_nombre[nombre] = campo

                opciones = []
                if tipo in ("ComboBox", "ListBox"):
                    opciones = list(widget.choice_values or [])
                elif tipo == "RadioButton":
                    opcion = widget.on_state()
                    if opcion:
                        opciones = [str(opcion)]
                for opcion in opciones:
                    if opcion not in campo["opciones"]:
                        campo["opciones"].append(opcion)

    if not campos_por_nombre:
        raise ValueError(
            "Este PDF no contiene campos de formulario rellenables. "
            "Por ahora el modo PDF necesita un formulario interactivo (AcroForm)."
        )

    return list(campos_por_nombre.values()), "\n\n".join(texto_paginas)


def aplicar_valores(ruta_origen, ruta_destino, valores):
    """Aplica valores conocidos a una copia, validando el tipo y las opciones."""
    fitz = _cargar_pymupdf()
    origen = Path(ruta_origen).resolve()
    destino = Path(ruta_destino).resolve()
    if origen == destino:
        raise ValueError("La salida debe ser distinta del PDF original.")

    permitidos = set()
    rellenados = set()
    for nombre, valor in valores.items():
        if isinstance(nombre, str) and valor is not None:
            permitidos.add(nombre)

    with fitz.open(origen) as documento:
        for pagina in documento:
            for widget in pagina.widgets() or ():
                nombre = (widget.field_name or "").strip()
                tipo = widget.field_type_string or ""
                if (
                    nombre not in permitidos
                    or tipo not in TIPOS_RELLENABLES
                    or widget.field_flags & 1
                ):
                    continue

                valor = valores[nombre]
                if isinstance(valor, str) and not valor.strip():
                    continue

                if tipo == "CheckBox":
                    marcado = _a_booleano(valor)
                    if marcado is None:
                        continue
                    widget.field_value = widget.on_state() if marcado else "Off"
                elif tipo == "RadioButton":
                    opcion = widget.on_state()
                    if opcion is None or str(valor).casefold() != str(opcion).casefold():
                        continue
                    widget.field_value = opcion
                elif tipo in ("ComboBox", "ListBox"):
                    opciones = list(widget.choice_values or [])
                    coincidente = next(
                        (op for op in opciones if str(op).casefold() == str(valor).casefold()),
                        None,
                    )
                    if coincidente is None:
                        continue
                    widget.field_value = coincidente
                else:
                    if isinstance(valor, (dict, list, tuple)):
                        continue
                    texto = str(valor).strip()
                    maximo = widget.text_maxlen
                    if maximo and len(texto) > maximo:
                        continue
                    widget.field_value = texto

                widget.update()
                rellenados.add(nombre)

        if not rellenados:
            raise ValueError(
                "La IA no propuso valores válidos para los campos del PDF. "
                "El original sigue intacto."
            )

        _actualizar_datasets_xfa(documento, {nombre: valores[nombre] for nombre in rellenados})
        documento.save(str(destino), garbage=4, deflate=True)

    return sorted(rellenados)


def _actualizar_datasets_xfa(documento, valores):
    """Sincroniza los valores AcroForm con el dataset XML de formularios XFA."""
    catalogo = documento.pdf_catalog()
    tipo_acroform, acroform = documento.xref_get_key(catalogo, "AcroForm")
    if tipo_acroform != "xref":
        return

    xref_acroform = int(acroform.split()[0])
    tipo_xfa, xfa = documento.xref_get_key(xref_acroform, "XFA")
    if tipo_xfa != "array":
        return

    partes = dict(
        (nombre, int(xref))
        for nombre, xref in re.findall(r"\(([^)]+)\)\s*(\d+)\s+0\s+R", xfa)
    )
    xref_datasets = partes.get("datasets")
    if not xref_datasets:
        raise ValueError("El formulario XFA no contiene un dataset editable.")

    datos = documento.xref_stream(xref_datasets)
    if not datos:
        raise ValueError("No se pudo leer el dataset XFA del formulario.")

    try:
        raiz = ET.fromstring(datos)
    except ET.ParseError as e:
        raise ValueError("El dataset XFA del formulario no es XML válido.") from e

    for nombre, valor in valores.items():
        coincidencias = re.findall(r"(?:^|\.)([^.\[\]]+)(?:\[\d+\])?$", nombre)
        if not coincidencias:
            raise ValueError(f"No se pudo resolver el campo XFA: {nombre}")
        etiqueta = coincidencias[-1]
        nodos = [
            nodo
            for nodo in raiz.iter()
            if nodo.tag.split("}")[-1] == etiqueta
        ]
        if len(nodos) != 1:
            raise ValueError(
                f"El campo XFA '{etiqueta}' no es único; no se guardó el PDF."
            )
        nodos[0].text = str(valor)

    xml_actualizado = ET.tostring(raiz, encoding="utf-8", xml_declaration=True)
    documento.update_stream(xref_datasets, xml_actualizado, compress=True)


def _a_booleano(valor):
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, (int, float)) and valor in (0, 1):
        return bool(valor)

    texto = str(valor).strip().casefold()
    if texto in {"sí", "si", "true", "verdadero", "marcado", "seleccionado", "yes", "1"}:
        return True
    if texto in {"no", "false", "falso", "desmarcado", "off", "0"}:
        return False
    return None

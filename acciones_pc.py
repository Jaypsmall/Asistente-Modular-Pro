import os
import subprocess
import urllib.parse
import pyautogui

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.3

APPS_EXTRAS = {
    "calculadora": "calc",
    "paint": "mspaint",
    "cmd": "cmd",
    "terminal": "wt",
    "android studio": "studio64.exe",
}

def ejecutar_accion_pc(cmd):
    cmd_lower = cmd.lower().strip()
    
    # 1. Normalizar errores fonéticos comunes del reconocedor de voz
    cmd_lower = (cmd_lower.replace("quierra", "cierra")
                           .replace("sierra", "cierra")
                           .replace("tierra", "cierra"))

    # 2. Control de Pestañas y Navegador
    if "pestaña" in cmd_lower:
        if "primera" in cmd_lower:
            pyautogui.hotkey("ctrl", "1")
            return "Saltando a la primera pestaña."
        elif "segunda" in cmd_lower:
            pyautogui.hotkey("ctrl", "2")
            return "Saltando a la segunda pestaña."
        elif "tercera" in cmd_lower:
            pyautogui.hotkey("ctrl", "3")
            return "Saltando a la tercera pestaña."
        elif "última" in cmd_lower or "ultima" in cmd_lower:
            pyautogui.hotkey("ctrl", "9") # En la mayoría de navegadores salta a la última
            return "Saltando a la última pestaña."
        elif "nueva" in cmd_lower:
            pyautogui.hotkey("ctrl", "t")
            return "Abriendo nueva pestaña."
        elif "cierra" in cmd_lower or "cerrar" in cmd_lower:
            pyautogui.hotkey("ctrl", "w")
            return "Cerrando pestaña actual."
        else:
            # Alternar entre pestañas hacia adelante (Ctrl + Tab)
            pyautogui.hotkey("ctrl", "tab")
            return "Cambiando de pestaña."

    # 3. Acciones de Scroll (Desplazamiento)
    elif "scroll" in cmd_lower or "desplaza" in cmd_lower or "baja" in cmd_lower or "sube" in cmd_lower:
        if "arriba" in cmd_lower or "sube" in cmd_lower:
            pyautogui.scroll(500) # Valor positivo desplaza hacia arriba
            return "Desplazando hacia arriba."
        else:
            pyautogui.scroll(-500) # Valor negativo desplaza hacia abajo
            return "Desplazando hacia abajo."

    # 4. Manejo de Cierre / Apagado general
    elif any(k in cmd_lower for k in ["cierra", "cerrar", "apaga"]):
        if "navegador" in cmd_lower or "chrome" in cmd_lower or "google" in cmd_lower:
            os.system("taskkill /f /im chrome.exe")
            os.system("taskkill /f /im msedge.exe")
            os.system("taskkill /f /im firefox.exe")
            return "Navegador cerrado correctamente."
        else:
            pyautogui.hotkey("alt", "f4")
            return "Cerrando ventana activa (Alt+F4)."

    # 5. Búsqueda en web
    elif "busca" in cmd_lower:
        query = cmd_lower.split("busca", 1)[1].strip()
        url = f"https://www.google.com/search?q={urllib.parse.quote(query)}"
        subprocess.run(["start", url], shell=True)
        return f"Buscando en Google: {query}"
        
    # 6. Apertura de apps
    elif "abre" in cmd_lower:
        target = cmd_lower.split("abre", 1)[1].strip()
        if target in APPS_EXTRAS:
            subprocess.run(["start", APPS_EXTRAS[target]], shell=True)
        else:
            subprocess.run(["start", target], shell=True)
        return f"Abriendo: {target}"
        
    # 7. Pegar contenido
    elif "pega" in cmd_lower or "pegar" in cmd_lower:
        pyautogui.hotkey("ctrl", "v")
        return "Pegando contenido (Ctrl+V)"
        
    return f"Comando de PC no reconocido: '{cmd}'"
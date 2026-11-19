import queue
import threading
import pyttsx3

try:
    import pythoncom
except ImportError:
    pythoncom = None


class GestorVozAsync:

    def __init__(self, cliente_ollama, velocidad=140, callback_log=None):
        self.cliente = cliente_ollama
        self.velocidad = velocidad
        self.callback_log = callback_log

        self._cola_frases = queue.Queue()
        self._evento_stop = threading.Event()
        self._evento_cierre = threading.Event()
        self._hablando_actualmente = False
        self._hilo_generador = None
        self._motor_activo = None
        self._lock_motor = threading.Lock()

        self._hilo_tts = threading.Thread(
            target=self._worker_tts, name="WorkerTTS", daemon=True
        )
        self._hilo_tts.start()

    def _pronunciar_frase_sapi(self, texto):
        """Reutiliza un motor SAPI5 en este hilo para evitar reiniciarlo por frase."""
        motor = self._motor_activo
        if motor is None:
            motor = pyttsx3.init()
            motor.setProperty("rate", self.velocidad)
            for voz in motor.getProperty("voices"):
                if "spanish" in voz.name.lower() or "es" in voz.id.lower():
                    motor.setProperty("voice", voz.id)
                    break

            with self._lock_motor:
                self._motor_activo = motor

        if self._evento_stop.is_set():
            return

        motor.setProperty("rate", self.velocidad)
        motor.say(texto)
        motor.runAndWait()

    def _worker_tts(self):
        """Hilo consumidor secuencial con soporte COM para Windows."""
        if pythoncom:
            pythoncom.CoInitialize()

        try:
            while not self._evento_cierre.is_set():
                try:
                    item = self._cola_frases.get(timeout=0.15)
                except queue.Empty:
                    continue

                if item is None:
                    self._cola_frases.task_done()
                    break

                frase, es_ia = item

                if not self._evento_stop.is_set():
                    self._hablando_actualmente = True
                    try:
                        if es_ia and self.callback_log:
                            self.callback_log(f"🤖 IA Charla: {frase}")
                        self._pronunciar_frase_sapi(frase)
                    except Exception as e:
                        print(f"[Error TTS]: {e}")
                    finally:
                        self._hablando_actualmente = False

                self._cola_frases.task_done()
        finally:
            with self._lock_motor:
                motor = self._motor_activo
                self._motor_activo = None
            if motor:
                try:
                    motor.stop()
                except Exception:
                    pass
            if pythoncom:
                pythoncom.CoUninitialize()

    def _productor_ollama(self, texto_usuario):
        """Lee el stream de frases de Ollama y alimenta la cola en tiempo real."""
        try:
            for frase in self.cliente.consultar_charla_frases(texto_usuario):
                if self._evento_stop.is_set():
                    break
                self._cola_frases.put((frase, True))
        except Exception as e:
            if not self._evento_stop.is_set() and self.callback_log:
                self.callback_log(f"[Error Stream Charla]: {e}")

    def decir_directo(self, texto):
        """Encola un aviso corto del sistema sin pasar por Ollama."""
        self._evento_stop.clear()
        self._cola_frases.put((texto, False))

    def responder_charla(self, texto_usuario):
        """Inicia respuesta conversacional en streaming."""
        self.interrumpir()
        self._evento_stop.clear()

        self._hilo_generador = threading.Thread(
            target=self._productor_ollama,
            args=(texto_usuario,),
            name="ProductorOllama",
            daemon=True,
        )
        self._hilo_generador.start()

    def interrumpir(self):
        """Corta el stream de Ollama, vacía la cola y detiene el motor activo."""
        self._evento_stop.set()

        while not self._cola_frases.empty():
            try:
                self._cola_frases.get_nowait()
                self._cola_frases.task_done()
            except queue.Empty:
                break

        with self._lock_motor:
            if self._motor_activo:
                try:
                    self._motor_activo.stop()
                except Exception:
                    pass

        if self._hilo_generador and self._hilo_generador.is_alive():
            self._hilo_generador.join(timeout=0.5)

    def esta_hablando(self):
        """Devuelve True si está generando, hay frases en cola o está hablando ahora mismo."""
        generando = (
            self._hilo_generador is not None and self._hilo_generador.is_alive()
        )
        return (
            generando
            or self._hablando_actualmente
            or not self._cola_frases.empty()
        )

    def apagar(self):
        """Cierre limpio al cerrar la ventana principal."""
        self.interrumpir()
        self._evento_cierre.set()
        self._cola_frases.put(None)
        self._hilo_tts.join(timeout=1.0)

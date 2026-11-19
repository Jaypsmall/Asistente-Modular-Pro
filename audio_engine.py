import os
import threading

import numpy as np
import sounddevice as sd

# Silencia los avisos informativos de Hugging Face Hub
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"


class MotorAudio:

    def __init__(self, modelo="small", dispositivo="auto"):
        self.sample_rate = 16000
        self.nombre_modelo = modelo
        self.dispositivo = dispositivo
        self.modelo = None
        self._lock_modelo = threading.Lock()
        tipo_computo = "float16" if dispositivo == "cuda" else "int8"
        self.tipo_computo = tipo_computo

        self.prompt_tecnico = (
            "Programación en español con términos técnicos en inglés: "
            "Kotlin, Java, Jetpack Compose, Android SDK, NDK, Flutter, Dart, Rust, Cargo, JNI, Python, "
            "HexRootScan, HexRootFuzz, HexColor, Daltonic Assist Pro, DemoniTalk, CyberVarilla, "
            "Ollama, Qwen, JSON, API, socket, coroutine, thread, refactorizar, portapapeles."
        )

    @property
    def modelo_cargado(self):
        return self.modelo is not None

    def preparar(self):
        """Carga Faster-Whisper para que la primera orden no tenga esa espera."""
        return self._obtener_modelo()

    def _obtener_modelo(self):
        """Carga el modelo cuando empieza la escucha, sin retrasar la ventana."""
        if self.modelo is not None:
            return self.modelo

        with self._lock_modelo:
            if self.modelo is not None:
                return self.modelo

            from faster_whisper import WhisperModel

            print(f"[Audio] Cargando Faster-Whisper ({self.nombre_modelo})...")
            try:
                self.modelo = WhisperModel(
                    self.nombre_modelo,
                    device=self.dispositivo,
                    compute_type=self.tipo_computo,
                    local_files_only=True,
                )
            except Exception:
                # Si falta la caché, Faster-Whisper obtiene el modelo la primera vez.
                self.modelo = WhisperModel(
                    self.nombre_modelo,
                    device=self.dispositivo,
                    compute_type=self.tipo_computo,
                    local_files_only=False,
                )

            print("[Audio] Faster-Whisper listo.")
            return self.modelo

    def escuchar_frase(self, duracion=9):
        """
        Graba audio del micrófono con detección automática de silencio (no espera los 9s si ya callaste)
        y lo transcribe con alta precisión técnica.
        """
        bloque_ms = 100  # Analiza cada 0.1 segundos
        samples_por_bloque = int(self.sample_rate * (bloque_ms / 1000.0))
        max_bloques = int((duracion * 1000) / bloque_ms)

        umbral_energia = 0.012  # Sensibilidad de voz (sube a 0.02 si hay mucho ruido de fondo)
        bloques_silencio_para_cortar = 14  # 1.4 segundos de silencio tras hablar corta la grabación

        audio_grabado = []
        hablando = False
        contador_silencio = 0

        with sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            blocksize=samples_por_bloque,
        ) as stream:
            for _ in range(max_bloques):
                datos, _ = stream.read(samples_por_bloque)
                chunk = datos.flatten()
                energia = np.sqrt(np.mean(chunk**2))

                if energia > umbral_energia:
                    hablando = True
                    contador_silencio = 0
                    audio_grabado.append(chunk)
                elif hablando:
                    audio_grabado.append(chunk)
                    contador_silencio += 1
                    if contador_silencio >= bloques_silencio_para_cortar:
                        # El usuario ya terminó la frase, cortamos sin esperar los 9 segundos enteros
                        break

        if not audio_grabado:
            return ""

        audio_np = np.concatenate(audio_grabado)

        # Transcripción con filtro VAD interno para eliminar alucinaciones en silencios
        modelo = self._obtener_modelo()
        segmentos, _ = modelo.transcribe(
            audio_np,
            language="es",
            beam_size=3,
            initial_prompt=self.prompt_tecnico,
            condition_on_previous_text=False,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
        )

        texto_final = " ".join(seg.text.strip() for seg in segmentos).strip()
        return texto_final

import io
import json
import os
import re
import subprocess
import time
import wave
from typing import Callable

from live_translator.config import CONFIG
from live_translator.flow_logger import flow_log


class PiperTTSEngine:
    def __init__(
        self,
        model_path: str,
        piper_binary: str,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        self.model_path = model_path
        self.piper_binary = piper_binary
        self.on_error = on_error
        self.sample_rate = self._load_model_sample_rate(default=22050)

    def _emit_error(self, message: str) -> None:
        if self.on_error is not None:
            self.on_error(message)

    def _load_model_sample_rate(self, default: int) -> int:
        metadata_path = f"{self.model_path}.json"
        if not os.path.isfile(metadata_path):
            return default

        try:
            with open(metadata_path, "r", encoding="utf-8") as file:
                metadata = json.load(file)
            return int(metadata.get("audio", {}).get("sample_rate", default))
        except Exception as exc:
            self._emit_error(f"Failed to read Piper metadata: {exc}")
            return default

    def _normalize_phrase(self, text: str) -> str:
        phrase = re.sub(r"\s+", " ", text.strip())
        if not phrase:
            return ""
        phrase = re.sub(r"<[^>]+>", " ", phrase)
        phrase = re.sub(r"\[[^\]]*\]|\([^\)]*\)", " ", phrase)
        phrase = re.sub(r"\b(\w+)(?:\s+\1){2,}\b", r"\1", phrase, flags=re.IGNORECASE)
        phrase = re.sub(r"\s+", " ", phrase).strip()
        return phrase

    def synthesize(self, text: str) -> bytes | None:
        phrase = self._normalize_phrase(text)
        if not phrase:
            return None
        if phrase[-1] not in ".!?":
            phrase = f"{phrase}."

        command = [
            self.piper_binary,
            "--model",
            self.model_path,
            "--output_raw",
            "--speaker",
            str(max(0, CONFIG.PIPER_SPEAKER_ID)),
            "--noise_scale",
            f"{max(0.0, CONFIG.PIPER_NOISE_SCALE):.3f}",
            "--length_scale",
            f"{max(0.6, CONFIG.PIPER_LENGTH_SCALE):.3f}",
            "--noise_w",
            f"{max(0.0, CONFIG.PIPER_NOISE_W):.3f}",
            "--sentence_silence",
            f"{max(0.0, CONFIG.PIPER_SENTENCE_SILENCE):.3f}",
        ]

        creationflags = 0
        startupinfo = None
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0

        started = time.perf_counter()
        try:
            result = subprocess.run(
                command,
                input=phrase.encode("utf-8"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=12,
                creationflags=creationflags,
                startupinfo=startupinfo,
            )
        except subprocess.TimeoutExpired:
            self._emit_error("Piper process timeout.")
            return None
        except Exception as exc:
            self._emit_error(f"Piper process failure: {exc}")
            return None

        if result.returncode != 0:
            stderr_text = result.stderr.decode("utf-8", errors="ignore").strip()
            self._emit_error(f"Piper process failure: {stderr_text or 'unknown error'}")
            return None

        raw_pcm = result.stdout
        if not raw_pcm:
            self._emit_error("Piper produced empty audio.")
            return None

        if len(raw_pcm) % 2 != 0:
            raw_pcm = raw_pcm[:-1]

        if len(raw_pcm) < 2:
            self._emit_error("Piper produced invalid audio.")
            return None

        frames = len(raw_pcm) // 2
        duration_sec = frames / float(self.sample_rate) if self.sample_rate > 0 else 0.0
        max_duration = max(CONFIG.TTS_MAX_AUDIO_SEC, len(phrase) * CONFIG.TTS_MAX_SEC_PER_CHAR)
        trimmed = False
        if duration_sec > max_duration and self.sample_rate > 0:
            max_frames = max(1, int(max_duration * self.sample_rate))
            raw_pcm = raw_pcm[: max_frames * 2]
            duration_sec = max_duration
            trimmed = True
            flow_log(
                "tts",
                "synthesize_trimmed_long_audio",
                original_duration=f"{frames / float(self.sample_rate):.2f}s",
                trimmed_duration=f"{duration_sec:.2f}s",
                chars=len(phrase),
            )

        with io.BytesIO() as wav_buffer:
            with wave.open(wav_buffer, "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(self.sample_rate)
                wav_file.writeframes(raw_pcm)
            wav_bytes = wav_buffer.getvalue()

            elapsed = time.perf_counter() - started
            flow_log(
                "tts",
                "synthesize_done",
                elapsed=f"{elapsed:.3f}s",
                chars=len(phrase),
                bytes=len(wav_bytes),
                duration=f"{duration_sec:.2f}s",
                trimmed=trimmed,
            )
            return wav_bytes

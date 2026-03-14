import queue
import re
import threading
import time
from typing import Callable

import numpy as np
from deepgram import DeepgramClient
from deepgram.core.events import EventType

from live_translator.config import CONFIG
from live_translator.flow_logger import flow_log


class DeepgramStreamingEngine:
    def __init__(
        self,
        api_key_getter: Callable[[], str],
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        self._api_key_getter = api_key_getter
        self.on_error = on_error
        self._connected_event = threading.Event()
        self._last_error: str = ""
        self._last_error_at: float = 0.0
        self._last_final_text: str = ""
        self._last_final_at: float = 0.0
        self._last_emitted_text: str = ""
        self._last_emitted_at: float = 0.0

    @property
    def is_connected(self) -> bool:
        return self._connected_event.is_set()

    def _emit_error(self, message: str) -> None:
        now = time.monotonic()
        if message == self._last_error and (now - self._last_error_at) < 2.0:
            return
        self._last_error = message
        self._last_error_at = now
        if self.on_error is not None:
            self.on_error(message)

    def _to_linear16_bytes(self, audio_chunk: np.ndarray) -> bytes:
        samples = np.asarray(audio_chunk, dtype=np.float32).reshape(-1)
        if samples.size <= 0:
            return b""
        peak = float(np.max(np.abs(samples)))
        target = float(CONFIG.STT_AUTO_GAIN_TARGET_PEAK)
        if peak > 1e-4 and target > 0:
            gain = min(float(CONFIG.STT_AUTO_GAIN_MAX), target / peak)
            if gain > 1.01:
                samples = samples * gain
        samples = np.clip(samples, -1.0, 1.0)
        return (samples * 32767.0).astype(np.int16, copy=False).tobytes()

    def _extract_stream_transcript(self, message: object) -> tuple[str, float, str]:
        if str(getattr(message, "type", "")) != "Results":
            return "", 0.0, ""

        is_final = bool(getattr(message, "is_final", False))
        speech_final = bool(getattr(message, "speech_final", False))

        channel = getattr(message, "channel", None)
        alternatives = getattr(channel, "alternatives", None) if channel is not None else None
        if not alternatives:
            return "", 0.0, ""

        transcript = str(getattr(alternatives[0], "transcript", "") or "").strip()
        confidence = float(getattr(alternatives[0], "confidence", 0.0) or 0.0)
        if not transcript:
            return "", confidence, ""
        if is_final:
            emit_kind = "final"
        elif speech_final:
            emit_kind = "speech_final"
        else:
            words = re.findall(r"\w+", transcript, flags=re.UNICODE)
            if not bool(CONFIG.DEEPGRAM_INTERIM_RESULTS):
                return "", confidence, ""
            min_words = int(CONFIG.DEEPGRAM_INTERIM_MIN_WORDS)
            if len(words) < min_words:
                return "", confidence, ""
            # Avoid flooding pipeline with unstable partials that create repeated audio.
            if not transcript.endswith((".", "!", "?", "...")) and len(words) < (min_words + 4):
                return "", confidence, ""
            emit_kind = "interim"
        return re.sub(r"\s+", " ", transcript), confidence, emit_kind

    def _allow_emit(self, normalized: str, emit_kind: str) -> bool:
        now = time.monotonic()
        if emit_kind == "interim":
            if (now - self._last_emitted_at) < float(CONFIG.DEEPGRAM_INTERIM_THROTTLE_SEC):
                return False
            if self._last_emitted_text:
                if normalized == self._last_emitted_text:
                    return False
                if normalized in self._last_emitted_text:
                    return False
                if normalized.startswith(self._last_emitted_text):
                    growth = len(normalized) - len(self._last_emitted_text)
                    if growth < int(CONFIG.DEEPGRAM_INTERIM_MIN_GROWTH_CHARS):
                        return False
                growth = max(0, len(normalized) - len(self._last_emitted_text))
                curr_tokens = {token for token in normalized.split(" ") if token}
                prev_tokens = {token for token in self._last_emitted_text.split(" ") if token}
                if curr_tokens and prev_tokens:
                    overlap = len(curr_tokens & prev_tokens) / max(1, len(curr_tokens))
                    if (
                        overlap >= 0.90
                        and growth < int(CONFIG.DEEPGRAM_INTERIM_MIN_GROWTH_CHARS)
                        and not normalized.endswith((".", "!", "?"))
                    ):
                        return False
        else:
            if normalized == self._last_final_text and (
                now - self._last_final_at
            ) <= CONFIG.STT_FINAL_DEDUP_SEC:
                return False
            self._last_final_text = normalized
            self._last_final_at = now

        self._last_emitted_text = normalized
        self._last_emitted_at = now
        return True

    def _flush_audio_queue(self, audio_queue: queue.Queue, keep: int = 0) -> int:
        dropped = 0
        keep_items = max(0, int(keep))
        while audio_queue.qsize() > keep_items:
            try:
                audio_queue.get_nowait()
                dropped += 1
            except queue.Empty:
                break
        return dropped

    def run(
        self,
        stop_event: threading.Event,
        audio_queue: queue.Queue,
        on_final_transcript: Callable[[str, float | None], None],
    ) -> None:
        backoff_sec = 1.0

        while not stop_event.is_set():
            api_key = self._api_key_getter().strip()
            if not api_key:
                self._connected_event.clear()
                self._emit_error("Deepgram API key missing. Configure DEEPGRAM_API_KEY in CONFIG.")
                stop_event.wait(1.0)
                continue

            listener_error: dict[str, Exception | None] = {"exc": None}

            try:
                dropped = self._flush_audio_queue(audio_queue, keep=1)
                if dropped:
                    flow_log("deepgram", "preconnect_queue_flush", dropped=dropped, kept=audio_queue.qsize())
                flow_log(
                    "deepgram",
                    "connect_attempt",
                    model=CONFIG.DEEPGRAM_MODEL,
                    language=CONFIG.DEEPGRAM_LANGUAGE,
                    sample_rate=CONFIG.SAMPLE_RATE,
                    channels=CONFIG.CHANNELS,
                )
                client = DeepgramClient(api_key=api_key)
                with client.listen.v1.connect(
                    model=CONFIG.DEEPGRAM_MODEL,
                    language=CONFIG.DEEPGRAM_LANGUAGE,
                    punctuate=str(bool(CONFIG.DEEPGRAM_PUNCTUATE)).lower(),
                    interim_results=str(bool(CONFIG.DEEPGRAM_INTERIM_RESULTS)).lower(),
                    smart_format=str(bool(CONFIG.DEEPGRAM_SMART_FORMAT)).lower(),
                    encoding=CONFIG.DEEPGRAM_ENCODING,
                    sample_rate=str(CONFIG.SAMPLE_RATE),
                    channels=str(CONFIG.CHANNELS),
                    endpointing=str(max(0, int(CONFIG.DEEPGRAM_ENDPOINTING_MS))),
                    utterance_end_ms=str(max(0, int(CONFIG.DEEPGRAM_UTTERANCE_END_MS))),
                ) as connection:
                    self._connected_event.set()
                    backoff_sec = 1.0
                    flow_log("deepgram", "connected")

                    def _on_message(message: object) -> None:
                        try:
                            started = time.perf_counter()
                            transcript, confidence, emit_kind = self._extract_stream_transcript(message)
                            if not transcript:
                                return

                            words = re.findall(r"\w+", transcript, flags=re.UNICODE)
                            if confidence > 0 and confidence < CONFIG.DEEPGRAM_MIN_CONFIDENCE and len(words) <= 4:
                                flow_log(
                                    "deepgram",
                                    "final_dropped_low_confidence",
                                    confidence=f"{confidence:.3f}",
                                    words=len(words),
                                )
                                return

                            normalized = transcript.lower()
                            if not self._allow_emit(normalized, emit_kind):
                                return

                            elapsed = time.perf_counter() - started
                            on_final_transcript(transcript, elapsed)
                            flow_log(
                                "deepgram",
                                "transcript_emitted",
                                kind=emit_kind,
                                confidence=f"{confidence:.3f}",
                                chars=len(transcript),
                            )
                        except Exception as exc:  # pragma: no cover - safety
                            listener_error["exc"] = exc

                    def _on_error(exc: Exception) -> None:
                        listener_error["exc"] = exc

                    connection.on(EventType.MESSAGE, _on_message)
                    connection.on(EventType.ERROR, _on_error)

                    listener_thread = threading.Thread(
                        target=connection.start_listening,
                        name="deepgram_listener_thread",
                        daemon=True,
                    )
                    listener_thread.start()

                    last_keep_alive_at = time.monotonic()
                    while not stop_event.is_set():
                        if listener_error["exc"] is not None:
                            raise RuntimeError(f"Deepgram listener error: {listener_error['exc']}")

                        try:
                            audio_chunk = audio_queue.get(timeout=0.20)
                        except queue.Empty:
                            now = time.monotonic()
                            if now - last_keep_alive_at >= 4.0:
                                connection.send_keep_alive()
                                last_keep_alive_at = now
                            continue

                        if audio_queue.qsize() >= CONFIG.AUDIO_BACKLOG_TRIM_THRESHOLD:
                            dropped = self._flush_audio_queue(audio_queue, keep=CONFIG.AUDIO_BACKLOG_KEEP_CHUNKS)
                            if dropped:
                                flow_log(
                                    "deepgram",
                                    "audio_backlog_trim",
                                    dropped=dropped,
                                    kept=audio_queue.qsize(),
                                )

                        payload = self._to_linear16_bytes(audio_chunk)
                        if payload:
                            connection.send_media(payload)
                            last_keep_alive_at = time.monotonic()

                    try:
                        connection.send_finalize()
                    except Exception:
                        pass
                    try:
                        connection.send_close_stream()
                    except Exception:
                        pass
                    listener_thread.join(timeout=1.5)

                self._connected_event.clear()
                flow_log("deepgram", "disconnected")

            except Exception as exc:
                self._connected_event.clear()
                flow_log("deepgram", "connection_failure", error=exc, backoff=f"{backoff_sec:.1f}s")
                self._emit_error(f"Deepgram connection failure: {exc}")
                if stop_event.wait(backoff_sec):
                    break
                backoff_sec = min(CONFIG.DEEPGRAM_RECONNECT_MAX_SEC, backoff_sec * 2.0)

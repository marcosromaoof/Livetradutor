import queue
import re
import threading
import time
from typing import Any, Callable

from live_translator.audio_capture import SystemAudioCapture
from live_translator.audio_player import AudioPlayer
from live_translator.config import CONFIG
from live_translator.deepgram_engine import DeepgramStreamingEngine
from live_translator.flow_logger import flow_log
from live_translator.queue_utils import clear_queue, put_with_drop
from live_translator.runtime_settings import RuntimeSettings
from live_translator.trace_logs import log_ai_trace, log_stt_trace
from live_translator.translator import build_translator, contains_prompt_leak
from live_translator.tts_engine import PiperTTSEngine


class LiveTranslatorPipeline:
    def __init__(
        self,
        runtime_settings: RuntimeSettings,
        on_status: Callable[[str], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        self.on_status = on_status
        self.on_error = on_error
        self.runtime_settings = runtime_settings

        self.audio_queue: queue.Queue = queue.Queue(maxsize=CONFIG.QUEUE_MAXSIZE)
        self.text_queue: queue.Queue = queue.Queue(maxsize=CONFIG.QUEUE_MAXSIZE)
        self.translated_queue: queue.Queue = queue.Queue(maxsize=CONFIG.QUEUE_MAXSIZE)
        self.speech_queue: queue.Queue = queue.Queue(maxsize=CONFIG.QUEUE_MAXSIZE)
        self.playback_ack_queue: queue.Queue = queue.Queue(maxsize=max(8, CONFIG.QUEUE_MAXSIZE * 2))

        self.stop_event = threading.Event()
        self.playback_guard_event = threading.Event()
        self._lock = threading.Lock()
        self._translator_lock = threading.Lock()
        self._echo_lock = threading.Lock()
        self._running = False

        self.capture = SystemAudioCapture(on_error=self._handle_error)
        self.stt = DeepgramStreamingEngine(
            api_key_getter=self._get_deepgram_api_key,
            on_error=self._handle_error,
        )
        self.translator: Any = build_translator(
            self.runtime_settings,
            on_error=self._handle_error,
        )
        self.tts = PiperTTSEngine(
            model_path=CONFIG.PIPER_MODEL_PATH,
            piper_binary=CONFIG.PIPER_BINARY,
            on_error=self._handle_error,
        )
        self.player = AudioPlayer(on_error=self._handle_error)

        self.threads: dict[str, threading.Thread] = {}
        self._recent_tts_texts: list[tuple[float, str, set[str]]] = []
        self._recent_tts_spoken: list[tuple[float, str, set[str]]] = []
        self._pending_source_text: str = ""
        self._pending_source_started_at: float = 0.0
        self._last_source_sent: str = ""
        self._last_source_sent_at: float = 0.0
        self._recent_source_sent: list[tuple[float, str, set[str]]] = []
        self._last_translated_sent: str = ""
        self._last_translated_sent_at: float = 0.0
        self._recent_translated_sent: list[tuple[float, str, set[str]]] = []
        self._last_tts_spoken: str = ""
        self._last_tts_spoken_at: float = 0.0
        self._tts_repeat_streak: int = 0
        self._pending_tts_text: str = ""
        self._pending_tts_started_at: float = 0.0
        self._speech_seq: int = 0
        self._last_stt_text: str = ""
        self._last_stt_text_at: float = 0.0
        self._trace_session_id: str = ""
        self._trace_stt_seq: int = 0
        self._trace_ai_seq: int = 0
        self._monitor_last_log: float = time.monotonic()

    @property
    def is_running(self) -> bool:
        return self._running

    def _emit_status(self, status: str) -> None:
        if self.on_status is not None:
            self.on_status(status)

    def _handle_error(self, message: str) -> None:
        flow_log("pipeline", "error", message=message)
        if self.on_error is not None:
            self.on_error(message)

    def _get_deepgram_api_key(self) -> str:
        runtime_key = self.runtime_settings.deepgram_api_key.strip()
        if runtime_key:
            return runtime_key
        return CONFIG.DEEPGRAM_API_KEY.strip()

    def update_runtime_settings(self, runtime_settings: RuntimeSettings) -> None:
        with self._translator_lock:
            self.runtime_settings = runtime_settings
            self.translator = build_translator(
                self.runtime_settings,
                on_error=self._handle_error,
            )
        flow_log(
            "pipeline",
            "settings_updated",
            provider=runtime_settings.normalized_provider(),
            fallback=runtime_settings.fallback_enabled,
        )

    def _start_thread(self, name: str, target: Callable[[], None]) -> None:
        thread = threading.Thread(target=target, name=name, daemon=True)
        thread.start()
        self.threads[name] = thread
        flow_log("pipeline", "thread_started", name=name)

    def start(self) -> None:
        with self._lock:
            if self._running:
                return

            self.stop_event.clear()
            clear_queue(self.playback_ack_queue)
            self._speech_seq = 0
            self._last_stt_text = ""
            self._last_stt_text_at = 0.0
            self._trace_session_id = str(int(time.time() * 1000))
            self._trace_stt_seq = 0
            self._trace_ai_seq = 0
            suppress_event = self.playback_guard_event if CONFIG.ENABLE_PLAYBACK_CAPTURE_SUPPRESSION else None
            flow_log(
                "pipeline",
                "start",
                stt_engine="deepgram",
                deepgram_model=CONFIG.DEEPGRAM_MODEL,
                deepgram_language=CONFIG.DEEPGRAM_LANGUAGE,
                deepgram_interim=CONFIG.DEEPGRAM_INTERIM_RESULTS,
                chunk_sec=CONFIG.CHUNK_DURATION_SEC,
                provider=self.runtime_settings.normalized_provider(),
                fallback=self.runtime_settings.fallback_enabled,
                capture_suppression=CONFIG.ENABLE_PLAYBACK_CAPTURE_SUPPRESSION,
                trace_session=self._trace_session_id,
            )

            self._start_thread(
                "audio_capture_thread",
                lambda: self.capture.run(
                    self.stop_event,
                    self.audio_queue,
                    suppress_capture_event=suppress_event,
                ),
            )
            self._start_thread("deepgram_thread", self._deepgram_worker)
            self._start_thread("translation_thread", self._translation_worker)
            self._start_thread("tts_thread", self._tts_worker)
            self._start_thread("monitor_thread", self._monitor_worker)
            self._start_thread(
                "playback_thread",
                lambda: self.player.run(
                    self.stop_event,
                    self.speech_queue,
                    playback_guard_event=suppress_event,
                    ack_queue=self.playback_ack_queue,
                ),
            )

            self._running = True
            self._emit_status("Running")

    def stop(self) -> None:
        with self._lock:
            if not self._running:
                self._emit_status("Stopped")
                return

            flow_log("pipeline", "stop_requested")
            self.stop_event.set()
            self.playback_guard_event.clear()
            self.player.stop()

            for thread in self.threads.values():
                thread.join(timeout=3.0)
            self.threads.clear()

            clear_queue(self.audio_queue)
            clear_queue(self.text_queue)
            clear_queue(self.translated_queue)
            clear_queue(self.speech_queue)
            clear_queue(self.playback_ack_queue)
            with self._echo_lock:
                self._recent_tts_texts.clear()
            self._recent_tts_spoken.clear()
            self._pending_source_text = ""
            self._pending_source_started_at = 0.0
            self._last_source_sent = ""
            self._last_source_sent_at = 0.0
            self._recent_source_sent.clear()
            self._last_translated_sent = ""
            self._last_translated_sent_at = 0.0
            self._recent_translated_sent.clear()
            self._last_tts_spoken = ""
            self._last_tts_spoken_at = 0.0
            self._tts_repeat_streak = 0
            self._pending_tts_text = ""
            self._pending_tts_started_at = 0.0
            self._speech_seq = 0
            self._last_stt_text = ""
            self._last_stt_text_at = 0.0
            self._trace_session_id = ""
            self._trace_stt_seq = 0
            self._trace_ai_seq = 0
            self._monitor_last_log = time.monotonic()

            self._running = False
            self._emit_status("Stopped")
            flow_log("pipeline", "stopped")

    def _normalize_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", text.strip().lower())

    def _normalize_loose(self, text: str) -> str:
        return " ".join(re.findall(r"\w+", text.lower(), flags=re.UNICODE))

    def _tokenize(self, text: str) -> set[str]:
        return {token for token in re.findall(r"\w+", text.lower(), flags=re.UNICODE) if len(token) >= 2}

    def _token_overlap_ratio(self, left: str, right: str) -> float:
        left_tokens = self._tokenize(left)
        right_tokens = self._tokenize(right)
        if not left_tokens or not right_tokens:
            return 0.0
        inter = len(left_tokens & right_tokens)
        base = max(len(left_tokens), len(right_tokens))
        return inter / max(1, base)

    def _word_count(self, text: str) -> int:
        return len(re.findall(r"\w+", text, flags=re.UNICODE))

    def _is_recently_similar(
        self,
        normalized: str,
        recent_items: list[tuple[float, str, set[str]]],
        *,
        threshold: float,
        window_sec: float,
    ) -> bool:
        if not normalized:
            return False
        now = time.monotonic()
        cutoff = now - window_sec
        tokens = self._tokenize(normalized)
        kept: list[tuple[float, str, set[str]]] = []
        similar = False
        for ts, text, text_tokens in recent_items:
            if ts < cutoff:
                continue
            kept.append((ts, text, text_tokens))
            if normalized == text:
                similar = True
                continue
            if not tokens or not text_tokens:
                continue
            overlap = len(tokens & text_tokens) / max(len(tokens), len(text_tokens))
            if overlap >= threshold:
                similar = True
        recent_items[:] = kept
        return similar

    def _remember_recent(
        self,
        normalized: str,
        recent_items: list[tuple[float, str, set[str]]],
        *,
        window_sec: float,
        max_items: int = 16,
    ) -> None:
        if not normalized:
            return
        now = time.monotonic()
        cutoff = now - max(1.0, window_sec)
        tokens = self._tokenize(normalized)
        kept: list[tuple[float, str, set[str]]] = []
        for ts, text, text_tokens in recent_items:
            if ts < cutoff:
                continue
            kept.append((ts, text, text_tokens))
        kept.append((now, normalized, tokens))
        if len(kept) > max_items:
            kept = kept[-max_items:]
        recent_items[:] = kept

    def _max_suffix_prefix_overlap_words(self, left_text: str, right_text: str, max_words: int = 24) -> int:
        left_words = re.findall(r"\w+", left_text.lower(), flags=re.UNICODE)
        right_words = re.findall(r"\w+", right_text.lower(), flags=re.UNICODE)
        if not left_words or not right_words:
            return 0
        max_k = min(max_words, len(left_words), len(right_words))
        for k in range(max_k, 0, -1):
            if left_words[-k:] == right_words[:k]:
                return k
        return 0

    def _append_with_overlap(self, base_text: str, incoming_text: str, *, min_overlap_words: int = 3) -> str:
        base = base_text.strip()
        incoming = incoming_text.strip()
        if not base:
            return incoming
        if not incoming:
            return base

        base_norm = self._normalize_text(base)
        incoming_norm = self._normalize_text(incoming)
        if incoming_norm.startswith(base_norm):
            return incoming
        if base_norm.startswith(incoming_norm):
            return base
        if incoming_norm in base_norm:
            return base
        if base_norm in incoming_norm:
            return incoming

        overlap_words = self._max_suffix_prefix_overlap_words(base, incoming)
        if overlap_words >= min_overlap_words:
            incoming_words = incoming.split()
            if overlap_words < len(incoming_words):
                tail = " ".join(incoming_words[overlap_words:]).strip()
                if tail:
                    return f"{base} {tail}".strip()
            return base

        if not base_norm.endswith(incoming_norm):
            return f"{base} {incoming}".strip()
        return base

    def _is_gpu_active(self) -> bool:
        return False

    def _aggressive_mode(self) -> bool:
        return bool(CONFIG.AGGRESSIVE_CONTINUOUS_MODE)

    def _runtime_batch_window_sec(self) -> float:
        value = float(CONFIG.TEXT_BATCH_WINDOW_SEC)
        if self._aggressive_mode():
            return min(value, 0.25)
        return value

    def _runtime_batch_max_items(self) -> int:
        value = int(CONFIG.TEXT_BATCH_MAX_ITEMS)
        if self._aggressive_mode():
            return 1
        return value

    def _runtime_min_source_chars(self) -> int:
        value = int(CONFIG.MIN_SOURCE_TEXT_CHARS)
        if self._aggressive_mode():
            return max(6, min(value, 8))
        return value

    def _runtime_min_source_words(self) -> int:
        value = int(CONFIG.MIN_SOURCE_TEXT_WORDS)
        if self._aggressive_mode():
            return max(2, min(value, 2))
        return value

    def _runtime_source_accum_max_sec(self) -> float:
        value = float(CONFIG.SOURCE_ACCUM_MAX_SEC)
        if self._aggressive_mode():
            return min(value, 0.55)
        return value

    def _runtime_tts_batch_window_sec(self) -> float:
        value = float(CONFIG.TTS_BATCH_WINDOW_SEC)
        if self._aggressive_mode():
            return max(0.12, min(value, 0.22))
        return value

    def _runtime_tts_batch_max_items(self) -> int:
        value = int(CONFIG.TTS_BATCH_MAX_ITEMS)
        if self._aggressive_mode():
            return max(1, min(value, 2))
        return value

    def _runtime_tts_buffer_min_chars(self) -> int:
        value = int(CONFIG.TTS_BUFFER_MIN_CHARS)
        if self._aggressive_mode():
            return max(14, min(value, 18))
        return value

    def _runtime_tts_buffer_max_age_sec(self) -> float:
        value = float(CONFIG.TTS_BUFFER_MAX_AGE_SEC)
        if self._aggressive_mode():
            return min(value, 0.75)
        return value

    def _runtime_repeat_source_cooldown_sec(self) -> float:
        value = float(CONFIG.REPEAT_SOURCE_COOLDOWN_SEC)
        if self._aggressive_mode():
            return max(2.0, min(value, 2.8))
        return value

    def _runtime_source_repeat_overlap_threshold(self) -> float:
        if self._aggressive_mode():
            return 0.94
        return 0.88

    def _runtime_translated_repeat_overlap_threshold(self) -> float:
        if self._aggressive_mode():
            return 0.96
        return 0.92

    def _has_meaningful_source(self, text: str) -> bool:
        probe = text.strip()
        if not probe:
            return False
        compact = re.sub(r"\s+", "", probe)
        min_chars = self._runtime_min_source_chars()
        if len(compact) < min_chars:
            return False
        spaced_words = [w for w in re.split(r"\s+", probe) if w]
        if len(spaced_words) >= 2:
            word_tokens = re.findall(r"\w+", probe, flags=re.UNICODE)
            longish_words = [w for w in word_tokens if len(w) >= 2]
            if len(longish_words) < self._runtime_min_source_words():
                return False
        return True

    def _is_tiny_fragment(self, text: str) -> bool:
        probe = text.strip()
        if not probe:
            return True
        compact = re.sub(r"\s+", "", probe)
        if len(compact) <= 1:
            return True
        if compact.isascii() and len(compact) <= 3:
            return True
        return False

    def _monitor_worker(self) -> None:
        while not self.stop_event.wait(0.5):
            now = time.monotonic()
            if now - self._monitor_last_log < CONFIG.FLOW_LOG_INTERVAL_SEC:
                continue
            flow_log(
                "pipeline",
                "queues",
                audio_q=self.audio_queue.qsize(),
                text_q=self.text_queue.qsize(),
                translated_q=self.translated_queue.qsize(),
                speech_q=self.speech_queue.qsize(),
                ack_q=self.playback_ack_queue.qsize(),
                stt_connected=self.stt.is_connected,
            )
            self._monitor_last_log = now

    def _remember_tts_text(self, translated_text: str) -> None:
        normalized = self._normalize_text(translated_text)
        if not normalized:
            return
        tokens = self._tokenize(normalized)
        now = time.monotonic()
        cutoff = now - CONFIG.ECHO_MEMORY_SEC
        with self._echo_lock:
            self._recent_tts_texts.append((now, normalized, tokens))
            self._recent_tts_texts = [item for item in self._recent_tts_texts if item[0] >= cutoff]

    def _is_probable_tts_echo(self, source_text: str) -> bool:
        normalized = self._normalize_text(source_text)
        if not normalized:
            return False
        source_tokens = self._tokenize(normalized)
        if not source_tokens:
            return False

        now = time.monotonic()
        cutoff = now - CONFIG.ECHO_MEMORY_SEC
        with self._echo_lock:
            recent = [item for item in self._recent_tts_texts if item[0] >= cutoff]
            self._recent_tts_texts = recent

        for _, tts_text, tts_tokens in recent:
            if normalized == tts_text:
                return True
            if not tts_tokens:
                continue
            overlap = len(source_tokens & tts_tokens) / max(len(source_tokens), len(tts_tokens))
            if overlap >= CONFIG.ECHO_OVERLAP_THRESHOLD:
                return True
        return False

    def _collect_text_batch(self, first_text: str) -> str:
        pieces: list[str] = []
        first_piece = first_text.strip()
        if first_piece:
            pieces.append(first_piece)
        started = time.monotonic()
        batch_max_items = self._runtime_batch_max_items()
        batch_window = self._runtime_batch_window_sec()

        while len(pieces) < batch_max_items:
            remaining = batch_window - (time.monotonic() - started)
            if remaining <= 0:
                break
            timeout = min(0.08, remaining)
            if self._aggressive_mode():
                timeout = min(timeout, 0.04)
            try:
                item = self.text_queue.get(timeout=timeout)
            except queue.Empty:
                break
            piece = item.strip()
            if not piece:
                continue
            if not pieces or self._normalize_text(piece) != self._normalize_text(pieces[-1]):
                pieces.append(piece)

        return " ".join(pieces).strip()

    def _is_sentence_complete(self, text: str) -> bool:
        probe = text.strip()
        if not probe:
            return False
        return probe.endswith((".", "!", "?", "..."))

    def _prepare_tts_text(self, translated_text: str) -> str:
        text = translated_text.strip()
        if not text:
            return ""
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\[[^\]]*\]|\([^\)]*\)", " ", text)
        text = re.sub(r"(?i)\b(?:system prompt|prompt|rules?|instruction|formato|texto:?)\b.*$", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        text = re.sub(r"([.!?,;:])\1{1,}", r"\1", text)
        # Collapse long word repetition loops before sending to TTS.
        text = re.sub(r"\b(\w+)(?:\s+\1){2,}\b", r"\1", text, flags=re.IGNORECASE)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _split_tts_text(self, text: str) -> list[str]:
        normalized = self._prepare_tts_text(text)
        if not normalized:
            return []

        limit = CONFIG.MAX_TTS_TEXT_CHARS
        if len(normalized) <= limit:
            return [normalized]

        sentences = re.split(r"(?<=[.!?])\s+", normalized)
        chunks: list[str] = []
        current = ""

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            if len(sentence) > limit:
                words = sentence.split()
                part = ""
                for word in words:
                    candidate = f"{part} {word}".strip()
                    if part and len(candidate) > limit:
                        chunks.append(part)
                        part = word
                    else:
                        part = candidate
                if part:
                    if current:
                        chunks.append(current)
                        current = ""
                    chunks.append(part)
                continue

            candidate = f"{current} {sentence}".strip() if current else sentence
            if current and len(candidate) > limit:
                chunks.append(current)
                current = sentence
            else:
                current = candidate

        if current:
            chunks.append(current)

        if len(chunks) > CONFIG.MAX_TTS_CHUNKS_PER_TRANSLATION:
            tail = " ".join(chunks[CONFIG.MAX_TTS_CHUNKS_PER_TRANSLATION - 1 :]).strip()
            chunks = chunks[: CONFIG.MAX_TTS_CHUNKS_PER_TRANSLATION - 1] + ([tail] if tail else [])

        return [item.strip() for item in chunks if item.strip()]

    def _collect_translated_batch(self, first_text: str) -> str:
        pieces: list[str] = []
        first_piece = first_text.strip()
        if first_piece:
            pieces.append(first_piece)
        started = time.monotonic()
        batch_max_items = max(1, self._runtime_tts_batch_max_items())
        batch_window = max(0.12, self._runtime_tts_batch_window_sec())

        while len(pieces) < batch_max_items:
            remaining = batch_window - (time.monotonic() - started)
            if remaining <= 0:
                break
            timeout = min(0.08, remaining)
            if self._aggressive_mode():
                timeout = min(timeout, 0.04)
            try:
                item = self.translated_queue.get(timeout=timeout)
            except queue.Empty:
                break
            piece = item.strip()
            if not piece:
                continue
            if not pieces or self._normalize_text(piece) != self._normalize_text(pieces[-1]):
                pieces.append(piece)
        return " ".join(pieces).strip()

    def _merge_pending_tts(self, incoming_text: str) -> str | None:
        normalized_incoming = incoming_text.strip()
        now = time.monotonic()

        if not normalized_incoming and not self._pending_tts_text:
            return None

        if normalized_incoming:
            if not self._pending_tts_text:
                self._pending_tts_text = normalized_incoming
                self._pending_tts_started_at = now
            else:
                self._pending_tts_text = self._append_with_overlap(
                    self._pending_tts_text,
                    normalized_incoming,
                    min_overlap_words=3,
                )
            max_pending_chars = max(120, CONFIG.MAX_TTS_TEXT_CHARS * 3)
            if len(self._pending_tts_text) > max_pending_chars:
                self._pending_tts_text = self._pending_tts_text[-max_pending_chars:]
        elif self._pending_tts_started_at <= 0:
            self._pending_tts_started_at = now

        min_chars = max(CONFIG.MIN_TTS_TEXT_CHARS, self._runtime_tts_buffer_min_chars())
        age = now - max(0.0, self._pending_tts_started_at)
        has_min_chars = len(self._pending_tts_text) >= min_chars
        sentence_complete = self._is_sentence_complete(self._pending_tts_text)
        backlog_ready = has_min_chars and self.translated_queue.qsize() >= max(1, self._runtime_tts_batch_max_items() // 2)
        age_ready = age >= max(0.35 if self._aggressive_mode() else 0.6, self._runtime_tts_buffer_max_age_sec())
        if not (age_ready or (has_min_chars and sentence_complete) or backlog_ready):
            if normalized_incoming:
                flow_log(
                    "pipeline",
                    "tts_accumulating",
                    chars=len(self._pending_tts_text),
                    age=f"{age:.2f}s",
                    min_chars=min_chars,
                    translated_q=self.translated_queue.qsize(),
                )
            return None

        result = self._pending_tts_text.strip()
        self._pending_tts_text = ""
        self._pending_tts_started_at = 0.0
        return result if result else None

    def _next_speech_seq(self) -> int:
        self._speech_seq += 1
        return self._speech_seq

    def _enqueue_speech_packet(self, seq_id: int, wav_bytes: bytes, tts_text: str) -> bool:
        packet = (seq_id, wav_bytes, tts_text)
        while not self.stop_event.is_set():
            try:
                self.speech_queue.put(packet, timeout=0.2)
                flow_log("pipeline", "speech_enqueued", seq=seq_id, queue=self.speech_queue.qsize())
                return True
            except queue.Full:
                flow_log("pipeline", "speech_queue_wait", seq=seq_id, queue=self.speech_queue.qsize())
                continue
        return False

    def _wait_playback_ack(self, seq_id: int) -> bool:
        timeout = max(8.0, float(CONFIG.PLAYBACK_ACK_TIMEOUT_SEC))
        deadline = time.monotonic() + timeout
        while not self.stop_event.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                flow_log("pipeline", "playback_ack_timeout", seq=seq_id, timeout=f"{timeout:.1f}s")
                return False
            try:
                ack_seq = self.playback_ack_queue.get(timeout=min(0.25, remaining))
            except queue.Empty:
                continue
            if ack_seq == seq_id:
                flow_log("pipeline", "playback_ack_ok", seq=seq_id)
                return True
            flow_log("pipeline", "playback_ack_mismatch", expected=seq_id, got=ack_seq)
        return False

    def _merge_pending_source(self, incoming_text: str) -> str | None:
        normalized_incoming = incoming_text.strip()
        now = time.monotonic()

        if not normalized_incoming and not self._pending_source_text:
            return None

        if normalized_incoming:
            if self._is_tiny_fragment(normalized_incoming):
                return None
            if not self._pending_source_text:
                self._pending_source_text = normalized_incoming
                self._pending_source_started_at = now
            else:
                self._pending_source_text = self._append_with_overlap(
                    self._pending_source_text,
                    normalized_incoming,
                    min_overlap_words=3,
                )
            if len(self._pending_source_text) > 280:
                self._pending_source_text = self._pending_source_text[-280:]
        elif self._pending_source_started_at <= 0:
            self._pending_source_started_at = now

        min_chars = self._runtime_min_source_chars()
        soft_max_sec = self._runtime_source_accum_max_sec()
        hard_cap = float(CONFIG.SOURCE_ACCUM_HARD_MAX_SEC)
        if self._aggressive_mode():
            soft_max_sec = min(soft_max_sec, 0.55)
            hard_cap = min(hard_cap, 1.6)
        if self.runtime_settings.fallback_enabled:
            # In fallback mode, prioritize continuity over long sentence accumulation.
            soft_max_sec = min(soft_max_sec, 1.0)
            hard_cap = min(hard_cap, 2.8)
        hard_max_sec = max(soft_max_sec + 0.6, hard_cap)
        age = now - self._pending_source_started_at
        ready_by_time = age >= soft_max_sec
        ready_by_hard_time = age >= hard_max_sec
        has_meaningful = self._has_meaningful_source(self._pending_source_text)
        sentence_complete = self._is_sentence_complete(self._pending_source_text)
        long_enough_min = max(min_chars + 6, 14) if self._aggressive_mode() else max(min_chars + 14, 28)
        long_enough = len(self._pending_source_text) >= long_enough_min
        backlog_ready = has_meaningful and self.text_queue.qsize() >= (1 if self._aggressive_mode() else 2)
        if not ready_by_hard_time and not backlog_ready and not (
            ready_by_time and has_meaningful and (sentence_complete or long_enough)
        ):
            if normalized_incoming:
                flow_log(
                    "pipeline",
                    "source_accumulating",
                    chars=len(self._pending_source_text),
                    age=f"{age:.2f}s",
                    min_chars=min_chars,
                    text_q=self.text_queue.qsize(),
                )
            return None

        if not has_meaningful:
            flow_log(
                "pipeline",
                "source_too_short_dropped",
                chars=len(self._pending_source_text),
                age=f"{age:.2f}s",
            )
            self._pending_source_text = ""
            self._pending_source_started_at = 0.0
            return None

        result = self._pending_source_text
        self._pending_source_text = ""
        self._pending_source_started_at = 0.0
        return result

    def _is_repeated_source(self, source_text: str) -> bool:
        normalized = self._normalize_loose(source_text)
        if not normalized:
            return True
        now = time.monotonic()
        delta = now - self._last_source_sent_at
        cooldown = self._runtime_repeat_source_cooldown_sec()
        prev = self._last_source_sent
        if prev and delta <= (cooldown * 2.0):
            if normalized.startswith(prev):
                growth_chars = len(normalized) - len(prev)
                growth_words = self._word_count(normalized) - self._word_count(prev)
                if growth_chars < 24 and growth_words < 4:
                    flow_log(
                        "pipeline",
                        "source_prefix_repeat_blocked",
                        growth_chars=growth_chars,
                        growth_words=growth_words,
                        delta=f"{delta:.2f}s",
                    )
                    return True
            elif prev.startswith(normalized):
                flow_log("pipeline", "source_regressive_repeat_blocked", delta=f"{delta:.2f}s")
                return True
        if normalized == self._last_source_sent and delta <= cooldown:
            return True
        source_recent_threshold = max(0.70, self._runtime_source_repeat_overlap_threshold() - 0.18)
        if len(normalized) >= 110:
            source_recent_threshold = max(source_recent_threshold, 0.76)
        if self._is_recently_similar(
            normalized,
            self._recent_source_sent,
            threshold=source_recent_threshold,
            window_sec=max(cooldown * 2.8, 10.0),
        ):
            prev = self._last_source_sent
            growth_chars = len(normalized) - len(prev) if prev else 0
            growth_words = self._word_count(normalized) - self._word_count(prev) if prev else 0
            if not (prev and normalized.startswith(prev) and (growth_chars >= 28 or growth_words >= 5)):
                flow_log(
                    "pipeline",
                    "source_recent_repeat_blocked",
                    growth_chars=growth_chars,
                    growth_words=growth_words,
                    delta=f"{delta:.2f}s",
                )
                return True
        if self._last_source_sent and delta <= (cooldown * 2.0):
            overlap = self._token_overlap_ratio(normalized, self._last_source_sent)
            if overlap >= self._runtime_source_repeat_overlap_threshold():
                growth_chars = len(normalized) - len(self._last_source_sent)
                growth_words = self._word_count(normalized) - self._word_count(self._last_source_sent)
                if normalized.startswith(self._last_source_sent) and (growth_chars >= 28 or growth_words >= 5):
                    pass
                else:
                    flow_log("pipeline", "source_near_repeat_blocked", overlap=f"{overlap:.2f}", delta=f"{delta:.2f}s")
                    return True
        self._last_source_sent = normalized
        self._last_source_sent_at = now
        self._remember_recent(
            normalized,
            self._recent_source_sent,
            window_sec=max(cooldown * 3.0, 12.0),
            max_items=18,
        )
        return False

    def _should_skip_tts_repeat(self, tts_text: str) -> bool:
        normalized = self._normalize_loose(tts_text)
        if not normalized:
            return True
        now = time.monotonic()
        delta = now - self._last_tts_spoken_at
        overlap = self._token_overlap_ratio(normalized, self._last_tts_spoken) if self._last_tts_spoken else 0.0
        cooldown = float(CONFIG.REPEAT_TTS_COOLDOWN_SEC)
        if self._last_tts_spoken and delta <= (cooldown * 2.0):
            if normalized.startswith(self._last_tts_spoken):
                growth_chars = len(normalized) - len(self._last_tts_spoken)
                growth_words = self._word_count(normalized) - self._word_count(self._last_tts_spoken)
                if growth_chars < 38 and growth_words < 6:
                    self._tts_repeat_streak += 1
                    flow_log(
                        "pipeline",
                        "tts_prefix_repeat_blocked",
                        streak=self._tts_repeat_streak,
                        growth_chars=growth_chars,
                        growth_words=growth_words,
                        delta=f"{delta:.2f}s",
                    )
                    return True
            elif self._last_tts_spoken.startswith(normalized):
                self._tts_repeat_streak += 1
                flow_log(
                    "pipeline",
                    "tts_regressive_repeat_blocked",
                    streak=self._tts_repeat_streak,
                    delta=f"{delta:.2f}s",
                )
                return True
        if self._is_recently_similar(
            normalized,
            self._recent_tts_spoken,
            threshold=0.62,
            window_sec=max(cooldown * 2.0, 18.0),
        ):
            growth_chars = len(normalized) - len(self._last_tts_spoken) if self._last_tts_spoken else 0
            growth_words = (
                self._word_count(normalized) - self._word_count(self._last_tts_spoken)
                if self._last_tts_spoken
                else 0
            )
            if not (
                self._last_tts_spoken
                and normalized.startswith(self._last_tts_spoken)
                and (growth_chars >= 34 or growth_words >= 6)
            ):
                self._tts_repeat_streak += 1
                flow_log(
                    "pipeline",
                    "tts_recent_repeat_blocked",
                    streak=self._tts_repeat_streak,
                    growth_chars=growth_chars,
                    growth_words=growth_words,
                    delta=f"{delta:.2f}s",
                )
                return True
        if self._last_tts_spoken and self.speech_queue.qsize() > 0:
            backlog_overlap = self._token_overlap_ratio(normalized, self._last_tts_spoken)
            if backlog_overlap >= 0.55:
                self._tts_repeat_streak += 1
                flow_log(
                    "pipeline",
                    "tts_backlog_similar_blocked",
                    streak=self._tts_repeat_streak,
                    overlap=f"{backlog_overlap:.2f}",
                    speech_q=self.speech_queue.qsize(),
                )
                return True
        if (
            normalized == self._last_tts_spoken
            or (self._last_tts_spoken and delta <= (cooldown * 1.5) and overlap >= 0.90)
        ) and delta <= (cooldown * 1.5):
            self._tts_repeat_streak += 1
            flow_log(
                "pipeline",
                "tts_repeat_blocked",
                streak=self._tts_repeat_streak,
                cooldown=f"{cooldown:.1f}s",
                overlap=f"{overlap:.2f}",
            )
            return True
        self._last_tts_spoken = normalized
        self._last_tts_spoken_at = now
        self._tts_repeat_streak = 0
        self._remember_recent(
            normalized,
            self._recent_tts_spoken,
            window_sec=max(cooldown * 2.2, 20.0),
            max_items=24,
        )
        return False

    def _is_repeated_translation(self, translated_text: str) -> bool:
        normalized = self._normalize_loose(translated_text)
        if not normalized:
            return True
        now = time.monotonic()
        delta = now - self._last_translated_sent_at
        cooldown = self._runtime_repeat_source_cooldown_sec()
        prev = self._last_translated_sent
        if prev and delta <= (cooldown * 2.0):
            if normalized.startswith(prev):
                growth_chars = len(normalized) - len(prev)
                growth_words = self._word_count(normalized) - self._word_count(prev)
                if growth_chars < 36 and growth_words < 6:
                    flow_log(
                        "pipeline",
                        "translated_prefix_repeat_blocked",
                        growth_chars=growth_chars,
                        growth_words=growth_words,
                        delta=f"{delta:.2f}s",
                    )
                    return True
            elif prev.startswith(normalized):
                flow_log("pipeline", "translated_regressive_repeat_blocked", delta=f"{delta:.2f}s")
                return True
        if normalized == self._last_translated_sent and delta <= cooldown:
            return True
        translated_recent_threshold = max(0.68, self._runtime_translated_repeat_overlap_threshold() - 0.24)
        if len(normalized) >= 110:
            translated_recent_threshold = max(translated_recent_threshold, 0.74)
        if self._is_recently_similar(
            normalized,
            self._recent_translated_sent,
            threshold=translated_recent_threshold,
            window_sec=max(cooldown * 2.6, 10.0),
        ):
            prev = self._last_translated_sent
            growth_chars = len(normalized) - len(prev) if prev else 0
            growth_words = self._word_count(normalized) - self._word_count(prev) if prev else 0
            if not (prev and normalized.startswith(prev) and (growth_chars >= 36 or growth_words >= 6)):
                flow_log(
                    "pipeline",
                    "translated_recent_repeat_blocked",
                    growth_chars=growth_chars,
                    growth_words=growth_words,
                    delta=f"{delta:.2f}s",
                )
                return True
        if self._last_translated_sent and delta <= (cooldown * 2.0):
            overlap = self._token_overlap_ratio(normalized, self._last_translated_sent)
            if overlap >= self._runtime_translated_repeat_overlap_threshold():
                growth_chars = len(normalized) - len(self._last_translated_sent)
                growth_words = self._word_count(normalized) - self._word_count(self._last_translated_sent)
                if normalized.startswith(self._last_translated_sent) and (growth_chars >= 36 or growth_words >= 6):
                    pass
                else:
                    flow_log("pipeline", "translated_near_repeat_blocked", overlap=f"{overlap:.2f}", delta=f"{delta:.2f}s")
                    return True
        self._last_translated_sent = normalized
        self._last_translated_sent_at = now
        self._remember_recent(
            normalized,
            self._recent_translated_sent,
            window_sec=max(cooldown * 3.0, 12.0),
            max_items=18,
        )
        return False

    def _enqueue_translated_text(self, translated_text: str) -> bool:
        while not self.stop_event.is_set():
            try:
                self.translated_queue.put(translated_text, timeout=0.2)
                return True
            except queue.Full:
                flow_log("pipeline", "translated_queue_wait", queue=self.translated_queue.qsize())
                continue
        return False

    def _handle_stt_transcript(self, text: str, elapsed_sec: float | None = None) -> None:
        cleaned = re.sub(r"\s+", " ", (text or "").strip())
        if not cleaned:
            return
        words = re.findall(r"\w+", cleaned, flags=re.UNICODE)
        if len(words) < 2 and len(cleaned) < 12:
            flow_log("pipeline", "stt_text_dropped_low_info", chars=len(cleaned), words=len(words))
            return
        if self._is_tiny_fragment(cleaned):
            flow_log("pipeline", "stt_text_dropped_short", chars=len(cleaned))
            return
        if len(cleaned) > CONFIG.MAX_STT_TEXT_CHARS:
            flow_log(
                "pipeline",
                "stt_text_dropped_long",
                chars=len(cleaned),
                max_chars=CONFIG.MAX_STT_TEXT_CHARS,
            )
            return
        if self._is_probable_tts_echo(cleaned):
            flow_log("pipeline", "stt_echo_filtered", chars=len(cleaned))
            return

        normalized = self._normalize_text(cleaned)
        now = time.monotonic()
        if normalized == self._last_stt_text and (now - self._last_stt_text_at) <= self._runtime_repeat_source_cooldown_sec():
            flow_log("pipeline", "stt_duplicate_blocked", chars=len(cleaned))
            return
        self._last_stt_text = normalized
        self._last_stt_text_at = now

        put_with_drop(self.text_queue, cleaned)
        flow_log(
            "pipeline",
            "stt_text",
            elapsed=f"{elapsed_sec:.3f}s" if elapsed_sec is not None else "n/a",
            chars=len(cleaned),
            text_queue=self.text_queue.qsize(),
        )
        if self._trace_session_id:
            self._trace_stt_seq += 1
            log_stt_trace(
                session_id=self._trace_session_id,
                seq=self._trace_stt_seq,
                text=cleaned,
                elapsed_sec=round(float(elapsed_sec), 3) if elapsed_sec is not None else None,
                text_queue=self.text_queue.qsize(),
            )

    def _deepgram_worker(self) -> None:
        self.stt.run(
            stop_event=self.stop_event,
            audio_queue=self.audio_queue,
            on_final_transcript=self._handle_stt_transcript,
        )

    def _process_translation_source(self, merged_source: str | None) -> None:
        if not merged_source:
            return
        if self._is_repeated_source(merged_source):
            flow_log("pipeline", "source_repeat_blocked", chars=len(merged_source))
            return
        if self._is_probable_tts_echo(merged_source):
            flow_log("pipeline", "echo_filtered", chars=len(merged_source))
            return

        with self._translator_lock:
            translator = self.translator

        started = time.perf_counter()
        translated = translator.translate(merged_source)
        elapsed = time.perf_counter() - started
        provider = getattr(translator, "last_provider", "")
        provider_error = str(getattr(translator, "last_provider_error", "") or "")

        if translated and not contains_prompt_leak(translated):
            if self._is_repeated_translation(translated):
                flow_log("pipeline", "translated_repeat_blocked", chars=len(translated))
                if self._trace_session_id:
                    self._trace_ai_seq += 1
                    log_ai_trace(
                        session_id=self._trace_session_id,
                        seq=self._trace_ai_seq,
                        provider=provider or "unknown",
                        source_text=merged_source,
                        translated_text=translated,
                        status="blocked_repeat",
                        elapsed_sec=round(elapsed, 3),
                        overlap_ratio=round(self._token_overlap_ratio(merged_source, translated), 3),
                    )
                return
            if not self._enqueue_translated_text(translated):
                return
            flow_log(
                "pipeline",
                "translated",
                elapsed=f"{elapsed:.3f}s",
                provider=provider or "unknown",
                source_len=len(merged_source),
                translated_len=len(translated),
            )
            if self._trace_session_id:
                self._trace_ai_seq += 1
                log_ai_trace(
                    session_id=self._trace_session_id,
                    seq=self._trace_ai_seq,
                    provider=provider or "unknown",
                    source_text=merged_source,
                    translated_text=translated,
                    status="ok",
                    elapsed_sec=round(elapsed, 3),
                    source_len=len(merged_source),
                    translated_len=len(translated),
                    overlap_ratio=round(self._token_overlap_ratio(merged_source, translated), 3),
                )
        elif translated:
            self._handle_error("Filtered translation containing prompt text.")
            if self._trace_session_id:
                self._trace_ai_seq += 1
                log_ai_trace(
                    session_id=self._trace_session_id,
                    seq=self._trace_ai_seq,
                    provider=provider or "unknown",
                    source_text=merged_source,
                    translated_text=translated,
                    status="filtered_prompt",
                    elapsed_sec=round(elapsed, 3),
                )
        else:
            flow_log(
                "pipeline",
                "translation_empty",
                elapsed=f"{elapsed:.3f}s",
                provider=provider or "unknown",
                source_len=len(merged_source),
            )
            if self._trace_session_id:
                self._trace_ai_seq += 1
                log_ai_trace(
                    session_id=self._trace_session_id,
                    seq=self._trace_ai_seq,
                    provider=provider or "unknown",
                    source_text=merged_source,
                    translated_text="",
                    status="empty",
                    elapsed_sec=round(elapsed, 3),
                    error=provider_error,
                )

    def _translation_worker(self) -> None:
        while not self.stop_event.is_set():
            try:
                first_text = self.text_queue.get(timeout=0.2)
                source_text = self._collect_text_batch(first_text)
                self._process_translation_source(self._merge_pending_source(source_text))
            except queue.Empty:
                # Flush pending source when the stream pauses after speech.
                self._process_translation_source(self._merge_pending_source(""))
                continue
        # Final flush on shutdown.
        self._process_translation_source(self._merge_pending_source(""))

    def _dispatch_tts_text(self, merged_tts_text: str | None) -> None:
        if not merged_tts_text:
            return

        tts_chunks = self._split_tts_text(merged_tts_text)
        if not tts_chunks:
            return
        flow_log("pipeline", "tts_chunks", count=len(tts_chunks), total_chars=len(merged_tts_text))

        for index, tts_text in enumerate(tts_chunks, start=1):
            if self.stop_event.is_set():
                return
            if len(tts_text) < CONFIG.MIN_TTS_TEXT_CHARS:
                flow_log("pipeline", "tts_skip_short", chars=len(tts_text), chunk=index)
                continue
            if self._should_skip_tts_repeat(tts_text):
                if self._tts_repeat_streak >= 4:
                    flow_log("pipeline", "tts_repeat_guard_flush", streak=self._tts_repeat_streak)
                    clear_queue(self.translated_queue)
                    self._pending_tts_text = ""
                    self._pending_tts_started_at = 0.0
                continue

            self._remember_tts_text(tts_text)
            started = time.perf_counter()
            wav_bytes = self.tts.synthesize(tts_text)
            elapsed = time.perf_counter() - started

            if not wav_bytes:
                flow_log("pipeline", "tts_empty", elapsed=f"{elapsed:.3f}s", chunk=index)
                continue

            seq_id = self._next_speech_seq()
            if not self._enqueue_speech_packet(seq_id, wav_bytes, tts_text):
                return
            flow_log(
                "pipeline",
                "tts_ready",
                elapsed=f"{elapsed:.3f}s",
                seq=seq_id,
                text_len=len(tts_text),
                bytes=len(wav_bytes),
                chunk=index,
            )

            if CONFIG.STRICT_PLAYBACK_HANDSHAKE:
                if not self._wait_playback_ack(seq_id):
                    flow_log("pipeline", "tts_wait_ack_failed", seq=seq_id)
                    break
            else:
                max_q = max(1, int(CONFIG.TTS_BACKPRESSURE_MAX_QUEUE))
                if self.speech_queue.qsize() >= max_q:
                    flow_log(
                        "pipeline",
                        "tts_backpressure_wait",
                        queue=self.speech_queue.qsize(),
                        max_queue=max_q,
                        seq=seq_id,
                    )
                    if not self._wait_playback_ack(seq_id):
                        flow_log("pipeline", "tts_backpressure_ack_failed", seq=seq_id)
                        break

    def _tts_worker(self) -> None:
        while not self.stop_event.is_set():
            try:
                first_text = self.translated_queue.get(timeout=0.2)
            except queue.Empty:
                # Flush pending translated text when stream pauses.
                self._dispatch_tts_text(self._merge_pending_tts(""))
                continue

            merged_now = self._collect_translated_batch(first_text)
            ready_text = self._merge_pending_tts(merged_now)
            self._dispatch_tts_text(ready_text)

        # Final flush on shutdown.
        self._dispatch_tts_text(self._merge_pending_tts(""))


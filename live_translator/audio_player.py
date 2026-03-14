import io
import queue
import threading
import time
import wave
from typing import Callable, Any

import numpy as np
import sounddevice as sd

from live_translator.flow_logger import flow_log


class AudioPlayer:
    def __init__(self, on_error: Callable[[str], None] | None = None) -> None:
        self.on_error = on_error
        self.capture_suppress_tail_sec = 0.45

    def _emit_error(self, message: str) -> None:
        if self.on_error is not None:
            self.on_error(message)

    def play_wav_bytes(self, wav_bytes: bytes) -> None:
        started = time.perf_counter()
        try:
            with wave.open(io.BytesIO(wav_bytes), "rb") as wav_file:
                channels = wav_file.getnchannels()
                sample_width = wav_file.getsampwidth()
                sample_rate = wav_file.getframerate()
                frame_count = wav_file.getnframes()
                pcm_data = wav_file.readframes(frame_count)

            if sample_width != 2:
                self._emit_error(f"Unsupported WAV sample width: {sample_width}")
                return

            audio = np.frombuffer(pcm_data, dtype=np.int16).astype(np.float32) / 32768.0
            if channels > 1:
                audio = audio.reshape(-1, channels).mean(axis=1)

            duration_sec = len(audio) / float(sample_rate) if sample_rate > 0 else 0.0
            flow_log("playback", "play_start", samples=len(audio), sample_rate=sample_rate, duration=f"{duration_sec:.2f}s")
            sd.play(audio, samplerate=sample_rate, blocking=True)
            elapsed = time.perf_counter() - started
            flow_log("playback", "play_done", elapsed=f"{elapsed:.2f}s")

        except Exception as exc:
            self._emit_error(f"Audio playback failure: {exc}")

    def _parse_packet(self, packet: Any) -> tuple[int | None, bytes | None]:
        if isinstance(packet, (tuple, list)) and len(packet) >= 2:
            seq = packet[0]
            payload = packet[1]
            if isinstance(seq, int) and isinstance(payload, (bytes, bytearray)):
                return seq, bytes(payload)
        if isinstance(packet, (bytes, bytearray)):
            return None, bytes(packet)
        return None, None

    def _emit_ack(self, ack_queue: queue.Queue | None, seq_id: int | None) -> None:
        if ack_queue is None or seq_id is None:
            return
        try:
            ack_queue.put_nowait(seq_id)
            flow_log("playback", "ack_sent", seq=seq_id)
        except queue.Full:
            try:
                ack_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                ack_queue.put_nowait(seq_id)
                flow_log("playback", "ack_sent_after_drop", seq=seq_id)
            except Exception:
                flow_log("playback", "ack_failed", seq=seq_id)

    def run(
        self,
        stop_event: threading.Event,
        speech_queue: queue.Queue,
        playback_guard_event: threading.Event | None = None,
        ack_queue: queue.Queue | None = None,
    ) -> None:
        while not stop_event.is_set():
            try:
                packet = speech_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            seq_id, wav_bytes = self._parse_packet(packet)
            if wav_bytes is None:
                flow_log("playback", "invalid_packet")
                self._emit_ack(ack_queue, seq_id)
                continue

            try:
                if playback_guard_event is not None:
                    playback_guard_event.set()
                self.play_wav_bytes(wav_bytes)
            finally:
                if playback_guard_event is not None:
                    if self.capture_suppress_tail_sec > 0:
                        time.sleep(self.capture_suppress_tail_sec)
                    playback_guard_event.clear()
                self._emit_ack(ack_queue, seq_id)

        sd.stop()
        flow_log("playback", "worker_stopped")

    def stop(self) -> None:
        sd.stop()

import queue
import threading
import time
from typing import Callable

import numpy as np
import sounddevice as sd

from live_translator.config import CONFIG
from live_translator.flow_logger import flow_log
from live_translator.queue_utils import put_with_drop


SYSTEM_CAPTURE_KEYWORDS = (
    "loopback",
    "stereo mix",
    "what u hear",
    "mixed capture",
    "mixagem estereo",
)


class SystemAudioCapture:
    def __init__(self, on_error: Callable[[str], None] | None = None) -> None:
        self.sample_rate = CONFIG.SAMPLE_RATE
        self.chunk_size = CONFIG.CHUNK_SIZE
        self.dtype = CONFIG.DTYPE
        self.on_error = on_error

        self._input_sample_rate = self.sample_rate
        self._pending_buffers: list[np.ndarray] = []
        self._pending_samples = 0
        self._preferred_channel_idx: int | None = None

        # Fast-start first chunk while avoiding ultra-short fragments.
        self._first_chunk_emitted = False
        if CONFIG.CHUNK_DURATION_SEC >= 2.5:
            warmup_seconds = CONFIG.CHUNK_DURATION_SEC
        else:
            warmup_seconds = min(2.0, max(0.60, CONFIG.CHUNK_DURATION_SEC * 0.66))
        self._first_chunk_size = min(self.chunk_size, max(1, int(self.sample_rate * warmup_seconds)))

        self._emitted_chunks = 0
        self._suppressed_callbacks = 0
        self._stats_log_mark = time.monotonic()

    def _to_mono(self, indata: np.ndarray) -> np.ndarray:
        if indata.ndim == 1:
            return indata.astype(np.float32, copy=False)
        if indata.shape[1] == 1:
            return indata[:, 0].astype(np.float32, copy=False)

        # Keep a stable channel selection to avoid frame-to-frame channel hopping,
        # which can hurt ASR consistency.
        channels = indata.astype(np.float32, copy=False)
        if self._preferred_channel_idx is None:
            energies = np.sqrt(np.mean(np.square(channels, dtype=np.float32), axis=0))
            if float(np.max(energies)) < 1e-4:
                return channels.mean(axis=1, dtype=np.float32)
            self._preferred_channel_idx = int(np.argmax(energies))
        channel_index = max(0, min(channels.shape[1] - 1, int(self._preferred_channel_idx)))
        return channels[:, channel_index]

    def _emit_error(self, message: str) -> None:
        if self.on_error is not None:
            self.on_error(message)

    def _list_input_devices(self) -> list[tuple[int, dict, str]]:
        devices = sd.query_devices()
        hostapis = sd.query_hostapis()

        inputs: list[tuple[int, dict, str]] = []
        for idx, device in enumerate(devices):
            if int(device.get("max_input_channels", 0)) < 1:
                continue
            hostapi_index = int(device.get("hostapi", -1))
            hostapi_name = ""
            if hostapi_index >= 0:
                hostapi_name = str(hostapis[hostapi_index].get("name", "")).lower()
            inputs.append((idx, device, hostapi_name))
        return inputs

    def _select_capture_device(self) -> tuple[int, str, str]:
        input_devices = self._list_input_devices()
        if not input_devices:
            raise RuntimeError("No input-capable audio device found.")

        for idx, device, hostapi in input_devices:
            name = str(device.get("name", "")).lower()
            if "wasapi" in hostapi and "loopback" in name:
                return idx, hostapi, "WASAPI loopback"

        for idx, device, hostapi in input_devices:
            name = str(device.get("name", "")).lower()
            if any(keyword in name for keyword in SYSTEM_CAPTURE_KEYWORDS):
                return idx, hostapi, "Stereo Mix/What U Hear"

        default_devices = sd.default.device
        if isinstance(default_devices, (list, tuple)) and len(default_devices) > 0:
            default_input = int(default_devices[0])
            for idx, _, hostapi in input_devices:
                if idx == default_input:
                    return idx, hostapi, "Default input fallback (microphone)"

        first_idx, _, first_hostapi = input_devices[0]
        return first_idx, first_hostapi, "First input fallback (microphone)"

    def _resample_if_needed(self, mono_audio: np.ndarray) -> np.ndarray:
        if self._input_sample_rate == self.sample_rate:
            return mono_audio
        if mono_audio.size == 0:
            return mono_audio

        output_len = max(1, int(round(mono_audio.size * self.sample_rate / self._input_sample_rate)))
        x_old = np.linspace(0.0, 1.0, num=mono_audio.size, endpoint=False, dtype=np.float64)
        x_new = np.linspace(0.0, 1.0, num=output_len, endpoint=False, dtype=np.float64)
        return np.interp(x_new, x_old, mono_audio).astype(np.float32, copy=False)

    def _clear_pending(self) -> None:
        self._pending_buffers.clear()
        self._pending_samples = 0

    def _pop_samples(self, target_size: int) -> np.ndarray:
        if target_size <= 0 or self._pending_samples <= 0:
            return np.empty(0, dtype=np.float32)

        chunk = np.empty(target_size, dtype=np.float32)
        copied = 0

        while copied < target_size and self._pending_buffers:
            head = self._pending_buffers[0]
            need = target_size - copied

            if head.size <= need:
                chunk[copied : copied + head.size] = head
                copied += head.size
                self._pending_samples -= int(head.size)
                self._pending_buffers.pop(0)
            else:
                chunk[copied:] = head[:need]
                self._pending_buffers[0] = head[need:]
                copied += need
                self._pending_samples -= need

        if copied <= 0:
            return np.empty(0, dtype=np.float32)
        return chunk[:copied].copy()

    def _append_and_chunk(self, audio_queue: queue.Queue, samples: np.ndarray) -> int:
        if samples.size == 0:
            return 0

        self._pending_buffers.append(samples)
        self._pending_samples += int(samples.size)
        emitted = 0

        if not self._first_chunk_emitted and self._pending_samples >= self._first_chunk_size:
            first_chunk = self._pop_samples(self._first_chunk_size)
            if first_chunk.size > 0:
                put_with_drop(audio_queue, first_chunk)
                self._first_chunk_emitted = True
                emitted += 1

        while self._pending_samples >= self.chunk_size:
            chunk = self._pop_samples(self.chunk_size)
            if chunk.size > 0:
                put_with_drop(audio_queue, chunk)
                emitted += 1
        return emitted

    def run(
        self,
        stop_event: threading.Event,
        audio_queue: queue.Queue,
        suppress_capture_event: threading.Event | None = None,
    ) -> None:
        try:
            self._clear_pending()
            self._first_chunk_emitted = False
            self._preferred_channel_idx = None
            self._emitted_chunks = 0
            self._suppressed_callbacks = 0
            self._stats_log_mark = time.monotonic()

            capture_device, hostapi_name, mode = self._select_capture_device()
            flow_log("capture", "device_selected", device_id=capture_device, hostapi=hostapi_name, mode=mode)
            if "fallback" in mode.lower():
                self._emit_error(f"System loopback unavailable. Using {mode}.")

            device_info = sd.query_devices(capture_device, "input")
            flow_log(
                "capture",
                "device_info",
                max_input_channels=int(device_info.get("max_input_channels", 0)),
                default_samplerate=int(device_info.get("default_samplerate", self.sample_rate)),
            )

            def callback(indata: np.ndarray, _frames: int, _time, status) -> None:
                if status:
                    self._emit_error(f"Audio capture status: {status}")

                if suppress_capture_event is not None and suppress_capture_event.is_set():
                    self._clear_pending()
                    self._suppressed_callbacks += 1
                    return

                mono = self._to_mono(indata)
                mono = self._resample_if_needed(mono)
                self._emitted_chunks += self._append_and_chunk(audio_queue, mono)

                now = time.monotonic()
                if now - self._stats_log_mark >= CONFIG.FLOW_LOG_INTERVAL_SEC:
                    flow_log(
                        "capture",
                        "stats",
                        emitted_chunks=self._emitted_chunks,
                        suppressed_callbacks=self._suppressed_callbacks,
                        queue_size=audio_queue.qsize(),
                    )
                    self._emitted_chunks = 0
                    self._suppressed_callbacks = 0
                    self._stats_log_mark = now

            max_input_channels = int(device_info.get("max_input_channels", 1))
            fallback_rate = int(device_info.get("default_samplerate", self.sample_rate))
            fallback_channels = max(1, min(max_input_channels, 2))

            attempts = [(self.sample_rate, CONFIG.CHANNELS)]
            if (fallback_rate, fallback_channels) not in attempts:
                attempts.append((fallback_rate, fallback_channels))

            extra_settings = None
            if "wasapi" in hostapi_name:
                extra_settings = sd.WasapiSettings(auto_convert=True)

            last_error: Exception | None = None
            for stream_rate, channels in attempts:
                try:
                    self._input_sample_rate = stream_rate
                    flow_log(
                        "capture",
                        "stream_attempt",
                        sample_rate=stream_rate,
                        channels=channels,
                        suppress_enabled=bool(suppress_capture_event is not None),
                    )
                    with sd.InputStream(
                        device=capture_device,
                        samplerate=stream_rate,
                        channels=channels,
                        dtype=self.dtype,
                        callback=callback,
                        blocksize=0,
                        extra_settings=extra_settings,
                    ):
                        flow_log("capture", "stream_started", sample_rate=stream_rate, channels=channels)
                        while not stop_event.wait(0.1):
                            pass
                    flow_log("capture", "stream_stopped")
                    return
                except Exception as exc:
                    flow_log("capture", "stream_attempt_failed", sample_rate=stream_rate, channels=channels, error=exc)
                    last_error = exc
                    continue

            if last_error is not None:
                raise last_error

        except Exception as exc:
            self._emit_error(f"Audio capture failed: {exc}")

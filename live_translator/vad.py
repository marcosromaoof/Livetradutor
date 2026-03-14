import numpy as np


class VoiceActivityDetector:
    def __init__(self, threshold: float) -> None:
        self.threshold = float(threshold)

    def rms(self, audio_chunk: np.ndarray) -> float:
        if audio_chunk.size == 0:
            return 0.0
        return float(np.sqrt(np.mean(np.square(audio_chunk, dtype=np.float32))))

    def is_speech(self, audio_chunk: np.ndarray) -> bool:
        return self.rms(audio_chunk) >= self.threshold

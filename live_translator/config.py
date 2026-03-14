import os
from dataclasses import dataclass

from live_translator.app_paths import get_asset_base_dir


BASE_DIR = get_asset_base_dir()
PIPER_DIR = os.path.join(BASE_DIR, "piper")
DEFAULT_PIPER_MODEL_PATH = os.path.join(PIPER_DIR, "pt_BR-faber-medium.onnx")
DEFAULT_PIPER_BINARY = os.path.join(PIPER_DIR, "piper.exe")
DEFAULT_GROQ_API_KEY = ""
DEFAULT_DEEPGRAM_API_KEY = ""


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class AppConfig:
    SAMPLE_RATE: int = 16000
    CHANNELS: int = 1
    DTYPE: str = "float32"
    CHUNK_DURATION_SEC: float = _env_float("CHUNK_DURATION_SEC", 0.8)
    DEEPGRAM_API_KEY: str = os.getenv("DEEPGRAM_API_KEY", DEFAULT_DEEPGRAM_API_KEY)
    DEEPGRAM_MODEL: str = os.getenv("DEEPGRAM_MODEL", "nova-3")
    DEEPGRAM_LANGUAGE: str = os.getenv("DEEPGRAM_LANGUAGE", "en")
    DEEPGRAM_PUNCTUATE: bool = _env_bool("DEEPGRAM_PUNCTUATE", True)
    DEEPGRAM_INTERIM_RESULTS: bool = _env_bool("DEEPGRAM_INTERIM_RESULTS", True)
    DEEPGRAM_SMART_FORMAT: bool = _env_bool("DEEPGRAM_SMART_FORMAT", True)
    DEEPGRAM_ENCODING: str = os.getenv("DEEPGRAM_ENCODING", "linear16")
    DEEPGRAM_ENDPOINTING_MS: int = _env_int("DEEPGRAM_ENDPOINTING_MS", 450)
    DEEPGRAM_UTTERANCE_END_MS: int = _env_int("DEEPGRAM_UTTERANCE_END_MS", 1000)
    DEEPGRAM_MIN_CONFIDENCE: float = _env_float("DEEPGRAM_MIN_CONFIDENCE", 0.40)
    DEEPGRAM_RECONNECT_MAX_SEC: float = _env_float("DEEPGRAM_RECONNECT_MAX_SEC", 6.0)
    DEEPGRAM_INTERIM_MIN_WORDS: int = _env_int("DEEPGRAM_INTERIM_MIN_WORDS", 6)
    DEEPGRAM_INTERIM_THROTTLE_SEC: float = _env_float("DEEPGRAM_INTERIM_THROTTLE_SEC", 0.85)
    DEEPGRAM_INTERIM_MIN_GROWTH_CHARS: int = _env_int("DEEPGRAM_INTERIM_MIN_GROWTH_CHARS", 22)
    STT_AUTO_GAIN_TARGET_PEAK: float = _env_float("STT_AUTO_GAIN_TARGET_PEAK", 0.70)
    STT_AUTO_GAIN_MAX: float = _env_float("STT_AUTO_GAIN_MAX", 8.0)
    STT_FINAL_DEDUP_SEC: float = _env_float("STT_FINAL_DEDUP_SEC", 2.0)
    STT_WINDOW_SEC: float = _env_float("STT_WINDOW_SEC", 3.0)
    STT_OVERLAP_SEC: float = _env_float("STT_OVERLAP_SEC", 1.0)
    STT_CONTEXT_WORDS: int = _env_int("STT_CONTEXT_WORDS", 15)
    VAD_THRESHOLD: float = 0.0035
    VAD_PROBE_EVERY: int = 6
    QUEUE_MAXSIZE: int = 10
    AUDIO_BACKLOG_TRIM_THRESHOLD: int = 8
    AUDIO_BACKLOG_KEEP_CHUNKS: int = 3
    MAX_STT_TEXT_CHARS: int = 180
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", DEFAULT_GROQ_API_KEY)
    GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
    GROQ_URL: str = "https://api.groq.com/openai/v1/chat/completions"
    GROQ_TIMEOUT_SEC: float = _env_float("GROQ_TIMEOUT_SEC", 8.0)
    GEMINI_TIMEOUT_SEC: float = _env_float("GEMINI_TIMEOUT_SEC", 2.8)
    DEEPSEEK_TIMEOUT_SEC: float = _env_float("DEEPSEEK_TIMEOUT_SEC", 8.0)
    PIPER_MODEL_PATH: str = os.getenv("PIPER_MODEL_PATH", DEFAULT_PIPER_MODEL_PATH)
    PIPER_BINARY: str = os.getenv("PIPER_BINARY", DEFAULT_PIPER_BINARY)
    PIPER_SPEAKER_ID: int = _env_int("PIPER_SPEAKER_ID", 0)
    PIPER_NOISE_SCALE: float = _env_float("PIPER_NOISE_SCALE", 0.58)
    PIPER_LENGTH_SCALE: float = _env_float("PIPER_LENGTH_SCALE", 0.95)
    PIPER_NOISE_W: float = _env_float("PIPER_NOISE_W", 0.90)
    PIPER_SENTENCE_SILENCE: float = _env_float("PIPER_SENTENCE_SILENCE", 0.10)
    TTS_MAX_AUDIO_SEC: float = _env_float("TTS_MAX_AUDIO_SEC", 12.0)
    TTS_MAX_SEC_PER_CHAR: float = _env_float("TTS_MAX_SEC_PER_CHAR", 0.18)
    PLAYBACK_ACK_TIMEOUT_SEC: float = _env_float("PLAYBACK_ACK_TIMEOUT_SEC", 45.0)
    SPEECH_QUEUE_TRIM_THRESHOLD: int = 3
    SPEECH_QUEUE_KEEP_CHUNKS: int = 1
    PLAYBACK_BLOCKSIZE: int = 0
    FLOW_LOG_INTERVAL_SEC: float = 2.0
    AGGRESSIVE_CONTINUOUS_MODE: bool = _env_bool("AGGRESSIVE_CONTINUOUS_MODE", True)
    STRICT_PLAYBACK_HANDSHAKE: bool = _env_bool("STRICT_PLAYBACK_HANDSHAKE", False)
    TTS_BACKPRESSURE_MAX_QUEUE: int = _env_int("TTS_BACKPRESSURE_MAX_QUEUE", 2)
    ENABLE_PLAYBACK_CAPTURE_SUPPRESSION: bool = _env_bool("ENABLE_PLAYBACK_CAPTURE_SUPPRESSION", True)
    TEXT_BATCH_WINDOW_SEC: float = 0.65
    TEXT_BATCH_MAX_ITEMS: int = 5
    MIN_SOURCE_TEXT_CHARS: int = 10
    MIN_SOURCE_TEXT_WORDS: int = 3
    SOURCE_ACCUM_MAX_SEC: float = 1.5
    SOURCE_ACCUM_HARD_MAX_SEC: float = 4.2
    MAX_TTS_TEXT_CHARS: int = 90
    MIN_TTS_TEXT_CHARS: int = 10
    TTS_BATCH_WINDOW_SEC: float = _env_float("TTS_BATCH_WINDOW_SEC", 0.45)
    TTS_BATCH_MAX_ITEMS: int = _env_int("TTS_BATCH_MAX_ITEMS", 3)
    TTS_BUFFER_MIN_CHARS: int = _env_int("TTS_BUFFER_MIN_CHARS", 26)
    TTS_BUFFER_MAX_AGE_SEC: float = _env_float("TTS_BUFFER_MAX_AGE_SEC", 1.4)
    REPEAT_SOURCE_COOLDOWN_SEC: float = 4.0
    REPEAT_TTS_COOLDOWN_SEC: float = 14.0
    MAX_TTS_CHUNKS_PER_TRANSLATION: int = 4
    ECHO_MEMORY_SEC: float = 12.0
    ECHO_OVERLAP_THRESHOLD: float = 0.72

    @property
    def CHUNK_SIZE(self) -> int:
        return int(self.SAMPLE_RATE * self.CHUNK_DURATION_SEC)


CONFIG = AppConfig()

SAMPLE_RATE = CONFIG.SAMPLE_RATE
CHUNK_SIZE = CONFIG.CHUNK_SIZE
DEEPGRAM_API_KEY = CONFIG.DEEPGRAM_API_KEY
GROQ_API_KEY = CONFIG.GROQ_API_KEY
PIPER_MODEL_PATH = CONFIG.PIPER_MODEL_PATH

import json
import logging
import threading
from typing import Any

from live_translator.app_paths import get_ai_trace_path, get_stt_trace_path


_trace_lock = threading.Lock()
_stt_logger: logging.Logger | None = None
_ai_logger: logging.Logger | None = None


def get_stt_log_path() -> str:
    return get_stt_trace_path()


def get_ai_log_path() -> str:
    return get_ai_trace_path()


def _setup_named_logger(name: str, path: str) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        formatter = logging.Formatter(
            fmt="%(asctime)s.%(msecs)03d %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler = logging.FileHandler(path, encoding="utf-8")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger


def setup_trace_loggers() -> tuple[logging.Logger, logging.Logger]:
    global _stt_logger, _ai_logger
    if _stt_logger is not None and _ai_logger is not None:
        return _stt_logger, _ai_logger

    with _trace_lock:
        if _stt_logger is None:
            _stt_logger = _setup_named_logger("live_translator.stt_trace", get_stt_trace_path())
        if _ai_logger is None:
            _ai_logger = _setup_named_logger("live_translator.ai_trace", get_ai_trace_path())
    return _stt_logger, _ai_logger


def _compact_text(text: str) -> str:
    return " ".join((text or "").strip().split())


def _safe_fields(payload: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, str):
            cleaned[key] = _compact_text(value)
        else:
            cleaned[key] = value
    return cleaned


def log_stt_trace(session_id: str, seq: int, text: str, **fields: Any) -> None:
    if not text or not text.strip():
        return
    stt_logger, _ = setup_trace_loggers()
    payload = {
        "session": session_id,
        "seq": seq,
        "text": _compact_text(text),
    }
    payload.update(fields)
    stt_logger.info(json.dumps(_safe_fields(payload), ensure_ascii=False))


def log_ai_trace(
    session_id: str,
    seq: int,
    provider: str,
    source_text: str,
    translated_text: str,
    status: str,
    **fields: Any,
) -> None:
    _, ai_logger = setup_trace_loggers()
    payload = {
        "session": session_id,
        "seq": seq,
        "provider": provider or "unknown",
        "status": status,
        "source_text": _compact_text(source_text),
        "translated_text": _compact_text(translated_text),
    }
    payload.update(fields)
    ai_logger.info(json.dumps(_safe_fields(payload), ensure_ascii=False))

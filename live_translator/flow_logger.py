import logging
import threading
from typing import Any

from live_translator.app_paths import get_log_path as resolve_log_path


LOG_PATH = resolve_log_path()
_logger_lock = threading.Lock()
_logger: logging.Logger | None = None


def get_log_path() -> str:
    return LOG_PATH


def setup_flow_logger() -> logging.Logger:
    global _logger
    if _logger is not None:
        return _logger

    with _logger_lock:
        if _logger is not None:
            return _logger

        logger = logging.getLogger("live_translator")
        logger.setLevel(logging.INFO)
        logger.propagate = False

        if not logger.handlers:
            formatter = logging.Formatter(
                fmt="%(asctime)s.%(msecs)03d [%(threadName)s] %(levelname)s %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )

            file_handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)

        _logger = logger
        return logger


def flow_log(stage: str, event: str, **fields: Any) -> None:
    logger = setup_flow_logger()
    if fields:
        payload = " ".join(f"{key}={value}" for key, value in fields.items())
        logger.info("%s.%s %s", stage, event, payload)
        return
    logger.info("%s.%s", stage, event)

import json
import os
import shutil
from dataclasses import dataclass

from live_translator.app_paths import get_asset_base_dir, get_settings_path
from live_translator.config import CONFIG
from live_translator.secure_store import SecureSecretStore


SETTINGS_PATH = get_settings_path()
LEGACY_SETTINGS_PATH = os.path.join(get_asset_base_dir(), "runtime_settings.json")

SECRET_KEYS = ("groq_api_key", "gemini_api_key", "deepseek_api_key", "deepgram_api_key")
SECRET_STORE = SecureSecretStore()


def _detect_provider_from_key(token: str) -> str | None:
    probe = token.strip()
    if not probe:
        return None
    if probe.startswith("gsk_"):
        return "groq"
    if probe.startswith("AIza"):
        return "gemini"
    if probe.startswith("sk-"):
        return "deepseek"
    return None


def _coerce_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        probe = value.strip().lower()
        if probe in {"1", "true", "yes", "on"}:
            return True
        if probe in {"0", "false", "no", "off"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def _read_json(path: str) -> dict:
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
        if isinstance(data, dict):
            return data
    except Exception:
        return {}
    return {}


def _sanitize_payload(data: dict) -> dict:
    cleaned = dict(data)
    for key in SECRET_KEYS:
        cleaned.pop(key, None)
    return cleaned


def _write_json(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)


@dataclass
class RuntimeSettings:
    provider: str = "gemini"
    fallback_enabled: bool = True
    deepgram_api_key: str = os.getenv("DEEPGRAM_API_KEY", "")
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    groq_model: str = CONFIG.GROQ_MODEL
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    deepseek_api_key: str = os.getenv("DEEPSEEK_API_KEY", "")
    deepseek_model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    def normalized_provider(self) -> str:
        provider = self.provider.strip().lower()
        if provider == "deepseek":
            return "deepseek"
        if provider == "groq":
            return "groq"
        return "gemini"


def _migrate_legacy_settings_file() -> None:
    if os.path.isfile(SETTINGS_PATH) or not os.path.isfile(LEGACY_SETTINGS_PATH):
        return
    try:
        os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
        shutil.copyfile(LEGACY_SETTINGS_PATH, SETTINGS_PATH)
    except Exception:
        return


def _read_secret(name: str, fallback: str) -> str:
    try:
        value = SECRET_STORE.get_secret(name)
        if value:
            return value
    except Exception:
        pass
    return fallback


def _write_secret(name: str, value: str) -> None:
    try:
        SECRET_STORE.set_secret(name, value)
    except Exception:
        # Fail closed for persistence: runtime still works for current session.
        pass


def load_runtime_settings() -> RuntimeSettings:
    _migrate_legacy_settings_file()
    defaults = RuntimeSettings()
    data = _read_json(SETTINGS_PATH)

    provider = str(data.get("primary_provider", data.get("provider", defaults.provider)))
    fallback_enabled = _coerce_bool(data.get("fallback_enabled", defaults.fallback_enabled), defaults.fallback_enabled)
    groq_model = str(data.get("groq_model", defaults.groq_model))
    gemini_model = str(data.get("gemini_model", defaults.gemini_model))
    deepseek_model = str(data.get("deepseek_model", defaults.deepseek_model))

    migrated = False
    legacy_groq = str(data.get("groq_api_key", defaults.groq_api_key)).strip()
    legacy_gemini = str(data.get("gemini_api_key", defaults.gemini_api_key)).strip()
    legacy_deepseek = str(data.get("deepseek_api_key", defaults.deepseek_api_key)).strip()
    legacy_deepgram = str(data.get("deepgram_api_key", defaults.deepgram_api_key)).strip()

    groq_api_key = _read_secret("groq_api_key", legacy_groq)
    gemini_api_key = _read_secret("gemini_api_key", legacy_gemini)
    deepseek_api_key = _read_secret("deepseek_api_key", legacy_deepseek)
    deepgram_api_key = _read_secret("deepgram_api_key", legacy_deepgram)

    if legacy_groq:
        _write_secret("groq_api_key", legacy_groq)
        migrated = True
    if legacy_gemini:
        _write_secret("gemini_api_key", legacy_gemini)
        migrated = True
    if legacy_deepseek:
        _write_secret("deepseek_api_key", legacy_deepseek)
        migrated = True
    if legacy_deepgram:
        _write_secret("deepgram_api_key", legacy_deepgram)
        migrated = True

    key_map = {
        "groq": groq_api_key,
        "gemini": gemini_api_key,
        "deepseek": deepseek_api_key,
    }
    auto_routed = False
    for source_provider in ("groq", "gemini", "deepseek"):
        source_key = key_map[source_provider]
        detected_provider = _detect_provider_from_key(source_key)
        if detected_provider is None or detected_provider == source_provider:
            continue
        if key_map[detected_provider]:
            continue
        key_map[detected_provider] = source_key
        key_map[source_provider] = ""
        auto_routed = True

    if auto_routed:
        groq_api_key = key_map["groq"]
        gemini_api_key = key_map["gemini"]
        deepseek_api_key = key_map["deepseek"]
        _write_secret("groq_api_key", groq_api_key)
        _write_secret("gemini_api_key", gemini_api_key)
        _write_secret("deepseek_api_key", deepseek_api_key)
        migrated = True

    if migrated or any(key in data for key in SECRET_KEYS):
        _write_json(SETTINGS_PATH, _sanitize_payload(data))
        if os.path.isfile(LEGACY_SETTINGS_PATH):
            try:
                legacy_data = _read_json(LEGACY_SETTINGS_PATH)
                if legacy_data:
                    _write_json(LEGACY_SETTINGS_PATH, _sanitize_payload(legacy_data))
            except Exception:
                pass

    return RuntimeSettings(
        provider=provider,
        fallback_enabled=fallback_enabled,
        deepgram_api_key=deepgram_api_key,
        groq_api_key=groq_api_key,
        groq_model=groq_model,
        gemini_api_key=gemini_api_key,
        gemini_model=gemini_model,
        deepseek_api_key=deepseek_api_key,
        deepseek_model=deepseek_model,
    )


def save_runtime_settings(settings: RuntimeSettings) -> None:
    _write_secret("deepgram_api_key", settings.deepgram_api_key.strip())
    _write_secret("groq_api_key", settings.groq_api_key.strip())
    _write_secret("gemini_api_key", settings.gemini_api_key.strip())
    _write_secret("deepseek_api_key", settings.deepseek_api_key.strip())

    payload = {
        "provider": settings.normalized_provider(),
        "primary_provider": settings.normalized_provider(),
        "fallback_enabled": bool(settings.fallback_enabled),
        "groq_model": settings.groq_model.strip() or CONFIG.GROQ_MODEL,
        "gemini_model": settings.gemini_model.strip() or "gemini-2.0-flash",
        "deepseek_model": settings.deepseek_model.strip() or "deepseek-chat",
    }
    _write_json(SETTINGS_PATH, payload)


def clear_runtime_api_keys() -> None:
    SECRET_STORE.clear_all()

    for path in (SETTINGS_PATH, LEGACY_SETTINGS_PATH):
        if not os.path.isfile(path):
            continue
        data = _read_json(path)
        if not data:
            continue
        _write_json(path, _sanitize_payload(data))

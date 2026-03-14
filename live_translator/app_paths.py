import os
import sys


def get_asset_base_dir() -> str:
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            return os.path.abspath(meipass)
        return os.path.abspath(os.path.dirname(sys.executable))
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def get_user_data_dir() -> str:
    custom = os.getenv("LIVETRADUTOR_HOME", "").strip()
    if custom:
        path = os.path.abspath(custom)
    else:
        appdata = os.getenv("APPDATA", "").strip()
        if appdata:
            path = os.path.join(appdata, "LiveTradutor")
        else:
            path = os.path.join(os.path.expanduser("~"), ".livetradutor")
    os.makedirs(path, exist_ok=True)
    return path


def get_settings_path() -> str:
    return os.path.join(get_user_data_dir(), "runtime_settings.json")


def get_secrets_db_path() -> str:
    return os.path.join(get_user_data_dir(), "secure_secrets.db")


def get_log_path() -> str:
    return os.path.join(get_user_data_dir(), "live_translator.log")


def get_stt_trace_path() -> str:
    return os.path.join(get_user_data_dir(), "stt_transcript.log")


def get_ai_trace_path() -> str:
    return os.path.join(get_user_data_dir(), "ai_translation.log")

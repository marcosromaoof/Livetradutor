import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DIST_DIR = ROOT / "dist"
BUILD_DIR = ROOT / "build"
SPEC_PATH = ROOT / "livetradutor.spec"


def run(cmd: list[str]) -> None:
    print(">", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=ROOT)


def ensure_assets() -> None:
    piper_dir = ROOT / "piper"
    if not piper_dir.exists():
        raise RuntimeError(f"Pasta piper ausente: {piper_dir}")


def clean_previous() -> None:
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)


def main() -> None:
    if not SPEC_PATH.exists():
        raise RuntimeError(f"Spec nao encontrado: {SPEC_PATH}")

    ensure_assets()
    clean_previous()

    run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
    run([sys.executable, "-m", "pip", "install", "-r", "requirements-build.txt"])
    run([sys.executable, "-m", "PyInstaller", str(SPEC_PATH), "--noconfirm", "--clean"])

    exe_path = DIST_DIR / "LiveTradutor" / "LiveTradutor.exe"
    if not exe_path.exists():
        raise RuntimeError(f"EXE nao gerado: {exe_path}")

    print(f"\nBuild concluido com sucesso: {exe_path}")
    print("Distribua a pasta inteira dist\\LiveTradutor")


if __name__ == "__main__":
    main()

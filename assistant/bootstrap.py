"""First-run provisioning: ensure Ollama and the STT model are ready.

Invoked as ``assistant doctor`` from the frozen binary. Idempotent; mirrors
``install.sh`` steps 7-8 (setup_ollama, prewarm_stt). The daemon itself only
health-checks Ollama and degrades gracefully, so this is provisioning — not a
hard dependency at every boot.
"""

from __future__ import annotations

import shutil
import subprocess
import time
import urllib.request

from assistant.core.config import Config


def _ollama_up(host: str) -> bool:
    try:
        with urllib.request.urlopen(f"{host}/api/version", timeout=3) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001 - any failure means "not reachable"
        return False


def _ensure_ollama_installed() -> bool:
    if shutil.which("ollama"):
        print("[doctor] ollama already installed")
        return True
    if shutil.which("pacman"):
        print("[doctor] installing Ollama via pacman ...")
        subprocess.run(["sudo", "pacman", "-S", "--needed", "--noconfirm", "ollama"], check=False)
    else:
        print("[doctor] installing Ollama via official script ...")
        try:
            dl = subprocess.run(
                ["curl", "-fsSL", "https://ollama.com/install.sh"],
                check=True, capture_output=True, text=True,
            )
            subprocess.run(["sh"], input=dl.stdout, check=True, text=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[doctor] automatic install failed ({exc}); install Ollama manually.")
            return False
    return shutil.which("ollama") is not None


def _ensure_serving(host: str) -> bool:
    if _ollama_up(host):
        print("[doctor] ollama daemon already running")
        return True
    if shutil.which("systemctl"):
        subprocess.run(["systemctl", "--user", "start", "ollama"], check=False,
                       capture_output=True)
    if not _ollama_up(host) and shutil.which("ollama"):
        print("[doctor] starting `ollama serve` in the background ...")
        subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    for _ in range(20):
        if _ollama_up(host):
            return True
        time.sleep(1)
    return _ollama_up(host)


def _ensure_model(model: str) -> None:
    out = subprocess.run(["ollama", "list"], capture_output=True, text=True)
    if any(line.split()[:1] == [model] for line in out.stdout.splitlines()):
        print(f"[doctor] model {model} already present")
        return
    print(f"[doctor] pulling {model} (this can be ~2 GB) ...")
    subprocess.run(["ollama", "pull", model], check=False)


def _prewarm_stt(cfg: Config) -> None:
    print(f"[doctor] pre-downloading faster-whisper {cfg.stt.model} ...")
    from faster_whisper import WhisperModel

    WhisperModel(cfg.stt.model, device="cpu", compute_type=cfg.stt.compute_type)
    print("[doctor] STT model cached")


def run(args: list[str]) -> int:
    cfg = Config()
    host = cfg.llm.host
    ok = True

    if _ensure_ollama_installed() and _ensure_serving(host):
        _ensure_model(cfg.llm.model)
    else:
        print("[doctor] Ollama not reachable; start it and re-run `assistant doctor`.")
        ok = False

    if "--no-stt" not in args:
        try:
            _prewarm_stt(cfg)
        except Exception as exc:  # noqa: BLE001
            print(f"[doctor] STT prewarm failed: {exc}")
            ok = False

    print("[doctor] done." if ok else "[doctor] finished with warnings.")
    return 0 if ok else 1

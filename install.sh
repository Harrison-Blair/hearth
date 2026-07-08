#!/usr/bin/env bash
#
# install.sh — install dependencies and set up personal-assistant to run.
#
# Full setup by default; every step is individually disable-able via a flag.
# Optionally installs a user-level systemd unit (off unless --systemd is passed).
# Native packages support Arch (pacman) and Debian/Raspberry Pi OS (apt).
#
# Run ./install.sh --help for the full option list.

set -euo pipefail

# --- Resolve repo root (the assistant must run with cwd = repo root) ----------
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

# --- Defaults -----------------------------------------------------------------
DO_NATIVE=1
DO_VENV=1
DO_PIP=1
DO_WAKE=1
DO_PIPER_VOICE=1
DO_OLLAMA=1
DO_PREWARM_STT=0
DO_SYSTEMD=0
SYSTEMD_ENABLE=1            # only relevant when DO_SYSTEMD=1

EXTRAS="all,dev"
OLLAMA_MODEL="qwen2.5:3b-instruct"
PIPER_VOICE="en_US-lessac-medium"
PYTHON_BIN=""              # auto-detect unless --python given

OWW_VERSION="0.6.0"
PIPER_VOICES_BASE="https://huggingface.co/rhasspy/piper-voices/resolve/main"
SERVICE_NAME="personal-assistant"

VENV="$REPO_ROOT/.venv"
VPY="$VENV/bin/python"
VPIP="$VENV/bin/pip"

# --- Output helpers -----------------------------------------------------------
if [[ -t 1 ]]; then
    BLUE=$'\033[1;34m'; YELLOW=$'\033[1;33m'; RED=$'\033[1;31m'; DIM=$'\033[2m'; RESET=$'\033[0m'
else
    BLUE=""; YELLOW=""; RED=""; DIM=""; RESET=""
fi
section() { printf '\n%s==> %s%s\n' "$BLUE" "$1" "$RESET"; }
log()     { printf '    %s\n' "$1"; }
skip()    { printf '    %sskip: %s%s\n' "$DIM" "$1" "$RESET"; }
warn()    { printf '%swarning:%s %s\n' "$YELLOW" "$RESET" "$1" >&2; }
die()     { printf '%serror:%s %s\n' "$RED" "$RESET" "$1" >&2; exit 1; }

usage() {
    cat <<'EOF'
Usage: ./install.sh [options]

Installs dependencies and sets up personal-assistant to run. Full setup runs by
default; disable any step with its --no-<step> flag. Re-running is safe.

Steps (ON by default; pass --no-<step> to skip):
  --no-native         Skip system packages (PortAudio).
  --no-venv           Reuse an existing .venv instead of creating it.
  --no-pip            Skip the pip install of extras.
  --no-wake           Skip openWakeWord + feature/stock-model download.
  --no-piper-voice    Skip the Piper TTS voice download.
  --no-ollama         Skip Ollama install, daemon start, and model pull.

Optional steps (OFF by default):
  --prewarm-stt       Pre-download the faster-whisper base.en model now.
  --systemd           Install + enable a --user systemd unit (auto-start).
  --systemd-no-enable Write the unit file but do not enable/start it.

Tunables:
  --extras LIST       pip extras to install (default: all,dev).
  --ollama-model M    Ollama model to pull (default: qwen2.5:3b-instruct).
  --piper-voice V     Piper voice id (default: en_US-lessac-medium).
  --python BIN        Python interpreter to build the venv from (default: auto).
  -h, --help          Show this help and exit.

Convenience:
  --minimal           Equivalent to --no-ollama --no-piper-voice.
EOF
}

# --- Argument parsing ---------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-native)        DO_NATIVE=0 ;;
        --no-venv)          DO_VENV=0 ;;
        --no-pip)           DO_PIP=0 ;;
        --no-wake)          DO_WAKE=0 ;;
        --no-piper-voice)   DO_PIPER_VOICE=0 ;;
        --no-ollama)        DO_OLLAMA=0 ;;
        --prewarm-stt)      DO_PREWARM_STT=1 ;;
        --systemd)          DO_SYSTEMD=1; SYSTEMD_ENABLE=1 ;;
        --systemd-no-enable) DO_SYSTEMD=1; SYSTEMD_ENABLE=0 ;;
        --minimal)          DO_OLLAMA=0; DO_PIPER_VOICE=0 ;;
        --extras)           EXTRAS="${2:?--extras needs a value}"; shift ;;
        --extras=*)         EXTRAS="${1#*=}" ;;
        --ollama-model)     OLLAMA_MODEL="${2:?--ollama-model needs a value}"; shift ;;
        --ollama-model=*)   OLLAMA_MODEL="${1#*=}" ;;
        --piper-voice)      PIPER_VOICE="${2:?--piper-voice needs a value}"; shift ;;
        --piper-voice=*)    PIPER_VOICE="${1#*=}" ;;
        --python)           PYTHON_BIN="${2:?--python needs a value}"; shift ;;
        --python=*)         PYTHON_BIN="${1#*=}" ;;
        -h|--help)          usage; exit 0 ;;
        *)                  usage >&2; die "unknown option: $1" ;;
    esac
    shift
done

# --- Shared helpers -----------------------------------------------------------
PKG=""                     # set by detect_platform
SUDO=""                    # set by detect_platform

detect_platform() {
    section "Detecting platform"
    if command -v pacman >/dev/null 2>&1; then
        PKG="pacman"
    elif command -v apt-get >/dev/null 2>&1; then
        PKG="apt"
    else
        PKG=""
    fi
    if [[ $EUID -ne 0 ]] && command -v sudo >/dev/null 2>&1; then
        SUDO="sudo"
    fi
    log "package manager: ${PKG:-none (pacman/apt not found)}"
    log "repo root:       $REPO_ROOT"
}

# --- Step 1: native packages --------------------------------------------------
install_native() {
    section "System packages (PortAudio)"
    case "$PKG" in
        pacman)
            $SUDO pacman -S --needed --noconfirm portaudio
            ;;
        apt)
            $SUDO apt-get update
            $SUDO apt-get install -y libportaudio2 portaudio19-dev
            ;;
        *)
            warn "no supported package manager (pacman/apt); install PortAudio manually."
            ;;
    esac
}

# --- Step 2: pick a Python interpreter ---------------------------------------
# Echoes a usable interpreter path/name (>=3.11), or exits.
py_ok() {
    # $1 = interpreter; succeed if it is Python >= 3.11
    "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null
}

pick_python() {
    section "Selecting Python interpreter"
    local candidate=""
    if [[ -n "$PYTHON_BIN" ]]; then
        command -v "$PYTHON_BIN" >/dev/null 2>&1 || die "--python '$PYTHON_BIN' not found on PATH"
        py_ok "$PYTHON_BIN" || die "--python '$PYTHON_BIN' is not Python >= 3.11"
        candidate="$PYTHON_BIN"
    else
        local c
        for c in python3.12 python3.13 python3.11; do
            if command -v "$c" >/dev/null 2>&1 && py_ok "$c"; then candidate="$c"; break; fi
        done
        if [[ -z "$candidate" ]] && command -v pyenv >/dev/null 2>&1; then
            # Honor the repo's .python-version (3.12.13) if pyenv provides it.
            local pyenv_py
            pyenv_py="$(pyenv which python 2>/dev/null || true)"
            if [[ -n "$pyenv_py" ]] && py_ok "$pyenv_py"; then candidate="$pyenv_py"; fi
        fi
        if [[ -z "$candidate" ]] && command -v python3 >/dev/null 2>&1 && py_ok python3; then
            candidate="python3"
        fi
    fi
    [[ -n "$candidate" ]] || die "no Python >= 3.11 found. Install python 3.12 (see README: pyenv install 3.12) or pass --python."
    PYTHON_BIN="$candidate"
    log "using: $PYTHON_BIN ($("$PYTHON_BIN" --version 2>&1))"
}

# --- Step 3: virtualenv -------------------------------------------------------
make_venv() {
    section "Virtual environment (.venv)"
    if [[ -x "$VPY" ]]; then
        skip ".venv already exists"
    else
        "$PYTHON_BIN" -m venv "$VENV"
        log "created $VENV"
    fi
    "$VPY" -m pip install --quiet --upgrade pip
    log "pip upgraded"
}

# --- Step 4: pip extras -------------------------------------------------------
pip_install() {
    section "Python dependencies (.[$EXTRAS])"
    [[ -x "$VPIP" ]] || die ".venv not found; rerun without --no-venv"
    "$VPIP" install -e ".[$EXTRAS]"
}

# --- Step 5: wake word (openWakeWord, ONNX backend) ---------------------------
setup_wake() {
    section "Wake word (openWakeWord, ONNX backend)"
    [[ -x "$VPY" ]] || die ".venv not found; rerun without --no-venv"
    if "$VPY" -c 'import openwakeword' 2>/dev/null; then
        skip "openwakeword already installed"
    else
        # --no-deps avoids its tflite-runtime pin (no 3.12 wheel); we use ONNX.
        "$VPIP" install --no-deps "openwakeword==$OWW_VERSION"
    fi
    # Feature models (melspectrogram + embedding) — required by the ONNX detector.
    log "downloading openWakeWord feature models + stock hey_jarvis"
    "$VPY" - <<'PY'
import openwakeword.utils as u
u.download_models([])            # melspectrogram + embedding feature models
u.download_models(['hey_jarvis'])  # stock fallback wake model
PY
    if [[ ! -f "$REPO_ROOT/models/wake/hey_assistant.onnx" ]]; then
        warn "custom wake model models/wake/hey_assistant.onnx is absent."
        log  "config.yaml points wake.model_path at it. Either:"
        log  "  - fall back to stock hey_jarvis: set wake.model_path: null in config.yaml"
        log  "    (or export ASSISTANT_WAKE__MODEL_PATH= to clear it), or"
        log  "  - train it: bash training/bootstrap.sh && bash training/train.sh  (heavy)"
    fi
}

# --- Step 6: Piper TTS voice --------------------------------------------------
download_piper_voice() {
    section "Piper TTS voice ($PIPER_VOICE)"
    command -v curl >/dev/null 2>&1 || die "curl is required to download the Piper voice"
    local dir="$REPO_ROOT/models/piper"
    mkdir -p "$dir"
    # Voice id like en_US-lessac-medium -> en/en_US/lessac/medium on the HF repo.
    local lang_full="${PIPER_VOICE%%-*}"          # en_US
    local lang="${lang_full%%_*}"                 # en
    local rest="${PIPER_VOICE#*-}"                # lessac-medium
    local name="${rest%%-*}"                      # lessac
    local quality="${rest#*-}"                    # medium
    local url_dir="$PIPER_VOICES_BASE/$lang/$lang_full/$name/$quality"
    local f
    for f in "$PIPER_VOICE.onnx" "$PIPER_VOICE.onnx.json"; do
        if [[ -f "$dir/$f" ]]; then
            skip "$f already present"
        else
            log "downloading $f"
            curl -fL --retry 3 -o "$dir/$f" "$url_dir/$f" \
                || die "failed to download $f from $url_dir/$f"
        fi
    done
}

# --- Step 7: Ollama -----------------------------------------------------------
ollama_up() { curl -fsS --max-time 3 http://localhost:11434/api/version >/dev/null 2>&1; }

setup_ollama() {
    section "Ollama (local LLM: $OLLAMA_MODEL)"
    if ! command -v ollama >/dev/null 2>&1; then
        case "$PKG" in
            pacman) $SUDO pacman -S --needed --noconfirm ollama ;;
            *)      log "installing Ollama via official script"
                    curl -fsSL https://ollama.com/install.sh | sh ;;
        esac
    else
        skip "ollama already installed"
    fi

    if ollama_up; then
        skip "ollama daemon already running"
    elif command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files ollama.service >/dev/null 2>&1; then
        log "starting ollama.service"
        $SUDO systemctl enable --now ollama.service || true
    fi
    if ! ollama_up; then
        log "starting 'ollama serve' in the background"
        nohup ollama serve >/tmp/ollama-serve.log 2>&1 &
        local i
        for i in $(seq 1 20); do ollama_up && break; sleep 1; done
    fi
    ollama_up || { warn "Ollama daemon not reachable; skipping model pull. Start it with 'ollama serve'."; return; }

    if ollama list 2>/dev/null | grep -q "^${OLLAMA_MODEL}[[:space:]]"; then
        skip "model $OLLAMA_MODEL already pulled"
    else
        log "pulling $OLLAMA_MODEL (~2 GB)"
        ollama pull "$OLLAMA_MODEL"
    fi
}

# --- Step 8: prewarm STT ------------------------------------------------------
prewarm_stt() {
    section "Pre-downloading faster-whisper base.en"
    "$VPY" - <<'PY'
from faster_whisper import WhisperModel
WhisperModel("base.en", compute_type="int8")
print("    base.en cached")
PY
}

# --- Step 9: systemd user unit ------------------------------------------------
setup_systemd() {
    section "systemd user service"
    command -v systemctl >/dev/null 2>&1 || die "systemctl not found; cannot install a systemd unit"
    local unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
    local unit="$unit_dir/$SERVICE_NAME.service"
    mkdir -p "$unit_dir"
    cat > "$unit" <<EOF
[Unit]
Description=Personal voice assistant
After=ollama.service network-online.target
Wants=ollama.service

[Service]
Type=simple
WorkingDirectory=$REPO_ROOT
ExecStart=$VPY -m assistant.app
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF
    log "wrote $unit"
    systemctl --user daemon-reload
    if [[ $SYSTEMD_ENABLE -eq 1 ]]; then
        systemctl --user enable --now "$SERVICE_NAME.service"
        # Linger lets the user service start at boot / survive logout.
        loginctl enable-linger "$USER" >/dev/null 2>&1 || warn "could not enable linger (needs privileges); service starts on login only."
        log "enabled and started; logs: journalctl --user -u $SERVICE_NAME -f"
    else
        log "unit written but not enabled. Enable with:"
        log "  systemctl --user enable --now $SERVICE_NAME.service"
    fi
}

# --- Run ----------------------------------------------------------------------
detect_platform
[[ $DO_NATIVE      -eq 1 ]] && install_native        || skip "system packages (--no-native)"
[[ $DO_VENV -eq 1 || $DO_PIP -eq 1 || $DO_WAKE -eq 1 || $DO_PREWARM_STT -eq 1 ]] && pick_python
[[ $DO_VENV        -eq 1 ]] && make_venv             || skip "venv (--no-venv)"
[[ $DO_PIP         -eq 1 ]] && pip_install           || skip "pip extras (--no-pip)"
[[ $DO_WAKE        -eq 1 ]] && setup_wake            || skip "wake word (--no-wake)"
[[ $DO_PIPER_VOICE -eq 1 ]] && download_piper_voice  || skip "Piper voice (--no-piper-voice)"
[[ $DO_OLLAMA      -eq 1 ]] && setup_ollama          || skip "Ollama (--no-ollama)"
[[ $DO_PREWARM_STT -eq 1 ]] && prewarm_stt           || skip "STT prewarm (default off; --prewarm-stt to enable)"
[[ $DO_SYSTEMD     -eq 1 ]] && setup_systemd         || skip "systemd unit (default off; --systemd to enable)"

# --- Summary ------------------------------------------------------------------
section "Done"
if [[ $DO_SYSTEMD -eq 1 && $SYSTEMD_ENABLE -eq 1 ]]; then
    log "Assistant running as a user service."
    log "Status: systemctl --user status $SERVICE_NAME"
    log "Logs:   journalctl --user -u $SERVICE_NAME -f"
else
    log "Run the assistant with:"
    log "  source .venv/bin/activate && python -m assistant.app"
fi

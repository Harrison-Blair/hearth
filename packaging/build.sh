#!/usr/bin/env bash
# Build the single-file `assistant` binary for the host architecture.
#
# Reproducible: fresh throwaway venv each run, pinned tool versions, mirrors
# install.sh's openWakeWord --no-deps quirk. PyInstaller cannot cross-compile,
# so run this natively on each target arch (x86_64 desktop, aarch64 Pi 5).
#
#   bash packaging/build.sh            # -> dist/assistant-$(uname -m)
#   PYTHON_BIN=python3.12 bash packaging/build.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

BUILD_VENV="$ROOT/.build-venv"
OWW_VERSION="0.6.0"

# Pick a Python 3.12 (native deps lack wheels for 3.13+/older). Mirrors
# install.sh's pick_python: honor PYTHON_BIN, else probe PATH, else pyenv.
py_ok() { "$1" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)' 2>/dev/null; }
PY=""
if [[ -n "${PYTHON_BIN:-}" ]]; then
    command -v "$PYTHON_BIN" >/dev/null 2>&1 && py_ok "$PYTHON_BIN" && PY="$PYTHON_BIN"
    [[ -n "$PY" ]] || { echo "error: --python '$PYTHON_BIN' is not Python 3.12" >&2; exit 1; }
else
    for c in python3.12 python3; do
        if command -v "$c" >/dev/null 2>&1 && py_ok "$c"; then PY="$c"; break; fi
    done
    if [[ -z "$PY" ]] && command -v pyenv >/dev/null 2>&1; then
        cand="$(pyenv which python3.12 2>/dev/null || pyenv which python 2>/dev/null || true)"
        [[ -n "$cand" ]] && py_ok "$cand" && PY="$cand"
    fi
fi
[[ -n "$PY" ]] || { echo "error: no Python 3.12 found; install it or pass PYTHON_BIN=" >&2; exit 1; }
echo "using: $PY ($("$PY" --version 2>&1))"

rm -rf "$BUILD_VENV" build dist
"$PY" -m venv "$BUILD_VENV"
VPIP="$BUILD_VENV/bin/pip"

"$VPIP" install --upgrade pip "setuptools<81" wheel   # <81 keeps pkg_resources for webrtcvad
"$VPIP" install -e ".[all,tui]"
"$VPIP" install --no-deps "openwakeword==$OWW_VERSION" # tflite pin has no 3.12 wheel; we use ONNX
"$VPIP" install "pyinstaller==6.*" pyinstaller-hooks-contrib

# openWakeWord feature models ship in the wheel, but ensure they're present
# (matches install.sh step 5) so the bundle is complete.
"$BUILD_VENV/bin/python" - <<'PY'
import openwakeword.utils as u
u.download_models([])             # melspectrogram + embedding feature models
u.download_models(['hey_jarvis']) # stock fallback wake model
PY

"$BUILD_VENV/bin/pyinstaller" --clean --noconfirm packaging/assistant.spec

ARCH="$(uname -m)"
OUT="dist/assistant-${ARCH}"
mv -f dist/assistant "$OUT"
echo "built: $OUT"
"$OUT" --version || true

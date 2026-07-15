#!/usr/bin/env bash
# Build training/.venv-train for livekit-wakeword training on the AMD RX 9070 XT
# (RDNA4/gfx1201 -> ROCm PyTorch). The hearth runtime venv never gets torch;
# the training deps live here only. Idempotent-ish: re-run to rebuild the venv.
set -euo pipefail
cd "$(dirname "$0")/.."
VENV=training/.venv-train

# System deps (Arch): espeak-ng libsndfile ffmpeg sox.
for bin in espeak-ng ffmpeg sox; do
  command -v "$bin" >/dev/null \
    || echo "WARNING: $bin not on PATH (Arch: sudo pacman -S espeak-ng libsndfile ffmpeg sox)"
done

# Build with the repo-pinned 3.12 (torch ROCm wheels lag the newest CPython, and a
# bare `python` here may be 3.14). Prefer python3.12, then the pyenv-managed one.
PY="$(command -v python3.12 || true)"
[ -z "$PY" ] && command -v pyenv >/dev/null && PY="$(pyenv which python3.12 2>/dev/null || true)"
[ -z "$PY" ] && PY=python
echo "using interpreter: $PY ($("$PY" --version 2>&1))"

"$PY" -m venv --clear "$VENV"   # --clear: rebuild from scratch, drop any stale deps
"$VENV/bin/pip" install --upgrade pip

# Torch + torchaudio FIRST from the ROCm index, so the livekit install below can't
# pull CUDA builds on top (livekit[train] depends on torchaudio, whose C++ extension
# hard-loads libcudart from the default-PyPI CUDA wheel and fails on an AMD box).
# gfx1201 (RDNA4) needs ROCm >= 6.4 wheels; if the 6.4 index lacks RDNA4 kernels,
# switch to the newest ROCm index (e.g. rocm6.5/7.x). HSA_OVERRIDE_GFX_VERSION does
# NOT apply to RDNA4 — there is no override fallback.
ROCM_INDEX=https://download.pytorch.org/whl/rocm6.4
"$VENV/bin/pip" install torch torchaudio --index-url "$ROCM_INDEX"
# Let the livekit install resolve its other deps from PyPI, but keep torch/torchaudio
# pinned to the ROCm builds we just installed.
"$VENV/bin/pip" install "livekit-wakeword[train,eval,export]" \
  --extra-index-url "$ROCM_INDEX"

# Assert we got the ROCm/HIP build and the GPU is actually usable.
"$VENV/bin/python" - <<'PY'
import torch
assert torch.version.hip, f"expected a ROCm/HIP torch build, got {torch.version.cuda=}"
assert torch.cuda.is_available(), "torch cannot see the GPU"
x = torch.randn(1024, 1024, device="cuda")
_ = (x @ x).sum().item()
print(f"torch {torch.__version__} (HIP {torch.version.hip}) — GPU OK: {torch.cuda.get_device_name(0)}")
PY

echo "bootstrap: training/.venv-train ready"

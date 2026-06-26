#!/usr/bin/env bash
# One-time setup for wake-word training. Idempotent: re-running skips finished steps.
# Run from the repo root:  bash training/bootstrap.sh
#
# Training uses an ISOLATED venv (training/.venv-train), not the project .venv:
# the 2023-era openWakeWord training stack pins old numpy/scipy that conflict with
# the assistant runtime. The runtime only consumes the trained .onnx, so the two
# never need to share an environment.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
DATA="training/data"
FORK="training/piper-sample-generator"
VENV="training/.venv-train"
mkdir -p "$DATA"

echo "==> [1/6] Creating isolated training venv (coherent older scientific stack)"
if [ ! -d "$VENV" ]; then
  # Build from the project's Python 3.12 interpreter.
  "$(command -v python3.12 || echo .venv/bin/python3.12)" -m venv "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"
pip install -U pip wheel >/dev/null

echo "==> [2/6] Installing training dependencies (CPU torch, no TensorFlow)"
# tflite export is skipped (runtime loads .onnx), so the whole TF stack is omitted.
# numpy<2 / scipy<1.15 keep acoustics + the old audio libs importable.
pip install "numpy==1.26.4" "scipy==1.13.1"
# Pin torch 2.7: newer torchaudio (>=2.9) drops native decoding and requires
# torchcodec, which doesn't support this system's FFmpeg 8. 2.7 decodes via soundfile.
pip install "torch==2.7.1" "torchaudio==2.7.1" --index-url https://download.pytorch.org/whl/cpu
pip install \
  torchinfo torchmetrics speechbrain==0.5.14 \
  audiomentations==0.33.0 torch-audiomentations==0.12.0 acoustics==0.2.6 \
  mutagen pronouncing deep-phonemizer espeak-phonemizer webrtcvad \
  onnx onnxruntime pyyaml tqdm requests librosa soundfile "pyarrow>=17"
pip install "openwakeword==0.6.0" --no-deps
# --no-deps skips the bundled feature models; fetch them (melspectrogram + embedding).
python -c "import openwakeword.utils as u; u.download_models([])"

echo "==> [3/6] Cloning piper-sample-generator (dscripka fork, espeak-based)"
if [ ! -d "$FORK" ]; then
  git clone --depth 1 https://github.com/dscripka/piper-sample-generator "$FORK"
fi
# torch>=2.6 defaults torch.load(weights_only=True), which rejects the VITS voice
# checkpoint. The voice is a trusted rhasspy release, so force weights_only=False.
sed -i 's/torch.load(model_path)/torch.load(model_path, weights_only=False)/' \
  "$FORK/generate_samples.py"

echo "==> [4/6] Downloading LibriTTS generator voice (~255 MB, resumable)"
VOICE="$FORK/models/en-us-libritts-high.pt"
if [ ! -s "$VOICE" ]; then
  curl -L -C - -o "$VOICE" \
    "https://github.com/rhasspy/piper-sample-generator/releases/download/v1.0.0/en-us-libritts-high.pt"
fi

echo "==> [5/6] Downloading pre-computed openWakeWord features (resumable)"
# 16 GB negative training features + ~170 MB false-positive validation set.
curl -L -C - -o "$DATA/openwakeword_features_ACAV100M_2000_hrs_16bit.npy" \
  "https://huggingface.co/datasets/davidscripka/openwakeword_features/resolve/main/openwakeword_features_ACAV100M_2000_hrs_16bit.npy"
curl -L -C - -o "$DATA/validation_set_features.npy" \
  "https://huggingface.co/datasets/davidscripka/openwakeword_features/resolve/main/validation_set_features.npy"

echo "==> [6/6] Building RIR + background audio datasets (16 kHz wav)"
python training/setup_data.py

echo "==> Bootstrap complete. Next:  bash training/train.sh --smoke   (fast validation run)"

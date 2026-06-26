#!/usr/bin/env bash
# Thin shim: run the train_batch dashboard under the isolated training venv from the
# repo root (so "bash training/train.sh" and training/work paths resolve). The real
# orchestrator is training/train_batch.py. See that file (and bootstrap.sh) for setup.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
exec training/.venv-train/bin/python training/train_batch.py "$@"

#!/usr/bin/env bash
# Build the single-file hearth binary for the host architecture.
# Output: dist/hearth-$(uname -m). PyInstaller can't cross-compile -- run once
# per target arch (x86_64 desktop, aarch64 Pi 5); CI (release.yml) does exactly
# that, natively on each runner.
set -euo pipefail
cd "$(dirname "$0")/.."

# Extras baked into the build venv. Release builds want everything; a local
# smoke build can trim, e.g. HEARTH_BUILD_EXTRAS="" for the bare runtime.
EXTRAS="${HEARTH_BUILD_EXTRAS-all}"

python3 -m venv .build-venv
.build-venv/bin/pip install --upgrade pip
if [ -n "$EXTRAS" ]; then
    .build-venv/bin/pip install ".[$EXTRAS]" pyinstaller
else
    .build-venv/bin/pip install "." pyinstaller
fi

# --add-data lands config.yaml at the bundle root (sys._MEIPASS), which is
# exactly where hearth.config's package-adjacent CONFIG_YAML_PATH resolves in
# the frozen binary. --collect-submodules guards the function-level hearth.*
# imports in app.py that static analysis would otherwise miss.
.build-venv/bin/pyinstaller \
    --onefile \
    --name "hearth-$(uname -m)" \
    --add-data "$(pwd)/config.yaml:." \
    --collect-submodules hearth \
    --specpath build \
    --noconfirm \
    packaging/entry.py

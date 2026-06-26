.PHONY: release clean

# Build the single-file binary for the host architecture.
# Run on each target arch (x86_64 desktop, aarch64 Pi 5) — PyInstaller can't
# cross-compile. Output: dist/assistant-$(uname -m)
release:
	bash packaging/build.sh

clean:
	rm -rf build dist .build-venv

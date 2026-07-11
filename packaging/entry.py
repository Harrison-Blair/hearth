"""PyInstaller entry point: a real script for the analyzer to start from."""
import sys

from hearth.app import main

if __name__ == "__main__":
    sys.exit(main())

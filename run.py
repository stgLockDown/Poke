#!/usr/bin/env python
"""Entrypoint shim so `python run.py` works even without installing the package.

Railway and Procfile-based deployments use this file.
"""
import sys
from pathlib import Path

# Add src/ to path so we can import pokealert without pip install -e .
SRC = Path(__file__).parent / "src"
if SRC.exists() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pokealert.main import app  # noqa: E402

if __name__ == "__main__":
    # If no arguments provided, default to "run"
    if len(sys.argv) == 1:
        sys.argv.append("run")
    app()
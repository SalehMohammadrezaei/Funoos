#!/usr/bin/env bash
# Funoos — one-step setup from source (Linux).
# Builds the C++ solver cores and installs the Python deps into a local venv.
set -e
cd "$(dirname "$0")"

echo "==> [1/3] Building the C++ solvers (needs g++ with OpenMP)…"
for d in lbm incompressible compressible sph; do
  make -C "solvers/$d"
done

echo "==> [2/3] Creating a virtual environment (.venv)…"
python3 -m venv .venv

echo "==> [3/3] Installing Python dependencies into .venv…"
.venv/bin/python -m pip install --upgrade pip >/dev/null
.venv/bin/python -m pip install -r requirements.txt

echo "==> [4/4] Checking for a GUI backend for pywebview (GTK/WebKit or Qt)…"
if .venv/bin/python - <<'PY'
import sys
try:
    import gi; gi.require_version("WebKit2", "4.1"); from gi.repository import WebKit2  # noqa
    print("GTK/WebKit2 found"); sys.exit(0)
except Exception:
    pass
try:
    import PyQt6.QtWebEngineWidgets  # noqa
    print("Qt WebEngine found"); sys.exit(0)
except Exception:
    pass
try:
    import PyQt5.QtWebEngineWidgets  # noqa
    print("Qt WebEngine (PyQt5) found"); sys.exit(0)
except Exception:
    pass
sys.exit(1)
PY
then :; else
  echo "   No GUI backend found. Install ONE of:"
  echo "     sudo apt install python3-gi gir1.2-webkit2-4.1        (GTK; then create the venv with --system-site-packages)"
  echo "     .venv/bin/python -m pip install 'pywebview[qt]'         (Qt)"
  echo "   See https://pywebview.flowrl.com/guide/installation.html"
fi

echo
echo "Done.  Launch Funoos with:   ./run.sh"

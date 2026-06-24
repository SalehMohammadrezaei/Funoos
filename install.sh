#!/usr/bin/env bash
# Funoos — one-step setup from source (Linux / macOS).
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

echo
echo "Done.  Launch Funoos with:   ./run.sh"

#!/usr/bin/env bash
# Funoos — one-step setup from source (Linux / macOS).
# Builds the C++ solver cores and installs the Python deps into a local venv.
set -e
cd "$(dirname "$0")"

# --- pick an OpenMP-capable C++ compiler ---
if [ "$(uname)" = "Darwin" ]; then
  if   command -v g++-14 >/dev/null 2>&1; then CXX=g++-14
  elif command -v g++-13 >/dev/null 2>&1; then CXX=g++-13
  elif command -v g++-12 >/dev/null 2>&1; then CXX=g++-12
  else CXX=""; fi
  if [ -n "$CXX" ]; then                       # Homebrew gcc: native OpenMP
    CXXFLAGS="-O3 -fopenmp -std=c++17 -Wall"
  else                                         # fall back to clang + libomp
    OMP="$(brew --prefix libomp 2>/dev/null || echo /usr/local/opt/libomp)"
    CXX=clang++
    CXXFLAGS="-O3 -std=c++17 -Wall -Xpreprocessor -fopenmp -I$OMP/include -L$OMP/lib -lomp"
    echo "    (using clang++ + libomp at $OMP — run 'brew install libomp' if this fails)"
  fi
else
  CXX="${CXX:-g++}"; CXXFLAGS="-O3 -march=native -fopenmp -std=c++17 -Wall"
fi
export CXX CXXFLAGS

echo "==> [1/3] Building the C++ solvers with $CXX …"
for d in lbm incompressible compressible sph; do
  make -C "solvers/$d" clean >/dev/null 2>&1 || true
  make -C "solvers/$d"
done

echo "==> [2/3] Creating a virtual environment (.venv)…"
python3 -m venv .venv

echo "==> [3/3] Installing Python dependencies into .venv…"
.venv/bin/python -m pip install --upgrade pip >/dev/null
.venv/bin/python -m pip install -r requirements.txt

echo
echo "Done.  Launch Funoos with:   ./run.sh"

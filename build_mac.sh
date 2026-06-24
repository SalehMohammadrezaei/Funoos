#!/usr/bin/env bash
# Funoos — macOS build script.  Produces dist/Funoos.app and dist/Funoos.dmg.
# Prereqs (one time):  brew install python gcc libomp   (gcc gives OpenMP; libomp is the clang fallback)
# Run on a Mac:  ./build_mac.sh
set -e
cd "$(dirname "$0")"

# --- OpenMP-capable compiler (same logic as install.sh) ---
if   command -v g++-14 >/dev/null 2>&1; then CXX=g++-14; CXXFLAGS="-O3 -fopenmp -std=c++17"
elif command -v g++-13 >/dev/null 2>&1; then CXX=g++-13; CXXFLAGS="-O3 -fopenmp -std=c++17"
elif command -v g++-12 >/dev/null 2>&1; then CXX=g++-12; CXXFLAGS="-O3 -fopenmp -std=c++17"
else
  OMP="$(brew --prefix libomp 2>/dev/null || echo /usr/local/opt/libomp)"
  CXX=clang++; CXXFLAGS="-O3 -std=c++17 -Xpreprocessor -fopenmp -I$OMP/include -L$OMP/lib -lomp"
fi
export CXX CXXFLAGS

echo "=== [1/4] Building the C++ solvers with $CXX ==="
for d in lbm incompressible compressible sph; do
  make -C "solvers/$d" clean >/dev/null 2>&1 || true; make -C "solvers/$d"
done

echo "=== [2/4] Python venv + dependencies + PyInstaller ==="
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip >/dev/null
.venv/bin/python -m pip install -r requirements.txt pyinstaller

echo "=== [3/4] Bundling Funoos.app (macOS uses ':' in --add-data) ==="
.venv/bin/pyinstaller --noconfirm --windowed --name Funoos \
  --add-data "index.html:." --add-data "web:web" \
  --add-data "solvers:solvers" --add-data "docs:docs" --add-data "results:results" \
  --collect-all webview --collect-all imageio_ffmpeg \
  funoos_app.py

echo "=== [4/4] Packaging dist/Funoos.dmg ==="
hdiutil create -volname Funoos -srcfolder "dist/Funoos.app" -ov -format UDZO "dist/Funoos.dmg"

echo
echo "=== SUCCESS ==="
echo "App:  dist/Funoos.app   (double-click to run)"
echo "DMG:  dist/Funoos.dmg   (hand this out)"
echo "Note: it is unsigned — first launch needs right-click > Open (Gatekeeper)."

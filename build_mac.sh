#!/usr/bin/env bash
# ============================================================================
#  Funoos - macOS build script (pywebview desktop app).
#  Produces  dist/Funoos.app  and a drag-to-Applications  Funoos-macOS-<arch>.dmg
#
#  Prerequisites (one-time):  brew install gcc dylibbundler   +  Python 3 with pip.
#  Apple's clang has no OpenMP, so the C++ solvers are built with Homebrew GCC and
#  libgomp/libstdc++ are linked STATICALLY, so the finished app needs nothing
#  installed on the user's Mac.  Runs unattended on a GitHub Actions macOS runner.
# ============================================================================
set -euo pipefail
cd "$(dirname "$0")"
ARCH=$(uname -m)                       # arm64 (Apple Silicon) or x86_64 (Intel)

GXX=$(ls /opt/homebrew/bin/g++-[0-9]* /usr/local/bin/g++-[0-9]* 2>/dev/null | sort -V | tail -1 || true)
[ -n "$GXX" ] || { echo "Homebrew GCC not found - run: brew install gcc"; exit 1; }
LIBGOMP_A=$("$GXX" -print-file-name=libgomp.a)
echo "=== [1/4] Building C++ solvers with $GXX (arch $ARCH) ==="

build_solver() {                       # usage: build_solver <dir> <name>
  local d=$1 n=$2
  local src="solvers/$d/$n.cpp" bin="solvers/$d/$n"
  rm -f "$bin" "$bin.o"; rm -rf "solvers/$d/libs"
  "$GXX" -O3 -fopenmp -std=c++17 -c "$src" -o "$bin.o"
  if [ -f "$LIBGOMP_A" ]; then
    "$GXX" -o "$bin" "$bin.o" -static-libgcc -static-libstdc++ "$LIBGOMP_A" -lpthread
  else
    "$GXX" -fopenmp -o "$bin" "$bin.o" -static-libgcc -static-libstdc++
  fi
  rm -f "$bin.o"
  # Anything still pointing at Homebrew gets copied next to the binary and re-pathed.
  if otool -L "$bin" | grep -qE "/opt/homebrew|/usr/local"; then
    echo "    bundling Homebrew dylibs for $n"
    dylibbundler -od -b -x "$bin" -d "solvers/$d/libs" -p @executable_path/libs >/dev/null
  fi
  if otool -L "$bin" | grep -qE "/opt/homebrew|/usr/local"; then
    echo "ERROR: $n still depends on Homebrew libraries:"; otool -L "$bin"; exit 1
  fi
  codesign --force -s - "$bin"         # ad-hoc signature: required to launch on Apple Silicon
  echo "    built $bin"
}
build_solver lbm            lbm2d
build_solver incompressible ins2d
build_solver compressible   euler2d
build_solver sph            sph2d

echo "=== [2/4] Installing Python dependencies ==="
python3 -m pip install --upgrade pip >/dev/null
python3 -m pip install -r requirements.txt pyinstaller

echo "=== [3/4] Bundling the app with PyInstaller ==="
rm -rf build dist
python3 -m PyInstaller --noconfirm --onedir --windowed --name Funoos \
  --add-data "index.html:." --add-data "web:web" \
  --add-data "solvers/lbm/lbm2d:solvers/lbm" --add-data "solvers/incompressible/ins2d:solvers/incompressible" --add-data "solvers/compressible/euler2d:solvers/compressible" --add-data "solvers/sph/sph2d:solvers/sph" --add-data "docs/eq:docs/eq" --add-data "results/gallery/*.mp4:results/gallery" --add-data "results/gallery/*.jpg:results/gallery" --add-data "LICENSE:." --add-data "THIRD_PARTY_NOTICES.md:." --add-data "CITATION.cff:." \
  --collect-all webview --collect-all imageio_ffmpeg \
  funoos_app.py
APP=dist/Funoos.app
[ -d "$APP" ] || { echo "ERROR: $APP was not produced"; exit 1; }
# make sure the bundled solvers stayed executable, then ad-hoc sign the whole bundle
find "$APP" -path "*/solvers/*" -type f \( -name lbm2d -o -name ins2d -o -name euler2d -o -name sph2d \) -exec chmod +x {} \;
codesign --force --deep -s - "$APP"

echo "=== [4/4] Creating the .dmg (drag Funoos -> Applications) ==="
STAGE=$(mktemp -d)
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
DMG="Funoos-macOS-$ARCH.dmg"; rm -f "$DMG"
hdiutil create -volname "Funoos" -srcfolder "$STAGE" -ov -format UDZO "$DMG"
rm -rf "$STAGE"

echo
echo "=== SUCCESS ==="
echo "App:  $APP"
echo "DMG:  $DMG   (hand this file out; users drag Funoos into Applications)"
echo "(First launch: right-click -> Open, because the app is not Apple-notarized.)"

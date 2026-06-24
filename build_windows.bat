@echo off
REM ============================================================================
REM  Funoos - Windows build script (pywebview desktop app).
REM  Produces a standalone app at  dist\Funoos\Funoos.exe
REM
REM  Prerequisites (one-time):
REM    * g++ with OpenMP on PATH  (MSYS2: `pacman -S mingw-w64-x86_64-gcc`, or w64devkit)
REM    * Python 3 with pip on PATH.
REM    * ffmpeg: handled automatically by the pip package imageio-ffmpeg (installed below).
REM      A separate ffmpeg install / bin\ffmpeg.exe is optional.
REM    * WebView2 runtime (preinstalled on Windows 10/11; else get the Evergreen runtime).
REM ============================================================================
setlocal

echo === [0/4] Cleaning old build\ and dist\ ===
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist

echo === [1/4] Building C++ solvers (statically linked, OpenMP) ===
g++ -O3 -fopenmp -static -std=c++17 -D_USE_MATH_DEFINES -o solvers\lbm\lbm2d.exe solvers\lbm\lbm2d.cpp || goto :err
g++ -O3 -fopenmp -static -std=c++17 -D_USE_MATH_DEFINES -o solvers\incompressible\ins2d.exe solvers\incompressible\ins2d.cpp || goto :err
g++ -O3 -fopenmp -static -std=c++17 -D_USE_MATH_DEFINES -o solvers\compressible\euler2d.exe solvers\compressible\euler2d.cpp || goto :err
g++ -O3 -fopenmp -static -std=c++17 -D_USE_MATH_DEFINES -o solvers\sph\sph2d.exe solvers\sph\sph2d.cpp || goto :err

echo === [2/4] Installing Python dependencies ===
python -m pip install --upgrade pip || goto :err
pip install numpy scipy matplotlib pillow pywebview imageio-ffmpeg pyinstaller || goto :err

echo === [3/4] Rendering gallery clips if missing (first build only; ~20-40 min) ===
if not exist results\gallery\spec_kh.mp4 python render_gallery.py High 1.8

echo === [4/4] Bundling the app with PyInstaller ===
set FF=
if exist bin\ffmpeg.exe set FF=--add-binary "bin\ffmpeg.exe;."
pyinstaller --noconfirm --onedir --windowed --name Funoos ^
  --add-data "index.html;." --add-data "web;web" ^
  --add-data "solvers;solvers" --add-data "docs;docs" --add-data "results;results" ^
  --collect-all webview --collect-all imageio_ffmpeg ^
  %FF% funoos_app.py || goto :err

echo.
echo === SUCCESS ===
echo App:  dist\Funoos\Funoos.exe
echo Next: open installer.iss in Inno Setup and click Compile to get Funoos-Setup.exe (a one-click installer to hand out).
echo (If the window is blank, install the WebView2 Evergreen runtime from Microsoft.)
echo (No ffmpeg.exe in bin\ ^=^> the player can't encode video; add it and rebuild.)
goto :eof

:err
echo.
echo *** BUILD FAILED -- see the messages above. ***
exit /b 1

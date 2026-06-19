@echo off
REM ============================================================================
REM  Funoos - Windows build script.
REM  Produces a standalone app at  dist\FunoosStudio\FunoosStudio.exe
REM
REM  Prerequisites (one-time):
REM    * g++ with OpenMP on PATH  (install MSYS2 then `pacman -S mingw-w64-x86_64-gcc`,
REM      or w64devkit) -- to compile the C++ solvers for Windows.
REM    * Python 3 with pip on PATH.
REM    * (optional) ffmpeg.exe placed in a  bin\  folder here, for GIF/MP4 export.
REM ============================================================================
setlocal

echo === [0/3] Cleaning old build\ and dist\ (so the .exe is always fresh) ===
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist

echo === [1/3] Building C++ solvers (statically linked, OpenMP) ===
g++ -O3 -fopenmp -static -std=c++17 -D_USE_MATH_DEFINES -o solvers\lbm\lbm2d.exe solvers\lbm\lbm2d.cpp || goto :err
g++ -O3 -fopenmp -static -std=c++17 -D_USE_MATH_DEFINES -o solvers\incompressible\ins2d.exe solvers\incompressible\ins2d.cpp || goto :err
g++ -O3 -fopenmp -static -std=c++17 -D_USE_MATH_DEFINES -o solvers\compressible\euler2d.exe solvers\compressible\euler2d.cpp || goto :err
g++ -O3 -fopenmp -static -std=c++17 -D_USE_MATH_DEFINES -o solvers\sph\sph2d.exe solvers\sph\sph2d.cpp || goto :err

echo === [2/3] Installing Python dependencies ===
python -m pip install --upgrade pip || goto :err
pip install numpy scipy matplotlib pillow customtkinter pyinstaller || goto :err

echo === [3/3] Bundling the app with PyInstaller ===
set FF=
if exist bin\ffmpeg.exe set FF=--add-binary "bin\ffmpeg.exe;."
pyinstaller --noconfirm --onedir --windowed --name FunoosStudio ^
  --add-data "solvers;solvers" --add-data "docs;docs" --add-data "results;results" --collect-all customtkinter ^
  %FF% studio.py || goto :err

echo.
echo === SUCCESS ===
echo App:  dist\FunoosStudio\FunoosStudio.exe
echo (GIF/MP4 export needs ffmpeg: put ffmpeg.exe in bin\ before building, or on PATH.)
echo To make an installer, open installer.iss with Inno Setup.
goto :eof

:err
echo.
echo *** BUILD FAILED -- see the messages above. ***
exit /b 1

# Building Funoos for Windows

The supported desktop app is `funoos_app.py` (a pywebview shell). The legacy
`studio.py` (CustomTkinter) is unsupported and not packaged.

## Prerequisites (one time)

* `g++` with OpenMP on PATH (MSYS2: `pacman -S mingw-w64-x86_64-gcc`, or w64devkit).
* Python 3.10–3.12 on PATH (the interpreter you run the script with is the one that
  gets packaged; the script uses `python -m pip`).
* The WebView2 Evergreen runtime (preinstalled on Windows 10/11; otherwise install it
  from Microsoft). The app checks for it at start-up and prints a hint if it is missing.
* ffmpeg: provided by the `imageio-ffmpeg` wheel; a `bin\ffmpeg.exe` is optional.

## Build

```bat
build_windows.bat
```

It builds the four solvers statically, installs the pinned requirements, renders the
gallery clips if they are missing (first build only), bundles the app with PyInstaller
into `dist\Funoos\Funoos.exe` — with only the assets the app needs (UI, solver
binaries, equation images, gallery MP4s; not the promotional videos) — runs the
packaged app's self-test (`Funoos.exe --selftest`: bundled solvers, font, encoder),
and writes `dist\Funoos.exe.sha256.txt`.

Then open `installer.iss` in Inno Setup and compile it to get `Funoos-Setup.exe`.
Publish the installer together with its SHA-256 (`certutil -hashfile Funoos-Setup.exe SHA256`)
on the release page so users can verify the download.

## Running from source instead

```bat
make -C solvers/lbm & make -C solvers/incompressible & make -C solvers/compressible & make -C solvers/sph
python -m pip install -r requirements.txt
python funoos_app.py
```

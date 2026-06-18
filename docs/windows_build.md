# Running FlowZoo on Windows

There are two ways to get FlowZoo Studio running on Windows. Pick one.

---

## Option A — Run it in WSL (easiest, zero build)

If you already use **WSL2 on Windows 11** (or recent Windows 10), the GUI works
out of the box via **WSLg** — no packaging needed:

```bash
# in your WSL Ubuntu terminal, inside the FlowZoo folder
make -C solvers/lbm && make -C solvers/incompressible
make -C solvers/compressible && make -C solvers/sph
pip install numpy scipy matplotlib pillow customtkinter
sudo apt install ffmpeg          # for GIF/MP4 export
python studio.py
```
The window opens on your Windows desktop. (Check `echo $DISPLAY` — if it prints
something like `:0`, WSLg is active.) This is the recommended path.

---

## Option B — Build a native Windows `.exe` + installer

This produces a standalone `FlowZooStudio.exe` (and an optional setup installer)
that runs on any Windows PC with no Python required.

### Prerequisites (one-time)
1. **A C++ compiler with OpenMP.** Easiest: install [MSYS2](https://www.msys2.org),
   then in its terminal `pacman -S mingw-w64-x86_64-gcc`, and add
   `C:\msys64\mingw64\bin` to your PATH. (Alternatively [w64devkit](https://github.com/skeeto/w64devkit).)
   Check: `g++ --version`.
2. **Python 3** with pip on PATH. Check: `python --version`.
3. *(optional)* **ffmpeg** — download a static `ffmpeg.exe` and drop it in a
   `bin\` folder here (or put it on PATH) so the app can export GIF/MP4.
4. *(optional)* **Inno Setup** (https://jrsoftware.org/isinfo.php) to build the installer.

### Build
From a terminal in the FlowZoo folder:
```bat
build_windows.bat
```
This compiles the four C++ solvers to `.exe`, installs the Python deps, and
bundles everything with PyInstaller. Result:
```
dist\FlowZooStudio\FlowZooStudio.exe
```
Double-click it to run. To **share** the app, copy the *whole*
`dist\FlowZooStudio\` folder — the `.exe` needs its sibling `_internal\` folder
(this is a one-folder PyInstaller build, not a single loose file).

### Make an installer (optional)
Open `installer.iss` in Inno Setup and click **Compile**. You get
`FlowZooStudio-Setup.exe` — a normal Windows installer with Start-menu and
desktop shortcuts.

---

### Notes
- The solvers are built **statically** (`-static`) so they need no MinGW DLLs at runtime.
- The animation **preview** works without ffmpeg; only **saving** GIF/MP4 needs it.
- Why no prebuilt exe in the repo? It must be compiled *on Windows* — PyInstaller
  cannot cross-compile from Linux/Mac, and the C++ binaries are OS-specific.

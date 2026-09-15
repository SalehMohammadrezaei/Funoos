# Third-party notices

Funoos is MIT-licensed (see LICENSE). The packaged application bundles or depends on
the following third-party software, each under its own licence:

| component | licence | use |
|---|---|---|
| NumPy | BSD-3-Clause | arrays, FFT |
| SciPy | BSD-3-Clause | numerics |
| Matplotlib | PSF-based (Matplotlib licence) | plots, colour maps, figure rendering; bundled DejaVu fonts (Bitstream Vera licence) |
| Pillow | HPND / MIT-CMU | image handling, text masks |
| pywebview | BSD-3-Clause | desktop window bridging Python and the HTML UI |
| imageio-ffmpeg | BSD-2-Clause; the bundled **FFmpeg** binary is GPL/LGPL (see https://ffmpeg.org/legal.html) | video/GIF encoding |
| Python | PSF licence | runtime (packaged builds) |
| DejaVu fonts | Bitstream Vera licence / public domain additions | text geometry and legends |

Windows builds additionally rely on the Microsoft Edge WebView2 runtime (Microsoft licence,
installed separately). macOS builds use WebKit (system).

These notices and the LICENSE file are included in every packaged release.

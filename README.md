# 🦓 FlowZoo

**A zoo of fluid phenomena — each one solved from scratch with a different numerical method, validated against a textbook benchmark, and rendered as a cinematic animation.**

Most CFD portfolios show one solver run one way. FlowZoo shows fluids from *five* angles — kinetic (lattice Boltzmann), continuum (Navier–Stokes), compressible (finite-volume shock capturing), meshfree (SPH), and spectral (FFT) — with the physics checked every time and the output built to be *watched*.

<p align="center">
  <img src="results/vortex_street.gif" alt="Kármán vortex street (LBM)" width="88%">
</p>
<p align="center"><em>Kármán vortex street behind a cylinder — lattice-Boltzmann, colored by vorticity.</em></p>

---

## The exhibits

| Exhibit | Method | Validation | Status |
|---|---|---|---|
| ★ **Flow around your name** | Lattice Boltzmann (D2Q9) | qualitative wake physics | 🚧 |
| **Kármán vortex street** | Lattice Boltzmann (D2Q9) | Strouhal number St ≈ 0.2 | ✅ |
| 🔥 **Rising smoke plume** | Incompressible Navier–Stokes (projection) | — | 🚧 |
| 🍄 **Rayleigh–Taylor instability** | Incompressible Navier–Stokes | — | 🚧 |
| 💥 **Explosion / blast wave** | Compressible Euler (finite-volume HLLC) | exact Sod solution | 🚧 |
| 🫧 **Shock–bubble interaction** | Compressible Euler | exact Sod solution | 🚧 |
| 🌊 **Dam break splash** | Smoothed-Particle Hydrodynamics | Martin–Moyce surge front | 🚧 |
| 🌀 **2D turbulence / Kelvin–Helmholtz** | Pseudo-spectral (FFT) | energy-spectrum slope | 🚧 |

*Each exhibit is a self-contained, validated demonstration of a numerical method. The signature exhibit lets you **type your own name** and watch vortices shed off the letters.*

## Why each method matters
- **Lattice Boltzmann** — a kinetic/mesoscopic view; trivially handles arbitrary geometry (any obstacle mask, even text).
- **Incompressible Navier–Stokes (projection method)** — the continuum workhorse; pressure–velocity coupling, buoyancy, scalar transport.
- **Compressible Euler (finite-volume, HLLC)** — hyperbolic conservation laws and shock capturing.
- **SPH** — a meshfree Lagrangian paradigm, natural for free surfaces and splashing.
- **Spectral (FFT)** — high-accuracy methods for turbulence and instabilities.

## Stack
**C++** (OpenMP) for the solver cores — fast enough on a CPU to run high resolution, which is what makes the output beautiful — and **Python** (NumPy / Pillow / Matplotlib + ffmpeg) for geometry, post-processing, validation, and a shared cinematic rendering pipeline so the whole gallery looks like one product.

## Run it
```bash
# build the LBM solver (needs g++ with OpenMP)
make -C solvers/lbm

# Kármán vortex street (validated) — writes results/vortex_street.gif
python demos/vortex_street.py            # full quality
python demos/vortex_street.py --quick    # fast smoke test
```

## Repository layout
```
solvers/      C++ solver cores (one per method)
flowzoo/      Python: geometry, text→mask, frame I/O, cinematic renderer
demos/        one runnable script per exhibit
results/      the gallery animations (GIF + MP4)
docs/         method notes & validation write-ups
```

## License
MIT — see [LICENSE](LICENSE).

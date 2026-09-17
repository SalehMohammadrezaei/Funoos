// FlowZoo - 2D Lattice-Boltzmann external-flow solver (D2Q9, BGK).
//
// Simulates incompressible flow past arbitrary obstacles read from a binary
// mask (1 = solid). Uniform inflow at the left, open outflow at the right,
// periodic top/bottom, half-way bounce-back on the obstacle. A viscosity
// sponge near the outlet absorbs vortices to keep the boundary clean.
//
// Writes float32 velocity frames (ux then uy, row-major Ny x Nx) and a probe
// time-series of transverse velocity for Strouhal-number validation.
//
// Build:  see solvers/lbm/Makefile  (g++ -O3 -fopenmp)
// Usage:  lbm2d --nx 900 --ny 300 --mask mask.bin --U 0.08 --tau 0.56 \
//               --steps 60000 --save_every 200 --out frames_dir \
//               --probe_x 360 --probe_y 150

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cmath>
#ifndef M_PI
#define M_PI 3.14159265358979323846   // not defined by MinGW under strict -std=c++17
#endif
#include <string>
#include <vector>
#include <fstream>
#include <filesystem>
#include <algorithm>

// D2Q9 lattice
static const int    NQ = 9;
static const int    cx[NQ] = {0, 1, 0,-1, 0, 1,-1,-1, 1};
static const int    cy[NQ] = {0, 0, 1, 0,-1, 1, 1,-1,-1};
static const int    opp[NQ]= {0, 3, 4, 1, 2, 7, 8, 5, 6};
static const double w[NQ]  = {4.0/9,
                              1.0/9, 1.0/9, 1.0/9, 1.0/9,
                              1.0/36,1.0/36,1.0/36,1.0/36};

struct Args {
    int nx=900, ny=300, steps=60000, save_every=200;
    int probe_x=-1, probe_y=-1, periodic=0, fdir=0;   // fdir: 0 = force along +x, 1 = along +y
    double U=0.08, tau=0.56, force=0.0;     // force = body force (Darcy/periodic mode)
    std::string mask, out="frames";
};

static Args parse(int argc, char** argv) {
    Args a;
    for (int i=1;i<argc-1;i+=2) {
        std::string k=argv[i]; std::string v=argv[i+1];
        if      (k=="--nx") a.nx=atoi(v.c_str());
        else if (k=="--ny") a.ny=atoi(v.c_str());
        else if (k=="--steps") a.steps=atoi(v.c_str());
        else if (k=="--save_every") a.save_every=atoi(v.c_str());
        else if (k=="--U") a.U=atof(v.c_str());
        else if (k=="--tau") a.tau=atof(v.c_str());
        else if (k=="--mask") a.mask=v;
        else if (k=="--out") a.out=v;
        else if (k=="--probe_x") a.probe_x=atoi(v.c_str());
        else if (k=="--probe_y") a.probe_y=atoi(v.c_str());
        else if (k=="--force") a.force=atof(v.c_str());
        else if (k=="--periodic") a.periodic=atoi(v.c_str());
        else if (k=="--fdir") a.fdir=atoi(v.c_str());
    }
    if (a.probe_x<0) a.probe_x = a.nx*2/5;
    if (a.probe_y<0) a.probe_y = a.ny/2;
    // validate before allocating anything (bad sizes, non-finite numbers, unstable tau, bad intervals)
    auto fail=[](const std::string& m){ fprintf(stderr,"error: %s\n",m.c_str()); exit(2); };
    if (a.nx<4||a.ny<4||(long long)a.nx*a.ny>400000000LL) fail("--nx/--ny must be >= 4 and nx*ny <= 4e8");
    if (a.steps<1||a.save_every<1) fail("--steps and --save_every must be >= 1");
    if (!std::isfinite(a.U)||!std::isfinite(a.tau)||!std::isfinite(a.force)) fail("non-finite --U/--tau/--force");
    if (a.tau<=0.5||a.tau>10.0) fail("--tau must be in (0.5, 10] (nu = (tau-0.5)/3 > 0)");
    if (std::fabs(a.U)>0.5) fail("--U must satisfy |U| <= 0.5 (lattice units; keep well below 0.3)");
    if (a.fdir!=0&&a.fdir!=1) fail("--fdir must be 0 (x) or 1 (y)");
    if (a.probe_x<0||a.probe_x>=a.nx||a.probe_y<0||a.probe_y>=a.ny) fail("probe outside the grid");
    return a;
}

int main(int argc, char** argv) {
    Args a = parse(argc, argv);
    const int nx=a.nx, ny=a.ny, N=nx*ny;

    // --- obstacle mask (1 = solid) ---
    std::vector<unsigned char> solid(N, 0);
    if (!a.mask.empty()) {
        std::ifstream f(a.mask, std::ios::binary);
        if (!f) { fprintf(stderr,"error: mask file not found: %s\n", a.mask.c_str()); return 2; }
        f.seekg(0, std::ios::end); long long sz=f.tellg(); f.seekg(0, std::ios::beg);
        if (sz < (long long)a.nx*a.ny) { fprintf(stderr,"error: mask file truncated (%lld bytes, need %lld)\n", sz, (long long)a.nx*a.ny); return 2; }
        if (!f) { fprintf(stderr,"cannot open mask %s\n", a.mask.c_str()); return 1; }
        f.read((char*)solid.data(), N);
    }

    // --- per-column relaxation: sponge near the outlet (last 12%) ---
    std::vector<double> omega(nx);
    int sponge0 = (int)(nx*0.88);
    for (int i=0;i<nx;i++) {
        double tau = a.tau;
        if (i>sponge0 && !a.periodic) {
            double s = double(i-sponge0)/double(nx-1-sponge0);  // 0..1
            tau = a.tau + s*s*(1.0 - a.tau + 0.5);               // ramp toward strong damping
        }
        omega[i] = 1.0/tau;
    }

    // --- distributions ---
    std::vector<double> f(NQ*N), fnew(NQ*N);
    auto IDX = [&](int k,int i,int j){ return k*N + j*nx + i; };

    // init inflow (rho=1, u=(U,0)) with a faint transverse ripple to seed asymmetry
    for (int j=0;j<ny;j++) for (int i=0;i<nx;i++) {
        double ux=a.U, uy=0.01*a.U*sin(2*M_PI*i/30.0), u2=ux*ux+uy*uy;
        for (int k=0;k<NQ;k++) {
            double cu = cx[k]*ux + cy[k]*uy;
            f[IDX(k,i,j)] = w[k]*(1.0 + 3*cu + 4.5*cu*cu - 1.5*u2);
        }
    }

    // startup gust: oscillating transverse inflow for an initial transient,
    // which kicks the wake into the Karman instability; then it self-sustains.
    int    n_pert = std::max(1500, a.steps/15);
    double pert_amp = 0.06*a.U, pert_period = 2000.0;

    std::error_code _ec; std::filesystem::create_directories(a.out, _ec);

    std::ofstream probe(a.out + "/probe.csv");
    probe << "step,uy\n";
    std::ofstream permh(a.out + "/perm.csv");     // k at every frame (periodic/body-force mode): convergence record
    permh << "step,k\n";
    auto total_mass=[&](){ double m=0; for(int s=0;s<(int)N;s++) for(int k=0;k<NQ;k++) m+=f[k*N+s]; return m; };
    auto perm_now=[&](){ if(!a.force) return 0.0; double su=0; long nfl=0;
        for(int s=0;s<(int)N;s++) if(!solid[s]){ double rho=0,ux=0,uy=0; for(int k=0;k<NQ;k++){ rho+=f[k*N+s]; ux+=cx[k]*f[k*N+s]; uy+=cy[k]*f[k*N+s]; }
            su += a.fdir? (uy+0.5*a.force)/rho : (ux+0.5*a.force)/rho; nfl++; }
        return ((a.tau-0.5)/3.0)*(su/(double)N)/a.force; };
    const double mass0 = total_mass();
    int nframes = 0;

    // frame i holds the state at the START of the step it is saved in (time = step); frame 0 is the
    // initial state and the final state is always saved after the loop
    std::ofstream ftimes(a.out + "/frame_times.txt"); int last_saved = -1;
    auto save_frame = [&](int step) {
            if (a.periodic) permh << step << "," << perm_now() << "\n";
            std::vector<float> buf(2*N);
            int bad = 0;                     // set by any thread that meets a state that is not one
            #pragma omp parallel for schedule(static) reduction(|:bad)
            for (int j=0;j<ny;j++) for (int i=0;i<nx;i++) {
                int s=j*nx+i; double rho=0,ux=0,uy=0;
                for (int k=0;k<NQ;k++){ rho+=f[k*N+s]; ux+=cx[k]*f[k*N+s]; uy+=cy[k]*f[k*N+s]; }
                double vx=(ux+0.5*(a.fdir?0.0:a.force))/rho;   // same velocity definition as collision
                double vy=(uy+0.5*(a.fdir?a.force:0.0))/rho;
                // A result is only a result if the state behind it is admissible: density finite and
                // positive, velocity finite, and speed below the lattice sound speed 1/sqrt(3). That
                // is the scheme's own limit, not a tuned margin: past it D2Q9 has stopped modelling
                // anything. Without this the run completes, writes NaN frames, and the app renders
                // them as a video.
                if (!solid[s] && (!std::isfinite(rho) || rho<=0.0
                                  || !std::isfinite(vx) || !std::isfinite(vy)
                                  || vx*vx+vy*vy > (1.0/3.0))) bad = 1;
                buf[s]   = (float)vx;
                buf[N+s] = (float)vy;
            }
            if (bad) {
                fprintf(stderr,"error: the calculation went unstable at step %d "
                        "(density or speed left the range the lattice can represent, tau=%.5f, U=%.4f); "
                        "no usable result was produced\n", step, a.tau, a.U);
                exit(4);
            }
            char fn[512]; snprintf(fn,sizeof(fn),"%s/frame_%05d.bin",a.out.c_str(),nframes);
            std::ofstream of(fn,std::ios::binary);
            of.write((char*)buf.data(), buf.size()*sizeof(float)); of.close();
            if (!of) { fprintf(stderr,"error: could not write %s (disk full or not writable)\n", fn); exit(3); }
            ftimes << step << "\n"; nframes++; last_saved = step;
            if (step % (a.save_every*3)==0)
                printf("step %d/%d  (%d frames)\n", step, a.steps, nframes);
            };
    for (int step=0; step<a.steps; step++) {
        if (step % a.save_every == 0) save_frame(step);
        // --- collide (in place) ---
        #pragma omp parallel for schedule(static)
        for (int j=0;j<ny;j++) for (int i=0;i<nx;i++) {
            int s = j*nx+i;
            double fl[NQ];
            for (int k=0;k<NQ;k++) fl[k]=f[k*N+s];
            if (solid[s]) {                       // bounce-back: reverse populations
                double tmp[NQ];
                for (int k=0;k<NQ;k++) tmp[k]=fl[opp[k]];
                for (int k=0;k<NQ;k++) f[k*N+s]=tmp[k];
            } else {                              // BGK (+ optional Guo body force in +x)
                double rho=0,ux=0,uy=0;
                for (int k=0;k<NQ;k++){ rho+=fl[k]; ux+=cx[k]*fl[k]; uy+=cy[k]*fl[k]; }
                double Fx=a.fdir? 0.0 : a.force, Fy=a.fdir? a.force : 0.0;
                ux=(ux+0.5*Fx)/rho; uy=(uy+0.5*Fy)/rho;   // Guo half-force in the velocity
                double u2=ux*ux+uy*uy, om=omega[i];
                for (int k=0;k<NQ;k++){
                    double cu=cx[k]*ux+cy[k]*uy;
                    double feq=w[k]*rho*(1.0+3*cu+4.5*cu*cu-1.5*u2);
                    // Guo forcing term: (1-ω/2) w_k [3 (c_k - u)·F + 9 (c_k·u)(c_k·F)]
                    double cF=cx[k]*Fx+cy[k]*Fy;
                    double Si=a.force? (1.0-0.5*om)*w[k]*(3*((cx[k]-ux)*Fx+(cy[k]-uy)*Fy)+9*cu*cF) : 0.0;
                    f[k*N+s]=fl[k]-om*(fl[k]-feq)+Si;
                }
            }
        }

        // --- stream (pull, periodic wrap) ---
        #pragma omp parallel for schedule(static)
        for (int j=0;j<ny;j++) for (int i=0;i<nx;i++) {
            for (int k=0;k<NQ;k++){
                int si=(i-cx[k]+nx)%nx, sj=(j-cy[k]+ny)%ny;
                fnew[k*N + j*nx+i] = f[k*N + sj*nx+si];
            }
        }

        // --- inflow/outflow (skipped in periodic body-force mode: streaming already wraps) ---
        if (!a.periodic) {
            double uy_in = (step < n_pert) ? pert_amp*sin(2*M_PI*step/pert_period) : 0.0;
            double feq_in[NQ];
            { double ux=a.U, u2=ux*ux+uy_in*uy_in;
              for (int k=0;k<NQ;k++){ double cu=cx[k]*ux+cy[k]*uy_in;
                feq_in[k]=w[k]*(1.0+3*cu+4.5*cu*cu-1.5*u2); } }
            #pragma omp parallel for schedule(static)
            for (int j=0;j<ny;j++) {
                for (int k=0;k<NQ;k++) fnew[k*N + j*nx+0] = feq_in[k];
                for (int k=0;k<NQ;k++) fnew[k*N + j*nx+(nx-1)] = fnew[k*N + j*nx+(nx-2)];
            }
        }

        f.swap(fnew);

        // --- probe + frame output ---
        {
            int s=a.probe_y*nx+a.probe_x; double rho=0,uy=0;
            for (int k=0;k<NQ;k++){ rho+=f[k*N+s]; uy+=cy[k]*f[k*N+s]; }
            probe << step << "," << (uy/rho) << "\n";
        }

    }

    if (last_saved != a.steps) save_frame(a.steps);     // final state

    // Darcy (superficial) velocity: flow averaged over the WHOLE sample with solids
    // counting as u=0, i.e. U_D = phi*<u>_pore. Uses the same macroscopic velocity as
    // collision (Guo half-force). Previously the pore average was used as U_D, which
    // over-states k by 1/phi.
    // (the velocity component ALONG the force direction is used, so k is the
    //  permeability in that direction: x for --fdir 0, y for --fdir 1)
    double sumux=0; long nfluid=0;
    for (int s=0;s<N;s++) if(!solid[s]){
        double rho=0,ux=0,uy=0; for(int k=0;k<NQ;k++){ rho+=f[k*N+s]; ux+=cx[k]*f[k*N+s]; uy+=cy[k]*f[k*N+s]; }
        double ua = a.fdir? (uy+0.5*a.force)/rho : (ux+0.5*a.force)/rho;
        sumux += ua; nfluid++;
    }
    double nu=(a.tau-0.5)/3.0;
    double meanux_pore = nfluid ? sumux/nfluid : 0.0;   // interstitial (pore-average) velocity
    double meanux      = sumux/(double)N;              // superficial (Darcy) velocity U_D
    double porosity=(double)nfluid/N;
    // k = nu*U_D/g, g = body force per unit mass (= pressure gradient / rho with rho~1)
    double perm=(a.force!=0.0)? nu*meanux/a.force : 0.0;

    // metadata for the Python renderer
    std::ofstream meta(a.out + "/meta.txt");
    meta << "mass_initial "<<mass0<<"\nmass_final "<<total_mass()<<"\n";
    meta << "nx "<<nx<<"\nny "<<ny<<"\nU "<<a.U<<"\ntau "<<a.tau
         << "\nnu "<<nu<<"\nsave_every "<<a.save_every
         << "\nnframes "<<nframes
         << "\nporosity "<<porosity<<"\nmean_ux "<<meanux<<"\nmean_ux_pore "<<meanux_pore<<"\npermeability "<<perm<<"\n";
    printf("done: %d frames -> %s\n", nframes, a.out.c_str());
    return 0;
}

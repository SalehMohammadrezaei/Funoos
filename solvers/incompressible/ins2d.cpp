// FlowZoo - 2D incompressible Navier-Stokes (projection method).
//
// Collocated grid, semi-Lagrangian advection (Stam "Stable Fluids"), a
// Gauss-Seidel/Jacobi pressure projection enforcing div(u)=0, Boussinesq
// buoyancy from an advected scalar, and vorticity confinement for lively
// small-scale swirl. Two exhibits share this solver:
//
//   --mode smoke : inject a hot, dyed source at the bottom -> rising plume
//   --mode rt    : heavy fluid over light + gravity -> Rayleigh-Taylor fingers
//   --mode rb    : hot plate below, cold plate above -> Rayleigh-Benard convection
//   --mode wind  : a chimney source in a steady crosswind -> a bent-over plume
//
// Outputs float32 scalar frames (the dye for smoke, density for RT), Ny x Nx.
//
// Build:  see Makefile  (g++ -O3 -fopenmp)

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

struct Args {
    int nx=240, ny=360, steps=4000, save_every=20, iters=60, modes=0;   // modes: RT single-mode wavenumber (0 = multi-mode)
    double dt=1.0, visc=0.0001, buoy=2.0e-3, grav=3.0e-3, conf=6.0, srcw=1.0, pert=1.0, atwood=1.0, flicker=0.0, wind=0.0, zst=0.12, kappa=0.0;   // kappa: thermal diffusivity (RB conduction)
    std::string mode="smoke", out="frames";
};
static Args parse(int c, char** v){
    Args a;
    for(int i=1;i<c-1;i+=2){ std::string k=v[i],x=v[i+1];
        if(k=="--nx")a.nx=atoi(x.c_str()); else if(k=="--ny")a.ny=atoi(x.c_str());
        else if(k=="--steps")a.steps=atoi(x.c_str()); else if(k=="--save_every")a.save_every=atoi(x.c_str());
        else if(k=="--iters")a.iters=atoi(x.c_str()); else if(k=="--dt")a.dt=atof(x.c_str());
        else if(k=="--visc")a.visc=atof(x.c_str()); else if(k=="--kappa")a.kappa=atof(x.c_str()); else if(k=="--buoy")a.buoy=atof(x.c_str());
        else if(k=="--grav")a.grav=atof(x.c_str()); else if(k=="--conf")a.conf=atof(x.c_str());
        else if(k=="--srcw")a.srcw=atof(x.c_str()); else if(k=="--pert")a.pert=atof(x.c_str());
        else if(k=="--atwood")a.atwood=atof(x.c_str()); else if(k=="--flicker")a.flicker=atof(x.c_str());
        else if(k=="--wind")a.wind=atof(x.c_str()); else if(k=="--zst")a.zst=atof(x.c_str());
        else if(k=="--modes")a.modes=atoi(x.c_str());
        else if(k=="--mode")a.mode=x; else if(k=="--out")a.out=x; }
    auto fail=[](const std::string& m){ fprintf(stderr,"error: %s\n",m.c_str()); exit(2); };
    if(a.mode!="smoke"&&a.mode!="rt"&&a.mode!="rb"&&a.mode!="flame"&&a.mode!="wind") fail("unknown --mode (smoke|rt|rb|flame|wind)");
    if(a.nx<16||a.ny<16||(long long)a.nx*a.ny>400000000LL) fail("--nx/--ny must be >= 16 (the source geometry needs room) and nx*ny <= 4e8");
    if(a.steps<1||a.save_every<1||a.iters<1) fail("--steps, --save_every and --iters must be >= 1");
    for(double v: {a.dt,a.visc,a.buoy,a.grav,a.conf,a.srcw,a.pert,a.atwood,a.flicker,a.wind,a.zst,a.kappa})
        if(!std::isfinite(v)) fail("non-finite numeric argument");
    if(a.dt<=0||a.visc<0||a.kappa<0||a.srcw<=0) fail("--dt and --srcw must be > 0; --visc and --kappa >= 0");
    if(a.kappa*a.dt>0.25) fail("--kappa*dt must be <= 0.25 (explicit diffusion stability)");
    if(a.modes<0) fail("--modes must be >= 0");
    return a;
}

int main(int argc,char**argv){
    Args a=parse(argc,argv);
    const int nx=a.nx, ny=a.ny, N=nx*ny;
    auto IX=[&](int i,int j){ return i + nx*j; };
    const bool smoke = (a.mode=="smoke");
    const bool rt    = (a.mode=="rt");
    const bool rb    = (a.mode=="rb");          // Rayleigh-Benard convection
    const bool wind  = (a.mode=="wind");        // chimney plume in a crosswind
    const bool flame = (a.mode=="flame");       // laminar diffusion flame (Burke-Schumann)
    const bool hassrc   = smoke || wind;        // a continuous dyed/hot source
    const bool open_top = smoke || wind || flame;  // open (zero-gradient) top boundary
    // Burke-Schumann fast chemistry: temperature peaks at the stoichiometric mixture
    // fraction Z = zst (the flame sheet) and falls to ambient toward pure fuel or pure air.
    const double Zst = a.zst;
    auto Tof=[&](double Z){ double T = (Z<=Zst) ? (Z/Zst) : ((1.0-Z)/(1.0-Zst)); return T<0?0.0:T; };

    std::vector<double> u(N,0), v(N,0), u0(N,0), v0(N,0);
    std::vector<double> s(N,0), s0(N,0), p(N,0), div(N,0);

    auto clampd=[&](double x,double lo,double hi){ return x<lo?lo:(x>hi?hi:x); };

    int sx = wind ? nx/4 : nx/2;                 // chimney sits upwind so the plume can bend across
    // source geometry, bounded so it always fits inside the interior (i in [1, nx-2], j in [1, ny-2])
    int sw=std::min(std::max(6,(int)(nx/12*a.srcw)), std::max(1,(nx-4)/2));
    int sh=std::min(std::max(5,ny/26), std::max(1,(ny-4)/2));
    int stack_h  = wind ? std::min((int)(0.32*ny), ny-sh-3) : 0;    // chimney height; the plume leaves its top
    int stack_hw = std::min(std::max(2, sw/2), std::max(1,(nx-4)/2)); // chimney half-width (solid)
    int sj = wind ? stack_h : 1;                 // source sits at the stack mouth, not on the floor
    if(sj+sh>ny-1) sh=std::max(1, ny-1-sj);

    // ---- staggered (MAC) layout -------------------------------------------------------
    // u[IX(i,j)] is the VERTICAL face between cells (i,j) and (i+1,j); u[IX(nx-1,j)] is unused.
    // v[IX(i,j)] is the HORIZONTAL face between cells (i,j) and (i,j+1); v[IX(i,ny-1)] is unused.
    // p, s and div stay at cell centres. Divergence and gradient are then both compact, and their
    // composition is exactly the five-point Laplacian the pressure solve inverts, so a converged
    // pressure really does leave a divergence-free field. On a collocated grid they span three
    // cells while the Laplacian spans one; they do not compose, and the grid-scale (checkerboard)
    // mode is invisible to the pressure, which is why the old projection left 34% to 84% behind.
    auto ufx=[&](int i,int j){ return u[IX(i,j)]; };          // face right of cell (i,j)
    auto vfy=[&](int i,int j){ return v[IX(i,j)]; };          // face above cell (i,j)
    // a face is closed when either neighbouring cell is solid; closed faces carry no flow and take
    // no pressure gradient, which is how the chimney is imposed INSIDE the projection rather than
    // stomped on afterwards (stomping reintroduced exactly the divergence the solve had removed)
    // Precomputed once: the geometry never changes, and evaluating it inside the SOR inner loop
    // meant up to eight predicate calls per cell per colour per sweep.
    std::vector<char> sld(N,0), opx(N,0), opy(N,0);
    for(int j=0;j<ny;j++)for(int i=0;i<nx;i++)
        sld[IX(i,j)] = (wind && j<stack_h && i>=sx-stack_hw && i<=sx+stack_hw) ? 1 : 0;
    for(int j=0;j<ny;j++)for(int i=0;i<nx;i++){
        opx[IX(i,j)] = (i+1<nx && !sld[IX(i,j)] && !sld[IX(i+1,j)]) ? 1 : 0;
        opy[IX(i,j)] = (j+1<ny && !sld[IX(i,j)] && !sld[IX(i,j+1)]) ? 1 : 0;
    }
    auto solid_cell=[&](int i,int j){ return sld[IX(i,j)]!=0; };
    auto openx=[&](int i,int j){ return opx[IX(i,j)]!=0; };
    auto openy=[&](int i,int j){ return opy[IX(i,j)]!=0; };


    // bilinear sample of field q at (x,y) in cell units
    auto sample=[&](const std::vector<double>&q,double x,double y){
        // clamp so the 2x2 stencil below always sits inside the array; callers that sample a face
        // field pass coordinates already shifted by half a cell, and the old centre-only clamp put
        // their edge rows half a cell out of place every step
        x=clampd(x,0.0,(double)nx-1.001); y=clampd(y,0.0,(double)ny-1.001);
        int i=(int)x, j=(int)y; double fx=x-i, fy=y-j;
        double q00=q[IX(i,j)],q10=q[IX(i+1,j)],q01=q[IX(i,j+1)],q11=q[IX(i+1,j+1)];
        return (1-fx)*(1-fy)*q00+fx*(1-fy)*q10+(1-fx)*fy*q01+fx*fy*q11;
    };
    // Semi-Lagrangian advection of d (from its copy d0) along the FROZEN velocity (ua,va).
    // Both velocity components must be back-traced with the same field -- previously the
    // second component used a u that the first call had already overwritten.
    auto advect=[&](std::vector<double>&d,const std::vector<double>&d0,
                    const std::vector<double>&ua,const std::vector<double>&va){
        #pragma omp parallel for schedule(static)
        for(int j=1;j<ny-1;j++)for(int i=1;i<nx-1;i++){
            double x=i-a.dt*ua[IX(i,j)], y=j-a.dt*va[IX(i,j)];
            d[IX(i,j)]=sample(d0,x,y);
        }
    };
    // Face-aware versions. Each velocity component is traced from ITS OWN face position, with the
    // other component interpolated to that position, and sampled out of its own face field. The
    // collocated version traced both from the cell centre, which on a staggered grid is half a
    // cell wrong for every component.
    auto advect_u=[&](std::vector<double>&d,const std::vector<double>&u0f,
                      const std::vector<double>&v0f){
        #pragma omp parallel for schedule(static)
        for(int j=1;j<ny-1;j++)for(int i=1;i<nx-2;i++){
            if(!opx[IX(i,j)]){ d[IX(i,j)]=0.0; continue; }
            // v at the u face (i+1/2, j): average the four v faces around it
            double vhere=0.25*(v0f[IX(i,j)]+v0f[IX(i+1,j)]
                              +v0f[IX(i,std::max(j-1,0))]+v0f[IX(i+1,std::max(j-1,0))]);
            double x=(i+0.5)-a.dt*u0f[IX(i,j)], y=j-a.dt*vhere;
            d[IX(i,j)]=sample(u0f, x-0.5, y);          // u faces are offset half a cell in x
        }
    };
    auto advect_v=[&](std::vector<double>&d,const std::vector<double>&u0f,
                      const std::vector<double>&v0f){
        #pragma omp parallel for schedule(static)
        for(int j=1;j<ny-2;j++)for(int i=1;i<nx-1;i++){
            if(!opy[IX(i,j)]){ d[IX(i,j)]=0.0; continue; }
            double uhere=0.25*(u0f[IX(i,j)]+u0f[IX(i,j+1)]
                              +u0f[IX(std::max(i-1,0),j)]+u0f[IX(std::max(i-1,0),j+1)]);
            double x=i-a.dt*uhere, y=(j+0.5)-a.dt*v0f[IX(i,j)];
            d[IX(i,j)]=sample(v0f, x, y-0.5);          // v faces are offset half a cell in y
        }
    };
    // walls: free-slip sides/floor; open top for smoke/wind, closed for RT/RB.
    // wind: left is a velocity inlet (u=U, v=0, clean air), right an outflow.
    // Boundary conditions on a staggered grid. Which index IS the wall differs per field, and the
    // collocated version got this wrong once the layout changed: it zeroed u[IX(nx-1,j)] and
    // v[IX(i,ny-1)], both of which are unused slots here, so the right wall and the closed top were
    // never imposed at all, while the values it did write were fed straight into the divergence
    // measurement that project() takes immediately afterwards.
    //
    //   u[IX(i,j)] is the face between cells i and i+1  -> the left wall is u[IX(0,j)],
    //                                                      the right wall is u[IX(nx-2,j)]
    //   v[IX(i,j)] is the face between cells j and j+1  -> the floor is v[IX(i,0)],
    //                                                      the ceiling is v[IX(i,ny-2)]
    //   scalars live at centres, so their ghost ring is the outermost cell as before.
    auto set_bc=[&](std::vector<double>&q,int kind){ // kind: 0 scalar,1 u,2 v
        if(kind==1){                                  // u faces
            for(int j=0;j<ny;j++){
                if(wind){
                    q[IX(0,j)]    = a.wind;           // velocity inlet on the left wall face
                    // the outflow face u[nx-2] is NOT overwritten: with p = 0 pinned in the ghost
                    // beyond it, the projection sets it so that whatever the interior pushes out
                    // leaves. Copying the neighbour here undid that correction every step and
                    // paired a free velocity with a zero-gradient pressure, which no outflow can
                    // satisfy; the energy that could not leave grew without bound once the
                    // projection stopped leaking it.
                } else {
                    q[IX(0,j)]    = 0.0;              // no flow through the side walls
                    if(nx>=2) q[IX(nx-2,j)] = 0.0;
                }
                if(nx>=1) q[IX(nx-1,j)] = 0.0;        // unused slot, kept clean
            }
            for(int i=0;i<nx;i++){                    // free-slip floor/ceiling: tangential copied
                q[IX(i,0)] = q[IX(i,1)];
                q[IX(i,ny-1)] = q[IX(i,ny-2)];
            }
        } else if(kind==2){                           // v faces
            for(int i=0;i<nx;i++){
                q[IX(i,0)] = 0.0;                     // no flow through the floor
                if(ny>=2 && !wind) q[IX(i,ny-2)] = open_top ? q[IX(i,std::max(ny-3,0))] : 0.0;
                // wind: the top face v[ny-2] is left to the projection, as the outflow face is
                q[IX(i,ny-1)] = 0.0;                  // unused slot, kept clean
            }
            for(int j=0;j<ny;j++){                    // free-slip side walls: tangential copied
                q[IX(0,j)] = wind ? 0.0 : q[IX(1,j)];
                q[IX(nx-1,j)] = q[IX(nx-2,j)];
            }
        } else if(kind==3){                           // pressure ghosts
            // Velocity prescribed on a boundary -> pressure zero-gradient there; velocity free
            // (outflow, open top) -> pressure pinned to zero there. Wind is the only mode with a
            // free boundary; every other mode is zero-gradient all round and singular.
            for(int j=0;j<ny;j++){
                q[IX(0,j)] = q[IX(1,j)];
                q[IX(nx-1,j)] = wind ? 0.0 : q[IX(nx-2,j)];
            }
            for(int i=0;i<nx;i++){
                q[IX(i,0)] = q[IX(i,1)];
                q[IX(i,ny-1)] = wind ? 0.0 : q[IX(i,ny-2)];
            }
        } else {                                      // scalars, unchanged
            for(int j=0;j<ny;j++){
                if(wind){ q[IX(0,j)] = 0.0; q[IX(nx-1,j)] = q[IX(nx-2,j)]; }
                else    { q[IX(0,j)] = q[IX(1,j)]; q[IX(nx-1,j)] = q[IX(nx-2,j)]; }
            }
            for(int i=0;i<nx;i++){
                q[IX(i,0)] = q[IX(i,1)];
                q[IX(i,ny-1)] = q[IX(i,ny-2)];
            }
        }
    };
    // velocity at a cell centre, averaged from the faces either side (used for output and for
    // advecting the scalar; never written back into the face state)
    auto uc=[&](int i,int j){ return 0.5*(u[IX(i,j)] + u[IX(std::max(i-1,0),j)]); };
    auto vc=[&](int i,int j){ return 0.5*(v[IX(i,j)] + v[IX(i,std::max(j-1,0))]); };

    // RMS of the divergence the velocity operator actually measures, over the interior.
    // Reported so a projection can never again be assumed to have done its job: a converged
    // pressure solve does not imply a divergence-free field when the operators disagree.
    double diag_div_pre=0.0, diag_div_post=0.0, diag_div_mid=0.0;
    int diag_iters_used=0, diag_iters_capped=0;
    auto div_rms=[&](){
        double acc=0.0; long cnt=0;
        for(int j=2;j<ny-2;j++)for(int i=2;i<nx-2;i++){
            if(solid_cell(i,j)) continue;
            double d=(ufx(i,j)-ufx(i-1,j))+(vfy(i,j)-vfy(i,j-1));   // compact, on the faces
            acc+=d*d; cnt++;
        }
        return cnt? sqrt(acc/(double)cnt) : 0.0;
    };
    auto project=[&](){
        set_bc(u,1); set_bc(v,2);
        diag_div_pre = div_rms();
        #pragma omp parallel for schedule(static)
        for(int j=1;j<ny-1;j++)for(int i=1;i<nx-1;i++){
            div[IX(i,j)] = solid_cell(i,j) ? 0.0
                         : -((ufx(i,j)-ufx(i-1,j))+(vfy(i,j)-vfy(i,j-1)));
            // p is NOT reset: the pressure changes little between steps, so last step's field is
            // a far better starting guess than zero, and the solve picks up where it left off.
        }
        set_bc(div,0);
        // Conjugate gradients on the pressure Poisson.
        //
        //   A p = div,   (A p)_ij = sum over OPEN faces of (p_ij - p_neighbour)
        //
        // A is the graph Laplacian of the open-face connectivity: symmetric and positive
        // semi-definite, which is what CG needs. SOR solved the same system correctly but its
        // iteration count grows with the grid (2816 sweeps at 60x90, 43136 at 540x360 for the
        // same accuracy), so the cost grew faster than the problem. CG converges in far fewer.
        //
        // Every boundary here is zero-gradient for pressure, so constants lie in the null space
        // and the system is singular. The mean is removed from the right-hand side to make it
        // compatible, and from the solution to pin the arbitrary constant.
        // The wind case pins the pressure to zero in the ghosts beyond the outflow and the open
        // top (see set_bc, kind 3): a Dirichlet condition where the velocity is free, which makes
        // the system non-singular and lets the imbalance between the prescribed inflow and
        // whatever leaves be absorbed at the boundaries that are free to pass it. The inlet, where
        // the velocity is prescribed, is zero-gradient. (It was the other way round until
        // 2026-09-26: p pinned at the inlet, zero-gradient at the outflow, with the outflow face
        // copied from its neighbour after every correction. That is a boundary the flow cannot
        // leave through consistently, and once the projection stopped leaking divergence the
        // kinetic energy doubled every few hundred steps and the run went non-finite.) Either way
        // the coupling has to appear in the operator, or CG solves a different system from the one
        // the boundary conditions describe and satisfies its own residual while the divergence
        // stays put.
        const bool has_dirichlet = wind;
        auto applyA=[&](const std::vector<double>& x, std::vector<double>& y){
            #pragma omp parallel for schedule(static)
            for(int j=1;j<ny-1;j++)for(int i=1;i<nx-1;i++){
                int k=IX(i,j);
                if(sld[k]){ y[k]=0.0; continue; }
                double acc=0.0;
                if(i>1    && opx[IX(i-1,j)]) acc += x[k]-x[IX(i-1,j)];
                if(i<nx-2 && opx[IX(i,j)])   acc += x[k]-x[IX(i+1,j)];
                if(j>1    && opy[IX(i,j-1)]) acc += x[k]-x[IX(i,j-1)];
                if(j<ny-2 && opy[IX(i,j)])   acc += x[k]-x[IX(i,j+1)];
                if(has_dirichlet && i==nx-2 && opx[IX(i,j)]) acc += x[k];   // outflow ghost p = 0
                if(has_dirichlet && j==ny-2 && opy[IX(i,j)]) acc += x[k];   // open-top ghost p = 0
                y[k]=acc;
            }
        };
        auto dotp=[&](const std::vector<double>& x, const std::vector<double>& y){
            double acc=0.0;
            #pragma omp parallel for schedule(static) reduction(+:acc)
            for(int j=1;j<ny-1;j++)for(int i=1;i<nx-1;i++){
                int k=IX(i,j); if(!sld[k]) acc += x[k]*y[k];
            }
            return acc;
        };
        auto demean=[&](std::vector<double>& x){
            double acc=0.0; long cnt=0;
            for(int j=1;j<ny-1;j++)for(int i=1;i<nx-1;i++){
                int k=IX(i,j); if(!sld[k]){ acc+=x[k]; cnt++; }
            }
            if(!cnt) return;
            double m=acc/(double)cnt;
            for(int j=1;j<ny-1;j++)for(int i=1;i<nx-1;i++){
                int k=IX(i,j); if(!sld[k]) x[k]-=m;
            }
        };
        static std::vector<double> rr, pp, Ap;
        rr.assign(N,0.0); pp.assign(N,0.0); Ap.assign(N,0.0);
        // Only a purely Neumann system is singular and needs its right-hand side made compatible.
        // With a Dirichlet boundary the imbalance is real and must be absorbed there, not averaged
        // away across every cell.
        if(!has_dirichlet) demean(div);
        double rhs_scale = sqrt(dotp(div,div));
        applyA(p, Ap);                                // warm start: p carries over between steps
        #pragma omp parallel for schedule(static)
        for(int j=1;j<ny-1;j++)for(int i=1;i<nx-1;i++){
            int k=IX(i,j); if(!sld[k]) rr[k]=div[k]-Ap[k];
        }
        pp = rr;
        double rs = dotp(rr,rr);
        const double target = 1e-8 * rhs_scale;
        int used = 0;
        if(rhs_scale > 0.0){
            for(int it=0; it<a.iters; it++){
                used = it + 1;
                applyA(pp, Ap);
                double pAp = dotp(pp,Ap);
                if(fabs(pAp) < 1e-300) break;
                double alpha = rs/pAp;
                #pragma omp parallel for schedule(static)
                for(int j=1;j<ny-1;j++)for(int i=1;i<nx-1;i++){
                    int k=IX(i,j);
                    if(!sld[k]){ p[k]+=alpha*pp[k]; rr[k]-=alpha*Ap[k]; }
                }
                double rs_new = dotp(rr,rr);
                if(sqrt(rs_new) < target) break;
                double beta = rs_new/rs;
                #pragma omp parallel for schedule(static)
                for(int j=1;j<ny-1;j++)for(int i=1;i<nx-1;i++){
                    int k=IX(i,j); if(!sld[k]) pp[k]=rr[k]+beta*pp[k];
                }
                rs = rs_new;
            }
        }
        if(!has_dirichlet) demean(p);                 // pin the constant only when it is arbitrary
        set_bc(p,3);                                  // pressure ghosts: zero-gradient, or zero where the flow is free
        diag_iters_used = used;
        diag_iters_capped = (used >= a.iters) ? 1 : 0;
        #pragma omp parallel for schedule(static)
        for(int j=1;j<ny-1;j++)for(int i=0;i<nx-1;i++)
            if(openx(i,j)) u[IX(i,j)] -= (p[IX(i+1,j)]-p[IX(i,j)]); else u[IX(i,j)]=0.0;
        #pragma omp parallel for schedule(static)
        for(int j=0;j<ny-1;j++)for(int i=1;i<nx-1;i++)
            if(openy(i,j)) v[IX(i,j)] -= (p[IX(i,j+1)]-p[IX(i,j)]); else v[IX(i,j)]=0.0;
        set_bc(u,1); set_bc(v,2);
        diag_div_post = div_rms();
    };

    // --- initial condition ---
    if(rt){ // Rayleigh-Taylor: heavy (s=1) on top, light (s=0) below, wavy interface
        for(int j=0;j<ny;j++)for(int i=0;i<nx;i++){
            double yi = a.modes>0
                ? 0.5*ny + 0.02*ny*a.pert*cos(2*M_PI*i/(double)nx*a.modes)      // single mode, small amplitude
                : 0.5*ny + 0.04*ny*a.pert*sin(2*M_PI*i/(double)nx*3)
                         + 0.015*ny*a.pert*sin(2*M_PI*i/(double)nx*7);
            // Atwood number sets the density contrast across the interface:
            // s in [0.5(1-A), 0.5(1+A)], so the buoyant forcing scales with A
            s[IX(i,j)] = 0.5 + 0.5*a.atwood*tanh((j-yi)/2.0);
        }
    } else if(rb){ // Rayleigh-Benard: hot plate below (s=1), cold above (s=0), seeded
        for(int j=0;j<ny;j++)for(int i=0;i<nx;i++){
            double base = 1.0 - (double)j/(ny-1);            // linear conduction profile
            double seed = 0.05*a.pert*sin(2*M_PI*(double)i/nx*6.0)*sin(M_PI*(double)j/(ny-1));
            s[IX(i,j)] = base + seed;
        }
    } else if(wind){ // start with the crosswind already blowing across the box
        for(int k=0;k<N;k++){ u[k]=a.wind; s[k]=0.0; }
    }

    std::error_code _ec; std::filesystem::create_directories(a.out, _ec);
    int nf=0;
    // zero the velocity inside the solid chimney so the wind flows around it
    auto solidify=[&](){ if(!wind) return;
        for(int j=0;j<stack_h;j++) for(int i=std::max(0,sx-stack_hw);i<=std::min(nx-1,sx+stack_hw);i++){
            u[IX(i,j)]=0; v[IX(i,j)]=0; } };

    // frame i holds the state at the START of the step it is saved in (time = step, dt = 1);
    // frame 0 is the initial state and the final state is always saved after the loop
    std::ofstream ftimes(a.out+"/frame_times.txt"); int last_saved=-1;
    auto save_frame=[&](int step){
        // Admissibility before anything is written: a velocity or scalar that is no longer finite
        // cannot be rendered, and the semi-Lagrangian sampler indexes with it, so a run that has
        // blown up produces frames of garbage that look like a result. The LBM solver already
        // refuses such a state with exit 4; this solver used to write it out and report success.
        {
            long bad=0;
            #pragma omp parallel for schedule(static) reduction(+:bad)
            for(int k=0;k<N;k++) if(!std::isfinite(u[k])||!std::isfinite(v[k])||!std::isfinite(s[k])) bad++;
            if(bad){
                fprintf(stderr,"error: the calculation went unstable at step %d (%ld cells are no longer finite); "
                               "try a lower buoyancy, less vorticity confinement or more viscosity\n",step,bad);
                exit(4);
            }
        }
        std::vector<float> buf(N);
        // flame renders the luminous temperature field T(Z); other modes render the scalar
        for(int k=0;k<N;k++) buf[k]=(float)(flame ? Tof(s[k]) : s[k]);
        char fn[512]; snprintf(fn,sizeof(fn),"%s/frame_%05d.bin",a.out.c_str(),nf);
        std::ofstream of(fn,std::ios::binary); of.write((char*)buf.data(),N*sizeof(float));
        std::vector<float> vb(2*N);                 // velocity field (for Speed/streamlines)
        // the state lives on faces; rendering wants cell centres, so average here and only here
        for(int j=0;j<ny;j++)for(int i=0;i<nx;i++){
            vb[IX(i,j)]   = (float)uc(i,j);
            vb[N+IX(i,j)] = (float)vc(i,j);
        }
        char vn[512]; snprintf(vn,sizeof(vn),"%s/vel_%05d.bin",a.out.c_str(),nf);
        std::ofstream vof(vn,std::ios::binary); vof.write((char*)vb.data(),2*N*sizeof(float)); of.close(); vof.close();
        if(!of||!vof){ fprintf(stderr,"error: could not write frame %d (disk full or not writable)\n",nf); exit(3); }
        ftimes<<step*a.dt<<"\n"; nf++; last_saved=step;
        if(step%(a.save_every*3)==0) printf("step %d/%d (%d frames)\n",step,a.steps,nf);
    };
    for(int step=0; step<a.steps; step++){
        if(step%a.save_every==0) save_frame(step);
        // forces: buoyancy + (smoke/wind) continuous source + vorticity confinement
        if(hassrc){
            // flicker: a wobbling, pulsing source so the plume dances like a flame
            double ph=step*0.06;
            int off=(int)(a.flicker*sw*0.8*(sin(ph)+0.4*sin(2.3*ph+1.0)));
            double str=1.0 + a.flicker*0.5*sin(1.7*ph);
            int sxx=std::min(nx-2-sw, std::max(1+sw, sx+off));
            for(int j=sj;j<std::min(ny-1,sj+sh);j++)for(int i=std::max(1,sxx-sw);i<=std::min(nx-2,sxx+sw);i++){
                double r=double(i-sxx)/sw; double g=exp(-3*r*r);
                s[IX(i,j)] = std::min(1.0, s[IX(i,j)]+0.55*g*str);
                if(opy[IX(i,j)]) v[IX(i,j)] += 0.02*g*str;      // v is the face above this cell
            }
        }
        if(flame){                                  // fuel-rich vapour rising off a thin wick
            int ww=std::min(std::max(2, sw/3), std::max(1,(nx-4)/2));
            for(int j=1;j<std::min(ny-1,1+sh);j++)for(int i=std::max(1,sx-ww);i<=std::min(nx-2,sx+ww);i++){
                double r=double(i-sx)/ww; double g=exp(-3*r*r);
                s[IX(i,j)] = std::min(1.0, s[IX(i,j)]+0.6*g);        // mixture fraction Z→1 at the wick
                if(opy[IX(i,j)]) v[IX(i,j)] += 0.06*g;               // launch the fuel upward off the wick
                if(opx[IX(i,j)])   u[IX(i,j)]   *= 0.5;              // damp lateral drift on both faces
                if(i>0 && opx[IX(i-1,j)]) u[IX(i-1,j)] *= 0.5;       // that bound this cell
            }
        }
        // v lives on the face between (i,j) and (i,j+1), so the scalar driving it is the average
        // of the two cells that face separates, not the value at one cell centre.
        #pragma omp parallel for schedule(static)
        for(int j=1;j<ny-2;j++)for(int i=1;i<nx-1;i++){
            if(!opy[IX(i,j)]) continue;
            double sf = 0.5*(s[IX(i,j)] + s[IX(i,j+1)]);
            if(hassrc)     v[IX(i,j)] += a.dt*a.buoy*sf;
            else if(flame) v[IX(i,j)] += a.dt*a.buoy*0.5*(Tof(s[IX(i,j)])+Tof(s[IX(i,j+1)]));
            else if(rb)    v[IX(i,j)] += a.dt*a.buoy*(sf-0.5);
            else           v[IX(i,j)] -= a.dt*a.grav*sf;
        }
        // vorticity confinement
        if(a.conf>0){
            // On a staggered grid the curl falls naturally at the cell CORNER between the two
            // faces it differences, with no averaging needed: dv/dx from the v faces either side,
            // du/dy from the u faces above and below.
            std::vector<double> w(N,0);
            #pragma omp parallel for schedule(static)
            for(int j=0;j<ny-1;j++)for(int i=0;i<nx-1;i++)
                w[IX(i,j)] = (v[IX(i+1,j)]-v[IX(i,j)]) - (u[IX(i,j+1)]-u[IX(i,j)]);
            // the magnitude gradient is taken at cell centres, where the four surrounding corners
            // are available, and the resulting force is applied to the faces it belongs to
            std::vector<double> wc(N,0);
            #pragma omp parallel for schedule(static)
            for(int j=1;j<ny-1;j++)for(int i=1;i<nx-1;i++)
                wc[IX(i,j)] = 0.25*(fabs(w[IX(i,j)])+fabs(w[IX(i-1,j)])
                                   +fabs(w[IX(i,j-1)])+fabs(w[IX(i-1,j-1)]));
            #pragma omp parallel for schedule(static)
            for(int j=2;j<ny-2;j++)for(int i=2;i<nx-2;i++){
                double gx=0.5*(wc[IX(i+1,j)]-wc[IX(i-1,j)]);
                double gy=0.5*(wc[IX(i,j+1)]-wc[IX(i,j-1)]);
                double m=sqrt(gx*gx+gy*gy)+1e-12; gx/=m; gy/=m;
                double wcen=0.25*(w[IX(i,j)]+w[IX(i-1,j)]+w[IX(i,j-1)]+w[IX(i-1,j-1)]);
                if(opx[IX(i,j)]) u[IX(i,j)] += a.dt*a.conf*1e-2*( gy*wcen);
                if(opy[IX(i,j)]) v[IX(i,j)] += a.dt*a.conf*1e-2*(-gx*wcen);
            }
        }
        set_bc(u,1); set_bc(v,2);

        // advect velocity, each component from its own face
        u0=u; v0=v; advect_u(u,u0,v0); advect_v(v,u0,v0); set_bc(u,1); set_bc(v,2);
        project();          // the chimney is closed faces INSIDE this, not a stomp afterwards:
                            // zeroing velocities after the projection put back the divergence the
                            // solve had just removed, which no choice of operators could fix
        // advect the scalar along the velocity at cell centres, where the scalar lives
        s0=s;
        #pragma omp parallel for schedule(static)
        for(int j=1;j<ny-1;j++)for(int i=1;i<nx-1;i++){
            double x=i-a.dt*uc(i,j), y=j-a.dt*vc(i,j);
            s[IX(i,j)]=sample(s0,x,y);
        }
        set_bc(s,0);
        if(rb){ for(int i=0;i<nx;i++){ s[IX(i,0)]=1.0; s[IX(i,ny-1)]=0.0; } }  // fixed hot/cold plates
        if(rb && a.kappa>0){                        // thermal diffusion (conduction): dT/dt = kappa*lap(T)
            s0=s;                                   // explicit FTCS; stable for dt*kappa <= 0.25
            #pragma omp parallel for schedule(static)
            for(int j=1;j<ny-1;j++)for(int i=1;i<nx-1;i++)
                s[IX(i,j)] += a.dt*a.kappa*(s0[IX(i-1,j)]+s0[IX(i+1,j)]+s0[IX(i,j-1)]+s0[IX(i,j+1)]-4*s0[IX(i,j)]);
            set_bc(s,0);
            for(int i=0;i<nx;i++){ s[IX(i,0)]=1.0; s[IX(i,ny-1)]=0.0; }   // plates last, so they win
        }
        if(flame){                                  // diffuse the mixture fraction (sets the flame thickness)
            s0=s;
            #pragma omp parallel for schedule(static)
            for(int j=1;j<ny-1;j++)for(int i=1;i<nx-1;i++)
                s[IX(i,j)] += 0.05*(s0[IX(i-1,j)]+s0[IX(i+1,j)]+s0[IX(i,j-1)]+s0[IX(i,j+1)]-4*s0[IX(i,j)]);
            // fuel consumption: fuel is burned away as it rises, so it reaches a bounded steady
            // height instead of accumulating (a widening torch) — this is what fixes the growth.
            #pragma omp parallel for schedule(static)
            for(int k=0;k<N;k++) s[k] *= 0.965;
            set_bc(s,0);
        }
        // light viscous smoothing of velocity (stability)
        if(a.visc>0){
            u0=u; v0=v;
            #pragma omp parallel for schedule(static)
            for(int j=1;j<ny-1;j++)for(int i=1;i<nx-1;i++){
                if(opx[IX(i,j)]){
                    double lapu=u0[IX(i-1,j)]+u0[IX(i+1,j)]+u0[IX(i,j-1)]+u0[IX(i,j+1)]-4*u0[IX(i,j)];
                    u[IX(i,j)]+=a.dt*a.visc*lapu;
                }
                if(opy[IX(i,j)]){
                    double lapv=v0[IX(i-1,j)]+v0[IX(i+1,j)]+v0[IX(i,j-1)]+v0[IX(i,j+1)]-4*v0[IX(i,j)];
                    v[IX(i,j)]+=a.dt*a.visc*lapv;
                }
            }
            set_bc(u,1); set_bc(v,2);
        }

    }
    if(last_saved!=a.steps) save_frame(a.steps);       // final state (the run length need not divide the interval)
    std::ofstream meta(a.out+"/meta.txt");
    meta<<"nx "<<nx<<"\nny "<<ny<<"\nmode_smoke "<<(smoke?1:0)<<"\nnframes "<<nf<<"\n";
    // the last projection of the run: what it was handed, and what it left behind
    meta<<"div_pre "<<diag_div_pre<<"\ndiv_post "<<diag_div_post<<"\n";
    meta<<"pressure_iters "<<diag_iters_used<<"\npressure_capped "<<diag_iters_capped<<"\n";
    printf("done: %d frames -> %s\n",nf,a.out.c_str());
    return 0;
}

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
    int nx=240, ny=360, steps=4000, save_every=20, iters=60;
    double dt=1.0, visc=0.0001, buoy=2.0e-3, grav=3.0e-3, conf=6.0, srcw=1.0, pert=1.0, atwood=1.0, flicker=0.0, wind=0.0;
    std::string mode="smoke", out="frames";
};
static Args parse(int c, char** v){
    Args a;
    for(int i=1;i<c-1;i+=2){ std::string k=v[i],x=v[i+1];
        if(k=="--nx")a.nx=atoi(x.c_str()); else if(k=="--ny")a.ny=atoi(x.c_str());
        else if(k=="--steps")a.steps=atoi(x.c_str()); else if(k=="--save_every")a.save_every=atoi(x.c_str());
        else if(k=="--iters")a.iters=atoi(x.c_str()); else if(k=="--dt")a.dt=atof(x.c_str());
        else if(k=="--visc")a.visc=atof(x.c_str()); else if(k=="--buoy")a.buoy=atof(x.c_str());
        else if(k=="--grav")a.grav=atof(x.c_str()); else if(k=="--conf")a.conf=atof(x.c_str());
        else if(k=="--srcw")a.srcw=atof(x.c_str()); else if(k=="--pert")a.pert=atof(x.c_str());
        else if(k=="--atwood")a.atwood=atof(x.c_str()); else if(k=="--flicker")a.flicker=atof(x.c_str());
        else if(k=="--wind")a.wind=atof(x.c_str());
        else if(k=="--mode")a.mode=x; else if(k=="--out")a.out=x; }
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
    const bool hassrc   = smoke || wind;        // a continuous dyed/hot source
    const bool open_top = smoke || wind;        // open (zero-gradient) top boundary

    std::vector<double> u(N,0), v(N,0), u0(N,0), v0(N,0);
    std::vector<double> s(N,0), s0(N,0), p(N,0), div(N,0);

    auto clampd=[&](double x,double lo,double hi){ return x<lo?lo:(x>hi?hi:x); };

    // bilinear sample of field q at (x,y) in cell units
    auto sample=[&](const std::vector<double>&q,double x,double y){
        x=clampd(x,0.5,nx-1.5); y=clampd(y,0.5,ny-1.5);
        int i=(int)x, j=(int)y; double fx=x-i, fy=y-j;
        double q00=q[IX(i,j)],q10=q[IX(i+1,j)],q01=q[IX(i,j+1)],q11=q[IX(i+1,j+1)];
        return (1-fx)*(1-fy)*q00+fx*(1-fy)*q10+(1-fx)*fy*q01+fx*fy*q11;
    };
    auto advect=[&](std::vector<double>&d,const std::vector<double>&d0){
        #pragma omp parallel for schedule(static)
        for(int j=1;j<ny-1;j++)for(int i=1;i<nx-1;i++){
            double x=i-a.dt*u[IX(i,j)], y=j-a.dt*v[IX(i,j)];
            d[IX(i,j)]=sample(d0,x,y);
        }
    };
    // walls: free-slip sides/floor; open top for smoke/wind, closed for RT/RB.
    // wind: left is a velocity inlet (u=U, v=0, clean air), right an outflow.
    auto set_bc=[&](std::vector<double>&q,int kind){ // kind: 0 scalar,1 u,2 v
        for(int j=0;j<ny;j++){
            if(wind){
                q[IX(0,j)]    = (kind==1)? a.wind : 0.0;   // inlet: u=U, v=0, s=0
                q[IX(nx-1,j)] = q[IX(nx-2,j)];             // outflow (zero-gradient)
            } else {
                q[IX(0,j)]    = (kind==1)?0.0:q[IX(1,j)];
                q[IX(nx-1,j)] = (kind==1)?0.0:q[IX(nx-2,j)];
            }
        }
        for(int i=0;i<nx;i++){
            q[IX(i,0)]    = (kind==2)?0.0:q[IX(i,1)];                 // no-slip / no-penetration floor
            if(open_top) q[IX(i,ny-1)] = q[IX(i,ny-2)];              // open top: zero-gradient for u, v AND scalar
            else         q[IX(i,ny-1)] = (kind==2)?0.0:q[IX(i,ny-2)]; // closed top (RT/RB)
        }
    };
    auto project=[&](){
        #pragma omp parallel for schedule(static)
        for(int j=1;j<ny-1;j++)for(int i=1;i<nx-1;i++){
            div[IX(i,j)]=-0.5*((u[IX(i+1,j)]-u[IX(i-1,j)])+(v[IX(i,j+1)]-v[IX(i,j-1)]));
            p[IX(i,j)]=0;
        }
        set_bc(div,0); set_bc(p,0);
        const double omega=1.8;                 // SOR over-relaxation
        for(int it=0;it<a.iters;it++){
            for(int color=0;color<2;color++){   // red-black Gauss-Seidel (parallel-safe)
                #pragma omp parallel for schedule(static)
                for(int j=1;j<ny-1;j++)for(int i=1;i<nx-1;i++) if(((i+j)&1)==color){
                    double gs=(div[IX(i,j)]+p[IX(i-1,j)]+p[IX(i+1,j)]
                              +p[IX(i,j-1)]+p[IX(i,j+1)])*0.25;
                    p[IX(i,j)]+=omega*(gs-p[IX(i,j)]);
                }
            }
            set_bc(p,0);
        }
        #pragma omp parallel for schedule(static)
        for(int j=1;j<ny-1;j++)for(int i=1;i<nx-1;i++){
            u[IX(i,j)]-=0.5*(p[IX(i+1,j)]-p[IX(i-1,j)]);
            v[IX(i,j)]-=0.5*(p[IX(i,j+1)]-p[IX(i,j-1)]);
        }
        set_bc(u,1); set_bc(v,2);
    };

    // --- initial condition ---
    if(rt){ // Rayleigh-Taylor: heavy (s=1) on top, light (s=0) below, wavy interface
        for(int j=0;j<ny;j++)for(int i=0;i<nx;i++){
            double yi=0.5*ny + 0.04*ny*a.pert*sin(2*M_PI*i/(double)nx*3)
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
    int sx = wind ? nx/4 : nx/2;                 // chimney sits upwind so the plume can bend across
    int sw=std::max(6,(int)(nx/12*a.srcw)), sh=std::max(5,ny/26);
    int stack_h  = wind ? (int)(0.32*ny) : 0;    // chimney height; the plume leaves its top
    int stack_hw = std::max(2, sw/2);            // chimney half-width (solid)
    int sj = wind ? stack_h : 1;                 // source sits at the stack mouth, not on the floor
    // zero the velocity inside the solid chimney so the wind flows around it
    auto solidify=[&](){ if(!wind) return;
        for(int j=0;j<stack_h;j++) for(int i=std::max(0,sx-stack_hw);i<=std::min(nx-1,sx+stack_hw);i++){
            u[IX(i,j)]=0; v[IX(i,j)]=0; } };

    for(int step=0; step<=a.steps; step++){
        // forces: buoyancy + (smoke/wind) continuous source + vorticity confinement
        if(hassrc){
            // flicker: a wobbling, pulsing source so the plume dances like a flame
            double ph=step*0.06;
            int off=(int)(a.flicker*sw*0.8*(sin(ph)+0.4*sin(2.3*ph+1.0)));
            double str=1.0 + a.flicker*0.5*sin(1.7*ph);
            int sxx=std::min(nx-2-sw, std::max(1+sw, sx+off));
            for(int j=sj;j<sj+sh;j++)for(int i=sxx-sw;i<=sxx+sw;i++){
                double r=double(i-sxx)/sw; double g=exp(-3*r*r);
                s[IX(i,j)] = std::min(1.0, s[IX(i,j)]+0.55*g*str);
                v[IX(i,j)] += 0.02*g*str;
            }
        }
        #pragma omp parallel for schedule(static)
        for(int j=1;j<ny-1;j++)for(int i=1;i<nx-1;i++){
            if(hassrc)   v[IX(i,j)] += a.dt*a.buoy*s[IX(i,j)];        // hot rises
            else if(rb)  v[IX(i,j)] += a.dt*a.buoy*(s[IX(i,j)]-0.5);  // warm rises, cool sinks
            else         v[IX(i,j)] -= a.dt*a.grav*s[IX(i,j)];        // RT: heavy sinks
        }
        // vorticity confinement
        if(a.conf>0){
            std::vector<double> w(N,0);
            #pragma omp parallel for schedule(static)
            for(int j=1;j<ny-1;j++)for(int i=1;i<nx-1;i++)
                w[IX(i,j)]=0.5*((v[IX(i+1,j)]-v[IX(i-1,j)])-(u[IX(i,j+1)]-u[IX(i,j-1)]));
            #pragma omp parallel for schedule(static)
            for(int j=2;j<ny-2;j++)for(int i=2;i<nx-2;i++){
                double gx=0.5*(fabs(w[IX(i+1,j)])-fabs(w[IX(i-1,j)]));
                double gy=0.5*(fabs(w[IX(i,j+1)])-fabs(w[IX(i,j-1)]));
                double m=sqrt(gx*gx+gy*gy)+1e-12; gx/=m; gy/=m;
                u[IX(i,j)] += a.dt*a.conf*1e-2*( gy*w[IX(i,j)]);
                v[IX(i,j)] += a.dt*a.conf*1e-2*(-gx*w[IX(i,j)]);
            }
        }
        set_bc(u,1); set_bc(v,2); solidify();

        // advect velocity
        u0=u; v0=v; advect(u,u0); advect(v,v0); set_bc(u,1); set_bc(v,2);
        project(); solidify();
        // advect scalar
        s0=s; advect(s,s0); set_bc(s,0);
        if(rb){ for(int i=0;i<nx;i++){ s[IX(i,0)]=1.0; s[IX(i,ny-1)]=0.0; } }  // fixed hot/cold plates
        // light viscous smoothing of velocity (stability)
        if(a.visc>0){
            u0=u; v0=v;
            #pragma omp parallel for schedule(static)
            for(int j=1;j<ny-1;j++)for(int i=1;i<nx-1;i++){
                double lapu=u0[IX(i-1,j)]+u0[IX(i+1,j)]+u0[IX(i,j-1)]+u0[IX(i,j+1)]-4*u0[IX(i,j)];
                double lapv=v0[IX(i-1,j)]+v0[IX(i+1,j)]+v0[IX(i,j-1)]+v0[IX(i,j+1)]-4*v0[IX(i,j)];
                u[IX(i,j)]+=a.visc*lapu; v[IX(i,j)]+=a.visc*lapv;
            }
            set_bc(u,1); set_bc(v,2);
        }

        if(step%a.save_every==0){
            std::vector<float> buf(N);
            for(int k=0;k<N;k++) buf[k]=(float)s[k];
            char fn[512]; snprintf(fn,sizeof(fn),"%s/frame_%05d.bin",a.out.c_str(),nf);
            std::ofstream of(fn,std::ios::binary); of.write((char*)buf.data(),N*sizeof(float));
            std::vector<float> vb(2*N);                 // velocity field (for Speed/streamlines)
            for(int k=0;k<N;k++){ vb[k]=(float)u[k]; vb[N+k]=(float)v[k]; }
            char vn[512]; snprintf(vn,sizeof(vn),"%s/vel_%05d.bin",a.out.c_str(),nf);
            std::ofstream vof(vn,std::ios::binary); vof.write((char*)vb.data(),2*N*sizeof(float));
            nf++;
            if(step%(a.save_every*20)==0) printf("step %d/%d (%d frames)\n",step,a.steps,nf);
        }
    }
    std::ofstream meta(a.out+"/meta.txt");
    meta<<"nx "<<nx<<"\nny "<<ny<<"\nmode_smoke "<<(smoke?1:0)<<"\nnframes "<<nf<<"\n";
    printf("done: %d frames -> %s\n",nf,a.out.c_str());
    return 0;
}

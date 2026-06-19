// FlowZoo - 2D incompressible Navier-Stokes (projection method).
//
// Collocated grid, semi-Lagrangian advection (Stam "Stable Fluids"), a
// Gauss-Seidel/Jacobi pressure projection enforcing div(u)=0, Boussinesq
// buoyancy from an advected scalar, and vorticity confinement for lively
// small-scale swirl. Two exhibits share this solver:
//
//   --mode smoke : inject a hot, dyed source at the bottom -> rising plume
//   --mode rt    : heavy fluid over light + gravity -> Rayleigh-Taylor fingers
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
    double dt=1.0, visc=0.0001, buoy=2.0e-3, grav=3.0e-3, conf=6.0, srcw=1.0, pert=1.0, atwood=1.0;
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
        else if(k=="--atwood")a.atwood=atof(x.c_str());
        else if(k=="--mode")a.mode=x; else if(k=="--out")a.out=x; }
    return a;
}

int main(int argc,char**argv){
    Args a=parse(argc,argv);
    const int nx=a.nx, ny=a.ny, N=nx*ny;
    auto IX=[&](int i,int j){ return i + nx*j; };
    const bool smoke = (a.mode=="smoke");

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
    // free-slip side/floor walls; open top for smoke, closed for RT
    auto set_bc=[&](std::vector<double>&q,int kind){ // kind: 0 scalar,1 u,2 v
        for(int j=0;j<ny;j++){
            q[IX(0,j)]   = (kind==1)?0.0:q[IX(1,j)];
            q[IX(nx-1,j)]= (kind==1)?0.0:q[IX(nx-2,j)];
        }
        for(int i=0;i<nx;i++){
            q[IX(i,0)]    = (kind==2)?0.0:q[IX(i,1)];
            if(smoke && kind!=2) q[IX(i,ny-1)] = q[IX(i,ny-2)];        // open top
            else q[IX(i,ny-1)] = (kind==2)?0.0:q[IX(i,ny-2)];
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
    if(!smoke){ // Rayleigh-Taylor: heavy (s=1) on top, light (s=0) below, wavy interface
        for(int j=0;j<ny;j++)for(int i=0;i<nx;i++){
            double yi=0.5*ny + 0.04*ny*a.pert*sin(2*M_PI*i/(double)nx*3)
                              + 0.015*ny*a.pert*sin(2*M_PI*i/(double)nx*7);
            // Atwood number sets the density contrast across the interface:
            // s in [0.5(1-A), 0.5(1+A)], so the buoyant forcing scales with A
            s[IX(i,j)] = 0.5 + 0.5*a.atwood*tanh((j-yi)/2.0);
        }
    }

    std::error_code _ec; std::filesystem::create_directories(a.out, _ec);
    int nf=0;
    int sx=nx/2, sw=std::max(6,(int)(nx/12*a.srcw)), sh=std::max(5,ny/26);

    for(int step=0; step<=a.steps; step++){
        // forces: buoyancy + (smoke) continuous source + vorticity confinement
        if(smoke){
            for(int j=1;j<1+sh;j++)for(int i=sx-sw;i<=sx+sw;i++){
                double r=double(i-sx)/sw; double g=exp(-3*r*r);
                s[IX(i,j)] = std::min(1.0, s[IX(i,j)]+0.6*g);
                v[IX(i,j)] += 0.02*g;
            }
        }
        #pragma omp parallel for schedule(static)
        for(int j=1;j<ny-1;j++)for(int i=1;i<nx-1;i++){
            if(smoke) v[IX(i,j)] += a.dt*a.buoy*s[IX(i,j)];      // hot rises
            else      v[IX(i,j)] -= a.dt*a.grav*s[IX(i,j)];      // heavy sinks
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
        set_bc(u,1); set_bc(v,2);

        // advect velocity
        u0=u; v0=v; advect(u,u0); advect(v,v0); set_bc(u,1); set_bc(v,2);
        project();
        // advect scalar
        s0=s; advect(s,s0); set_bc(s,0);
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

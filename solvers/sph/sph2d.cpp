// FlowZoo - 2D weakly-compressible SPH (dam break).
//
// Cubic-spline kernel, Tait equation of state, density by continuity,
// Monaghan artificial viscosity, symplectic-Euler integration, uniform-grid
// neighbor search. A water column collapses under gravity and surges across
// the tank. Walls use a repulsive boundary force plus a reflective clamp.
//
// Outputs per frame: float32 [x, y, speed] for each particle, plus a
// front.csv (time, leading-edge x) for the dam-break front-speed validation.

#include <cstdio>
#include <cstdlib>
#include <cmath>
#ifndef M_PI
#define M_PI 3.14159265358979323846   // not defined by MinGW under strict -std=c++17
#endif
#include <string>
#include <vector>
#include <fstream>
#include <filesystem>
#include <algorithm>

struct Args{ double a=1.0,H=2.0,Lx=5.0,Ly=3.2,dp=0.025,g=9.81,tend=1.6;
             int save_every=12; std::string out="frames"; };
static Args parse(int c,char**v){ Args a;
    for(int i=1;i<c-1;i+=2){ std::string k=v[i],x=v[i+1];
        if(k=="--a")a.a=atof(x.c_str()); else if(k=="--H")a.H=atof(x.c_str());
        else if(k=="--Lx")a.Lx=atof(x.c_str()); else if(k=="--Ly")a.Ly=atof(x.c_str());
        else if(k=="--dp")a.dp=atof(x.c_str()); else if(k=="--tend")a.tend=atof(x.c_str());
        else if(k=="--save_every")a.save_every=atoi(x.c_str()); else if(k=="--out")a.out=x; }
    return a; }

int main(int argc,char**argv){
    Args A=parse(argc,argv);
    const double dp=A.dp, h=1.3*dp, h2=h*h, supp=2*h, rho0=1000.0, g=A.g, gamma=7.0;
    const double c0=10.0*sqrt(g*A.H), B=rho0*c0*c0/gamma, m=rho0*dp*dp;
    const double ad=10.0/(7.0*M_PI*h*h);            // 2D cubic-spline norm
    const double dt=0.08*h/c0, alphaV=0.20, vmax=1.5*c0;
    const int steps=(int)(A.tend/dt);

    // --- initialize the water column ---
    std::vector<double> x,y,vx,vy,rho,p;
    for(double px=dp*0.5; px<A.a; px+=dp)
        for(double py=dp*0.5; py<A.H; py+=dp){
            x.push_back(px); y.push_back(py); vx.push_back(0); vy.push_back(0);
            double rh=rho0*pow(1.0+rho0*g*(A.H-py)/B, 1.0/gamma);  // hydrostatic
            rho.push_back(rh); p.push_back(0); }
    const int N=x.size();
    std::vector<double> drho(N), ax(N), ay(N);
    printf("SPH dam break: %d particles, c0=%.1f, dt=%.2e, steps=%d\n",N,c0,dt,steps);

    auto Wgrad=[&](double r,double dx,double dy,double&gx,double&gy){
        double q=r/h; double dwdr=0;
        if(q<1) dwdr=ad/h*(-3*q+2.25*q*q);
        else if(q<2) dwdr=ad/h*(-0.75*(2-q)*(2-q));
        if(r>1e-12){ gx=dwdr*dx/r; gy=dwdr*dy/r; } else {gx=gy=0;} };

    // uniform grid for neighbor search
    int gnx=(int)(A.Lx/supp)+2, gny=(int)(A.Ly/supp)+2;
    std::vector<std::vector<int>> cell(gnx*gny);
    auto cellId=[&](double px,double py){ int ci=std::min(gnx-1,std::max(0,(int)(px/supp)+1));
        int cj=std::min(gny-1,std::max(0,(int)(py/supp)+1)); return cj*gnx+ci; };

    std::error_code _ec; std::filesystem::create_directories(A.out, _ec);
    std::ofstream front(A.out+"/front.csv"); front<<"t,xfront\n";
    int nf=0;

    for(int step=0; step<=steps; step++){
        // rebuild grid
        for(auto&cl:cell) cl.clear();
        for(int i=0;i<N;i++) cell[cellId(x[i],y[i])].push_back(i);

        // pressure (Tait), clamped >=0 to avoid free-surface tensile instability
        #pragma omp parallel for
        for(int i=0;i<N;i++){ double pr=B*(pow(rho[i]/rho0,gamma)-1.0); p[i]=pr>0?pr:0.0; }

        // interactions
        #pragma omp parallel for schedule(dynamic,64)
        for(int i=0;i<N;i++){
            double dr=0,fx=0,fy=0; int ci=(int)(x[i]/supp)+1, cj=(int)(y[i]/supp)+1;
            for(int dj=-1;dj<=1;dj++)for(int di=-1;di<=1;di++){
                int cc=(cj+dj)*gnx+(ci+di); if(cc<0||cc>=gnx*gny) continue;
                for(int j: cell[cc]){
                    double dx=x[i]-x[j], dy=y[i]-y[j], r2=dx*dx+dy*dy;
                    if(r2>=supp*supp||j==i) continue;
                    double r=sqrt(r2), gx,gy; Wgrad(r,dx,dy,gx,gy);
                    double dvx=vx[i]-vx[j], dvy=vy[i]-vy[j];
                    dr += m*(dvx*gx+dvy*gy);                       // continuity
                    double pr=-m*(p[i]/(rho[i]*rho[i])+p[j]/(rho[j]*rho[j]));
                    double visc=0; double vr=dvx*dx+dvy*dy;
                    if(vr<0){ double mu=h*vr/(r2+0.01*h2);
                        visc=-alphaV*c0*mu/(0.5*(rho[i]+rho[j])); }
                    fx += (pr - m*visc)*gx; fy += (pr - m*visc)*gy;
                }
            }
            drho[i]=dr; ax[i]=fx; ay[i]=fy-g;
        }

        // integrate (symplectic Euler) + bounded wall force + velocity limiter
        const double kw=0.10*c0*c0/h;          // bounded repulsive wall acceleration
        #pragma omp parallel for
        for(int i=0;i<N;i++){
            rho[i]+=dt*drho[i]; if(rho[i]<rho0*0.5) rho[i]=rho0*0.5;
            double wx=0,wy=0;
            if(x[i]<h)      wx+= kw*(1.0-x[i]/h);
            if(x[i]>A.Lx-h) wx-= kw*(1.0-(A.Lx-x[i])/h);
            if(y[i]<h)      wy+= kw*(1.0-y[i]/h);
            if(y[i]>A.Ly-h) wy-= kw*(1.0-(A.Ly-y[i])/h);
            vx[i]+=dt*(ax[i]+wx); vy[i]+=dt*(ay[i]+wy);
            double sp=sqrt(vx[i]*vx[i]+vy[i]*vy[i]);          // velocity limiter
            if(sp>vmax){ vx[i]*=vmax/sp; vy[i]*=vmax/sp; }
            x[i]+=dt*vx[i]; y[i]+=dt*vy[i];
            if(x[i]<0){x[i]=0; vx[i]*=-0.3;} if(x[i]>A.Lx){x[i]=A.Lx; vx[i]*=-0.3;}
            if(y[i]<0){y[i]=0; vy[i]*=-0.3;} if(y[i]>A.Ly){y[i]=A.Ly; vy[i]*=-0.3;}
        }

        if(step%A.save_every==0){
            std::vector<float> buf(3*N); double xf=0;
            for(int i=0;i<N;i++){ buf[3*i]=(float)x[i]; buf[3*i+1]=(float)y[i];
                buf[3*i+2]=(float)sqrt(vx[i]*vx[i]+vy[i]*vy[i]);
                if(y[i]<0.1*A.H && x[i]>xf) xf=x[i]; }   // leading edge near floor
            char fn[512]; snprintf(fn,sizeof(fn),"%s/frame_%05d.bin",A.out.c_str(),nf);
            std::ofstream of(fn,std::ios::binary); of.write((char*)buf.data(),buf.size()*sizeof(float));
            front<<step*dt<<","<<xf<<"\n"; nf++;
            if(step%(A.save_every*20)==0) printf("step %d/%d (%d frames) xfront=%.2f\n",step,steps,nf,xf);
        }
    }
    std::ofstream meta(A.out+"/meta.txt");
    meta<<"N "<<N<<"\nLx "<<A.Lx<<"\nLy "<<A.Ly<<"\na "<<A.a<<"\nH "<<A.H
        <<"\ng "<<g<<"\nnframes "<<nf<<"\n";
    printf("done: %d frames -> %s\n",nf,A.out.c_str());
    return 0;
}

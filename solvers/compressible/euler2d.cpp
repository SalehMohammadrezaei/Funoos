// FlowZoo - 2D compressible Euler solver (finite volume, MUSCL + HLLC).
//
// Conservative variables [rho, rho*u, rho*v, E]; piecewise-linear MUSCL
// reconstruction with a minmod limiter; HLLC approximate Riemann solver at
// the faces; SSP-RK2 time stepping with a CFL-limited dt. Transmissive
// (zero-gradient) boundaries. gamma = 1.4.
//
//   --mode sod    : 1D Sod shock tube (for exact-solution validation)
//   --mode blast  : circular high-pressure region -> expanding blast wave
//   --mode bubble : planar shock striking a light gas bubble
//
// Outputs float32 density frames (Ny x Nx) + meta with the physical time.

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cmath>
#include <string>
#include <vector>
#include <fstream>
#include <filesystem>
#include <algorithm>

static const double G = 1.4;

struct Args{ int nx=400,ny=200,steps=2000,save_every=20; double cfl=0.4,tend=0.2;
             std::string mode="sod",out="frames"; };
static Args parse(int c,char**v){ Args a;
    for(int i=1;i<c-1;i+=2){ std::string k=v[i],x=v[i+1];
        if(k=="--nx")a.nx=atoi(x.c_str()); else if(k=="--ny")a.ny=atoi(x.c_str());
        else if(k=="--steps")a.steps=atoi(x.c_str()); else if(k=="--save_every")a.save_every=atoi(x.c_str());
        else if(k=="--cfl")a.cfl=atof(x.c_str()); else if(k=="--tend")a.tend=atof(x.c_str());
        else if(k=="--mode")a.mode=x; else if(k=="--out")a.out=x; }
    return a; }

struct St{ double r,u,v,p; };
static inline double minmod(double a,double b){
    if(a*b<=0) return 0.0; return (fabs(a)<fabs(b))?a:b; }

// HLLC flux in x-direction (normal = x). Pass primitive L/R states.
static void hllc_x(const St&L,const St&R,double F[4]){
    double aL=sqrt(G*L.p/L.r), aR=sqrt(G*R.p/R.r);
    double SL=std::min(L.u-aL,R.u-aR), SR=std::max(L.u+aL,R.u+aR);
    double EL=L.p/(G-1)+0.5*L.r*(L.u*L.u+L.v*L.v);
    double ER=R.p/(G-1)+0.5*R.r*(R.u*R.u+R.v*R.v);
    auto flux=[&](const St&s,double E,double*f){
        f[0]=s.r*s.u; f[1]=s.r*s.u*s.u+s.p; f[2]=s.r*s.u*s.v; f[3]=(E+s.p)*s.u; };
    if(SL>=0){ flux(L,EL,F); return; }
    if(SR<=0){ flux(R,ER,F); return; }
    double Sstar=(R.p-L.p + L.r*L.u*(SL-L.u) - R.r*R.u*(SR-R.u))
                /(L.r*(SL-L.u) - R.r*(SR-R.u));
    if(Sstar>=0){
        double FL[4]; flux(L,EL,FL);
        double f=L.r*(SL-L.u)/(SL-Sstar);
        double Us[4]={f, f*Sstar, f*L.v,
                      f*(EL/L.r + (Sstar-L.u)*(Sstar + L.p/(L.r*(SL-L.u))))};
        double Uc[4]={L.r,L.r*L.u,L.r*L.v,EL};
        for(int k=0;k<4;k++) F[k]=FL[k]+SL*(Us[k]-Uc[k]);
    } else {
        double FR[4]; flux(R,ER,FR);
        double f=R.r*(SR-R.u)/(SR-Sstar);
        double Us[4]={f, f*Sstar, f*R.v,
                      f*(ER/R.r + (Sstar-R.u)*(Sstar + R.p/(R.r*(SR-R.u))))};
        double Uc[4]={R.r,R.r*R.u,R.r*R.v,ER};
        for(int k=0;k<4;k++) F[k]=FR[k]+SR*(Us[k]-Uc[k]);
    }
}

int main(int argc,char**argv){
    Args a=parse(argc,argv);
    const int nx=a.nx,ny=a.ny,N=nx*ny;
    auto IX=[&](int i,int j){return i+nx*j;};
    std::vector<double> r(N),mx(N),my(N),E(N), r1(N),mx1(N),my1(N),E1(N);

    auto setprim=[&](int s,double rho,double u,double v,double p){
        r[s]=rho; mx[s]=rho*u; my[s]=rho*v; E[s]=p/(G-1)+0.5*rho*(u*u+v*v); };

    // --- initial conditions ---
    for(int j=0;j<ny;j++)for(int i=0;i<nx;i++){ int s=IX(i,j);
        if(a.mode=="sod"){ if(i<nx/2) setprim(s,1.0,0,0,1.0); else setprim(s,0.125,0,0,0.1); }
        else if(a.mode=="blast"){ double dx=i-nx/2.0,dy=j-ny/2.0;
            if(dx*dx+dy*dy < (nx*0.06)*(nx*0.06)) setprim(s,1.0,0,0,10.0);
            else setprim(s,0.5,0,0,0.1); }
        else { // bubble: ambient air, a low-density bubble, a shock at left
            double cx=nx*0.45, cy=ny*0.5, rad=ny*0.18;
            double dx=i-cx,dy=j-cy; bool inb=(dx*dx+dy*dy<rad*rad);
            if(i< nx*0.12){ // post-shock (Mach ~1.5 air)
                setprim(s,1.34,0.40,0,1.5);
            } else if(inb) setprim(s,0.18,0,0,1.0);   // light bubble
            else setprim(s,1.0,0,0,1.0); }
    }

    auto getprim=[&](const std::vector<double>&R,const std::vector<double>&MX,
                     const std::vector<double>&MY,const std::vector<double>&EE,int s){
        St q; q.r=R[s]; q.u=MX[s]/R[s]; q.v=MY[s]/R[s];
        q.p=(G-1)*(EE[s]-0.5*R[s]*(q.u*q.u+q.v*q.v)); if(q.p<1e-6)q.p=1e-6; return q; };
    // physical fluxes (components ordered as [rho, rho*u, rho*v, E])
    auto xflux=[&](const St&q,double F[4]){ double E=q.p/(G-1)+0.5*q.r*(q.u*q.u+q.v*q.v);
        F[0]=q.r*q.u; F[1]=q.r*q.u*q.u+q.p; F[2]=q.r*q.u*q.v; F[3]=(E+q.p)*q.u; };
    auto yflux=[&](const St&q,double F[4]){ double E=q.p/(G-1)+0.5*q.r*(q.u*q.u+q.v*q.v);
        F[0]=q.r*q.v; F[1]=q.r*q.u*q.v; F[2]=q.r*q.v*q.v+q.p; F[3]=(E+q.p)*q.v; };

    // L(U): finite-volume residual with MUSCL+HLLC in both directions
    auto residual=[&](std::vector<double>&R,std::vector<double>&MX,
                      std::vector<double>&MY,std::vector<double>&EE,
                      std::vector<double>&dR,std::vector<double>&dMX,
                      std::vector<double>&dMY,std::vector<double>&dE){
        std::fill(dR.begin(),dR.end(),0.0);std::fill(dMX.begin(),dMX.end(),0.0);
        std::fill(dMY.begin(),dMY.end(),0.0);std::fill(dE.begin(),dE.end(),0.0);
        // x-direction faces
        #pragma omp parallel for schedule(static)
        for(int j=0;j<ny;j++)for(int i=0;i<nx-1;i++){
            int sL=IX(i,j),sR=IX(i+1,j);
            int sLL=IX(std::max(i-1,0),j), sRR=IX(std::min(i+2,nx-1),j);
            St cL=getprim(R,MX,MY,EE,sL), cR=getprim(R,MX,MY,EE,sR);
            St cLL=getprim(R,MX,MY,EE,sLL), cRR=getprim(R,MX,MY,EE,sRR);
            St L,Rr;
            L.r=cL.r+0.5*minmod(cL.r-cLL.r,cR.r-cL.r); L.u=cL.u+0.5*minmod(cL.u-cLL.u,cR.u-cL.u);
            L.v=cL.v+0.5*minmod(cL.v-cLL.v,cR.v-cL.v); L.p=cL.p+0.5*minmod(cL.p-cLL.p,cR.p-cL.p);
            Rr.r=cR.r-0.5*minmod(cR.r-cL.r,cRR.r-cR.r); Rr.u=cR.u-0.5*minmod(cR.u-cL.u,cRR.u-cR.u);
            Rr.v=cR.v-0.5*minmod(cR.v-cL.v,cRR.v-cR.v); Rr.p=cR.p-0.5*minmod(cR.p-cL.p,cRR.p-cR.p);
            if(L.p<1e-6||L.r<1e-6){L=cL;} if(Rr.p<1e-6||Rr.r<1e-6){Rr=cR;}
            double F[4]; hllc_x(L,Rr,F);
            #pragma omp atomic
            dR[sL]-=F[0];
            #pragma omp atomic
            dMX[sL]-=F[1];
            #pragma omp atomic
            dMY[sL]-=F[2];
            #pragma omp atomic
            dE[sL]-=F[3];
            #pragma omp atomic
            dR[sR]+=F[0];
            #pragma omp atomic
            dMX[sR]+=F[1];
            #pragma omp atomic
            dMY[sR]+=F[2];
            #pragma omp atomic
            dE[sR]+=F[3];
        }
        // y-direction faces (rotate: normal=y -> swap u,v into hllc_x)
        #pragma omp parallel for schedule(static)
        for(int j=0;j<ny-1;j++)for(int i=0;i<nx;i++){
            int sL=IX(i,j),sR=IX(i,j+1);
            int sLL=IX(i,std::max(j-1,0)), sRR=IX(i,std::min(j+2,ny-1));
            St cL=getprim(R,MX,MY,EE,sL),cR=getprim(R,MX,MY,EE,sR);
            St cLL=getprim(R,MX,MY,EE,sLL),cRR=getprim(R,MX,MY,EE,sRR);
            auto roty=[](St q){ std::swap(q.u,q.v); return q; };
            St L=roty(cL),Rr=roty(cR),LL=roty(cLL),RR=roty(cRR);
            St Lr,Rr2;
            Lr.r=L.r+0.5*minmod(L.r-LL.r,Rr.r-L.r); Lr.u=L.u+0.5*minmod(L.u-LL.u,Rr.u-L.u);
            Lr.v=L.v+0.5*minmod(L.v-LL.v,Rr.v-L.v); Lr.p=L.p+0.5*minmod(L.p-LL.p,Rr.p-L.p);
            Rr2.r=Rr.r-0.5*minmod(Rr.r-L.r,RR.r-Rr.r); Rr2.u=Rr.u-0.5*minmod(Rr.u-L.u,RR.u-Rr.u);
            Rr2.v=Rr.v-0.5*minmod(Rr.v-L.v,RR.v-Rr.v); Rr2.p=Rr.p-0.5*minmod(Rr.p-L.p,RR.p-Rr.p);
            if(Lr.p<1e-6||Lr.r<1e-6)Lr=L; if(Rr2.p<1e-6||Rr2.r<1e-6)Rr2=Rr;
            double F[4]; hllc_x(Lr,Rr2,F);  // F[1]=normal(y)-mom, F[2]=tangential(x)-mom
            #pragma omp atomic
            dR[sL]-=F[0];
            #pragma omp atomic
            dMY[sL]-=F[1];
            #pragma omp atomic
            dMX[sL]-=F[2];
            #pragma omp atomic
            dE[sL]-=F[3];
            #pragma omp atomic
            dR[sR]+=F[0];
            #pragma omp atomic
            dMY[sR]+=F[1];
            #pragma omp atomic
            dMX[sR]+=F[2];
            #pragma omp atomic
            dE[sR]+=F[3];
        }
        // transmissive domain boundaries: zero-gradient ghost = boundary cell,
        // so the boundary-face flux is the physical flux there (balances pressure)
        #pragma omp parallel for schedule(static)
        for(int j=0;j<ny;j++){
            double F[4]; int s;
            St qL=getprim(R,MX,MY,EE,IX(0,j));    xflux(qL,F); s=IX(0,j);
            dR[s]+=F[0];dMX[s]+=F[1];dMY[s]+=F[2];dE[s]+=F[3];
            St qR=getprim(R,MX,MY,EE,IX(nx-1,j)); xflux(qR,F); s=IX(nx-1,j);
            dR[s]-=F[0];dMX[s]-=F[1];dMY[s]-=F[2];dE[s]-=F[3];
        }
        #pragma omp parallel for schedule(static)
        for(int i=0;i<nx;i++){
            double F[4]; int s;
            St qB=getprim(R,MX,MY,EE,IX(i,0));    yflux(qB,F); s=IX(i,0);
            dR[s]+=F[0];dMX[s]+=F[1];dMY[s]+=F[2];dE[s]+=F[3];
            St qT=getprim(R,MX,MY,EE,IX(i,ny-1)); yflux(qT,F); s=IX(i,ny-1);
            dR[s]-=F[0];dMX[s]-=F[1];dMY[s]-=F[2];dE[s]-=F[3];
        }
    };

    auto maxspeed=[&](){ double m=1e-9;
        #pragma omp parallel for reduction(max:m)
        for(int s=0;s<N;s++){ St q=getprim(r,mx,my,E,s);
            double a2=sqrt(G*q.p/q.r); m=std::max(m,std::max(fabs(q.u),fabs(q.v))+a2);} return m; };

    std::error_code _ec; std::filesystem::create_directories(a.out, _ec);
    std::vector<double> dR(N),dMX(N),dMY(N),dE(N);
    double t=0; int nf=0;
    for(int step=0; step<a.steps && t<a.tend; step++){
        double dt=a.cfl/maxspeed(); if(t+dt>a.tend)dt=a.tend-t;
        // stage 1
        residual(r,mx,my,E,dR,dMX,dMY,dE);
        #pragma omp parallel for
        for(int s=0;s<N;s++){ r1[s]=r[s]+dt*dR[s]; mx1[s]=mx[s]+dt*dMX[s];
            my1[s]=my[s]+dt*dMY[s]; E1[s]=E[s]+dt*dE[s]; }
        // stage 2 (Heun)
        residual(r1,mx1,my1,E1,dR,dMX,dMY,dE);
        #pragma omp parallel for
        for(int s=0;s<N;s++){
            r[s]=0.5*(r[s]+r1[s]+dt*dR[s]); mx[s]=0.5*(mx[s]+mx1[s]+dt*dMX[s]);
            my[s]=0.5*(my[s]+my1[s]+dt*dMY[s]); E[s]=0.5*(E[s]+E1[s]+dt*dE[s]); }
        t+=dt;
        if(step%a.save_every==0){
            std::vector<float> buf(N); for(int s=0;s<N;s++)buf[s]=(float)r[s];
            char fn[512]; snprintf(fn,sizeof(fn),"%s/frame_%05d.bin",a.out.c_str(),nf);
            std::ofstream of(fn,std::ios::binary); of.write((char*)buf.data(),N*sizeof(float));
            nf++; if(step%(a.save_every*10)==0)printf("step %d t=%.4f (%d frames)\n",step,t,nf);
        }
    }
    // always save final density
    { std::vector<float> buf(N); for(int s=0;s<N;s++)buf[s]=(float)r[s];
      char fn[512]; snprintf(fn,sizeof(fn),"%s/final.bin",a.out.c_str());
      std::ofstream of(fn,std::ios::binary); of.write((char*)buf.data(),N*sizeof(float)); }
    std::ofstream meta(a.out+"/meta.txt");
    meta<<"nx "<<nx<<"\nny "<<ny<<"\nnframes "<<nf<<"\ntime "<<t<<"\nmode_"<<a.mode<<" 1\n";
    printf("done: %d frames, t=%.4f -> %s\n",nf,t,a.out.c_str());
    return 0;
}

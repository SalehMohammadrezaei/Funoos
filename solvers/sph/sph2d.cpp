// FlowZoo - 2D weakly-compressible SPH with selectable scenes.
//
// Cubic-spline kernel, Tait EOS (p>=0), density by continuity, Monaghan
// artificial viscosity, delta-SPH density diffusion + XSPH, symplectic-Euler
// integration, uniform-grid neighbour search. Walls use DYNAMIC BOUNDARY
// PARTICLES (Crespo/DualSPHysics): fixed particles in layers along the floor and
// side walls that develop pressure through the same EOS when the fluid presses
// on them, so the wall pushes back with real pressure instead of a penalty force
// on the fluid (no spurious near-wall velocity, no bounce-back). Scenes (--scene):
//   dam    : a water column collapses and surges across the tank
//   drop   : a round droplet falls into a still pool (crown splash)
//   slosh  : a layer of water sloshing under oscillating (sideways) gravity
//   pour   : water poured from a spout, continuously, filling the tank
//   waves  : a paddle wavemaker (moving wall particles) drives travelling waves
//   ship   : a rigid hull floats on the wavy ocean
//
// Outputs per frame float32 [x, y, speed] for each FLUID particle (walls hidden).

#include <cstdio>
#include <cstdlib>
#include <cmath>
#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif
#include <string>
#include <vector>
#include <fstream>
#include <filesystem>
#include <algorithm>

struct Args{ double a=1.0,H=2.0,Lx=5.0,Ly=3.2,dp=0.03,g=9.81,tend=2.0;
             double dh=0.70, sloshA=0.7, sloshT=1.1, sw=0.045, pourv=2.2,
                    waveA=0.0, waveT=0.9, shipsz=1.0;   // per-scene controls
             int save_every=12; std::string scene="dam",out="frames"; };
static Args parse(int c,char**v){ Args a;
    for(int i=1;i<c-1;i+=2){ std::string k=v[i],x=v[i+1];
        if(k=="--a")a.a=atof(x.c_str()); else if(k=="--H")a.H=atof(x.c_str());
        else if(k=="--Lx")a.Lx=atof(x.c_str()); else if(k=="--Ly")a.Ly=atof(x.c_str());
        else if(k=="--dp")a.dp=atof(x.c_str()); else if(k=="--tend")a.tend=atof(x.c_str());
        else if(k=="--g")a.g=atof(x.c_str()); else if(k=="--scene")a.scene=x;
        else if(k=="--dh")a.dh=atof(x.c_str()); else if(k=="--sloshA")a.sloshA=atof(x.c_str());
        else if(k=="--sloshT")a.sloshT=atof(x.c_str()); else if(k=="--sw")a.sw=atof(x.c_str());
        else if(k=="--pourv")a.pourv=atof(x.c_str()); else if(k=="--waveA")a.waveA=atof(x.c_str());
        else if(k=="--waveT")a.waveT=atof(x.c_str()); else if(k=="--shipsz")a.shipsz=atof(x.c_str());
        else if(k=="--save_every")a.save_every=atoi(x.c_str()); else if(k=="--out")a.out=x; }
    return a; }

int main(int argc,char**argv){
    Args A=parse(argc,argv);
    const std::string sc=A.scene;
    const double dp=A.dp, h=1.3*dp, h2=h*h, supp=2*h, rho0=1000.0, g=A.g, gamma=7.0;
    const double Href=std::max(A.H, A.Ly*0.5);
    const double c0=10.0*sqrt(g*Href), B=rho0*c0*c0/gamma, m=rho0*dp*dp;
    const double ad=10.0/(7.0*M_PI*h*h);
    const double dt=0.08*h/c0, alphaV=0.20, vmax=1.5*c0;
    const double deltaSPH=0.10, epsX=0.25;   // density diffusion + XSPH
    const int steps=(int)(A.tend/dt);

    std::vector<double> x,y,vx,vy,rho,p;
    std::vector<char> bnd;        // 0 = fluid, 1 = fixed dynamic-boundary particle
    std::vector<double> bx0;      // base x (boundary particles; used by the moving paddle)
    auto add_fluid=[&](double px,double py,double vyi){
        x.push_back(px); y.push_back(py); vx.push_back(0); vy.push_back(vyi);
        rho.push_back(rho0); p.push_back(0); bnd.push_back(0); bx0.push_back(0.0); };
    auto add_wall=[&](double px,double py){
        x.push_back(px); y.push_back(py); vx.push_back(0); vy.push_back(0);
        rho.push_back(rho0); p.push_back(0); bnd.push_back(1); bx0.push_back(px); };
    auto add_block=[&](double x0,double x1,double y0,double y1,double surf,double vyi=0.0){
        (void)surf;
        for(double px=x0+dp*0.5; px<x1; px+=dp)
            for(double py=y0+dp*0.5; py<y1; py+=dp) add_fluid(px,py,vyi);
    };
    // a round droplet (disk) — used by the drop scene so it actually looks like a drop
    auto add_disk=[&](double cx,double cy,double R,double vyi){
        for(double px=cx-R; px<=cx+R+1e-9; px+=dp)
            for(double py=cy-R; py<=cy+R+1e-9; py+=dp){
                double ddx=px-cx, ddy=py-cy;
                if(ddx*ddx+ddy*ddy<=R*R) add_fluid(px,py,vyi);
            }
    };
    // --- scene initial conditions (fluid) ---
    if(sc=="dam"){ add_block(0,A.a,0,A.H,A.H); }
    else if(sc=="drop"){ double Hp=0.30*A.Ly; add_block(0,A.Lx,0,Hp,Hp);
        double R=0.36*A.a, cx=A.Lx*0.5, cy=A.dh*A.Ly;       // release height = dh (disk centre)
        if(cy+R>A.Ly-2*dp) cy=A.Ly-2*dp-R;                  // keep clear of the ceiling
        if(cy-R<Hp+4*dp)   cy=Hp+4*dp+R;                    // and well above the pool
        add_disk(cx,cy,R,0.0); }
    else if(sc=="slosh"){ double Hs=0.42*A.Ly; add_block(0,A.Lx,0,Hs,Hs); }
    else if(sc=="waves"||sc=="ship"){ double Ho=0.40*A.Ly; add_block(0,A.Lx,0,Ho,Ho); }
    // pour starts from an empty glass and fills via continuous emission

    // --- dynamic boundary particles: fixed layers along floor + side walls ---
    const int NBL=3;                              // wall thickness (layers)
    for(int l=0;l<NBL;l++){ double py=-(l+0.5)*dp;                 // floor (spans under the walls too)
        for(double px=-(NBL-0.5)*dp; px<=A.Lx+(NBL-0.5)*dp+1e-9; px+=dp) add_wall(px,py); }
    for(int l=0;l<NBL;l++){ double px=-(l+0.5)*dp;                 // left wall (becomes the paddle)
        for(double py=0.5*dp; py<=A.Ly+1e-9; py+=dp) add_wall(px,py); }
    for(int l=0;l<NBL;l++){ double px=A.Lx+(l+0.5)*dp;             // right wall
        for(double py=0.5*dp; py<=A.Ly+1e-9; py+=dp) add_wall(px,py); }
    int Nfluid=0; for(char b: bnd) if(!b) Nfluid++;

    std::vector<double> drho, ax, ay, cvx, cvy;   // cvx/cvy: XSPH velocity correction

    // floating-ship rigid body (a tapered hull, handled by penalty contact)
    const bool ship=(sc=="ship");
    std::vector<double> hlx,hly;
    double Cx=0,Cy=0,th=0, bvx=0,bvy=0,bom=0, Mship=1,Iship=1;
    if(ship){
        double Ho=0.40*A.Ly, Wt=0.95*A.shipsz, Wb=0.50*A.shipsz, Hh=0.50*A.shipsz;
        for(double py=-Hh/2; py<=Hh/2+1e-9; py+=dp){
            double frac=(py+Hh/2)/Hh, halfw=0.5*(Wb+(Wt-Wb)*frac);
            for(double px=-halfw; px<=halfw+1e-9; px+=dp){ hlx.push_back(px); hly.push_back(py); }
        }
        Cx=A.Lx*0.45; Cy=Ho+Hh*0.12;
        double area=0.5*(Wt+Wb)*Hh; Mship=rho0*area*0.55; Iship=Mship*(Wt*Wt+Hh*Hh)/12.0;
    }
    printf("SPH scene=%s: %d fluid + %d wall particles, c0=%.1f, dt=%.2e, steps=%d\n",
           sc.c_str(),Nfluid,(int)x.size()-Nfluid,c0,dt,steps);

    auto Wgrad=[&](double r,double dx,double dy,double&gx,double&gy){
        double q=r/h, dwdr=0;
        if(q<1) dwdr=ad/h*(-3*q+2.25*q*q); else if(q<2) dwdr=ad/h*(-0.75*(2-q)*(2-q));
        if(r>1e-12){ gx=dwdr*dx/r; gy=dwdr*dy/r; } else {gx=gy=0;} };

    // uniform grid (origin shifted by a margin so the wall particles outside the
    // [0,Lx]x[0,Ly] box still land in valid cells)
    const double marg=(NBL+1)*dp;
    const int gnx=(int)((A.Lx+2*marg)/supp)+3, gny=(int)((A.Ly+2*marg)/supp)+3;
    std::vector<std::vector<int>> cell(gnx*gny);
    auto cix=[&](double px){ int c=(int)((px+marg)/supp)+1; return c<0?0:(c>=gnx?gnx-1:c); };
    auto ciy=[&](double py){ int c=(int)((py+marg)/supp)+1; return c<0?0:(c>=gny?gny-1:c); };

    std::error_code _ec; std::filesystem::create_directories(A.out, _ec);
    std::ofstream front(A.out+"/front.csv"); front<<"t,xfront\n";   // dam-break front validation
    int nf=0;
    const double kw=0.10*c0*c0/h;                 // (still used by the ship-hull contact)
    const double sx=A.Lx*0.5, sw=std::max(3.0*dp, A.sw*A.Lx);       // pour stream half-width
    const double Tw=A.waveT, paddle=(A.waveA>0.0)? A.waveA : std::min(0.5, 0.12*A.Lx);
    const double Ts=A.sloshT, sloshA=A.sloshA*g;
    const int Ncap=22000;

    for(int step=0; step<=steps; step++){
        double t=step*dt;
        double ramp=std::min(1.0, t/0.40), gt=g*ramp;     // ease gravity in
        // continuous emission for the pour scene
        if(sc=="pour" && (int)x.size()<Ncap && step%std::max(1,(int)(0.012/dt))==0){
            for(double px=sx-sw; px<sx+sw; px+=dp) add_fluid(px,A.Ly-2*dp,-A.pourv);
        }
        int N=x.size();
        if((int)drho.size()<N){ drho.resize(N); ax.resize(N); ay.resize(N); cvx.resize(N); cvy.resize(N); }

        for(auto&cl:cell) cl.clear();
        for(int i=0;i<N;i++) cell[ciy(y[i])*gnx+cix(x[i])].push_back(i);

        // equation of state (boundary particles never drop below rest density -> no suction)
        #pragma omp parallel for
        for(int i=0;i<N;i++){ double rr=(bnd[i]&&rho[i]<rho0)?rho0:rho[i];
            double pr=B*(pow(rr/rho0,gamma)-1.0); p[i]=pr>0?pr:0.0; }

        double gx=(sc=="slosh")? sloshA*sin(2*M_PI*t/Ts)*ramp : 0.0;

        #pragma omp parallel for schedule(dynamic,64)
        for(int i=0;i<N;i++){
            double dr=0,fx=0,fy=0,xsx=0,xsy=0; int ci=cix(x[i]), cj=ciy(y[i]);
            for(int dj=-1;dj<=1;dj++)for(int di=-1;di<=1;di++){
                int cci=ci+di, ccj=cj+dj;
                if(cci<0||cci>=gnx||ccj<0||ccj>=gny) continue;
                for(int j: cell[ccj*gnx+cci]){
                    double dx=x[i]-x[j], dy=y[i]-y[j], r2=dx*dx+dy*dy;
                    if(r2>=supp*supp||j==i) continue;
                    double r=sqrt(r2), gxk,gyk; Wgrad(r,dx,dy,gxk,gyk);
                    double dvx=vx[i]-vx[j], dvy=vy[i]-vy[j];
                    dr += m*(dvx*gxk+dvy*gyk);
                    // delta-SPH density diffusion (Molteni & Colagrossi)
                    double rdotg=dx*gxk+dy*gyk;            // (x_i-x_j)·∇W ; diffusion uses -rdotg
                    dr += deltaSPH*h*c0*(m/rho[j])*2.0*(rho[j]-rho[i])*(-rdotg)/(r2+0.01*h2);
                    double prf=-m*(p[i]/(rho[i]*rho[i])+p[j]/(rho[j]*rho[j]));
                    double visc=0, vrr=dvx*dx+dvy*dy;
                    if(vrr<0){ double mu=h*vrr/(r2+0.01*h2); visc=-alphaV*c0*mu/(0.5*(rho[i]+rho[j])); }
                    fx += (prf - m*visc)*gxk; fy += (prf - m*visc)*gyk;
                    // XSPH only among FLUID neighbours (don't drag the near-wall layer
                    // toward the wall's zero velocity -> avoids an artificial sticky skin)
                    if(!bnd[j]){
                        double q=r/h, W = (q<1)? ad*(1-1.5*q*q+0.75*q*q*q) : ad*0.25*(2-q)*(2-q)*(2-q);
                        xsx += (m/rho[j])*(vx[j]-vx[i])*W; xsy += (m/rho[j])*(vy[j]-vy[i])*W;
                    }
                }
            }
            drho[i]=dr; ax[i]=fx+gx; ay[i]=fy-gt; cvx[i]=xsx; cvy[i]=xsy;
        }

        // floating ship: penalty contact pushes fluid away from the hull; the
        // equal-and-opposite reaction (+gravity) drives the rigid body's heave,
        // surge and roll — buoyancy emerges from the fluid pressure on the hull.
        if(ship){
            double ca=cos(th), sa=sin(th), Fbx=0, Fby=0, Tb=0; int Nh=hlx.size();
            double kwt=kw*ramp;
            for(int k=0;k<Nh;k++){
                double hxk=Cx+ca*hlx[k]-sa*hly[k], hyk=Cy+sa*hlx[k]+ca*hly[k];
                int ci=cix(hxk), cj=ciy(hyk);
                for(int dj=-1;dj<=1;dj++)for(int di=-1;di<=1;di++){
                    int cci=ci+di, ccj=cj+dj;
                    if(cci<0||cci>=gnx||ccj<0||ccj>=gny) continue;
                    for(int j: cell[ccj*gnx+cci]){
                        if(bnd[j]) continue;
                        double dx=x[j]-hxk, dy=y[j]-hyk, r2=dx*dx+dy*dy;
                        if(r2>=h2||r2<1e-10) continue;
                        double d=sqrt(r2), push=kwt*(1.0-d/h), dirx=dx/d, diry=dy/d;
                        ax[j]+=push*dirx; ay[j]+=push*diry;          // push fluid out
                        double fxr=-m*push*dirx, fyr=-m*push*diry;   // reaction on hull
                        Fbx+=fxr; Fby+=fyr; Tb+=(hxk-Cx)*fyr-(hyk-Cy)*fxr;
                    }
                }
            }
            Fby-=Mship*gt;                                           // weight
            Fbx-=0.8*Mship*bvx; Fby-=0.8*Mship*bvy; Tb-=0.9*Iship*bom; // damping
            bvx+=dt*Fbx/Mship; bvy+=dt*Fby/Mship; bom+=dt*Tb/Iship;
            Cx+=dt*bvx; Cy+=dt*bvy; th+=dt*bom;
            if(th>0.5){th=0.5;bom=0;} if(th<-0.5){th=-0.5;bom=0;}
            if(Cx<1.0){Cx=1.0;bvx=0;} if(Cx>A.Lx-1.0){Cx=A.Lx-1.0;bvx=0;}
        }

        // wavemaker: the left-wall boundary particles physically move (the paddle),
        // pushing the fluid through their pressure — no special fluid force needed
        double tp=std::max(0.0, t-0.40);
        bool mover=(sc=="waves"||sc=="ship");
        double wallL = mover? paddle*0.5*(1-cos(2*M_PI*tp/Tw)) : 0.0;
        double wallV = (mover&&tp>0)? paddle*0.5*(2*M_PI/Tw)*sin(2*M_PI*tp/Tw) : 0.0;

        #pragma omp parallel for
        for(int i=0;i<N;i++){
            rho[i]+=dt*drho[i];
            if(bnd[i]){                                  // fixed wall particle
                if(rho[i]<rho0) rho[i]=rho0;             // no suction
                if(bx0[i]<0.0 && mover){ x[i]=bx0[i]+wallL; vx[i]=wallV; }  // paddle moves
                continue;
            }
            if(rho[i]<rho0*0.5) rho[i]=rho0*0.5;
            vx[i]+=dt*ax[i]; vy[i]+=dt*ay[i];
            double spd=sqrt(vx[i]*vx[i]+vy[i]*vy[i]);
            if(spd>vmax){ vx[i]*=vmax/spd; vy[i]*=vmax/spd; }
            x[i]+=dt*(vx[i]+epsX*cvx[i]); y[i]+=dt*(vy[i]+epsX*cvy[i]);
            // safety backstop only (the boundary particles do the real confinement)
            if(x[i]<0){x[i]=0; if(vx[i]<0)vx[i]=0;} if(x[i]>A.Lx){x[i]=A.Lx; if(vx[i]>0)vx[i]=0;}
            if(y[i]<0){y[i]=0; if(vy[i]<0)vy[i]=0;} if(y[i]>A.Ly){y[i]=A.Ly; if(vy[i]>0)vy[i]=0;}
        }

        if(step%A.save_every==0){
            std::vector<float> buf; buf.reserve(3*Nfluid+3);
            int Nw=0;
            for(int i=0;i<N;i++) if(!bnd[i]){
                buf.push_back((float)x[i]); buf.push_back((float)y[i]);
                buf.push_back((float)sqrt(vx[i]*vx[i]+vy[i]*vy[i])); Nw++; }
            char fn[512]; snprintf(fn,sizeof(fn),"%s/frame_%05d.bin",A.out.c_str(),nf);
            std::ofstream of(fn,std::ios::binary); of.write((char*)buf.data(),buf.size()*sizeof(float));
            if(ship){ double ca=cos(th),sa=sin(th); int Nh=hlx.size();
                std::vector<float> hb(2*Nh);
                for(int k=0;k<Nh;k++){ hb[2*k]=(float)(Cx+ca*hlx[k]-sa*hly[k]);
                    hb[2*k+1]=(float)(Cy+sa*hlx[k]+ca*hly[k]); }
                char hn[512]; snprintf(hn,sizeof(hn),"%s/hull_%05d.bin",A.out.c_str(),nf);
                std::ofstream hof(hn,std::ios::binary); hof.write((char*)hb.data(),hb.size()*sizeof(float)); }
            double xf=0; for(int i=0;i<N;i++) if(!bnd[i] && y[i]<0.1*A.H && x[i]>xf) xf=x[i];
            front<<t<<","<<xf<<"\n"; nf++;
            if(step%(A.save_every*20)==0) printf("step %d/%d (%d frames, %d fluid)\n",step,steps,nf,Nw);
        }
    }
    std::ofstream meta(A.out+"/meta.txt");
    meta<<"N "<<Nfluid<<"\nLx "<<A.Lx<<"\nLy "<<A.Ly<<"\ng "<<g
        <<"\nscene_"<<sc<<" 1\nnframes "<<nf<<"\n";
    printf("done: %d frames -> %s\n",nf,A.out.c_str());
    return 0;
}

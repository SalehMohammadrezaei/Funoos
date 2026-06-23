/* Funoos — frontend (talks to the Python backend via pywebview.api) */
"use strict";
let RUN = null, SPEC = null, PSTATE = {}, CUR_EXH = null, CUR_CMAP = null, FPS = 26, CUR = "intro", GAL = [];

const api = () => window.pywebview.api;
const $ = s => document.querySelector(s);
const el = (t, c, h) => { const e = document.createElement(t); if (c) e.className = c; if (h != null) e.innerHTML = h; return e; };
window.onProgress = m => {
  const s = $("#s-status"); if (s) s.textContent = "⏳ " + m;
  const k = $("#s-skelmsg"); if (k) k.textContent = m;
  const pm = /(\d+)\s*%/.exec(m), f = $("#s-pfill");           // drive the progress bar from "… N%"
  if (f && pm) { f.style.width = pm[1] + "%"; f.parentElement.style.opacity = 1; }
};

function show(v) {
  document.querySelectorAll(".view").forEach(x => x.classList.remove("active"));
  $("#" + v).classList.add("active");
  document.querySelectorAll(".railbtn").forEach(b => b.classList.toggle("on", b.dataset.view === v));
  CUR = v;
  $("#heroCanvas").style.opacity = v === "intro" ? 0.5 : 0.1;
  if (v !== "studio") { const sv = $("#s-video"); if (sv) sv.pause(); }
  if (v === "intro") { revealAll($("#intro")); runCounters(); }
  if (v === "gallery") { const r = $("#gallery-scroll"); if (r) r.scrollTop = 0; }   // open at the top
}
function revealAll(root) {
  root.querySelectorAll(".reveal").forEach((e, i) => { e.classList.remove("in"); setTimeout(() => e.classList.add("in"), 80 + i * 90); });
}

/* cursor spotlight — glows through the glass */
window.addEventListener("pointermove", e => {
  const r = document.documentElement.style;
  r.setProperty("--mx", e.clientX + "px"); r.setProperty("--my", e.clientY + "px");
});

/* boot */
function boot() { buildGallery(); show("intro"); }
if (window.pywebview && window.pywebview.api) boot();
else window.addEventListener("pywebviewready", boot);

/* animated counters */
let countersDone = false;
function runCounters() {
  if (countersDone) return; countersDone = true;
  document.querySelectorAll(".stat .n").forEach(n => {
    const target = +n.dataset.count, t0 = performance.now(), dur = 1100;
    const tick = now => { const p = Math.min(1, (now - t0) / dur); n.textContent = Math.round(target * (1 - Math.pow(1 - p, 3))); if (p < 1) requestAnimationFrame(tick); };
    requestAnimationFrame(tick);
  });
}

/* ───────── gallery: a card grid (one card per scene) ───────── */
const SHORT = {
  "Lattice–Boltzmann": "Lattice–Boltzmann", "Incompressible Navier–Stokes": "Navier–Stokes",
  "Compressible Euler": "Compressible Euler", "Smoothed-Particle Hydrodynamics": "SPH",
  "Pseudo-spectral": "Pseudo-spectral", "Reaction–Diffusion": "Reaction–Diffusion"
};
const ACC = {
  "Lattice–Boltzmann": "#5b86f0", "Incompressible Navier–Stokes": "#e0a23a",
  "Compressible Euler": "#e35d6a", "Smoothed-Particle Hydrodynamics": "#56c5e8",
  "Pseudo-spectral": "#9b8cff", "Reaction–Diffusion": "#9be25a"
};
const SCHEME = {
  "Lattice–Boltzmann": "D2Q9 BGK", "Incompressible Navier–Stokes": "Projection",
  "Compressible Euler": "HLLC", "Smoothed-Particle Hydrodynamics": "WCSPH",
  "Pseudo-spectral": "FFT", "Reaction–Diffusion": "Gray–Scott"
};
// play only the cards currently on screen (keeps 29 clips light)
const _vio = new IntersectionObserver(es => es.forEach(e => {
  const v = e.target; if (e.isIntersecting) v.play().catch(() => {}); else v.pause();
}), { root: null, threshold: 0.15 });

async function buildGallery() {
  GAL = await api().catalog();
  const root = $("#gallery-grid"); root.innerHTML = "";
  for (const g of GAL) {
    const acc = ACC[g.method] || "#5b86f0", method = SHORT[g.method] || g.method, scheme = SCHEME[g.method] || "";
    for (const s of g.scenes) root.append(sceneCard(s, acc, method, scheme));
  }
}
function sceneCard(s, acc, method, scheme) {
  const c = el("div", "gcard");
  const media = el("div", "media");
  if (s.clip) { const v = el("video"); v.src = s.clip; v.loop = v.muted = true; v.playsInline = true; v.preload = "metadata"; media.append(v); _vio.observe(v); }
  const pl = el("div", "pill left"); const dot = el("span", "dot"); dot.style.background = acc;
  pl.append(dot, document.createTextNode(method));
  media.append(pl, el("div", "pill right", scheme));
  const body = el("div", "gbody");
  body.append(el("div", "ttl", s.name));
  const foot = el("div", "foot");
  const teaser = (s.blurb || "").split(/[.;—]/)[0].trim();
  foot.append(el("div", "sub", teaser.length > 46 ? teaser.slice(0, 44).trim() + "…" : teaser),
    el("div", "go", "↗"));
  body.append(foot);
  c.append(media, body);
  c.onclick = () => openDetail(s.key);
  return c;
}

/* ───────── detail ───────── */
// FLIP morph: navigate first (so the click always works), then glide a clone of the
// card onto the detail video — it lands exactly on it, so there's no jump.
async function morphToDetail(card, key) {
  const r0 = card.getBoundingClientRect(), v0 = card.querySelector("video");
  await openDetail(key);                       // build + show detail (navigation is guaranteed)
  const target = $("#d-video"), r1 = target.getBoundingClientRect();
  if (!v0 || !r1.width) return;                // nothing to animate; detail is already up
  const clone = el("div");
  clone.style.cssText = `position:fixed;left:0;top:0;width:${r1.width}px;height:${r1.height}px;transform-origin:top left;`
    + `border-radius:14px;overflow:hidden;background:#06101f;z-index:200;pointer-events:none;box-shadow:0 40px 95px rgba(0,0,0,.55)`;
  const v = el("video"); v.src = v0.currentSrc || v0.src; v.loop = v.muted = v.autoplay = true; v.playsInline = true;
  v.style.cssText = "width:100%;height:100%;object-fit:contain"; clone.append(v);
  document.body.append(clone); v.play().catch(() => {});
  const sx = r0.width / r1.width, sy = r0.height / r1.height;
  const anim = clone.animate(
    [{ transform: `translate(${r0.left}px,${r0.top}px) scale(${sx},${sy})` },
     { transform: `translate(${r1.left}px,${r1.top}px) scale(1,1)` }],
    { duration: 440, easing: "cubic-bezier(.5,0,.18,1)" });
  anim.onfinish = () => clone.remove();
  setTimeout(() => clone.remove(), 700);
}
async function openDetail(key) {
  const d = await api().scene_detail(key);
  $("#d-method").textContent = d.method; $("#d-title").textContent = d.name; $("#d-video").src = d.clip;
  const t = $("#d-text"); t.innerHTML = "";
  t.append(section("this scene", d.blurb), section("the physics", d.physics));
  if (d.eq) { const k = el("div", "section"); k.append(el("div", "kicker", "GOVERNING EQUATION")); const b = el("div", "eqbox"); const im = el("img"); im.src = d.eq; b.append(im); k.append(b); t.append(k); }
  if (d.terms) t.append(el("div", "terms", d.terms));
  if (d.ic || d.bc) {                                   // initial & boundary conditions
    const sec = el("div", "section"); sec.append(el("div", "kicker", "SETUP — INITIAL & BOUNDARY CONDITIONS"));
    const box = el("div", "setup");
    if (d.ic) box.append(el("div", "sline", `<b>Initial</b>${d.ic}`));
    if (d.bc) box.append(el("div", "sline", `<b>Boundary</b>${d.bc}`));
    sec.append(box); t.append(sec);
  }
  t.append(section("how it's solved", d.numerics));
  const v = section("validation", "✓  " + d.validation); v.querySelector(".kicker").style.color = "#a9e6a0"; v.querySelector(".body").classList.add("ok"); t.append(v);
  buildRelated(t, key);
  [...t.children].forEach((c, i) => { c.classList.add("reveal"); setTimeout(() => c.classList.add("in"), 60 + i * 70); });
  $("#d-open").onclick = () => openStudio(d);
  show("detail");
}
function buildRelated(t, key) {
  let group = null;
  for (const g of GAL) if (g.scenes.some(s => s.key === key)) group = g;
  if (!group || group.scenes.length < 2) return;
  const sec = el("div", "section"); sec.append(el("div", "kicker", "MORE IN THIS METHOD"));
  const rail = el("div", "related");
  for (const s of group.scenes) {
    if (s.key === key) continue;
    const m = el("div", "rel"); if (s.clip) { const v = el("video"); v.src = s.clip; v.loop = v.muted = v.autoplay = true; v.playsInline = true; m.append(v); }
    m.append(el("div", "rnm", s.name)); m.onclick = () => openDetail(s.key); rail.append(m);
  }
  sec.append(rail); t.append(sec);
}
function section(head, body) { const s = el("div", "section"); s.append(el("div", "kicker", head.toUpperCase()), el("div", "read body", body)); return s; }

/* ───────── studio ───────── */
function openStudio(d) {
  CUR_EXH = d.exhibit; CUR_CMAP = d.cmap || null; SPEC = d.params; PSTATE = {};
  for (const q of SPEC) PSTATE[q.name] = q.default;
  if (d.preset) for (const k in d.preset) PSTATE[k] = d.preset[k];
  $("#s-name").textContent = (d.name || "parameters").toUpperCase();
  renderParams();
  RUN = null; $("#s-video").style.display = "none"; $("#s-hint").style.display = "block";
  $("#s-views").innerHTML = ""; $("#s-cmap").innerHTML = ""; $("#s-plotpanel").style.display = "none";
  $("#s-kpis").innerHTML = '<div class="muted" style="font-size:12px">Run a simulation to see live readouts.</div>';
  $("#s-status").textContent = "Ready."; show("studio");
}
function visible(q) { return !q.when || q.when[1].includes(PSTATE[q.when[0]]); }
function renderParams() {
  const root = $("#s-params"); root.innerHTML = ""; const groups = {};
  for (const q of SPEC) { if (!visible(q)) continue; (groups[q.group] || (groups[q.group] = [])).push(q); }
  for (const g of ["Geometry", "Physics", "Render"]) {
    if (!groups[g]) continue;
    const blk = el("div", "pgroup"); blk.append(el("div", "kicker", g));
    for (const q of groups[g]) blk.append(field(q)); root.append(blk);
  }
}
function field(q) {
  const f = el("div", "field"); const lab = el("label", null, q.label || q.name);
  if (q.type === "float") lab.append(el("span", "rng", `&nbsp;&nbsp;(${q.min} – ${q.max})`));
  f.append(lab); let inp;
  if (q.type === "choice") {
    inp = el("select");
    for (const c of q.choices) { const o = el("option", null, c); o.value = c; if (c === PSTATE[q.name]) o.selected = true; inp.append(o); }
    inp.onchange = () => { PSTATE[q.name] = inp.value; renderParams(); };
  } else {
    inp = el("input"); inp.type = "text"; inp.value = PSTATE[q.name];
    inp.oninput = () => { PSTATE[q.name] = q.type === "float" ? parseFloat(inp.value) : inp.value; };
  }
  f.append(inp); return f;
}
async function runSim() {
  const btn = $("#s-run"); btn.disabled = true; btn.textContent = "●  Simulating…";
  $("#s-skel").classList.add("on"); $("#s-hint").style.display = "none"; $("#s-plotpanel").style.display = "none";
  const pf = $("#s-pfill"); if (pf) { pf.style.width = "0%"; } $("#s-skelmsg").textContent = "simulating…";
  const params = { ...PSTATE }; const view = (RUN && RUN.view) || null;
  try {
    const r = await api().run(CUR_EXH, params, view, CUR_CMAP); RUN = r; FPS = 26;
    buildViewbar(r); setVideo(r.video); renderKPIs(r.stats || []);
    $("#s-status").textContent = "✓ " + r.info; toast("Simulation ready", "ok");
  } catch (e) { $("#s-status").textContent = "⚠ " + e; toast("Run failed: " + e, "err"); }
  $("#s-skel").classList.remove("on"); btn.disabled = false; btn.textContent = "▶  Run simulation";
}
function renderKPIs(stats) {
  const k = $("#s-kpis"); k.innerHTML = "";
  if (!stats.length) { k.innerHTML = '<div class="muted" style="font-size:12px">No readouts.</div>'; return; }
  for (const s of stats) {
    if (s.frac != null) {
      const t = el("div", "kpi gauge" + (s.accent ? " accent" : ""));
      const dial = el("div", "dial", kpiGauge(s.frac, s.accent));
      dial.append(el("div", "dval", `${s.v}${s.u ? `<small>${s.u}</small>` : ""}`));
      t.append(dial, el("div", "l", s.l)); k.append(t);
    } else {
      const t = el("div", "kpi" + (s.accent ? " accent" : ""));
      t.append(el("div", "l", s.l), el("div", "v", s.v + (s.u ? ` <small>${s.u}</small>` : "")));
      k.append(t);
    }
  }
}
// 270° speedometer-style SVG dial filled to `frac`
function kpiGauge(frac, accent) {
  const R = 33, C = 2 * Math.PI * R, span = 0.75, dash = C * span;
  const val = (dash * Math.max(0, Math.min(1, frac))).toFixed(1), Cf = C.toFixed(1);
  const col = accent ? "#e1fc66" : "#6f90e8";
  return `<svg width="84" height="84" viewBox="0 0 84 84">
    <g transform="rotate(135 42 42)">
      <circle cx="42" cy="42" r="${R}" fill="none" stroke="rgba(255,255,255,.10)" stroke-width="7" stroke-linecap="round" stroke-dasharray="${dash.toFixed(1)} ${Cf}"/>
      <circle cx="42" cy="42" r="${R}" fill="none" stroke="${col}" stroke-width="7" stroke-linecap="round" stroke-dasharray="${val} ${Cf}"/>
    </g></svg>`;
}
function buildViewbar(r) {
  const seg = $("#s-views"); seg.innerHTML = "";
  for (const v of r.views) { const b = el("button", v === r.view ? "on" : "", v); b.onclick = () => switchView(v); seg.append(b); }
  const cm = $("#s-cmap"); cm.innerHTML = "";
  for (const c of r.cmaps) { const o = el("option", null, c); o.value = c; if (c === r.defcmap) o.selected = true; cm.append(o); }
}
async function switchView(v) {
  if (!RUN || v === RUN.view) return; setBusy("rendering " + v + "…");
  try { const r = await api().render_view(RUN.run_id, v, $("#s-cmap").value); RUN.view = v; setVideo(r.video);
    document.querySelectorAll("#s-views button").forEach(b => b.classList.toggle("on", b.textContent === v)); }
  catch (e) { toast("" + e, "err"); }
  $("#s-skel").classList.remove("on");
}
async function recolor() {
  if (!RUN) return; setBusy("recolouring…");
  try { const r = await api().render_view(RUN.run_id, RUN.view, $("#s-cmap").value); setVideo(r.video); } catch (e) { toast("" + e, "err"); }
  $("#s-skel").classList.remove("on");
}
function setBusy(msg) { $("#s-skel").classList.add("on"); $("#s-skelmsg").textContent = msg; $("#s-status").textContent = "⏳ " + msg; }
function setVideo(src) {
  const v = $("#s-video"); v.src = src; v.style.display = "block"; $("#s-hint").style.display = "none";
  v.playbackRate = 1; $("#s-rate").textContent = "1×";
  v.onloadeddata = () => { v.play(); $("#s-play").textContent = "⏸"; };
}
async function togglePlots() {
  if (!RUN) { toast("Run a simulation first", "err"); return; }
  const p = $("#s-plotpanel"); if (p.style.display === "block") { p.style.display = "none"; return; }
  setBusy("computing diagnostics…");
  try {
    const plots = await api().diagnostics(RUN.run_id); p.innerHTML = "";
    if (!plots.length) p.append(el("div", "muted", "No diagnostics for this case."));
    for (const pl of plots) {
      const card = el("div", "plot");
      card.append(el("div", "kicker", pl.title));
      const i = el("img"); i.src = pl.img; card.append(i);
      if (pl.explain) card.append(el("div", "explain", pl.explain));
      p.append(card);
    }
    p.style.display = "block"; $("#s-status").textContent = "✓ diagnostics ready.";
  } catch (e) { toast("" + e, "err"); }
  $("#s-skel").classList.remove("on");
}

/* transport */
const sv = () => $("#s-video");
function vToggle() { const v = sv(); if (v.paused) { v.play(); $("#s-play").textContent = "⏸"; } else { v.pause(); $("#s-play").textContent = "▶"; } }
function vStep(d) { const v = sv(); v.pause(); $("#s-play").textContent = "▶"; v.currentTime = Math.min(v.duration || 0, Math.max(0, v.currentTime + d / FPS)); }
function vSeek(t) { sv().currentTime = t; }
function vScrub() { const v = sv(); if (v.duration) v.currentTime = $("#s-scrub").value / 1000 * v.duration; }
function vSpeed(d) { const v = sv(); v.playbackRate = Math.min(4, Math.max(0.25, v.playbackRate + d * 0.25)); $("#s-rate").textContent = v.playbackRate + "×"; }
document.addEventListener("timeupdate", e => {
  if (e.target.id !== "s-video" || !e.target.duration) return; const v = e.target;
  $("#s-scrub").value = v.currentTime / v.duration * 1000;
  const f = n => { const m = Math.floor(n / 60), s = Math.floor(n % 60); return m + ":" + String(s).padStart(2, "0"); };
  $("#s-time").textContent = f(v.currentTime) + " / " + f(v.duration);
}, true);

/* toasts */
function toast(msg, kind) {
  const t = el("div", "toast " + (kind || ""), msg); $("#toasts").append(t);
  requestAnimationFrame(() => t.classList.add("in"));
  setTimeout(() => { t.classList.remove("in"); setTimeout(() => t.remove(), 450); }, 3400);
}

/* ───────── living hero canvas (flow-field particles) ───────── */
(function hero() {
  const cv = $("#heroCanvas"), ctx = cv.getContext("2d");
  let W, H, P = [];
  function resize() { W = cv.width = innerWidth; H = cv.height = innerHeight; }
  addEventListener("resize", resize); resize();
  const N = Math.min(700, Math.floor(W * H / 2600));
  for (let i = 0; i < N; i++) P.push({ x: Math.random() * W, y: Math.random() * H, a: Math.random() });
  function vel(x, y, t) {                       // smooth pseudo flow-field
    const s = 0.0016;
    return [Math.cos(y * s + t) + 0.6 * Math.sin((x + y) * s * 0.7 - t * 0.7),
            Math.sin(x * s - t * 0.8) + 0.6 * Math.cos((x - y) * s * 0.6 + t)];
  }
  let t = 0;
  (function frame() {
    t += 0.0016;
    ctx.fillStyle = "rgba(7,13,24,0.10)"; ctx.fillRect(0, 0, W, H);
    for (const p of P) {
      const [vx, vy] = vel(p.x, p.y, t); const px = p.x, py = p.y;
      p.x += vx * 0.9; p.y += vy * 0.9; p.a += 0.01;
      if (p.x < 0 || p.x > W || p.y < 0 || p.y > H) { p.x = Math.random() * W; p.y = Math.random() * H; }
      const hue = 210 + 30 * Math.sin(p.a);
      ctx.strokeStyle = `hsla(${hue},80%,68%,0.5)`; ctx.lineWidth = 1.1;
      ctx.beginPath(); ctx.moveTo(px, py); ctx.lineTo(p.x, p.y); ctx.stroke();
    }
    requestAnimationFrame(frame);
  })();
})();

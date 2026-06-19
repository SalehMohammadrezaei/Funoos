/* Funoos — frontend logic (talks to the Python backend via pywebview.api) */
"use strict";
let API = null, RUN = null, SPEC = null, PSTATE = {}, CUR_EXH = null, FPS = 26;

function api(){ return window.pywebview.api; }
window.onProgress = m => { const s = document.querySelector("#s-status"); if (s) s.textContent = "⏳ " + m; };
const $ = s => document.querySelector(s);
const el = (t, c, h) => { const e = document.createElement(t); if (c) e.className = c; if (h != null) e.innerHTML = h; return e; };

function show(v){
  document.querySelectorAll(".view").forEach(x => x.classList.remove("active"));
  $("#" + v).classList.add("active");
  // pause the studio video when leaving
  if (v !== "studio") { const sv = $("#s-video"); if (sv) sv.pause(); }
}

/* ───────── boot ───────── */
function boot(){ buildGallery(); }
if (window.pywebview && window.pywebview.api) boot();
else window.addEventListener("pywebviewready", boot);

/* ───────── gallery ───────── */
async function buildGallery(){
  const groups = await api().catalog();
  const root = $("#gallery-grid"); root.innerHTML = "";
  for (const g of groups){
    const head = el("div", "method-head");
    head.append(el("div", "bar"), el("div", "name", g.method),
                el("div", "count", `${g.scenes.length} scene${g.scenes.length > 1 ? "s" : ""}`));
    root.append(head);
    const grid = el("div", "grid");
    for (const s of g.scenes) grid.append(sceneCard(s));
    root.append(grid);
  }
}
function sceneCard(s){
  const card = el("div", "card");
  const clip = el("div", "clip");
  if (s.clip){
    const v = el("video"); v.src = s.clip; v.autoplay = v.loop = v.muted = true;
    v.playsInline = true; clip.append(v);
  }
  const meta = el("div", "meta");
  meta.append(el("div", "nm", s.name), el("div", "bl", s.blurb));
  card.append(clip, meta);
  card.onclick = () => openDetail(s.key);
  return card;
}

/* ───────── detail ───────── */
async function openDetail(key){
  const d = await api().scene_detail(key);
  $("#d-method").textContent = d.method;
  $("#d-title").textContent = d.name;
  $("#d-video").src = d.clip;
  const t = $("#d-text"); t.innerHTML = "";
  t.append(section("this scene", d.blurb));
  t.append(section("the physics", d.physics));
  if (d.eq){
    const k = el("div"); k.append(el("div", "kicker", "GOVERNING EQUATION"));
    const box = el("div", "eqbox"); const img = el("img"); img.src = d.eq; box.append(img);
    k.append(box); k.className = "section"; t.append(k);
  }
  if (d.terms) t.append(el("div", "terms", d.terms));
  t.append(section("how it's solved", d.numerics));
  const v = section("validation", "✓  " + d.validation); v.querySelector(".kicker").style.color = "#a9e6a0";
  v.querySelector(".body").classList.add("ok"); t.append(v);
  $("#d-open").onclick = () => openStudio(d);
  show("detail");
}
function section(head, body){
  const s = el("div", "section");
  s.append(el("div", "kicker", head.toUpperCase()));
  s.append(el("div", "read body", body));
  return s;
}

/* ───────── studio ───────── */
function openStudio(d){
  CUR_EXH = d.exhibit; SPEC = d.params; PSTATE = {};
  for (const q of SPEC) PSTATE[q.name] = q.default;
  if (d.preset) for (const k in d.preset) PSTATE[k] = d.preset[k];
  $("#s-name").textContent = "· " + d.name;
  renderParams();
  // reset stage
  RUN = null; $("#s-video").style.display = "none"; $("#s-hint").style.display = "block";
  $("#s-views").innerHTML = ""; $("#s-cmap").innerHTML = ""; $("#s-transport").style.display = "none";
  $("#s-plotpanel").style.display = "none"; $("#s-status").textContent = "Ready.";
  show("studio");
}
function visible(q){
  if (!q.when) return true;
  return q.when[1].includes(PSTATE[q.when[0]]);
}
function renderParams(){
  const root = $("#s-params"); root.innerHTML = "";
  const groups = {};
  for (const q of SPEC){ if (!visible(q)) continue; (groups[q.group] || (groups[q.group] = [])).push(q); }
  for (const g of ["Geometry", "Physics", "Render"]){
    if (!groups[g]) continue;
    const blk = el("div", "pgroup"); blk.append(el("div", "kicker", g));
    for (const q of groups[g]) blk.append(field(q));
    root.append(blk);
  }
}
function field(q){
  const f = el("div", "field");
  const lab = el("label", null, q.label || q.name);
  if (q.type === "float") lab.append(el("span", "rng", `&nbsp;&nbsp;(${q.min} – ${q.max})`));
  f.append(lab);
  let inp;
  if (q.type === "choice"){
    inp = el("select");
    for (const c of q.choices){ const o = el("option", null, c); o.value = c; if (c === PSTATE[q.name]) o.selected = true; inp.append(o); }
    inp.onchange = () => { PSTATE[q.name] = inp.value; renderParams(); };
  } else {
    inp = el("input"); inp.type = q.type === "str" ? "text" : "text";
    inp.value = PSTATE[q.name];
    inp.oninput = () => { PSTATE[q.name] = q.type === "float" ? parseFloat(inp.value) : inp.value; };
  }
  f.append(inp); return f;
}

async function runSim(){
  const btn = $("#s-run"); btn.disabled = true; btn.textContent = "●  Simulating…";
  $("#s-spin").style.display = "block"; $("#s-hint").style.display = "none";
  $("#s-plotpanel").style.display = "none";
  const params = {}; for (const k in PSTATE) params[k] = PSTATE[k];
  const view = (RUN && RUN.view) || null;
  try {
    const r = await api().run(CUR_EXH, params, view);
    RUN = r; FPS = 26;
    buildViewbar(r);
    setVideo(r.video);
    $("#s-status").textContent = "✓ " + r.info + " — switch views live.";
  } catch (e){
    $("#s-status").textContent = "⚠ " + e;
  }
  $("#s-spin").style.display = "none";
  btn.disabled = false; btn.textContent = "▶  Run simulation";
}
function buildViewbar(r){
  const seg = $("#s-views"); seg.innerHTML = "";
  for (const v of r.views){
    const b = el("button", v === r.view ? "on" : "", v);
    b.onclick = () => switchView(v); seg.append(b);
  }
  const cm = $("#s-cmap"); cm.innerHTML = "";
  for (const c of r.cmaps){ const o = el("option", null, c); o.value = c; if (c === r.defcmap) o.selected = true; cm.append(o); }
}
async function switchView(v){
  if (!RUN || v === RUN.view) return;
  setBusy(true, "rendering " + v + "…");
  const r = await api().render_view(RUN.run_id, v, $("#s-cmap").value);
  RUN.view = v; setVideo(r.video);
  document.querySelectorAll("#s-views button").forEach(b => b.classList.toggle("on", b.textContent === v));
  setBusy(false);
}
async function recolor(){
  if (!RUN) return;
  setBusy(true, "recoloring…");
  const r = await api().render_view(RUN.run_id, RUN.view, $("#s-cmap").value);
  setVideo(r.video); setBusy(false);
}
function setBusy(b, msg){
  $("#s-spin").style.display = b ? "block" : "none";
  if (msg) $("#s-status").textContent = "⏳ " + msg;
}
function setVideo(src){
  const v = $("#s-video"); v.src = src; v.style.display = "block"; $("#s-hint").style.display = "none";
  $("#s-transport").style.display = "flex"; v.playbackRate = 1; $("#s-rate").textContent = "1×";
  v.onloadeddata = () => { v.play(); $("#s-play").textContent = "⏸"; };
}

/* plots */
async function togglePlots(){
  if (!RUN) return;
  const p = $("#s-plotpanel");
  if (p.style.display === "block"){ p.style.display = "none"; return; }
  setBusy(true, "computing diagnostics…");
  const plots = await api().diagnostics(RUN.run_id);
  p.innerHTML = "";
  if (!plots.length) p.append(el("div", "muted", "No diagnostics for this case."));
  for (const pl of plots){ p.append(el("div", "kicker", pl.title)); const i = el("img"); i.src = pl.img; p.append(i); }
  p.style.display = "block"; setBusy(false); $("#s-status").textContent = "✓ diagnostics ready.";
}

/* transport */
const sv = () => $("#s-video");
function vToggle(){ const v = sv(); if (v.paused){ v.play(); $("#s-play").textContent = "⏸"; } else { v.pause(); $("#s-play").textContent = "▶"; } }
function vStep(d){ const v = sv(); v.pause(); $("#s-play").textContent = "▶"; v.currentTime = Math.min(v.duration || 0, Math.max(0, v.currentTime + d / FPS)); }
function vSeek(t){ sv().currentTime = t; }
function vScrub(){ const v = sv(); if (v.duration) v.currentTime = $("#s-scrub").value / 1000 * v.duration; }
function vSpeed(d){ const v = sv(); v.playbackRate = Math.min(4, Math.max(0.25, v.playbackRate + d * 0.25)); $("#s-rate").textContent = v.playbackRate + "×"; }
document.addEventListener("timeupdate", e => {
  if (e.target.id !== "s-video") return;
  const v = e.target; if (!v.duration) return;
  $("#s-scrub").value = v.currentTime / v.duration * 1000;
  const f = n => { const m = Math.floor(n / 60), s = Math.floor(n % 60); return m + ":" + String(s).padStart(2, "0"); };
  $("#s-time").textContent = f(v.currentTime) + " / " + f(v.duration);
}, true);

/* Funoos — frontend (talks to the Python backend via pywebview.api) */
"use strict";
let RUN = null, SPEC = null, PSTATE = {}, CUR_EXH = null, CUR_CMAP = null, FPS = 26, CUR = "intro", GAL = [];
// JOB: the simulation currently in flight (null when idle). REQ: per-request-type
// counters — a response is applied only if its token is still the latest of its
// kind, so an older render/detail/diagnostics reply can never overwrite a newer one.
let JOB = null, ADV = false;                                 // ADV: advanced mode (extra controls, soft limits allowed)
let CMP = null, JOB_SCENE = null, JOB_NAME = null;                                              // comparison display state {a, b, view, times, unit, vmin, vmax, note}
const REQ = { run: 0, view: 0, detail: 0, diag: 0, est: 0, der: 0, probe: 0, cmp: 0 };
const nextReq = k => ++REQ[k];
const isCurrent = (k, t) => REQ[k] === t;

const api = () => window.pywebview.api;
const $ = s => document.querySelector(s);
const el = (t, c, h) => { const e = document.createElement(t); if (c) e.className = c; if (h != null) e.innerHTML = h; return e; };
const elt = (t, c, text) => { const e = document.createElement(t); if (c) e.className = c; if (text != null) e.textContent = text; return e; };
// Backend calls return envelopes: {ok:true, ...} or {ok:false, error}. `call` turns the
// latter (and any bridge rejection) into a thrown Error, so a failure is never used as data.
async function call(name, ...args) {
  let r;
  try { r = await api()[name](...args); }
  catch (e) { throw new Error(errText(e)); }
  if (r && typeof r === "object" && r.ok === false) throw new Error(r.error || "backend error");
  return r;
}
const errText = e => (e && e.message) ? e.message : (typeof e === "string" ? e : (e && e.error) || String(e));
const newId = () => "j" + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
const REDUCED = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
// A still image shown in the stage while the clip is still encoding (first useful output).
window.onPreview = (jobId, png, label) => {
  if (!(JOB && JOB.id === jobId)) return;
  showStill(png, label, true);
};
function showStill(png, label, keepSkel) {
  const im = $("#s-still"); if (!im) return;
  im.src = png; im.style.display = "block"; im.alt = label || "preview";
  const v = $("#s-video"); if (v) v.style.opacity = 0.0;
  const sm = $("#s-skelmsg"); if (sm && label) sm.textContent = label;
  if (!keepSkel) $("#s-skel").classList.remove("on");
}
function hideStill() {
  const im = $("#s-still"); if (im) { im.style.display = "none"; im.removeAttribute("src"); }
  const v = $("#s-video"); if (v) v.style.opacity = 1;
}
window.onProgress = (m, jobId) => {
  if (jobId && !(JOB && JOB.id === jobId)) return;            // progress from a superseded/cancelled job
  if (JOB && JOB.cancelling) return;                           // keep "cancelling…" on screen
  const s = $("#s-status"); if (s) s.textContent = "⏳ " + m;
  const k = $("#s-skelmsg"); if (k) k.textContent = m;
  const pm = /(\d+)\s*%/.exec(m), f = $("#s-pfill");           // drive the progress bar from "… N%"
  if (f && pm) { f.style.width = pm[1] + "%"; f.parentElement.style.opacity = 1; }
};

let GAL_SCROLL = 0;
function show(v) {
  if (CUR === "gallery") { const r = $("#gallery-scroll"); if (r) GAL_SCROLL = r.scrollTop; }   // remember position
  document.querySelectorAll(".view").forEach(x => { x.classList.remove("active"); x.inert = true; x.setAttribute("aria-hidden", "true"); });
  $("#" + v).classList.add("active"); $("#" + v).inert = false; $("#" + v).removeAttribute("aria-hidden");
  document.querySelectorAll(".railbtn").forEach(b => b.classList.toggle("on", b.dataset.view === v));
  CUR = v;
  $("#heroCanvas").style.opacity = v === "intro" ? 0.5 : 0.1;
  if (v !== "studio") { const sv = $("#s-video"); if (sv) sv.pause(); }
  _reconcilePlayback();                                                   // hidden clips stay paused
  const dvids = document.querySelectorAll("#d-video, #d-text video");
  if (v !== "detail") dvids.forEach(x => x.pause());
  else if (!REDUCED && _lsGet("funoos.autoplay", true)) dvids.forEach(x => x.play().catch(() => {}));
  if (v === "intro") { revealAll($("#intro")); runCounters(); }
  if (v === "about") fillAbout();
  if (v === "gallery") { const r = $("#gallery-scroll"); if (r) r.scrollTop = GAL_SCROLL; }
  heroActive(v === "intro" && !JOB && !REDUCED);
}
function revealAll(root) {
  root.querySelectorAll(".reveal").forEach((e, i) => {
    if (REDUCED) { e.classList.add("in"); return; }               // no staged reveal for reduced motion
    e.classList.remove("in"); setTimeout(() => e.classList.add("in"), 80 + i * 90); });
}

/* cursor spotlight — glows through the glass */
window.addEventListener("pointermove", e => {
  const r = document.documentElement.style;
  r.setProperty("--mx", e.clientX + "px"); r.setProperty("--my", e.clientY + "px");
});


/* animated counters */
let countersDone = false;
function runCounters() {
  if (countersDone) return; countersDone = true;
  document.querySelectorAll(".stat .n").forEach(n => {
    const target = +n.dataset.count, t0 = performance.now(), dur = 1100;
    if (REDUCED) { n.textContent = target; return; }
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
const _visible = new Set(), MAX_PLAYING = 6;
function _reconcilePlayback() {
  let playing = 0;
  for (const v of _visible) { if (CUR === "gallery" && playing < MAX_PLAYING && _lsGet("funoos.autoplay", true) && !REDUCED) { v.play().catch(() => {}); playing++; } else v.pause(); }
}
const _vio = new IntersectionObserver(es => { es.forEach(e => { const v = e.target; if (e.isIntersecting) _visible.add(v); else { _visible.delete(v); v.pause(); } }); _reconcilePlayback(); },
  { root: null, threshold: 0.15 });
function _releaseGalleryVideos() {
  document.querySelectorAll("#gallery-grid video").forEach(v => { _vio.unobserve(v); v.pause(); v.removeAttribute("src"); v.load(); });
  _visible.clear();
}

let GAL_METHODS = [], FILTER = { method: "", q: "", fav: false, quick: false }, S2E = {}, EXPS = [];
async function buildGallery() {
  const r = await call("catalog"); GAL = r.groups; GAL_METHODS = r.methods || []; S2E = r.scene_to_experiment || {};
  EXPS = GAL.flatMap(g => g.experiments);
  migrateStoredKeys();
  fillCounts(r.counts || {});
  const ms = $("#g-method"); if (ms) { ms.innerHTML = ""; const o = elt("option", null, "all methods"); o.value = ""; ms.append(o);
    for (const m of GAL_METHODS) { const x = elt("option", null, SHORT[m] || m); x.value = m; ms.append(x); } }
  renderGallery();
}
// Favourites and recents were stored as scene keys; they now refer to experiments but keep
// the original preset so reopening lands on what the user had selected.
function migrateStoredKeys() {
  if (!_lsGet("funoos.favs2", null)) _lsSet("funoos.favs2", FunoosLogic.migrateFavs(_lsGet("funoos.favs", []), S2E));
  const rec = _lsGet("funoos.recents", []);
  if (rec.length && typeof rec[0] === "string") _lsSet("funoos.recents", FunoosLogic.migrateRecents(rec, S2E));
}
function fillCounts(c) {
  for (const [k, id] of [["methods", "#n-methods"], ["experiments", "#n-scenes"], ["solvers", "#n-solvers"], ["presets", "#n-presets"]]) {
    const e = $(id); if (e && c[k] != null) { e.dataset.count = c[k]; e.textContent = countersDone ? c[k] : 0; }
  }
  const sub = $("#gal-sub"); if (sub && c.experiments) sub.textContent = `${c.experiments} experiments with ${c.presets} presets across ${c.methods} numerical methods.`;
}
function favs() { return _lsGet("funoos.favs2", {}); }            // {experimentId: presetKey}
function toggleFav(expId, key, ev) { if (ev) { ev.stopPropagation(); ev.preventDefault(); } const f = favs(); if (f[expId]) delete f[expId]; else f[expId] = key; _lsSet("funoos.favs2", f); renderGallery(); }
function recents() { return _lsGet("funoos.recents", []); }        // [{exp, key}]
function noteRecent(key) { const exp = S2E[key]; if (!exp) return; const r = recents().filter(x => x.exp !== exp); r.unshift({ exp, key }); _lsSet("funoos.recents", r.slice(0, 8)); }
function setFilter(k, v) { FILTER[k] = v; renderGallery(); }
function expMatches(e, q) {
  if (!q) return true;
  const hay = [e.name, e.question, e.phenomenon, ...e.methods, ...e.presets.flatMap(p => [p.label, p.name, p.question, p.status_label])].join(" ").toLowerCase();
  return hay.includes(q);
}
function renderGallery() {
  const root = $("#gallery-grid"); _releaseGalleryVideos(); root.innerHTML = "";
  const f = favs(), q = FILTER.q.trim().toLowerCase(), rec = recents();
  const match = e => (!FILTER.method || e.methods.includes(FILTER.method)) && (!FILTER.fav || f[e.id])
    && (!FILTER.quick || (e.estimate_s != null && e.estimate_s <= 60)) && expMatches(e, q);
  let shown = 0;
  if (rec.length && !q && !FILTER.method && !FILTER.fav && !FILTER.quick) {
    const rs = rec.map(x => ({ e: EXPS.find(e => e.id === x.exp), key: x.key })).filter(x => x.e);
    if (rs.length) { root.append(groupHead("Recent experiments", "")); for (const x of rs) root.append(expCard(x.e, f, x.key)); }
  }
  for (const g of GAL) {
    const items = g.experiments.filter(match); if (!items.length) continue;
    root.append(groupHead(g.phenomenon, items.length + (items.length === 1 ? " experiment" : " experiments")));
    for (const e of items) { root.append(expCard(e, f, f[e.id] || null)); shown++; }
  }
  if (!shown) root.append(elt("div", "muted", "No experiments match this filter."));
}
function groupHead(title, sub) {
  const h = el("div", "ghead"); h.append(elt("h2", null, title)); if (sub) h.append(elt("span", "muted", sub)); return h;
}
function expCard(e, favset, openKey) {
  const method = SHORT[e.method] || e.method, acc = ACC[e.method] || "#5b86f0";
  const c = el("div", "gcard"); c.tabIndex = 0; c.setAttribute("role", "button"); c.setAttribute("aria-label", e.name + " — " + e.question);
  const media = el("div", "media");
  const auto = _lsGet("funoos.autoplay", true) && !REDUCED;
  if (e.clip) { const v = el("video"); v.src = e.clip; v.loop = v.muted = true; v.playsInline = true; v.preload = "metadata"; if (e.poster) v.poster = e.poster; v.setAttribute("aria-hidden", "true"); media.append(v); if (auto) _vio.observe(v); }
  else if (e.poster) { const im = el("img"); im.src = e.poster; im.alt = ""; media.append(im); }
  else { media.append(elt("div", "noclip", "no preview clip yet")); }
  const pl = el("div", "pill left"); const dot = el("span", "dot"); dot.style.background = acc;
  pl.append(dot, document.createTextNode(e.methods.length > 1 ? e.methods.map(m => SHORT[m] || m).join(" · ") : method));
  media.append(pl, elt("div", "pill right status-" + e.status, e.n_presets > 1 ? e.n_presets + " presets" : e.status_label));
  const isFav = !!favset[e.id];
  const fav = elt("button", "favbtn" + (isFav ? " on" : ""), isFav ? "★" : "☆");
  fav.setAttribute("aria-label", (isFav ? "Remove from" : "Add to") + " favourites: " + e.name);
  fav.onclick = ev => toggleFav(e.id, openKey || e.representative, ev);
  fav.onkeydown = ev => { if (ev.key === "Enter" || ev.key === " ") { ev.stopPropagation(); ev.preventDefault(); toggleFav(e.id, openKey || e.representative, ev); } };
  media.append(fav);
  const body = el("div", "gbody");
  body.append(elt("div", "ttl", e.name));
  const foot = el("div", "foot");
  foot.append(elt("div", "sub", e.question), elt("div", "go", "↗"));
  body.append(foot);
  c.append(media, body);
  const key = openKey || e.representative;
  c.onclick = () => openDetail(key);
  c.onkeydown = ev => { if ((ev.key === "Enter" || ev.key === " ") && ev.target === c) { ev.preventDefault(); openDetail(key); } };
  return c;
}

/* ───────── detail ───────── */
// FLIP morph: navigate first (so the click always works), then glide a clone of the
// card onto the detail video — it lands exactly on it, so there's no jump.
async function morphToDetail(card, key) {
  const r0 = card.getBoundingClientRect(), v0 = card.querySelector("video");
  await openDetail(key);                       // build + show detail (navigation is guaranteed)
  const target = $("#d-video"), r1 = target.getBoundingClientRect();
  if (!v0 || !r1.width || REDUCED) return;     // nothing to animate; detail is already up
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
  const t = nextReq("detail"); let d;
  try { d = await call("scene_detail", key, t); } catch (e) { toast("Could not open scene: " + errText(e), "err"); return; }
  if (!isCurrent("detail", t)) return;                         // a newer scene was opened meanwhile
  try { renderDetail(d, key); } catch (e) { toast("Could not display the scene: " + errText(e), "err"); $("#s-status") && ($("#s-status").textContent = "⚠ " + errText(e)); console.error(e); }
}
function renderDetail(d, key) {
  noteRecent(key);
  const ex = d.experiment;
  $("#d-method").textContent = d.phenomenon + " · " + d.method; $("#d-title").textContent = ex ? ex.name : d.name;
  fillPresetSelector($("#d-preset"), ex, key, k => openDetail(k));   // openDetail is token-guarded
  const pl = $("#d-presetname"); if (pl) pl.textContent = ex && ex.presets.length > 1 ? "Preset: " + (ex.preset_label || d.name) : "";
  const cmpBox = $("#d-compare"); if (cmpBox) { cmpBox.innerHTML = ""; if (ex && ex.compare && ex.compare.length) { cmpBox.append(elt("div", "kicker", "GUIDED COMPARISONS")); for (const c of ex.compare) { const row = el("div", "gcmp"); row.append(elt("div", "read small", c.text)); if (c.b) { const b = elt("button", "linkbtn", "run both & compare"); b.onclick = () => guidedCompare(c.a, c.b); row.append(b); } else { const b = elt("button", "linkbtn", "open in Studio"); b.onclick = async () => { const dd = await call("scene_detail", c.a, nextReq("detail")); openStudio(dd); }; row.append(b); } cmpBox.append(row); } } }
  const dv = $("#d-video"); if (d.clip) { dv.src = d.clip; dv.style.display = "block"; dv.autoplay = !REDUCED && _lsGet("funoos.autoplay", true); if (!dv.autoplay) { dv.pause(); dv.controls = true; } } else { dv.removeAttribute("src"); dv.style.display = "none"; }
  const q = $("#d-question"); if (q) q.textContent = d.question;
  const sb = $("#d-status"); if (sb) { sb.textContent = d.status_label; sb.className = "statusbadge status-" + d.status; }
  const box = $("#d-text"); box.innerHTML = "";
  renderLayers(box, d.layers || [], d);
  try { buildRelated(box, key); } catch (e) { console.error("related experiments unavailable", e); }   // optional rail: the page still opens
  [...box.children].forEach((c, i) => { c.classList.add("reveal"); setTimeout(() => c.classList.add("in"), REDUCED ? 0 : 60 + i * 50); });
  $("#d-open").onclick = () => openStudio(d);
  show("detail");
}
// Layered explanation in reading order; the first layers are open, the mathematical detail is collapsed.
function renderLayers(box, layers, d) {
  for (const L of layers) {
    const sec = el("details", "layer"); sec.id = "layer-" + L.id;
    if (["question", "see", "try", "observe", "numerics"].includes(L.id)) sec.open = true;
    const sum = el("summary"); sum.append(elt("span", "kicker", L.title));
    if (L.id === "numerics" && L.status) sum.append(elt("span", "statusbadge status-" + d.status, L.status));
    sec.append(sum);
    if (L.text) sec.append(elt("div", "read body", L.text));
    if (L.items && L.items.length) { const ul = el("ul", "tries"); for (const it of L.items) ul.append(elt("li", null, it)); sec.append(ul); }
    if (L.id === "observe") {
      if (L.fixed && L.fixed.length) { sec.append(elt("div", "kicker small", "held fixed")); const ul = el("ul", "tries"); for (const f of L.fixed) ul.append(elt("li", null, f)); sec.append(ul); }
      if (L.more && L.more.length) { sec.append(elt("div", "kicker small", "further experiments")); const ul = el("ul", "tries"); for (const it of L.more) ul.append(elt("li", null, it)); sec.append(ul); }
    }
    if (L.id === "model") {
      if (L.eq && d.eq) { const b = el("div", "eqbox"); const im = el("img"); im.src = d.eq; im.alt = "governing equation"; b.append(im); sec.append(b); }
      if (L.text) { sec.querySelector(".body").classList.add("terms"); }
      sec.append(elt("div", "muted small", "The symbols are read out term by term above; units and conventions are stated in the numerical-method layer and docs/theory.md."));
    }
    if (L.id === "setup") {
      const s = el("div", "setup");
      if (L.ic) s.append(sline("Initial", L.ic)); if (L.bc) s.append(sline("Boundary", L.bc));
      const pre = Object.keys(L.preset || {}).length ? Object.entries(L.preset).map(([k, v]) => k + " = " + v).join(", ") : "exhibit defaults";
      s.append(sline("This preset", pre)); sec.append(s);
    }
    if (L.id === "numerics" && L.checks) { sec.append(elt("div", "kicker small", "checks and limitations")); sec.append(elt("div", "read body", L.checks)); }
    box.append(sec);
  }
}
function sline(k, v) { const r = el("div", "sline"); r.append(elt("b", null, k), elt("span", null, v)); return r; }
function fillPresetSelector(sel, ex, key, onpick) {
  if (!sel) return;
  sel.innerHTML = "";
  if (!ex || ex.presets.length < 2) { sel.style.display = "none"; return; }
  sel.style.display = "";
  for (const p of ex.presets) { const o = elt("option", null, p.label); o.value = p.key; if (p.key === key) o.selected = true; sel.append(o); }
  sel.onchange = () => onpick(sel.value);
}
function buildRelated(t, key) {
  const group = GAL.find(g => g.experiments.some(e => e.presets.some(p => p.key === key)));
  if (!group) return;
  const related = group.experiments.filter(e => !e.presets.some(p => p.key === key));   // other experiments of the phenomenon
  if (!related.length) return;
  const sec = el("div", "section"); sec.append(elt("div", "kicker", "MORE ON " + group.phenomenon.toUpperCase()));
  const rail = el("div", "related");
  for (const e of related) {
    const s = { ...e, key: e.representative };                    // open an experiment through its representative preset
    const m = el("div", "rel"); m.tabIndex = 0; m.setAttribute("role", "button"); m.setAttribute("aria-label", s.name);
    if (s.clip) { const v = el("video"); v.src = s.clip; v.loop = v.muted = true; v.autoplay = !REDUCED && _lsGet("funoos.autoplay", true); v.playsInline = true; if (s.poster) v.poster = s.poster; v.preload = "metadata"; m.append(v); }
    m.append(elt("div", "rnm", s.name)); m.onclick = () => openDetail(s.key); m.onkeydown = e => { if (e.key === "Enter") openDetail(s.key); }; rail.append(m);
  }
  sec.append(rail); t.append(sec);
}
function section(head, body) { const s = el("div", "section"); s.append(el("div", "kicker", head.toUpperCase()), el("div", "read body", body)); return s; }

/* ───────── studio ───────── */
let CUR_PRESET = null, CUR_SCENE = null, CUR_DETAIL = null, PENDING_PRES = null;   // presentation to apply after the next run
const DRAFTS = {};                                            // per-experiment draft settings kept while browsing
async function studioPick(sel) {
  const key = sel.value; if (!key) return;
  const t = nextReq("detail"); let d;
  try { d = await call("scene_detail", key, t); } catch (e) { toast(errText(e), "err"); return; }
  if (!isCurrent("detail", t) || d.key !== key) return;       // a newer pick won
  openStudio(d);
}
function fillStudioPicker() {
  const sel = $("#s-scene"); if (!sel || !GAL.length) return; sel.innerHTML = "";
  const o = elt("option", null, "choose an experiment…"); o.value = ""; sel.append(o);
  for (const g of GAL) { const og = el("optgroup"); og.label = g.phenomenon; for (const e of g.experiments) { const x = elt("option", null, e.name); x.value = e.id; og.append(x); } sel.append(og); }
  if (CUR_SCENE && S2E[CUR_SCENE]) sel.value = S2E[CUR_SCENE];
  const ex = CUR_DETAIL && CUR_DETAIL.experiment;
  fillPresetSelector($("#s-preset"), ex, CUR_SCENE, async k => { const tk = nextReq("detail"); const dd = await call("scene_detail", k, tk); if (isCurrent("detail", tk) && dd.key === k) openStudio(dd); });
  markCustom();
}
async function studioPickExperiment(sel) {
  const id = sel.value; if (!id) return;
  const e = EXPS.find(x => x.id === id); if (!e) return;
  const key = (favs()[id]) || e.representative;
  const t = nextReq("detail"); let d;
  try { d = await call("scene_detail", key, t); } catch (err) { toast(errText(err), "err"); return; }
  if (!isCurrent("detail", t) || d.key !== key) return;
  openStudio(d);
}
// "Custom setup" once the controls differ from the preset that was opened
function markCustom() {
  const nm = $("#s-name"); if (!nm || !CUR_DETAIL) return;
  const base = sceneDefaults(); const custom = SPEC.some(q => visible(q) && String(fmtNum(base[q.name])) !== String(fmtNum(PSTATE[q.name])));
  const ex = CUR_DETAIL.experiment; const presetName = ex && ex.presets.length > 1 ? (ex.preset_label || CUR_DETAIL.name) : CUR_DETAIL.name;
  nm.textContent = ((ex ? ex.name : CUR_DETAIL.name) + " · " + (custom ? "Custom setup" : presetName)).toUpperCase();
  const ps = $("#s-preset"); if (ps && ps.style.display !== "none") { ps.dataset.custom = custom ? "1" : "0"; }
}
function toggleHelp() {
  const h = $("#s-help"); if (!h) return;
  if (h.style.display === "block") { h.style.display = "none"; return; }
  h.innerHTML = "";
  if (!CUR_DETAIL) { h.append(elt("div", "muted", "Pick a scene first.")); }
  else { h.append(elt("div", "kicker", CUR_DETAIL.name)); h.append(elt("div", "read small", CUR_DETAIL.question)); renderLayers(h, CUR_DETAIL.layers || [], CUR_DETAIL); }
  h.style.display = "block";
}
function openStudio(d) {
  // a running job keeps running (its result lands in the history); only the view state is reset
  if (CUR_EXH && CUR_SCENE) DRAFTS[CUR_SCENE] = { ...PSTATE };  // keep this scene's draft while browsing
  nextReq("view"); nextReq("diag");                            // render/diagnostic replies for the old scene are stale now
  if (!JOB) $("#s-skel").classList.remove("on");
  CUR_EXH = d.exhibit; CUR_CMAP = d.cmap || null; SPEC = d.params; PSTATE = {}; CUR_PRESET = d.preset || null; CUR_SCENE = d.key || null; CUR_DETAIL = d;
  if (d.key) noteRecent(d.key); fillStudioPicker(); const hp = $("#s-help"); if (hp) hp.style.display = "none";
  UNDO = []; REDO = []; updateUndoButtons();
  for (const q of SPEC) PSTATE[q.name] = q.default;
  if (d.preset) for (const k in d.preset) PSTATE[k] = d.preset[k];
  if (DRAFTS[d.key]) PSTATE = { ...PSTATE, ...DRAFTS[d.key] };   // restore an unsaved draft of this scene
  $("#s-name").textContent = (d.name || "parameters").toUpperCase();
  DRAFTS[d.exhibit] = DRAFTS[d.exhibit] || null;
  renderParams(); refreshEstimate(); refreshPresetMenu(); refreshHistory(); zoomReset();
  RUN = null; $("#s-video").style.display = "none"; $("#s-hint").style.display = "block"; hideStill();
  $("#s-views").innerHTML = ""; $("#s-cmap").innerHTML = ""; $("#s-plotpanel").style.display = "none";
  $("#s-kpis").innerHTML = '<div class="muted" style="font-size:12px">Run a simulation to see live readouts.</div>';
  if (JOB) $("#s-status").textContent = "⏳ " + (JOB_NAME || "another experiment") + " is still simulating — its result will appear in the run history";
  else $("#s-status").textContent = "Ready.";
  refreshJobUI(); show("studio");
}
function visible(q) { return !q.when || q.when[1].includes(PSTATE[q.when[0]]); }
let _estT = null;
function refreshEstimate() {
  clearTimeout(_estT);
  _estT = setTimeout(async () => {
    if (!CUR_EXH) return;
    const t = nextReq("est");
    try {
      const e = await call("estimate", CUR_EXH, { ...PSTATE });
      if (!isCurrent("est", t)) return;
      const el_ = $("#s-estimate"); if (!el_) return;
      const secs = e.seconds < 90 ? Math.round(e.seconds) + " s" : Math.round(e.seconds / 60) + " min";
      el_.textContent = `≈ ${e.grid[0]}×${e.grid[1]} grid · ${e.frames} frames · ${e.mb} MB · ~${secs} (estimate, ${e.threads} threads)`;
    } catch (err) { /* estimate is advisory */ }
    const td = nextReq("der");
    try {
      const d = await call("derived", CUR_EXH, { ...PSTATE });
      if (!isCurrent("der", td)) return;
      renderDerived(d.items || []);
    } catch (err) { /* derived quantities are advisory */ }
  }, 250);
}
function renderDerived(items) {
  const box = $("#s-derived"); if (!box) return; box.innerHTML = "";
  if (!items.length) return;
  box.append(elt("div", "kicker", "derived quantities"));
  for (const it of items) {
    const row = el("div", "drow"); row.append(elt("span", "dl", it.label), elt("span", "dv", it.value + (it.units ? " " + it.units : "")));
    if (it.note) row.title = it.note;
    box.append(row);
  }
}
function renderParams() {
  const root = $("#s-params"); root.innerHTML = ""; const groups = {};
  for (const q of SPEC) { if (!visible(q) || (q.advanced && !ADV)) continue; (groups[q.group] || (groups[q.group] = [])).push(q); }
  for (const g of ["Geometry", "Physics", "Render"]) {
    if (!groups[g]) continue;
    const blk = el("div", "pgroup");
    const head = elt("div", "kicker", g);
    const rst = elt("button", "linkbtn", "reset"); rst.type = "button"; rst.title = "Reset this group to the scene defaults";
    rst.setAttribute("aria-label", "Reset " + g + " parameters"); rst.onclick = () => resetGroup(g);
    head.append(rst); blk.append(head);
    for (const q of groups[g]) blk.append(field(q)); root.append(blk);
  }
  const advb = $("#s-adv"); if (advb) { advb.textContent = ADV ? "Advanced mode: on" : "Advanced mode: off"; advb.setAttribute("aria-pressed", ADV ? "true" : "false"); }
  const hasAdv = SPEC.some(q => q.advanced); if (advb) advb.style.display = "inline-block";
  validateAll();
}
function toggleAdvanced() { ADV = !ADV; renderParams(); refreshEstimate(); }
function markMatch() {
  const m = $("#s-match"); if (!m) return;
  if (!RUN || !RUN.params) { m.textContent = ""; return; }
  const same = SPEC.every(q => !visible(q) || String(fmtNum(RUN.params[q.name])) === String(fmtNum(PSTATE[q.name])));
  m.textContent = same ? "✓ result matches the current controls" : "⚠ result is from an earlier setup — controls have changed";
  m.className = "match " + (same ? "ok" : "stale");
}
function fmtNum(v) { return (typeof v === "number" && !Number.isInteger(v)) ? +v.toPrecision(6) : v; }
// Complete numeric parsing lives in web/logic.js (unit-tested with node): "0,01" → 0.01, "1e" / "2abc" / "" → NaN.
const parseNum = FunoosLogic.parseNum;
function field(q) {
  const f = el("div", "field"); f.dataset.name = q.name;
  const id = "p-" + q.name;
  const lab = elt("label", null, q.label || q.name); lab.htmlFor = id;
  if (q.units) lab.append(" ", elt("span", "units", "(" + q.units + ")"));
  if (q.type === "float" || q.type === "int") lab.append(elt("span", "rng", "  " + q.min + " – " + q.max));
  f.append(lab); let inp;
  if (q.type === "choice") {
    inp = el("select"); inp.id = id;
    for (const c of q.choices) { const o = elt("option", null, c); o.value = c; if (c === PSTATE[q.name]) o.selected = true; inp.append(o); }
    inp.onchange = () => { pushUndo(); PSTATE[q.name] = inp.value; renderParams(); refreshEstimate(); };
  } else {
    inp = el("input"); inp.id = id; inp.type = "text"; inp.value = fmtNum(PSTATE[q.name]);
    inp.inputMode = q.type === "int" ? "numeric" : (q.type === "float" ? "decimal" : "text");
    if (q.type === "int") inp.step = "1";
    inp.onfocus = () => { inp.dataset.before = JSON.stringify(PSTATE[q.name]); };
    inp.oninput = () => { PSTATE[q.name] = q.type === "float" || q.type === "int" ? parseNum(inp.value) : inp.value; validateOne(q, f); validateAll(); refreshEstimate(); };
    inp.onchange = () => { if (inp.dataset.before !== JSON.stringify(PSTATE[q.name])) pushUndo(JSON.parse(inp.dataset.before), q.name); };
  }
  f.append(inp);
  const help = elt("div", "help", (q.help || "") + (q.fixed ? "  Held fixed: " + q.fixed + "." : ""));
  help.id = id + "-help"; inp.setAttribute("aria-describedby", help.id); f.append(help);
  f.append(elt("div", "verr", "")); validateOne(q, f);
  return f;
}
// client-side validation (the backend repeats it before any solver starts)
function checkParam(q, v) { return FunoosLogic.checkParam(q, v, ADV); }
function validateOne(q, f) {
  const msg = checkParam(q, PSTATE[q.name]); const e = f.querySelector(".verr");
  f.classList.toggle("invalid", !!msg && !/^warn:/.test(msg)); f.classList.toggle("warn", !!msg && /^warn:/.test(msg));
  e.textContent = msg ? msg.replace(/^warn:/, "") : "";
  const inp = f.querySelector("input,select"); if (inp) inp.setAttribute("aria-invalid", msg && !/^warn:/.test(msg) ? "true" : "false");
}
function validateAll() {
  markMatch(); markCustom();
  let bad = 0;
  document.querySelectorAll("#s-params .field").forEach(f => { const q = SPEC.find(x => x.name === f.dataset.name); if (q) { validateOne(q, f); if (f.classList.contains("invalid")) bad++; } });
  const btn = $("#s-run"); if (btn && !JOB) { btn.disabled = bad > 0; btn.title = bad ? "Fix the highlighted values first" : ""; }
  return bad === 0;
}
/* undo / redo / reset */
let UNDO = [], REDO = [];
function pushUndo(prevVal, name) {
  const snap = { ...PSTATE }; if (name !== undefined) snap[name] = prevVal;
  UNDO.push(snap); if (UNDO.length > 50) UNDO.shift(); REDO = []; updateUndoButtons();
}
function undoParams() { if (!UNDO.length) return; REDO.push({ ...PSTATE }); PSTATE = UNDO.pop(); renderParams(); refreshEstimate(); updateUndoButtons(); }
function redoParams() { if (!REDO.length) return; UNDO.push({ ...PSTATE }); PSTATE = REDO.pop(); renderParams(); refreshEstimate(); updateUndoButtons(); }
function updateUndoButtons() { const u = $("#s-undo"), r = $("#s-redo"); if (u) u.disabled = !UNDO.length; if (r) r.disabled = !REDO.length; }
function sceneDefaults() { const d = {}; for (const q of SPEC) d[q.name] = q.default; if (CUR_PRESET) for (const k in CUR_PRESET) d[k] = CUR_PRESET[k]; return d; }
function resetGroup(g) { pushUndo(); const d = sceneDefaults(); for (const q of SPEC) if (q.group === g) PSTATE[q.name] = d[q.name]; renderParams(); refreshEstimate(); }
function resetAll() { pushUndo(); PSTATE = sceneDefaults(); renderParams(); refreshEstimate(); }
async function runSim() {
  if (JOB || !CUR_EXH) return;                                 // one job at a time (button is disabled anyway)
  if (!validateAll()) { toast("Fix the highlighted values first", "err"); return; }
  const t = nextReq("run"); JOB_SCENE = CUR_SCENE; JOB_NAME = CUR_DETAIL ? CUR_DETAIL.name : CUR_EXH;
  JOB = { id: newId(), exhibit: CUR_EXH, params: Object.freeze({ ...PSTATE }), cancelling: false, token: t, scene: CUR_SCENE };
  setRunning(true);
  $("#s-skel").classList.add("on"); $("#s-hint").style.display = "none"; $("#s-plotpanel").style.display = "none";
  const pf = $("#s-pfill"); if (pf) { pf.style.width = "0%"; } $("#s-skelmsg").textContent = "preparing…";
  $("#s-status").textContent = "⏳ preparing…"; heroActive(false);
  const view = (RUN && RUN.view) || null, cmap = $("#s-cmap").value || CUR_CMAP;   // keep the user's colour choice
  let r = null, err = null;
  try { r = await api().run(JOB.exhibit, JOB.params, view, cmap, 26, JOB.id, ADV); }
  catch (e) { err = errText(e); }
  if (!isCurrent("run", t)) return;                            // newer run: this reply is stale
  JOB = null; setRunning(false); $("#s-skel").classList.remove("on"); hideStill(); heroActive(CUR === "intro" && !REDUCED);
  if (r && r.ok && JOB_SCENE && JOB_SCENE !== CUR_SCENE) {     // the user browsed elsewhere: keep it in the history only
    toast("Run finished for " + JOB_SCENE + " — open it from the run history", "ok"); refreshHistory(); return;
  }
  if (r && r.ok) {                                             // the previous RUN is replaced only now
    RUN = r; FPS = 26; leaveCompare(); markMatch();
    buildViewbar(r); setVideo(r.video, false); renderKPIs(r.stats || []);
    if (PENDING_PRES) {                                        // a loaded setup's presentation, applied once the view bar exists
      const pp = PENDING_PRES; PENDING_PRES = null;
      if (pp.cmap) { const cm = $("#s-cmap"); if ([...cm.options].some(o => o.value === pp.cmap)) cm.value = pp.cmap; }
      if ((pp.view && pp.view !== r.view) || (pp.cmap && pp.cmap !== r.defcmap) || pp.vmin != null || pp.vmax != null) switchView(pp.view || r.view, true);
    }
    if (r.validation && r.validation.warnings && r.validation.warnings.length) toast(r.validation.warnings[0], "");
    if (r.validation && r.validation.applied && r.validation.applied.length) toast("Applied: " + r.validation.applied.join("; "), "");
    $("#s-status").textContent = "✓ " + r.info; refreshHistory(); zoomReset();
    $("#s-plots").classList.add("ready");                       // draw attention to the diagnostics
    toast("Done — open 📊 Diagnostic plots for the analysis", "ok");
    if (r.evicted && r.evicted.length) toast("Older result" + (r.evicted.length > 1 ? "s" : "") + " released to stay within the memory budget", "");
  } else if (r && r.state === "cancelled") {
    $("#s-status").textContent = RUN ? "■ Cancelled — previous result kept." : "■ Cancelled.";
    if (RUN) $("#s-hint").style.display = "none"; else $("#s-hint").style.display = "block";
  } else {
    const msg = err || (r && r.error) || "unknown error";
    $("#s-status").textContent = "⚠ " + msg; toast("Run failed: " + msg, "err");
    if (!RUN) $("#s-hint").style.display = "block";
  }
}
async function cancelSim() {
  if (!JOB || JOB.cancelling) return;
  JOB.cancelling = true;
  $("#s-status").textContent = "⏳ cancelling…"; $("#s-skelmsg").textContent = "cancelling…";
  const cb = $("#s-cancel"); if (cb) cb.disabled = true;
  try { await api().cancel(JOB.id); } catch (e) { /* the run reply will carry the final state */ }
}
function setRunning(on) { refreshJobUI(); }
// Button states come from the active job, not from the scene on screen: while a job runs
// (possibly for another experiment) Run stays disabled, Cancel stays visible and says what runs.
function refreshJobUI() {
  const btn = $("#s-run"), cb = $("#s-cancel"); if (!btn) return;
  const on = !!JOB;
  btn.disabled = on; btn.textContent = on ? (JOB_SCENE && JOB_SCENE !== CUR_SCENE ? "●  Simulating " + (JOB_NAME || JOB_SCENE) + "…" : "●  Simulating…") : "▶  Run simulation";
  btn.title = on ? "A simulation is running" + (JOB_SCENE && JOB_SCENE !== CUR_SCENE ? " for " + (JOB_NAME || JOB_SCENE) : "") + " — cancel it or wait; the result lands in the run history" : "";
  const sw = $("#s-sweep-run"); if (sw) sw.disabled = on;
  if (cb) { cb.style.display = on ? "block" : "none"; cb.disabled = !!(JOB && JOB.cancelling); cb.textContent = on && JOB_SCENE && JOB_SCENE !== CUR_SCENE ? "■  Cancel " + (JOB_NAME || JOB_SCENE) : "■  Cancel"; }
  if (!on) validateAll();
}
function renderKPIs(stats) {
  const k = $("#s-kpis"); k.innerHTML = "";
  if (!stats.length) { k.append(elt("div", "muted small", "No readouts.")); return; }
  for (const s of stats) {
    if (s.frac != null) {
      const t = el("div", "kpi gauge" + (s.accent ? " accent" : ""));
      const dial = el("div", "dial", kpiGauge(s.frac, s.accent));
      const dv = elt("div", "dval", s.v); if (s.u) dv.append(elt("small", null, s.u)); dial.append(dv);
      t.append(dial, elt("div", "l", s.l)); k.append(t);
    } else {
      const t = el("div", "kpi" + (s.accent ? " accent" : ""));
      const v = elt("div", "v", s.v); if (s.u) { v.append(" ", elt("small", null, s.u)); }
      t.append(elt("div", "l", s.l), v);
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
  for (const v of r.views) { const b = elt("button", v === r.view ? "on" : "", v); b.onclick = () => switchView(v); seg.append(b); }
  const cm = $("#s-cmap"), keep = cm.value; cm.innerHTML = "";
  const sel = r.cmaps.includes(keep) ? keep : r.defcmap;        // colour choice survives a new run
  for (const c of r.cmaps) { const o = elt("option", null, c); o.value = c; if (c === sel) o.selected = true; cm.append(o); }
}
async function switchView(v, force) {
  if (!RUN || (v === RUN.view && !CMP && !force)) return; leaveCompare();
  const t = nextReq("view"), rid = RUN.run_id; setBusy("rendering " + v + "…");
  try {
    const r = await call("render_view", rid, v, $("#s-cmap").value, 26, t, $("#x-vmin").value, $("#x-vmax").value);   // manual limits stay across views
    if (!isCurrent("view", t) || !RUN || RUN.run_id !== rid) return;   // stale: a newer view/run won
    hideStill(); RUN.view = r.view; RUN.field_rect = r.field_rect || null; setVideo(r.video, true);
    document.querySelectorAll("#s-views button").forEach(b => b.classList.toggle("on", b.textContent === r.view));
    $("#s-status").textContent = "✓ " + RUN.info;
  } catch (e) { if (isCurrent("view", t) && !/superseded/.test(errText(e))) { toast(errText(e), "err"); $("#s-status").textContent = "⚠ " + errText(e); } }
  if (isCurrent("view", t) && !JOB) $("#s-skel").classList.remove("on");
}
async function recolor() {
  if (!RUN) return;
  if (CMP) { return compareWith(CMP.a, true); }                // recolour the comparison itself (both runs, shared scale)
  const t = nextReq("view"), rid = RUN.run_id, cmap = $("#s-cmap").value;
  const idx = curFrame(), frac = idx == null ? 1.0 : { index: idx, frac: 1.0 };
  // 1) instant: re-map the frame on screen with the new palette (one PNG, no encoding)
  try {
    if (!_lsGet("funoos.preview", true)) throw new Error("previews off");
    const p = await call("preview_frame", rid, RUN.view, cmap, frac, t);
    if (!isCurrent("view", t) || !RUN || RUN.run_id !== rid) return;
    showStill(p.img, "palette preview · encoding clip…", false);
  } catch (e) { /* fall through to the clip */ }
  // 2) then the full clip (cached per palette after the first time)
  try {
    const r = await call("render_view", rid, RUN.view, cmap, 26, t, $("#x-vmin").value, $("#x-vmax").value);
    if (!isCurrent("view", t) || !RUN || RUN.run_id !== rid) return;
    hideStill(); setVideo(r.video, true); $("#s-status").textContent = "✓ " + RUN.info + (r.cached ? "  (cached)" : "");
  } catch (e) {
    if (!isCurrent("view", t)) return;
    if (!/superseded/.test(errText(e))) { toast(errText(e), "err"); $("#s-status").textContent = "⚠ " + errText(e); }
  }
  if (isCurrent("view", t) && !JOB) $("#s-skel").classList.remove("on");
}
function setBusy(msg) { $("#s-skel").classList.add("on"); $("#s-skelmsg").textContent = msg; $("#s-status").textContent = "⏳ " + msg; }
function setVideo(src, keepPosition) {
  const v = $("#s-video");
  const rate = v.playbackRate || 1, wasPaused = v.style.display === "block" ? v.paused : false;
  const at = keepPosition ? (v.currentTime || 0) : 0;
  v.src = src; v.style.display = "block"; $("#s-hint").style.display = "none";
  v.onloadeddata = () => {
    v.playbackRate = rate; $("#s-rate").textContent = rate + "×";
    if (at > 0 && v.duration) v.currentTime = Math.min(at, Math.max(0, v.duration - 0.05));
    if (wasPaused && keepPosition) { v.pause(); $("#s-play").textContent = "▶"; }
    else { v.play().catch(() => {}); $("#s-play").textContent = "⏸"; }
  };
}
async function saveClip(fmt) {
  if (!RUN) { toast("Run a simulation first", "err"); return; }
  const v = $("#s-video");
  const opts = { fps: +($("#x-fps").value || 26), scale: +($("#x-scale").value || 1), t0: +($("#x-t0").value || 0), t1: +($("#x-t1").value || 1),
                 vmin: $("#x-vmin").value, vmax: $("#x-vmax").value };
  $("#s-status").textContent = "⏳ rendering " + fmt.toUpperCase() + " to save…";
  try {
    const r = await call("save_clip", RUN.run_id, RUN.view, $("#s-cmap").value, fmt, opts);
    if (r.path) { $("#s-status").textContent = `✓ saved: ${r.path} (${r.frames} frames at ${r.fps} fps)`; toast("Saved " + fmt.toUpperCase(), "ok"); }
    else { $("#s-status").textContent = "Save cancelled."; }
  } catch (e) { $("#s-status").textContent = "⚠ " + errText(e); toast("Save failed: " + errText(e), "err"); }
}
async function exportAction(sel) {
  const what = sel.value; sel.value = "";
  if (!RUN) { toast("Run a simulation first", "err"); return; }
  if (CMP && what !== "project" && what !== "options") { toast("Exports refer to a single run: switch a view to leave the comparison first", "err"); return; }
  const idx = curFrame(), frac = idx == null ? 1.0 : { index: idx, frac: 1.0 }, cmap = $("#s-cmap").value;
  try {
    let r;
    if (what === "mp4" || what === "gif") { await saveClip(what); return; }
    if (what === "png") r = await call("save_png", RUN.run_id, RUN.view, cmap, frac, $("#x-vmin").value, $("#x-vmax").value);
    else if (what === "svg") r = await call("save_plots_svg", RUN.run_id);
    else if (what === "npz") r = await call("save_arrays", RUN.run_id);
    else if (what === "csv") r = await call("export_csv", RUN.run_id, "series", {});
    else if (what === "report") r = await call("save_report", RUN.run_id, CUR_SCENE, RUN.view, cmap);
    else if (what === "project") { await saveProject(); return; }
    else if (what === "options") { const b = $("#x-opts"); b.style.display = b.style.display === "block" ? "none" : "block"; return; }
    if (!r) return;
    const p = r.path || (r.paths && r.paths.join(", "));
    if (p) { toast("Saved " + p, "ok"); $("#s-status").textContent = "✓ saved: " + p; } else $("#s-status").textContent = "Save cancelled.";
  } catch (e) { toast("Export failed: " + errText(e), "err"); }
}
async function applyLimits() {
  if (!RUN) return;
  const t = nextReq("view"), rid = RUN.run_id;
  try {
    const r = await call("render_view", rid, RUN.view, $("#s-cmap").value, 26, t, $("#x-vmin").value, $("#x-vmax").value);
    if (!isCurrent("view", t) || !RUN || RUN.run_id !== rid) return;
    hideStill(); setVideo(r.video, true); $("#s-status").textContent = "✓ colour limits applied";
  } catch (e) { if (isCurrent("view", t) && !/superseded/.test(errText(e))) toast(errText(e), "err"); }
}
async function togglePlots() {
  if (!RUN) { toast("Run a simulation first", "err"); return; }
  $("#s-plots").classList.remove("ready");           // attention cue consumed
  const p = $("#s-plotpanel");
  if (p.style.display === "block") { p.style.display = "none"; return; }
  const t = nextReq("diag"), rid = RUN.run_id; setBusy("computing diagnostics…");
  try {
    const r = await call("diagnostics", rid, t);
    if (!isCurrent("diag", t) || !RUN || RUN.run_id !== rid) return;   // stale: newer request or run
    p.innerHTML = ""; p.dataset.run = rid;
    if (!r.plots.length) p.append(elt("div", "muted", "No diagnostics for this case."));
    for (const pl of r.plots) {
      const card = el("div", "plot");
      card.append(elt("div", "kicker", pl.title));
      const i = el("img"); i.src = pl.img; card.append(i);
      if (pl.explain) card.append(el("div", "explain", pl.explain));
      p.append(card);
    }
    p.style.display = "block"; $("#s-status").textContent = "✓ diagnostics ready.";
  } catch (e) { if (isCurrent("diag", t)) { toast(errText(e), "err"); $("#s-status").textContent = "⚠ " + errText(e); } }
  if (isCurrent("diag", t) && !JOB) $("#s-skel").classList.remove("on");
}

/* ───────── experiments: presets · projects · history · sweeps · compare · probes · zoom ───────── */
function _lsGet(k, d) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : d; } catch (e) { return d; } }
function _lsSet(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* storage may be unavailable */ } }
function presetKey() { return "funoos.presets." + CUR_EXH; }
function refreshPresetMenu() {
  const sel = $("#s-presets"); if (!sel) return; sel.innerHTML = "";
  const o0 = elt("option", null, "★ presets…"); o0.value = ""; sel.append(o0);
  const saved = _lsGet(presetKey(), {});
  for (const n of Object.keys(saved).sort()) { const o = elt("option", null, n); o.value = "load:" + n; sel.append(o); }
  const s1 = elt("option", null, "＋ save current as…"); s1.value = "save"; sel.append(s1);
  if (Object.keys(saved).length) { const s2 = elt("option", null, "－ delete a preset…"); s2.value = "del"; sel.append(s2); }
}
function presetAction(sel) {
  const v = sel.value; sel.value = "";
  const saved = _lsGet(presetKey(), {});
  if (v === "save") {
    const n = prompt("Name for this setup:"); if (!n) return;
    saved[n] = { ...PSTATE }; _lsSet(presetKey(), saved); refreshPresetMenu(); toast("Preset saved: " + n, "ok");
  } else if (v === "del") {
    const n = prompt("Delete which preset?\n" + Object.keys(saved).join(", ")); if (!n || !(n in saved)) return;
    delete saved[n]; _lsSet(presetKey(), saved); refreshPresetMenu();
  } else if (v.startsWith("load:")) {
    const n = v.slice(5); if (!(n in saved)) return;
    pushUndo(); PSTATE = { ...sceneDefaults(), ...saved[n] }; renderParams(); refreshEstimate(); toast("Preset loaded: " + n, "ok");
  }
}
async function saveProject() {
  if (!CUR_EXH) return;
  try {
    const pres = { vmin: $("#x-vmin").value || null, vmax: $("#x-vmax").value || null, fps: +($("#x-fps").value || 26), zoom: ZOOM.k };
    const r = await call("save_project", CUR_SCENE, CUR_EXH, { ...PSTATE }, RUN && RUN.view, $("#s-cmap").value, ADV, RUN && RUN.run_id, pres);
    if (r.path) toast("Setup saved: " + r.path + (RUN && RUN.params && JSON.stringify(RUN.params) !== JSON.stringify(PSTATE) ? " (draft differs from the displayed run; both are recorded)" : ""), "ok");
  } catch (e) { toast("Save failed: " + errText(e), "err"); }
}
async function loadProject() {
  try {
    const r = await call("load_project");
    if (!r.config) return;
    await applyProject(r.config);
  } catch (e) { toast("Load failed: " + errText(e), "err"); }
}
async function applyProject(cfg) {
  if (cfg.scene && cfg.scene !== CUR_SCENE) {
    let d = null; try { d = await call("scene_detail", cfg.scene, nextReq("detail")); } catch (e) { d = null; }
    if (d && d.exhibit === cfg.exhibit) { openStudio(d); }
  }
  if (cfg.exhibit !== CUR_EXH) { toast("This setup is for " + cfg.exhibit + "; open that scene first", "err"); return; }
  pushUndo(); PSTATE = { ...sceneDefaults(), ...(cfg.params || {}) }; ADV = !!cfg.advanced;
  const pres = cfg.presentation || {};
  PENDING_PRES = { view: pres.view || null, cmap: pres.cmap || null, vmin: pres.vmin, vmax: pres.vmax };
  if (pres.cmap) { const cm = $("#s-cmap"); if (cm && [...cm.options].some(o => o.value === pres.cmap)) cm.value = pres.cmap; else CUR_CMAP = pres.cmap; }
  $("#x-vmin").value = pres.vmin == null ? "" : pres.vmin;        // null = automatic limits: clear any manual ones
  $("#x-vmax").value = pres.vmax == null ? "" : pres.vmax;
  if (pres.fps) $("#x-fps").value = pres.fps;
  if (pres.zoom && pres.zoom > 0) { ZOOM.k = Math.min(8, Math.max(1, pres.zoom)); ZOOM.x = ZOOM.y = 0; applyZoom(); } else zoomReset();
  renderParams(); refreshEstimate();
  const w = (cfg.validation && cfg.validation.warnings) || [];
  toast("Setup loaded" + (w.length ? " (" + w[0] + ")" : ""), "ok");
}
/* run history: duplicate a setup, pin, compare */
async function refreshHistory() {
  const box = $("#s-history"); if (!box) return;
  let r; try { r = await call("runs"); } catch (e) { return; }
  box.innerHTML = "";
  if (!r.runs.length) return;
  box.append(elt("div", "kicker", "run history"));
  for (const run of r.runs.slice().reverse()) {
    const row = el("div", "hrow" + (RUN && RUN.run_id === run.run_id ? " cur" : ""));
    const nm = elt("span", "hname", run.info); nm.title = run.info; row.append(nm);
    const pin = elt("button", "linkbtn", run.pinned ? "★" : "☆"); pin.title = run.pinned ? "Unpin (may be evicted)" : "Pin (never evicted)";
    pin.setAttribute("aria-label", (run.pinned ? "Unpin" : "Pin") + " run " + run.info);
    pin.onclick = async () => { try { await call("pin_run", run.run_id, !run.pinned); refreshHistory(); } catch (e) { toast(errText(e), "err"); } };
    const dup = elt("button", "linkbtn", "⧉"); dup.title = "Duplicate: load this run's setup into the controls";
    dup.setAttribute("aria-label", "Load setup of run " + run.info);
    dup.onclick = () => duplicateRun(run.run_id);
    const op = elt("button", "linkbtn", "▶"); op.title = "Open this result (loads its complete descriptor)";
    op.setAttribute("aria-label", "Open run " + run.info); op.onclick = () => openRun(run.run_id);
    row.append(op);
    const cmp = elt("button", "linkbtn", "⇄"); cmp.title = "Compare this run with the current one, side by side";
    cmp.setAttribute("aria-label", "Compare run " + run.info + " with the current run");
    cmp.onclick = () => compareWith(run.run_id);
    row.append(pin, dup, cmp); box.append(row);
  }
}
// Load a stored run as the displayed result: complete descriptor (views, palettes, stats, meta,
// params, provenance) from the backend, switching to the run's scene if needed.
async function openRun(rid, viewWanted) {
  let t = nextReq("view"); setBusy("loading result…");
  try {
    const info = await call("run_info", rid);
    if (!isCurrent("view", t)) return;
    if (info.scene && info.scene !== CUR_SCENE) {                // switch to the run's experiment first
      const dd = await call("scene_detail", info.scene, nextReq("detail"));
      if (!isCurrent("view", t)) return;
      openStudio(dd); t = nextReq("view");                         // openStudio invalidates view requests; this one continues
    }
    else if (info.exhibit !== CUR_EXH) { toast("Result belongs to " + info.exhibit + "; showing it without its controls", ""); }
    const r = await call("render_view", rid, viewWanted || info.view || null, $("#s-cmap").value, 26, t, $("#x-vmin").value, $("#x-vmax").value);
    if (!isCurrent("view", t)) return;
    leaveCompare();
    RUN = { ...info, run_id: rid, view: r.view, defcmap: r.cmap, field_rect: r.field_rect || null, video: null };
    buildViewbar(RUN); hideStill(); setVideo(r.video, false); renderKPIs(info.stats || []); $("#s-plotpanel").style.display = "none";
    $("#s-status").textContent = "✓ " + info.info; markMatch(); refreshHistory(); zoomReset();
  } catch (e) { if (isCurrent("view", t)) toast(errText(e), "err"); }
  if (isCurrent("view", t) && !JOB) $("#s-skel").classList.remove("on");
}
async function duplicateRun(rid) {
  try {
    const j = await call("job", rid);
    if (j.exhibit !== CUR_EXH) { toast("That run is a different scene (" + j.exhibit + ")", "err"); return; }
    pushUndo(); PSTATE = { ...sceneDefaults(), ...j.params }; renderParams(); refreshEstimate();
    toast("Setup loaded from the run — change one thing and Run", "ok");
  } catch (e) { toast(errText(e), "err"); }
}
async function compareWith(rid, again) {
  if (!RUN) { toast("Run a simulation first", "err"); return; }
  if (rid === RUN.run_id && !again) { toast("Pick a different run to compare with", "err"); return; }
  const t = nextReq("cmp"), cur = RUN.run_id, view = RUN.view; setBusy("rendering side-by-side…");
  try {
    const r = await call("compare", rid, cur, view, $("#s-cmap").value, 26, t);
    if (!isCurrent("cmp", t) || !RUN || RUN.run_id !== cur) return;     // the active run changed meanwhile
    CMP = { a: rid, b: cur, view: r.view, times: r.times, unit: r.time_unit, vmin: r.vmin, vmax: r.vmax, note: r.note, label_a: r.label_a, label_b: r.label_b, cmap: r.cmap };
    hideStill(); setVideo(r.video, false);
    $("#s-status").textContent = `⇄ comparison · left: ${r.label_a} · right: ${r.label_b} · ${r.note}`;
    const ci = $("#s-cmpinfo"); if (ci) { ci.style.display = "block"; ci.textContent = `Comparison of ${r.frames} shared frames, one colour scale ${(+r.vmin).toPrecision(3)} – ${(+r.vmax).toPrecision(3)} (${r.view}). ${r.note}. Probes and exports refer to the single run again once you switch a view or run.`; }
    toast("Left: earlier run · Right: current run · one shared colour scale", "");
  } catch (e) { if (isCurrent("cmp", t)) toast(errText(e), "err"); }
  if (isCurrent("cmp", t) && !JOB) $("#s-skel").classList.remove("on");
}
function leaveCompare() { CMP = null; const ci = $("#s-cmpinfo"); if (ci) ci.style.display = "none"; }
/* parameter sweep (bounded queue, one cancellable job) */
function openSweep() {
  const box = $("#s-sweep"); if (!box) return;
  if (box.style.display === "block") { box.style.display = "none"; return; }
  const sel = $("#s-sweep-param"); sel.innerHTML = "";
  for (const q of SPEC) if ((q.type === "float" || q.type === "int") && visible(q) && (!q.advanced || ADV)) { const o = elt("option", null, q.label); o.value = q.name; sel.append(o); }
  sel.onchange = () => { const q = SPEC.find(x => x.name === sel.value); if (q) $("#s-sweep-values").placeholder = `e.g. ${q.min}, ${(q.min + q.max) / 2}, ${q.max}`; };
  sel.onchange(); box.style.display = "block"; sel.focus();
}
async function runSweep() {
  if (JOB || !CUR_EXH) return;
  const name = $("#s-sweep-param").value, raw = $("#s-sweep-values").value;
  const values = raw.split(/[,\s]+/).filter(x => x !== "").map(Number);
  if (!values.length || values.some(v => !Number.isFinite(v))) { toast("Enter a comma-separated list of numbers", "err"); return; }
  if (values.length > 8) { toast("At most 8 values per sweep", "err"); return; }
  const t = nextReq("run");
  JOB = { id: newId(), exhibit: CUR_EXH, params: Object.freeze({ ...PSTATE }), cancelling: false, token: t, sweep: true };
  setRunning(true); $("#s-skel").classList.add("on"); $("#s-plotpanel").style.display = "none"; heroActive(false);
  $("#s-status").textContent = "⏳ sweep: preparing…"; $("#s-sweep").style.display = "none";
  let r = null, err = null;
  try { r = await api().sweep(JOB.exhibit, JOB.params, name, values, RUN && RUN.view, $("#s-cmap").value, JOB.id, ADV); }
  catch (e) { err = errText(e); }
  if (!isCurrent("run", t)) return;
  JOB = null; setRunning(false); $("#s-skel").classList.remove("on"); heroActive(CUR === "intro" && !REDUCED);
  if (r && r.ok) {
    showSweep(r); $("#s-status").textContent = `✓ sweep of ${name}: ${r.items.length} runs`; refreshHistory();
  } else if (r && r.state === "cancelled") {
    $("#s-status").textContent = "■ Sweep cancelled" + (r.items && r.items.length ? ` (${r.items.length} runs kept)` : ""); if (r.items && r.items.length) showSweep(r);
  } else { const m = err || (r && r.error) || "unknown error"; $("#s-status").textContent = "⚠ " + m; toast("Sweep failed: " + m, "err"); }
}
function showSweep(r) {
  const p = $("#s-plotpanel"); p.innerHTML = ""; p.dataset.run = "sweep";
  p.append(elt("div", "kicker", "parameter sweep · " + r.name));
  if (r.plot) { const i = el("img"); i.src = r.plot; i.alt = "readout versus " + r.name; p.append(i); }
  if (r.store) p.append(elt("div", "muted small", `${r.items.length} results kept in the run history (${r.store.runs} of ${r.store.max_runs} slots, ${(r.store.bytes / 1048576).toFixed(0)} MB in memory, ${(r.store.disk_bytes / 1048576).toFixed(0)} MB on disk). Each result is a run of its own: duplicate, report and export work from the history.`));
  const grid = el("div", "sweepgrid");
  for (const [k, it] of r.items.entries()) {
    const card = el("div", "sweepcard" + (r.retained && r.retained[k] === false ? " expired" : ""));
    if (r.retained && r.retained[k] === false) card.append(elt("div", "verr", "no longer in memory (evicted)"));
    const im = el("img"); im.src = it.frame; im.alt = r.name + " = " + it.value; card.append(im);
    card.append(elt("div", "sv", r.name + " = " + it.value));
    const ks = Object.keys(it.metrics || {});
    if (ks.length) card.append(elt("div", "sm", ks.slice(0, 3).map(k => k + " " + (it.metrics[k] == null ? "unavailable" : (+it.metrics[k]).toPrecision(3))).join(" · ")));
    card.tabIndex = 0; card.setAttribute("role", "button"); card.title = "Open this run";
    card.onclick = () => openSweepRun(it); card.onkeydown = e => { if (e.key === "Enter") openSweepRun(it); };
    grid.append(card);
  }
  p.append(grid);
  for (const e of (r.errors || [])) p.append(elt("div", "verr", r.name + " = " + e.value + ": " + e.error));
  p.style.display = "block";
}
async function openSweepRun(it) { await openRun(it.run_id, RUN && RUN.view); }
/* probes and frame inspection: click on the field */
let PROBE = false;
function toggleProbe() { PROBE = !PROBE; const b = $("#s-probe"); if (b) { b.classList.toggle("on", PROBE); b.setAttribute("aria-pressed", PROBE ? "true" : "false"); } $("#s-status").textContent = PROBE ? "📍 click on the field to read a value, probe a point in time, or draw a profile" : "Ready."; }
function curFrame() {                     // index of the encoded frame on screen
  const v = $("#s-video"); if (!v.duration || !RUN || !RUN.meta) return null;
  return FunoosLogic.frameAt(v.currentTime, FPS, RUN.meta.frames || 1);
}
function _fieldFrac(ev) {
  // fractions of the rendered frame (object-fit: contain letterboxing accounted for), +y up
  const v = $("#s-video"), st = $("#s-still");
  const src = st.style.display === "block" ? st : v;
  const rect = src.getBoundingClientRect();
  const nw = src.videoWidth || src.naturalWidth, nh = src.videoHeight || src.naturalHeight;
  if (!nw || !nh) return null;
  const sc = Math.min(rect.width / nw, rect.height / nh), w = nw * sc, h = nh * sc;
  const x0 = rect.left + (rect.width - w) / 2, y0 = rect.top + (rect.height - h) / 2;
  const fx = (ev.clientX - x0) / w, fy = 1 - (ev.clientY - y0) / h;
  if (fx < 0 || fx > 1 || fy < 0 || fy > 1) return null;
  return { fx, fy };
}
async function stageClick(ev) {
  if (!PROBE || !RUN || ZOOM.dragging) return;
  if (CMP) { toast("Probes refer to a single run: switch a view to leave the comparison first", "err"); return; }
  const f = _fieldFrac(ev); if (!f) return;
  const idx = curFrame(); const frac = idx == null ? 1.0 : idx;
  const t = nextReq("probe"), rid = RUN.run_id, view = RUN.view;   // resolve the selection ONCE
  try {
    const r = await call("inspect", rid, view, f.fx, f.fy, { index: idx == null ? undefined : idx, frac: 1.0 }, t);
    if (!RUN || RUN.run_id !== rid) return;
    if (!isCurrent("probe", t)) return;
    if (r.outside) { $("#s-status").textContent = "(colourbar panel)"; return; }
    const val = r.value == null ? (r.solid ? "solid" : "no fluid") : (+r.value).toPrecision(4);
    $("#s-status").textContent = `📍 ${r.label} = ${val} at cell (${r.ix}, ${r.iy}), t = ${(+r.time).toPrecision(4)}`;
    if (ev.shiftKey) { await showProfile(f, "x"); return; }
    if (ev.altKey) { await showProfile(f, "y"); return; }
    const pr = await call("probe", rid, view, f.fx, f.fy, t);
    if (!isCurrent("probe", t) || !RUN || RUN.run_id !== rid) return;
    const p = $("#s-plotpanel"); p.innerHTML = ""; p.dataset.run = rid;
    const card = el("div", "plot"); card.append(elt("div", "kicker", "point probe · " + pr.label));
    const i = el("img"); i.src = pr.plot; i.alt = "probe time series"; card.append(i);
    card.append(elt("div", "explain", `Value of ${pr.label} at cell (${pr.ix}, ${pr.iy}) of run ${rid} over the saved frames (time in ${pr.time_unit}). Shift-click for a horizontal profile, Alt-click for a vertical one.`));
    const sel = { rid, view, ix: pr.ix, iy: pr.iy };            // captured now: the export refers to THIS plot
    const ex = elt("button", "linkbtn", "⬇ CSV"); ex.onclick = async () => { try { const s = await call("export_csv", sel.rid, "probe", { view: sel.view, ix: sel.ix, iy: sel.iy }); if (s.path) toast("Saved " + s.path, "ok"); } catch (e) { toast(errText(e), "err"); } };
    card.append(ex); p.append(card); p.style.display = "block";
  } catch (e) { if (isCurrent("probe", t)) toast(errText(e), "err"); }
}
async function showProfile(f, axis) {
  const idx = curFrame();
  const t = nextReq("probe"), rid = RUN.run_id, view = RUN.view;
  const pr = await call("line_profile", rid, view, axis, axis === "x" ? f.fy : f.fx, { index: idx == null ? undefined : idx, frac: 1.0 }, t);
  if (!isCurrent("probe", t) || !RUN || RUN.run_id !== rid) return;
  const p = $("#s-plotpanel"); p.innerHTML = ""; p.dataset.run = rid;
  const card = el("div", "plot"); card.append(elt("div", "kicker", "line profile · " + pr.label));
  const i = el("img"); i.src = pr.plot; i.alt = "line profile"; card.append(i);
  card.append(elt("div", "explain", `${pr.label} along ${axis} at ${axis === "x" ? "row " + pr.iy : "column " + pr.ix}, frame ${pr.index} (t = ${pr.time}) of run ${rid}.`));
  const sel = { rid, view, axis, index: pr.index, ix: pr.ix, iy: pr.iy };
  const ex = elt("button", "linkbtn", "⬇ CSV"); ex.onclick = async () => { try { const s = await call("export_csv", sel.rid, "profile", { view: sel.view, axis: sel.axis, index: sel.index, ix: sel.ix, iy: sel.iy }); if (s.path) toast("Saved " + s.path, "ok"); } catch (e) { toast(errText(e), "err"); } };
  card.append(ex); p.append(card); p.style.display = "block";
}
/* zoom & pan of the stage (CSS transform; the data are untouched) */
const ZOOM = { k: 1, x: 0, y: 0, dragging: false, sx: 0, sy: 0, ox: 0, oy: 0 };
function applyZoom() {
  const tr = `translate(${ZOOM.x}px, ${ZOOM.y}px) scale(${ZOOM.k})`;
  for (const id of ["#s-video", "#s-still"]) { const e = $(id); if (e) { e.style.transform = tr; e.style.transformOrigin = "center center"; } }
  const z = $("#s-zoom"); if (z) z.textContent = Math.round(ZOOM.k * 100) + "%";
}
function zoomBy(f) { ZOOM.k = Math.min(8, Math.max(1, ZOOM.k * f)); if (ZOOM.k === 1) { ZOOM.x = ZOOM.y = 0; } applyZoom(); }
function zoomReset() { ZOOM.k = 1; ZOOM.x = ZOOM.y = 0; applyZoom(); }
function initStage() {
  const sc = $("#s-screen"); if (!sc) return;
  sc.addEventListener("wheel", e => { if (!RUN) return; e.preventDefault(); zoomBy(e.deltaY < 0 ? 1.15 : 1 / 1.15); }, { passive: false });
  sc.addEventListener("pointerdown", e => { if (ZOOM.k === 1) return; ZOOM.dragging = false; ZOOM.sx = e.clientX; ZOOM.sy = e.clientY; ZOOM.ox = ZOOM.x; ZOOM.oy = ZOOM.y; sc.setPointerCapture(e.pointerId); sc.dataset.down = "1"; });
  sc.addEventListener("pointermove", e => { if (sc.dataset.down !== "1") return; const dx = e.clientX - ZOOM.sx, dy = e.clientY - ZOOM.sy; if (Math.hypot(dx, dy) > 3) ZOOM.dragging = true; ZOOM.x = ZOOM.ox + dx; ZOOM.y = ZOOM.oy + dy; applyZoom(); });
  sc.addEventListener("pointerup", e => { sc.dataset.down = "0"; setTimeout(() => { ZOOM.dragging = false; }, 0); });
  sc.addEventListener("click", stageClick);
}
document.addEventListener("keydown", e => {
  if (CUR !== "studio" || e.target.matches("input,select,textarea,button,a,[role=button],summary")) return;
  if (e.key === " ") { e.preventDefault(); vToggle(); }
  else if (e.key === "ArrowLeft") { vStep(-1); } else if (e.key === "ArrowRight") { vStep(1); }
  else if (e.key === "+" || e.key === "=") { zoomBy(1.15); } else if (e.key === "-") { zoomBy(1 / 1.15); } else if (e.key === "0") { zoomReset(); }
  else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") { e.preventDefault(); if (e.shiftKey) redoParams(); else undoParams(); }
  else if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { runSim(); }
});

/* settings: memory, threads, previews, autoplay */
async function openSettings() {
  const box = $("#settings"); if (!box) return;
  if (box.style.display === "block") { box.style.display = "none"; return; }
  try { const r = await call("runs"); $("#st-maxruns").value = r.max_runs; $("#st-mem").value = Math.round(r.max_bytes / 1048576); $("#st-usage").textContent = `${r.runs.length} runs · ${(r.bytes / 1048576).toFixed(0)} MB in memory · ${(r.disk_bytes / 1048576).toFixed(0)} MB on disk`; } catch (e) { /* advisory */ }
  try { const s = await call("settings"); $("#st-threads").value = s.threads; $("#st-threads").max = s.cpus; $("#st-threadnote").textContent = `of ${s.cpus} logical CPUs`; } catch (e) { /* advisory */ }
  $("#st-autoplay").checked = _lsGet("funoos.autoplay", true); $("#st-preview").checked = _lsGet("funoos.preview", true);
  box.style.display = "block";
}
async function applySettings() {
  try {
    await call("set_budget", +$("#st-maxruns").value || 3, +$("#st-mem").value || 1024);
    await call("set_threads", +$("#st-threads").value || 0);
    _lsSet("funoos.autoplay", $("#st-autoplay").checked); _lsSet("funoos.preview", $("#st-preview").checked);
    _reconcilePlayback(); toast("Settings applied", "ok");
  } catch (e) { toast(errText(e), "err"); }
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
  const st = $("#s-simtime");
  const times = CMP ? CMP.times : (RUN && RUN.meta && RUN.meta.times), unit = CMP ? CMP.unit : (RUN && RUN.meta && RUN.meta.time_unit);
  if (st && times && times.length) {
    const i = FunoosLogic.frameAt(v.currentTime, FPS, times.length);
    const tv = times[i]; st.textContent = "t = " + (Math.abs(tv) >= 1000 ? Math.round(tv) : +tv.toPrecision(4)) + " " + (unit || "") + (CMP ? " (comparison)" : "");
  } else if (st) st.textContent = "";
}, true);

/* toasts */
function toast(msg, kind) {
  const t = elt("div", "toast " + (kind || ""), msg); $("#toasts").append(t);
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
  let t = 0, active = !REDUCED, raf = null;
  window.heroActive = on => {
    const want = !!on && !REDUCED;
    if (want === active) return;
    active = want; if (active && raf === null) raf = requestAnimationFrame(frame);
  };
  if (REDUCED) { ctx.fillStyle = "rgba(7,13,24,1)"; ctx.fillRect(0, 0, W, H); }
  document.addEventListener("visibilitychange", () => { if (document.hidden) { active = false; } else if (CUR === "intro" && !JOB && !REDUCED) window.heroActive(true); });
  function frame() {
    raf = null;
    if (!active) return;
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
    raf = requestAnimationFrame(frame);
  }
  if (active) raf = requestAnimationFrame(frame);
})();

/* guided comparison: run two presets of one experiment in sequence, then show them side by side */
async function guidedCompare(a, b) {
  if (JOB) { toast("A run is in progress", "err"); return; }
  let da; try { da = await call("scene_detail", a, nextReq("detail")); } catch (e) { toast(errText(e), "err"); return; }
  openStudio(da); show("studio");
  const run = async (key) => {
    const d = await call("scene_detail", key, nextReq("detail")); const params = { ...Object.fromEntries(d.params.map(q => [q.name, q.default])), ...(d.preset || {}) };
    const t = nextReq("run"); JOB = { id: newId(), exhibit: d.exhibit, params: Object.freeze(params), cancelling: false, token: t };
    setRunning(true); $("#s-skel").classList.add("on"); $("#s-status").textContent = "⏳ " + d.name + "…";
    let r = null; try { r = await api().run(d.exhibit, params, null, d.cmap || $("#s-cmap").value, 26, JOB.id, false); } catch (e) { r = { ok: false, error: errText(e) }; }
    JOB = null; setRunning(false); $("#s-skel").classList.remove("on"); hideStill();
    if (!r || !r.ok) throw new Error((r && r.error) || "run failed");
    RUN = r; buildViewbar(r); setVideo(r.video, false); renderKPIs(r.stats || []); refreshHistory(); return r.run_id;
  };
  try {
    const ra = await run(a); const rb = await run(b);
    await compareWith(ra);
  } catch (e) { toast("Guided comparison stopped: " + errText(e), "err"); }
}

async function openUrl(u) { try { await call("open_url", u); } catch (e) { toast(errText(e), "err"); } }
async function fillAbout() {
  try { const a = await call("about"); const box = $("#about-body"); if (!box) return; box.innerHTML = "";
    const row = (k, v) => { const r = el("div", "sline"); r.append(elt("b", null, k), elt("span", null, v)); return r; };
    const s = el("div", "setup"); s.append(row("Author", a.author), row("Version", a.version + (a.build ? " · build " + a.build : "")), row("Licence", a.license), row("Python", a.python)); box.append(s);
    const links = el("div", "ptools"); for (const [label, url] of a.links) { const b = elt("button", "linkbtn", label); b.onclick = () => openUrl(url); links.append(b); } box.append(links);
    box.append(elt("div", "kicker", "citation")); const cit = el("pre", "cite"); cit.textContent = a.citation; box.append(cit);
    box.append(elt("div", "kicker", "acknowledgements")); box.append(elt("div", "read small", a.acknowledgements));
  } catch (e) { /* about is static; ignore */ }
}

/* boot — last, so every top-level declaration above is initialised even when the bridge is
   already present while this script is evaluated (no pywebviewready event in that case) */
function boot() { buildGallery().then(fillStudioPicker); initStage(); show("intro"); }
if (window.pywebview && window.pywebview.api) boot();
else window.addEventListener("pywebviewready", boot);

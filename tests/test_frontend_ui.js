// Frontend interaction test: loads the real index.html + web/logic.js + web/app.js in jsdom and
// drives them with the REAL catalogue/detail responses (generated from the Python registry) and a
// stubbed pywebview bridge.  Run: node tests/test_frontend_ui.js   (needs: npm install jsdom)
//
// Covers: every experiment card opens (click, Enter, Space) and shows its layers and related
// items; Back; preset switching in Detail and Studio incl. out-of-order replies; job button
// states when switching experiments during a run and reopening a background result from the
// history; recolouring a comparison keeps the comparison; sweep cards show "unavailable" for
// null metrics; loading a setup restores/clears presentation fields; the playback clock uses
// the encoded-frame index and the comparison's own times.
const assert = require("assert");
const path = require("path");
const fs = require("fs");
const { execFileSync } = require("child_process");
const { JSDOM } = require("jsdom");

const ROOT = path.resolve(__dirname, "..");
const UI = process.env.FUNOOS_UI_ROOT ? path.resolve(process.env.FUNOOS_UI_ROOT) : ROOT;   // page under test (default: this checkout)
const fixtures = JSON.parse(execFileSync("python3", ["-c", `
import sys, json; sys.path.insert(0, ${JSON.stringify(ROOT)})
from funoos_app import Api, RunStore
from flowzoo import catalog
api = Api(store=RunStore(max_runs=2), sweep=False)
print(json.dumps({"catalog": api.catalog(), "details": {s["key"]: api.scene_detail(s["key"]) for s in catalog.SCENES}, "exhibits": api.exhibits()}))
`], { maxBuffer: 64 << 20 }).toString());

const sleep = ms => new Promise(r => setTimeout(r, ms));
async function until(fn, what, ms = 4000) { const t0 = Date.now(); while (Date.now() - t0 < ms) { try { if (fn()) return; } catch (e) { /* retry */ } await sleep(10); } throw new Error("timeout waiting for " + what); }
let n = 0, failed = 0;
async function t(name, fn) { try { await fn(); n++; console.log("  ok   " + name); } catch (e) { failed++; console.log("  FAIL " + name + ": " + (e.stack || e).toString().split("\n").slice(0, 3).join(" | ")); } }

// ---------- the bridge stub: real catalogue data, controllable delays and pending runs ----------
const calls = [];
const delays = {};                                    // scene key → ms before scene_detail replies
let pendingRun = null;                                // {resolve} of the run in flight
const fakeVideo = "data:video/mp4;base64,AAAA";
const fakeRun = (id, exhibit, params, view) => ({ ok: true, job_id: id, run_id: id, state: "completed", video: fakeVideo,
  views: ["Vorticity", "Speed", "Streamlines"], view: view || "Vorticity", info: "run " + id, cmaps: ["Turbo", "Inferno"], defcmap: "Turbo",
  stats: [{ l: "frames", v: "3" }], params: params || {}, evicted: [], meta: { frames: 100, times: Array.from({ length: 100 }, (_, i) => i * 10), time_unit: "lattice steps", shape: [8, 8] },
  validation: { ok: true, errors: [], warnings: [], applied: [] }, derived: [], store: { runs: 1, bytes: 0 } });
const stored = {};
function sceneFor(exhibit, params) {
  let best = null, n = -1;
  for (const [k, d] of Object.entries(fixtures.details)) {
    const pre = d.preset || {};
    if (d.exhibit === exhibit && Object.entries(pre).every(([a, b]) => params[a] === b) && Object.keys(pre).length > n) { best = k; n = Object.keys(pre).length; }
  }
  return best;
}
const api = {
  catalog: async () => fixtures.catalog,
  exhibits: async () => fixtures.exhibits,
  scene_detail: async (key, req) => { calls.push(["scene_detail", key]); if (delays[key]) await sleep(delays[key]); const d = fixtures.details[key]; return d ? { ...d, req } : { ok: false, error: "unknown scene", req }; },
  estimate: async () => ({ ok: true, grid: [10, 10], frames: 3, mb: 0.1, seconds: 1, threads: 1 }),
  derived: async () => ({ ok: true, items: [] }),
  validate: async () => ({ ok: true, errors: [], warnings: [], applied: [], params: {} }),
  runs: async () => ({ ok: true, runs: Object.values(stored).map(r => ({ run_id: r.run_id, info: r.info, pinned: false, bytes: 0, disk: 0 })), max_runs: 3, max_bytes: 1, bytes: 0, disk_bytes: 0, disk_max: 1 }),
  run: (exhibit, params, view, cmap, fps, job_id) => new Promise(resolve => { pendingRun = { resolve: () => { const r = fakeRun(job_id, exhibit, params, view); stored[job_id] = { ...r, exhibit }; resolve(r); } }; }),
  cancel: async id => ({ ok: true, job_id: id, state: "running", cancel_requested: true }),
  run_info: async rid => { const r = stored[rid]; return r ? { ok: true, run_id: rid, info: r.info, views: r.views, view: r.view, cmaps: r.cmaps, defcmap: r.defcmap, stats: r.stats, meta: r.meta, params: r.params, exhibit: r.exhibit, scene: sceneFor(r.exhibit, r.params), state: "completed", provenance: {}, parent: null, derived: [] } : { ok: false, error: "run expired" }; },
  render_view: async (rid, view, cmap, fps, req, vmin, vmax) => { calls.push(["render_view", rid, view, cmap]); return { ok: true, run_id: rid, req, view: view || "Vorticity", cmap: cmap || "Turbo", video: fakeVideo, cached: false, field_rect: { x0: 0, y0: 0, w: 0.8, h: 1, shape: [8, 8] } }; },
  preview_frame: async (rid, view, cmap, frac, req) => ({ ok: true, req, img: "data:image/png;base64,AAAA", index: 0, time: 0 }),
  compare: async (a, b, view, cmap, fps, req) => { calls.push(["compare", a, b, view, cmap]); return { ok: true, req, video: fakeVideo, times: [10, 20, 30, 40], run_a: a, run_b: b, view, cmap, vmin: 0, vmax: 1, time_unit: "lattice steps", note: "shared interval [10, 40]", label_a: "A", label_b: "B", info: "A | B", frames: 4 }; },
  job: async rid => ({ ok: true, job_id: rid, exhibit: stored[rid] && stored[rid].exhibit, params: stored[rid] ? stored[rid].params : {}, state: "completed" }),
  pin_run: async () => ({ ok: true }),
  settings: async () => ({ ok: true, threads: 4, cpus: 8 }),
  about: async () => ({ ok: true, author: "x", version: "t", license: "MIT", python: "3", links: [], citation: "c", acknowledgements: "a" }),
};

(async () => {
  const html = fs.readFileSync(path.join(UI, "index.html"), "utf8");
  const dom = new JSDOM(html, {
    url: "file://" + UI + "/index.html", runScripts: "dangerously", resources: "usable", pretendToBeVisual: true,
    beforeParse(window) {
      window.pywebview = { api };
      window.matchMedia = () => ({ matches: false, addListener() {}, addEventListener() {} });
      window.IntersectionObserver = class { constructor(cb) { this.cb = cb; } observe() {} unobserve() {} disconnect() {} };
      window.HTMLMediaElement.prototype.play = function () { return Promise.resolve(); };
      window.HTMLMediaElement.prototype.pause = function () {};
      window.HTMLMediaElement.prototype.load = function () {};
      window.Element.prototype.animate = () => ({ onfinish: null });
      window.HTMLCanvasElement.prototype.getContext = () => ({ fillRect() {}, beginPath() {}, moveTo() {}, lineTo() {}, stroke() {}, set fillStyle(v) {}, set strokeStyle(v) {}, set lineWidth(v) {} });
      window.prompt = () => null;
    },
  });
  const w = dom.window, d = w.document, $ = s => d.querySelector(s), $$ = s => [...d.querySelectorAll(s)];
  const G = expr => w.eval(expr);                     // top-level let/const of app.js live in the global lexical scope
  const cardOf = name => $$("#gallery-grid .gcard").find(c => c.getAttribute("aria-label").startsWith(name + " —"));
  w.addEventListener("error", e => { console.log("  window error:", e.message); });
  await until(() => $$("#gallery-grid .gcard").length > 0, "gallery cards", 8000);

  const cards = $$("#gallery-grid .gcard");
  const exps = fixtures.catalog.groups.flatMap(g => g.experiments);
  await t("27 experiment cards rendered", async () => { assert.strictEqual(cards.length, exps.length); assert.strictEqual(cards.length, 27); });

  await t("every card opens its detail page by click, with layers and related experiments", async () => {
    for (const e of exps) {
      const card = cardOf(e.name);
      assert.ok(card, e.name);
      card.click();
      await until(() => $("#detail").classList.contains("active") && $("#d-title").textContent === e.name, "detail of " + e.name);
      assert.ok($$("#d-text .layer").length >= 6, "layers rendered for " + e.name);
      const group = fixtures.catalog.groups.find(g => g.experiments.some(x => x.id === e.id));
      const expected = group.experiments.length - 1;
      assert.strictEqual($$("#d-text .related .rel").length, expected, "related items for " + e.name);
      const sel = $("#d-preset");
      if (e.presets.length > 1) assert.strictEqual(sel.options.length, e.presets.length, "preset selector for " + e.name); else assert.strictEqual(sel.style.display, "none");
      $(".back").click();
      await until(() => $("#gallery").classList.contains("active"), "back to gallery");
    }
  });
  await t("Enter and Space open a card from the keyboard", async () => {
    for (const key of ["Enter", " "]) {
      const card = $$("#gallery-grid .gcard")[3];
      card.dispatchEvent(new w.KeyboardEvent("keydown", { key, bubbles: true }));
      await until(() => $("#detail").classList.contains("active") && $("#d-title").textContent === exps[3].name, "keyboard open " + key);
      $(".back").click(); await until(() => $("#gallery").classList.contains("active"), "back");
    }
  });
  await t("related items navigate to another experiment; favourite button does not open the card", async () => {
    $$("#gallery-grid .gcard")[0].click(); await until(() => $("#detail").classList.contains("active"), "detail");
    const rel = $("#d-text .related .rel"); const target = rel.querySelector(".rnm").textContent;
    rel.click(); await until(() => $("#d-title").textContent === target, "related target " + target);
    $(".back").click(); await until(() => $("#gallery").classList.contains("active"), "back");
    const fav = $$("#gallery-grid .gcard")[1].querySelector(".favbtn"); fav.dispatchEvent(new w.KeyboardEvent("keydown", { key: "Enter", bubbles: true })); await sleep(50);
    assert.ok($("#gallery").classList.contains("active"), "favourite keydown must not open the card");
  });
  await t("preset switching in Detail updates title/preset and survives out-of-order replies", async () => {
    const air = exps.find(e => e.id === "airfoil_lift");
    cardOf(air.name).click();
    await until(() => $("#d-title").textContent === air.name, "airfoil detail");
    const sel = $("#d-preset");
    sel.value = "lbm_airfoil_zero"; sel.dispatchEvent(new w.Event("change"));
    await until(() => /0°/.test($("#d-presetname").textContent), "0° preset");
    delays["lbm_airfoil_neg"] = 300; delays["lbm_airfoil_zero"] = 20;          // −14° replies AFTER 0°
    sel.value = "lbm_airfoil_neg"; sel.dispatchEvent(new w.Event("change"));
    await sleep(5);
    sel.value = "lbm_airfoil_zero"; sel.dispatchEvent(new w.Event("change"));
    await sleep(500);
    assert.ok(/0°/.test($("#d-presetname").textContent), "latest selection wins: " + $("#d-presetname").textContent);
    delete delays["lbm_airfoil_neg"]; delete delays["lbm_airfoil_zero"];
  });
  await t("Studio preset selector: latest request wins", async () => {
    $("#d-open").click(); await until(() => $("#studio").classList.contains("active"), "studio");
    const sel = $("#s-preset"); assert.ok(sel && sel.style.display !== "none", "studio preset selector present");
    delays["lbm_airfoil_neg"] = 300; delays["lbm_airfoil"] = 20;
    sel.value = "lbm_airfoil_neg"; sel.dispatchEvent(new w.Event("change")); await sleep(5);
    sel.value = "lbm_airfoil"; sel.dispatchEvent(new w.Event("change")); await sleep(500);
    assert.ok(/\+14°/.test($("#s-name").textContent), "studio shows the latest preset: " + $("#s-name").textContent);
    delete delays["lbm_airfoil_neg"]; delete delays["lbm_airfoil"];
  });
  await t("switching experiments during a run keeps Cancel visible and Run disabled; the result is reopened from history", async () => {
    $("#s-run").click();
    await until(() => pendingRun !== null, "run started");
    assert.ok($("#s-run").disabled && $("#s-cancel").style.display === "block", "running state");
    const sceneSel = $("#s-scene"); sceneSel.value = "dam_break"; sceneSel.dispatchEvent(new w.Event("change"));
    await until(() => /Dam break/i.test($("#s-name").textContent), "dam break studio");
    assert.ok($("#s-run").disabled, "Run stays disabled while another experiment runs");
    assert.ok($("#s-cancel").style.display === "block" && /Airfoil/i.test($("#s-cancel").textContent), "Cancel names the running experiment: " + $("#s-cancel").textContent);
    assert.ok(/simulating/i.test($("#s-status").textContent), "status says what is running");
    pendingRun.resolve(); pendingRun = null;
    await until(() => !$("#s-run").disabled, "run finished");
    assert.ok($("#s-cancel").style.display === "none", "Cancel hidden after completion");
    await until(() => $$("#s-history .hrow").length === 1, "history row");
    $("#s-history .hrow button[aria-label^='Open run']").click();
    await until(() => G("RUN") && G("RUN").meta && G("RUN").meta.frames === 100, "run reopened with a complete descriptor");
    assert.ok(/AIRFOIL/.test($("#s-name").textContent), "switched back to the run's experiment: " + $("#s-name").textContent);
    assert.strictEqual(G("CUR_SCENE"), "lbm_airfoil");
    assert.ok(G("RUN").views.length === 3 && G("RUN").params.angle !== undefined && $("#s-video").style.display === "block");
  });
  await t("playback clock uses the encoded-frame index and the comparison's own times", async () => {
    const v = $("#s-video");
    Object.defineProperty(v, "duration", { value: 100 / 26, configurable: true });
    Object.defineProperty(v, "currentTime", { value: 51 / 26 + 1e-4, configurable: true, writable: true });
    v.dispatchEvent(new w.Event("timeupdate", { bubbles: true }));
    assert.ok(/t = 510 /.test($("#s-simtime").textContent), "frame 51 → t = 510: " + $("#s-simtime").textContent);
    // comparison with its own times
    stored["other"] = { ...fakeRun("other", "Wind Tunnel", {}, "Vorticity"), exhibit: "Wind Tunnel" };
    await w.compareWith("other");
    await until(() => G("CMP") !== null, "comparison state");
    Object.defineProperty(v, "currentTime", { value: 2 / 26 + 1e-4, configurable: true, writable: true });
    v.dispatchEvent(new w.Event("timeupdate", { bubbles: true }));
    assert.ok(/t = 30 .*comparison/.test($("#s-simtime").textContent), "comparison frame 2 → t = 30: " + $("#s-simtime").textContent);
  });
  await t("changing the palette during a comparison recolours the comparison (state and video stay together)", async () => {
    const before = calls.filter(c => c[0] === "compare").length, renders = calls.filter(c => c[0] === "render_view").length;
    $("#s-cmap").value = "Inferno"; $("#s-cmap").dispatchEvent(new w.Event("change"));
    await until(() => calls.filter(c => c[0] === "compare").length === before + 1, "compare called again");
    const last = calls.filter(c => c[0] === "compare").pop();
    assert.strictEqual(last[4], "Inferno");
    await until(() => G("CMP") && G("CMP").cmap === "Inferno", "comparison state kept with the new palette");
    await sleep(100);
    assert.strictEqual(calls.filter(c => c[0] === "render_view").length, renders, "no single-run clip replaced the comparison");
  });
  await t("sweep cards show 'unavailable' for missing metrics instead of 0", async () => {
    w.showSweep({ name: "reynolds", items: [{ value: 60, run_id: "x", info: "i", stats: [], metrics: { strouhal: null, cd: 1.5 }, frame: "data:image/png;base64,AAAA" }], errors: [], plot: null, retained: [true], store: { runs: 1, max_runs: 3, bytes: 0, disk_bytes: 0 } });
    const txt = $("#s-plotpanel .sweepcard .sm").textContent;
    assert.ok(/strouhal unavailable/.test(txt) && /cd 1\.50/.test(txt), txt);
  });
  await t("loading a setup restores fps and zoom and clears manual limits when the saved value is automatic", async () => {
    $("#x-vmin").value = "0.1"; $("#x-vmax").value = "0.9";
    await w.applyProject({ scene: G("CUR_SCENE"), exhibit: G("CUR_EXH"), params: {}, advanced: false, presentation: { view: "Speed", cmap: "Turbo", vmin: null, vmax: null, fps: 12, zoom: 2 }, validation: { warnings: [] } });
    assert.strictEqual($("#x-vmin").value, ""); assert.strictEqual($("#x-vmax").value, "");
    assert.strictEqual($("#x-fps").value, "12"); assert.strictEqual(G("ZOOM").k, 2);
  });
  console.log(`${n} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})().catch(e => { console.log("HARNESS ERROR", e); process.exit(1); });

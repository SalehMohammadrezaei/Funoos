/* Funoos — pure frontend logic (no DOM). Loaded before app.js; also usable from node for tests. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory(); else root.FunoosLogic = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";
  // Complete numeric parsing with one decimal policy ('.' or ',' as the decimal mark; nothing partial).
  const NUM_RE = /^[+-]?(\d+([.,]\d*)?|[.,]\d+)([eE][+-]?\d+)?$/;
  function parseNum(s) { s = String(s).trim(); if (!NUM_RE.test(s)) return NaN; return Number(s.replace(",", ".")); }
  // Validation message for one control (null = valid). Mirrors flowzoo/schema.py.
  function checkParam(q, v, adv) {
    if (q.type === "choice") return q.choices.includes(v) ? null : "choose one of the options";
    if (q.type === "str") return (v == null || !String(v).trim()) ? "enter some text" : null;
    const num = typeof v === "number" ? v : parseNum(v);
    if (v == null || v === "" || !Number.isFinite(num)) return "enter a number (e.g. 0.01 or 1e-3)";
    v = num;
    if (q.type === "int" && !Number.isInteger(v)) return "warn:will be rounded to " + Math.round(v);
    if (q.hard_min != null && v < q.hard_min) return "must be ≥ " + q.hard_min + (q.units ? " " + q.units : "") + " (solver limit)";
    if (q.hard_max != null && v > q.hard_max) return "must be ≤ " + q.hard_max + (q.units ? " " + q.units : "") + " (solver limit)";
    const out = (q.min != null && v < q.min) || (q.max != null && v > q.max);
    if (out && !adv) return "outside the recommended range " + q.min + " – " + q.max + " (turn on advanced mode to explore)";
    if (out) return "warn:outside the recommended range " + q.min + " – " + q.max;
    return null;
  }
  const isError = msg => !!msg && !/^warn:/.test(msg);
  // Form validity: the Run button is enabled iff no visible control has an error.
  function formValid(spec, state, adv, visible) {
    return spec.every(q => !visible(q, state) || !isError(checkParam(q, state[q.name], adv)));
  }
  // Request tokens: a reply applies only if it is the newest of its kind.
  function makeTokens(kinds) {
    const req = {}; for (const k of kinds) req[k] = 0;
    return { next: k => ++req[k], isCurrent: (k, t) => req[k] === t, get: k => req[k] };
  }
  // Frame index of the encoded clip at playback time t (fps frames per second, n frames).
  function frameAt(t, fps, n) { return Math.min(n - 1, Math.max(0, Math.floor(t * fps + 1e-6))); }
  // Stored favourites/recents migration: scene keys → {experimentId: sceneKey}.
  function migrateFavs(oldKeys, s2e) { const out = {}; for (const k of oldKeys || []) { if (typeof k === "string" && s2e[k]) out[s2e[k]] = k; } return out; }
  function migrateRecents(old, s2e) { return (old || []).map(x => typeof x === "string" ? { exp: s2e[x], key: x } : x).filter(x => x && x.exp); }
  // Result-vs-controls: does a run's parameter snapshot match the current controls (visible ones only)?
  function matchesControls(spec, runParams, state, visible) {
    if (!runParams) return false;
    return spec.every(q => !visible(q, state) || String(runParams[q.name]) === String(state[q.name]));
  }
  return { parseNum, checkParam, isError, formValid, makeTokens, frameAt, migrateFavs, migrateRecents, matchesControls, NUM_RE };
});

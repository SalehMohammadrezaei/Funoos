// Frontend logic checks (run with: node tests/test_frontend.js). Covers input recovery after an
// invalid value, stale-response tokens, the frame index of the clip, favourite/recent migration
// and the result-vs-controls identity — without a browser.
const assert = require("assert");
const L = require("../web/logic.js");
let n = 0;
function t(name, fn) { try { fn(); n++; console.log("  ok   " + name); } catch (e) { console.log("  FAIL " + name + ": " + e.message); process.exitCode = 1; } }

t("parseNum accepts complete numbers only", () => {
  assert.strictEqual(L.parseNum("0,01"), 0.01); assert.strictEqual(L.parseNum("1e-3"), 0.001); assert.strictEqual(L.parseNum(" 2 "), 2);
  for (const bad of ["1e", "2abc", "", ".", "1,2,3", "nan", "0x10"]) assert.ok(Number.isNaN(L.parseNum(bad)), bad);
});
const spec = [{ name: "re", type: "float", min: 30, max: 1200, hard_min: 5, hard_max: 5000 }, { name: "n", type: "int", min: 0, max: 8 },
              { name: "shape", type: "choice", choices: ["a", "b"] }, { name: "angle", type: "float", min: -25, max: 25, when: ["shape", ["b"]] }];
const vis = (q, s) => !q.when || q.when[1].includes(s[q.when[0]]);
t("Run recovers after an invalid value is corrected", () => {
  const s = { re: "abc", n: 3, shape: "a", angle: 0 };
  assert.strictEqual(L.formValid(spec, s, false, vis), false);
  s.re = "160"; assert.strictEqual(L.formValid(spec, s, false, vis), true);
  s.re = 3000; assert.strictEqual(L.formValid(spec, s, false, vis), false, "soft range needs advanced mode");
  assert.strictEqual(L.formValid(spec, s, true, vis), true);
  s.re = 9000; assert.strictEqual(L.formValid(spec, s, true, vis), false, "solver limit is hard");
  s.re = 100; s.n = 2.5; assert.ok(/^warn:/.test(L.checkParam(spec[1], s.n, false)) && L.formValid(spec, s, false, vis), "rounding is a warning");
  s.angle = 999; assert.strictEqual(L.formValid(spec, s, false, vis), true, "hidden controls are ignored");
});
t("stale responses are rejected by tokens", () => {
  const T = L.makeTokens(["view"]); const a = T.next("view"); const b = T.next("view");
  assert.ok(!T.isCurrent("view", a) && T.isCurrent("view", b));
});
t("frame index follows the encoded clip", () => {
  assert.strictEqual(L.frameAt(0, 26, 90), 0); assert.strictEqual(L.frameAt(1 / 26, 26, 90), 1); assert.strictEqual(L.frameAt(89.99 / 26, 26, 90), 89);
  assert.strictEqual(L.frameAt(100, 26, 90), 89);
});
t("favourites and recents migrate to experiments keeping the original preset", () => {
  const s2e = { lbm_airfoil_neg: "airfoil_lift", sph_dam: "dam_break" };
  assert.deepStrictEqual(L.migrateFavs(["lbm_airfoil_neg", "zzz"], s2e), { airfoil_lift: "lbm_airfoil_neg" });
  assert.deepStrictEqual(L.migrateRecents(["sph_dam", "nope"], s2e), [{ exp: "dam_break", key: "sph_dam" }]);
  assert.deepStrictEqual(L.migrateRecents([{ exp: "x", key: "y" }], s2e), [{ exp: "x", key: "y" }]);
});
t("result identity: displayed run versus edited controls", () => {
  const run = { re: 160, n: 3, shape: "a", angle: 0 }; const s = { re: 160, n: 3, shape: "a", angle: 5 };
  assert.strictEqual(L.matchesControls(spec, run, s, vis), true, "hidden angle does not count");
  s.re = 200; assert.strictEqual(L.matchesControls(spec, run, s, vis), false);
});
console.log(n + " frontend checks ran" + (process.exitCode ? " — FAILURES" : ""));

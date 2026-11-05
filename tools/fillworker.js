/* Fill search worker for the Fill grid tab.
 *
 * Finds high-quality fills for a section of a crossword grid using your word
 * scores. Quality = the weakest new entry first, then the average:
 *   1. For thresholds 60, 55, 50, ... it asks "can every new entry in the
 *      section score >= t?" using arc consistency + backtracking. The first
 *      threshold that works is the best possible weakest word (proven when every
 *      higher threshold was ruled out completely, not just timed out).
 *   2. It then collects different fills at that level, each time excluding one
 *      word of an earlier fill, so the alternatives really differ.
 * Squares outside the section stay fillable: their entries only need words
 * scoring at least the "floor".
 *
 * Messages in:  {type:"dict", lens:{L:{mat:ArrayBuffer(Uint8 letters 0-25), score:ArrayBuffer(Int16)}}}
 *               {type:"score", word, score}         (-1 removes the word)
 *               {type:"solve", id, n, cells, region, floor, timeMs, maxResults}
 *               {type:"cands", id, n, cells, slotCells, floor, limit}
 * Messages out: {type:"ready", count} {type:"progress", id, text} {type:"result", id, ...} {type:"error", id, message}
 */
"use strict";

let D = {};              // L -> {mat, score, n, order}
let scratch = new Int32Array(1 << 16);
let index = new Map();   // WORD -> [L, i]

const A_CODE = 65;

function wordAt(L, i) {
  const d = D[L];
  let s = "";
  for (let p = 0; p < L; p++) s += String.fromCharCode(A_CODE + d.mat[i * L + p]);
  return s;
}

function orderOf(L) {
  const d = D[L];
  if (!d) return null;
  if (!d.order) {
    const idx = [];
    for (let i = 0; i < d.n; i++) if (d.score[i] >= 0) idx.push(i);
    idx.sort((a, b) => d.score[b] - d.score[a] || a - b);
    d.order = Int32Array.from(idx);
  }
  return d.order;
}

// ----- grid model ------------------------------------------------------------
function extractSlots(n, cells) {
  const slots = [];
  const run = (dir) => {
    for (let a = 0; a < n; a++) {
      let cur = [];
      for (let b = 0; b <= n; b++) {
        const i = b < n ? (dir === "A" ? a * n + b : b * n + a) : -1;
        if (i >= 0 && cells[i] !== "#") cur.push(i);
        else {
          if (cur.length >= 2) slots.push({ dir, cells: cur, L: cur.length });
          cur = [];
        }
      }
    }
  };
  run("A");
  run("D");
  return slots;
}

function prepare(m) {
  const { n, cells } = m;
  const slots = extractSlots(n, cells);
  const short = slots.filter((s) => s.L < 3 && s.cells.some((i) => !cells[i]));
  const used = new Set();
  for (const s of slots) {
    if (s.cells.every((i) => cells[i])) {
      const w = s.cells.map((i) => cells[i]).join("");
      const r = index.get(w);
      if (r) used.add(r[0] + ":" + r[1]);
    }
  }
  const active = slots.filter((s) => s.L >= 3 && s.cells.some((i) => !cells[i]));
  const owners = new Map();
  active.forEach((s, k) => s.cells.forEach((i, p) => {
    if (!owners.has(i)) owners.set(i, []);
    owners.get(i).push([k, p]);
  }));
  const cross = active.map(() => []);
  for (const list of owners.values()) {
    if (list.length === 2) {
      const [[a, pa], [b, pb]] = list;
      cross[a].push([pa, b, pb]);
      cross[b].push([pb, a, pa]);
    }
  }
  return { slots, active, cross, used, short };
}

// Keep only the given active slots (indices into P.active) and rebuild crossings.
function subset(P, keep) {
  const map = new Map();
  const active = [];
  keep.forEach((k) => { map.set(k, active.length); active.push(P.active[k]); });
  const cross = active.map(() => []);
  keep.forEach((k) => {
    for (const [p, o, q] of P.cross[k]) if (map.has(o)) cross[map.get(k)].push([p, map.get(o), q]);
  });
  return { ...P, active, cross, map };
}

// ----- domains / propagation -------------------------------------------------
function makeEngine(P, cells) {
  const { active, cross, used } = P;

  function base(k, minScore, exclude) {
    const s = active[k];
    const d = D[s.L];
    const order = orderOf(s.L);
    if (!d || !order) return new Int32Array(0);
    const fixed = [];
    s.cells.forEach((i, p) => { if (cells[i]) fixed.push(p, cells[i].charCodeAt(0) - A_CODE); });
    const out = [];
    const L = s.L;
    for (let j = 0; j < order.length; j++) {
      const idx = order[j];
      if (d.score[idx] < minScore) break; // order is score-descending
      let ok = true;
      for (let f = 0; f < fixed.length; f += 2) {
        if (d.mat[idx * L + fixed[f]] !== fixed[f + 1]) { ok = false; break; }
      }
      if (!ok) continue;
      const key = L + ":" + idx;
      if (used.has(key) || (exclude && exclude.has(key))) continue;
      out.push(idx);
    }
    return Int32Array.from(out);
  }

  function presOf(k, dom) {
    const L = active[k].L;
    const mat = D[L] ? D[L].mat : null;
    const out = new Uint32Array(L);
    if (!mat) return out;
    for (let j = 0; j < dom.length; j++) {
      const off = dom[j] * L;
      for (let p = 0; p < L; p++) out[p] |= 1 << mat[off + p];
    }
    return out;
  }

  // Flattened crossings: crossF[k] = Int32Array [p, o, q, p, o, q, ...]
  const crossF = cross.map((list) => Int32Array.from(list.flat()));

  // AC-3 over copy-on-write arrays. Returns -1 if consistent, else wiped slot.
  function propagate(doms, pres, queue) {
    const q = Array.from(queue);
    const inq = new Uint8Array(active.length);
    for (const k of q) inq[k] = 1;
    while (q.length) {
      const k = q.pop();
      inq[k] = 0;
      const pk = pres[k];
      const cf = crossF[k];
      for (let c = 0; c < cf.length; c += 3) {
        const allowed = pk[cf[c]];
        const o = cf[c + 1], oq = cf[c + 2];
        if ((pres[o][oq] & ~allowed) === 0) continue;
        const L = active[o].L;
        const mat = D[L].mat;
        const dom = doms[o];
        if (scratch.length < dom.length) scratch = new Int32Array(dom.length * 2);
        let cnt = 0;
        for (let j = 0; j < dom.length; j++) {
          const idx = dom[j];
          if ((allowed >>> mat[idx * L + oq]) & 1) scratch[cnt++] = idx;
        }
        if (!cnt) return o;
        doms[o] = scratch.slice(0, cnt);
        pres[o] = presOf(o, doms[o]);
        if (!inq[o]) { q.push(o); inq[o] = 1; }
      }
    }
    return -1;
  }

  return { base, presOf, propagate };
}

const TIME = { time: true };
const BUDGET = { budget: true };

function solve(m) {
  const t0 = performance.now();
  const deadline = t0 + (m.timeMs || 8000);
  const maxResults = m.maxResults || 8;
  const floor = m.floor ?? 30;
  const P0 = prepare(m);
  if (P0.short.length) return { fills: [], note: "This section has an entry shorter than 3 letters. Fix the blocks first." };
  const region = new Set(m.region);
  const vars0 = [];
  P0.active.forEach((s, k) => { if (s.cells.some((i) => region.has(i))) vars0.push(k); });
  if (!vars0.length) return { fills: [], note: "No empty squares in the section. Drag across some empty squares first." };
  // Only the section's entries and the entries crossing them matter.
  const keepSet = new Set(vars0);
  for (const k of vars0) for (const [, o] of P0.cross[k]) keepSet.add(o);
  const P = subset(P0, [...keepSet].sort((a, b) => a - b));
  const vars = vars0.map((k) => P.map.get(k));
  const varSet = new Set(vars);
  const E = makeEngine(P, m.cells);
  const thresholds = [60, 55, 50, 45, 40, 35, 30, 25, 20, 15, 10, 5];

  function root(t, exclude) {
    const doms = P.active.map((s, k) => E.base(k, varSet.has(k) ? t : floor, exclude));
    for (let k = 0; k < doms.length; k++) if (!doms[k].length) return { dead: k };
    const pres = doms.map((d, k) => E.presOf(k, d));
    const dead = E.propagate(doms, pres, P.active.map((_, k) => k));
    if (dead >= 0) return { dead };
    return { doms, pres };
  }

  let rng = (m.seed || 12345) >>> 0;
  const rand = () => ((rng = (rng * 1664525 + 1013904223) >>> 0) / 4294967296);

  function dfs(doms, pres, ctx) {
    ctx.nodes++;
    if ((ctx.nodes & 15) === 0) {
      const now = performance.now();
      if (now > deadline) throw TIME;
      if (ctx.until && now > ctx.until) throw BUDGET;
    }
    if (ctx.nodes > ctx.budget) throw BUDGET;
    let best = -1, bn = Infinity;
    for (const k of vars) {
      const len = doms[k].length;
      if (len > 1 && len < bn) { bn = len; best = k; }
    }
    if (best < 0) {
      const seen = new Set();
      for (const k of vars) {
        const key = P.active[k].L + ":" + doms[k][0];
        if (seen.has(key)) return null;
        seen.add(key);
      }
      return doms;
    }
    let cand = doms[best];
    if (cand.length > ctx.branch) ctx.truncated = true;
    let order = Array.from(cand.subarray(0, ctx.branch));
    if (ctx.jitter && order.length > 1) {
      // mostly best-first, with some shuffling among the top choices
      const head = order.slice(0, 8).map((x, r) => [r + rand() * 6, x]).sort((a, b) => a[0] - b[0]).map((x) => x[1]);
      order = head.concat(order.slice(8));
    }
    const L = P.active[best].L;
    for (const idx of order) {
      const nd = doms.slice();
      const np = pres.slice();
      nd[best] = Int32Array.of(idx);
      np[best] = E.presOf(best, nd[best]);
      if (E.propagate(nd, np, [best]) >= 0) continue;
      const r = dfs(nd, np, ctx);
      if (r) return r;
    }
    return null;
  }

  const results = [];
  const keys = new Set();
  function record(doms) {
    const words = vars.map((k) => {
      const s = P.active[k];
      const idx = doms[k][0];
      return { cells: s.cells, dir: s.dir, word: wordAt(s.L, idx), score: D[s.L].score[idx], key: s.L + ":" + idx };
    });
    const sig = words.map((w) => w.key).sort().join(",");
    if (keys.has(sig)) return false;
    keys.add(sig);
    const scores = words.map((w) => w.score);
    results.push({
      words,
      min: Math.min(...scores),
      mean: scores.reduce((a, b) => a + b, 0) / scores.length,
    });
    return true;
  }

  function sorted() { return results.slice().sort((a, b) => b.min - a.min || b.mean - a.mean); }
  function stream(text) {
    postMessage({ type: "progress", id: m.id, text, fills: sorted().slice(0, maxResults) });
  }

  // One level: can every new entry score >= t? Returns "found", "none" (ruled
  // out completely) or "unknown" (ran out of its time slice).
  function attempt(t, share) {
    stream(`Looking for fills with every new entry ≥ ${t}…`);
    const R = root(t);
    if (R.dead !== undefined) return "none";
    const until = performance.now() + Math.max(400, (deadline - performance.now()) * share);
    for (let r = 0; r < 40 && performance.now() < until; r++) {
      const ctx = { nodes: 0, budget: 1500 * (1 + r), until, branch: r === 0 ? 1e9 : 40, jitter: r > 0, truncated: false };
      try {
        const sol = dfs(R.doms, R.pres, ctx);
        if (sol) { record(sol); stream(`Found a fill with every new entry ≥ ${t}…`); return "found"; }
        if (!ctx.truncated) return "none";
      } catch (e) {
        if (e === TIME) throw e;
        if (e !== BUDGET) throw e;
      }
    }
    return "unknown";
  }

  const status = {};
  let bestT = null;
  let timedOut = false;
  const start = Math.min(50, Math.max(floor, 5));
  try {
    status[start] = attempt(start, 0.35);
    if (status[start] === "found") {
      bestT = start;
      for (const t of thresholds.filter((x) => x > start).reverse()) { // 55, then 60
        status[t] = attempt(t, 0.3);
        if (status[t] !== "found") break;
        bestT = t;
      }
    } else {
      for (const t of thresholds.filter((x) => x < start)) {
        status[t] = attempt(t, 0.3);
        if (status[t] === "found") { bestT = t; break; }
      }
    }
    // alternatives at the best level: exclude one word of an earlier fill each time
    if (bestT !== null) {
      const exclude = new Set();
      let tries = 0;
      while (results.filter((f) => f.min >= bestT).length < maxResults && performance.now() < deadline && tries < 300) {
        tries++;
        const pool = results.filter((f) => f.min >= bestT);
        const prev = pool[Math.floor(rand() * pool.length)];
        const pick = rand() < 0.5
          ? prev.words.reduce((a, b) => (a.score <= b.score ? a : b))
          : prev.words[Math.floor(rand() * prev.words.length)];
        const ex = new Set(exclude);
        ex.add(pick.key);
        const R2 = root(bestT, ex);
        if (R2.dead !== undefined) continue;
        const ctx = { nodes: 0, budget: 3000, branch: 30, jitter: true, truncated: false };
        try {
          const sol = dfs(R2.doms, R2.pres, ctx);
          if (sol && record(sol)) {
            stream(`Found ${results.length} fills…`);
            if (exclude.size < 6 && rand() < 0.3) exclude.add(pick.key);
          }
        } catch (e) {
          if (e === TIME) throw e;
        }
      }
    }
  } catch (e) {
    if (e !== TIME) throw e;
    timedOut = true;
  }
  // proven best: every level above the best one was ruled out completely
  const provenBest = bestT !== null && thresholds.filter((t) => t > bestT).every((t) => status[t] === "none" || (status[t] === undefined && thresholds.some((u) => u > bestT && u < t && status[u] === "none")));
  const final = sorted();
  let note = "";
  if (!final.length) note = timedOut
    ? "No fill found in the time allowed. Try a smaller section, a longer time, or a lower floor."
    : "This section can't be filled with your word list as it stands. Change a locked entry or a block nearby.";
  return {
    fills: final.slice(0, maxResults),
    bestT,
    provenBest,
    timedOut,
    note,
    ms: Math.round(performance.now() - t0),
  };
}

// Words for one slot that keep its crossing entries fillable. Only the slot and
// the entries crossing it are checked, so a dead end elsewhere in the grid
// doesn't hide good words here; that dead end is reported separately.
function candidates(m) {
  const P0 = prepare(m);
  const target = m.slotCells.join(",");
  const k0 = P0.active.findIndex((s) => s.cells.join(",") === target);
  if (k0 < 0) return { words: [] };
  const floor = m.floor ?? 30;
  const keep = new Set([k0]);
  for (const [, o] of P0.cross[k0]) keep.add(o);
  const P = subset(P0, [...keep].sort((a, b) => a - b));
  const k = P.map.get(k0);
  const E = makeEngine(P, m.cells);
  const doms = P.active.map((s, j) => E.base(j, floor));
  const pres = doms.map((d, j) => E.presOf(j, d));
  const limit = m.limit || 20;
  const out = [];
  const L = P.active[k].L;
  const dom = doms[k];
  const t0 = performance.now();
  let checked = 0;
  for (let j = 0; j < dom.length && out.length < limit && checked < 600 && performance.now() - t0 < 1500; j++) {
    checked++;
    const nd = doms.slice(), np = pres.slice();
    nd[k] = Int32Array.of(dom[j]);
    np[k] = E.presOf(k, nd[k]);
    if (E.propagate(nd, np, [k]) < 0) out.push({ word: wordAt(L, dom[j]), score: D[L].score[dom[j]] });
  }
  // Is the grid as a whole still fillable? Report the entry where it runs dry.
  let dead = null;
  if (performance.now() - t0 < 1500) {
    const E0 = makeEngine(P0, m.cells);
    const d0 = P0.active.map((s, j) => E0.base(j, floor));
    let w = d0.findIndex((d) => !d.length);
    if (w < 0) {
      const p0 = d0.map((d, j) => E0.presOf(j, d));
      w = E0.propagate(d0, p0, P0.active.map((_, j) => j));
    }
    if (w >= 0) dead = { cells: P0.active[w].cells, dir: P0.active[w].dir };
  }
  return { words: out, total: dom.length, dead };
}

onmessage = (e) => {
  const m = e.data;
  try {
    if (m.type === "dict") {
      D = {};
      index = new Map();
      let count = 0;
      for (const [Ls, v] of Object.entries(m.lens)) {
        const L = +Ls;
        const score = new Int16Array(v.score);
        D[L] = { mat: new Uint8Array(v.mat), score, n: score.length, order: null };
        for (let i = 0; i < score.length; i++) index.set(wordAt(L, i), [L, i]);
        count += score.length;
      }
      postMessage({ type: "ready", count });
    } else if (m.type === "score") {
      const r = index.get(m.word);
      if (r) { D[r[0]].score[r[1]] = m.score; D[r[0]].order = null; }
    } else if (m.type === "solve") {
      postMessage({ type: "result", id: m.id, ...solve(m) });
    } else if (m.type === "cands") {
      postMessage({ type: "cands", id: m.id, ...candidates(m) });
    }
  } catch (err) {
    postMessage({ type: "error", id: m.id, message: String((err && err.message) || err) });
  }
};

// Small deterministic checks for fillworker.js (run by tests/test_fillworker.py).
const assert = require("assert");
const { loadWorker, dictFromList } = require("./worker_harness.js");
const W = loadWorker();
// 3x3 open grid in a 15x15 frame is awkward; use a 15x15 grid where only a
// 3x3 corner is open and everything else is blocks.
const n = 15;
const cells = Array(n * n).fill("#");
for (let r = 0; r < 3; r++) for (let c = 0; c < 3; c++) cells[r * n + c] = "";
// rows BAD/ORE/ATE, columns BOA/ART/DEE (60s); a weaker alternative square uses CAT etc.
const list = ["bad;60", "ore;60", "ate;60", "boa;60", "art;60", "dee;60", "zzz;10"].join("\n");
W.send({ type: "dict", lens: dictFromList(list) });
assert.equal(W.out.pop().type, "ready");
const region = [0, 1, 2, 15, 16, 17, 30, 31, 32];
W.send({ type: "solve", id: 1, n, cells, region, floor: 5, timeMs: 3000, maxResults: 5 });
const res = W.out.filter((m) => m.type === "result").pop();
assert.equal(res.fills.length, 1, JSON.stringify(res));
assert.equal(res.fills[0].min, 60);
assert.equal(res.bestT, 60);
assert.ok(res.provenBest);
const words = res.fills[0].words.map((w) => w.word).sort();
assert.deepEqual(words, ["ART", "ATE", "BAD", "BOA", "DEE", "ORE"]);
// banning a word makes the corner impossible
W.send({ type: "score", word: "DEE", score: -1 });
W.out.length = 0;
W.send({ type: "solve", id: 2, n, cells, region, floor: 5, timeMs: 3000, maxResults: 5 });
const res2 = W.out.filter((m) => m.type === "result").pop();
assert.equal(res2.fills.length, 0);
assert.ok(/can't be filled/.test(res2.note), res2.note);
// candidates respect crossings: with B in the corner, 1-Across is BAD or BOA (the transposed square)
cells[0] = "B";
W.send({ type: "score", word: "DEE", score: 60 });
W.send({ type: "cands", id: 3, n, cells, slotCells: [0, 1, 2], floor: 5, limit: 5 });
const c = W.out.filter((m) => m.type === "cands").pop();
assert.deepEqual(c.words.map((w) => w.word).sort(), ["BAD", "BOA"]);
console.log("fillworker ok");

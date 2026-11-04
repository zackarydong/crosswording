// Load fillworker.js in Node and drive it like the page does.
const fs = require("fs"), vm = require("vm"), path = require("path");
function loadWorker() {
  const out = [];
  const ctx = { postMessage: (m) => out.push(m), performance, console, Int32Array, Uint32Array, Uint8Array, Int16Array, Map, Set, Math, String, Array, Object };
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(path.join(__dirname, "..", "fillworker.js"), "utf8"), ctx);
  return { send: (m) => ctx.onmessage({ data: m }), out };
}
function dictFromList(text) {
  const by = {};
  for (const ln of text.split(/\r?\n/)) {
    const k = ln.lastIndexOf(";"); if (k < 0) continue;
    const w = ln.slice(0, k).toUpperCase().replace(/[^A-Z]/g, ""); const s = parseInt(ln.slice(k + 1), 10);
    if (w.length < 3 || isNaN(s) || s < 0) continue;
    (by[w.length] = by[w.length] || []).push([w, s]);
  }
  const lens = {};
  for (const [L, items] of Object.entries(by)) {
    const mat = new Uint8Array(items.length * L), sc = new Int16Array(items.length);
    items.forEach(([w, s], i) => { for (let p = 0; p < L; p++) mat[i * L + p] = w.charCodeAt(p) - 65; sc[i] = s; });
    lens[L] = { mat: mat.buffer, score: sc.buffer };
  }
  return lens;
}
module.exports = { loadWorker, dictFromList };

/* Fill grid tab: grid editor + section fill suggestions (search runs in fillworker.js). */
(() => {
  const N = 15;
  const $ = (id) => document.getElementById(id);
  const WLG = window.WLG;
  const EXAMPLE_ROWS = [
    ".......##......", "........#......", "........#......", "....#..........", "###VIBECHECK###",
    "...........#...", ".....##...#....", ".....G###......", "....#E..##.....", "...#BOURGEOISIE",
    "###..C......###", ".....A....#....", ".....C#........", ".....H#........", ".....E##.......",
  ];
  const TIERS = [["Great", 60], ["Good", 50], ["Fair", 40], ["Weak", 25], ["Junk", 10], ["Remove", -1]];
  const GRID_KEY = "wlg.studio.grid.v1";

  let cells = [];
  let cursor = 0, dir = "A";
  let region = new Set();
  let results = [], previewIdx = -1;
  let undoStack = [];
  let worker = null, workerReady = false, reqId = 0, running = 0, candReq = 0;
  let downloads = null;

  // ----- grid state ------------------------------------------------------------
  function fromRows(rows) {
    return rows.join("").split("").map((ch) => ({ b: ch === "#", ch: /[A-Z]/.test(ch) ? ch : "", src: /[A-Z]/.test(ch) ? "user" : "" }));
  }
  function toText() {
    const out = [];
    for (let r = 0; r < N; r++) out.push(cells.slice(r * N, r * N + N).map((c) => (c.b ? "#" : c.ch || ".")).join(""));
    return out.join("\n");
  }
  function save() { try { localStorage.setItem(GRID_KEY, JSON.stringify(cells)); } catch {} }
  function load() {
    try { const s = JSON.parse(localStorage.getItem(GRID_KEY) || "null"); if (Array.isArray(s) && s.length === N * N) return s; } catch {}
    return null;
  }
  function snapshot() { undoStack.push(JSON.stringify(cells)); if (undoStack.length > 60) undoStack.shift(); }
  function undo() {
    const s = undoStack.pop();
    if (!s) return toast("Nothing to undo.");
    cells = JSON.parse(s); results = []; previewIdx = -1; save(); renderAll();
  }

  // Parse pasted grids: plain rows ("..#.."), gridfinder's numbered ASCII, or letters.
  function parsePasted(text) {
    const rows = [];
    for (let line of text.split(/\r?\n/)) {
      line = line.replace(/\t/g, " ").trimEnd();
      if (!line.trim()) continue;
      let toks = line.trim().split(/\s+/);
      if (toks.length > 1) {
        if (toks.every((t) => /^\d+$/.test(t))) continue; // column header
        if (/^\d+$/.test(toks[0]) && toks.length === N + 1) toks = toks.slice(1);
        if (toks.length === N && toks.every((t) => t.length === 1)) { rows.push(toks.join("")); continue; }
        toks = [toks.join("")];
      }
      const t = toks[0].replace(/^\d+/, "");
      if (t.length === N && /^[#.A-Za-z_\-?]+$/.test(t)) rows.push(t);
    }
    if (rows.length !== N) throw new Error(`Found ${rows.length} grid rows; expected ${N}. Use # for blocks and . for empty squares.`);
    return rows.map((r) => r.toUpperCase().replace(/[_\-?]/g, "."));
  }
  function fromIpuz(obj) {
    const p = obj.puzzle, s = obj.solution;
    if (!Array.isArray(p) || p.length !== N) throw new Error("Only 15x15 .ipuz files are supported.");
    const rows = [];
    for (let r = 0; r < N; r++) {
      let row = "";
      for (let c = 0; c < N; c++) {
        const cell = p[r][c];
        const blk = cell === "#" || cell === null || (cell && typeof cell === "object" && cell.cell === "#");
        const sol = s && s[r] && s[r][c];
        const letter = typeof sol === "string" && /^[A-Za-z]$/.test(sol) ? sol.toUpperCase() : sol && typeof sol === "object" && sol.value ? String(sol.value).toUpperCase() : "";
        row += blk ? "#" : /^[A-Z]$/.test(letter) ? letter : ".";
      }
      rows.push(row);
    }
    return rows;
  }

  function slotAt(i, d) {
    if (cells[i].b) return [];
    const r = Math.floor(i / N), c = i % N, out = [];
    if (d === "A") { let a = c; while (a > 0 && !cells[r * N + a - 1].b) a--; for (let x = a; x < N && !cells[r * N + x].b; x++) out.push(r * N + x); }
    else { let a = r; while (a > 0 && !cells[(a - 1) * N + c].b) a--; for (let y = a; y < N && !cells[y * N + c].b; y++) out.push(y * N + c); }
    return out;
  }
  function numbering() {
    const nums = new Map();
    let k = 0;
    for (let i = 0; i < N * N; i++) {
      if (cells[i].b) continue;
      const r = Math.floor(i / N), c = i % N;
      const acr = (c === 0 || cells[i - 1].b) && c + 1 < N && !cells[i + 1].b;
      const dwn = (r === 0 || cells[i - N].b) && r + 1 < N && !cells[i + N].b;
      if (acr || dwn) nums.set(i, ++k);
    }
    return nums;
  }
  function labelOf(slotCells, d, nums) {
    return `${nums.get(slotCells[0]) || "?"}-${d === "A" ? "Across" : "Down"}`;
  }

  // ----- rendering -------------------------------------------------------------
  function previewMap() {
    const m = new Map();
    const f = results[previewIdx];
    if (f) for (const w of f.words) w.cells.forEach((i, p) => { if (!cells[i].ch) m.set(i, w.word[p]); });
    return m;
  }
  function renderGrid() {
    const board = $("board");
    board.replaceChildren();
    const nums = numbering();
    const cur = new Set(slotAt(cursor, dir));
    const pv = previewMap();
    for (let i = 0; i < N * N; i++) {
      const c = cells[i];
      const d = document.createElement("div");
      d.className = "cell";
      d.dataset.i = i;
      if (c.b) d.classList.add("block");
      else {
        if (region.has(i)) d.classList.add("region");
        if (cur.has(i)) d.classList.add("entry");
        if (i === cursor) d.classList.add("cursor");
        if (nums.has(i)) { const s = document.createElement("small"); s.textContent = nums.get(i); d.append(s); }
        const span = document.createElement("span");
        if (c.ch) { span.textContent = c.ch; span.className = c.src === "fill" ? "fillch" : "userch"; }
        else if (pv.has(i)) { span.textContent = pv.get(i); span.className = "previewch"; }
        d.append(span);
      }
      board.append(d);
    }
  }
  function renderSection() {
    const empty = [...region].filter((i) => !cells[i].b && !cells[i].ch).length;
    const info = $("sectionInfo");
    if (!region.size) info.textContent = "No section chosen. Drag across the squares you want filled.";
    else info.textContent = `${region.size} squares selected, ${empty} empty.`;
    $("suggestBtn").disabled = !empty || !!running;
    $("cancelBtn").hidden = !running;
    const dict = WLG.isExample() ? "the tiny example list (open your word list at the top first)" : `${WLG.fileName()} with your grades`;
    $("dictInfo").textContent = `Using ${dict}.`;
  }
  function chipClass(s) { return s === -1 ? "chip del" : "chip s" + (s >= 60 ? 60 : s >= 50 ? 50 : s >= 40 ? 40 : s >= 25 ? 25 : 10); }
  function renderResults() {
    const box = $("results");
    box.replaceChildren();
    if (!results.length) {
      const p = document.createElement("p");
      p.className = "empty-note";
      p.textContent = running ? "Searching\u2026" : "Fills appear here, best first. Each one is ranked by its weakest new entry, then its average.";
      box.append(p);
      return;
    }
    const nums = numbering();
    results.forEach((f, k) => {
      const card = document.createElement("div");
      card.className = "fillcard" + (k === previewIdx ? " on" : "");
      const head = document.createElement("div");
      head.className = "fillhead";
      const worst = f.words.reduce((a, b) => (a.score <= b.score ? a : b));
      const h = document.createElement("span");
      h.innerHTML = "";
      h.append(document.createTextNode(`#${k + 1} \u00b7 weakest `));
      const wc = document.createElement("span"); wc.className = chipClass(worst.score); wc.textContent = `${worst.word} ${worst.score}`;
      h.append(wc, document.createTextNode(` \u00b7 avg ${f.mean.toFixed(1)}`));
      const use = document.createElement("button");
      use.type = "button"; use.textContent = "Use this fill";
      use.addEventListener("click", () => applyFill(k));
      head.append(h, use);
      const list = document.createElement("div");
      list.className = "fillwords";
      for (const w of f.words.slice().sort((a, b) => a.score - b.score)) {
        const it = document.createElement("span");
        it.className = "fw";
        const lab = document.createElement("span"); lab.className = "lab"; lab.textContent = labelOf(w.cells, w.dir, nums);
        const wd = document.createElement("b"); wd.textContent = w.word;
        const sc = document.createElement("span"); sc.className = chipClass(w.score); sc.textContent = w.score;
        const ban = document.createElement("button");
        ban.type = "button"; ban.className = "ban"; ban.title = `Remove ${w.word} from your list`; ban.textContent = "\u00d7";
        ban.setAttribute("aria-label", `Remove ${w.word} from your list`);
        ban.addEventListener("click", (e) => { e.stopPropagation(); banWord(w.word); });
        it.append(lab, wd, sc, ban);
        list.append(it);
      }
      card.append(head, list);
      card.addEventListener("mouseenter", () => { previewIdx = k; renderGrid(); markCards(); });
      card.addEventListener("focusin", () => { previewIdx = k; renderGrid(); markCards(); });
      box.append(card);
    });
  }
  function markCards() {
    [...$("results").children].forEach((c, k) => c.classList.toggle("on", k === previewIdx));
  }
  function renderEntry() {
    const slot = slotAt(cursor, dir);
    const nums = numbering();
    const box = $("entryBox");
    box.replaceChildren();
    if (slot.length < 2) { $("entryLabel2").textContent = "Current entry"; box.textContent = "Click a white square."; return; }
    $("entryLabel2").textContent = `${labelOf(slot, dir, nums)} \u00b7 ${slot.length} letters`;
    const pat = slot.map((i) => cells[i].ch || ".").join("");
    const row = document.createElement("div");
    row.className = "entryrow";
    const code = document.createElement("code"); code.className = "pat"; code.textContent = pat;
    row.append(code);
    if (!pat.includes(".")) {
      const s = WLG.score(pat);
      const chip = document.createElement("span");
      chip.className = s === null ? "chip orig" : chipClass(s);
      chip.textContent = s === null ? "not in list" : s;
      row.append(chip);
      box.append(row);
      const g = document.createElement("div");
      g.className = "gradebtns";
      for (const [lab, sc] of TIERS) {
        const b = document.createElement("button");
        b.type = "button"; b.textContent = sc === -1 ? lab : `${lab} ${sc}`;
        b.addEventListener("click", () => { WLG.setGrade(pat, sc); toast(sc === -1 ? `Removed ${pat} from your list` : `${pat} graded ${sc}`); renderEntry(); });
        g.append(b);
      }
      box.append(g);
      return;
    }
    box.append(row);
    const list = document.createElement("ul");
    list.className = "list cands";
    const li = document.createElement("li"); li.className = "empty-note"; li.textContent = workerReady ? "Finding words that fit with the crossings\u2026" : "Loading word list\u2026";
    list.append(li);
    box.append(list);
    requestCands(slot);
  }
  function renderAll() { renderGrid(); renderSection(); renderResults(); renderEntry(); }

  // ----- editing -----------------------------------------------------------------
  function move(dr, dc) {
    let r = Math.floor(cursor / N) + dr, c = (cursor % N) + dc;
    while (r >= 0 && r < N && c >= 0 && c < N) {
      if (!cells[r * N + c].b) { cursor = r * N + c; return; }
      r += dr; c += dc;
    }
  }
  function step(back) {
    const slot = slotAt(cursor, dir);
    const k = slot.indexOf(cursor);
    const nk = back ? k - 1 : k + 1;
    if (nk >= 0 && nk < slot.length) cursor = slot[nk];
  }
  function changed() { results = []; previewIdx = -1; save(); renderAll(); }
  function onKey(e) {
    if (e.metaKey || e.ctrlKey) {
      if (e.key === "z" || e.key === "Z") { e.preventDefault(); undo(); }
      return;
    }
    const k = e.key;
    if (/^[a-zA-Z]$/.test(k)) {
      e.preventDefault();
      if (cells[cursor].b) return;
      snapshot();
      cells[cursor].ch = k.toUpperCase(); cells[cursor].src = "user";
      step(false); changed();
    } else if (k === "Backspace") {
      e.preventDefault(); snapshot();
      if (!cells[cursor].ch) step(true);
      cells[cursor].ch = ""; cells[cursor].src = ""; changed();
    } else if (k === "Delete") {
      e.preventDefault(); snapshot(); cells[cursor].ch = ""; cells[cursor].src = ""; changed();
    } else if (k === ".") {
      e.preventDefault(); snapshot();
      const j = N * N - 1 - cursor;
      const b = !cells[cursor].b;
      for (const x of new Set([cursor, j])) { cells[x].b = b; cells[x].ch = ""; cells[x].src = ""; region.delete(x); }
      changed();
    } else if (k === " ") { e.preventDefault(); dir = dir === "A" ? "D" : "A"; renderGrid(); renderEntry(); }
    else if (k.startsWith("Arrow")) {
      e.preventDefault();
      const map = { ArrowLeft: [0, -1, "A"], ArrowRight: [0, 1, "A"], ArrowUp: [-1, 0, "D"], ArrowDown: [1, 0, "D"] };
      const [dr, dc, d] = map[k];
      if (dir !== d) dir = d; else move(dr, dc);
      renderGrid(); renderEntry();
    } else if (k === "Escape") { region.clear(); renderGrid(); renderSection(); }
  }

  // pointer: click = cursor, drag = choose a rectangular section
  let dragStart = -1, dragging = false;
  function cellFromEvent(e) {
    const el = document.elementFromPoint(e.clientX, e.clientY);
    const c = el && el.closest && el.closest(".cell");
    return c ? +c.dataset.i : -1;
  }
  function rect(a, b) {
    const r1 = Math.min(Math.floor(a / N), Math.floor(b / N)), r2 = Math.max(Math.floor(a / N), Math.floor(b / N));
    const c1 = Math.min(a % N, b % N), c2 = Math.max(a % N, b % N);
    const s = new Set();
    for (let r = r1; r <= r2; r++) for (let c = c1; c <= c2; c++) if (!cells[r * N + c].b) s.add(r * N + c);
    return s;
  }
  function bindBoard() {
    const board = $("board");
    board.addEventListener("pointerdown", (e) => {
      const i = cellFromEvent(e);
      if (i < 0) return;
      dragStart = i; dragging = false;
      board.setPointerCapture(e.pointerId);
      board.focus({ preventScroll: true });
    });
    board.addEventListener("pointermove", (e) => {
      if (dragStart < 0) return;
      const i = cellFromEvent(e);
      if (i < 0) return;
      if (i !== dragStart || dragging) {
        dragging = true;
        region = rect(dragStart, i);
        renderGrid(); renderSection();
      }
    });
    board.addEventListener("pointerup", (e) => {
      if (dragStart < 0) return;
      const i = dragStart;
      if (!dragging) {
        if (cells[i].b) { dragStart = -1; return; }
        if (i === cursor) dir = dir === "A" ? "D" : "A";
        cursor = i;
        renderGrid(); renderEntry();
      } else { results = []; previewIdx = -1; renderResults(); }
      dragStart = -1;
    });
    board.addEventListener("keydown", onKey);
    board.addEventListener("mouseleave", () => { if (previewIdx >= 0 && !results.length) { previewIdx = -1; renderGrid(); } });
  }

  // ----- worker --------------------------------------------------------------------
  function buildLens() {
    const words = WLG.words(), scores = WLG.scores(), edits = WLG.edits(), index = WLG.index();
    const by = new Map();
    const add = (w, s) => {
      if (s < 0 || w.length < 3 || w.length > N) return;
      let a = by.get(w.length); if (!a) by.set(w.length, (a = []));
      a.push(w, s);
    };
    const seen = new Set();
    for (let i = 0; i < words.length; i++) {
      const w = words[i];
      if (seen.has(w)) continue; seen.add(w);
      add(w, w in edits ? edits[w] : scores[i]);
    }
    for (const w of Object.keys(edits)) if (!index.has(w)) add(w, edits[w]);
    const lens = {}, transfer = [];
    for (const [L, a] of by) {
      const n = a.length / 2;
      const mat = new Uint8Array(n * L), sc = new Int16Array(n);
      for (let j = 0; j < n; j++) {
        const w = a[2 * j];
        for (let p = 0; p < L; p++) mat[j * L + p] = w.charCodeAt(p) - 65;
        sc[j] = a[2 * j + 1];
      }
      lens[L] = { mat: mat.buffer, score: sc.buffer };
      transfer.push(mat.buffer, sc.buffer);
    }
    return { lens, transfer };
  }
  function startWorker() {
    try { worker = new Worker("fillworker.js"); }
    catch { $("fillStatus").textContent = "This browser can't run the fill search here."; return; }
    workerReady = false;
    worker.onmessage = onWorker;
    worker.onerror = () => { $("fillStatus").textContent = "The fill search stopped unexpectedly. Reload the page to try again."; running = 0; renderSection(); };
    const { lens, transfer } = buildLens();
    worker.postMessage({ type: "dict", lens }, transfer);
  }
  let resendT = 0;
  function resendDict() { clearTimeout(resendT); resendT = setTimeout(() => { if (worker) worker.terminate(); running = 0; startWorker(); renderSection(); }, 300); }
  function onWorker(e) {
    const m = e.data;
    if (m.type === "ready") { workerReady = true; $("fillStatus").textContent = `Ready: ${m.count.toLocaleString()} words loaded.`; renderEntry(); }
    else if (m.type === "progress" && m.id === running) {
      $("fillStatus").textContent = m.text;
      if (m.fills) { results = m.fills; renderResults(); }
    } else if (m.type === "result" && m.id === running) {
      running = 0;
      results = m.fills;
      previewIdx = results.length ? 0 : -1;
      let msg = m.note || "";
      if (m.fills.length) {
        msg = `${m.fills.length} fill${m.fills.length > 1 ? "s" : ""} in ${(m.ms / 1000).toFixed(1)}s. ` +
          (m.provenBest ? `No fill exists where every new entry scores above ${m.bestT}.` :
            m.bestT !== null ? `Best level found: every new entry \u2265 ${m.bestT}${m.timedOut ? " (more time might find better)" : ""}.` : "");
      }
      $("fillStatus").textContent = msg;
      renderAll();
    } else if (m.type === "cands" && m.id === candReq) {
      const list = document.querySelector("#entryBox .cands");
      if (!list) return;
      list.replaceChildren();
      if (!m.words.length) { const li = document.createElement("li"); li.className = "empty-note"; li.textContent = "No word fits with the current crossings."; list.append(li); return; }
      for (const w of m.words) {
        const li = document.createElement("li");
        const b = document.createElement("button");
        b.type = "button"; b.className = "candbtn"; b.textContent = w.word; b.title = "Put this word in the grid";
        b.addEventListener("click", () => placeWord(w.word));
        const right = document.createElement("span"); right.className = "row";
        const sc = document.createElement("span"); sc.className = chipClass(w.score); sc.textContent = w.score;
        const ban = document.createElement("button"); ban.type = "button"; ban.className = "ban"; ban.textContent = "\u00d7";
        ban.setAttribute("aria-label", `Remove ${w.word} from your list`);
        ban.addEventListener("click", () => banWord(w.word));
        right.append(sc, ban);
        li.append(b, right);
        list.append(li);
      }
      const li = document.createElement("li"); li.className = "empty-note";
      li.textContent = `Top ${m.words.length} of ${m.total.toLocaleString()} matching words that keep every crossing fillable.`;
      list.append(li);
    } else if (m.type === "error") {
      if (m.id === running) running = 0;
      $("fillStatus").textContent = "Search error: " + m.message;
      renderSection();
    }
  }
  function cellsPayload() { return cells.map((c) => (c.b ? "#" : c.ch || "")); }
  function suggest() {
    if (!worker || !workerReady) return toast("The word list is still loading.");
    const empty = [...region].filter((i) => !cells[i].ch);
    if (!empty.length) return toast("Choose a section with empty squares first.");
    running = ++reqId;
    results = []; previewIdx = -1;
    $("fillStatus").textContent = "Starting\u2026";
    worker.postMessage({
      type: "solve", id: running, n: N, cells: cellsPayload(), region: [...region],
      floor: +$("floorSel").value, timeMs: +$("timeSel").value * 1000, maxResults: 8, seed: (Date.now() % 100000) + 1,
    });
    renderSection(); renderResults();
  }
  function cancel() {
    if (!running) return;
    running = 0;
    if (worker) worker.terminate();
    $("fillStatus").textContent = "Stopped. Showing what was found so far.";
    startWorker();
    renderAll();
  }
  let candT = 0;
  function requestCands(slot) {
    clearTimeout(candT);
    candT = setTimeout(() => {
      if (!worker || !workerReady || running) return;
      candReq = ++reqId;
      worker.postMessage({ type: "cands", id: candReq, n: N, cells: cellsPayload(), slotCells: slot, floor: +$("floorSel").value, limit: 15 });
    }, 200);
  }

  // ----- actions ---------------------------------------------------------------------
  function applyFill(k) {
    const f = results[k];
    if (!f) return;
    snapshot();
    for (const w of f.words) w.cells.forEach((i, p) => { if (!cells[i].ch) { cells[i].ch = w.word[p]; cells[i].src = "fill"; } });
    toast("Fill placed. Blue letters came from the filler; type over any of them.");
    changed();
  }
  function placeWord(word) {
    const slot = slotAt(cursor, dir);
    if (slot.length !== word.length) return;
    snapshot();
    slot.forEach((i, p) => { cells[i].ch = word[p]; cells[i].src = "user"; });
    changed();
  }
  function banWord(word) {
    WLG.setGrade(word, -1);
    results = results.filter((f) => !f.words.some((w) => w.word === word));
    if (previewIdx >= results.length) previewIdx = results.length - 1;
    toast(`Removed ${word} from your list. It won't be suggested again.`);
    renderAll();
  }

  let toastT = 0;
  function toast(msg) { const t = $("toast"); t.textContent = msg; t.hidden = false; clearTimeout(toastT); toastT = setTimeout(() => (t.hidden = true), 2600); }

  // ----- wiring --------------------------------------------------------------------------
  function init() {
    cells = load() || fromRows(EXAMPLE_ROWS);
    cursor = cells.findIndex((c) => !c.b && !c.ch);
    if (cursor < 0) cursor = 0;
    // default section: the top-left corner
    region = rect(0, 3 * N + 7);
    bindBoard();
    $("suggestBtn").addEventListener("click", suggest);
    $("cancelBtn").addEventListener("click", cancel);
    $("allEmptyBtn").addEventListener("click", () => { region = new Set(cells.map((c, i) => (!c.b && !c.ch ? i : -1)).filter((i) => i >= 0)); results = []; renderAll(); });
    $("clearSecBtn").addEventListener("click", () => { region.clear(); results = []; renderAll(); });
    $("undoGridBtn").addEventListener("click", undo);
    $("clearFillBtn").addEventListener("click", () => { snapshot(); cells.forEach((c) => { if (c.src === "fill") { c.ch = ""; c.src = ""; } }); changed(); });
    $("clearAllBtn").addEventListener("click", () => { snapshot(); cells.forEach((c) => { c.ch = ""; c.src = ""; }); changed(); });
    $("pasteBtn").addEventListener("click", () => { $("pastePanel").hidden = false; $("pasteText").focus(); });
    $("pasteCancel").addEventListener("click", () => { $("pastePanel").hidden = true; });
    $("pasteLoad").addEventListener("click", () => {
      try {
        const rows = parsePasted($("pasteText").value);
        snapshot(); cells = fromRows(rows); region.clear(); $("pastePanel").hidden = true; $("pasteText").value = "";
        changed(); toast("Grid loaded.");
      } catch (err) { toast(err.message); }
    });
    $("ipuzInput").addEventListener("change", async (e) => {
      const f = e.target.files && e.target.files[0];
      if (!f) return;
      try { snapshot(); cells = fromRows(fromIpuz(JSON.parse(await f.text()))); region.clear(); changed(); toast(`Loaded ${f.name}.`); }
      catch (err) { toast("Couldn't read that file: " + err.message); }
      e.target.value = "";
    });
    $("copyGridBtn").addEventListener("click", () => {
      navigator.clipboard.writeText(toText()).then(() => toast("Grid copied as text.")).catch(() => { $("pastePanel").hidden = false; $("pasteText").value = toText(); $("pasteText").select(); toast("Copy isn't allowed here; the grid is selected in the box below."); });
    });
    $("saveIpuzBtn").addEventListener("click", async () => {
      if (!downloads) return toast("Saving files isn't available here. Use Copy grid instead.");
      const nums = numbering();
      const puzzle = [], solution = [];
      for (let r = 0; r < N; r++) {
        puzzle.push(cells.slice(r * N, r * N + N).map((c, j) => (c.b ? "#" : nums.get(r * N + j) || 0)));
        solution.push(cells.slice(r * N, r * N + N).map((c) => (c.b ? "#" : c.ch || null)));
      }
      const ipuz = { version: "http://ipuz.org/v2", kind: ["http://ipuz.org/crossword#1"], dimensions: { width: N, height: N }, block: "#", empty: 0, puzzle, solution };
      try { await downloads.save({ filename: "grid-ipuz.json", data: JSON.stringify(ipuz, null, 1) }); toast("Saved. Rename it to .ipuz to import it elsewhere."); }
      catch (err) { toast(err && err.code === "declined" ? "Save cancelled." : "Couldn't save the file here."); }
    });
    $("floorSel").addEventListener("change", () => renderEntry());
    WLG.on("dict", () => { resendDict(); renderSection(); });
    WLG.on("grade", (w, s) => {
      if (!worker) return;
      if (WLG.index().has(w)) worker.postMessage({ type: "score", word: w, score: s });
      else resendDict();
    });
    (async () => { try { downloads = await (window.claude && window.claude.use ? window.claude.use("downloads") : null); } catch { downloads = null; } })();
    startWorker();
    renderAll();
  }
  init();
})();

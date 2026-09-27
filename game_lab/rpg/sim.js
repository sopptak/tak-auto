/*
 * CHOICE100 RPG 자동 플레이어(6-67) - 주몽 Vertical Slice를 끝까지 돌려 불변식·결과 분포를 본다. stdout만(실제 플레이 데이터 아님).
 *   node sim.js [korea.json] [판 수]
 */
"use strict";
const fs = require("fs");
const path = require("path");
const { Game } = require("./engine.js");
const Board = require("../board/engine.js");

function rng(seed) {
  let s = seed >>> 0 || 1;
  return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 2 ** 32);
}

function playBoard(g, r, acc) {
  const b = g.boardGame();
  for (let k = 0; k < 50 && b.state.phase !== "end"; k++) {
    const ph = b.state.phase;
    if (ph === "quiz") { const q = b.quiz(); b.answer(r() < acc ? q.correct : (q.correct + 1) % 4); }
    else if (ph === "parity") b.declare(r() < 0.5 ? "odd" : "even");
    else if (ph === "roll") b.roll();
    else if (ph === "steer") { const o = b.steerOptions(); b.steerTo(o[Math.floor(r() * o.length)].steps); }
    else if (ph === "cell") {
      if (b.cell().type === "QUIZ") { const q = b.cellQuiz(); b.answerCellQuiz(r() < acc ? q.correct : (q.correct + 2) % 4); }
      else { const opts = b.cellOptions().filter((o) => o.enabled); b.act(opts[Math.floor(r() * opts.length)].choice.id); }
    } else if (ph === "turn_end") b.nextTurn();
  }
  return g.finishBoard();
}

function play(data, { acc = 0.5, seed = 1 } = {}) {
  const r = rng(seed);
  const g = new Game(data, { BoardGame: Board.Game, rng: r });
  g.completeMain("m1");
  g.passGate("gate_joljbon");
  g.startStory("jumong");
  const trace = [];
  for (let k = 0; k < 100 && g.state.current; k++) {
    const s = g.step();
    let out;
    if (s.type === "quiz") { const q = g.quiz(); out = g.advance(r() < acc ? q.correct : (q.correct + 1 + Math.floor(r() * 3)) % 4); }
    else if (s.type === "choice") { const opts = s.options.filter((o) => g.optionEnabled(o)); out = g.advance(opts[Math.floor(r() * opts.length)].id); }
    else if (s.type === "board") { playBoard(g, r, acc); out = g.advance(); }
    else out = g.advance();
    trace.push(out);
    for (const [k2, v] of Object.entries(g.state.stats)) if (!Number.isFinite(v) || v < 0) throw new Error(`불가능한 상태 ${k2}=${v}`);
  }
  if (g.state.current) throw new Error("끝나지 않음");
  return { g, trace };
}

function simulate(data, n = 100) {
  const rows = [];
  let seed = 11;
  for (const acc of [0, 0.5, 1]) for (let i = 0; i < n; i++) rows.push({ acc, ...play(data, { acc, seed: seed++ }) });
  return rows;
}

function summarize(rows) {
  const by = {};
  for (const x of rows) {
    const k = `acc${x.acc}`;
    const b = (by[k] = by[k] || { n: 0, level: {}, exp: [], samguk: 0, companion: 0, bow: 0, policy: 0, songyang: {} });
    const st = x.g.state;
    b.n += 1;
    b.level[st.level] = (b.level[st.level] || 0) + 1;
    b.exp.push(st.stats.exp);
    if (st.regions.includes("samguk")) b.samguk += 1;
    if (st.companions.includes("jumong")) b.companion += 1;
    if (st.items.includes("jumong_bow")) b.bow += 1;
    if (st.policies.includes("jindae")) b.policy += 1;
    b.songyang[st.relations.songyang] = (b.songyang[st.relations.songyang] || 0) + 1;
  }
  for (const b of Object.values(by)) { b.exp.sort((a, c) => a - c); b.exp = { min: b.exp[0], median: b.exp[b.exp.length >> 1], max: b.exp[b.exp.length - 1] }; }
  return { runs: rows.length, by };
}

module.exports = { play, simulate, summarize, rng };

if (require.main === module) {
  const file = process.argv[2] || path.join(__dirname, "korea", "korea.json");
  const data = JSON.parse(fs.readFileSync(file, "utf8"));
  console.log(JSON.stringify(summarize(simulate(data, Number(process.argv[3]) || 100)), null, 1));
}

/*
 * CHOICE100 BOARD 자동 플레이어(6-66) - 밸런스·확률 점검용. 결과는 stdout에만(실제 플레이 데이터 아님).
 *   node sim.js [world.json] [판 수/전략]
 * 전략 = 퀴즈 정답률(acc) × 칸 선호(prefer) × 칸 행동(act). 주사위는 실제 무작위(시드 rng)로 굴린다.
 */
"use strict";
const fs = require("fs");
const path = require("path");
const { Game } = require("./engine.js");

function rng(seed) {
  let s = seed >>> 0 || 1;
  return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 2 ** 32);
}

const STRATEGIES = {
  trader: { prefer: ["TRADE", "CITY"], act: (opts) => opts.find((o) => o.enabled && o.choice.sell) || opts.find((o) => o.enabled && o.choice.buy) || null },
  explorer: { prefer: ["EXPLORE", "BONUS"], act: (opts) => opts.find((o) => o.enabled && o.choice.id === "explore") || null },
  scholar: { prefer: ["QUIZ", "CITY"], act: (opts) => opts.find((o) => o.enabled && o.choice.id === "lib") || null },
  random: { prefer: [], act: () => null },
};

function play(data, { acc = 0.6, strategy = "random", seed = 1 } = {}) {
  const r = rng(seed);
  const g = new Game(data, r);
  const st = STRATEGIES[strategy];
  const t = { answers: 0, correct: 0, declared: 0, hits: 0, steered: 0, rolls: [] };
  for (let guard = 0; guard < 500 && g.state.phase !== "end"; guard++) {
    const ph = g.state.phase;
    if (ph === "quiz") {
      const q = g.quiz();
      const right = r() < acc;
      const out = g.answer(right ? q.correct : (q.correct + 1 + Math.floor(r() * 3)) % 4);
      t.answers += 1;
      if (out.correct) t.correct += 1;
    } else if (ph === "parity") {
      const out = g.declare(r() < 0.5 ? "odd" : "even");
      t.declared += 1;
      t.rolls.push(out.roll);
      if (out.hit) t.hits += 1;
    } else if (ph === "roll") {
      t.rolls.push(g.roll().roll);
    } else if (ph === "steer") {
      const opts = g.steerOptions();
      const best = opts.find((o) => st.prefer.includes(o.cell.type)) || opts[Math.floor(r() * opts.length)];
      g.steerTo(best.steps);
      t.steered += 1;
    } else if (ph === "cell") {
      if (g.cell().type === "QUIZ") {
        const q = g.cellQuiz();
        g.answerCellQuiz(r() < acc ? q.correct : (q.correct + 1) % 4);
      } else {
        const opts = g.cellOptions();
        const pick = st.act(opts) || opts.filter((o) => o.enabled)[Math.floor(r() * opts.filter((o) => o.enabled).length)];
        g.act(pick.choice.id);
      }
    } else if (ph === "turn_end") {
      g.nextTurn();
    }
    for (const [k, v] of Object.entries(g.state.vars)) if (!Number.isFinite(v) || v < 0) throw new Error(`불가능한 상태 ${k}=${v}`);
    if (g.state.pos < 0 || g.state.pos >= data.board.length) throw new Error("보드 밖");
  }
  if (g.state.phase !== "end") throw new Error("끝나지 않음");
  return { game: g, t, ending: g.ending() };
}

function simulate(data, per = 100) {
  const rows = [];
  let seed = 7;
  for (const strategy of Object.keys(STRATEGIES)) for (const acc of [0.3, 0.6, 0.9]) for (let i = 0; i < per; i++) rows.push({ strategy, acc, ...play(data, { acc, strategy, seed: seed++ }) });
  return rows;
}

function summarize(rows) {
  const endings = {}, by = {};
  let declared = 0, hits = 0;
  const faces = [0, 0, 0, 0, 0, 0];
  for (const x of rows) {
    endings[x.ending.id] = (endings[x.ending.id] || 0) + 1;
    const k = `${x.strategy}@${x.acc}`;
    by[k] = by[k] || { n: 0, score: 0, endings: {} };
    by[k].n += 1;
    by[k].score += x.game.score();
    by[k].endings[x.ending.id] = (by[k].endings[x.ending.id] || 0) + 1;
    declared += x.t.declared;
    hits += x.t.hits;
    for (const f of x.t.rolls) faces[f - 1] += 1;
  }
  for (const v of Object.values(by)) v.score = Math.round(v.score / v.n);
  const rolls = faces.reduce((a, b) => a + b, 0);
  return { games: rows.length, endings, by, dice: { rolls, faces, declared, hits, hit_rate: declared ? +(hits / declared).toFixed(3) : null } };
}

module.exports = { play, simulate, summarize, STRATEGIES, rng };

if (require.main === module) {
  const file = process.argv[2] || path.join(__dirname, "world", "world.json");
  const data = JSON.parse(fs.readFileSync(file, "utf8"));
  console.log(JSON.stringify(summarize(simulate(data, Number(process.argv[3]) || 100)), null, 1));
}

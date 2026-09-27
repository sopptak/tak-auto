/*
 * CHOICE100 자동 플레이어(6-64) - 밸런스 점검용 시뮬레이션. 결과는 화면(stdout)에만 낸다.
 * 실제 플레이 데이터가 아니다: 어디에도 성과로 저장하지 않는다(6-63 16장 "시뮬레이션을 성과로 섞지 않음").
 *
 *   node sim.js [data.json] [runs]
 */
"use strict";
const fs = require("fs");
const path = require("path");
const { Game } = require("./engine.js");

// 전략: 선택지 글자·효과를 보고 고른다(데이터 형식만 알고 금융을 모른다).
const score = {
  debt_first: (c) => -(c.effects.debt || 0) * 3 - (c.effects.risk || 0),
  invest_first: (c) => (c.effects.investment || 0) + (c.moves || []).filter((m) => m.to === "investment").length * 500 + (c.effects.risk || 0),
  spender: (c) => (c.effects.happiness || 0) * 10 - (c.effects.cash || 0) * 0.01,
  safe: (c) => -(c.effects.risk || 0) * 10 + (c.effects.cash || 0) * 0.01,
  balanced: (c) => (c.effects.happiness || 0) * 3 - (c.effects.risk || 0) * 3 - (c.effects.debt || 0) + (c.effects.investment || 0) * 0.5 - (c.effects.expense || 0) * 5,
};

function rng(seed) {
  let s = seed >>> 0 || 1;
  return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 2 ** 32);
}

function play(data, pick) {
  const g = new Game(data);
  const trace = [];
  for (let guard = 0; guard < 1000; guard++) {
    const opts = g.choices().filter((o) => o.enabled);
    const out = g.choose(pick(opts, g).choice.id);
    trace.push(out);
    if (out.phase === "end") break;
    g.next();
  }
  return { game: g, trace, ending: g.ending(), final: g.snapshot() };
}

function simulate(data, runs = 200) {
  const results = [];
  for (const [name, f] of Object.entries(score)) {
    results.push({ strategy: name, ...play(data, (opts) => opts.reduce((a, b) => (f(b.choice) > f(a.choice) ? b : a))) });
  }
  const r = rng(42);
  for (let i = 0; i < runs; i++) results.push({ strategy: "random", ...play(data, (opts) => opts[Math.floor(r() * opts.length)]) });
  return results;
}

function summarize(results) {
  const endings = {};
  const byStrategy = {};
  const nw = [];
  for (const x of results) {
    endings[x.ending.id] = (endings[x.ending.id] || 0) + 1;
    if (x.strategy !== "random") byStrategy[x.strategy] = { ending: x.ending.id, net_worth: x.final.net_worth, risk: x.final.risk, happiness: x.final.happiness, debt: x.final.debt };
    nw.push(x.final.net_worth);
  }
  nw.sort((a, b) => a - b);
  return { runs: results.length, endings, byStrategy, net_worth: { min: nw[0], median: nw[Math.floor(nw.length / 2)], max: nw[nw.length - 1] } };
}

module.exports = { simulate, summarize, play, score };

if (require.main === module) {
  const file = process.argv[2] || path.join(__dirname, "data", "finance.json");
  const data = JSON.parse(fs.readFileSync(file, "utf8"));
  console.log(JSON.stringify(summarize(simulate(data, Number(process.argv[3]) || 200)), null, 2));
}

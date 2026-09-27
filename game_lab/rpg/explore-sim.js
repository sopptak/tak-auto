/*
 * 고조선 탐험 자동 플레이어(6-68) - 막힘(soft-lock)·길이·엔딩 분포 점검. stdout만(실제 플레이 데이터 아님).
 *   node explore-sim.js [gojoseon.json] [전략별 판 수]
 * 전략: explorer(탐색 먼저) · tribe(부족 먼저) · force(위협 섞음) · general(무작위 섞음)
 */
"use strict";
const fs = require("fs");
const path = require("path");
const { Explore } = require("./explore.js");
const Board = require("../board/engine.js");

function rng(seed) { let s = seed >>> 0 || 1; return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 2 ** 32); }

const PREF = {
  explorer: ["observe", "gift", "help", "fence", "watch", "dike", "high", "trade", "wait", "joseon", "death", "grain", "slave", "hongik"],
  tribe: ["gift", "help", "trade", "fence", "dike", "high", "watch", "observe", "wait", "joseon", "death", "grain", "slave", "hongik"],
  force: ["threaten", "observe", "high", "dike", "watch", "new", "exile", "labor", "forgive", "strong"],
  general: [],
};

function playBoard(g, r, acc) {
  const b = g.boardGame();
  for (let k = 0; k < 60 && b.state.phase !== "end"; k++) {
    const ph = b.state.phase;
    if (ph === "quiz") { const q = b.quiz(); b.answer(r() < acc ? q.correct : (q.correct + 1) % 4); }
    else if (ph === "parity") b.declare(r() < 0.5 ? "odd" : "even");
    else if (ph === "roll") b.roll();
    else if (ph === "steer") { const o = b.steerOptions(); const pick = o.find((x) => x.cell.type === "EXPLORE") || o[0]; b.steerTo(pick.steps); }
    else if (ph === "cell") {
      if (b.cell().type === "QUIZ") { const q = b.cellQuiz(); b.answerCellQuiz(r() < acc ? q.correct : (q.correct + 1) % 4); }
      else { const opts = b.cellOptions().filter((o) => o.enabled); b.act((opts.find((o) => o.choice.id === "explore") || opts[0]).choice.id); }
    } else if (ph === "turn_end") b.nextTurn();
  }
  return g.finishBoardMini();
}

// 아직 의미 있는 미니게임인가(이미 이겼거나, 목적이 사라졌으면 안 한다)
function useful(g, id) {
  if (g.s.flags.includes(`won_${id}`)) return false;
  if (id === "m_hunt") return g.s.tribes.hunters.status === "met" && !g.s.flags.includes("hunter_proved");
  if (id === "m_bronze") return g.s.tribes.crafters.status === "met";
  if (id === "m_route") return !g.rpg.state.items.includes("raft") && g.s.tribes.traders.status !== "integrated";
  return true;
}

// 지금 갈 수 있는 길로만 BFS - 목표 장소까지 첫 걸음
function stepToward(g, goal) {
  const start = g.s.loc;
  const seen = new Set([start]);
  const q = [[start, null]];
  while (q.length) {
    const [loc, first] = q.shift();
    if (goal(loc) && loc !== start) return first;
    for (const e of g.x.edges) {
      if (!g.edgeVisible(e)) continue;
      const to = e.from === loc ? e.to : e.to === loc ? e.from : null;
      if (!to || seen.has(to) || !g.meets(e.requires)) continue;
      seen.add(to);
      q.push([to, first || to]);
    }
  }
  return null;
}

function play(data, { strategy = "general", seed = 1, acc = 0.7, maxActions = 600 } = {}) {
  const r = rng(seed);
  const g = new Explore(data, { BoardGame: Board.Game, rng: r });
  const pref = PREF[strategy];
  let actions = 0;
  for (; actions < maxActions && !g.s.ended; actions++) {
    if (g.event()) {
      const opts = g.eventOptions().filter((o) => o.ok);
      let byPref = pref.map((id) => opts.find((o) => o.choice.id === id)).find(Boolean);
      if (g.event().id === "ev_gather" && (g.integratedCount() >= 4 || g.s.flags.includes("council_waiting") || g.s.day > 140)) byPref = opts.find((o) => o.choice.id === "open");
      g.choose((strategy === "general" || !byPref ? opts[Math.floor(r() * opts.length)] : byPref).choice.id);
      continue;
    }
    if (g.s.mini) {
      const m = g.M[g.s.mini.id];
      if (m.type === "board") playBoard(g, r, acc);
      else { const st = g.miniStep(); const hint = !!st.hint; const good = st.step.options.findIndex((o) => o.correct); g.miniAnswer(r() < (hint ? 0.95 : acc) ? good : (good + 1) % st.step.options.length); }
      continue;
    }
    const here = g.L[g.s.loc];
    // 1) 통합
    const t = here.tribe && g.tribeView(here.tribe);
    if (t && t.state.status === "met") {
      if (strategy === "force" && t.force && t.force.ok) { g.integrate(here.tribe, "force"); continue; }
      if (t.union.ok) { g.integrate(here.tribe, "union"); continue; }
      const rq = t.requests.find((x) => !x.done && x.ok);
      if (rq) { g.fulfill(here.tribe, rq.req.id); continue; }
      if (t.state.trust < t.tribe.union.trust && t.requests.every((x) => x.done) && g.giftInfo(here.tribe).ok) { g.gift(here.tribe); continue; }
      const of = t.requests.find((x) => x.offer);
      if (of && r() < 0.5) { g.offer(here.tribe, of.req.id); continue; }
    }
    // 2) 탐색(전략에 따라 순서)
    const si = g.searchInfo();
    const recruiting = g.s.flags.includes("council_waiting") && g.integratedCount() < 4 && g.s.day < 250; // 사람처럼: 더 모으겠다고 했으면 회의는 나중에
    if (si.left && !si.locked && !(recruiting && g.s.loc === "asadal") && (strategy === "explorer" || r() < 0.8)) { g.search(); continue; }
    // 3) 미니게임(아직 못 이긴 것)
    const mg = g.minigames().find((m) => m.ok && useful(g, m.mg.id));
    if (mg) { g.startMini(mg.mg.id); continue; }
    // 4) 채집(식량·구리가 모자랄 때)
    const gi = g.gatherInfo();
    const st = g.rpg.state.stats;
    if (gi && gi.ok && ((gi.gather.stat === "food" && st.food < 20) || (gi.gather.stat === "copper" && st.copper < 4))) { g.gather(); continue; }
    // 5) 이동 목표
    const goals = [
      (l) => !g.s.visited.includes(l),
      (l) => { const s2 = g.s.searched[l] || 0; const list = g.L[l].searches || []; return !(recruiting && l === "asadal") && s2 < list.length && g.meets(list[s2].requires); },
      (l) => { const tr = g.L[l].tribe; if (!tr) return false; const v = g.tribeView(tr); return v.state.status === "met" && (v.union.ok || v.requests.some((x) => !x.done && (x.ok || x.offer)) || (strategy === "force" && v.force && v.force.ok) || (v.requests.every((x) => x.done) && g.giftInfo(tr).ok)); },
      (l) => g.L[l].gather && (g.s.gathered[l] || 0) < (g.L[l].gather.max ?? 99) && g.meets(g.L[l].gather.requires) && ((g.L[l].gather.stat === "food" && st.food < 20) || (g.L[l].gather.stat === "copper" && st.copper < 4)),
      (l) => (g.L[l].minigames || []).some((id) => g.meets(g.M[id].requires) && useful(g, id)),
    ];
    let moved = false;
    for (const goal of goals) {
      const nxt = stepToward(g, goal);
      if (nxt) {
        const ex = g.exits().find((e) => e.to.id === nxt);
        if (ex && ex.ok) { g.travel(nxt); moved = true; break; }
      }
    }
    if (moved) continue;
    if (gi && gi.ok) { g.gather(); continue; }
    const back = g.exits().find((e) => e.ok && e.to.id === g.x.start) || g.exits().find((e) => e.ok);
    if (back) { g.travel(back.to.id); continue; }
    break;
  }
  return { g, actions, ended: g.s.ended };
}

function simulate(data, n = 50) {
  const rows = [];
  let seed = 101;
  for (const strategy of Object.keys(PREF)) for (let i = 0; i < n; i++) rows.push({ strategy, ...play(data, { strategy, seed: seed++ }) });
  return rows;
}

function summarize(rows) {
  const by = {};
  for (const x of rows) {
    const b = (by[x.strategy] = by[x.strategy] || { n: 0, ended: 0, endings: {}, actions: [], tribes: [], places: [], knowledge: [], level: [], stuck: [] });
    b.n += 1;
    if (x.ended) {
      b.ended += 1;
      b.endings[x.ended.ending] = (b.endings[x.ended.ending] || 0) + 1;
      b.actions.push(x.actions);
      b.tribes.push(x.ended.vals.tribes);
      b.places.push(x.ended.vals.places);
      b.knowledge.push(x.ended.vals.knowledge);
      b.level.push(x.ended.level);
    } else b.stuck.push({ loc: x.g.s.loc, day: x.g.s.day, integrated: x.g.integratedCount() });
  }
  const med = (a) => (a.length ? a.slice().sort((p, q) => p - q)[a.length >> 1] : null);
  for (const b of Object.values(by)) for (const k of ["actions", "tribes", "places", "knowledge", "level"]) b[k] = { min: Math.min(...b[k]), median: med(b[k]), max: Math.max(...b[k]) };
  return { runs: rows.length, by };
}

module.exports = { play, simulate, summarize, rng };

if (require.main === module) {
  const file = process.argv[2] || path.join(__dirname, "gojoseon", "gojoseon.json");
  const data = JSON.parse(fs.readFileSync(file, "utf8"));
  console.log(JSON.stringify(summarize(simulate(data, Number(process.argv[3]) || 50)), null, 1));
}

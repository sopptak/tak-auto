// 고조선 탐험·부족 통합 테스트(6-68) - node --test game_lab/rpg/test/explore.test.js
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("path");
const fs = require("fs");
const { Explore, validateExplore } = require("../explore.js");
const Rpg = require("../engine.js");
const Board = require("../../board/engine.js");
const { simulate, summarize, rng } = require("../explore-sim.js");

const load = () => JSON.parse(fs.readFileSync(path.join(__dirname, "..", "gojoseon", "gojoseon.json"), "utf8"));
const game = (d = load(), seed = 1) => new Explore(d, { BoardGame: Board.Game, rng: rng(seed) });

test("data valid for RPG core, exploration layer and hunt board", () => {
  const d = load();
  assert.deepEqual(Rpg.validate(d), []);
  assert.deepEqual(validateExplore(d), []);
  assert.deepEqual(Board.validate(d.boards.forest_hunt.data), []);
  assert.ok(d.explore.locations.length >= 10);
  assert.equal(d.explore.tribes.length, 4);
  assert.equal(d.explore.minigames.length, 3);
});

test("validation catches dead flags, unreachable events and broken refs", () => {
  const d = load();
  d.explore.events[0].choices[0].effects.flags = ["never_used_flag"];
  d.explore.events.push({ id: "orphan", title: "x", text: "x", historical_status: "game_setting", choices: [{ id: "a", text: "a", result: "a", historical_status: "game_setting", effects: {} }] });
  d.explore.edges[0].to = "nowhere";
  const errs = validateExplore(d);
  for (const needle of ["never_used_flag", "orphan", "edge e_camp_river"]) assert.ok(errs.some((e) => e.includes(needle)), needle);
});

test("exploration: search order, discoveries reveal hidden paths, first visit gives EXP", () => {
  const g = game();
  assert.deepEqual(g.exits().map((e) => e.to.id).sort(), ["forest", "river"]);
  assert.ok(!g.mapView().some((v) => v.loc.id === "plain")); // 안개
  g.travel("river");
  assert.equal(g.rpg.state.stats.exp, d0().explore.discover_exp);
  const r = g.search();
  assert.deepEqual(r.revealed, ["e_river_plain"]);
  assert.ok(g.exits().some((e) => e.to.id === "plain"));
  assert.ok(g.mapView().some((v) => v.loc.id === "plain" && !v.visited)); // ❓로 보인다
  g.search();
  assert.ok(g.s.flags.includes("salt_wind"));
  assert.throws(() => g.search(), /더 찾을 것이 없다/);
});
function d0() { return load(); }

test("tribe meet opens encounter; choice → trust → follow-up event chain", () => {
  const g = game();
  g.travel("river"); g.search(); g.travel("plain");
  assert.equal(g.s.tribes.farmers.status, "met");
  assert.equal(g.event().id, "ev_farmers_meet");
  assert.throws(() => g.search(), /사건/); // 사건 먼저
  const r = g.choose("help");
  assert.equal(r.trust.farmers, 1);
  assert.equal(g.event().id, "ev_flood"); // 선택 → 다음 사건
  const opts = Object.fromEntries(g.eventOptions().map((o) => [o.choice.id, o]));
  assert.equal(opts.dike.ok, false); // 인구 25 필요
  assert.match(opts.dike.why, /인구 25/);
  assert.equal(opts.high.ok, false); // 고인돌 언덕을 아직 모름
  g.choose("pray");
  const v = g.tribeView("farmers");
  const flood = v.requests.find((x) => x.req.id === "flood");
  assert.equal(flood.offer, true); // 다시 돕기
  g.search(); // 들 끝 언덕 발견 → 높은 땅 선택지 열림
  g.offer("farmers", "flood");
  assert.equal(g.eventOptions().find((o) => o.choice.id === "high").ok, true);
  g.choose("high");
  assert.ok(g.s.flags.includes("flood_passed"));
});

function toFarmersUnion(g) {
  g.travel("river"); g.search(); g.travel("plain");
  g.choose("gift");
  g.search();
  g.offer("farmers", "flood"); g.choose("high");
  g.fulfill("farmers", "flood");
  while (g.rpg.state.stats.food < 6) g.gather();
  g.fulfill("farmers", "feast");
  return g.integrate("farmers", "union");
}

test("union integration: abilities, items, companion, knowledge, population; farming boosts gathering", () => {
  const g = game();
  g.rpg.state.stats.food = 20;
  const before = g.rpg.state.stats.population;
  const r = toFarmersUnion(g);
  assert.equal(g.s.tribes.farmers.status, "integrated");
  assert.deepEqual(r.gained.skills, ["farming"]);
  assert.ok(g.rpg.state.items.includes("raft"));
  assert.ok(g.rpg.state.companions.includes("dulnyeok"));
  assert.ok(g.rpg.state.knowledge.includes("k_river"));
  assert.equal(g.rpg.state.stats.population, before + 30);
  assert.equal(g.rpg.state.relations.farmers, "ALLY");
  const gi = g.gatherInfo();
  const f0 = g.rpg.state.stats.food;
  const out = g.gather();
  assert.equal(out.bonus, true);
  assert.equal(g.rpg.state.stats.food, f0 + gi.gather.amount + gi.gather.bonus.amount);
  assert.throws(() => g.integrate("farmers"), /신뢰|요청/); // 이미 통합
});

test("force integration needs a threat and strength, costs reputation", () => {
  const g = game();
  g.travel("forest"); g.search(); g.search(); g.travel("ridge");
  g.choose("threaten");
  const v = g.tribeView("hunters");
  assert.equal(v.force.ok, false); // 인구 30 필요
  assert.match(v.force.why, /인구 30/);
  g.rpg.state.stats.population = 30;
  const rep = g.rpg.state.stats.reputation;
  const r = g.integrate("hunters", "force");
  assert.equal(r.method, "force");
  assert.equal(g.rpg.state.stats.reputation, rep - 8);
  assert.ok(!g.rpg.state.companions.includes("maegit")); // 복속은 동료가 되지 않는다
});

test("abilities open new play: tracking reveals a hidden discovery and path", () => {
  const g = game();
  g.travel("forest"); g.search(); g.search();
  assert.match(g.searchInfo().locked, /추적/);
  assert.throws(() => g.search(), /추적/);
  g.rpg.state.skills.push("tracking");
  assert.equal(g.searchInfo().locked, null);
  const r = g.search();
  assert.ok(r.gained.stats.food >= 8);
  g.travel("ridge");
  g.choose("observe");
  g.s.revealed.push("e_ridge_copper");
  assert.ok(g.exits().some((e) => e.to.id === "copper" && e.ok));
});

test("region gate: 아사달 needs 3 tribes; council asks before founding", () => {
  const g = game();
  g.s.revealed.push("e_ridge_crafts", "e_crafts_mist", "e_mist_asadal", "e_forest_ridge");
  g.rpg.state.skills.push("bronze_tools");
  g.s.loc = "mist";
  g.s.visited.push("mist");
  const ex = g.exits().find((e) => e.to.id === "asadal");
  assert.equal(ex.ok, false);
  assert.match(ex.why, /부족 3곳/);
  for (const t of ["farmers", "crafters", "traders"]) { g.s.tribes[t].status = "integrated"; g.s.tribes[t].method = "union"; }
  g.travel("asadal");
  assert.equal(g.event().id, "ev_gather");
  g.choose("wait");
  assert.equal(g.s.ended, null);
  const r = g.search(); // 모닥불 자리 → 회의
  assert.equal(g.event().id, "ev_council");
  g.choose("joseon"); g.choose("death"); g.choose("grain"); g.choose("slave");
  g.choose("hongik");
  assert.ok(g.s.ended);
  assert.deepEqual(g.s.ended.laws, ["death", "grain", "slave"]);
  assert.ok(g.rpg.state.knowledge.includes("k_8laws"));
  assert.ok(g.rpg.state.policies.includes("eight_laws")); // 지식 → 정책
  assert.ok(r.text.includes("모닥불"));
});

test("endings reflect how the country was built", () => {
  const d = load();
  const end = (setup) => {
    const g = game(d);
    setup(g);
    g.s.event = "ev_found";
    g.choose("full");
    return g.s.ended.ending;
  };
  const all = (m) => (g) => { for (const t of Object.keys(g.s.tribes)) { g.s.tribes[t].status = "integrated"; g.s.tribes[t].method = m(t); } };
  assert.equal(end(all(() => "union")), "union_all");
  assert.equal(end(all((t) => (t === "hunters" || t === "farmers" ? "force" : "union"))), "force");
  assert.equal(end((g) => { all(() => "union")(g); g.s.tribes.traders.status = "met"; g.s.tribes.traders.method = null; g.rpg.state.knowledge.push(...d.knowledge.map((k) => k.id)); }), "wisdom");
  assert.equal(end(() => {}), "small");
});

test("hunger: travel is never blocked by food, it costs population instead", () => {
  const g = game();
  g.travel("river"); g.search();
  g.rpg.state.stats.food = 0;
  const ex = g.exits().find((e) => e.to.id === "plain");
  assert.equal(ex.ok, true);
  assert.equal(ex.hungry, true);
  const pop = g.rpg.state.stats.population;
  const r = g.travel("plain");
  assert.ok(r.hunger);
  assert.equal(g.rpg.state.stats.population, pop - 3);
  assert.equal(g.rpg.state.stats.food, 0);
});

test("gift keeps trust reachable after any first choice", () => {
  const g = game();
  g.travel("river"); g.search(); g.travel("plain");
  g.choose("observe");
  g.rpg.state.stats.food = 8;
  const t0 = g.s.tribes.farmers.trust;
  g.gift("farmers");
  assert.equal(g.s.tribes.farmers.trust, t0 + 1);
  assert.equal(g.rpg.state.stats.food, 4);
});

test("pick minigame: knowledge shows hints, pass threshold, win reveals a new path", () => {
  const g = game();
  g.travel("river"); g.search(); g.search();
  const noHint = (() => { g.startMini("m_route"); return g.miniStep().hint; })();
  assert.equal(noHint, null);
  g.s.mini = null;
  g.rpg.state.knowledge.push("k_river");
  g.startMini("m_route");
  assert.match(g.miniStep().hint, /넓어지며/);
  for (let i = 0; i < 3; i++) g.miniAnswer(g.miniStep().step.options.findIndex((o) => o.correct));
  assert.ok(g.s.flags.includes("won_m_route"));
  assert.ok(g.exits().some((e) => e.to.id === "estuary" && e.ok)); // 뗏목 없이 가는 길
});

test("board minigame (6-66 engine): hunt win proves the hunter", () => {
  const g = game(load(), 5);
  g.travel("forest");
  g.startMini("m_hunt");
  const b = g.boardGame();
  b.state.vars.exploration = 1;
  b.state.phase = "end";
  const r = g.finishBoardMini();
  assert.equal(r.win, true);
  assert.ok(g.s.flags.includes("hunter_proved"));
  assert.ok(g.s.flags.includes("won_m_hunt"));
});

test("save/load round trip and bad saves rejected", () => {
  const d = load();
  const g = game(d);
  g.travel("river"); g.search();
  const saved = g.serialize();
  const r = Explore.restore(d, saved, { BoardGame: Board.Game });
  assert.equal(r.s.loc, "river");
  assert.deepEqual(r.s.revealed, ["e_river_plain"]);
  assert.equal(r.rpg.state.stats.exp, g.rpg.state.stats.exp);
  for (const bad of ["", "{", JSON.stringify({ v: 9 }), saved.replace('"loc":"river"', '"loc":"moon"')]) assert.equal(Explore.restore(d, bad, { BoardGame: Board.Game }), null);
  assert.equal(Explore.restore({ ...d, version: "x" }, saved, { BoardGame: Board.Game }), null);
});

test("history boundaries: myth is never labeled fact, facts carry sources, no founding year as fact", () => {
  const d = load();
  const k = Object.fromEntries(d.knowledge.map((x) => [x.id, x]));
  for (const id of ["k_myth", "k_dangun", "k_hongik"]) assert.equal(k[id].historical_status, "mythology");
  for (const id of ["k_dolmen", "k_bipa"]) { assert.equal(k[id].historical_status, "historical_fact"); assert.match(k[id].source, /encykorea\.aks\.ac\.kr\/Article\/E\d+/); }
  assert.equal(k.k_8laws.historical_status, "historical_record");
  for (const x of d.knowledge) if (x.historical_status !== "game_setting") assert.match(x.source, /https:\/\//, x.id);
  const txt = JSON.stringify(d);
  assert.doesNotMatch(txt, /2333/); // 확정되지 않은 건국 연도를 넣지 않는다
  for (const t of d.explore.tribes) assert.equal(t.historical_status, "game_setting");
  assert.match(d.disclaimer, /건국 연도를 사실로 쓰지 않습니다/);
});

test("200 simulated plays across 4 styles: no soft-lock, all reach the founding, endings vary by style", () => {
  const s = summarize(simulate(load(), 50));
  assert.equal(s.runs, 200);
  for (const [name, b] of Object.entries(s.by)) assert.equal(b.ended, b.n, `${name} stuck: ${JSON.stringify(b.stuck.slice(0, 2))}`);
  assert.ok(s.by.force.endings.force > 0);
  assert.ok(s.by.explorer.endings.union_all > 0);
  const all = new Set(Object.values(s.by).flatMap((b) => Object.keys(b.endings)));
  assert.ok(all.size >= 4, [...all].join(","));
  assert.ok(s.by.explorer.actions.median >= 60); // 1시간 슬라이스 분량(행동 수)
});

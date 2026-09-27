// CHOICE100 엔진·기록 테스트(6-64 → 6-65 V2) - node --test game_lab/choice100/test/engine.test.js
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("path");
const fs = require("fs");
const { Game, validate, formatValue } = require("../engine.js");
const { simulate, summarize, play } = require("../sim.js");
const Analytics = require("../analytics.js");

const DATA_PATH = path.join(__dirname, "..", "data", "finance.json");
const load = () => JSON.parse(fs.readFileSync(DATA_PATH, "utf8"));
const N = 40;

function finite(g) {
  for (const [k, v] of Object.entries(g.snapshot())) assert.ok(Number.isFinite(v), `${k}=${v}`);
}
function firstEnabled(g) { return g.choices().find((o) => o.enabled).choice.id; }

test("schema, 40 scenarios, q031~q040 connectivity, reachability", () => {
  const data = load();
  assert.deepEqual(validate(data), []);
  assert.equal(data.scenarios.length, N);
  assert.equal(data.total_choices, 100);
  assert.equal(data.chapters.length, 10);
  assert.deepEqual(data.chapters.map((c) => c.status), ["playable", "playable", "playable", "playable", "planned", "planned", "planned", "planned", "planned", "planned"]);
  const byId = Object.fromEntries(data.scenarios.map((s) => [s.id, s]));
  for (let i = 31; i <= 40; i++) {
    const s = byId[`q0${i}`];
    assert.equal(s.chapter, 4);
    assert.equal(s.next, i === 40 ? "END" : `q0${i + 1}`);
  }
  assert.equal(byId.q030.next, "q031");
  const seen = new Set();
  const stack = [data.first];
  while (stack.length) {
    const id = stack.pop();
    if (id === "END" || seen.has(id)) continue;
    seen.add(id);
    for (const c of byId[id].choices) stack.push(c.next || byId[id].next);
  }
  assert.equal(seen.size, N);
});

test("validate catches broken data (incl. flags that never come back)", () => {
  const data = load();
  data.scenarios[0].choices[0].next = "nope";
  data.scenarios[1].choices[0].effects = { money: 1 };
  data.scenarios[2].triggers = [{ flag: "never_set", effects: {}, text: "x" }];
  data.scenarios[3].choices[0].set_flags = ["orphan_flag"];
  const errs = validate(data);
  assert.ok(errs.some((e) => e.includes("next nope")));
  assert.ok(errs.some((e) => e.includes("모르는 변수 money")));
  assert.ok(errs.some((e) => e.includes("never_set")));
  assert.ok(errs.some((e) => e.includes("orphan_flag")));
  assert.throws(() => new Game(data));
});

test("start, choose, state change, net worth, own vs flow", () => {
  const g = new Game(load());
  assert.equal(g.state.vars.cash, 3100); // q001 보너스
  assert.equal(g.value("net_worth"), 3100 + 3000 - 2000);
  const out = g.choose("a"); // 대출 상환 100
  assert.equal(out.own.debt, -100);
  assert.equal(out.own.cash, -100);
  assert.equal(out.flow.cash, 150);
  assert.equal(out.deltas.debt, -100 + Math.round(1900 * 0.004));
  assert.equal(g.value("net_worth"), g.state.vars.cash + g.state.vars.investment + g.state.vars.asset - g.state.vars.debt);
  assert.equal(g.score(), g.value("net_worth"));
  assert.equal(out.phase, "result");
  assert.equal(out.delayed, false);
  assert.throws(() => g.choose("a"), /phase/);
  g.next();
  assert.equal(g.scenario().id, "q002");
});

test("requires disables choice and choose refuses it", () => {
  const g = new Game(load());
  g.state.vars.cash = 100;
  g.state.current = "q007";
  const opt = g.choices().find((o) => o.choice.id === "b");
  assert.equal(opt.enabled, false);
  assert.match(opt.reason, /현금 500만원 이상/);
  assert.throws(() => g.choose("b"), /조건/);
});

test("restart resets everything", () => {
  const g = new Game(load());
  g.choose("d"); g.next(); g.choose("b");
  g.start();
  assert.equal(g.state.count, 0);
  assert.equal(g.scenario().id, "q001");
  assert.deepEqual(g.state.flags, []);
  assert.deepEqual(g.state.style, {});
  assert.equal(g.state.vars.cash, 3100);
});

test("delayed consequence: early choice comes back with its origin", () => {
  const g = new Game(load());
  g.choose("a"); g.next();                       // q001
  const out = g.choose("b");                     // q002 임시 치료 → delayed_dental
  assert.equal(out.delayed, true);
  g.next();
  while (g.scenario().id !== "q008") { g.choose(firstEnabled(g)); g.next(); }
  const echo = g.state.enter_echoes.find((e) => e.flag === "delayed_dental");
  assert.ok(echo, JSON.stringify(g.state.enter_echoes));
  assert.equal(echo.origin.n, 2);
  assert.match(echo.origin.choice, /임시 치료/);
  assert.match(echo.text, /치아/);
});

test("sessions every 10, triggers, ending at 40", () => {
  const g = new Game(load());
  const phases = [];
  for (let i = 0; i < N; i++) {
    const s = g.scenario().id;
    const pickId = { q013: "d", q021: "c", q025: "a" }[s] || firstEnabled(g);
    phases.push(g.choose(pickId).phase);
    if (phases[phases.length - 1] === "end") break;
    g.next();
    if (g.scenario().id === "q019") assert.ok(g.state.enter_echoes.some((e) => e.flag === "guarantor"));
    if (g.scenario().id === "q025") assert.ok(g.state.enter_echoes.some((e) => e.flag === "single_stock"));
  }
  assert.deepEqual([phases[9], phases[19], phases[29], phases[39]], ["session_end", "session_end", "session_end", "end"]);
  assert.equal(phases.filter((p) => p === "result").length, 36);
  assert.ok(g.ending().title);
  finite(g);
});

test("player style accumulates from actual choice changes", () => {
  const data = load();
  const g = new Game(data);
  g.choose("a"); // 대출 상환: debt -100, risk -3
  assert.deepEqual(g.state.style, { debt_focus: 1 });
  g.next();
  g.choose("c"); // 치료 할부: debt +150 → 어느 규칙에도 안 걸림
  assert.deepEqual(g.state.style, { debt_focus: 1 });
  let r = g.styleResult();
  assert.equal(r.key, "debt_focus");
  assert.equal(r.title, "부채 정리형");
  g.state.style = { debt_focus: 3, investment_focus: 3, consumption_focus: 3, risk_averse: 3 };
  r = g.styleResult();
  assert.equal(r.key, "balanced"); // 최다 25% < 34%
  assert.match(data.style.note, /게임 내 선택을 기준/);
});

test("no NaN/Infinity, clamps and overdraft guard", () => {
  const data = load();
  const g = new Game(data);
  g.state.vars.cash = 50;
  g.state.vars.income = 0;
  g.state.vars.happiness = 99;
  g.state.current = "q005";
  const out = g.choose("b"); // 가족 여행 500 → 현금 음수 → 마이너스 대출
  assert.ok(g.state.vars.cash >= 0);
  assert.ok(out.events.some((e) => e.includes("마이너스 대출")));
  assert.ok(g.state.vars.happiness <= 100);
  g.state.vars.risk = Infinity;
  g.state.vars.credit = NaN;
  g._normalize();
  finite(g);
  assert.equal(g.state.vars.credit, data.start.credit);
});

test("refresh-safe serialize/restore, rejects corrupt or old saves", () => {
  const data = load();
  const g = new Game(data);
  g.choose("c"); g.next(); g.choose("a");
  const saved = g.serialize();
  const r = Game.restore(data, saved);
  assert.equal(r.state.count, 2);
  assert.equal(r.state.phase, "result");
  r.next();
  assert.equal(r.scenario().id, "q003");
  for (const bad of ["", "{", "null", JSON.stringify({ v: 999 }),
    saved.replace('"current":"q002"', '"current":"zzz"'), saved.replace(/"cash":\d+/, '"cash":null')]) {
    assert.equal(Game.restore(data, bad), null, bad.slice(0, 40));
  }
  assert.equal(Game.restore({ ...data, version: "g1-1" }, saved), null); // 6-64 저장은 새 버전에서 버림
});

test("money format", () => {
  assert.equal(formatValue("money", 3000, "만원"), "3,000만원");
  assert.equal(formatValue("money", 12500, "만원"), "1억 2,500만원");
  assert.equal(formatValue("money", 20000, "만원"), "2억원");
  assert.equal(formatValue("money", -150, "만원"), "-150만원");
  assert.equal(formatValue(undefined, 70), "70");
});

test("local analytics: start/choice/complete/restart, play time, previous run, storage only", () => {
  const mem = Analytics.memoryStorage();
  let now = Date.UTC(2026, 8, 27, 0, 0, 0);
  const a = Analytics.create(mem, "choice100-finance", "g2-1", () => now);
  a.start(false);
  for (let i = 1; i <= 3; i++) { now += 10000; a.choice(i, `q00${i}`, "a"); }
  now += 10 * 60 * 1000; // 자리 비움 10분 → 120초까지만 셈
  a.choice(4, "q004", "b");
  const run1 = a.complete({ choice_count: 4, ending: "balanced", style: "debt_focus", net_worth: 5000, debt: 100, happiness: 60 });
  assert.equal(run1.play_time_sec, 30 + 120);
  assert.equal(run1.choice_count, 4);
  assert.equal(a.previous(), null);
  a.start(true);
  now += 5000;
  a.complete({ choice_count: 40, ending: "happy", style: "balanced", net_worth: 9000, debt: 0, happiness: 90 });
  assert.equal(a.previous().ending, "balanced");
  const st = a.stats();
  assert.deepEqual([st.plays, st.completions, st.restart_count], [2, 2, 1]);
  const stored = JSON.parse(mem.get(a.key));
  assert.deepEqual(stored.events.map((e) => e.e), ["game_start", "choice_made", "choice_made", "choice_made", "choice_made", "game_completion", "game_restart", "game_start", "game_completion"]);
  assert.deepEqual(Object.keys(stored.runs[0]).sort(), ["choice_count", "completed_at", "debt", "ending", "game_id", "happiness", "net_worth", "play_time_sec",
    "restart_count", "started_at", "style", "version"]); // 개인정보 필드 없음
  mem.set(a.key, "{broken");
  assert.equal(a.stats().plays, 0); // 손상된 기록은 새로 시작
  const throwing = { get() { throw new Error("blocked"); }, set() { throw new Error("blocked"); } };
  const b = Analytics.create(throwing, "x", "v");
  assert.doesNotThrow(() => { b.start(); b.choice(1, "q", "a"); b.complete({ ending: "e" }); b.stats(); });
});

test("500+ simulated runs: every ending reachable, no strategy locks one ending, TIPs short", () => {
  const data = load();
  const results = simulate(data, 300, 50);
  assert.ok(results.length >= 500, String(results.length));
  const s = summarize(results);
  for (const e of data.endings) assert.ok(s.endings[e.id] > 0, `ending ${e.id} unreachable: ${JSON.stringify(s.endings)}`);
  for (const r of results) {
    assert.equal(r.trace.length, N);
    for (const v of Object.values(r.final)) assert.ok(Number.isFinite(v));
  }
  for (const [name, dist] of Object.entries(s.noisy)) {
    const total = Object.values(dist).reduce((a, b) => a + b, 0);
    assert.ok(Math.max(...Object.values(dist)) / total < 0.9, `${name} almost always one ending: ${JSON.stringify(dist)}`);
  }
  assert.ok(new Set(Object.values(s.byStrategy).map((x) => x.ending)).size >= 3, JSON.stringify(s.byStrategy));
  for (const sc of data.scenarios) for (const c of sc.choices) {
    assert.ok(c.tip.length <= 90, `${sc.id}.${c.id} tip too long`);
    assert.ok((c.tip.match(/[.!?]\s|[.!?]$/g) || []).length <= 2, `${sc.id}.${c.id} tip > 2 sentences`);
  }
});

test("delayed choices are a minority (about 20~30% of scenarios, <30% of choices)", () => {
  const data = load();
  const tflags = new Set(data.scenarios.flatMap((s) => (s.triggers || []).map((t) => t.flag)));
  const all = data.scenarios.flatMap((s) => s.choices);
  const delayed = all.filter((c) => (c.set_flags || []).some((f) => tflags.has(f)));
  const scenes = data.scenarios.filter((s) => s.choices.some((c) => (c.set_flags || []).some((f) => tflags.has(f))));
  const early = data.scenarios.slice(0, 10).filter((s) => s.choices.some((c) => (c.set_flags || []).length));
  assert.ok(delayed.length / all.length < 0.3, `${delayed.length}/${all.length}`);
  assert.ok(delayed.length / all.length >= 0.15, `${delayed.length}/${all.length}`);
  assert.ok(early.length >= 3, "초반 10개 안에 나중에 돌아오는 선택이 3개 이상");
  assert.ok(scenes.length >= 8);
});

test("engine is domain-free: a tiny non-finance game runs on the same engine", () => {
  const hanja = {
    id: "choice100-hanja-demo", version: "t", title: "선택100 한자", total_choices: 100, session_size: 10,
    stats: [{ key: "score", label: "점수" }, { key: "streak", label: "연속", min: 0 }], derived: {}, hud: ["score"],
    start: { score: 0, streak: 0 }, chapters: [{ n: 1, title: "기초" }], first: "h1", score_stat: "score",
    scenarios: [
      { id: "h1", chapter: 1, title: "水", situation: "이 한자의 뜻은?", next: "h2", choices: [
        { id: "a", text: "물", effects: { score: 10, streak: 1 }, result_text: "정답: 물 수", tip: "水는 물이 흐르는 모양입니다." },
        { id: "b", text: "불", effects: { streak: -99 }, result_text: "오답", tip: "불은 火입니다." }] },
      { id: "h2", chapter: 1, title: "火", situation: "이 한자의 뜻은?", next: "END", choices: [
        { id: "a", text: "물", effects: { streak: -99 }, result_text: "오답", tip: "물은 水입니다." },
        { id: "b", text: "불", effects: { score: 10, streak: 1 }, result_text: "정답: 불 화", tip: "火는 타오르는 불꽃 모양입니다." }] }],
    endings: [{ id: "perfect", title: "만점", when: [{ stat: "score", op: ">=", value: 20 }] }, { id: "try", title: "다시", when: [] }],
  };
  const r = play(hanja, (opts) => opts.find((o) => o.choice.result_text.startsWith("정답")) || opts[0]);
  assert.equal(r.ending.id, "perfect");
  assert.equal(r.final.streak, 2);
  assert.equal(r.game.score(), 20);
  assert.equal(r.game.styleResult(), null);
});

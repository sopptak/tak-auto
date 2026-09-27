// CHOICE100 엔진 테스트(6-64) - node --test game_lab/choice100/test/
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("path");
const fs = require("fs");
const { Game, validate, formatValue } = require("../engine.js");
const { simulate, summarize, play } = require("../sim.js");

const DATA_PATH = path.join(__dirname, "..", "data", "finance.json");
const load = () => JSON.parse(fs.readFileSync(DATA_PATH, "utf8"));

function finite(g) {
  for (const [k, v] of Object.entries(g.snapshot())) assert.ok(Number.isFinite(v), `${k}=${v}`);
}

test("1-5 data schema, next links, reachability of all 30", () => {
  const data = load();
  assert.deepEqual(validate(data), []);
  assert.equal(data.scenarios.length, 30);
  assert.equal(data.total_choices, 100);
  assert.equal(data.chapters.length, 10);
  // 모든 시나리오 도달 가능(first부터 next를 따라)
  const byId = Object.fromEntries(data.scenarios.map((s) => [s.id, s]));
  const seen = new Set();
  const stack = [data.first];
  while (stack.length) {
    const id = stack.pop();
    if (id === "END" || seen.has(id)) continue;
    seen.add(id);
    for (const c of byId[id].choices) stack.push(c.next || byId[id].next);
  }
  assert.equal(seen.size, 30);
});

test("validate catches broken data", () => {
  const data = load();
  data.scenarios[0].choices[0].next = "nope";
  data.scenarios[1].choices[0].effects = { money: 1 };
  data.scenarios[2].triggers = [{ flag: "never_set", effects: {}, text: "x" }];
  const errs = validate(data);
  assert.ok(errs.some((e) => e.includes("next nope")));
  assert.ok(errs.some((e) => e.includes("모르는 변수 money")));
  assert.ok(errs.some((e) => e.includes("never_set")));
  assert.throws(() => new Game(data));
});

test("6-9 start, choose, state change, net worth", () => {
  const data = load();
  const g = new Game(data);
  // q001 on_enter 보너스 +100
  assert.equal(g.state.vars.cash, 3100);
  assert.equal(g.value("net_worth"), 3100 + 0 + 3000 - 2000);
  const out = g.choose("a"); // 대출 상환 100
  assert.equal(out.deltas.debt, -100 + Math.round(1900 * 0.004));
  assert.equal(out.flow.cash, 150);
  assert.equal(g.state.vars.cash, 3100 - 100 + 150);
  assert.equal(g.value("net_worth"), g.state.vars.cash + g.state.vars.investment + g.state.vars.asset - g.state.vars.debt);
  assert.equal(out.phase, "result");
  assert.throws(() => g.choose("a"), /phase/);
  g.next();
  assert.equal(g.scenario().id, "q002");
  assert.equal(g.state.count, 1);
});

test("requires disables choice and choose refuses it", () => {
  const data = load();
  const g = new Game(data);
  g.state.vars.cash = 100;
  g.state.current = "q007";
  const opt = g.choices().find((o) => o.choice.id === "b");
  assert.equal(opt.enabled, false);
  assert.match(opt.reason, /현금 500만원 이상/);
  assert.throws(() => g.choose("b"), /조건/);
});

test("10 restart resets everything", () => {
  const g = new Game(load());
  g.choose("d"); g.next(); g.choose("a");
  g.start();
  assert.equal(g.state.count, 0);
  assert.equal(g.scenario().id, "q001");
  assert.deepEqual(g.state.flags, []);
  assert.equal(g.state.vars.cash, 3100);
});

test("sessions every 10, flags trigger later scenes, 11 ending reachable", () => {
  const g = new Game(load());
  const phases = [];
  for (let i = 0; i < 30; i++) {
    const s = g.scenario().id;
    const pickId = { q013: "d", q021: "c", q025: "a" }[s] || g.choices().find((o) => o.enabled).choice.id;
    phases.push(g.choose(pickId).phase);
    if (phases[phases.length - 1] === "end") break;
    if (g.scenario().id === "q018") assert.ok(!g.state.enter_events.some((e) => e.includes("친구")));  // 빌려주지 않았으면 상환 이벤트 없음
    g.next();
    if (g.scenario().id === "q019") assert.ok(g.state.enter_events.some((e) => e.includes("보증")));
    if (g.scenario().id === "q025") assert.ok(g.state.enter_events.some((e) => e.includes("몰빵")));
  }
  assert.equal(phases[9], "session_end");
  assert.equal(phases[19], "session_end");
  assert.equal(phases[29], "end");
  assert.equal(phases.filter((p) => p === "result").length, 27);
  assert.ok(g.ending().title);
  finite(g);
});

test("14-15 no NaN/Infinity, clamps and overdraft guard", () => {
  const data = load();
  const g = new Game(data);
  g.state.vars.cash = 50;
  g.state.vars.income = 0; // 월급으로 메워지지 않게
  g.state.vars.happiness = 99;
  g.state.current = "q004";
  const out = g.choose("b"); // -80 → 현금 음수 → 마이너스 대출
  assert.ok(g.state.vars.cash >= 0);
  assert.ok(out.events.some((e) => e.includes("마이너스 대출")));
  assert.ok(g.state.vars.happiness <= 100);
  g.state.vars.risk = Infinity;
  g.state.vars.credit = NaN;
  g._normalize();
  finite(g);
  assert.equal(g.state.vars.credit, data.start.credit);
});

test("16 refresh-safe serialize/restore, rejects corrupt saves", () => {
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
  const other = { ...data, version: "g1-other" };
  assert.equal(Game.restore(other, saved), null); // 데이터 버전이 바뀌면 옛 저장은 버림
});

test("money format", () => {
  assert.equal(formatValue("money", 3000, "만원"), "3,000만원");
  assert.equal(formatValue("money", 12500, "만원"), "1억 2,500만원");
  assert.equal(formatValue("money", 20000, "만원"), "2억원");
  assert.equal(formatValue("money", -150, "만원"), "-150만원");
  assert.equal(formatValue(undefined, 70), "70");
});

test("auto-players: 100+ runs, every ending reachable, no NaN, tips short", () => {
  const data = load();
  const results = simulate(data, 150);
  assert.ok(results.length >= 150);
  const s = summarize(results);
  for (const e of data.endings) assert.ok(s.endings[e.id] > 0, `ending ${e.id} unreachable: ${JSON.stringify(s.endings)}`);
  for (const r of results) {
    assert.equal(r.trace.length, 30);
    for (const v of Object.values(r.final)) assert.ok(Number.isFinite(v));
  }
  // 전략마다 결과가 달라야 한다(한 가지 선택이 모두를 이기는 구조 방지의 최소 확인)
  assert.ok(new Set(Object.values(s.byStrategy).map((x) => x.ending)).size >= 3, JSON.stringify(s.byStrategy));
  for (const sc of data.scenarios) for (const c of sc.choices) {
    assert.ok(c.tip.length <= 90, `${sc.id}.${c.id} tip too long`);
    assert.ok((c.tip.match(/[.!?]\s|[.!?]$/g) || []).length <= 2, `${sc.id}.${c.id} tip > 2 sentences`);
  }
});

test("engine is domain-free: a tiny non-finance game runs on the same engine", () => {
  const hanja = {
    id: "choice100-hanja-demo", version: "t", title: "선택100 한자", total_choices: 100, session_size: 10,
    stats: [{ key: "score", label: "점수" }, { key: "streak", label: "연속", min: 0 }], derived: {}, hud: ["score"],
    start: { score: 0, streak: 0 }, chapters: [{ n: 1, title: "기초" }], first: "h1",
    scenarios: [
      { id: "h1", chapter: 1, title: "水", situation: "이 한자의 뜻은?", next: "h2", choices: [
        { id: "a", text: "물", effects: { score: 10, streak: 1 }, result_text: "정답: 물 수", tip: "水는 물이 흐르는 모양입니다." },
        { id: "b", text: "불", effects: { streak: -99 }, result_text: "오답", tip: "불은 火입니다." }] },
      { id: "h2", chapter: 1, title: "火", situation: "이 한자의 뜻은?", next: "END", choices: [
        { id: "a", text: "물", effects: { streak: -99 }, result_text: "오답", tip: "물은 水입니다." },
        { id: "b", text: "불", effects: { score: 10, streak: 1 }, result_text: "정답: 불 화", tip: "火는 타오르는 불꽃 모양입니다." }] }],
    endings: [{ id: "perfect", title: "만점", when: [{ stat: "score", op: ">=", value: 20 }] }, { id: "try", title: "다시", when: [] }],
  };
  const r = play(hanja, (opts, g) => opts.find((o) => o.choice.result_text.startsWith("정답")) || opts[0]);
  assert.equal(r.ending.id, "perfect");
  assert.equal(r.final.streak, 2);
});

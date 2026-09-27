// CHOICE100 BOARD 엔진 테스트(6-66) - node --test game_lab/board/test/board.test.js
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("path");
const fs = require("fs");
const { Game, validate, parityOf, REWARD_TYPES, defaultRng } = require("../engine.js");
const { play, simulate, summarize, rng: seeded } = require("../sim.js");

const load = () => JSON.parse(fs.readFileSync(path.join(__dirname, "..", "world", "world.json"), "utf8"));
// 원하는 눈이 나오게 하는 rng(엔진은 1 + floor(rng*6))
const faceRng = (faces) => { let i = 0; return () => (faces[i++ % faces.length] - 1) / 6 + 0.01; };

function toQuiz(g, correct) {
  const q = g.quiz();
  return g.answer(correct ? q.correct : (q.correct + 1) % 4);
}

test("1 quiz schema: 15 quizzes with topic/era/region/source/source_date, 4 unique choices", () => {
  const d = load();
  assert.deepEqual(validate(d), []);
  assert.ok(d.quizzes.length >= 10);
  for (const q of d.quizzes) {
    assert.match(q.source, /^Wikipedia\(영문\) '.+' https:\/\/en\.wikipedia\.org\/wiki\//);
    assert.match(q.source_date, /^\d{4}-\d{2}-\d{2}$/);
    assert.equal(new Set(q.choices).size, 4);
  }
  assert.deepEqual(REWARD_TYPES, ["DICE_PARITY", "MOVE_BONUS", "TRADE_BONUS", "EXPLORE_TOKEN", "PROTECTION", "COIN"]);
});

test("board has 20+ cells with required type counts, START first", () => {
  const d = load();
  const count = (t) => d.board.filter((c) => c.type === t).length;
  assert.ok(d.board.length >= 20);
  assert.equal(d.board[0].type, "START");
  for (const [t, n] of Object.entries({ CITY: 4, TRADE: 4, EXPLORE: 4, EVENT: 3, QUIZ: 3, BONUS: 2 })) assert.ok(count(t) >= n, t);
});

test("2-4 correct → reward + parity privilege; wrong → no privilege; phases enforced", () => {
  const g = new Game(load(), faceRng([3]));
  assert.throws(() => g.declare("odd"), /parity/);
  assert.throws(() => g.roll(), /roll/);
  const r = toQuiz(g, true);
  assert.equal(r.correct, true);
  assert.equal(r.privilege, true);
  assert.equal(g.state.vars.knowledge, 1);
  assert.equal(g.state.phase, "parity");
  assert.throws(() => g.roll(), /roll/); // 특권이 있으면 선언을 거친다
  assert.throws(() => g.declare("prime"), /odd\/even/);

  const h = new Game(load(), faceRng([3]));
  const w = toQuiz(h, false);
  assert.equal(w.correct, false);
  assert.equal(w.privilege, false);
  assert.equal(h.state.vars.knowledge, 0);
  assert.equal(h.state.phase, "roll");
  assert.throws(() => h.declare("odd"), /parity/); // 오답이면 선언 불가
  const out = h.roll();
  assert.equal(out.parity, null);
  assert.equal(out.hit, null);
});

test("5-6 dice 1..6 and parity: hit iff declared parity matches the face (no hidden change)", () => {
  for (let face = 1; face <= 6; face++) for (const p of ["odd", "even"]) {
    const g = new Game(load(), faceRng([face]));
    toQuiz(g, true);
    const out = g.declare(p);
    assert.equal(out.roll, face);
    assert.equal(out.hit, parityOf(face) === p, `${face} ${p}`);
    if (out.hit) assert.deepEqual(g.state.steer, [face - 1, face, face + 1].filter((m) => m >= 1));
    else assert.notEqual(g.state.phase, "steer");
  }
});

test("18/23 probability: default rng is uniform (60k rolls, chi-square) and odd/even are 3/6 each", () => {
  const r = defaultRng();
  const faces = [0, 0, 0, 0, 0, 0];
  const N = 60000;
  for (let i = 0; i < N; i++) faces[Math.floor(r() * 6)] += 1;
  const e = N / 6;
  const chi = faces.reduce((a, o) => a + ((o - e) ** 2) / e, 0);
  assert.ok(chi < 20.52, `chi-square ${chi.toFixed(2)} (df=5, p=0.001 한계 20.52) ${faces}`);
  const odd = faces[0] + faces[2] + faces[4];
  assert.ok(Math.abs(odd / N - 0.5) < 0.01, `odd ${odd / N}`);
});

test("7-8 movement, wrap past START gives lap bonus, position always on board", () => {
  const d = load();
  const g = new Game(d, faceRng([6]));
  const L = d.board.length;
  let turns = 0;
  while (g.state.phase !== "end" && turns < 40) {
    if (g.state.phase === "quiz") toQuiz(g, false);
    if (g.state.phase === "roll") g.roll();
    if (g.state.phase === "cell") {
      if (g.cell().type === "QUIZ") g.answerCellQuiz(0);
      else g.act(g.cellOptions().find((o) => o.enabled && !o.choice.cost && !o.choice.buy && !o.choice.sell).choice.id);
    }
    assert.ok(g.state.pos >= 0 && g.state.pos < L);
    if (g.state.phase === "turn_end") { g.nextTurn(); turns += 1; }
  }
  assert.equal(g.state.phase, "end");
  assert.equal(turns, d.turns);
  assert.equal(g.state.laps, Math.floor((6 * d.turns) / L));
  assert.ok(g.state.vars.coin >= d.lap_bonus.coin * g.state.laps - 50);
});

test("steer lets the player pick the landing cell", () => {
  const d = load();
  const g = new Game(d, faceRng([3]));
  toQuiz(g, true);
  g.declare("odd");
  const opts = g.steerOptions();
  assert.deepEqual(opts.map((o) => o.steps), [2, 3, 4]);
  assert.throws(() => g.steerTo(5), /고를 수 없는/);
  g.steerTo(4);
  assert.equal(g.state.pos, 4);
  assert.equal(g.cell().type, d.board[4].type);
});

function landOn(type, face = null) {
  const d = load();
  const i = d.board.findIndex((c, k) => k > 0 && k <= 6 && c.type === type);
  assert.ok(i > 0, `no ${type} within 1..6`);
  const g = new Game(d, faceRng([face || i]));
  toQuiz(g, false);
  g.roll();
  assert.equal(g.cell().type, type);
  return g;
}

test("9 CITY: library costs coin and gives knowledge; sell disabled without cargo; 10 TRADE buy then sell for profit", () => {
  const g = landOn("CITY"); // 리스본
  const opts = g.cellOptions();
  assert.ok(opts.filter((o) => o.choice.sell).every((o) => !o.enabled && o.reason === "팔 물건 없음"));
  const r = g.act("lib");
  assert.deepEqual(r.deltas, { coin: -10, knowledge: 1 });

  const d = load();
  const t = new Game(d, faceRng([2]));
  toQuiz(t, false);
  t.roll(); // 지중해 시장: 비단 구매 20×3
  assert.equal(t.cell().type, "TRADE");
  t.act("buy_silk");
  assert.equal(t.state.cargo.silk, 3);
  assert.equal(t.state.vars.coin, 100 - 60);
  assert.throws(() => t.act("pass"), /cell/); // 한 칸에서 한 번
  t.nextTurn();
  t.state.pos = 0; t.state.phase = "quiz";
  toQuiz(t, false);
  t.rng = faceRng([1]);
  t.roll(); // 리스본: 비단 26에 판매
  const s = t.act("sell_silk");
  assert.equal(s.deltas.coin, 3 * 26);
  assert.equal(t.state.cargo.silk, 0);
});

test("cargo cap and coin limits disable buying (never negative)", () => {
  const g = landOn("TRADE", 2);
  g.state.vars.coin = 10;
  assert.equal(g.cellOptions().find((o) => o.choice.buy).enabled, false);
  assert.throws(() => g.act("buy_silk"), /코인/);
  g.state.vars.coin = 999;
  g.state.cargo.spice = 5;
  assert.match(g.cellOptions().find((o) => o.choice.buy).reason, /짐칸/);
});

test("11 EXPLORE: knowledge gate doubles the find; 13 lesson comes with source", () => {
  const d = load();
  const i = d.board.findIndex((c) => c.type === "EXPLORE");
  const need = d.board[i].choices.find((c) => c.id === "explore").bonus_if.gte;
  const low = new Game(d, faceRng([i]));
  toQuiz(low, false); low.roll();
  const r1 = low.act("explore");
  assert.deepEqual(r1.deltas, { coin: -10, exploration: 1 });
  assert.equal(r1.bonus, false);
  assert.match(r1.lesson.source, /wikipedia/);
  const high = new Game(d, faceRng([i]));
  high.state.vars.knowledge = need;
  toQuiz(high, false); high.roll();
  const r2 = high.act("explore");
  assert.equal(r2.bonus, true);
  assert.deepEqual(r2.deltas, { coin: 10, exploration: 2 });
});

test("12 EVENT and BONUS apply automatically with lesson; QUIZ cell gives bonus quiz", () => {
  const d = load();
  const e = d.board.findIndex((c) => c.type === "EVENT");
  const g = new Game(d, faceRng([e]));
  toQuiz(g, false); g.roll();
  assert.equal(g.state.phase, "turn_end");
  assert.deepEqual(g.state.cell_result.effects, d.board[e].effect);
  assert.ok(g.state.cell_result.lesson.text && g.state.cell_result.lesson.source);
  const qi = d.board.findIndex((c) => c.type === "QUIZ");
  const h = new Game(d, faceRng([qi]));
  toQuiz(h, false); h.roll();
  assert.equal(h.state.phase, "cell");
  const cq = h.cellQuiz();
  assert.notEqual(cq.id, h.state.answered.quiz); // 방금 푼 문제와 다름
  const r = h.answerCellQuiz(cq.correct);
  assert.deepEqual(r.deltas, d.board[qi].quiz);
});

test("14-15 player state stays valid, restore rejects bad saves", () => {
  const d = load();
  const g = new Game(d, seeded(3));
  toQuiz(g, true);
  const saved = g.serialize();
  const r = Game.restore(d, saved);
  assert.equal(r.state.phase, "parity");
  for (const bad of ["", "{", JSON.stringify({ v: 9 }), saved.replace(/"pos":\d+/, '"pos":999'), saved.replace(/"coin":\d+/, '"coin":null')]) {
    assert.equal(Game.restore(d, bad), null, bad.slice(0, 30));
  }
  assert.equal(Game.restore({ ...d, version: "x" }, saved), null);
});

test("16-17 1,200 simulated games: no impossible state, every ending reachable, knowledge raises score, hit rate ~0.5", () => {
  const d = load();
  const rows = simulate(d, 100);
  assert.equal(rows.length, 1200);
  const s = summarize(rows);
  for (const e of d.endings) assert.ok(s.endings[e.id] > 0, `${e.id}: ${JSON.stringify(s.endings)}`);
  assert.ok(Math.abs(s.dice.hit_rate - 0.5) < 0.02, `hit ${s.dice.hit_rate}`);
  const exp = s.dice.rolls / 6;
  for (const f of s.dice.faces) assert.ok(Math.abs(f - exp) / exp < 0.06, `faces ${s.dice.faces}`);
  for (const strat of ["trader", "explorer", "scholar", "random"]) {
    assert.ok(s.by[`${strat}@0.9`].score > s.by[`${strat}@0.3`].score, `${strat}: 지식 → 게임 실력`);
  }
});

test("engine is domain-free: a tiny finance-flavored board runs on the same engine", () => {
  const fin = {
    id: "fin-board-demo", version: "t", turns: 2, dice: { sides: 6 }, rewards: { DICE_PARITY: { on_hit: { steer: 1 } } },
    stats: [{ key: "coin", label: "현금", min: 0 }], goods: [], cargo_cap: 0, start: { coin: 100 }, score_weights: { coin: 1 },
    quizzes: [1, 2, 3].map((n) => ({ id: `f${n}`, question: "이자가 붙는 것은?", choices: ["대출", "현금", "공기", "비"], correct: 0, explanation: "대출에는 이자가 붙는다.",
      topic: "이자", era: "-", region: "-", source: "게임 설정", source_date: "2026-09-27" })),
    board: [{ id: "s", type: "START", name: "시작", region: "-" }, ...Array.from({ length: 7 }, (_, k) => ({ id: `b${k}`, type: "BONUS", name: "월급", region: "-", effect: { coin: 10 } }))],
    endings: [{ id: "rich", title: "부자", when: [{ stat: "coin", op: ">=", value: 120 }] }, { id: "ok", title: "보통", when: [] }],
  };
  const r = play(fin, { acc: 1, strategy: "random", seed: 5 });
  assert.equal(r.ending.id, "rich");
});

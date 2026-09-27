// CHOICE100 RPG 테스트(6-67) - node --test game_lab/rpg/test/rpg.test.js
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("path");
const fs = require("fs");
const { Game, validate, HISTORICAL, RELATIONS, ITEM_TYPES } = require("../engine.js");
const Board = require("../../board/engine.js");
const { simulate, summarize, play, rng } = require("../sim.js");

const load = () => JSON.parse(fs.readFileSync(path.join(__dirname, "..", "korea", "korea.json"), "utf8"));
const newGame = (d = load(), seed = 3) => new Game(d, { BoardGame: Board.Game, rng: rng(seed) });
function toStory(g) { g.completeMain("m1"); g.passGate("gate_joljbon"); g.startStory("jumong"); return g; }
function runTo(g, type, answer = (q) => q.correct, choose = (s, g2) => s.options.find((o) => g2.optionEnabled(o)).id) {
  for (let k = 0; k < 100; k++) {
    const s = g.step();
    if (!s || s.type === type) return s;
    if (s.type === "quiz") g.advance(answer(g.quiz()));
    else if (s.type === "choice") g.advance(choose(s, g));
    else if (s.type === "board") { finishBoard(g); g.advance(); }
    else g.advance();
  }
  throw new Error("못 찾음 " + type);
}
function finishBoard(g, acc = 1) {
  const b = g.boardGame();
  const r = rng(9);
  while (b.state.phase !== "end") {
    const ph = b.state.phase;
    if (ph === "quiz") { const q = b.quiz(); b.answer(acc ? q.correct : (q.correct + 1) % 4); }
    else if (ph === "parity") b.declare("odd");
    else if (ph === "roll") b.roll();
    else if (ph === "steer") b.steerTo(b.steerOptions()[0].steps);
    else if (ph === "cell") { if (b.cell().type === "QUIZ") b.answerCellQuiz(b.cellQuiz().correct); else b.act(b.cellOptions().find((o) => o.enabled).choice.id); }
    else if (ph === "turn_end") b.nextTurn();
    if (r() > 2) break;
  }
  return g.finishBoard();
}

test("schemas: data valid; hero/story/chapter/relation/item/skill/region/gate/main all typed with historical_status", () => {
  const d = load();
  assert.deepEqual(validate(d), []);
  assert.deepEqual(HISTORICAL, ["historical_fact", "historical_record", "legend", "game_setting"]);
  assert.deepEqual(RELATIONS, ["FRIEND", "COMPANION", "MENTOR", "RIVAL", "ALLY", "NEUTRAL"]);
  assert.deepEqual(ITEM_TYPES, ["ARTIFACT", "KNOWLEDGE", "POLICY", "SKILL"]);
  for (const h of d.heroes) for (const k of ["id", "name", "era", "region", "role", "stats", "skills", "items", "relationships", "knowledge", "sources", "chapters"]) assert.ok(k in h, `${h.id}.${k}`);
  assert.ok(d.heroes.length >= 4);
  assert.deepEqual(d.heroes.filter((h) => h.playable).map((h) => h.id), ["jumong"]);
  const st = d.stories[0];
  assert.equal(st.chapters[0].steps.at(-1).type, "end");
  for (const r of d.regions) for (const k of ["id", "name", "era", "recommended_level", "difficulty", "hero_stories", "events", "cities", "trade", "exploration", "quests"]) assert.ok(k in r, `${r.id}.${k}`);
  assert.deepEqual(d.stages.map((s) => s.id), ["korea", "china_japan", "eurasia"]);
  const genghis = d.main_story.find((m) => m.id === "m_genghis");
  assert.equal(genghis.historical_status, "game_setting");
  assert.match(genghis.desc, /역사적 사실이 아닌/);
  const bow = d.items.find((i) => i.id === "jumong_bow");
  assert.equal(bow.historical_status, "game_setting");
  assert.match(bow.note, /실제 유물이나 주몽의 실제 소유물이 아니다/);
});

test("validate catches broken references", () => {
  const d = load();
  d.stories[0].chapters[0].steps[2].quiz = "nope";
  d.heroes[0].skills = ["ghost"];
  d.items[0].historical_status = "maybe";
  d.boards.joljbon_hunt.merge.push({ from: "coin", to: "gold", rate: 1 });
  const errs = validate(d);
  for (const needle of ["quiz nope", "skill ghost", "item jumong_bow: historical_status", "merge coin→gold"]) assert.ok(errs.some((e) => e.includes(needle)), needle);
});

test("time gate + main story + hero select: jumong playable, others locked with reasons", () => {
  const g = newGame();
  assert.throws(() => g.startStory("jumong"), /지역/); // 시간의 문 먼저
  g.completeMain("m1");
  assert.deepEqual(g.state.main_done, ["m1"]);
  assert.equal(g.passGate("gate_joljbon").id, "joljbon");
  assert.throws(() => g.passGate("gate_hanyang"), /레벨 5/);
  const cards = Object.fromEntries(g.heroCards().map((c) => [c.hero.id, c]));
  assert.equal(cards.jumong.playable, true);
  for (const id of ["sejong", "yisunsin", "jangbogo"]) { assert.equal(cards[id].playable, false); assert.ok(cards[id].reason); assert.throws(() => g.startStory(id), /잠긴 영웅/); }
  g.startStory("jumong");
  assert.equal(g.step().type, "narration");
});

test("quiz reward: correct gives EXP+knowledge; wrong gives base EXP and explanation; game continues", () => {
  const g = toStory(newGame());
  runTo(g, "quiz");
  const q = g.quiz();
  const r = g.advance(q.correct);
  assert.equal(r.correct, true);
  assert.equal(r.gained.exp, 60);
  assert.deepEqual(r.gained.knowledge, ["k_jumong_name"]);
  assert.ok(r.source.includes("encykorea"));
  const h = toStory(newGame());
  runTo(h, "quiz");
  const w = h.advance((h.quiz().correct + 1) % 4);
  assert.equal(w.correct, false);
  assert.equal(w.gained.exp, 20);
  assert.deepEqual(w.gained.knowledge, []);
  assert.ok(w.explanation.length > 10);
  assert.equal(h.step().type, "reward"); // 계속 진행
});

test("item and exp/level: bow adds military; level table and level-up", () => {
  const g = toStory(newGame());
  runTo(g, "reward");
  assert.ok(g.state.items.includes("jumong_bow"));
  assert.equal(g.state.stats.military, 3);
  assert.equal(g.state.level, 1);
  const lv = g._grant({ exp: 100 });
  assert.deepEqual(lv.level_up, [2]);
  assert.equal(g.levelInfo().next, 220);
  const lv2 = g._grant({ exp: 1000 });
  assert.deepEqual(lv2.level_up, [3, 4, 5, 6]); // 60(퀴즈) + 100 + 1000 = 1160 → Lv6(1000~)
});

test("board integration: story board step runs a 6-66 board turn and merges into RPG state", () => {
  const g = toStory(newGame());
  runTo(g, "board");
  const b = g.boardGame();
  assert.ok(b instanceof Board.Game);
  assert.equal(b.data.turns, 1);
  assert.throws(() => g.advance(), /보드 단계가 끝나지 않음/);
  const before = { ...g.state.stats };
  const m = finishBoard(g);
  assert.equal(g.state.board.phase, "done");
  assert.equal(m.board.coin - 20, g.state.stats.food - before.food); // coin→food
  assert.ok(g.state.stats.exp >= before.exp);
  g.advance();
  assert.equal(g.state.board, null);
});

test("board skill bonus: 궁술 adds food when the hunt explored", () => {
  const d = load();
  const g = newGame(d);
  g.state.skills.push("gungsul");
  g.state.regions.push("joljbon");
  g._boardStart({ board: "joljbon_hunt" });
  const b = g.boardGame();
  b.state.vars.exploration = 1;
  b.state.phase = "end";
  const m = g.finishBoard();
  assert.equal(m.skill_bonus, true);
});

test("rival → ally via choice; stat requirement gates an option", () => {
  const g = toStory(newGame());
  runTo(g, "relation");
  g.advance();
  assert.equal(g.state.relations.songyang, "RIVAL");
  const s = g.step();
  assert.equal(s.type, "choice");
  const archery = s.options.find((o) => o.id === "archery");
  assert.equal(g.optionEnabled(archery), true); // 활(군사 3) 덕분
  g.state.stats.military = 0;
  assert.equal(g.optionEnabled(archery), false);
  assert.throws(() => g.advance("archery"), /조건/);
  const r = g.advance("talk");
  assert.equal(g.state.relations.songyang, "ALLY");
  assert.deepEqual(r.gained.knowledge, ["k_songyang"]);
});

test("companion unlock gives skill 궁술 + military, relation COMPANION; skill used later in winter choice", () => {
  const g = toStory(newGame());
  runTo(g, "companion");
  const mil = g.state.stats.military;
  const ent = g.state.entered.gained;
  assert.equal(ent.companion, "jumong");
  assert.ok(g.state.companions.includes("jumong"));
  assert.equal(g.state.relations.jumong, "COMPANION");
  assert.ok(g.state.skills.includes("gungsul"));
  assert.equal(g.state.stats.military, mil); // 합류는 들어갈 때 이미 반영
  g.advance(); // → region
  g.advance(); // → winter choice
  const r = g.advance("hunt");
  assert.equal(r.bonus, true);
  assert.match(r.result, /궁술/);
});

test("knowledge → policy interface: 진대법 unlocks from knowledge k_jindae", () => {
  const g = toStory(newGame());
  runTo(g, "choice", undefined, (s) => s.options[0].id);
  g.advance("talk");
  runTo(g, "choice");
  const r = g.advance("share");
  assert.deepEqual(r.gained.policies, ["jindae"]);
  assert.ok(g.state.policies.includes("jindae"));
  assert.match(r.lesson, /194년/);
});

test("region gate follows level: all-correct opens 삼국 항쟁, all-wrong does not", () => {
  const good = toStory(newGame());
  runTo(good, "end");
  assert.ok(good.state.regions.includes("samguk"));
  const bad = toStory(newGame());
  runTo(bad, "end", (q) => (q.correct + 1) % 4, (s, g2) => s.options.filter((o) => g2.optionEnabled(o)).at(-1).id);
  assert.ok(!bad.state.regions.includes("samguk"));
  assert.equal(bad.regionCards().find((c) => c.region.id === "samguk").unlocked, false);
});

test("hero story completes chapter, marks main m2, story done, cannot restart same finished story", () => {
  const g = toStory(newGame());
  runTo(g, "end");
  const r = g.advance();
  assert.equal(r.type, "end");
  assert.equal(r.story_done, true);
  assert.ok(g.state.main_done.includes("m2"));
  assert.equal(g.state.current, null);
  assert.throws(() => g.startStory("jumong"), /이미 끝난/);
});

test("save/restore mid-story (board step restarts cleanly), rejects bad saves", () => {
  const d = load();
  const g = toStory(newGame(d));
  runTo(g, "board");
  const saved = g.serialize();
  const r = Game.restore(d, saved, { BoardGame: Board.Game });
  assert.equal(r.step().type, "board");
  assert.ok(r.boardGame());
  for (const bad of ["", "{", JSON.stringify({ v: 2 }), saved.replace(/"exp":\d+/, '"exp":null')]) assert.equal(Game.restore(d, bad, { BoardGame: Board.Game }), null);
  assert.equal(Game.restore({ ...d, version: "x" }, saved, { BoardGame: Board.Game }), null);
});

test("300 simulated slices: always finish, valid state, companion 100%, knowledge raises level", () => {
  const d = load();
  const s = summarize(simulate(d, 100));
  assert.equal(s.runs, 300);
  for (const b of Object.values(s.by)) { assert.equal(b.companion, b.n); assert.equal(b.bow, b.n); }
  assert.ok(s.by.acc1.exp.median > s.by.acc0.exp.median);
  assert.equal(s.by.acc1.samguk, 100);
  assert.equal(s.by.acc0.samguk, 0);
  assert.deepEqual(Object.keys(s.by.acc1.level), ["3"]);
});

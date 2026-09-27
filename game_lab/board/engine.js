/*
 * CHOICE100 BOARD 엔진 (6-66 G0/G1) - QUIZ → REWARD → DICE → BOARD → 칸 효과 → 다음 QUIZ.
 * DOM 없음, 도메인(세계사·금융·한자) 모름. 게임 데이터(JSON)가 퀴즈·보드·보상·엔딩을 정한다.
 *
 * 주사위 원칙(투명·조작 금지):
 *   - 6면체, 매 굴림은 rng() 하나로 1~6 균등(기본 rng = crypto.getRandomValues, 없으면 Math.random).
 *   - 정답 보상 DICE_PARITY = "굴리기 전에 홀/짝을 선언하는 권리". 주사위 확률은 바꾸지 않는다 → 적중 확률은 정확히 3/6.
 *   - 적중하면 on_hit 보상(G1: steer = 도착 칸을 -1/0/+1 중에서 고름). 빗나가면 굴린 만큼 그대로 이동.
 *   - 오답이면 선언 권리 없음 → 그냥 굴린다(게임은 계속된다).
 *
 * phase: quiz → (정답) parity | (오답) roll → [적중] steer → cell → turn_end → quiz … → end
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.Choice100Board = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const REWARD_TYPES = ["DICE_PARITY", "MOVE_BONUS", "TRADE_BONUS", "EXPLORE_TOKEN", "PROTECTION", "COIN"]; // G1 구현: DICE_PARITY
  const CELL_TYPES = ["START", "CITY", "TRADE", "EXPLORE", "QUIZ", "EVENT", "BONUS", "REST"];
  const SAVE_VERSION = 1;

  function defaultRng() {
    const c = (typeof globalThis !== "undefined" && globalThis.crypto) || null;
    if (c && c.getRandomValues) {
      const a = new Uint32Array(1);
      return () => { c.getRandomValues(a); return a[0] / 4294967296; };
    }
    return Math.random;
  }

  function validate(data) {
    const errors = [];
    const err = (m) => errors.push(m);
    if (!data || typeof data !== "object") return ["data 없음"];
    const stats = new Set((data.stats || []).map((s) => s.key));
    const goods = new Set((data.goods || []).map((g) => g.key));
    for (const s of stats) if (!Number.isFinite((data.start || {})[s])) err(`start.${s} 없음`);
    if (!(data.dice && data.dice.sides === 6)) err("dice.sides는 6");
    if (!(data.turns >= 1)) err("turns");
    for (const r of Object.keys(data.rewards || {})) if (!REWARD_TYPES.includes(r)) err(`모르는 reward ${r}`);
    const ids = new Set();
    for (const q of data.quizzes || []) {
      if (ids.has(q.id)) err(`quiz 중복 ${q.id}`);
      ids.add(q.id);
      for (const k of ["question", "explanation", "topic", "era", "region", "source", "source_date"]) if (!q[k]) err(`${q.id}: ${k} 없음`);
      if (!Array.isArray(q.choices) || q.choices.length !== 4 || new Set(q.choices).size !== 4) err(`${q.id}: 선택지 4개(중복 없음)`);
      if (!(Number.isInteger(q.correct) && q.correct >= 0 && q.correct < 4)) err(`${q.id}: correct 범위`);
    }
    const effects = (w, eff) => { for (const [k, v] of Object.entries(eff || {})) if (!stats.has(k) || !Number.isFinite(v)) err(`${w}: 효과 ${k}`); };
    const board = data.board || [];
    if (board.length < 2) err("board 칸 부족");
    if (!board.length || board[0].type !== "START") err("첫 칸은 START");
    board.forEach((c, i) => {
      const w = `cell ${i} ${c.name}`;
      if (!CELL_TYPES.includes(c.type)) err(`${w}: type ${c.type}`);
      if (!c.name || !c.region) err(`${w}: name/region 없음`);
      effects(w, c.effect);
      if (c.lesson && !(c.lesson.text && c.lesson.source)) err(`${w}: lesson은 text+source`);
      if (c.type === "QUIZ" && !c.quiz) err(`${w}: QUIZ 칸은 quiz 보상`);
      for (const ch of c.choices || []) {
        effects(`${w}.${ch.id}`, ch.effects);
        if (ch.buy && (!goods.has(ch.buy.good) || !(ch.buy.qty > 0) || !(ch.buy.price > 0))) err(`${w}.${ch.id}: buy`);
        if (ch.sell && (!goods.has(ch.sell.good) || !(ch.sell.price > 0))) err(`${w}.${ch.id}: sell`);
        if (ch.bonus_if && (!stats.has(ch.bonus_if.stat) || !Number.isFinite(ch.bonus_if.gte))) err(`${w}.${ch.id}: bonus_if`);
      }
      if ((c.choices || []).length && !(c.choices || []).some((ch) => !ch.buy && !ch.sell && !ch.cost)) err(`${w}: 늘 고를 수 있는 선택지 하나는 필요`);
    });
    if ((data.quizzes || []).length < data.turns) err("퀴즈 수 < 턴 수(한 판에 같은 문제 반복)");
    const endings = data.endings || [];
    if (!endings.length || (endings[endings.length - 1].when || []).length) err("마지막 엔딩은 조건 없음");
    return errors;
  }

  class Game {
    constructor(data, rng = defaultRng()) {
      const errors = validate(data);
      if (errors.length) throw new Error("보드 데이터 오류: " + errors.slice(0, 5).join(" / "));
      this.data = data;
      this.rng = rng;
      this.start();
    }

    start() {
      const cargo = Object.fromEntries(this.data.goods.map((g) => [g.key, 0]));
      this.state = { vars: { ...this.data.start }, cargo, pos: 0, turn: 1, laps: 0, phase: "quiz", quiz_order: this._shuffle(this.data.quizzes.map((q) => q.id)),
                     quiz_i: 0, quiz: null, answered: null, privilege: false, parity: null, roll: null, hit: null, steer: null,
                     cell_quiz: null, log: [], correct: 0, hits: 0, declared: 0, visited: [0] };
      this._drawQuiz();
      return this.state;
    }

    // ---- 조회 ----
    quiz() { return this.data.quizzes.find((q) => q.id === this.state.quiz); }
    cell(i = this.state.pos) { return this.data.board[((i % this.data.board.length) + this.data.board.length) % this.data.board.length]; }
    cargoCount() { return Object.values(this.state.cargo).reduce((a, b) => a + b, 0); }
    score() {
      const w = this.data.score_weights || {};
      return Object.entries(w).reduce((a, [k, m]) => a + (this.state.vars[k] || 0) * m, 0);
    }

    // ---- 1. 퀴즈 ----
    answer(i) {
      this._need("quiz");
      const q = this.quiz();
      if (!(Number.isInteger(i) && i >= 0 && i < 4)) throw new Error("선택지 범위");
      const correct = i === q.correct;
      this.state.answered = { quiz: q.id, pick: i, correct };
      if (correct) {
        this.state.correct += 1;
        this._apply(this.data.quiz_reward || {});
      }
      this.state.privilege = correct && !!this.data.rewards.DICE_PARITY;
      this.state.phase = this.state.privilege ? "parity" : "roll";
      return { correct, answer: q.correct, explanation: q.explanation, privilege: this.state.privilege };
    }

    // ---- 2. 홀짝 선언(정답 보상) 또는 그냥 굴리기 ----
    declare(parity) {
      this._need("parity");
      if (parity !== "odd" && parity !== "even") throw new Error("odd/even");
      this.state.parity = parity;
      this.state.declared += 1;
      return this._roll();
    }
    roll() {
      this._need("roll");
      this.state.parity = null;
      return this._roll();
    }
    _roll() {
      const n = 1 + Math.floor(this.rng() * this.data.dice.sides);
      if (!(n >= 1 && n <= 6)) throw new Error("rng 범위 오류");
      const hit = this.state.parity ? (n % 2 === 1) === (this.state.parity === "odd") : null;
      this.state.roll = n;
      this.state.hit = hit;
      if (hit) this.state.hits += 1;
      const steer = hit && this.data.rewards.DICE_PARITY && this.data.rewards.DICE_PARITY.on_hit && this.data.rewards.DICE_PARITY.on_hit.steer;
      if (steer) {
        this.state.steer = [-steer, 0, steer].map((d) => n + d).filter((m) => m >= 1);
        this.state.phase = "steer";
      } else {
        this._move(n);
      }
      return { roll: n, parity: this.state.parity, hit, steer: this.state.steer };
    }

    // ---- 3. 적중 보상: 도착 칸 고르기 ----
    steerTo(steps) {
      this._need("steer");
      if (!this.state.steer.includes(steps)) throw new Error("고를 수 없는 이동");
      this._move(steps);
      return this.cell();
    }
    steerOptions() { return (this.state.steer || []).map((m) => ({ steps: m, cell: this.cell(this.state.pos + m) })); }

    _move(steps) {
      const L = this.data.board.length;
      const from = this.state.pos;
      const to = from + steps;
      const passedStart = to >= L;
      this.state.pos = to % L;
      this.state.steer = null;
      const events = [];
      if (passedStart) {
        this.state.laps += 1;
        this._apply(this.data.lap_bonus || {});
        if (this.data.lap_bonus) events.push("lap");
      }
      this.state.visited.push(this.state.pos);
      this.state.moved = { from, to: this.state.pos, steps, passedStart };
      const c = this.cell();
      this.state.cell_events = events;
      if (c.type === "QUIZ") {
        this.state.cell_quiz = this._takeQuiz();
        this.state.phase = "cell";
      } else if ((c.choices || []).length) {
        this.state.phase = "cell";
      } else {
        this._apply(c.effect);
        this.state.cell_result = { auto: true, effects: c.effect || {}, lesson: c.lesson || null };
        this.state.phase = "turn_end";
      }
    }

    // ---- 4. 칸 선택(도시·교역·탐험) ----
    cellOptions() {
      const c = this.cell();
      return (c.choices || []).map((ch) => ({ choice: ch, ...this._can(ch) }));
    }
    _can(ch) {
      const v = this.state.vars;
      if (ch.buy) {
        const cost = ch.buy.qty * ch.buy.price;
        if (v.coin < cost) return { enabled: false, reason: `코인 ${cost} 필요` };
        if (this.cargoCount() + ch.buy.qty > this.data.cargo_cap) return { enabled: false, reason: `짐칸 부족(최대 ${this.data.cargo_cap})` };
      }
      if (ch.sell && !this.state.cargo[ch.sell.good]) return { enabled: false, reason: "팔 물건 없음" };
      if (ch.cost && v.coin < ch.cost) return { enabled: false, reason: `코인 ${ch.cost} 필요` };
      return { enabled: true, reason: "" };
    }
    act(choiceId) {
      this._need("cell");
      const c = this.cell();
      const ch = (c.choices || []).find((x) => x.id === choiceId);
      if (!ch) throw new Error("없는 선택: " + choiceId);
      const can = this._can(ch);
      if (!can.enabled) throw new Error(can.reason);
      const before = { ...this.state.vars };
      const extra = [];
      if (ch.cost) this.state.vars.coin -= ch.cost;
      if (ch.buy) {
        this.state.vars.coin -= ch.buy.qty * ch.buy.price;
        this.state.cargo[ch.buy.good] += ch.buy.qty;
      }
      if (ch.sell) {
        const n = this.state.cargo[ch.sell.good];
        this.state.vars.coin += n * ch.sell.price;
        this.state.cargo[ch.sell.good] = 0;
        extra.push({ sold: n, good: ch.sell.good, price: ch.sell.price });
      }
      this._apply(ch.effects);
      let bonus = false;
      if (ch.bonus_if && this.state.vars[ch.bonus_if.stat] >= ch.bonus_if.gte) {
        this._apply(ch.bonus_if.effects);
        bonus = true;
      }
      this._clamp();
      const deltas = Object.fromEntries(Object.keys(before).filter((k) => before[k] !== this.state.vars[k]).map((k) => [k, this.state.vars[k] - before[k]]));
      this.state.cell_result = { choice: ch.id, deltas, bonus, extra, result_text: bonus ? ch.bonus_if.text : ch.result_text, lesson: ch.lesson || c.lesson || null };
      this.state.log.push({ turn: this.state.turn, cell: this.state.pos, choice: ch.id });
      this.state.phase = "turn_end";
      return this.state.cell_result;
    }

    // ---- 4'. QUIZ 칸: 보너스 퀴즈(주사위 보상 없음) ----
    cellQuiz() { return this.data.quizzes.find((q) => q.id === this.state.cell_quiz); }
    answerCellQuiz(i) {
      this._need("cell");
      const c = this.cell();
      if (c.type !== "QUIZ") throw new Error("QUIZ 칸 아님");
      const q = this.cellQuiz();
      const correct = i === q.correct;
      const before = { ...this.state.vars };
      if (correct) { this.state.correct += 1; this._apply(c.quiz); }
      this._clamp();
      const deltas = Object.fromEntries(Object.keys(before).filter((k) => before[k] !== this.state.vars[k]).map((k) => [k, this.state.vars[k] - before[k]]));
      this.state.cell_result = { quiz: q.id, correct, answer: q.correct, explanation: q.explanation, deltas, lesson: null };
      this.state.phase = "turn_end";
      return this.state.cell_result;
    }

    // ---- 5. 다음 턴 ----
    nextTurn() {
      this._need("turn_end");
      this.state.cell_result = null;
      this.state.cell_quiz = null;
      this.state.answered = null;
      this.state.privilege = false;
      this.state.parity = null;
      this.state.roll = null;
      this.state.hit = null;
      if (this.state.turn >= this.data.turns) {
        this.state.phase = "end";
        return "end";
      }
      this.state.turn += 1;
      this._drawQuiz();
      this.state.phase = "quiz";
      return "quiz";
    }

    ending() {
      const v = { ...this.state.vars, score: this.score(), correct: this.state.correct, laps: this.state.laps };
      const ops = { ">=": (a, b) => a >= b, "<=": (a, b) => a <= b, ">": (a, b) => a > b, "<": (a, b) => a < b };
      for (const e of this.data.endings) if ((e.when || []).every((c) => ops[c.op](v[c.stat], c.value))) return { ...e, values: v };
      return null;
    }

    // ---- 저장/복원 ----
    serialize() { return JSON.stringify({ v: SAVE_VERSION, game: this.data.id, data_version: this.data.version, state: this.state }); }
    static restore(data, text, rng) {
      try {
        const o = JSON.parse(text);
        if (!o || o.v !== SAVE_VERSION || o.game !== data.id || o.data_version !== data.version) return null;
        const g = new Game(data, rng);
        const st = o.state;
        const phases = ["quiz", "parity", "roll", "steer", "cell", "turn_end", "end"];
        if (!st || !phases.includes(st.phase) || !Number.isInteger(st.pos) || st.pos < 0 || st.pos >= data.board.length) return null;
        if (!(st.turn >= 1 && st.turn <= data.turns)) return null;
        for (const s of data.stats) if (!Number.isFinite(st.vars?.[s.key])) return null;
        if (st.phase === "quiz" && !data.quizzes.some((q) => q.id === st.quiz)) return null;
        g.state = st;
        return g;
      } catch (e) {
        return null;
      }
    }

    // ---- 내부 ----
    _need(phase) { if (this.state.phase !== phase) throw new Error(`지금은 ${phase} 단계가 아님(현재 ${this.state.phase})`); }
    _apply(eff) {
      for (const [k, v] of Object.entries(eff || {})) this.state.vars[k] += v;
      this._clamp();
    }
    _clamp() {
      for (const s of this.data.stats) {
        let v = this.state.vars[s.key];
        if (!Number.isFinite(v)) v = this.data.start[s.key];
        v = Math.round(v);
        if (s.min !== undefined) v = Math.max(s.min, v);
        this.state.vars[s.key] = v;
      }
    }
    _shuffle(a) {
      const x = a.slice();
      for (let i = x.length - 1; i > 0; i--) { const j = Math.floor(this.rng() * (i + 1)); [x[i], x[j]] = [x[j], x[i]]; }
      return x;
    }
    _takeQuiz() {
      const id = this.state.quiz_order[this.state.quiz_i % this.state.quiz_order.length];
      this.state.quiz_i += 1;
      return id;
    }
    _drawQuiz() { this.state.quiz = this._takeQuiz(); }
  }

  const parityOf = (n) => (n % 2 === 1 ? "odd" : "even");
  return { Game, validate, parityOf, REWARD_TYPES, CELL_TYPES, defaultRng };
});

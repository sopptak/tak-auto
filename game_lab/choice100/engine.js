/*
 * CHOICE100 엔진 (6-64 G1) - DOM 없이 도는 순수 게임 규칙. 브라우저(window.Choice100)와 Node(require) 둘 다.
 *
 * 도메인(금융·한국사·한자…)을 모른다. 게임 데이터(JSON)가 모든 것을 정한다:
 *   stats      : 변수 정의(key, label, icon, min, max)
 *   derived    : 계산 변수(plus/minus 합) - 예: 순자산 = 현금 + 투자 + 자산 - 부채
 *   per_turn   : 선택 한 번마다 적용되는 선형 규칙 {stat, from, rate} 또는 {stat, amount}
 *   guards     : 바닥 규칙 - 예: 현금 < 0 이면 부족분을 부채로 옮기고 벌점
 *   scenarios  : {id, chapter, title, situation, on_enter, triggers, choices[{id, text, effects, moves, requires,
 *                 set_flags, add_per_turn, result_text, tip, next}], next}
 *   endings    : 위에서부터 조건을 보고 첫 번째로 맞는 것. 마지막은 조건 없음(기본).
 *   style      : (6-65) 선택의 실제 변화량으로 플레이 스타일을 센다 {rules:[{style, when:[{stat, op, value}]}], labels, balanced}
 *   score_stat : (6-65) 점수로 쓸 변수(없으면 score()는 null) - 학습게임이 별도 점수를 쓸 자리
 * 나중에 돌아오는 선택: set_flags + 다른 시나리오의 triggers. 엔진이 "어느 선택에서 왔는지"(echo)를 기록한다.
 * 무작위 없음: 같은 선택은 항상 같은 결과(G1 원칙 - 운빨 게임 금지).
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.Choice100 = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const SAVE_VERSION = 1;
  const OPS = { ">=": (a, b) => a >= b, "<=": (a, b) => a <= b, ">": (a, b) => a > b, "<": (a, b) => a < b, "==": (a, b) => a === b };

  function validate(data) {
    const errors = [];
    const err = (m) => errors.push(m);
    if (!data || typeof data !== "object") return ["data 없음"];
    const statKeys = new Set((data.stats || []).map((s) => s.key));
    const derived = new Set(Object.keys(data.derived || {}));
    const known = (k) => statKeys.has(k) || derived.has(k);
    if (!statKeys.size) err("stats 없음");
    for (const s of data.stats || []) if (!(s.key in (data.start || {}))) err(`start에 ${s.key} 없음`);
    const ids = new Set();
    for (const sc of data.scenarios || []) {
      if (ids.has(sc.id)) err(`중복 id ${sc.id}`);
      ids.add(sc.id);
    }
    if (!ids.size) err("scenarios 없음");
    if (!ids.has(data.first)) err(`first ${data.first} 없음`);
    const flagsSet = new Set();
    for (const sc of data.scenarios || []) for (const c of sc.choices || []) for (const f of c.set_flags || []) flagsSet.add(f);
    const triggerFlags = new Set();
    for (const sc of data.scenarios || []) for (const t of sc.triggers || []) triggerFlags.add(t.flag);
    for (const f of flagsSet) if (!triggerFlags.has(f)) err(`flag ${f}: 켜는 선택은 있는데 돌아오는 trigger가 없음`);
    for (const r of (data.style && data.style.rules) || []) {
      if (!(data.style.labels || {})[r.style]) err(`style ${r.style}: labels 없음`);
      for (const c of r.when || []) if (!known(c.stat) || !OPS[c.op]) err(`style ${r.style}: 조건 오류`);
    }
    const checkEffects = (where, eff) => {
      for (const [k, v] of Object.entries(eff || {})) {
        if (!statKeys.has(k)) err(`${where}: 모르는 변수 ${k}`);
        const ok = typeof v === "number" ? Number.isFinite(v)
          : v && typeof v === "object" && (Number.isFinite(v.pct) || Number.isFinite(v.set));
        if (!ok) err(`${where}: ${k} 효과 형식 오류`);
      }
    };
    for (const sc of data.scenarios || []) {
      const w = sc.id;
      if (!sc.title || !sc.situation) err(`${w}: title/situation 없음`);
      if (!(sc.chapter >= 1 && sc.chapter <= (data.chapters || []).length)) err(`${w}: chapter 범위 밖`);
      checkEffects(`${w}.on_enter`, sc.on_enter);
      for (const t of sc.triggers || []) {
        if (!flagsSet.has(t.flag)) err(`${w}: trigger flag ${t.flag}를 켜는 선택이 없음`);
        checkEffects(`${w}.trigger`, t.effects);
        for (const m of t.moves || []) if (!statKeys.has(m.from) || !statKeys.has(m.to)) err(`${w}.trigger: move 변수 오류`);
      }
      const choices = sc.choices || [];
      if (choices.length < 2 || choices.length > 4) err(`${w}: 선택지는 2~4개`);
      if (!choices.some((c) => !c.requires)) err(`${w}: 조건 없는 선택지가 하나는 있어야 함`);
      const cids = new Set();
      for (const c of choices) {
        const cw = `${w}.${c.id}`;
        if (cids.has(c.id)) err(`${cw}: 중복 choice id`);
        cids.add(c.id);
        if (!c.text || !c.result_text || !c.tip) err(`${cw}: text/result_text/tip 없음`);
        checkEffects(cw, c.effects);
        for (const k of Object.keys(c.requires || {})) if (!known(k)) err(`${cw}: requires 모르는 변수 ${k}`);
        for (const m of c.moves || []) {
          if (!statKeys.has(m.from) || !statKeys.has(m.to)) err(`${cw}: move 변수 오류`);
          if (!(m.pct > 0 && m.pct <= 100)) err(`${cw}: move pct 범위`);
        }
        for (const r of c.add_per_turn || []) if (!statKeys.has(r.stat) || !Number.isFinite(r.amount)) err(`${cw}: add_per_turn 오류`);
        for (const st of c.style || []) if (!((data.style || {}).labels || {})[st]) err(`${cw}: style ${st} 없음`);
        const nxt = c.next || sc.next;
        if (!nxt) err(`${cw}: next 없음`);
        else if (nxt !== "END" && !ids.has(nxt)) err(`${cw}: next ${nxt} 없음`);
      }
    }
    const endings = data.endings || [];
    if (!endings.length || (endings[endings.length - 1].when || []).length) err("마지막 엔딩은 조건 없는 기본 엔딩이어야 함");
    for (const e of endings) for (const c of e.when || []) {
      if (!known(c.stat)) err(`ending ${e.id}: 모르는 변수 ${c.stat}`);
      if (!OPS[c.op]) err(`ending ${e.id}: op ${c.op}`);
    }
    return errors;
  }

  class Game {
    constructor(data) {
      const errors = validate(data);
      if (errors.length) throw new Error("게임 데이터 오류: " + errors.slice(0, 5).join(" / "));
      this.data = data;
      this.byId = Object.fromEntries(data.scenarios.map((s) => [s.id, s]));
      this.statDef = Object.fromEntries(data.stats.map((s) => [s.key, s]));
      this.triggerFlags = new Set(data.scenarios.flatMap((s) => (s.triggers || []).map((t) => t.flag)));
      this.start();
    }

    start() {
      this.state = { vars: { ...this.data.start }, flags: [], extra_per_turn: [], count: 0, current: this.data.first,
                     history: [], enter_events: [], enter_echoes: [], phase: "choose", session_start: null,
                     flag_origin: {}, style: {} };
      this._enter(this.data.first);
      this.state.session_start = this.snapshot();
      return this.state;
    }

    // ---- 값 ----
    value(key) {
      const d = (this.data.derived || {})[key];
      if (!d) return this.state.vars[key];
      return (d.plus || []).reduce((a, k) => a + this.state.vars[k], 0) - (d.minus || []).reduce((a, k) => a + this.state.vars[k], 0);
    }
    snapshot() {
      const out = { ...this.state.vars };
      for (const k of Object.keys(this.data.derived || {})) out[k] = this.value(k);
      return out;
    }
    scenario() { return this.byId[this.state.current]; }
    chapter() { return this.data.chapters[this.scenario().chapter - 1]; }

    choices() {
      return this.scenario().choices.map((c) => {
        const miss = Object.entries(c.requires || {}).find(([k, v]) => !(this.value(k) >= v));
        return { choice: c, enabled: !miss, reason: miss ? `${this._label(miss[0])} ${this._fmt(miss[0], miss[1])} 이상 필요` : "" };
      });
    }

    // ---- 진행 ----
    choose(choiceId) {
      if (this.state.phase !== "choose") throw new Error("지금은 선택할 수 없음(phase=" + this.state.phase + ")");
      const sc = this.scenario();
      const opt = this.choices().find((o) => o.choice.id === choiceId);
      if (!opt) throw new Error("없는 선택지: " + choiceId);
      if (!opt.enabled) throw new Error("조건이 안 맞는 선택지: " + opt.reason);
      const c = opt.choice;
      const before = this.snapshot();
      const events = [];
      this._apply(c.effects);
      for (const m of c.moves || []) this._move(m);
      const mid = this.snapshot();
      const own = {};
      for (const k of Object.keys(mid)) if (mid[k] !== before[k]) own[k] = mid[k] - before[k];
      const styles = this._styleOf(c, own);
      for (const st of styles) this.state.style[st] = (this.state.style[st] || 0) + 1;
      for (const f of c.set_flags || []) {
        if (!this.state.flags.includes(f)) this.state.flags.push(f);
        this.state.flag_origin[f] = { n: this.state.count + 1, scenario: sc.title, choice: c.text };
      }
      const delayed = (c.set_flags || []).some((f) => this.triggerFlags.has(f));
      for (const r of c.add_per_turn || []) this.state.extra_per_turn.push({ ...r, source: `${sc.id}.${c.id}` });
      const flow = this._perTurn();
      events.push(...this._guards());
      this._normalize();
      const after = this.snapshot();
      const deltas = {};
      for (const k of Object.keys(after)) if (after[k] !== before[k]) deltas[k] = after[k] - before[k];
      this.state.count += 1;
      this.state.history.push({ scenario: sc.id, choice: c.id });
      const nxt = c.next || sc.next;
      this.state.pending_next = nxt;
      const size = this.data.session_size || 10;
      this.state.phase = nxt === "END" ? "end" : (this.state.count % size === 0 ? "session_end" : "result");
      return { scenario: sc, choice: c, before, after, deltas, own, flow, events, styles, delayed, n: this.state.count,
               result_text: c.result_text, tip: c.tip, phase: this.state.phase };
    }

    next() {
      if (this.state.phase === "result" || this.state.phase === "session_end") {
        const wasSession = this.state.phase === "session_end";
        this._enter(this.state.pending_next);
        this.state.phase = "choose";
        if (wasSession) this.state.session_start = this.snapshot();
        return this.state.phase;
      }
      throw new Error("next 불가(phase=" + this.state.phase + ")");
    }

    sessionSummary() {
      const now = this.snapshot();
      const start = this.state.session_start || now;
      const size = this.data.session_size || 10;
      const done = this.state.count;
      return { session: Math.ceil(done / size), count: done, chapter: this.data.chapters[this.byId[this.state.history[this.state.history.length - 1].scenario].chapter - 1],
               start, now, change: Object.fromEntries(Object.keys(now).map((k) => [k, now[k] - start[k]])) };
    }

    ending() {
      const vals = this.snapshot();
      for (const e of this.data.endings) {
        if ((e.when || []).every((c) => OPS[c.op](vals[c.stat], c.value))) return { ...e, values: vals };
      }
      return null; // validate()가 기본 엔딩을 보장
    }

    // ---- 플레이 스타일(게임 내 선택 기준) ----
    _styleOf(c, own) {
      if (c.style) return c.style.slice();
      const rules = (this.data.style && this.data.style.rules) || [];
      return rules.filter((r) => (r.when || []).every((w) => OPS[w.op](own[w.stat] || 0, w.value))).map((r) => r.style);
    }
    styleResult() {
      const st = this.data.style;
      if (!st) return null;
      const counts = { ...this.state.style };
      const total = Object.values(counts).reduce((a, b) => a + b, 0);
      const [top, n] = Object.entries(counts).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))[0] || [null, 0];
      const share = total ? n / total : 0;
      const key = !top || share < (st.balanced.max_share || 0) ? "balanced" : top;
      const label = key === "balanced" ? st.balanced : st.labels[key];
      return { key, title: label.title, icon: label.icon, text: label.text || "", share: Math.round(share * 100), counts };
    }
    score() { return this.data.score_stat ? this.value(this.data.score_stat) : null; }

    // ---- 저장/복원(새로고침 대비) ----
    serialize() {
      return JSON.stringify({ v: SAVE_VERSION, game: this.data.id, data_version: this.data.version, state: this.state });
    }
    static restore(data, text) {
      try {
        const o = JSON.parse(text);
        if (!o || o.v !== SAVE_VERSION || o.game !== data.id || o.data_version !== data.version) return null;
        const g = new Game(data);
        const st = o.state;
        if (!st || !g.byId[st.current] || !Number.isInteger(st.count) || st.count < 0) return null;
        for (const s of data.stats) if (!Number.isFinite(st.vars?.[s.key])) return null;
        if (!["choose", "result", "session_end", "end"].includes(st.phase)) return null;
        if (st.phase !== "choose" && st.pending_next !== "END" && !g.byId[st.pending_next]) return null;
        g.state = st;
        return g;
      } catch (e) {
        return null;
      }
    }

    // ---- 내부 ----
    _enter(id) {
      const sc = this.byId[id];
      this.state.current = id;
      const before = this.snapshot();
      const events = [];
      const echoes = [];
      if (sc.on_enter) {
        this._apply(sc.on_enter);
        if (sc.enter_text) events.push(sc.enter_text);
      }
      for (const t of sc.triggers || []) {
        if (!this.state.flags.includes(t.flag)) continue;
        this._apply(t.effects);
        for (const m of t.moves || []) this._move(m);
        events.push(t.text);
        echoes.push({ text: t.text, flag: t.flag, origin: this.state.flag_origin[t.flag] || null });
      }
      events.push(...this._guards());
      this._normalize();
      const after = this.snapshot();
      const deltas = {};
      for (const k of Object.keys(after)) if (after[k] !== before[k]) deltas[k] = after[k] - before[k];
      this.state.enter_events = events;
      this.state.enter_echoes = echoes;
      this.state.enter_deltas = deltas;
    }

    _apply(eff) {
      for (const [k, v] of Object.entries(eff || {})) {
        const cur = this.state.vars[k];
        if (typeof v === "number") this.state.vars[k] = cur + v;
        else if (Number.isFinite(v.set)) this.state.vars[k] = v.set;
        else this.state.vars[k] = cur + (cur * v.pct) / 100;
      }
    }

    _move(m) {
      // from의 pct%를 떼어 to로 보낸다. reduce=true면 to에서 뺀다(예: 투자 일부로 부채 상환). reduce는 to 잔액까지만.
      const vars = this.state.vars;
      let amount = Math.round((Math.max(0, vars[m.from]) * m.pct) / 100);
      if (m.reduce) amount = Math.min(amount, Math.max(0, vars[m.to]));
      vars[m.from] -= amount;
      vars[m.to] += m.reduce ? -amount : amount;
    }

    _perTurn() {
      const before = this.snapshot();
      for (const r of [...(this.data.per_turn || []), ...this.state.extra_per_turn]) {
        this.state.vars[r.stat] += Number.isFinite(r.amount) ? r.amount : this.state.vars[r.from] * r.rate;
      }
      this._normalize();
      const after = this.snapshot();
      return Object.fromEntries(Object.keys(after).filter((k) => after[k] !== before[k]).map((k) => [k, after[k] - before[k]]));
    }

    _guards() {
      const events = [];
      for (const g of this.data.guards || []) {
        const v = this.state.vars[g.stat];
        if (v < g.below) {
          const gap = g.below - v;
          this.state.vars[g.stat] = g.below;
          this.state.vars[g.move_to] += gap;
          this._apply(g.effects);
          events.push(g.text.replace("{gap}", this._fmt(g.move_to, Math.round(gap))));
        }
      }
      return events;
    }

    _normalize() {
      for (const s of this.data.stats) {
        let v = this.state.vars[s.key];
        if (!Number.isFinite(v)) v = this.data.start[s.key]; // NaN/Infinity가 퍼지지 않게
        v = Math.round(v);
        if (s.min !== undefined && s.min !== null) v = Math.max(s.min, v);
        if (s.max !== undefined && s.max !== null) v = Math.min(s.max, v);
        this.state.vars[s.key] = v;
      }
    }

    _label(k) { return (this.statDef[k] || (this.data.derived || {})[k] || { label: k }).label; }
    _fmt(k, v) { return formatValue((this.statDef[k] || (this.data.derived || {})[k] || {}).unit, v, this.data.money_unit); }
  }

  function formatValue(unit, v, moneyUnit) {
    if (unit !== "money") return String(v);
    // 게임 단위: 1 = 1만원(data.money_unit). 1억 이상은 억 단위로.
    const sign = v < 0 ? "-" : "";
    const a = Math.abs(Math.round(v));
    if (a >= 10000) {
      const eok = Math.floor(a / 10000), rest = a % 10000;
      return `${sign}${eok}억${rest ? " " + rest.toLocaleString("ko-KR") + "만" : ""}원`;
    }
    return `${sign}${a.toLocaleString("ko-KR")}${moneyUnit || "만원"}`;
  }

  return { Game, validate, formatValue, SAVE_VERSION };
});

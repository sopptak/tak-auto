/*
 * CHOICE100 탐험·부족 통합 엔진 (6-68 고조선 Vertical Slice)
 * 성장(EXP·레벨·지식→정책·아이템·어빌리티(=스킬)·동료·관계)은 6-67 RPG 엔진(engine.js)을 그대로 쓴다(this.rpg).
 * 이 파일이 더하는 것: 지도(숨은 길·조건 길) · 장소 탐색(순서 있는 발견) · 채집 · 사건(선택 → 결과 → 다음 사건) ·
 *   부족(모름 → 만남 → 신뢰·요청 → 통합[연합/복속]) · 미니게임(pick/route + 6-66 보드 사냥) · 엔딩(내가 만든 나라).
 * 무작위는 보드 주사위뿐. 무엇을 발견하는지는 플레이어의 이동·선택·지식·어빌리티가 정한다.
 *
 * 조건(requires) 공통 형식: {ability, item, knowledge, flag, not_flag, tribe_met, tribe_integrated, tribes_integrated(수), stat:{k: 최소}}
 * 효과(effects) 공통 형식: {stats, exp, items, abilities, knowledge, flags, reveal:[edge id], trust:{tribe: n}, meet, event, minigame, companion}
 */
(function (root, factory) {
  const api = factory(root);
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.Choice100Explore = api;
})(typeof self !== "undefined" ? self : this, function (root) {
  "use strict";
  const Rpg = typeof module === "object" && module.exports ? require("./engine.js") : root.Choice100Rpg;
  const SAVE_VERSION = 1;

  function validateExplore(d) {
    const errs = [];
    const e = (m) => errs.push(m);
    const x = d.explore;
    if (!x) return ["explore 없음"];
    const locs = new Set(x.locations.map((l) => l.id));
    const tribes = new Set(x.tribes.map((t) => t.id));
    const events = new Set(x.events.map((v) => v.id));
    const minis = new Set(x.minigames.map((m) => m.id));
    const edges = new Set(x.edges.map((g) => g.id));
    const skills = new Set(d.skills.map((s) => s.id)), items = new Set(d.items.map((i) => i.id)), know = new Set(d.knowledge.map((k) => k.id));
    const stats = new Set(d.stats);
    const flagsSet = new Set();
    const hs = (w, o) => { if (!Rpg.HISTORICAL.includes(o && o.historical_status)) e(`${w}: historical_status`); };
    const req = (w, r) => {
      if (!r) return;
      if (r.ability && !skills.has(r.ability)) e(`${w}: ability ${r.ability}`);
      if (r.item && !items.has(r.item)) e(`${w}: item ${r.item}`);
      if (r.knowledge && !know.has(r.knowledge)) e(`${w}: knowledge ${r.knowledge}`);
      for (const k of ["tribe_met", "tribe_integrated"]) if (r[k] && !tribes.has(r[k])) e(`${w}: ${k} ${r[k]}`);
      for (const k of Object.keys(r.stat || {})) if (!stats.has(k)) e(`${w}: stat ${k}`);
    };
    const eff = (w, f) => {
      if (!f) return;
      for (const k of Object.keys(f.stats || {})) if (!stats.has(k)) e(`${w}: stat ${k}`);
      for (const a of f.abilities || []) if (!skills.has(a)) e(`${w}: ability ${a}`);
      for (const i of f.items || []) if (!items.has(i)) e(`${w}: item ${i}`);
      for (const k of f.knowledge || []) if (!know.has(k)) e(`${w}: knowledge ${k}`);
      for (const r of f.reveal || []) if (!edges.has(r)) e(`${w}: reveal ${r}`);
      for (const t of Object.keys(f.trust || {})) if (!tribes.has(t)) e(`${w}: trust ${t}`);
      if (f.event && !events.has(f.event)) e(`${w}: event ${f.event}`);
      if (f.minigame && !minis.has(f.minigame)) e(`${w}: minigame ${f.minigame}`);
      if (f.meet && !tribes.has(f.meet)) e(`${w}: meet ${f.meet}`);
      if (f.companion && !d.heroes.some((h) => h.id === f.companion)) e(`${w}: companion ${f.companion}`);
      for (const fl of f.flags || []) flagsSet.add(fl);
    };
    if (!locs.has(x.start)) e("start 장소 없음");
    for (const g of x.edges) {
      if (!locs.has(g.from) || !locs.has(g.to)) e(`edge ${g.id}: 장소`);
      req(`edge ${g.id}`, g.requires);
    }
    for (const l of x.locations) {
      hs(`loc ${l.id}`, l);
      if (!Number.isInteger(l.x) || !Number.isInteger(l.y)) e(`loc ${l.id}: x/y`);
      (l.searches || []).forEach((s, i) => { hs(`loc ${l.id} search ${i}`, s); req(`loc ${l.id}#${i}`, s.requires); eff(`loc ${l.id}#${i}`, s.effects); });
      if (l.gather) { if (!stats.has(l.gather.stat)) e(`loc ${l.id}: gather stat`); req(`loc ${l.id} gather`, l.gather.requires); }
      if (l.tribe && !tribes.has(l.tribe)) e(`loc ${l.id}: tribe`);
      for (const m of l.minigames || []) if (!minis.has(m)) e(`loc ${l.id}: minigame ${m}`);
      if (l.arrive) eff(`loc ${l.id} arrive`, l.arrive);
    }
    for (const v of x.events) {
      hs(`event ${v.id}`, v);
      if (!(v.choices || []).some((c) => !c.requires)) e(`event ${v.id}: 늘 고를 수 있는 선택 필요`);
      for (const c of v.choices || []) { req(`event ${v.id}.${c.id}`, c.requires); eff(`event ${v.id}.${c.id}`, c.effects); hs(`event ${v.id}.${c.id}`, c); }
    }
    const refEvents = new Set([x.ending.council_event]);
    const scanEv = (o) => { if (!o || typeof o !== "object") return; for (const [k, v] of Object.entries(o)) { if ((k === "event" || k === "encounter" || k === "offer_event") && typeof v === "string") refEvents.add(v); else scanEv(v); } };
    scanEv(x);
    for (const v of x.events) if (!refEvents.has(v.id)) e(`event ${v.id}: 어디서도 이어지지 않음`);
    for (const t of x.tribes) {
      hs(`tribe ${t.id}`, t);
      for (const r of t.requests || []) if (r.offer_event && !events.has(r.offer_event)) e(`tribe ${t.id}.${r.id}: offer_event`);
      if (!locs.has(t.location)) e(`tribe ${t.id}: location`);
      if (!events.has(t.encounter)) e(`tribe ${t.id}: encounter`);
      for (const r of t.requests || []) req(`tribe ${t.id}.${r.id}`, r.requires);
      eff(`tribe ${t.id}.union`, t.union.rewards);
      if (t.force) eff(`tribe ${t.id}.force`, t.force.rewards);
    }
    for (const m of x.minigames) {
      if (!["pick", "board"].includes(m.type)) e(`minigame ${m.id}: type`);
      if (m.type === "pick") for (const s of m.steps) {
        if (!(s.options || []).some((o) => o.correct)) e(`minigame ${m.id}: 정답 없음`);
        if (s.hint && !know.has(s.hint.knowledge)) e(`minigame ${m.id}: hint knowledge`);
      }
      if (m.type === "board" && !(d.boards || {})[m.board]) e(`minigame ${m.id}: board`);
      eff(`minigame ${m.id} win`, m.win);
      eff(`minigame ${m.id} lose`, m.lose);
    }
    // 켜지는 flag가 어디서도 안 쓰이면 경고성 오류(죽은 복선)
    const used = new Set();
    const scan = (o) => { if (!o || typeof o !== "object") return; for (const [k, v] of Object.entries(o)) { if ((k === "flag" || k === "not_flag") && typeof v === "string") used.add(v); else scan(v); } };
    scan(x);
    for (const f of flagsSet) if (!used.has(f) && !(x.info_flags || []).includes(f)) e(`flag ${f}: 켜기만 하고 쓰이지 않음`);
    if (!events.has(x.ending.council_event)) e("ending council_event");
    if (!x.tribe_gift || !stats.has(x.tribe_gift.stat)) e("tribe_gift");
    for (const k of Object.keys(x.hunger_penalty || {})) if (!stats.has(k)) e("hunger_penalty");
    return errs;
  }

  class Explore {
    constructor(data, opts = {}) {
      const errs = validateExplore(data);
      if (errs.length) throw new Error("탐험 데이터 오류: " + errs.slice(0, 6).join(" / "));
      this.data = data;
      this.x = data.explore;
      this.rpg = new Rpg.Game(data, opts);
      this.L = Object.fromEntries(this.x.locations.map((l) => [l.id, l]));
      this.T = Object.fromEntries(this.x.tribes.map((t) => [t.id, t]));
      this.E = Object.fromEntries(this.x.events.map((v) => [v.id, v]));
      this.M = Object.fromEntries(this.x.minigames.map((m) => [m.id, m]));
      this.start();
    }

    start() {
      this.rpg.start();
      this.s = { day: 1, loc: this.x.start, visited: [this.x.start], revealed: [], searched: {}, gathered: {}, flags: [], choices: [],
                 tribes: Object.fromEntries(this.x.tribes.map((t) => [t.id, { status: "unknown", trust: 0, done: [], method: null }])),
                 event: null, mini: null, log: [], ended: null, actions: 0 };
      this._log("start", this.L[this.x.start].name);
      return this.s;
    }

    // ---- 조건 ----
    meets(r) {
      if (!r) return true;
      const st = this.rpg.state;
      if (r.ability && !st.skills.includes(r.ability)) return false;
      if (r.item && !st.items.includes(r.item)) return false;
      if (r.knowledge && !st.knowledge.includes(r.knowledge)) return false;
      if (r.flag && !this.s.flags.includes(r.flag)) return false;
      if (r.not_flag && this.s.flags.includes(r.not_flag)) return false;
      if (r.tribe_met && this.s.tribes[r.tribe_met].status === "unknown") return false;
      if (r.tribe_integrated && this.s.tribes[r.tribe_integrated].status !== "integrated") return false;
      if (r.tribes_integrated && this.integratedCount() < r.tribes_integrated) return false;
      for (const [k, v] of Object.entries(r.stat || {})) if (!(st.stats[k] >= v)) return false;
      return true;
    }
    why(r) {
      if (!r || this.meets(r)) return "";
      const name = (arr, id) => (this.data[arr].find((z) => z.id === id) || { name: id }).name;
      if (r.ability && !this.rpg.state.skills.includes(r.ability)) return `어빌리티 ‘${name("skills", r.ability)}’ 필요`;
      if (r.item && !this.rpg.state.items.includes(r.item)) return `‘${name("items", r.item)}’ 필요`;
      if (r.knowledge && !this.rpg.state.knowledge.includes(r.knowledge)) return "알아야 할 것이 있다";
      if (r.tribes_integrated && this.integratedCount() < r.tribes_integrated) return `부족 ${r.tribes_integrated}곳 통합 필요(지금 ${this.integratedCount()})`;
      if (r.tribe_integrated) return `${this.T[r.tribe_integrated].name}와 함께해야 한다`;
      if (r.tribe_met) return `${this.T[r.tribe_met].name}를 먼저 만나야 한다`;
      for (const [k, v] of Object.entries(r.stat || {})) if (!(this.rpg.state.stats[k] >= v)) return `${(this.data.stat_labels[k] || [k])[0]} ${v} 필요`;
      if (r.flag) return "아직 모르는 것이 있다";
      return "조건 부족";
    }
    integratedCount() { return Object.values(this.s.tribes).filter((t) => t.status === "integrated").length; }

    // ---- 지도 ----
    edgeVisible(g) { return !g.hidden || this.s.revealed.includes(g.id); }
    exits() {
      return this.x.edges.filter((g) => (g.from === this.s.loc || (g.both !== false && g.to === this.s.loc)) && this.edgeVisible(g)).map((g) => {
        const to = g.from === this.s.loc ? g.to : g.from;
        // 식량이 모자라도 갈 수는 있다(굶주린 행군: 벌점) - 식량 때문에 갇히지 않게
        const hungry = this.rpg.state.stats.food < (g.food || 0);
        return { edge: g, to: this.L[to], ok: this.meets(g.requires), hungry, why: this.why(g.requires), visited: this.s.visited.includes(to) };
      });
    }
    // 지도에 보일 장소: 가 본 곳 + 보이는 길로 이어진 곳(아직 안 가 본 곳은 ?)
    mapView() {
      const known = new Set(this.s.visited);
      for (const g of this.x.edges) if (this.edgeVisible(g) && (known.has(g.from) || known.has(g.to))) { known.add(g.from); known.add(g.to); }
      return this.x.locations.filter((l) => known.has(l.id)).map((l) => ({ loc: l, visited: this.s.visited.includes(l.id), here: l.id === this.s.loc }));
    }
    travel(toId) {
      this._need();
      const ex = this.exits().find((o) => o.to.id === toId);
      if (!ex) throw new Error("갈 수 없는 곳");
      if (!ex.ok) throw new Error(ex.why);
      const hunger = ex.hungry ? this._grant({ stats: this.x.hunger_penalty }) : null;
      this._grant({ stats: { food: -(ex.edge.food || 0) } });
      this.s.loc = toId;
      this._tick();
      const first = !this.s.visited.includes(toId);
      const out = { type: "travel", to: toId, first, gained: null, hunger };
      if (first) {
        this.s.visited.push(toId);
        out.gained = this._grant({ exp: this.x.discover_exp });
        if (this.L[toId].arrive) Object.assign(out, { arrive: this._effects(this.L[toId].arrive) });
      }
      const t = this.L[toId].tribe;
      if (t && this.s.tribes[t].status === "unknown" && !this.s.event) this._meet(t);
      this._log("travel", this.L[toId].name);
      return out;
    }

    // ---- 탐색·채집 ----
    searchInfo() {
      const l = this.L[this.s.loc];
      const list = l.searches || [];
      const n = this.s.searched[l.id] || 0;
      const next = list[n];
      if (!next) return { left: 0, locked: null };
      return { left: list.length - n, locked: this.meets(next.requires) ? null : (next.hint || this.why(next.requires)) };
    }
    search() {
      this._need();
      const l = this.L[this.s.loc];
      const n = this.s.searched[l.id] || 0;
      const s = (l.searches || [])[n];
      if (!s) throw new Error("더 찾을 것이 없다");
      if (!this.meets(s.requires)) throw new Error(s.hint || this.why(s.requires));
      this.s.searched[l.id] = n + 1;
      this._tick();
      const res = this._effects({ exp: this.x.search_exp, ...(s.effects || {}) });
      this._log("search", s.text.slice(0, 30));
      return { type: "search", text: s.text, historical_status: s.historical_status, source: s.source || null, ...res };
    }
    gatherInfo() {
      const g = this.L[this.s.loc].gather;
      if (!g) return null;
      const used = this.s.gathered[this.s.loc] || 0;
      return { gather: g, left: g.max === undefined ? Infinity : g.max - used, ok: this.meets(g.requires) && (g.max === undefined || used < g.max), why: this.why(g.requires) };
    }
    gather() {
      this._need();
      const gi = this.gatherInfo();
      if (!gi || !gi.ok) throw new Error(gi ? gi.why || "다 캤다" : "채집할 것이 없다");
      this.s.gathered[this.s.loc] = (this.s.gathered[this.s.loc] || 0) + 1;
      this._tick();
      let amount = gi.gather.amount;
      const bonus = gi.gather.bonus && this.meets(gi.gather.bonus.requires) ? gi.gather.bonus.amount : 0;
      const g = this._grant({ stats: { [gi.gather.stat]: amount + bonus } });
      return { type: "gather", text: gi.gather.text, bonus: !!bonus, gained: g };
    }

    // ---- 사건 ----
    event() { return this.s.event ? this.E[this.s.event] : null; }
    eventOptions() { const v = this.event(); return v ? v.choices.map((c) => ({ choice: c, ok: this.meets(c.requires), why: this.why(c.requires) })) : []; }
    choose(id) {
      const v = this.event();
      if (!v) throw new Error("사건 없음");
      const c = v.choices.find((z) => z.id === id);
      if (!c) throw new Error("없는 선택");
      if (!this.meets(c.requires)) throw new Error(this.why(c.requires));
      this.s.event = null;
      this.s.choices.push(`${v.id}.${c.id}`);
      this._tick();
      const res = this._effects(c.effects || {});
      this._log("choice", `${v.title}: ${c.text}`.slice(0, 40));
      if (v.id === this.x.ending.council_event) this._end(c);
      return { type: "choice", event: v.id, choice: c.id, result: c.result, lesson: c.lesson || null, historical_status: c.historical_status, ...res };
    }

    // ---- 부족 ----
    tribeView(id) {
      const t = this.T[id], st = this.s.tribes[id];
      const reqs = (t.requests || []).map((r) => {
        const done = st.done.includes(r.id), ok = this.meets(r.requires);
        return { req: r, done, ok, why: this.why(r.requires), offer: !done && !ok && !!r.offer_event };
      });
      const unionOk = st.status === "met" && st.trust >= t.union.trust && reqs.every((r) => r.done);
      const forceOk = !!t.force && st.status === "met" && this.meets(t.force.requires);
      return { tribe: t, state: st, requests: reqs, union: { ok: unionOk, need: t.union.trust }, force: t.force ? { ok: forceOk, why: this.why(t.force.requires) } : null };
    }
    fulfill(tribeId, reqId) {
      this._need();
      const v = this.tribeView(tribeId);
      if (v.state.status !== "met") throw new Error("만난 부족이 아님");
      const r = v.requests.find((z) => z.req.id === reqId);
      if (!r || r.done) throw new Error("없거나 끝난 요청");
      if (!r.ok) throw new Error(r.why);
      v.state.done.push(reqId);
      this._tick();
      const res = this._effects({ ...(r.req.effects || {}), trust: { [tribeId]: r.req.trust || 0, ...((r.req.effects || {}).trust || {}) } });
      this._log("request", `${v.tribe.name}: ${r.req.text}`.slice(0, 40));
      return { type: "request", text: r.req.done_text, ...res };
    }
    // 선물(되풀이 가능): 식량을 나눠 신뢰를 쌓는다 - 어떤 선택을 했어도 신뢰에 닿을 길을 남긴다
    giftInfo(tribeId) {
      const gf = this.x.tribe_gift, st = this.s.tribes[tribeId];
      return { ...gf, ok: st.status === "met" && this.rpg.state.stats[gf.stat] >= gf.amount, why: st.status !== "met" ? "" : `${(this.data.stat_labels[gf.stat] || [gf.stat])[0]} ${gf.amount} 필요` };
    }
    gift(tribeId) {
      this._need();
      const gi = this.giftInfo(tribeId);
      if (!gi.ok) throw new Error(gi.why || "지금은 선물할 수 없다");
      this._tick();
      const res = this._effects({ stats: { [gi.stat]: -gi.amount }, trust: { [tribeId]: gi.trust } });
      return { type: "gift", text: gi.text, ...res };
    }
    // 요청을 아직 못 채웠을 때 다시 기회를 주는 사건(예: 홍수를 다시 막기)
    offer(tribeId, reqId) {
      this._need();
      const r = this.tribeView(tribeId).requests.find((z) => z.req.id === reqId);
      if (!r || !r.offer) throw new Error("다시 도울 수 있는 요청이 아님");
      this.s.event = r.req.offer_event;
      this._tick();
      return { type: "offer", event: r.req.offer_event };
    }
    integrate(tribeId, method = "union") {
      this._need();
      const v = this.tribeView(tribeId);
      if (method === "union" && !v.union.ok) throw new Error(`신뢰 ${v.union.need} 이상과 요청 해결이 필요`);
      if (method === "force" && !(v.force && v.force.ok)) throw new Error("복속 조건 부족");
      v.state.status = "integrated";
      v.state.method = method;
      this._tick();
      const rw = method === "union" ? v.tribe.union.rewards : v.tribe.force.rewards;
      const res = this._effects(rw);
      this.rpg.state.relations[tribeId] = method === "union" ? "ALLY" : "NEUTRAL";
      this._log("integrate", `${v.tribe.name} (${method === "union" ? "연합" : "복속"})`);
      return { type: "integrate", tribe: tribeId, method, text: method === "union" ? v.tribe.union.text : v.tribe.force.text, ...res };
    }
    _meet(id) {
      this.s.tribes[id].status = "met";
      this.rpg.state.relations[id] = "NEUTRAL";
      this.s.event = this.T[id].encounter;
    }

    // ---- 미니게임 ----
    minigames() {
      return (this.L[this.s.loc].minigames || []).map((id) => ({ mg: this.M[id], ok: this.meets(this.M[id].requires), why: this.why(this.M[id].requires), won: this.s.flags.includes(`won_${id}`) }));
    }
    startMini(id) {
      this._need();
      const m = this.M[id];
      if (!(this.L[this.s.loc].minigames || []).includes(id)) throw new Error("여기서 할 수 없는 미니게임");
      if (!this.meets(m.requires)) throw new Error(this.why(m.requires));
      this.s.mini = { id, step: 0, score: 0, answers: [] };
      if (m.type === "board") this.rpg._boardStart({ board: m.board });
      return this.s.mini;
    }
    miniStep() {
      const mi = this.s.mini;
      if (!mi) return null;
      const m = this.M[mi.id];
      if (m.type !== "pick") return null;
      const st = m.steps[mi.step];
      const hint = st.hint && this.rpg.state.knowledge.includes(st.hint.knowledge) ? st.hint.text : null;
      return { step: st, index: mi.step, total: m.steps.length, hint };
    }
    miniAnswer(i) {
      const mi = this.s.mini;
      const m = this.M[mi.id];
      const st = m.steps[mi.step];
      const o = st.options[i];
      if (!o) throw new Error("보기 범위");
      if (o.correct) mi.score += 1;
      mi.answers.push(i);
      mi.step += 1;
      const out = { correct: !!o.correct, feedback: o.feedback || (o.correct ? "좋은 선택!" : "아니었다."), done: mi.step >= m.steps.length };
      if (out.done) out.result = this._finishMini(mi.score >= m.pass);
      return out;
    }
    boardGame() { return this.rpg.boardGame(); }
    finishBoardMini() {
      const mi = this.s.mini;
      const m = this.M[mi.id];
      const merged = this.rpg.finishBoard();
      this.rpg.state.board = null;
      const win = merged.board[m.win_stat] >= m.win_min;
      return { merged, ...this._finishMini(win) };
    }
    _finishMini(win) {
      const mi = this.s.mini;
      const m = this.M[mi.id];
      this.s.mini = null;
      this._tick();
      const res = this._effects((win ? m.win : m.lose) || {});
      if (win && !this.s.flags.includes(`won_${m.id}`)) this.s.flags.push(`won_${m.id}`);
      this._log("minigame", `${m.name} ${win ? "성공" : "실패"}`);
      return { type: "minigame", id: m.id, win, text: win ? m.win_text : m.lose_text, ...res };
    }

    // ---- 효과 적용 ----
    _effects(f) {
      const out = { gained: this._grant({ exp: f.exp, stats: f.stats, items: f.items, skills: f.abilities, knowledge: f.knowledge }), revealed: [], trust: {}, flags: [] };
      for (const fl of f.flags || []) if (!this.s.flags.includes(fl)) { this.s.flags.push(fl); out.flags.push(fl); }
      for (const r of f.reveal || []) if (!this.s.revealed.includes(r)) { this.s.revealed.push(r); out.revealed.push(r); }
      for (const [t, n] of Object.entries(f.trust || {})) { this.s.tribes[t].trust += n; out.trust[t] = n; }
      if (f.companion) {
        const h = this.data.heroes.find((z) => z.id === f.companion);
        if (!this.rpg.state.companions.includes(h.id)) { this.rpg.state.companions.push(h.id); out.companion = h.id; this.rpg.state.relations[h.id] = "COMPANION"; }
      }
      if (f.meet && this.s.tribes[f.meet].status === "unknown") { this._meet(f.meet); out.met = f.meet; }
      else if (f.event) { this.s.event = f.event; out.event = f.event; }
      if (f.minigame) out.minigame = f.minigame;
      return out;
    }
    _grant(g) {
      const clean = { exp: g.exp || 0, stats: {}, items: g.items, skills: g.skills, knowledge: g.knowledge };
      for (const [k, v] of Object.entries(g.stats || {})) clean.stats[k] = v;
      return this.rpg._grant(clean);
    }
    _tick() { this.s.day += 1; this.s.actions += 1; }
    _need() {
      if (this.s.ended) throw new Error("이미 끝난 게임");
      if (this.s.event) throw new Error("먼저 사건에 답해야 한다");
      if (this.s.mini) throw new Error("미니게임 진행 중");
    }
    _log(k, t) { this.s.log.push({ day: this.s.day, k, t }); if (this.s.log.length > 200) this.s.log.shift(); }

    // ---- 엔딩 ----
    _end(lastChoice) {
      const tribes = this.x.tribes.map((t) => ({ id: t.id, name: t.name, icon: t.icon, status: this.s.tribes[t.id].status, method: this.s.tribes[t.id].method }));
      const union = tribes.filter((t) => t.method === "union").length, force = tribes.filter((t) => t.method === "force").length;
      const st = this.rpg.state;
      const vals = { union, force, tribes: union + force, places: this.s.visited.length, knowledge: st.knowledge.length, reputation: st.stats.reputation, population: st.stats.population };
      const ops = { ">=": (a, b) => a >= b, "<=": (a, b) => a <= b, "==": (a, b) => a === b };
      const ending = this.x.ending.variants.find((v) => (v.when || []).every((c) => ops[c.op](vals[c.stat], c.value)));
      const laws = this.s.choices.filter((c) => c.startsWith("law_")).map((c) => c.split(".")[1]);
      this.s.ended = { ending: ending.id, title: ending.title, text: ending.text, icon: ending.icon, vals, tribes, laws, days: this.s.day, level: st.level, last: lastChoice.id };
    }

    // ---- 저장 ----
    serialize() {
      const rpg = JSON.parse(this.rpg.serialize());
      return JSON.stringify({ v: SAVE_VERSION, game: this.data.id, data_version: this.data.version, s: this.s, rpg: rpg.state });
    }
    static restore(data, text, opts) {
      try {
        const o = JSON.parse(text);
        if (!o || o.v !== SAVE_VERSION || o.game !== data.id || o.data_version !== data.version) return null;
        const g = new Explore(data, opts);
        if (!o.s || !g.L[o.s.loc] || !Array.isArray(o.s.visited) || !o.rpg || !Number.isFinite(o.rpg.stats && o.rpg.stats.exp)) return null;
        const r = Rpg.Game.restore(data, JSON.stringify({ v: 1, game: data.id, data_version: data.version, state: o.rpg }), opts);
        if (!r) return null;
        g.rpg = r;
        g.s = o.s;
        if (g.s.mini && g.M[g.s.mini.id].type === "board") g.s.mini = null; // 보드 한 판은 저장하지 않음 - 다시 시작
        return g;
      } catch (e) {
        return null;
      }
    }
  }

  return { Explore, validateExplore };
});

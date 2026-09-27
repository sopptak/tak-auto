/*
 * CHOICE100 RPG 엔진 (6-67 Vertical Slice) - 메인 스토리 + 영웅별 독립 스토리 + 공통 세계(지역·시간의 문) + 성장(EXP·레벨·지식·아이템·스킬·동료).
 * DOM 없음, 도메인 모름. 데이터(JSON)가 영웅·스토리(단계 목록)·지역·아이템·스킬·관계·정책·레벨표를 정한다.
 *
 * 스토리 단계(step.type):
 *   narration  글 한 장(speaker, text, historical_status)
 *   quiz       퀴즈(정답/오답 보상 따로) - 오답도 기본 EXP + 해설, 게임은 계속
 *   choice     선택지(effects, requires_skill/stat, 결과 글) - 내정·탐험·라이벌 대응
 *   reward     아이템·스킬·지식·능력치·EXP 지급
 *   companion  영웅 합류(관계 COMPANION, 능력치·스킬 활성)
 *   relation   관계 변경(RIVAL → ALLY 등)
 *   board      6-66 보드 엔진 한 턴(퀴즈→주사위 특권→이동→칸) 실행 후 결과를 RPG 상태로 합침(merge 규칙은 데이터)
 *   region     지역 해금/레벨 관문 확인
 *   main       메인 스토리 진행 표시
 *   end        장(chapter) 완료
 * 역사 상태(historical_status): historical_fact | historical_record | legend | game_setting - 모든 글·아이템·지역·관문이 가진다.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.Choice100Rpg = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const HISTORICAL = ["historical_fact", "historical_record", "legend", "game_setting"];
  const RELATIONS = ["FRIEND", "COMPANION", "MENTOR", "RIVAL", "ALLY", "NEUTRAL"];
  const ITEM_TYPES = ["ARTIFACT", "KNOWLEDGE", "POLICY", "SKILL"];
  const STEP_TYPES = ["narration", "quiz", "choice", "reward", "companion", "relation", "board", "region", "main", "end"];
  const SAVE_VERSION = 1;

  function validate(d) {
    const errs = [];
    const e = (m) => errs.push(m);
    if (!d || typeof d !== "object") return ["data 없음"];
    const ids = (arr) => new Set((arr || []).map((x) => x.id));
    const heroes = ids(d.heroes), items = ids(d.items), skills = ids(d.skills), regions = ids(d.regions), quizzes = ids(d.quizzes);
    const knowledge = ids(d.knowledge), policies = ids(d.policies), stories = ids(d.stories), gates = ids(d.time_gates);
    const stats = new Set(d.stats || []);
    const hs = (w, x) => { if (!HISTORICAL.includes(x && x.historical_status)) e(`${w}: historical_status 없음/오류`); };
    const effects = (w, eff) => { for (const [k, v] of Object.entries(eff || {})) if (!stats.has(k) || !Number.isFinite(v)) e(`${w}: 효과 ${k}`); };
    if (!Array.isArray(d.levels) || d.levels[0] !== 0 || d.levels.some((v, i) => i && v <= d.levels[i - 1])) e("levels: 0부터 증가");
    for (const s of stats) if (!Number.isFinite((d.player.start || {})[s])) e(`player.start.${s}`);
    for (const h of d.heroes || []) {
      for (const k of ["id", "name", "era", "region", "role", "tagline", "stats", "skills", "items", "relationships", "sources"]) if (h[k] === undefined) e(`hero ${h.id}: ${k}`);
      hs(`hero ${h.id}`, h);
      if (!regions.has(h.region)) e(`hero ${h.id}: region ${h.region}`);
      if (h.playable && !stories.has(h.story)) e(`hero ${h.id}: story ${h.story}`);
      for (const s of h.skills || []) if (!skills.has(s)) e(`hero ${h.id}: skill ${s}`);
      for (const it of h.items || []) if (!items.has(it)) e(`hero ${h.id}: item ${it}`);
      for (const r of h.relationships || []) if (!RELATIONS.includes(r.type)) e(`hero ${h.id}: relation ${r.type}`);
    }
    for (const it of d.items || []) { if (!ITEM_TYPES.includes(it.type)) e(`item ${it.id}: type`); hs(`item ${it.id}`, it); effects(`item ${it.id}`, it.effects); }
    for (const s of d.skills || []) { hs(`skill ${s.id}`, s); if (!heroes.has(s.hero)) e(`skill ${s.id}: hero`); }
    for (const r of d.regions || []) {
      for (const k of ["id", "name", "era", "stage", "recommended_level", "difficulty"]) if (r[k] === undefined) e(`region ${r.id}: ${k}`);
      hs(`region ${r.id}`, r);
      for (const h of r.hero_stories || []) if (!stories.has(h)) e(`region ${r.id}: story ${h}`);
    }
    for (const g of d.time_gates || []) { hs(`gate ${g.id}`, g); if (!regions.has(g.to_region)) e(`gate ${g.id}: region`); }
    for (const k of d.knowledge || []) { hs(`knowledge ${k.id}`, k); if (!k.source) e(`knowledge ${k.id}: source`); }
    for (const p of d.policies || []) { if (!knowledge.has(p.requires_knowledge)) e(`policy ${p.id}: knowledge`); hs(`policy ${p.id}`, p); effects(`policy ${p.id}`, p.effects); }
    for (const q of d.quizzes || []) {
      for (const k of ["question", "choices", "correct", "explanation", "topic", "era", "region", "source", "source_date"]) if (q[k] === undefined) e(`quiz ${q.id}: ${k}`);
      hs(`quiz ${q.id}`, q);
      if (!Array.isArray(q.choices) || q.choices.length !== 4 || new Set(q.choices).size !== 4) e(`quiz ${q.id}: 보기 4개`);
    }
    for (const m of d.main_story || []) hs(`main ${m.id}`, m);
    for (const [bid, b] of Object.entries(d.boards || {})) {
      for (const r of b.merge || []) if (!(r.to === "exp" || stats.has(r.to)) || !Number.isFinite(r.rate)) e(`board ${bid}: merge ${r.from}→${r.to}`);
      if (b.skill_bonus && !skills.has(b.skill_bonus.skill)) e(`board ${bid}: skill_bonus`);
    }
    for (const st of d.stories || []) {
      if (!heroes.has(st.hero)) e(`story ${st.id}: hero`);
      for (const ch of st.chapters || []) {
        if (!ch.steps || !ch.steps.length || ch.steps[ch.steps.length - 1].type !== "end") e(`story ${st.id}/${ch.id}: 마지막은 end`);
        ch.steps.forEach((s, i) => {
          const w = `${st.id}/${ch.id}#${i}`;
          if (!STEP_TYPES.includes(s.type)) e(`${w}: type ${s.type}`);
          if (s.type === "narration") { hs(w, s); if (!s.text) e(`${w}: text`); }
          if (s.type === "quiz") {
            if (!quizzes.has(s.quiz)) e(`${w}: quiz ${s.quiz}`);
            effects(`${w}.correct`, (s.correct || {}).stats); effects(`${w}.wrong`, (s.wrong || {}).stats);
            for (const k of (s.correct || {}).knowledge || []) if (!knowledge.has(k)) e(`${w}: knowledge ${k}`);
          }
          if (s.type === "choice") {
            if (!(s.options || []).some((o) => !o.requires_skill && !o.requires_stat)) e(`${w}: 늘 고를 수 있는 선택지 필요`);
            for (const o of s.options || []) { effects(`${w}.${o.id}`, o.effects); hs(`${w}.${o.id}`, o); if (o.requires_skill && !skills.has(o.requires_skill)) e(`${w}: skill`); }
          }
          if (s.type === "reward") {
            for (const it of s.items || []) if (!items.has(it)) e(`${w}: item ${it}`);
            for (const sk of s.skills || []) if (!skills.has(sk)) e(`${w}: skill ${sk}`);
            for (const k of s.knowledge || []) if (!knowledge.has(k)) e(`${w}: knowledge ${k}`);
            effects(w, s.stats);
          }
          if ((s.type === "companion" || s.type === "relation") && !heroes.has(s.hero) && !(d.npcs || []).some((n) => n.id === s.hero)) e(`${w}: hero/npc ${s.hero}`);
          if (s.type === "relation" && !RELATIONS.includes(s.to)) e(`${w}: relation ${s.to}`);
          if (s.type === "board" && !(d.boards || {})[s.board]) e(`${w}: board ${s.board}`);
          if (s.type === "region" && !regions.has(s.region)) e(`${w}: region ${s.region}`);
          if (s.type === "main" && !(d.main_story || []).some((m) => m.id === s.main)) e(`${w}: main ${s.main}`);
        });
      }
    }
    return errs;
  }

  class Game {
    constructor(data, opts = {}) {
      const errs = validate(data);
      if (errs.length) throw new Error("RPG 데이터 오류: " + errs.slice(0, 5).join(" / "));
      this.data = data;
      this.BoardGame = opts.BoardGame || null; // 6-66 보드 엔진(Choice100Board.Game) - 주입
      this.rng = opts.rng;
      this.byId = (k) => Object.fromEntries((data[k] || []).map((x) => [x.id, x]));
      this.idx = { heroes: this.byId("heroes"), items: this.byId("items"), skills: this.byId("skills"), regions: this.byId("regions"), quizzes: this.byId("quizzes"),
                   knowledge: this.byId("knowledge"), policies: this.byId("policies"), stories: this.byId("stories"), gates: this.byId("time_gates"), npcs: this.byId("npcs") };
      this.start();
    }

    start() {
      const p = this.data.player;
      this.state = { stats: { ...p.start }, level: 1, items: [], skills: [], companions: [], knowledge: [], policies: [], regions: [...(p.regions || [])],
                     relations: { ...(p.relations || {}) }, main_done: [], stories: {}, current: null, board: null, log: [], last: null, answers: { correct: 0, wrong: 0 } };
      this._recalcLevel();
      return this.state;
    }

    // ---- 조회 ----
    heroCards() {
      return this.data.heroes.map((h) => ({ hero: h, ...this.heroAccess(h.id), done: !!(this.state.stories[h.story] || {}).done, companion: this.state.companions.includes(h.id) }));
    }
    heroAccess(id) {
      const h = this.idx.heroes[id];
      if (!h.playable) return { playable: false, reason: h.locked_reason || "준비 중" };
      const lv = (h.unlock || {}).level || 1;
      if (this.state.level < lv) return { playable: false, reason: `레벨 ${lv} 필요` };
      return { playable: true, reason: "" };
    }
    regionCards() {
      return this.data.regions.map((r) => ({ region: r, unlocked: this.state.regions.includes(r.id), meets_level: this.state.level >= r.recommended_level }));
    }
    levelInfo() {
      const L = this.data.levels, lv = this.state.level;
      const cur = L[lv - 1], next = L[lv];
      return { level: lv, exp: this.state.stats.exp, cur, next: next ?? null, progress: next ? (this.state.stats.exp - cur) / (next - cur) : 1 };
    }
    step() {
      const c = this.state.current;
      if (!c) return null;
      return this.idx.stories[c.story].chapters.find((ch) => ch.id === c.chapter).steps[c.step];
    }
    quiz() { const s = this.step(); return s && s.type === "quiz" ? this.idx.quizzes[s.quiz] : null; }

    // ---- 메인 스토리·시간의 문 ----
    completeMain(id) {
      if (!this.data.main_story.some((m) => m.id === id)) throw new Error("없는 main " + id);
      if (!this.state.main_done.includes(id)) this.state.main_done.push(id);
    }
    passGate(id) {
      const g = this.idx.gates[id];
      if (!g) throw new Error("없는 시간의 문 " + id);
      if (this.state.level < (g.requires_level || 1)) throw new Error(`레벨 ${g.requires_level} 필요`);
      if (!this.state.regions.includes(g.to_region)) this.state.regions.push(g.to_region);
      return this.idx.regions[g.to_region];
    }

    // ---- 영웅 스토리 ----
    startStory(heroId) {
      const h = this.idx.heroes[heroId];
      if (!h) throw new Error("없는 영웅");
      const acc = this.heroAccess(heroId);
      if (!acc.playable) throw new Error(`잠긴 영웅: ${acc.reason}`);
      if (!this.state.regions.includes(h.region)) throw new Error("지역이 열리지 않음(시간의 문 먼저)");
      const st = this.idx.stories[h.story];
      const prog = this.state.stories[st.id] || { chapter: 0, done: false };
      if (prog.done) throw new Error("이미 끝난 이야기");
      this.state.stories[st.id] = prog;
      this.state.current = { story: st.id, chapter: st.chapters[prog.chapter].id, step: 0 };
      this.state.last = null;
      return this._enterStep();
    }

    // 지금 단계를 진행한다. input: quiz=보기 번호, choice=option id, 그 외 없음
    advance(input) {
      const s = this.step();
      if (!s) throw new Error("진행 중인 이야기 없음");
      let out;
      if (s.type === "quiz") out = this._quiz(s, input);
      else if (s.type === "choice") out = this._choice(s, input);
      else if (s.type === "board") {
        if (!this.state.board || this.state.board.phase !== "done") throw new Error("보드 단계가 끝나지 않음");
        out = { type: "board", merged: this.state.board.merged };
        this.state.board = null;
      } else out = { type: s.type };
      this.state.last = out;
      if (s.type === "end") return this._finishChapter(out);
      this.state.current.step += 1;
      this._enterStep();
      return out;
    }

    // 단계에 들어갈 때 자동으로 일어나는 일(보상·합류·관계·해금)
    _enterStep() {
      const s = this.step();
      const ev = { type: s.type, gained: {} };
      if (s.type === "reward") ev.gained = this._grant(s);
      if (s.type === "companion") ev.gained = this._join(s);
      if (s.type === "relation") { this.state.relations[s.hero] = s.to; ev.gained = { relation: { hero: s.hero, to: s.to } }; }
      if (s.type === "region") ev.gained = this._region(s);
      if (s.type === "main") this.completeMain(s.main);
      if (s.type === "board") this._boardStart(s);
      this.state.entered = ev;
      return ev;
    }

    _quiz(s, i) {
      const q = this.idx.quizzes[s.quiz];
      if (!(Number.isInteger(i) && i >= 0 && i < 4)) throw new Error("보기 번호");
      const correct = i === q.correct;
      const r = correct ? s.correct || {} : s.wrong || {};
      this.state.answers[correct ? "correct" : "wrong"] += 1;
      const gained = this._grant({ exp: r.exp, stats: r.stats, knowledge: r.knowledge, items: r.items, skills: r.skills });
      return { type: "quiz", correct, answer: q.correct, explanation: q.explanation, source: q.source, gained };
    }

    _choice(s, id) {
      const o = (s.options || []).find((x) => x.id === id);
      if (!o) throw new Error("없는 선택");
      if (!this.optionEnabled(o)) throw new Error("조건 불충족");
      const bonus = o.skill_bonus && this.state.skills.includes(o.skill_bonus.skill);
      const gained = this._grant({ exp: o.exp, stats: { ...(o.effects || {}) }, knowledge: o.knowledge, items: o.items });
      if (bonus) Object.assign(gained, { bonus: this._grant({ stats: o.skill_bonus.effects, exp: o.skill_bonus.exp }) });
      if (o.relation) this.state.relations[o.relation.hero] = o.relation.to;
      return { type: "choice", option: o.id, result: bonus ? o.skill_bonus.text : o.result, lesson: o.lesson || null, historical_status: o.historical_status, gained, bonus: !!bonus };
    }
    optionEnabled(o) {
      if (o.requires_skill && !this.state.skills.includes(o.requires_skill)) return false;
      if (o.requires_stat && !(this.state.stats[o.requires_stat.stat] >= o.requires_stat.gte)) return false;
      return true;
    }

    _grant(g) {
      const out = { exp: 0, stats: {}, items: [], skills: [], knowledge: [], level_up: [] };
      for (const [k, v] of Object.entries(g.stats || {})) {
        if (k === "exp") continue;
        const before = this.state.stats[k];
        this.state.stats[k] = Math.max(0, Math.round(before + v));
        if (this.state.stats[k] !== before) out.stats[k] = this.state.stats[k] - before;
      }
      for (const it of g.items || []) if (!this.state.items.includes(it)) {
        this.state.items.push(it);
        out.items.push(it);
        for (const [k, v] of Object.entries(this.idx.items[it].effects || {})) { this.state.stats[k] += v; out.stats[k] = (out.stats[k] || 0) + v; }
      }
      for (const sk of g.skills || []) if (!this.state.skills.includes(sk)) { this.state.skills.push(sk); out.skills.push(sk); }
      for (const k of g.knowledge || []) if (!this.state.knowledge.includes(k)) {
        this.state.knowledge.push(k);
        out.knowledge.push(k);
        for (const p of this.data.policies || []) if (p.requires_knowledge === k && !this.state.policies.includes(p.id)) { this.state.policies.push(p.id); (out.policies = out.policies || []).push(p.id); }
      }
      const exp = (g.exp || 0) + ((g.stats || {}).exp || 0);
      if (exp) {
        const before = this.state.level;
        this.state.stats.exp += exp;
        out.exp = exp;
        this._recalcLevel();
        for (let l = before + 1; l <= this.state.level; l++) out.level_up.push(l);
      }
      return out;
    }

    _join(s) {
      if (!this.state.companions.includes(s.hero)) this.state.companions.push(s.hero);
      this.state.relations[s.hero] = "COMPANION";
      const h = this.idx.heroes[s.hero];
      const g = this._grant({ stats: s.stats || h.stats, skills: h.skills, exp: s.exp });
      return { companion: s.hero, ...g };
    }

    _region(s) {
      const r = this.idx.regions[s.region];
      const ok = this.state.level >= r.recommended_level;
      if (ok && !this.state.regions.includes(r.id)) this.state.regions.push(r.id);
      return { region: r.id, unlocked: ok, recommended_level: r.recommended_level, level: this.state.level };
    }

    _finishChapter() {
      const c = this.state.current;
      const st = this.idx.stories[c.story];
      const prog = this.state.stories[st.id];
      prog.chapter += 1;
      if (prog.chapter >= st.chapters.length) prog.done = true;
      this.state.log.push({ story: st.id, chapter: c.chapter, done: true });
      this.state.current = null;
      return { type: "end", story: st.id, chapter: c.chapter, story_done: prog.done };
    }

    _recalcLevel() {
      const L = this.data.levels;
      let lv = 1;
      while (lv < L.length && this.state.stats.exp >= L[lv]) lv += 1;
      this.state.level = lv;
    }

    // ---- 6-66 보드 연동: 한 턴 ----
    _boardStart(s) {
      if (!this.BoardGame) throw new Error("보드 엔진이 주입되지 않음");
      const bd = this.data.boards[s.board];
      const g = new this.BoardGame(bd.data, this.rng);
      this.state.board = { id: s.board, phase: "play" };
      this.board = g;
    }
    boardGame() { return this.state.board && this.state.board.phase === "play" ? this.board : null; }
    finishBoard() {
      const g = this.board;
      if (!g || g.state.phase !== "end") throw new Error("보드 턴이 끝나지 않음");
      const bd = this.data.boards[this.state.board.id];
      const start = bd.data.start;
      const stats = {};
      let exp = 0;
      for (const rule of bd.merge) {
        const delta = g.state.vars[rule.from] - (start[rule.from] || 0);
        if (rule.to === "exp") exp += delta * rule.rate;
        else stats[rule.to] = (stats[rule.to] || 0) + delta * rule.rate;
      }
      const skillBonus = bd.skill_bonus && this.state.skills.includes(bd.skill_bonus.skill) && g.state.vars.exploration > 0;
      if (skillBonus) for (const [k, v] of Object.entries(bd.skill_bonus.stats)) stats[k] = (stats[k] || 0) + v;
      const gained = this._grant({ stats, exp: Math.round(exp) });
      this.state.board = { id: this.state.board.id, phase: "done", merged: { ...gained, board: { ...g.state.vars }, roll: g.state.log, skill_bonus: !!skillBonus } };
      this.board = null;
      return this.state.board.merged;
    }

    // ---- 저장 ----
    serialize() {
      const st = { ...this.state };
      if (st.board && st.board.phase === "play") st.board = null; // 보드 한 턴은 저장하지 않는다(이어할 때 보드 단계부터 다시)
      return JSON.stringify({ v: SAVE_VERSION, game: this.data.id, data_version: this.data.version, state: st });
    }
    static restore(data, text, opts) {
      try {
        const o = JSON.parse(text);
        if (!o || o.v !== SAVE_VERSION || o.game !== data.id || o.data_version !== data.version) return null;
        const g = new Game(data, opts);
        const st = o.state;
        if (!st || !st.stats || !Number.isFinite(st.stats.exp)) return null;
        for (const s of data.stats) if (!Number.isFinite(st.stats[s])) return null;
        g.state = st;
        g._recalcLevel();
        if (st.current) {
          const story = g.idx.stories[st.current.story];
          const ch = story && story.chapters.find((c) => c.id === st.current.chapter);
          if (!ch || !ch.steps[st.current.step]) return null;
          if (ch.steps[st.current.step].type === "board" && !st.board) g._boardStart(ch.steps[st.current.step]);
        }
        return g;
      } catch (e) {
        return null;
      }
    }
  }

  return { Game, validate, HISTORICAL, RELATIONS, ITEM_TYPES, STEP_TYPES };
});

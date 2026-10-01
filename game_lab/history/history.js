/* 6-69 KOREA HISTORY MASTER — 역사 콘텐츠 데이터(시대·인물·엔티티·관계·어빌리티·영웅 풀·영입 퀘스트) 검증과 조회.
 * DOM·네트워크 없음. 브라우저 전역(Choice100History) + Node require 둘 다 된다.
 * 역사 시간축(eras.json)과 게임 진행 시간축(hero_pool.json)은 따로 둔다. 수치(stats·effects)는 GAME_SETTING 데이터다. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.Choice100History = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var STATUSES = ["HISTORICAL_RECORD", "HISTORICAL_INTERPRETATION", "MYTHOLOGY", "LEGEND", "LITERARY_FICTION", "GAME_SETTING"];
  var ENTITY_TYPES = ["PERSON", "HERO", "EVENT", "LOCATION", "REGION", "TERRAIN", "ARTIFACT", "TECHNOLOGY", "INSTITUTION", "CULTURE",
    "SPECIALTY", "COUNTRY", "TRIBE", "BATTLE", "KNOWLEDGE", "MYTH", "LEGEND"];
  var RELATIONS = ["TEACHER", "STUDENT", "COLLEAGUE", "RIVAL", "LORD", "VASSAL", "ALLY", "ENEMY", "FAMILY", "ERA_LINK", "EVENT_LINK"];
  var RELATION_LABEL = { TEACHER: "스승", STUDENT: "제자", COLLEAGUE: "동료", RIVAL: "라이벌", LORD: "군주", VASSAL: "신하",
    ALLY: "동맹", ENEMY: "적", FAMILY: "가족", ERA_LINK: "시대적 연관", EVENT_LINK: "사건 연관" };
  var INVERSE = { TEACHER: "STUDENT", STUDENT: "TEACHER", LORD: "VASSAL", VASSAL: "LORD" };
  var QUEST_STEPS = ["explore", "clue", "talk", "item", "knowledge", "choice", "puzzle", "condition", "recruit"];
  // 게임(6-67·6-68) 소문자 태그 → 마스터 상태
  var GAME_TAG = { historical_fact: ["HISTORICAL_RECORD"], historical_record: ["HISTORICAL_RECORD", "HISTORICAL_INTERPRETATION"],
    mythology: ["MYTHOLOGY"], legend: ["LEGEND"], game_setting: ["GAME_SETTING"] };

  function Library(d) {
    this.d = d;
    this.eras = {}; this.byId = {}; this.abilities = {}; this.stages = {}; this.gates = {}; this.quests = {};
    var self = this;
    d.eras.historical_timeline.forEach(function (e) { self.eras[e.id] = e; (e.sub_eras || []).forEach(function (s) { self.eras[s] = { id: s, parent: e.id, order: e.order }; }); });
    d.persons.concat(d.entities).forEach(function (x) { self.byId[x.id] = x; });
    d.abilities.forEach(function (a) { self.abilities[a.id] = a; });
    d.hero_pool.player_hero_timeline.forEach(function (s) { self.stages[s.id] = s; });
    d.hero_pool.time_gates.forEach(function (g) { self.gates[g.id] = g; });
    d.quests.forEach(function (q) { self.quests[q.id] = q; });
  }

  Library.prototype.get = function (id) { return this.byId[id] || this.abilities[id] || this.gates[id] || null; };
  Library.prototype.persons = function (f) { return this.d.persons.filter(f || function () { return true; }); };
  Library.prototype.songSpine = function () {
    return this.persons(function (p) { return p.song_catalog.included; }).sort(function (a, b) { return a.spine_order - b.spine_order; });
  };

  // 관계: 한 방향으로만 적어도 양쪽에서 보인다(LORD↔VASSAL처럼 방향 있는 것은 뒤집어 보인다).
  Library.prototype.relationsOf = function (id) {
    var out = [];
    this.d.relations.relations.forEach(function (r) {
      if (r.from === id) out.push({ other: r.to, type: r.type, label: RELATION_LABEL[r.type], historical_status: r.historical_status, note: r.note });
      else if (r.to === id) { var t = INVERSE[r.type] || r.type; out.push({ other: r.from, type: t, label: RELATION_LABEL[t], historical_status: r.historical_status, note: r.note }); }
    });
    return out;
  };

  // 엔티티/인물이 가리키는 모든 id(1단계)
  Library.prototype.related = function (id) {
    var x = this.byId[id]; if (!x) return [];
    var ids = [].concat(x.related_entities || [], x.key_events || [], x.related_locations || [], x.related_artifacts || [], x.knowledge || []);
    this.relationsOf(id).forEach(function (r) { ids.push(r.other); });
    var self = this;
    this.d.entities.forEach(function (e) { if ((e.related_entities || []).indexOf(id) >= 0) ids.push(e.id); });
    return ids.filter(function (v, i) { return ids.indexOf(v) === i && v !== id && self.get(v); });
  };

  // 역사 → 어빌리티: 엔티티가 여는 어빌리티(엔티티 쪽 abilities + 어빌리티 쪽 from_entities)
  Library.prototype.abilitiesFrom = function (id) {
    var x = this.byId[id], ids = (x && x.abilities) ? x.abilities.slice() : [];
    this.d.abilities.forEach(function (a) { if (a.from_entities.indexOf(id) >= 0 && ids.indexOf(a.id) < 0) ids.push(a.id); });
    return ids;
  };

  // 게임 진행 단계에서 만날 수 있는 영웅(역사 시대는 그대로, 도착 경로만 다르다)
  Library.prototype.heroPoolFor = function (stageId) {
    var self = this, order = this.stages[stageId].order;
    return this.d.hero_pool.pool.filter(function (h) { return self.stages[h.stage].order <= order; }).map(function (h) {
      var p = self.byId[h.hero];
      return { id: p.id, name: p.name, era: p.era, via: h.via, gate: h.gate || null, quest: h.quest || null, badge: h.badge || null, historical_status: p.historical_status };
    });
  };

  // 고조선 슬라이스 상태(Choice100Rpg state) → 마스터 id. state.knowledge / skills / items 는 배열 또는 {id:true}
  Library.prototype.gojoseonUnlocks = function (state) {
    var L = this.d.links.gojoseon, seen = {};
    function ids(v) { return Array.isArray(v) ? v : Object.keys(v || {}).filter(function (k) { return v[k]; }); }
    var entities = [], abilities = [], self = this;
    function add(list, id) { if (id && !seen[id]) { seen[id] = 1; list.push(id); } }
    ids(state.knowledge).forEach(function (k) { add(entities, L.knowledge[k]); });
    ids(state.items).forEach(function (k) { add(entities, L.items[k]); });
    ids(state.skills).forEach(function (k) { add(abilities, L.skills[k]); });
    ids(state.policies).forEach(function (k) { add(abilities, L.policies[k]); });
    entities.forEach(function (e) { self.abilitiesFrom(e).forEach(function (a) { add(abilities, a); }); });
    return { entities: entities, abilities: abilities };
  };

  function validate(d) {
    var errors = [], lib;
    function err(m) { errors.push(m); }
    try { lib = new Library(d); } catch (e) { return ["load: " + e.message]; }
    var ids = {};
    function uniq(id, where) { if (!/^[A-Z][A-Z0-9_]*$/.test(id)) err(where + ": id 형식 " + id); if (ids[id]) err("중복 id " + id); ids[id] = 1; }
    function status(x, where) { if (STATUSES.indexOf(x.historical_status) < 0) err(where + ": historical_status " + x.historical_status); }
    function ref(id, where) { if (!lib.get(id) && !lib.eras[id] && !lib.stages[id]) err(where + ": 없는 id " + id); }
    function src(x, where) {
      (x.source_refs || []).forEach(function (s) { if (!d.sources[s]) err(where + ": 없는 출처 " + s); });
      // 기록·해석·신화·전설은 출처가 있어야 한다(검수 대기 표시는 예외)
      if (x.historical_status !== "GAME_SETTING" && x.review_status !== "needs_review" && !(x.source_refs || []).length) err(where + ": 출처 없음");
    }
    Object.keys(d.sources).forEach(function (k) {
      var s = d.sources[k]; if (!/^https:\/\//.test(s.url) || !/^\d{4}-\d{2}-\d{2}$/.test(s.checked)) err("source " + k);
    });
    d.eras.historical_timeline.forEach(function (e, i) { uniq(e.id, "era"); status(e, e.id); if (e.order !== i + 1) err("era order " + e.id); });

    d.persons.forEach(function (p) {
      var w = "person " + p.id; uniq(p.id, "person"); status(p, w); src(p, w);
      if (p.type !== "PERSON") err(w + ": type");
      if (!lib.eras[p.era]) err(w + ": era " + p.era);
      if (!p.name || !p.historical_summary || !p.roles || !p.roles.length || !p.country) err(w + ": 필수 필드");
      if (typeof p.hero_eligible !== "boolean" || !p.song_catalog || typeof p.song_catalog.included !== "boolean") err(w + ": 플래그");
      if (!p.hero_eligible && !p.hero_note) err(w + ": 영웅 제외 사유 없음");
      if (p.historical_status === "LITERARY_FICTION" && !p.hero_note) err(w + ": 문학 인물 표시 없음");
      Object.keys(p.base_stats || {}).forEach(function (k) { var v = p.base_stats[k]; if (typeof v !== "number" || v < 0 || v > 10) err(w + ": stat " + k); });
      if (!/GAME_SETTING/.test(p.game_data_note || "")) err(w + ": 수치가 게임 데이터라는 표시 없음");
      [].concat(p.key_events, p.related_locations, p.related_artifacts, p.knowledge).forEach(function (r) { ref(r, w); });
      p.abilities.forEach(function (a) { if (!lib.abilities[a]) err(w + ": 없는 어빌리티 " + a); });
      if (p.recruit_quest && !lib.quests[p.recruit_quest]) err(w + ": 없는 퀘스트 " + p.recruit_quest);
      if (!p.hero_eligible && (p.recruit_quest || p.recruit_method)) err(w + ": 영웅 제외 인물에 영입 경로");
    });
    d.entities.forEach(function (e) {
      var w = "entity " + e.id; uniq(e.id, "entity"); status(e, w); src(e, w);
      if (ENTITY_TYPES.indexOf(e.type) < 0) err(w + ": type " + e.type);
      if (e.era !== null && !lib.eras[e.era]) err(w + ": era " + e.era);
      ["name", "description"].forEach(function (f) { if (!e[f]) err(w + ": " + f); });
      if (!Array.isArray(e.related_entities) || !Array.isArray(e.abilities) || typeof e.game_effects !== "object" || !("unlock_condition" in e)) err(w + ": 필드 모양");
      e.related_entities.forEach(function (r) { ref(r, w); });
      e.abilities.forEach(function (a) { if (!lib.abilities[a]) err(w + ": 없는 어빌리티 " + a); });
      if (e.type === "MYTH" && e.historical_status !== "MYTHOLOGY") err(w + ": 신화 상태");
      if (e.type === "LEGEND" && e.historical_status !== "LEGEND") err(w + ": 전설 상태");
      if (e.type === "TRIBE" && e.historical_status === "HISTORICAL_RECORD") err(w + ": 가상 부족을 기록으로 표시");
    });
    d.abilities.forEach(function (a) {
      var w = "ability " + a.id; uniq(a.id, "ability");
      if (a.historical_status !== "GAME_SETTING") err(w + ": 어빌리티 수치는 GAME_SETTING");
      if (!a.from_entities.length) err(w + ": 근거 엔티티 없음");
      a.from_entities.forEach(function (r) { ref(r, w); });
      if (!a.effects || !Object.keys(a.effects).length) err(w + ": 효과 없음");
    });
    // 모든 어빌리티는 누군가(인물/엔티티)가 연다
    d.abilities.forEach(function (a) {
      var used = d.persons.concat(d.entities).some(function (x) { return (x.abilities || []).indexOf(a.id) >= 0; });
      if (!used) err("ability " + a.id + ": 여는 인물·엔티티 없음");
    });
    d.relations.relations.forEach(function (r, i) {
      var w = "relation " + i;
      if (RELATIONS.indexOf(r.type) < 0) err(w + ": type " + r.type);
      if (!lib.byId[r.from] || !lib.byId[r.to]) err(w + ": 없는 인물 " + r.from + "/" + r.to);
      if (r.from === r.to) err(w + ": 자기 자신");
      status(r, w);
      // 게임 설정 관계는 역사 기록 인물 사이라도 GAME_SETTING으로만
      var a = lib.byId[r.from], b = lib.byId[r.to];
      if (a && b && a.era !== b.era && r.type !== "ERA_LINK" && r.type !== "EVENT_LINK" && r.historical_status === "HISTORICAL_RECORD" && !r.note) err(w + ": 시대가 다른 관계에 근거 메모 없음");
    });
    // 영웅 풀(게임 시간축)
    var hp = d.hero_pool;
    hp.player_hero_timeline.forEach(function (s, i) { uniq(s.id, "stage"); if (s.order !== i + 1) err("stage order " + s.id); s.native_eras.forEach(function (e) { if (!lib.eras[e]) err("stage era " + e); }); });
    hp.time_gates.forEach(function (g) { uniq(g.id, "gate"); if (g.historical_status !== "GAME_SETTING") err("gate " + g.id + " 는 GAME_SETTING"); });
    hp.pool.forEach(function (h) {
      var p = lib.byId[h.hero], s = lib.stages[h.stage], w = "pool " + h.hero;
      if (!p || !s) return err(w + ": 없는 인물/단계");
      if (!p.hero_eligible) err(w + ": 영웅 제외 인물");
      var eraOrder = (lib.eras[p.era] || {}).order, native = s.native_eras.indexOf(p.era) >= 0;
      if (h.via === "native" && !native) err(w + ": 자기 시대 단계가 아닌데 native");
      if (!native && h.via !== "time_gate") err(w + ": 시대를 넘으면 time_gate 필요");
      if (h.via === "time_gate" && !lib.gates[h.gate]) err(w + ": 없는 시간의 문 " + h.gate);
      if (eraOrder === undefined) err(w + ": era");
      if (h.quest && lib.quests[h.quest].hero !== h.hero) err(w + ": 퀘스트 영웅 불일치");
    });
    d.quests.forEach(function (q) {
      var w = "quest " + q.id; uniq(q.id, "quest");
      if (q.historical_status !== "GAME_SETTING") err(w + ": GAME_SETTING");
      if (!lib.byId[q.hero] || !lib.byId[q.hero].hero_eligible) err(w + ": 영웅");
      if (q.steps[q.steps.length - 1].type !== "recruit" || q.steps[q.steps.length - 1].ref !== q.hero) err(w + ": 마지막은 영입");
      q.steps.forEach(function (s) { if (QUEST_STEPS.indexOf(s.type) < 0) err(w + ": step " + s.type); if (s.ref) ref(s.ref, w); });
    });
    // 노래 목차: 수록 여부만, 가사 없음
    var song = d.persons.filter(function (p) { return p.song_catalog.included; });
    if (song.length !== d.song_catalog.expected_count) err("song: 수록 인물 " + song.length + "명");
    Object.keys(d.song_catalog.groups).forEach(function (g) {
      var n = d.persons.filter(function (p) { return p.group === g && p.song_catalog.included; }).length;
      if (n !== d.song_catalog.groups[g]) err("song group " + g + ": " + n);
    });
    var orders = d.persons.map(function (p) { return p.spine_order; });
    if (orders.some(function (o, i) { return orders.indexOf(o) !== i; })) err("spine_order 중복");
    // 고조선 연결
    var L = d.links && d.links.gojoseon;
    if (!L) err("links.gojoseon 없음");
    else ["knowledge", "items", "skills", "tribes", "locations", "events", "policies", "companions"].forEach(function (g) {
      Object.keys(L[g]).forEach(function (k) { ref(L[g][k], "gojoseon." + g + "." + k); });
    });
    return errors;
  }

  // 게임 태그와 마스터 상태가 서로 맞는지(연결 검증용)
  function compatible(gameTag, masterStatus) { return (GAME_TAG[gameTag] || []).indexOf(masterStatus) >= 0; }

  var FILES = ["eras", "persons", "entities", "relations", "abilities", "hero_pool", "quests", "song_catalog", "sources"];
  // 브라우저: fetch로 읽는다(같은 출처 정적 파일만). Node: require.
  function load(base, fetchFn) {
    var parts = FILES.map(function (f) { return base + "/" + f + ".json"; }).concat([base + "/links/gojoseon.json"]);
    return Promise.all(parts.map(function (u) { return fetchFn(u).then(function (r) { return r.json(); }); })).then(function (arr) {
      var d = {}; FILES.forEach(function (f, i) { d[f] = arr[i]; }); d.links = { gojoseon: arr[FILES.length] }; return d;
    });
  }
  function loadNode(dir) {
    var path = require("path"), d = {};
    dir = path.resolve(dir);
    FILES.forEach(function (f) { d[f] = require(path.join(dir, f + ".json")); });
    d.links = { gojoseon: require(path.join(dir, "links", "gojoseon.json")) };
    return d;
  }

  return { STATUSES: STATUSES, ENTITY_TYPES: ENTITY_TYPES, RELATIONS: RELATIONS, RELATION_LABEL: RELATION_LABEL, QUEST_STEPS: QUEST_STEPS,
    Library: Library, validate: validate, compatible: compatible, load: load, loadNode: loadNode };
});

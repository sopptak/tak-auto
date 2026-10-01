// node --test game_lab/history/test/history.test.js
"use strict";
const test = require("node:test");
const assert = require("node:assert");
const path = require("path");
const H = require("../history.js");

const DATA = path.join(__dirname, "..", "data");
const fresh = () => JSON.parse(JSON.stringify(H.loadNode(DATA))); // require 캐시를 건드리지 않게 복사
const G = require("../../rpg/gojoseon/gojoseon.json");

test("스키마: 전체 데이터가 검증을 통과한다", () => {
  assert.deepStrictEqual(H.validate(fresh()), []);
});

test("스키마: 필드가 빠지거나 타입이 틀리면 잡는다", () => {
  const d = fresh();
  delete d.entities[0].description;
  d.entities[1].type = "DRAGON";
  d.persons[0].era = "ATLANTIS";
  const e = H.validate(d).join("\n");
  assert.match(e, /description/);
  assert.match(e, /type DRAGON/);
  assert.match(e, /era ATLANTIS/);
});

test("historical_status: 허용 값만, 신화·전설·가상 부족은 기록이 될 수 없다", () => {
  const d = fresh();
  assert.ok(d.persons.concat(d.entities).every((x) => H.STATUSES.includes(x.historical_status)));
  const myth = d.entities.find((e) => e.type === "MYTH");
  myth.historical_status = "HISTORICAL_RECORD";
  d.entities.find((e) => e.type === "TRIBE").historical_status = "HISTORICAL_RECORD";
  d.persons[1].historical_status = "FACT";
  const e = H.validate(d).join("\n");
  assert.match(e, /신화 상태/);
  assert.match(e, /가상 부족/);
  assert.match(e, /historical_status FACT/);
});

test("historical_status: 출처 없는 기록은 검수 대기 표시가 있어야 한다", () => {
  const d = fresh();
  const x = d.entities.find((e) => e.review_status === "source_checked");
  x.source_refs = [];
  assert.match(H.validate(d).join("\n"), /출처 없음/);
  const bad = fresh();
  bad.entities[0].source_refs = ["SRC_NOPE"];
  assert.match(H.validate(bad).join("\n"), /없는 출처/);
});

test("신화와 사실 구분: 단군·아사달·홍익인간은 신화, 고인돌·비파형 동검은 기록", () => {
  const L = new H.Library(fresh());
  for (const id of ["DAN_GUN", "LOC_ASADAL", "KN_HONGIK", "MY_DANGUN", "EV_GOJOSEON_FOUNDING_MYTH", "KN_DANGUN_MYTH"]) assert.strictEqual(L.get(id).historical_status, "MYTHOLOGY", id);
  for (const id of ["AR_DOLMEN", "AR_BIPA_DAGGER", "IN_EIGHT_LAWS", "EV_GOJOSEON_FALL"]) assert.strictEqual(L.get(id).historical_status, "HISTORICAL_RECORD", id);
  assert.strictEqual(L.get("LG_COTTON_BRUSHCAP").historical_status, "LEGEND");
  assert.strictEqual(L.get("HONG_GILDONG").historical_status, "LITERARY_FICTION");
  // 논쟁 중인 건국 연도를 사실로 쓰지 않는다
  assert.ok(!JSON.stringify(fresh()).includes("2333"));
});

test("영웅 타임라인: 역사 시간축과 게임 시간축이 분리되고, 시대를 넘는 영웅은 시간의 문으로만 온다", () => {
  const d = fresh();
  const L = new H.Library(d);
  const g = L.heroPoolFor("STAGE_GOJOSEON").map((h) => h.id);
  assert.deepStrictEqual(g, ["DAN_GUN", "JUMONG", "GWANGGAETO"]);
  const jumong = L.heroPoolFor("STAGE_GOJOSEON").find((h) => h.id === "JUMONG");
  assert.strictEqual(jumong.era, "THREE_KINGDOMS"); // 역사 시대는 그대로
  assert.strictEqual(jumong.via, "time_gate");
  assert.ok(L.heroPoolFor("STAGE_JOSEON").length >= L.heroPoolFor("STAGE_GORYEO").length);
  // 역사 시간축 순서는 고정
  assert.deepStrictEqual(d.eras.historical_timeline.map((e) => e.id), ["BRONZE_AGE", "GOJOSEON", "THREE_KINGDOMS", "NORTH_SOUTH_STATES", "GORYEO", "JOSEON", "MODERN"]);
  const bad = fresh();
  bad.hero_pool.pool.find((h) => h.hero === "JUMONG").via = "native";
  assert.match(H.validate(bad).join("\n"), /native/);
  const bad2 = fresh();
  bad2.hero_pool.pool.push({ hero: "YI_WANYONG", stage: "STAGE_MODERN", via: "native" });
  assert.match(H.validate(bad2).join("\n"), /영웅 제외 인물/);
});

test("관계: 11종, 양쪽에서 보이고 방향 관계는 뒤집힌다", () => {
  const d = fresh();
  const L = new H.Library(d);
  assert.strictEqual(H.RELATIONS.length, 11);
  const sj = L.relationsOf("SEJONG");
  assert.ok(sj.some((r) => r.other === "JANG_YEONGSIL" && r.type === "LORD"));
  assert.ok(L.relationsOf("JANG_YEONGSIL").some((r) => r.other === "SEJONG" && r.type === "VASSAL" && r.label === "신하"));
  assert.ok(L.relationsOf("ONJO").some((r) => r.other === "JUMONG" && r.type === "FAMILY"));
  const bad = fresh();
  bad.relations.relations.push({ from: "SEJONG", to: "NOBODY", type: "FRIEND", historical_status: "HISTORICAL_RECORD" });
  const e = H.validate(bad).join("\n");
  assert.match(e, /type FRIEND/);
  assert.match(e, /없는 인물/);
});

test("역사 → 어빌리티: 모든 어빌리티는 근거 엔티티가 있고, 엔티티에서 거꾸로 찾을 수 있다", () => {
  const d = fresh();
  const L = new H.Library(d);
  assert.ok(L.abilitiesFrom("IN_JINDAE").includes("AB_JINDAE"));
  assert.ok(L.abilitiesFrom("AR_BIPA_DAGGER").includes("AB_BRONZE_CASTING"));
  assert.ok(L.abilitiesFrom("SEJONG").includes("AB_HUNMINJEONGEUM"));
  assert.ok(d.abilities.every((a) => a.historical_status === "GAME_SETTING"));
  const kinds = new Set(d.abilities.map((a) => a.kind));
  for (const k of ["nation", "tactic", "movement", "production", "equipment", "hero"]) assert.ok(kinds.has(k), k); // 미니게임 강제 없음
  const bad = fresh();
  bad.persons[0].abilities.push("AB_TELEPORT");
  bad.abilities.push({ id: "AB_ORPHAN", from_entities: ["TE_BRONZE"], effects: { x: 1 }, historical_status: "GAME_SETTING" });
  const e = H.validate(bad).join("\n");
  assert.match(e, /AB_TELEPORT/);
  assert.match(e, /AB_ORPHAN: 여는 인물/);
});

test("100인 seed: 노래 수록 100명(묶음 포함), 가사 없음, 100명 밖으로 확장된다", () => {
  const d = fresh();
  const L = new H.Library(d);
  const spine = L.songSpine();
  assert.strictEqual(spine.length, 100);
  assert.ok(d.persons.length > 100);
  assert.ok(d.persons.filter((p) => !p.song_catalog.included).every((p) => p.review_status !== "identity_checked"));
  // 시대 순서가 연대를 거스르지 않는다(spine = 우리가 정한 연대순)
  const order = Object.fromEntries(d.eras.historical_timeline.map((e) => [e.id, e.order]));
  for (let i = 1; i < spine.length; i++) assert.ok(order[spine[i].era] >= order[spine[i - 1].era], spine[i].id);
  // 모든 인물이 시대·나라·역할·요약을 가진다
  assert.ok(d.persons.every((p) => p.era && p.country && p.roles.length && p.historical_summary));
  // 비판받는 인물·문학 인물은 영웅이 아니거나 배지가 있다
  assert.strictEqual(L.get("YI_WANYONG").hero_eligible, false);
  assert.strictEqual(L.get("YI_SUIL").hero_eligible, false);
  assert.ok(L.get("HONG_GILDONG").hero_note.includes("문학"));
  const bad = fresh();
  bad.persons.find((p) => p.id === "SEJONG").song_catalog.included = false;
  assert.match(H.validate(bad).join("\n"), /수록 인물 99명/);
});

test("영입 퀘스트: 탐험→단서→대화→아이템→지식→선택→퍼즐→조건→영입 단계만 쓰고 영입으로 끝난다", () => {
  const d = fresh();
  for (const q of d.quests) {
    assert.strictEqual(q.steps.at(-1).type, "recruit");
    assert.ok(q.steps.every((s) => H.QUEST_STEPS.includes(s.type)));
  }
  const bad = fresh();
  bad.quests[0].steps.push({ type: "pay" });
  assert.match(H.validate(bad).join("\n"), /step pay|마지막은 영입/);
});

test("고조선 연결: 슬라이스의 모든 id가 마스터에 이어지고 상태 태그가 맞는다", () => {
  const d = fresh();
  const L = new H.Library(d);
  const link = d.links.gojoseon;
  const X = G.explore;
  const gameIds = {
    knowledge: G.knowledge, items: G.items, skills: G.skills, policies: G.policies, companions: G.heroes,
    tribes: X.tribes, locations: X.locations,
  };
  for (const [group, list] of Object.entries(gameIds)) {
    for (const x of list) assert.ok(link[group][x.id], `${group}/${x.id} 연결 없음`);
  }
  for (const k of Object.keys(link.events)) assert.ok(X.events.some((e) => e.id === k), k);
  for (const k of G.knowledge) {
    const m = L.get(link.knowledge[k.id]);
    assert.ok(H.compatible(k.historical_status, m.historical_status), `${k.id}: ${k.historical_status} vs ${m.historical_status}`);
  }
  const u = L.gojoseonUnlocks({ knowledge: ["k_bipa", "k_8laws", "k_dolmen"], skills: { farming: true }, policies: ["eight_laws"] });
  assert.deepStrictEqual(u.entities, ["KN_BIPA", "KN_EIGHT_LAWS", "KN_DOLMEN"]);
  for (const a of ["AB_AGRICULTURE", "AB_EIGHT_LAWS", "AB_BRONZE_CASTING", "AB_MONUMENT_LABOR"]) assert.ok(u.abilities.includes(a), a);
  // 고조선 핵심 주제 15개가 모두 마스터에 있다
  for (const id of ["CT_GOJOSEON", "DAN_GUN", "TE_BRONZE", "AR_DOLMEN", "AR_BIPA_DAGGER", "TE_AGRICULTURE", "TR_HUNTERS", "CU_SETTLEMENT",
    "TN_MOUNTAIN", "TN_RIVER", "TN_PLAIN", "SP_SALT_TRADE", "AB_EXPLORATION", "MY_DANGUN", "IN_EIGHT_LAWS"]) assert.ok(L.get(id), id);
});

test("고조선 도감 카드: 게임 상태에서 역사 기록과 해금 어빌리티를 출처 데이터와 함께 조회한다", () => {
  const L = new H.Library(fresh());
  const state = { knowledge: ["k_dolmen", "k_myth", "k_dolmen"], skills: ["tracking", "tracking"] };
  const cards = L.gojoseonCards(state);
  assert.deepStrictEqual(cards.entities.map((x) => x.id), ["KN_DOLMEN", "KN_DANGUN_MYTH"]);
  assert.ok(cards.entities.every((x) => x.description && x.source_refs.length));
  assert.ok(cards.abilities.some((x) => x.id === "AB_TRACKING"));
  assert.ok(cards.abilities.every((x) => x.historical_status === "GAME_SETTING"));
  assert.deepStrictEqual(L.gojoseonCards(state), cards);
  const empty = L.gojoseonCards({ knowledge: [], skills: [], items: [], policies: [] });
  assert.deepStrictEqual(empty, { entities: [], abilities: [] });
});

# 6-69 KOREA HISTORY MASTER CONTENT SYSTEM

> 「한국을 빛낸 100명의 위인들」을 **역사 콘텐츠 목차(Spine)** 로 삼아, 시대·인물·엔티티·관계·어빌리티·영웅 풀을
> 앞으로 무한히 확장할 수 있는 게임 데이터 구조로 만들었다. 게임 방향은 바꾸지 않고 확장만 했다.

- 모듈: `game_lab/history/` (`history.js` + `data/*.json`), DOM·네트워크 없음, 브라우저 전역 `Choice100History` + Node require
- 기존 코드 변경: **없음** (rpg·board·choice100 파일 그대로. 새 파일만 추가)
- 테스트: node 11 + Python `tests/test_6_69_history.py`

## 1. 게임 역사 Spine

- 노래는 **목차 / 기억의 레일 / 영웅 카탈로그의 출발점**이다. 사실 검증의 권위가 아니다.
- 가사·가사 속 수식어는 싣지 않는다. `persons.json`의 `song_catalog.included`(true/false)만 저장한다.
- 순서는 노래 순서가 아니라 게임이 정한 연대순 `spine_order`를 쓴다(`Library.songSpine()`).
- 노래의 구절 → 시대 대응(`song_catalog.json` `verse_eras`)만 둔다: 1절 고조선·삼국, 2절 남북국·고려, 3·4절 조선, 5절 근현대.

## 2. 시대 구조

`eras.json` = **HISTORICAL_TIMELINE** (고정, 게임 진행으로 바뀌지 않음)

`BRONZE_AGE → GOJOSEON → THREE_KINGDOMS → NORTH_SOUTH_STATES → GORYEO → JOSEON → MODERN`

세분화가 필요하면 시대 id를 추가하고(예: `JOSEON_LATE`), 인물·엔티티의 `era`가 그 id를 가리키게 하면 된다. 검증기는 존재하지 않는 era를 오류로 잡는다.

## 3. 시대 초월 영웅 구조

두 축을 분리했다.

| 축 | 파일 | 의미 |
|---|---|---|
| HISTORICAL_TIMELINE | `eras.json` | 인물이 실제로 활동한 시대. 절대 바뀌지 않음 |
| PLAYER_HERO_TIMELINE | `hero_pool.json` | 플레이어가 겪는 단계(STAGE_GOJOSEON → … → STAGE_MODERN) |

- `pool`: 단계별로 영입 가능한 영웅. `via: native`(그 시대 인물) 또는 `via: time_gate`(다른 시대 인물).
- 규칙: 자기 시대보다 **이른** 단계에서 만나는 영웅은 반드시 `time_gate`(GAME_SETTING)로만 온다. 인물의 `era`는 바뀌지 않는다. 검증기가 강제한다.
- 예: STAGE_GOJOSEON 풀 = 단군(native, 신화 배지), 주몽(TG_JOLBON), 광개토대왕(TG_MANCHURIA), 장보고(TG_SEA) …
- 조회: `Library.heroPoolFor("STAGE_GOJOSEON")`.

## 4. Entity schema

타입 17종: PERSON, HERO, EVENT, LOCATION, REGION, TERRAIN, ARTIFACT, TECHNOLOGY, INSTITUTION, CULTURE, SPECIALTY, COUNTRY, TRIBE, BATTLE, KNOWLEDGE, MYTH, LEGEND

필드: `id, name, era, type, historical_status, description, source_refs, related_entities, game_effects, abilities, stats, unlock_condition` (+ `review_status`)

- id는 `^[A-Z][A-Z0-9_]*$`, 전 파일에서 유일.
- `related_entities`·`abilities`·`source_refs`는 모두 존재하는 id여야 한다.
- 현재 seed: 엔티티 75개 (EVENT 14, KNOWLEDGE 13, COUNTRY 7, ARTIFACT 7, TERRAIN 6, BATTLE 5, TECHNOLOGY 5, TRIBE 4, …).

## 5. Hero schema

`persons.json` 한 명 = `id, type:PERSON, name, era, country, roles, historical_summary, historical_status, spine_order, song_catalog, hero_eligible, key_events, related_locations, related_artifacts, knowledge, abilities, source_refs, review_status, base_stats, recruit_method, recruit_quest, special_event, hero_story, game_data_note`

- `base_stats`(might/wisdom/charm/explore)와 `abilities`는 **게임 밸런스용 GAME_SETTING 데이터**다. 모든 인물에 `game_data_note`로 명시한다.
- `historical_summary`는 직접 쓴 요약이다(가사·백과 문장 복제 아님).
- `hero_eligible: false` — 영웅으로 쓰지 않는 인물: 이완용(매국 행위, 역사 지식으로만), 김두한(평가 논쟁, 검토 필요), 정중부·한명회(정변 인물, 라이벌 NPC로만), 이수일·심순애(문학 속 인물).
- 현재: 인물 106명 (노래 수록 100 + 추가), 시대별 고조선 1 · 삼국 16 · 남북국 3 · 고려 19 · 조선 51 · 근현대 16.

## 6. Person relationship

`relations.json`: `{from, to, type, historical_status, note}` — 시대가 다른 인물 사이의 RECORD 관계는 근거 메모 필수

타입 11종: TEACHER(스승), STUDENT(제자), COLLEAGUE(동료), RIVAL(라이벌), LORD(군주), VASSAL(신하), ALLY(동맹), ENEMY(적), FAMILY(가족), ERA_LINK(시대적 연관), EVENT_LINK(사건 연관)

- 현재 53개 (ALLY 13, LORD 11, FAMILY 8, ENEMY 8, ERA_LINK 6, EVENT_LINK 6, COLLEAGUE 1).
- 검증: 양 끝 id 존재, 자기 자신 금지, 중복 금지.
- 조회: `relationsOf(id)`(양방향, 역방향 라벨 자동), `related(id)`(엔티티 링크 포함 전체 이웃) — 시대 초월 영웅 네트워크의 기반.

## 7. History → Ability

`abilities.json`: `{id, name, kind, from_entities, effects, description, historical_status: GAME_SETTING, note}` — 38개

| 역사 엔티티 | 어빌리티 | 종류 |
|---|---|---|
| 진대법(IN_JINDAE) | 국가 운영 | governance |
| 청동기·비파형동검 | AB_BRONZE_CASTING | equipment |
| 농경 | AB_AGRICULTURE | production |
| 강·산 지형 | 이동·방어·교역 | terrain |
| 전투(BATTLE) | 전술 | tactics |
| 인물 | 영웅 능력 | hero |
| 유물 | 아이템 능력 | item |

- 지식을 **발견·이해**하면 어빌리티가 열린다(`abilitiesFrom(id)`). 미니게임을 강제하지 않는다.
- 어빌리티 효과 수치는 GAME_SETTING, 근거 엔티티의 역사 상태는 `from_entities` 쪽에서 따로 본다.
- 검증: 모든 어빌리티는 1개 이상 존재하는 엔티티에서 나와야 하고, 엔티티/인물이 가리키는 어빌리티는 모두 존재해야 한다.

## 8. 동요 기반 seed catalog의 역할

- 노래 수록 100명 전원이 `persons.json`에 있다(`song_catalog.included: true`, 검증기가 정확히 100명을 확인).
- 강좌칠현·태정태세문단세·사육신·생육신·삼학사처럼 묶음으로 불리는 인물은 개인으로 풀었다.
- 목표는 100명으로 끝내기가 아니다: 조력자·라이벌·상인·학자·장군·예술가·기술자·탐험가·통치자를 `included: false`로 계속 추가한다(현재 추가 6명).
- 노래가 사실과 다르게 알려진 부분은 데이터에서 교정한다. 예: 문익점의 붓두껍은 후대 전승(LEGEND 지식으로 분리), 최영의 "황금 보기를 돌같이"는 『고려사』상 아버지의 훈계.

## 9. 역사/신화/전승/게임설정 구분

`historical_status` 6종

| 상태 | 의미 | 예 |
|---|---|---|
| HISTORICAL_RECORD | 기록·유물로 확인 | 8조법, 고인돌, 비파형동검 |
| HISTORICAL_INTERPRETATION | 학계 해석·추정(확정 아님) | 고조선 중심지·강역 |
| MYTHOLOGY | 신화 | 단군 신화, 홍익인간 |
| LEGEND | 전승·전설 | 백결 선생, 논개 일화, 붓두껍 |
| LITERARY_FICTION | 문학 속 인물(요구 5종에 추가) | 홍길동, 이수일·심순애 |
| GAME_SETTING | 게임 창작 | 시간의 문, 수치, 퀘스트 |

- 인물: RECORD 100, LEGEND 2, LITERARY_FICTION 3, MYTHOLOGY 1.
- 엔티티: RECORD 49, GAME_SETTING 14, MYTHOLOGY 6, INTERPRETATION 4, LEGEND 2.
- GAME_SETTING 외 모든 상태는 `source_refs` 필수(검증기 강제, `review_status: needs_review`만 예외). 출처는 `sources.json`(한국민족문화대백과 encykorea, ko.wikipedia).
- 기존 게임 태그(lowercase)와의 호환: `compatible(gameTag, masterStatus)` — `historical_fact → HISTORICAL_RECORD`, `mythology → MYTHOLOGY` 등. 링크 검증에서 불일치를 잡는다.

## 10. Gojoseon 연결

`data/links/gojoseon.json`이 6-68 `gojoseon.json`의 id를 마스터 id로 잇는다. 게임 파일은 수정하지 않았다.

| 게임 | 마스터 | 상태 |
|---|---|---|
| k_dolmen (고인돌) | KN_DOLMEN | RECORD |
| k_bipa, bipa_sword (비파형동검) | KN_BIPA, AR_BIPA_DAGGER | RECORD |
| k_myth, k_dangun (단군) | KN_DANGUN_MYTH, DAN_GUN | MYTHOLOGY |
| k_jejeong | KN_JEJEONG_ILCHI | RECORD |
| k_hongik | KN_HONGIK | MYTHOLOGY |
| k_8laws, eight_laws | KN_EIGHT_LAWS, IN_EIGHT_LAWS | RECORD |
| farming (농경) | AB_AGRICULTURE | GAME_SETTING |
| bronze_tools (청동기) | AB_BRONZE_CASTING | GAME_SETTING |
| trade_route (교역) | AB_RIVER_TRADE | GAME_SETTING |
| tracking (탐험) | AB_TRACKING | GAME_SETTING |
| hunters/farmers/crafters/traders (부족) | TR_* | GAME_SETTING |
| raft·river·ridge (강·산 지형) | TN_* | — |
| k_hunt_signal, k_river, k_bronze_mix | KN_* | GAME_SETTING |

- `Library.gojoseonUnlocks(state)`: 고조선 게임 상태(knowledge/skills/items/tribes) → 해금된 마스터 엔티티·어빌리티 목록.
- 테스트가 링크의 양쪽 id 존재와 상태 호환(게임 태그 ↔ 마스터 상태)을 확인한다.
- 회귀: 6-68 테스트 스위트(엔진·자동 플레이·화면 정적 점검) 통과. rpg 파일은 이번 작업에서 바뀌지 않았다(git diff 없음). 390px 실측은 6-68에서 통과한 화면 그대로이며, 이번 세션에서 Chrome 재실측은 하지 않았다.

## 11. Open Source audit

| 범주 | 후보 | 라이선스 | 판단 |
|---|---|---|---|
| hex map | honeycomb-grid | MIT, 0 deps, 52KB | 보류 — 현재 5×4 격자로 충분. 헥스 전략 맵 도입 시 1순위 |
| fog of war / FOV | rot.js | BSD-3 | 보류 — hidden/reveal 플래그로 충분 |
| pathfinding | PathFinding.js | **LICENSE 파일 없음, npm license 없음** | 사용 금지(라이선스 불명). 필요 시 EasyStar(MIT, 9KB) |
| turn system | boardgame.io | MIT, 2.8MB, 22 deps | 보류 — 무겁다. 6-66 board 엔진 유지 |
| dialogue / quest | inkjs, Yarn | MIT | 보류 — 데이터 스텝 형식으로 충분 |
| event engine | mitt | MIT | 보류 — 필요 시 수 줄로 직접 |
| game framework | Phaser / Excalibur / KAPLAY / PixiJS | MIT / BSD-2 / MIT / MIT | 보류(6-68 조사 재사용) |
| map editor | Tiled | 에디터 GPL, libtiled BSD | 에디터 산출물만 쓰면 무관 |
| assets | Kenney | CC0 (상업 사용 가능) | 그래픽 도입 시 1순위 |

코드 라이선스와 에셋 라이선스를 구분해 기록했다. 이번 작업은 **외부 코드 채택 없음**: 순수 데이터 + 검증기라 기존 구현이 더 단순하고 안전하다. 도입 시 LICENSE 원문과 attribution을 `game_lab/<module>/THIRD_PARTY.md`에 남긴다.

## 12. 향후 삼국/고려/조선/근현대 확장 방법

1. 인물 추가: `persons.json`에 한 명 추가 → `era`, `country`, `source_refs`, `review_status`. 노래 밖 인물은 `song_catalog.included: false`.
2. 엔티티 추가: 사건·전투·제도·유물을 `entities.json`에 추가하고 `abilities`로 어빌리티를 연결.
3. 관계 추가: `relations.json`에 `{from,to,type}` 한 줄.
4. 단계 플레이: 새 슬라이스(예: `rpg/three_kingdoms`)를 만들면 `hero_pool.json` 단계에 `game`을 적고, `data/links/<stage>.json`으로 게임 id를 마스터 id에 잇는다.
5. 시대 초월 영입: `pool`에 `{hero, stage, via:"time_gate", gate, quest}` 추가 + `quests.json`에 영입 퀘스트.
6. 논쟁 인물은 `hero_eligible: false` 또는 `review_status: review_required`로 두고 확정 사실처럼 쓰지 않는다.
7. 검증기(`validate`)가 id·참조·상태·출처·타임라인 규칙을 전부 잡으므로 데이터만 늘리면 된다.

## 13. 다음 개발 단계

1. 고조선 화면에 "발견한 역사 카드"(gojoseonUnlocks 결과) 표시 — 작은 UI.
2. `designed` 상태 영입 퀘스트(광개토대왕·세종·장영실)를 탐험 엔진 이벤트로 구현.
3. STAGE_THREE_KINGDOMS 슬라이스: 주몽(6-67)을 삼국 단계 첫 장으로 편입.
4. 인물 `review_status`(source_checked 5 · identity_checked 96 · needs_review 5)를 encykorea 출처로 하나씩 `source_checked`로 올리기.
5. 관계망 확충(스승·제자·라이벌 부족).

## 결과

| 항목 | 값 |
|---|---|
| 시대 | 7 |
| 인물 | 106 (노래 수록 100) |
| 엔티티 | 75 (17타입 중 PERSON/HERO 외 15타입 사용) |
| 관계 | 53 |
| 어빌리티 | 38 |
| 영입 퀘스트 | 4 (JUMONG playable, 광개토대왕·세종·장영실 designed) |
| 출처 | 14 |
| 검증 오류 | 0 |
| 금지 사항 | 가사 미수록, 프로덕션 데이터 변경 없음, 외부 API·업로드 없음 |

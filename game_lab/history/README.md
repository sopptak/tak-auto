# game_lab/history — 6-69 KOREA HISTORY MASTER

역사 콘텐츠 데이터(시대·인물·엔티티·관계·어빌리티·영웅 풀·영입 퀘스트)와 검증기. DOM·네트워크 없음.
설계 `docs/6-69-korea-history-master-content-system.md`.

| 파일 | 역할 |
|---|---|
| `history.js` | `validate(d)`, `Library`(get·related·relationsOf·abilitiesFrom·heroPoolFor·songSpine·gojoseonUnlocks), `load`/`loadNode` |
| `data/eras.json` | HISTORICAL_TIMELINE (고정) |
| `data/hero_pool.json` | PLAYER_HERO_TIMELINE, time_gates, 단계별 영웅 풀 |
| `data/persons.json` | 인물 106명(노래 수록 100 + 추가) |
| `data/entities.json` | 인물 외 엔티티 17타입 |
| `data/relations.json` | 인물 관계망 |
| `data/abilities.json` | 역사 엔티티 → 게임 어빌리티 |
| `data/quests.json` | King's Quest식 영입 퀘스트 |
| `data/song_catalog.json` | 노래 수록 정책(가사 없음) |
| `data/sources.json` | 출처 레지스트리 |
| `data/links/gojoseon.json` | 6-68 고조선 id → 마스터 id |

테스트: `node --test game_lab/history/test/history.test.js`, `py -m unittest tests.test_6_69_history`

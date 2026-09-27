# CHOICE100 RPG — 선택100: 대한민국

- **고조선 — 첫 번째 땅** (6-68, 탐험 + 부족 통합, 게임의 시작점): http://127.0.0.1:8790/rpg/gojoseon/ — `explore.js` + `explore-renderer.js` + `gojoseon/gojoseon.json`, 설계 `docs/6-68-gojoseon-exploration-tribe-vertical-slice.md`
- **주몽 이야기 1장** (6-67, 영웅별 미니게임 프로토타입): http://127.0.0.1:8790/rpg/korea/

## 주몽 Vertical Slice (6-67)

영웅별 독립 이야기 + 메인 스토리 + 시간의 문 + 성장(EXP·레벨·지식·아이템·스킬·동료). 주몽 이야기 1장만 플레이 가능하다.
설계·결과: `docs/6-67-choice100-octopath-world-architecture.md`.

```
py -m http.server 8790 --bind 127.0.0.1 -d game_lab
# http://127.0.0.1:8790/rpg/korea/
```

| 파일 | 역할 |
|---|---|
| `engine.js` | RPG 규칙(DOM 없음). 스토리 = 단계 목록(narration/quiz/choice/reward/companion/relation/board/region/main/end) |
| `renderer.js` | 화면. 보드 단계는 `../board/engine.js`(6-66)로 한 턴을 돌린다 |
| `korea/korea.json` | 영웅·메인 스토리·지역·시간의 문·아이템·스킬·지식·정책·퀴즈·주몽 1장·졸본 보드 |
| `sim.js` | 자동 플레이(정답률 0/0.5/1 × 100). stdout만 |
| `test/rpg.test.js` | `node --test game_lab/rpg/test/rpg.test.js` |
| `explore.js` | (6-68) 탐험·부족 통합 층. 성장은 `engine.js`를 그대로 쓴다 |
| `explore-renderer.js` · `gojoseon/` | (6-68) 고조선 화면·데이터 |
| `explore-sim.js` · `test/explore.test.js` | (6-68) 자동 플레이 4전략(막힘·길이·엔딩 점검), 테스트 |

모든 항목에 `historical_status`(역사적 사실 / 역사 기록 / 신화 / 전승 / 게임 설정)가 있고 화면에 배지로 보인다. 퀴즈·지식은 한국민족문화대백과사전 출처와 확인일을 가진다.

# 6-67 CHOICE100 OCTOPATH WORLD ARCHITECTURE — 대한민국 통일 (Vertical Slice)

> 선택100 역사 RPG의 전체 구조를 정했다: **영웅별 독립 이야기 + 공통 세계(지역·시간의 문) + 메인 스토리로 수렴**.
> 실제로 도는 최소 수직 단면(Vertical Slice)을 만들었다: **메인 1 → 시간의 문 → 영웅 선택(4명, 주몽만 플레이) → 주몽 1장**.
> 주몽 1장 흐름: 퀴즈 → EXP·지식 → 주몽의 활 → 6-66 보드 사냥 한 턴 → 라이벌 송양왕 → 동료 합류·궁술 → 지역 관문 → 내정 선택(진대법 정책 해금) → 완료.
> 금융(6-64·6-65)과 세계사 보드(6-66)는 그대로 두고 보드 엔진은 재사용했다. 배포·광고·결제·로그인·서버는 없다.

## 1. Executive Summary

| 완료 기준 | 결과 |
|---|---|
| Main Story 구조 | ✅ 9단계(메인 1~5 → 대한민국 통일 → 중국·일본 → 유라시아 → 초원의 대결). 1·2는 플레이 가능, 나머지는 계획 |
| Hero Story 구조 | ✅ 영웅마다 story → chapters → steps(10가지 단계형). 순서 자유(시간의 문) |
| Hero Select | ✅ 4명(주몽 플레이 가능, 세종·이순신·장보고는 🔒 미리보기: 역할·스킬·상징 아이템·탁멍과의 관계) |
| 주몽 Vertical Slice | ✅ 16단계, 3~5분(정답 루트 약 45번 탭) |
| Quiz / EXP / Level / Knowledge | ✅ 정답: EXP + 지식 / 오답: 기본 EXP + 해설, 계속 진행. 레벨표 10단계, 레벨업 연출 |
| Item / Skill / Companion | ✅ 🏹 주몽의 활(군사 +3, 게임 상징) · 🎯 궁술(겨울 선택에서 보너스) · 주몽 합류(군사 +5, 관계 COMPANION) |
| Rival | ✅ 송양왕 RIVAL → 선택(활쏘기·설득)에 따라 ALLY |
| Region gate | ✅ 권장 레벨: 정답 루트 Lv 3 → 삼국 항쟁 열림, 오답 루트 Lv 2 → 🔒 |
| Time Gate | ✅ 시간의 서고 → 졸본(기원전 1세기). 한양 문은 Lv 5 필요(오류로 확인) |
| Board integration | ✅ 주몽 1장 안에서 6-66 보드 엔진으로 졸본 들판 한 턴(퀴즈 → 홀짝 특권 → 이동 → 사냥/탐험), 결과를 RPG 상태로 합침 |
| Knowledge → Policy | ✅ 인터페이스: 지식 `k_jindae` → 정책 `진대법` 해금(효과는 다음 장) |
| 테스트 | node RPG 14 + Python 9(신규), 시뮬레이션 300판 |
| Chrome | 정답 루트 · 오답 루트 · 잠긴 영웅 → 주몽 루트 모두 완주, 콘솔 오류 0, 390px 20개 화면 상태 가로 넘침 0 |

## 2. Game Vision

**대한민국 통일** — "100번의 선택으로 역사를 바꿔라". 플레이어 **탁멍**은 과거의 서고에서 시간의 문을 발견하고 시대를 건너 영웅들을 만난다.
영웅들의 이야기를 함께 겪으며 지식과 능력을 얻고 자신만의 나라를 키운다.
"역사를 바꾼다"는 것은 **게임 속 가상 시뮬레이션**이다. 화면과 데이터에서 역사 기록과 분명히 구분한다(21장).

## 3. Octopath-inspired structural principles

참고한 것은 **구조**뿐이다. 특정 게임의 코드·그래픽·UI·스토리·캐릭터·수치·맵은 쓰지 않았다.

| 원리 | 선택100 RPG에서 |
|---|---|
| 여러 주인공이 각자 독립된 이야기 | 영웅마다 `story → chapters → steps` |
| 원하는 이야기부터 고른다 | 영웅 선택 화면 + 시간의 문(역사 순서와 무관) |
| 공통 세계를 돌아다닌다 | 지역(stage별)·시간의 문 |
| 지역별 권장 레벨·위험도 | `recommended_level`·`difficulty`, 레벨 미달이면 🔒 |
| 이야기들이 결국 하나로 모인다 | 영웅 이야기 완료 → 동료·스킬·지식 → 메인 스토리 진행 |

## 4. Main Story

```
MAIN 1 과거로(✅) → MAIN 2 첫 영웅을 만나다(✅, 주몽 1장 완료 시) → MAIN 3 역사 세계의 균열 → MAIN 4 시간의 문 열쇠 → MAIN 5 모여드는 영웅들
→ 대한민국 통일(STAGE 1 목표) → 바다 건너, 대륙으로(STAGE 2) → 유라시아(STAGE 3) → 초원의 대결(대체역사 이벤트)
```

모든 메인 항목은 `historical_status: game_setting`이다. 영웅 이야기의 `main` 단계가 메인 항목을 완료 처리한다(주몽 1장 → MAIN 2).

## 5. Hero Story

```
MAIN STORY
     │
 ┌───┼────────┬──────────┐
 ↓   ↓        ↓          ↓
주몽 Story  세종 Story  이순신 Story  장보고 Story …   (각자 chapter 1, 2, 3 …)
 └───┬────────┴──────────┘
     ↓
동료 · 스킬 · 지식 · 아이템 · 관계
     ↓
MAIN STORY 다음 단계
```

- 스토리는 단계 목록이다. 단계 종류 10가지: `narration` · `quiz` · `choice` · `reward` · `companion` · `relation` · `board` · `region` · `main` · `end`.
  엔진은 단계 종류만 알고 내용은 데이터에서 온다. 새 영웅은 데이터만 추가하면 된다.
- 주몽 1장(16단계):

| # | 단계 | 내용 |
|---|---|---|
| 1 | narration | 전승 |
| 2 | narration | 게임 대화 |
| 3 | quiz | 이름의 뜻 |
| 4 | reward | 주몽의 활 |
| 5 | narration | 알 이야기 |
| 6 | quiz | 신화인가 사실인가 |
| 7 | board | 졸본 사냥 |
| 8 | narration | 비류국 |
| 9 | relation | 송양 RIVAL |
| 10 | choice | 활쏘기·설득·관망 |
| 11 | quiz | 건국 연도 |
| 12 | companion | 주몽 |
| 13 | region | 삼국 항쟁 관문 |
| 14 | choice | 첫 겨울 내정 |
| 15 | main | MAIN 2 |
| 16 | end | 완료 |

- 오답이어도 이야기는 끝까지 간다(기본 EXP, 해설). 다만 레벨이 낮아 다음 지역이 늦게 열린다.

## 6. Hero Select

- 카드마다: 아이콘, 이름, 시대, 한 줄 소개, 플레이 스타일 칩, PLAY 또는 🔒 이유.
  - 주몽: 전투·탐험·궁술
  - 세종: 지식·내정·기술 · Lv 5 · 준비 중
  - 이순신: 해전·방어·전략 · Lv 6 · 준비 중
  - 장보고: 교역·해상·외교 · Lv 4 · 준비 중
- 잠긴 카드를 누르면 미리보기가 열린다: 역할(한국어), 스킬, 상징 아이템, 탁멍과의 관계(세종 = 스승, 이순신 = 동맹, 장보고 = 친구).
  기대감을 만드는 장치이고, 이야기는 없다.
- 소개 문구에는 확인한 사실만 쓴다(세종 "조선의 제4대 왕(재위 1418~1450)" — 한국민족문화대백과사전). 나머지는 역할 문구다.

## 7. Hero relationship

- 관계 종류: `FRIEND · COMPANION · MENTOR · RIVAL · ALLY · NEUTRAL`(검증).
- 영웅 데이터: `relationships: [{with, type, when}]`.
- 게임 상태: `relations{대상: 관계}` — 선택·단계에 따라 바뀐다.
- 영웅끼리의 관계도 같은 구조로 둘 수 있다(`with`에 다른 영웅 id).

## 8. Companion / Rival

- **동료**: 1장의 `companion` 단계에서 주몽이 합류한다.
  - 관계 COMPANION, 영웅 능력치(군사 +5)·스킬(궁술)을 적용한다.
  - 상단 파티 아이콘에 표시된다.
  - 스킬은 이후 선택의 `skill_bonus`로 쓰인다(겨울 사냥: 식량 +20, "궁술 보너스").
- **라이벌**: NPC 송양왕(비류국, `historical_record`)이 RIVAL로 등장한다. 선택에 따라 달라진다.

| 선택 | 조건 | 결과 |
|---|---|---|
| 🎯 활쏘기 | 군사 3 이상 — 활을 받았으면 가능 | ALLY + 지식 |
| 🤝 설득 | 없음 | ALLY + 지식 |
| ⏳ 관망 | 없음 | RIVAL 유지 |

- 교훈: "『삼국사기』에는 기원전 36년 송양왕이 항복했다고 기록돼 있다. 겨루기·설득 장면은 게임 창작이다."

## 9. Knowledge

- 지식은 수집 점수가 아니라 **출처가 붙은 문장**이다(id·text·historical_status·source·source_date). 획득하면 화면에 출처와 함께 보인다.
- **KNOWLEDGE → POLICY** 인터페이스:
  - `policies[].requires_knowledge`
  - 지식 `k_jindae`(194년 고국천왕 때 진대법)를 얻으면 정책 **진대법**이 해금된다(`status: interface`).
  - 식량 위기 대응 효과는 다음 장에서 사용한다.
- 탕평책·훈민정음 연결은 해당 지식 항목이 생길 때 붙인다. 근거 없는 자리표시 정책은 넣지 않았다.

## 10. EXP / Level

- 레벨표: `levels = [0, 100, 220, 400, 650, 1000, 1500, 2200, 3000, 4000]`(Lv 1~10).
- 여러 레벨을 한꺼번에 올려도 레벨업 이벤트가 레벨마다 나온다(테스트).
- 레벨이 여는 것:
  - 영웅 이야기(`unlock.level`)
  - 시간의 문(`requires_level`)
  - 지역(`recommended_level`)
  - 선택지(능력치 조건)
- 시뮬레이션 300판(정답률별 100판):

| 정답률 | 레벨 | 중앙 EXP | 삼국 항쟁 열림 |
|---|---|---|---|
| 0% | Lv 2 99%, Lv 3 1% | 170 | 0% |
| 50% | Lv 3 85% | 255 | 61% |
| 100% | Lv 3 100% | 310 | 100% |

  지식이 곧 진행 속도다. 동료·활은 모든 루프에서 얻는다(오답이어도 이야기는 끝난다).

## 11. Item

- 종류: `ARTIFACT · KNOWLEDGE · POLICY · SKILL`.
- 🏹 **주몽의 활**: ARTIFACT, 군사 +3, `game_setting`. 표시 문구: "게임 속 상징 아이템. 실제 유물이나 주몽의 실제 소유물이 아니다(이름의 뜻 ‘활을 잘 쏘는 사람’에서 착안)."
- 계획 항목(데이터에만 있음):
  - 📕 삼국사기(KNOWLEDGE, 역사 기록: 1145년경 김부식 등 편찬)
  - 📜 훈민정음
  - 🐢 거북선 모형(게임 제작물)
  - 🌾 진대법 두루마리

## 12. Skill

- 🎯 **궁술**(주몽): 탐험·사냥·겨루기에서 추가 효과. `game_setting` — 기록 속 "활을 잘 쏘는 사람"에서 착안했다.
  - 주몽 1장: 겨울 사냥 보너스
  - 보드 연동: 사냥에서 탐험하면 식량 +10(`boards.*.skill_bonus`, 테스트)
- 계획: 📚 집현(세종), ⚓ 해전 지휘(이순신), ⛵ 해상 교역(장보고).

## 13. Region

- 지역 필드: `id, name, era, stage, recommended_level, difficulty, hero_stories, events, cities, trade, exploration, quests, status, historical_status`.
- 13곳:

| 구역 | 지역 |
|---|---|
| 허브 | 시간의 서고 |
| STAGE 1 | 고조선 Lv 2 · **졸본 Lv 1(플레이)** · 삼국 항쟁 Lv 3 · 남해 바닷길 Lv 4 · 발해 Lv 4 · 고려 Lv 5 · 한양 Lv 5 · 남해 바다 Lv 6 · 근현대 Lv 8 |
| STAGE 2 | 중국·일본 Lv 10 |
| STAGE 3 | 유라시아 초원 Lv 15 |

- 지역 지도 화면: 🟢 열림 / ⚪ 레벨은 충분(아직 안 열림) / 🔒 레벨 부족, 권장 레벨·난이도 별·"준비 중".

## 14. Time Gate

- `time_gates[]`: `{id, name, to_region, era, requires_level, historical_status: game_setting}`.
- 시간의 문을 지나면 그 시대 지역이 열리고, 그 지역 영웅의 이야기를 시작할 수 있다(지역이 안 열렸으면 `startStory` 오류 — 테스트).
- **게임 진행 순서 ≠ 역사 연대순.** 주몽 → 세종 → 이순신 → 다시 주몽 순서가 가능하다. 화면 문구: "시간의 문은 게임 설정입니다. 역사 속 시대 순서와 상관없이 영웅의 이야기를 골라 들어갈 수 있습니다."

## 15. Board integration

- 스토리 단계 `board`가 6-66 보드 엔진(`game_lab/board/engine.js`)을 주입받아 **한 턴**을 돌린다(`boards.joljbon_hunt`, 8칸 졸본 들판: 사슴 사냥터·졸본 마을·산딸기 숲·비류수 물가·모닥불·원로의 질문·숲속 길).
  - 흐름: 보드 퀴즈(고구려 문제 3개 중) → 정답이면 🎲 홀짝 특권(3/6) → 이동(적중 시 도착 칸 선택) → 칸 선택/효과 → "사냥 마치기".
- 결과 합치기 규칙은 데이터 `merge[{from, to, rate}]`:

| 보드 값 | RPG로 |
|---|---|
| 군량 | 식량 ×1 |
| 지식 | 지식 ×1, EXP ×10 |
| 탐험 | 탐험 ×1, EXP ×30 |

  - 스킬 보너스(궁술)도 적용한다.
- 저장 중 보드 한 턴은 저장하지 않는다. 이어하기를 하면 보드 단계를 처음부터 다시 한다(테스트).

## 16. Korea stage

목표 **대한민국 통일**(게임 속 목표). 시대 지역: 고조선 → 삼국 → 통일신라 → 발해 → 고려 → 조선 → 근현대(데이터의 `stage: korea`).
각 지역에 해당 영웅 이야기를 붙인다(졸본 = 주몽, 한양 = 세종, 남해 바다 = 이순신, 남해 바닷길 = 장보고).

## 17. China / Japan stage

통일 이후 중국·일본(Lv 10~). 탐험·교역·외교·문화·역사·지리·전투를 모두 쓴다. **정벌은 여러 선택지 중 하나**일 뿐이다.
6-66 보드의 교역·탐험, 6-65 선택의 대가 구조를 그대로 쓴다.

## 18. Eurasia stage

중앙아시아·몽골·유럽(Lv 15~). 보드 여정과 교역로를 넓힌다.

## 19. Genghis Khan final event

`m_genghis` "초원의 대결": **역사적 사실이 아닌 대체역사 판타지 이벤트**(`game_setting`, 데이터 설명에 명시 — 테스트).
동료로 모은 영웅들의 스킬·지식·정책이 대결의 선택지가 되는 구조로 설계한다(미구현).

## 20. Vertical Slice (실제 Chrome 플레이테스트)

| 루트 | 결과 |
|---|---|
| 1. 주몽 정답 루트 | 퀴즈 ⭕3, Lv 3(EXP 380), 활·궁술·주몽 동료, 지식 5, 진대법 해금, 송양왕 동맹, 삼국 항쟁 🟢 |
| 2. 주몽 오답 루트 | 퀴즈 ❌3, Lv 2(EXP 190), 이야기 완료·동료 합류, 삼국 항쟁 🔒 "권장 Lv 3 · 지금 Lv 2" |
| 3. 영웅 선택 → 잠긴 영웅 → 주몽 | 세종·이순신·장보고 미리보기 3개 → 주몽 완주 |
| 실제 키·클릭 | 게임 시작 클릭 → → 로 메인 1·시간의 문 → 세종(🔒) 미리보기 → 주몽 → 2번 키로 정답 → EXP 바 60/100, 지식, 주몽의 활 카드 |

- 확인한 화면: 시작, 영웅 선택, 이야기, 퀴즈, 보상, 레벨업(⬆️ Lv 3), 아이템, 스킬, 동료, 관계, 지역, 메인, 장 완료, 지역 지도.
- 로컬 기록 이벤트(실측): `game_start` · `hero_select` · `quiz_answer` · `level_up` · `dice_parity_selected` · `dice_result` · `board_done` · `companion_join` · `chapter_complete` · `game_completion` · `game_restart`
  (+ 보상 단계 `item` — 누락을 발견해 고쳤다).
- 390px(iframe): 타이틀·메인 1·시간의 문·영웅 선택·미리보기·서사·퀴즈·결과·보드(굴림·특권·조정·칸)·보상·관계·선택·동료·지역·메인·장 완료·지도·긴 글 등 **20개 상태 가로 넘침 0**. 영웅 카드 167px 폭.
- 콘솔 오류 0. 회귀: 세계사 보드 1판, 금융 선택 10개 이상 390px에서 동작.

## 21. Historical accuracy model

`historical_status` 4값을 **모든** 영웅·아이템·스킬·지역·시간의 문·지식·정책·퀴즈·메인 항목·서사·선택지가 가진다(검증 + Python 테스트). 화면에 배지로 보인다.

| 값 | 배지 | 예 |
|---|---|---|
| `historical_fact` | 역사적 사실 | (이번 데이터에는 기록 기반 항목만 사용) |
| `historical_record` | 역사 기록 | 『삼국사기』 기록: 기원전 37년 졸본 건국, 기원전 36년 송양왕 항복, 이름의 뜻 · 194년 진대법 |
| `legend` | 전승·신화 | 알에서 태어났다는 이야기(동명왕 신화), 부여를 떠나 남하한 이야기 |
| `game_setting` | 게임 설정 | 시간의 문, 탁멍과 영웅의 만남·대화, 주몽의 활, 궁술 스킬, 겨루기·설득 장면, 통일·대결 목표 |

- 전승을 사실처럼 쓰지 않는다. 오히려 퀴즈 하나가 "알 이야기는 사실인가 신화인가?"를 묻는다(정답: 건국 신화).
- **출처(2026-09-27 확인, 한국민족문화대백과사전)**:

| 항목 | 확인한 내용 |
|---|---|
| E0016431 동명성왕 | 재위 기원전 37~19, 부여에서 활 잘 쏘는 사람을 주몽이라 함, 졸본 도읍·기원전 37년 건국, 기원전 36년 송양왕 항복, 알 설화 |
| E0016436 동명왕 신화 | — |
| E0042024 유화부인 | 알 이야기는 "전설에 의하면" |
| E0054628 진대법 | 194년 고국천왕, 3~7월 대여·10월 상환 |
| E0029857 세종 | 조선 제4대 왕, 재위 1418~1450 |

- 처음 시도한 영문 백과사전은 접근이 막혔다(403). 한국사 항목은 공신력 있는 국내 백과사전을 1순위로 했다.

## 22. Data schema (`game_lab/rpg/korea/korea.json`)

| 영역 | 필드 |
|---|---|
| 기본 | `id`, `version`, `title`, `subtitle`, `disclaimer`, `historical_status_labels`, `relation_types`, `item_types`, `levels`, `stats`(exp·military·admin·exploration·food·lore), `stat_labels`, `player{start, regions, relations}` |
| 세계 | `stages[]`, `main_story[]{id,title,desc,stage,status,historical_status}`, `regions[]`, `time_gates[]` |
| 영웅 | `heroes[]{id,name,era,region,role,tagline,playable,icon,story,chapters,stats,skills,items,relationships,knowledge,sources,style,unlock,locked_reason,historical_status}`, `npcs[]` |
| 성장 | `items[]{id,name,icon,type,effects,note,status,historical_status}`, `skills[]{id,name,hero,use,desc,historical_status}`, `knowledge[]{id,text,historical_status,source,source_date}`, `policies[]{id,name,requires_knowledge,effects,status}` |
| 퀴즈 | `quizzes[]` — 6-66 스키마 + `historical_status` |
| 이야기 | `stories[]{id,hero,title,chapters[{id,title,steps[]}]}` |
| 보드 | `boards{id:{title, data(6-66 보드 데이터), merge[], skill_bonus}}` |

## 23. Future expansion

1. 영웅 2호: 세종 1장(지식·내정 — 훈민정음 상징 아이템, 집현 스킬, 탁멍과 MENTOR), 시간의 문 · 한양(Lv 5).
2. 주몽 2~3장 + 정책 실제 사용(진대법으로 식량 위기 대응).
3. 메인 3~5: 여러 영웅 이야기 완료가 조건이 되는 수렴 장면.
4. 동료 스킬을 보드 칸 효과에 연결(궁술 → 사냥 칸, 해상 교역 → 교역 칸).
5. 지역마다 보드(6-66) + 선택(6-65) 조합, 이후 STAGE 2·3.

## 24. Risks

| 위험 | 대응 |
|---|---|
| 역사 왜곡 논란("역사를 바꾼다") | 모든 항목에 역사 상태 배지, 목표·대결은 게임 설정 명시, 퀴즈·지식은 출처 필수 |
| 전승을 사실처럼 가르침 | legend 배지 + "신화인가 사실인가" 퀴즈 |
| 민감한 시대(근현대·한일·중국) | 설계만. 해당 스테이지는 사람 검수 뒤 착수 |
| 범위 폭주(영웅 8명 × 여러 장) | 단계형 스토리 데이터로 영웅 추가 비용을 낮춤, 1명씩 |
| 실존 인물 묘사 | 대화는 게임 창작(game_setting) 표시, 인물 평가 문구 없음 |
| 특정 게임 모방 | 구조 원리만 사용(3장), 그래픽·문구·수치 없음 |

## 25. NOT IMPLEMENTED

- 세종·이순신·장보고 이야기, 주몽 2장 이후
- 정책 효과 실제 사용
- 전투 시스템
- STAGE 2·3 콘텐츠, 칭기즈 칸 이벤트
- 영웅 간 관계 이벤트
- 지역 지도 그래픽, 사운드, 캐릭터 그림
- PWA·배포·광고·결제·로그인·서버 분석
- 역사 교과 전문가 검수(사람)

## 26. Next step

1. **Director 플레이테스트**:
   - `py -m http.server 8790 --bind 127.0.0.1 -d game_lab` → http://127.0.0.1:8790/rpg/korea/
   - 정답·오답 각 1회
   - "영웅을 고르는 순간이 설레는가 / 동료 합류가 보상처럼 느껴지는가 / 역사 배지가 몰입을 방해하는가" 판정
2. 세종 1장 설계(출처 조사부터).
3. 주몽 2장: 진대법 정책 사용 + 보드 2턴.

## 데이터 보호·회귀

- Production(Archive·ShortsScript·YouTube·Threads·KNOWLEDGE·SCOUT)과 MONEY: 작업 전후 지문 **동일**.
- 금융(6-64·6-65)·보드(6-66): node·Python 테스트 통과, Chrome 390px 동작, 코드 변경 없음(보드 엔진은 읽기만 재사용).
- 게임 데이터·기록은 `game_lab/`와 브라우저 localStorage에만 있다.

# 6-58 TAK AUTO MONEY — 실제 수익 기회 운영판

작업 시간: 2026-09-27 12:41 ~ 13:02 KST(약 21분 — 요청은 장시간 자율 작업이었지만, 완료 조건·브라우저 재검증·발견한 문제 수정을 끝낸 뒤 기능을 억지로 늘리지 않았다). 외부 사이트 로그인·설문 응답·자동 제출·스크래핑 0, YouTube/Threads/Naver/LLM/OCR API 0, Production 데이터 변경 0.

## 1. 6-57 현재 상태 (시작 시 확인)

- `git status` 깨끗, `main`, HEAD = origin/main = `120b442`(6-57), `git diff` 없음.
- 문서(docs/6-57)와 코드(`content_engine/money.py`, `scripts/money_web.py`, dashboard 연결, `operator_summary` MONEY 행, CLI, `tests/test_6_57_money.py`)가 일치. 6-57 테스트 26개 OK. `.gitignore`의 `data/*.json` 규칙으로 MONEY 데이터는 git 제외.
- 공식 링크 4개 재확인(HTTP 200, 다른 사이트로 이동 없음): 패널나우 `https://www.panelnow.co.kr/`, 오베이 `https://ovey.io/`(6-57에서 확인한 값 유지), 헤이폴 `https://www.heypoll.co.kr/`, 네이버 애드포스트 `https://adpost.naver.com/`. 변경 없음.
- 6-57은 커밋 직후 브라우저에서 검증된 상태였고 그 뒤 코드 변경이 없어, 그대로 출발점으로 삼았다(복구 필요 없음).
- 전체 테스트 baseline: 6-57 최종 실행(같은 커밋 `120b442`) **1710 OK, skipped 11**. 이번 시작 때 다시 돌린 baseline은 실행 도중 내가 `money_web.py`를 고치기 시작해, 요청 때마다 화면 모듈을 읽는 6-57 HTTP 테스트 5개가 반쯤 바뀐 파일을 읽고 ERROR가 났다(오염된 실행 — 원인 확인 후 무시, 최종 실행은 16장).

## 2. 6-58 목표

"오늘 내가 뭘 하면 돈을 벌 수 있는가?"를 `/money` 첫 화면에서 바로 판단하게 한다.

```
OPPORTUNITY(기회 발견·등록) → PROFITABILITY(예상 시급·등급) → PRIORITY(추천 행동·정렬) → ACTION(할래요 → 직접 작업) → RECORD(완료 기록) → LEARN(플랫폼별 실제/예상, 확인 기록)
```

## 3. 설계

새 웹앱·프레임워크 없이 6-57 구조를 그대로 확장했다.

| 파일 | 변경 |
|---|---|
| `content_engine/money.py` | 플랫폼 metadata, 추천 행동, 관대한 파서 `parse_opportunity()`(+ `quick_parse` 강화), 기회 상태(`new`)와 `accept()`, 중복 기회 방지, 플랫폼 확인 기록(`record_check`, `money_checks.json`), `routine()`/`today_summary()`, 정렬 옵션(플랫폼·등급), 내 기록 반영 시급(`learned_hourly`), 플랫폼 메모, Operator 요약 확장 |
| `scripts/money_web.py` | 첫 화면 순서 재구성, 오늘의 루틴·확인 버튼, 등록 전 확인 화면, 캡처 텍스트 등록, 기회/작업 카드 분리, 추천 배지, 최근 수익 표, `/money/platforms` directory |
| `content_engine/operator_summary.py` | MONEY 행에 "새 기회 N건 · 오늘 미확인 플랫폼 N/4곳"(키가 있을 때만 붙임 — 6-57 문구 유지), 행동 문구 |
| `scripts/run_scout_dashboard.py`, `scripts/operator_control_center.py` | Operator 요약에 확인 기록 전달(한 줄씩) |
| `tests/test_6_58_money_opportunity.py` | **신규** 24 tests |
| `tests/test_6_57_money.py` | 요구가 바뀐 3곳 갱신(15장) |

## 4. Opportunity 구조 — 새 파일을 만들지 않은 이유

Opportunity에 필요한 필드(`id, platform, title, reward, minutes, url, status, source, notes, discovered_at, expires_at`)는 6-57 작업(`money_tasks.json`) 필드와 **같다**(`memo`=notes, `created_at`=discovered_at, `deadline`=expires_at, `hourly/grade`는 저장하지 않고 매번 계산). 별도 `money_opportunities.json`을 만들면 같은 데이터가 두 파일에 복사되고, 기회→작업 이동 때 두 파일을 함께 써야 해 중간에 끊기면 어긋난다. 그래서 **같은 목록에 `status`로 단계를 구분**했다.

| status | 뜻 | 화면 |
|---|---|---|
| `new` | 기회 — 발견만 함 | 💡 수익 기회 |
| `open` | 하기로 한 작업(6-57 작업과 같음) | 🔥 지금 할 만한 온라인 작업 |
| `done` | 완료(로그에 예상+실제) | 📒 기록 |
| `skipped` | 안 함(삭제 아님) | - |
| (expired) | 마감 지남 — **저장하지 않고 계산**(`deadline <= 지금`), 흐리게·맨 뒤 | 두 목록 끝 |

추가 필드: `accepted_at`(할래요 시각, 완료 때 자동 채움). 6-57 파일은 그대로 읽힌다(기존 작업은 `open`).
`hourly`/`grade`/`recommended`를 저장하지 않는 이유: 사용자가 기준을 바꾸면 모든 카드가 즉시 새 기준으로 다시 분류돼야 하기 때문(8장).

## 5. Task와 관계

```
기회(new) ──[할래요]──▶ 작업(open) ──[완료 기록]──▶ done + money_log(예상 사본 + 실제)
   │                                   ▲
   └──────────[완료 기록](바로)─────────┘     [안 함] ▶ skipped
```
- `accept()`: `new`만 → `open`(아니면 `NOT_AN_OPPORTUNITY`).
- `complete()`: `new`/`open` 모두 허용(기회를 보고 바로 해버린 경우 클릭 하나 줄임), 6-57의 중복 완료 방지·로그 먼저 쓰기 그대로.
- 중복 기회 방지: 같은 플랫폼 + 작업명(공백·대소문자 무시) + 보상 + 시간의 **열린(new/open)** 항목이 있으면 `DUPLICATE_OPPORTUNITY`. 닫힌 뒤에는 다시 등록 가능. 화면 등록은 항상 검사, 6-57 API 기본 동작(작업 직접 추가)은 호환을 위해 기회일 때만 검사.

## 6. 플랫폼 directory

설정(`DEFAULT_CONFIG.platforms`, `money_config.json`으로 덮어쓰기) 항목마다: `name, kind, url, aliases, point_value, description, active, notification_available`. 사람이 쓰는 메모는 `platform_notes`. `last_checked_at`은 저장하지 않고 확인 기록·등록 기록에서 계산한다.

| 플랫폼 | kind | 루틴 | 비고 |
|---|---|---|---|
| 패널나우 | survey(설문) | ✓ | |
| 오베이 | survey | ✓ | `https://ovey.io/` |
| 헤이폴 | survey | ✓ | |
| 네이버 애드포스트 | content(콘텐츠 수익) | ✓ | 6-57의 `asset`에서 `content`로(요청 4장 표기). 장기 자산 분류는 `asset` kind로 계속 가능 |
| 기타 | other | 제외 | 공식 링크 없음 |

`notification_available`은 확인하지 않은 사실을 적지 않으려고 `None`("알림 여부 미확인")으로 두었다.
`/money/platforms`: 종류, 설명, 공식 사이트, 오늘 확인 여부, 누적 수익, 실제 시급, 예상 대비, 최근 확인, **확인 횟수 / 작업 없음 횟수 / 발견(등록) / 완료**, 메모 저장. 가짜 수익·가짜 작업은 만들지 않는다(빈 상태면 0원/-).
장기 수익 플랫폼(YouTube, Threads, 쿠팡파트너스, 전자책, 블로그, 디지털상품)은 코드 변경 없이 설정 목록에 `kind: asset/affiliate/digital_product`로 추가하면 directory·통계에 나타난다(이번에는 추가하지 않음).

## 7. 오늘의 MONEY ROUTINE

첫 화면 순서(요청 2장): ① 오늘의 수익 → 🎯 첫 10,000원까지 → 🔥 오늘의 MONEY ROUTINE(오늘 할 일) → ④ 지금 확인할 플랫폼 → ⚡ 빠른 등록 → 💡 수익 기회 → 🔥 할 작업 → 📒 최근 수익 기록 → (접힘) 기간별 통계·자세히 등록·작업 없는 수익.

- 오늘 할 일: `오늘 확인할 곳 (2/4): ■ 패널나우 ■ 오베이 □ 헤이폴 □ 네이버 애드포스트` / 오늘 발견한 기회 / 오늘 완료한 작업 / 오늘 수익 + "하루 사용법" 7단계(요청 18장).
- 플랫폼 카드: `○ 오늘 미확인` → `[확인하기 ↗]`(공식 사이트, 새 탭) · `[작업 없었음]` · `[작업 있음 → 등록]`. 확인 후 `● 오늘 확인함 · 작업 없음/있음` + `[다시 확인 ↗]`.
- `[확인하기]`는 링크일 뿐 아무것도 기록하지 않는다(사람이 실제로 봤는지 알 수 없으므로) — 확인 결과는 사람이 버튼으로 남긴다. 그 플랫폼 기회를 오늘 등록하면 자동으로 "확인함 · 작업 있음"으로 센다.
- "작업 있음 → 등록"은 빠른 등록 칸에 플랫폼 이름을 채우고 그 칸으로 이동한다. 확인 버튼 뒤에는 루틴 영역으로 돌아온다.
- 확인 기록(`money_checks.json`: `id, platform, outcome(none|found), checked_at`)은 수익과 **별개**다 — "확인했지만 작업 없음"도 남아 플랫폼별 확인 대비 발견·완료·수익 분석의 기반이 된다.
- 날짜 경계는 KST(설정 `utc_offset_hours`) 자정.

## 8. 빠른 등록 · 캡처 텍스트

`parse_opportunity(text, config)`는 **예외 없이 초안**을 돌려준다: `platform, title, reward, minutes, estimated_hourly, grade, recommended, source_text, missing[]`. `quick_parse()`는 이를 감싸 모자란 값이 있으면 `QUICK_PARSE_FAILED`(6-57 계약 유지).

| 입력 | 결과 |
|---|---|
| `패널나우 20분 850P 일반인 의견 조사` | 패널나우 · 일반인 의견 조사 · 850 · 20분 · 2,550원 · 🟡 시간 여유 있을 때 |
| `오베이 15분 1200원 쇼핑 조사` | 오베이 · 쇼핑 조사 · 1,200 · 15분 · 4,800원 · 🟢 지금 확인 |
| `헤이폴 10분 450P 설문` | 헤이폴 · 설문 · 450 · 10분 · 2,700원 · 🟡 |
| `패널나우⏎일반인 의견 조사⏎약 20분⏎850P` (캡처 텍스트) | 패널나우 · 일반인 의견 조사 · 850 · 20분 |
| `[오베이] 소비자 설문 · 소요시간 15~20분 · 보상 1,500원` | 오베이 · 소비자 설문 · 1,500 · **20분**(범위는 큰 값 — 시급을 낙관하지 않게) |
| `패널나우 850P` | 시간을 못 읽음 → 확인 화면에서 빨간 칸으로 채우게 함 |

시간: `20분 / 약 20분 / 20분 내외 / 15~20분 / 15-20분 / 1시간 / 1시간 30분 / 25min / 소요시간: 12분`. 보상: `850P / 850 P / 850p / 850 포인트 / 1,200원 / 보상: 1,500 / 3000 points`. 작업명: 플랫폼·시간·보상·안내 말(약, 내외, 소요시간, 보상 …)을 뺀 나머지, 없으면 "플랫폼 작업". 길이 제한 120자.

흐름: `⚡ 빠른 등록`(한 줄) 또는 `/money/capture`(캡처에서 복사한 여러 줄) → **등록 전 확인 화면**(아직 저장 안 됨, 값 수정 가능, 예상 시급·추천 표시) → `[💡 기회로 저장]` 또는 `[🔥 바로 할 작업으로 등록]` / `[취소]`. 확인 화면에서 온 입력이 저장 오류(중복 등)면 값을 유지한 채 확인 화면으로 되돌아간다. 출처 구분 `source: quick | ocr | manual`.
OCR은 구현하지 않았다: 사람이 휴대폰 '텍스트 복사' 등으로 얻은 글자만 받는다. OCR을 붙일 자리는 `이미지 → 텍스트` 한 단계뿐이고 그 뒤는 지금 흐름 그대로다.

## 9. 수익성 판단

| 등급 | 기준(기본, 설정값) | 추천 행동 |
|---|---|---|
| 🟢 GREEN | ≥ 3,000원/시간 | 지금 확인 |
| 🟡 YELLOW | 2,000~2,999 | 시간 여유 있을 때 |
| 🟠 ORANGE | 1,000~1,999 | 다른 작업 없을 때 |
| 🔴 RED | < 1,000 | 보류 |

- 절대 평가가 아니라 사용자가 정한 기준에 따른 자동 분류(화면에 "초기 실험용 기준" 표기). 기준을 바꾸면 카드 등급·추천이 즉시 바뀐다(브라우저: 🟢 기준 4,000으로 올리자 3,500원 카드가 🟡 "시간 여유 있을 때"로).
- **예상 시급만 보지 않게**: 카드에 같은 플랫폼의 내 실제 기록을 붙인다 — `내 기록: 오베이 실제 3,600원/시간 (예상 대비 -25%, 1건) → 이 작업 약 2,625원`(= 예상 시급 × 실제/예상 비율). 로그의 `estimated_hourly / actual_hourly`, 완료 카드의 `(예상 대비 −25.0%)`, 플랫폼별 `hourly_gap_pct`가 그 재료다.
- 정렬: 예상 시급(기본) · 마감 임박 · 최근 등록 · 플랫폼 · 등급. 필터: 전체/🟢/🟡/🟠/🔴, 플랫폼. 마감 지난 항목은 항상 뒤.

## 10. 첫 10,000원 운영 흐름

`🎯 첫 10,000원까지 — 현재 / 남은 금액 / 진행률` 바로 아래에 오늘의 루틴(확인할 곳 □, 오늘 발견한 기회, 오늘 완료, 오늘 수익). 달성하면 🎉 + 다음 목표(6-57 그대로). 목표는 `/money/settings`.

## 11. 브라우저 검증 (Claude in Chrome, 실제 Chrome)

`http://127.0.0.1:8767`(MONEY 파일은 `artifacts/6-58-money-browser/` 샌드박스 — 실제 `data/`를 쓰지 않음).

| # | 확인 | 결과 |
|---|---|---|
| 1 | 오늘의 MONEY ROUTINE | 오늘 확인할 곳 (0/4) □×4, 발견 0 · 완료 0 · 수익 0원 → 확인 후 (2/4)·(3/4) ✓ |
| 2 | 플랫폼 목록 | 루틴 카드 4개 + `/money/platforms` directory 5개 ✓ |
| 3 | 공식 사이트 링크 | 4개 모두 설정 주소, 새 탭 `noopener noreferrer` ✓(테스트로도 고정) |
| 4 | 오늘 확인 버튼 | 패널나우 [작업 없었음] → `● 오늘 확인함 · 작업 없음` + [다시 확인 ↗] ✓ / 오베이 [작업 있음 → 등록] → 빠른 등록 칸에 "오베이 " 채움 ✓ |
| 5~6 | 빠른 등록 · 파싱 결과 | "오베이 15분 1200원 쇼핑 조사" → 확인 화면 🟢 오베이 · 지금 확인 · 쇼핑 조사 · 4,800원 ✓ |
| 7 | 작업 등록 | [💡 기회로 저장] → 수익 기회 1건 → [할래요] → 할 작업 1건 ✓ |
| 8~9 | 예상 시급 · 등급 | 4,800원 🟢, 기준 4,000으로 바꾸자 3,500원 카드 🟢→🟡 추천 변경 ✓ |
| 10~11 | 완료 기록 · 실제 수익 | 1,200원 / 20분 → 실제 3,600원/시간(예상 대비 −25.0%) ✓ |
| 12 | 첫 10,000원 진행률 | 현재 1,200원 / 남은 8,800원 / 12% ✓ |
| 13 | /money/log | 기간 KPI, 플랫폼별(오베이 1건 1,200원 3,600 vs 4,800 −25%) ✓ |
| 14 | Operator Center | `MONEY: IN_PROGRESS · 오늘 1,200원 · 이번 달 1,200원 · 열린 작업 0건 · 첫 목표(10,000원) 12% · 새 기회 1건 · 오늘 미확인 플랫폼 2/4곳` + "확인하세요" ✓ |
| 15 | 390px | `/money`, `/money/platforms`, `/money/log`, `/money/capture`를 390px iframe에서: 페이지 가로 스크롤 없음, 버튼 높이 ≥ 40px(`/money/log`의 넓은 표는 자기 영역 안에서만 스크롤) ✓ |
| + | 캡처 텍스트 | 3줄(`[오베이] 신규 설문 도착 / 소요시간 10~12분 / 보상 700P`) → 오베이 · 12분 · 700 · 3,500원, 카드에 "내 기록 … 이 작업 약 2,625원" ✓ |

검증 중 발견·수정: 확인 버튼 뒤 페이지가 맨 위로 튐 → 루틴 영역으로 복귀(`#routine`) · 루틴 제외 플랫폼(기타)에 "오늘 미확인"이 뜸 → "오늘 루틴 제외".
자동화 한계(기록): 일부 버튼은 요소 참조로 클릭하면 제출되지 않아 화면 좌표로 클릭했다(서버 로그·화면으로 결과 확인). 창 크기 변경은 이 환경에서 적용되지 않아 390px은 iframe으로 확인했다.

## 12. 테스트

`tests/test_6_58_money_opportunity.py` 24개(신규). 요청 21장 매핑:
1 파서 `test_1_2_3_spec_examples` · 2/3 같은 테스트(패널나우 20분 850P, 오베이 15분 1200원, 헤이폴 10분 450P) · 4 `test_4_time_strings`(9가지) · 5/6 `test_5_6_point_and_won_strings`(8가지) · 7 `test_7_title_extraction` · 8/9 `test_8_9_hourly_grade_and_recommendation_follow_settings`(경계 + 기준 변경 시 재분류) · 10 `test_10_register_opportunity` · 11 `test_11_opportunity_to_task_to_log`, `test_complete_directly_from_opportunity` · 12/13/14 `test_12_13_14_check_status_per_platform`(어제 확인은 오늘 미확인, 작업 없음 횟수, 확인 기록은 수익과 별개), `test_registering_counts_as_checked_today` · 15 `test_15_opportunity_expiry` · 16 `test_16_duplicate_opportunity_blocked`(공백 차이, 닫힌 뒤 재등록 허용) · 17 `test_17_bad_quick_input` · 18 `test_18_xss_and_bad_urls`(제목/메모 `<script>`/`<img onerror>` 이스케이프, `javascript:`/`data:`/따옴표/`//` 주소 거부, 잘못된 status 거부) · 그 밖: 정렬 5종, 내 기록 반영 시급, 플랫폼 metadata·메모, 잘못된 확인 요청, Operator 미확인 수, 첫 화면 순서, 확인 화면(저장 안 됨) → 기회 → 할래요 → 완료 → 목표 갱신, 캡처 흐름, directory 화면, 빈 시작에서 파일을 만들지 않음.
19 기존 MONEY 테스트: 6-57 26개 전부 통과. **바꾼 3곳**(요구 변경, 약화 아님): 목표 카드 제목(`🎯 첫 10,000원까지` + 부제 `첫 온라인 수익 목표` 둘 다 확인), 빠른 등록이 바로 저장되지 않고 확인 화면을 거침(저장 안 됐음을 추가로 확인한 뒤 확인 화면 제출), 모자란 입력은 400 오류 대신 빨간 칸 확인 화면(아무것도 저장 안 됨 확인 + 빈 입력은 여전히 400).
20 전체 회귀(`TAK_TEST_FFMPEG` 설정): **1734 tests OK, skipped 11** (1710 + 신규 24, FAIL 0, ERROR 0, 새 오류 0).

## 13. 보안

- 외부 서비스 로그인·인증 기능 없음. 입력칸 이름에 password/token/cookie/otp/인증/phone/email/birth/주민 없음(6-57 테스트 유지). 메모 칸에 "비밀번호/개인정보는 적지 마세요".
- 링크: 설정의 공식 주소 또는 사용자가 넣은 `http/https`만. 모든 출력 HTML 이스케이프(테스트). 확인 기록의 플랫폼 이름은 설정 목록만 허용.
- `money.py`/`money_web.py`에 네트워크 모듈 없음. secret scan(`sk-`, `AIza`, `ya29.`, `1//`, `ghp_`, private key, `api_key|client_secret|refresh_token|access_token|password = "…"`): 변경 코드·테스트·문서·브라우저 샌드박스 데이터 **0건**, 환경변수의 실제 토큰/키 값 3개 대조 **0건**(값 출력 없음).

## 14. Production 보호

| 항목 | 시작(12:42) | 종료 |
|---|---|---|
| `data/*.json` 12개 + `data/shorts_scripts` 2개 + 6-48 staging 5개 sha256 | 기록 | **동일** |
| Production archive 18건 (content_id, generation_id, review_status, superseded_by) | 기록 | **동일** |
| `data/money_*.json` | 없음 | 없음(테스트는 임시 폴더, 브라우저는 `artifacts/6-58-money-browser/`, 둘 다 git 제외) |

Production Archive · Shorts Scripts · YouTube/Threads publish 데이터 변경 없음. 외부 API 호출 없음(공식 링크 HTTP 상태 확인은 공개 첫 페이지 조회만).

## 15. 실제 구현하지 않은 것

외부 사이트의 설문 목록 가져오기(스크래핑·API) — 로그인/개인정보/세션/CAPTCHA/약관/페이지 변경 문제, 자동 로그인·설문 응답·제출, OCR(이미지 → 글자), 알림(푸시/문자), 장기 수익 플랫폼 실제 연동(YouTube/Threads/쿠팡파트너스 등), 플랫폼 추가(요청대로 4개 유지), 새 파일 `money_opportunities.json`(4장 이유).

## 16. 향후 6-59 후보 ("첫 10,000원을 더 빨리"를 기준으로)

1. **확인 대비 성과 보기**: 플랫폼별 "확인 N회 → 작업 발견 N → 완료 N → 수익 N원", 요일·시간대별 발견률 → 어느 플랫폼을 언제 먼저 볼지 순서 추천(루틴 카드 순서 자동 정렬).
2. **내 기록 반영 등급**: 기록이 3건 이상 쌓인 플랫폼은 `learned_hourly`로 등급/추천을 매기기(지금은 참고 문구).
3. 캡처 이미지 → 텍스트(OCR은 로컬 또는 사람이 복사) → 지금의 확인 화면.
4. 마감 임박 기회 강조(30분 이내), 오래된 기회 정리(n일 지나면 접기).
5. 목표 달성 예상일(최근 7일 평균 수익 기준).

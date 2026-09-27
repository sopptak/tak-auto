# 6-57 TAK AUTO MONEY — 온라인 수익 노가다 관제판 (1차)

작업 시간: 2026-09-27 12:14 ~ 12:34 KST(약 20분). 요청은 5~6시간이었다. 체크리스트·브라우저 검증·발견한 UX 문제 수정·재검증을 끝낸 뒤 시간을 채우려고 기능을 늘리지 않았다. 외부 사이트 로그인/응답/제출 0, YouTube/Threads/Naver/LLM API 0, Production Archive·Shorts 데이터 변경 0.

## 1. 목적

```
DISCOVER(작업 발견·등록) → FILTER(예상 시급 등급) → DO(사람이 공식 사이트에서 직접) → RECORD(실제 보상·시간) → LEARN(기간/플랫폼 통계)
```
TAK AUTO는 **수익성 계산 + 작업 관리 + 공식 링크 + 결과 기록**만 한다. 설문·로그인·본인인증은 사람이 각 사이트에서 직접 한다.

## 2. 설계 (기존 구조 조사 결과)

- 조사: `git status`(깨끗, main, HEAD = origin/main = `03a3cf4`), `scripts/run_scout_dashboard.py`(표준 라이브러리 `http.server` + 서버 HTML, `_page` 공통 CSS), `scripts/operator_control_center.py` + `content_engine/operator_summary.py`(파일을 읽지 않는 순수 요약, `StatusWhyAction` 한 줄 구조), 6-55/6-56 Studio 방식(화면은 `scripts/*_web.py`, 계산은 `content_engine/*.py`, 대시보드는 연결만), `data/*.json`(목록 JSON, `.gitignore`가 `data/*.json`을 기본 제외), 테스트(`unittest`, 임시 폴더 + 실제 HTTP 서버).
- 그 구조를 그대로 따랐다 — 새 웹앱/프레임워크 없음.

| 파일 | 역할 |
|---|---|
| `content_engine/money.py` | **신규** — 설정, 계산(시급·등급·파싱), 저장소(작업/완료/수익/건너뛰기), 통계(기간·목표·플랫폼·Operator 요약). 네트워크 없음 |
| `scripts/money_web.py` | **신규** — `/money`, `/money/log`, `/money/settings`, 작업 등록·빠른 등록·완료 기록·안 함·수익 기록 |
| `scripts/run_scout_dashboard.py` | `DashboardConfig`에 경로 3개, `/money` 요청 전달(POST 100KB 제한), 홈 nav에 💰 MONEY, Operator 화면에 MONEY 행 |
| `content_engine/operator_summary.py` | `OperatorInputs.money`(선택) + `build_money_row()` + `OperatorSummary.money` — 기존 행/SYSTEM 판정 불변 |
| `scripts/operator_control_center.py` | CLI에 `--- MONEY ---` 한 줄 |
| `tests/test_6_57_money.py` | **신규** 26 tests |

## 3. 데이터 구조

모두 **파일이 없어도 동작**(최초 실행 = 빈 상태). 화면을 열기만 해서는 파일을 만들지 않는다. `data/*.json` 규칙상 git에 올라가지 않는 로컬 운영 데이터다(개인 수익 기록).

`data/money_tasks.json` — 작업 후보(목록). **예상값은 등록 후 바꾸지 않는다.**
```json
{"schema": "money_task/1", "id": "task-3f9c0a1b2c3d", "platform": "패널나우", "title": "일반인 의견 조사",
 "reward": 850, "minutes": 20, "point_value": 1, "url": "https://www.panelnow.co.kr/", "memo": "",
 "deadline": "2026-09-28T18:00+09:00", "status": "open|done|skipped", "source": "manual|quick",
 "created_at": "2026-09-27T03:20:00+00:00", "closed_at": null}
```
`data/money_log.json` — 완료/수익 기록(추가만). **예상값 사본과 실제값을 따로 보존.**
```json
{"schema": "money_log/1", "id": "log-…", "kind": "task|income", "task_id": "task-…", "platform": "패널나우", "title": "…",
 "estimated_reward": 850, "estimated_minutes": 20, "estimated_hourly": 2550,
 "actual_reward": 800, "actual_minutes": 24, "actual_hourly": 2000,
 "point_value": 1, "memo": "", "completed_at": "2026-09-27T03:21:00+00:00"}
```
`data/money_config.json`(선택) — 없으면 기본값. 키 단위로 덮어쓴다.
```json
{"goals": [10000, 100000, 1000000], "thresholds": {"green": 3000, "yellow": 2000, "orange": 1000},
 "utc_offset_hours": 9, "platforms": [{"name": "패널나우", "url": "…", "aliases": ["panelnow"], "point_value": 1, "kind": "survey"}, …]}
```
- 시간은 UTC로 저장, 화면·기간 계산은 `utc_offset_hours`(기본 9 = KST). Windows에 `tzdata`가 없어 `zoneinfo("Asia/Seoul")`를 쓸 수 없어서 고정 오프셋(KST는 서머타임 없음).
- `point_value`: 포인트 1 = 몇 원. 확인되지 않은 환산율은 추측하지 않고 1로 두었다 — 사람이 설정에서 바꾼다. 기록에 당시 환산율을 같이 남겨 나중에 바꿔도 과거 금액이 변하지 않는다.
- `kind: "income"`: 작업 카드 없이 들어온 수익(애드포스트 정산 등 장기 수익자산) — `task_id: null`.
- 쓰기는 임시 파일 → 교체(원자적), 같은 서버 안 동시 요청은 잠금으로 직렬화. 완료 시 **로그를 먼저** 쓰고 작업 상태를 바꾼다(중간에 끊겨도 로그 기준으로 중복이 막힌다 — 테스트).
- 파일이 깨졌으면 `DATA_UNREADABLE`로 알리고 **덮어쓰지 않는다**(테스트).

## 4. 화면

| URL | 내용 |
|---|---|
| `/money` | 💰 TAK AUTO MONEY · 온라인 수익 노가다 관제판 / 🎯 첫 목표 카드 / KPI 12칸(오늘·이번 주·이번 달·누적 × 수익·투자시간·실제 시간당 수익) / ⚡ 빠른 등록 / 🔥 지금 할 만한 온라인 작업(정렬: 예상 시급·마감·최근, 필터: 등급·플랫폼) / ✍️ 자세히 등록 / 💵 작업 없이 들어온 수익 / 공식 사이트 링크 |
| `/money/task/<id>/complete` | 예상값 표시 + 실제 보상·실제 시간·메모 입력 |
| `/money/log` | 기간 KPI / 📊 플랫폼별(건수, 누적 수익, 투자, 실제 시급+등급, 예상 시급, **예상 대비 %**) / 최근 완료(예상 vs 실제, 실제 시급, 완료 시각) |
| `/money/settings` | 목표 금액(여러 개), 등급 기준 3개 |
| `/operator` | MONEY 행: `오늘 N원 · 이번 달 N원 · 열린 작업 N건 · 첫 목표(10,000원) N%` → 상세보기 `/money` |

작업 카드: `🟢 패널나우 / 작업명 / 예상시간 20분 / 예상보상 850원 / 예상 시급 2,550원 / ⏰ 마감(남은 시간) / 📝 메모 / [바로가기 ↗] [완료 기록] [안 함]`. 등급 색 띠, 마감 지난 작업은 흐리게·맨 뒤. "안 함"은 삭제가 아니라 `skipped`(분석에 남음).
모바일: KPI 2열, 카드 1열(390px 폭에서 가로 스크롤 없음 — 브라우저 확인).

## 5. 수익성 계산

- 예상 시급 = `reward × point_value × 60 ÷ minutes`(원 반올림). 850 × 60 ÷ 20 = **2,550원/시간**.
- 실제 시급 = 실제 보상 기준 같은 식.
- 등급(설정값, 초기 실험용 — 절대 평가 아님): 🟢 ≥ 3,000 · 🟡 2,000~2,999 · 🟠 1,000~1,999 · 🔴 < 1,000. `/money/settings`나 `money_config.json`에서 바꾼다(코드 하드코딩 없음).
- 기간 시급은 **시간을 들인 기록만**으로 계산한다 — 시간 없이 들어온 정산 수익은 수익 합계에는 들어가고 시급은 부풀리지 않는다(테스트).
- 이번 주 = 월요일 00:00(KST)부터.
- 빠른 등록 파서 `quick_parse()`: "패널나우 20분 850P 일반인 의견 조사" → 플랫폼(이름/별칭: panelnow, heypoll, ovey, 애드포스트 …) + 시간(`20분`, `1시간 30분`, `90min`) + 보상(`850P`, `1,200원`, `3,000 포인트`) + 나머지 = 작업명. 캡처 기반 등록의 입력 함수로 그대로 쓸 수 있다(13장).

## 6. 목표 시스템

`goals`(기본 10,000 / 100,000 / 1,000,000) 중 가장 작은 값이 첫 목표. 화면: `🎯 첫 온라인 수익 목표 10,000원 / 현재 / 남은 금액 / 진행률 %` + 막대. 달성하면 `🎉 첫 10,000원 달성 — 누적 N원` + 다음 목표 진행률, 모두 달성하면 "설정한 모든 목표 달성". 목표는 `/money/settings`에서 바로 바꾼다(브라우저 확인).

## 7. 실제 완료 기록

카드 [완료 기록] → 실제 보상·실제 시간·메모. 저장하면 로그에 `estimated_*`(작업의 예상값 사본)과 `actual_*`를 따로 남기고 작업은 `done`. 작업 파일의 예상값은 그대로다. 같은 작업은 **한 번만**(`ALREADY_COMPLETED`, HTTP 409 — 브라우저 뒤로 가기 후 재제출도 막힘 확인). 없는 작업은 `TASK_NOT_FOUND`(404).

## 8. 안전 경계

- 없는 기능(의도적): 외부 사이트 로그인·설문 응답·본인인증·CAPTCHA·자동 제출·스크래핑. `money.py`에 `requests/urllib.request/http.client/socket/selenium/playwright` 없음(테스트).
- 저장하지 않는 것: 비밀번호·인증번호·세션 쿠키·토큰·개인정보. 입력칸 이름에 password/token/cookie/otp/인증/phone/email/birth/주민 없음(테스트). 메모 칸에 "비밀번호/개인정보는 적지 마세요" 안내.
- 링크: `http/https`만(`javascript:`, `data:`, 따옴표/꺾쇠 포함 주소 거부 — XSS 방지, 테스트), 새 탭 `rel="noopener noreferrer"`. 모든 출력은 HTML 이스케이프.
- 공식 링크 확인(2026-09-27, 공개 페이지 HTTP 상태·제목만 확인): 패널나우 `https://www.panelnow.co.kr/`(200, "패널나우"), 헤이폴 `https://www.heypoll.co.kr/`(200, "헤이폴"), 네이버 애드포스트 `https://adpost.naver.com/`(200, "네이버 애드포스트"). **오베이는 요청서 예시 `https://ovey.kr/`가 브랜드 표시 없는 빈 앱 껍데기("sofront")를 돌려줘 확인할 수 없었고, `ovey.co.kr`이 `https://ovey.io/`("오베이 · 내 의견의 가치")로 이동해 `https://ovey.io/`를 썼다.**
- Operator Center의 SYSTEM 판정·다음 행동에는 MONEY를 넣지 않았다(콘텐츠 파이프라인과 별개).

## 9. 테스트 결과

| 항목 | 결과 |
|---|---|
| baseline(시작, 03a3cf4, `TAK_TEST_FFMPEG` 설정) | 1684 OK, skipped 11 |
| 최종 전체(`TAK_TEST_FFMPEG` 설정) | **1710 tests OK, skipped 11** (1684 + 신규 26, FAIL 0, ERROR 0, 새 오류 0) |
| 신규 | `tests/test_6_57_money.py` 26개(삭제/약화한 기존 테스트 없음) |
| 기존 환경 오류 | 이번 실행들에서 없음 |

요청 17장 매핑: 1 `test_01_hourly_850_20` · 2~5 `test_02_05_grades`(경계값 2999/1999/999 포함) · 6 `test_06_register_task` · 7/8/9/15 `test_07_08_09_15_complete_keeps_estimate_and_actual_separately` · 10~13 `test_10_13_periods`(KST 자정 경계, 주·월 경계) · 14 `test_14_first_goal` · 16 `test_16_invalid_input`(13가지) · 17/18 `test_17_18_first_run_without_files` · 19 `test_19_complete_unknown_task` · 20 `test_20_duplicate_completion_blocked`, `test_duplicate_blocked_even_if_task_file_was_not_updated`.
추가: 설정값 기준/목표 변경, 빠른 등록 파서, 깨진 파일 보존, 마감·정렬·안 함, 시간 없는 수익과 시급, 플랫폼별·예상 대비, Operator 행/HTTP 표시, HTTP 전체 흐름(빠른 등록→카드→완료→기록→중복 409→목표 갱신), 입력 오류 시 값 유지, 목표 달성 배너·설정 저장, 인증정보 입력칸·자동화 import 없음.

## 10. 브라우저 검증 결과

Claude in Chrome(실제 Chrome)으로 `http://127.0.0.1:8766`(MONEY 파일은 `artifacts/6-57-money-browser/` 샌드박스, 실제 `data/`는 사용하지 않음).

| # | 확인 | 결과 |
|---|---|---|
| 1 | 첫 화면(빈 데이터) | 목표 10,000원 / 현재 0원 / 남은 10,000원 / 0%, KPI 12칸 0원·0분·- ✓ |
| 2 | 작업 등록 | 빠른 등록 "패널나우 20분 850P 일반인 의견 조사" ✓ / 자세히 등록(오베이, 1,200원, 15분, 마감, 메모) ✓ |
| 3 | 등록된 작업 표시 | 카드 2개, 예상 시급 높은 순(오베이 4,800 → 패널나우 2,550) ✓ |
| 4 | 예상 시급·등급 | 🟢 4,800원 / 🟡 2,550원 ✓, 마감 "남은 29시간 38분" ✓ |
| 5 | 공식 링크 | `https://ovey.io/`, `https://www.panelnow.co.kr/`, `target=_blank rel=noopener noreferrer` ✓ |
| 6~7 | 완료 기록·실제 수익 | 800원 / 24분 입력 → 저장 ✓ |
| 8 | 수익 합계 | 오늘·주·월·누적 800원, 24분, 2,000원/시간 ✓ |
| 9 | 목표 진행률 | 현재 800원 / 남은 9,200원 / 8% ✓ |
| 10 | /money/log | 예상 850원/20분(2,550) vs 실제 800원/24분, 실제 시급 2,000, 플랫폼별 패널나우 -21.6% ✓ |
| 11 | Operator Center | `MONEY: IN_PROGRESS (1건)` · 오늘 800원 · 이번 달 800원 · 열린 작업 1건 · 첫 목표(10,000원) 8% ✓ |
| + | 중복 완료 | 브라우저 뒤로 가기 후 재제출 → "이미 완료 기록이 있는 작업입니다(중복 기록 방지)" ✓ |
| + | 작업 없는 수익 | 애드포스트 1,500원(시간 없음) → 누적 2,300원, 시급은 2,000 유지 ✓ |
| + | 설정 | 목표 2,000으로 변경 → "🎉 첫 2,000원 달성 — 누적 2,300원 · 다음 목표 100,000원 2.3%" ✓ |
| + | 모바일 | 390px iframe: 가로 스크롤 없음(371 ≤ 386px), KPI 2열, 카드 전체 폭 ✓ (창 크기 변경 도구는 이 환경에서 적용되지 않아 iframe으로 확인) |

검증 중 발견·수정: 빈 목록 안내 카드가 한 칸 폭으로 좁음 → 전체 폭 / 빠른 등록을 작업 목록 **위로** 이동(찾기 → 바로 등록) / 중복 완료 메시지가 두 번 표시 → 한 번 / 대시보드 홈 nav에 💰 MONEY 추가.
자동화 한계(기록): 접힌 영역 안의 입력칸은 참조로 클릭했을 때 입력이 들어가지 않아 화면 좌표 클릭으로 입력했다(서버 로그로 요청 도달 확인).

## 11. 실행 방법

```
py scripts/run_scout_dashboard.py            # http://127.0.0.1:8000/money  (홈 nav의 💰 MONEY)
py scripts/operator_control_center.py        # CLI에서 MONEY 한 줄 확인
```
처음에는 `data/money_*.json`이 없어도 된다(첫 등록 때 생긴다). 목표/기준은 화면의 ⚙️ 목표·기준에서 바꾼다.

## 12. 향후 확장 계획

| 요청 | 지금 | 다음 |
|---|---|---|
| A 마감시간 | 저장·남은 시간·정렬 ✓ | 알림 |
| B 만료 | 마감 지나면 흐리게·맨 뒤(자동 변경 없음) ✓ | 일정 기간 지난 작업 자동 `expired` 보관 |
| C 플랫폼별 누적 | ✓ | 월별 추이 |
| D/E 실제 시급·예상 대비 | ✓ (`hourly_gap_pct`) | 플랫폼별 "예상보다 N% 짧게/길게 걸림" 보정 → 등록 때 보정된 예상 시급 제안 |
| F/G/H 목표 | 10,000 → 100,000 → 1,000,000 ✓ | 기간 목표(이번 달 N원) |
| I 장기 수익자산 | `kind: "income"`, 플랫폼 `kind: "asset"`(애드포스트) ✓ | 블로그/쿠팡파트너스/전자책/YouTube/Threads를 플랫폼으로 추가(설정만), TAK AUTO 콘텐츠(content_id)와 수익을 잇는 `content_id` 필드 |
| 13 캡처 등록 | `quick_parse()` + 빠른 등록 ✓ | 캡처 이미지 → 텍스트(OCR/사람 확인) → `quick_parse()` → 확인 후 등록. 자동 제출 없음 |
| 개인화 분석 | 기록 스키마에 예상/실제/환산율/시각 보존 ✓ | 요일·시간대별 실제 시급, 플랫폼 추천 순위 |

## 13. 보안 · Production 확인

- secret scan(`sk-`, `AIza`, `ya29.`, `1//`, `ghp_`, private key, `api_key|client_secret|refresh_token|access_token|password = "…"`): 변경 코드·테스트·문서·브라우저 샌드박스 데이터 **0건**. 환경변수의 실제 토큰/키 값 3개 대조 **0건**(값 출력 없음).
- Production: `data/*.json` 12개 + `data/shorts_scripts` 2개 + 6-48 staging 5개 sha256, archive 18건의 review_status/superseded_by — 시작·종료 **동일**. `data/money_*.json`은 만들지 않았다(테스트는 임시 폴더, 브라우저는 `artifacts/6-57-money-browser/`, 둘 다 git 제외).

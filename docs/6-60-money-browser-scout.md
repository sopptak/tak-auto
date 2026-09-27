# 6-60 TAK AUTO MONEY — Browser Scout

작업 시간: 2026-09-27 14:10 ~ 14:35 KST(약 25분 — 요청은 5~6시간이었지만 실제 사이트 확인·구현·테스트·Chrome 검증·문서를 끝낸 뒤 기능을 늘리지 않았다).
결론: **PARTIAL** — 파이프라인(검사·정규화·중복 병합·staging·승격·우선순위·화면·CLI)은 완성했고 실제 PanelNow 화면으로 끝까지 검증했다. 하지만 4개 중 **자동으로 읽을 수 있는 곳은 PanelNow 하나**다(오베이: 웹 목록 없음, 헤이폴: 이용약관상 자동 접근 금지, 애드포스트: 브라우저 도구가 사이트 열기 거부). 그리고 대시보드 버튼이 브라우저를 스스로 움직이지는 않는다(18장).

## 1. 목표

사람이 4개 플랫폼을 돌아다니며 캡처·입력하던 일을 줄인다: 브라우저가 **읽기만** 해서 기회를 모으고 → 정규화 → 중복 제거 → 시급 → 과거 기록과 비교 → 우선순위 → MONEY 기회로. 사람은 한다 / 나중에 / 안 한다만 판단하고 실제 참여는 직접 한다.

## 2. 기존 6-59 상태

`git status` 깨끗, `main`, HEAD = origin/main = `b62ca91`. 실제 `data/money_*.json` 없음(아직 실제 기록 전). 깨끗한 baseline(편집 전 끝까지 실행): **1752 tests OK, skipped 11**. 재사용한 것: `money_tasks.json`의 기회(`status=new`) → 할래요(`open`) → 완료 로그 흐름, `money.hourly/grade/recommend/open_tasks`, 6-59 `calibration`(표본 충분할 때만 보정), `performance`, `MoneyStore.accept/skip/complete`, 원자적 쓰기·잠금.

## 3. 변경 파일

| 파일 | 내용 |
|---|---|
| `content_engine/money_scout.py` | **신규** 파이프라인: 플랫폼 정책/`plan()`, `validate_raw`, 개인정보 `scrub`, `normalize_item`, `fingerprint`/`canonical_url`, staging(`load_staging`, `request_scout`), `ingest`(실패 격리), `promote`(병합·사라짐), `buckets`(우선순위), `record_choice` |
| `content_engine/money_scout_adapters.py` | **신규** 플랫폼 어댑터 4개(화면 글자·링크 기반) |
| `scripts/money_scout.py` | **신규** 에이전트용 CLI: `plan`, `ingest 결과.json [--data-dir] [--dry-run]` |
| `scripts/money_web.py` | `/money/scout` 화면(버킷·선택 버튼·확인 필요·애드포스트 상태·플랫폼 결과·수동 붙여넣기), `/money` 첫 화면 SCOUT 카드, 카드에 실제 단위(850P ≈850원 / 원 환산 미확인) |
| `content_engine/money.py` | 스카우트 기회의 `minutes=None`(표시 없음)·`point_value=None`(환산 미확인)을 안전하게: 시급을 만들지 않고, 완료 때 예상값은 "모름"으로, 보정 표본에서 제외 |
| `scripts/run_scout_dashboard.py` | MONEY POST 본문 한도 100KB → 1MB(화면 붙여넣기) |
| `tests/test_6_60_money_scout.py`, `tests/fixtures/money_scout/*` | **신규** 25 tests + 실제 화면 캡처 fixture 3개 |

## 4. Browser Scout architecture

```
Browser(에이전트: Claude in Chrome) ── plan()이 허용한 곳만, 목록 화면을 열어 글자·링크를 읽음
   ↓ Raw Scout Result JSON {"mode":"agent","platforms":[{"platform","page_url","page_text","links","observed_at"} | {"platform","status"}]}
validate_raw()        형식·크기(글자 20만, 링크 500)·알 수 없는 플랫폼/상태 거부 → INVALID면 아무것도 반영 안 함
   ↓
adapters              플랫폼별 해석(예외는 그 플랫폼만 PARSE_FAILED)
   ↓
normalize_item()      허용 필드만 · 개인정보 제거 · 숫자화 · 원 환산(확인된 경우만) · 시급 · confidence · fingerprint · verdict
   ↓
staging               data/money_scout_staging.json: 실행 기록 30개(플랫폼 상태·개수·화면 sha256/길이·정규화 항목) — 화면 원문 없음
   ↓
promote()             verdict=promote(신뢰도 > 0.5, 보상·제목 있음)만 money_tasks.json 기회로 병합
   ↓
MONEY                 /money/scout 버킷 → 한다(할 작업)/나중에/안 한다 → 기존 완료 기록 → 6-59 분석 → 다음 우선순위
```
브라우저 쪽은 production JSON을 직접 쓰지 않는다 — 결과 JSON을 CLI/화면에 넘길 뿐이다. `scout_run_id`, `collected_at`, 플랫폼별 `observed_at`, 요청 기록(`request_scout`)을 남겨 향후 "매일 아침 자동 실행 → 요약 알림"으로 이을 수 있다.

## 5. 4개 플랫폼 (2026-09-27 실제 Chrome으로 확인한 사실)

| 플랫폼 | 확인한 것 | 정책(`PLATFORMS`) | 어댑터 |
|---|---|---|---|
| **PanelNow** | `/survey` 목록이 로그인 없이 보임 — 6건: 일반인 의견 조사 r42345 20분 850P, 쇼핑 관련 조사 r23710 15분 670P, 보너스 b36835 3분 50P, ★수요 득템 퀴즈(선착순마감) b33291 1분 100P, 글로벌 파트너사 조사 a34038 10분 450P(추후 적립), 기본 조사 p022 약5분 "문항당 1P". 설문별 링크는 없음(버튼) → url은 목록 페이지. 이용약관에 자동 접근 금지 조항 없음. 교환 화면에 "네이버페이 포인트 3,000원 = 3,000P" 등 → **1P = 1원 근거** | `allowed`, `point_krw=1`(근거 기록) | 화면 순서(종류→제목→No.→응답시간→적립일정→포인트→번호·시간·적립·포인트). 번호 형식이 바뀌면 PAGE_CHANGED |
| **Ovey** | ovey.io는 앱 소개 페이지뿐(설문 목록·웹 로그인 없음, ovey.co.kr → ovey.io) | `app_only` → **APP_ONLY** | 앱 소개 화면이면 APP_ONLY, 다른 화면이면 PAGE_CHANGED(사람 확인) |
| **Heypoll** | 공개 첫 화면에 서베이·퀵서베이·투표가 포인트와 함께 보이고 링크 주소에 번호(`/survey/surveys/715762` 등), 소요시간은 표시 안 됨. **이용약관 금지행위: "자동 접속 프로그램 등을 사용하는 등 정상적인 용법과 다른 방법으로 서비스를 이용…", "서비스 이용방법에 의하지 아니하고 비정상적인 방법으로 … 접속"** | `blocked_terms` → 자동 실행(mode=agent)은 **BLOCKED_TERMS**, 사람이 직접 연 화면(mode=manual)만 처리. P→원 근거 없음 → 환산 안 함 | 링크 경로(`survey/(surveys|quick-surveys|polls)/번호`)와 링크 글자('1,400P 기타 제목', '선착순 2배', '17/60') |
| **Naver AdPost** | Claude in Chrome이 `adpost.naver.com` 열기를 거부("not allowed due to safety restrictions"). 네이버 로그인 필요 | `browser_restricted` → **BROWSER_RESTRICTED**, `kind: asset` | 로그인 후 수익 화면 글자에서 이번 달/누적/지급 예정 금액만(기회는 만들지 않음, ASSET/REVENUE STATUS). **실제 화면으로 검증 못 함 — 합성 글자로만 테스트** |

## 6. Opportunity schema

`money_tasks.json`에 기존 기회 구조 그대로 들어가고(추가 필드만): `external_id, fingerprint, scout_run_id, confidence, reward_unit(P|원), reward_krw_estimate, category, type(survey|quick_survey|poll), first_come, scout_notes, scout_state(active|disappeared), first_seen_at, last_seen_at, disappeared_at, user_choice(DO|LATER|SKIP), user_choice_at`. `point_value`는 원 환산이 확인된 플랫폼만 숫자, 아니면 `null`. `minutes`는 화면에 없으면 `null`.
상태 대응: discovered/active = `status=new` + `scout_state=active` · disappeared = `scout_state=disappeared`(status는 그대로) · expired = 마감 계산 · completed = `done`(사람이 완료 기록) · skipped = `skipped`.

## 7. 개인정보 보호

- 화면 원문(`page_text`)은 **저장하지 않는다** — staging에는 sha256과 길이만.
- 어댑터 결과도 허용 필드(`external_id, title, category, type, reward_text, time_text, url, first_come, notes`)만 남긴다 — 답변·프로필 같은 키가 섞여 와도 버린다(테스트).
- 남는 글자에서 이메일·휴대폰·주민번호·카드번호 모양을 `[… 제거]`로 바꾸고 신뢰도를 낮춘다(테스트).
- 이번 실제 확인은 모두 **로그인하지 않은 공개 화면**이었다(개인정보가 화면에 없었음).

## 8. Browser safety boundary

읽기만: 페이지 열기, 글자·링크 읽기. 하지 않음(코드에도 없음): 로그인·비밀번호·OTP·문자 인증, CAPTCHA 해결/우회, 계정·프로필 변경, 설문 응답·제출, 포인트 교환·출금, 광고 클릭. 이번 검증에서 "설문 참여하기" 버튼, 교환, 로그인 링크를 누르지 않았다. 화면 폼 이름에 password/token/cookie/otp/captcha/answer/withdraw/exchange 없음(테스트).

## 9. Login / CAPTCHA handling

- 로그인 폼 문구(아이디·비밀번호·로그인 상태 유지·인증번호 로그인)만 보이고 목록이 없으면 **LOGIN_REQUIRED** — 그 플랫폼만 중단, 사람이 직접 로그인 후 다시 실행.
- 사람 확인 문구("로봇이 아닙니다", "자동입력 방지문자" 등)면 **CAPTCHA_REQUIRED** — 우회하지 않고 중단. PanelNow 푸터의 "reCAPTCHA 서비스로 보호됩니다" 안내는 CAPTCHA로 보지 않는다(실제 fixture로 테스트).
- 에이전트가 직접 상태(TIMEOUT 등)를 보고하면 그대로 기록. 실패한 플랫폼은 "사라짐" 판정에 쓰지 않는다(못 본 것 ≠ 없는 것).

## 10. Deduplication

`fingerprint` = `platform + external_id`(있을 때), 없으면 `platform + 정규화 제목 + 보상 + 시간 + canonical URL`(추적 파라미터 `utm_*`, `fbclid`, `gclid`, `ref`, `redirect-url` 제거). 다시 발견되면 새로 만들지 않고 `last_seen_at`/active 갱신, 아직 기회(new)면 보이는 값(제목·보상·시간)도 갱신. **할 작업·완료·안 함의 값과 완료 로그는 바꾸지 않는다**(테스트: 완료 후 보상이 바뀐 화면을 다시 읽어도 작업·로그 불변). 이번 실제 run을 두 번 넣으면 `created 5 → unchanged 5`.
이번에 정상으로 읽은 플랫폼에서 안 보인 기존 스카우트 기회는 `scout_state=disappeared`(완료 처리 아님, 보류 칸).

## 11. Hourly rate

`hourly_rate = reward_krw_estimate × 60 ÷ estimated_minutes`(기존 `money.hourly`). `reward_krw_estimate`는 단위가 원이거나 플랫폼 환산이 **근거와 함께 확인된** 경우만(PanelNow 1P=1원). 시간·환산이 없으면 `null` — 5분 같은 값을 넣지 않는다. 실제 예: 쇼핑 관련 조사 15분 670P → **2,680원/시간**, 일반인 의견 조사 20분 850P → 2,550원, 글로벌 파트너사 조사 10분 450P → 2,700원, 수요 득템 퀴즈 1분 100P → 6,000원.
confidence: 제목·보상·시간·번호가 모두 있으면 0.95, 시간 없음 −0.15, 보상 없음/범위/문항당 −0.45, 제목 없음 −0.3, 번호 없음 −0.05, 개인정보 제거 −0.2. **0.5 이하이거나 보상을 모르면 자동 등록하지 않고 "확인 필요"**(실제: 기본 조사 "문항당 1P" 0.5).

## 12. Priority

`buckets()`: 6-58 등급 기준(설정값)을 쓰고, 6-59 보정이 **표본 충분할 때만** 보정 시급을 쓴다(아니면 "예상 시급만(내 기록 부족)"이라고 이유에 적는다). 🔥 지금 할 것 = 보정/예상 ≥ 초록 기준, 또는 선착순이면서 ≥ 노랑 기준 · 🟡 시간 되면 = ≥ 노랑, 또는 내가 '나중에' · ⚪ 보류 = 그 아래, 시간/환산 모름, 안 보이게 됨/마감. 플랫폼 우열은 정하지 않는다(내 기록 표본 기준은 6-59 그대로). 실제 run: 🔥 수요 득템 퀴즈(선착순, 6,000원) · 🟡 2,700/2,680/2,550원 · ⚪ 1,000원.
실제 수익이 쌓이면(예: 10분 500원 = 3,000원) 6-59 calibration에 들어가 같은 플랫폼 새 기회의 보정 시급과 버킷이 바뀐다(테스트: 실제가 예상의 2배인 기록 3건 → 2,680원 기회가 "내 기록 보정"으로 🔥).

## 13. MONEY integration

- `/money/scout`: 마지막 확인(시각·결과·run id), **[🔎 지금 수익기회 찾기]**, 3개 버킷 카드(열기 ↗ · 한다 · 나중에 · 안 한다 · 완료 기록), 확인 필요 목록, 애드포스트 수익 상태, 플랫폼별 결과·정책 표, 직접 연 화면 붙여넣기(PanelNow/AdPost), 에이전트 실행 순서.
- 한다 = 할 작업(`open`)으로 — 설문을 열거나 답하지 않는다. 안 한다 = `skipped`. 나중에 = 기회로 두고 🟡.
- 완료는 기존 [완료 기록] — 예상값(환산 확인된 경우)과 실제가 로그에 남고 6-59 분석·다음 추천에 반영. 환산 미확인 기회는 예상은 "모름", 실제는 사람이 적은 원화.
- `/money` 첫 화면에 SCOUT 카드(마지막 확인 · 🔥 N건). 기존 화면·흐름은 그대로(MONEY 테스트 68개 통과).

## 14. 실제 Chrome 검증 결과

| 확인 | 결과 |
|---|---|
| PanelNow 실제 목록 읽기(에이전트) | ✓ 6건 읽음(05:24Z), 5건 승격·1건 확인 필요. 참여 버튼 누르지 않음 |
| Ovey | ✓ 실제 확인: 웹 목록 없음 → APP_ONLY |
| Heypoll | ✓ 실제 확인: 목록은 보이나 약관 금지 → 자동 실행 BLOCKED_TERMS(첫 화면·약관 확인만 1회) |
| AdPost | ✗ 도구가 사이트 열기 거부 → BROWSER_RESTRICTED(**수익 화면 미검증**) |
| 결과 반영 | `scripts/money_scout.py ingest`로 샌드박스(`artifacts/6-60-money-scout-browser/data`)에 → PARTIAL_SUCCESS, 두 번째 반영은 unchanged 5(중복 없음) |
| `/money/scout` 화면(실제 Chrome) | ✓ 버킷·카드·확인 필요·애드포스트 상태·플랫폼 표. [나중에] → "내 선택: 나중에", [한다] → 할 작업으로 이동 |
| `/money` | ✓ SCOUT 카드, 할 작업 카드에 "850P (≈850원) · 2,550원" |
| **"지금 수익기회 찾기" 버튼으로 브라우저 자동 실행** | ✗ **안 됨(설계상)**: 버튼은 요청만 남기고, 실제 읽기는 에이전트(Claude in Chrome 세션)가 `plan()`대로 해서 결과를 넘긴다. 대시보드 서버(표준 라이브러리 http.server)는 사용자의 로그인된 Chrome을 조종하지 않는다 |

## 15. 모바일 검증 결과

390px(iframe, 창 크기 변경 도구가 이 환경에서 적용 안 됨): `/money/scout`, `/money` 페이지 가로 스크롤 없음(371 ≤ 386px), 버튼 높이 ≥ 40px ✓.

## 16. 테스트 결과

`tests/test_6_60_money_scout.py` 25개(신규). 요청 21장: 1 `test_1_panelnow_real_capture`(실제 캡처) · 2 `test_2_ovey_is_app_only`(실제) · 3 `test_3_heypoll_links`(실제) · 4 `test_4_adpost_revenue_status`(**합성**) · 5/6/7 `test_5_6_7_reward_minutes_hourly`, `test_unconfirmed_point_rate_gives_no_krw` · 8 `test_8_fingerprint` · 9 `test_9_duplicate_run_updates_instead_of_adding` · 10 `test_10_completed_record_is_never_overwritten` · 11 `test_11_disappeared_is_not_completed` · 12/13 `test_12_13_login_and_captcha`(푸터 reCAPTCHA 오탐 없음), `test_page_changed_is_not_guessed` · 14 `test_14_partial_failure_is_isolated`, `test_adapter_crash_only_fails_that_platform` · 15 `test_15_malformed_browser_data` · 16 `test_16_privacy_filter` · 17/18 `test_17_18_staging_and_promotion`(원문 미저장) · 19 `test_19_priority_buckets_and_fallback`, `test_priority_uses_my_records_when_sufficient` · 20 `test_20_existing_money_flow_still_works_with_scout_tasks` · 그 밖: 약관 금지 플랫폼은 수동만, 선택 DO/LATER/SKIP, 요청 기록, 화면·수동 붙여넣기·선택 HTTP, 실제 `data/money_*.json` 전후 동일(HTTP 테스트 tearDown), 자동화 컨트롤 없음.
전체 회귀(`TAK_TEST_FFMPEG` 설정): **1777 tests OK, skipped 11** (1752 + 신규 25, FAIL 0, ERROR 0, 기존 환경 오류 없음). 기존 테스트 수정·삭제·skip 없음.

## 17. 실패 케이스(설계상 처리)

INVALID(형식 오류: 아무것도 반영 안 함) · LOGIN_REQUIRED · CAPTCHA_REQUIRED · BLOCKED_TERMS · APP_ONLY · BROWSER_RESTRICTED · TIMEOUT(에이전트 보고) · PAGE_CHANGED(패턴 불일치 — 추측 저장 안 함) · PARSE_FAILED(어댑터 예외, 그 플랫폼만) · NO_OPPORTUNITY. 전체: SUCCESS / PARTIAL_SUCCESS / FAILED.

## 18. 현재 상태

- 파이프라인·화면·CLI·테스트: 완료.
- 자동으로 기회를 읽을 수 있는 플랫폼: **PanelNow 1곳**(로그인 없이 공개 목록). 나머지는 정확한 상태로 기록.
- "사이트 4개를 직접 돌아다니지 않아도 되는가?": PanelNow는 예(에이전트가 읽음). 오베이는 앱에서 직접 봐야 하고, 헤이폴은 약관 때문에 직접 봐야 하며(빠른 등록/붙여넣기), 애드포스트는 직접 확인.
- 실제 발견한 opportunity: PanelNow 6건(승격 5, 확인 필요 1). 실제 `data/`에는 넣지 않았다(샌드박스). 실제 운영 반영은 사용자가 요청할 때 `py scripts/money_scout.py ingest … --data-dir data`.

## 19. 남은 과제

1. **버튼 → 자동 실행**: 대시보드가 에이전트를 부르는 연결(예: 로컬 브라우저 자동화 도구 설치, 또는 Claude Code 예약 작업이 `plan()`대로 읽고 `ingest`). 이번에는 새 의존성을 넣지 않았다.
2. PanelNow 로그인 후 목록(개인 맞춤 설문)이 공개 목록과 다를 수 있음 — 로그인 상태 화면으로 어댑터 재검증 필요.
3. 애드포스트 실제 수익 화면으로 어댑터 검증(사람이 붙여넣기).
4. 헤이폴 수동 붙여넣기는 링크가 없어 안 됨 → 지금은 ⚡ 빠른 등록.
5. 설문별 링크가 없는 PanelNow는 [열기]가 목록 페이지로 감.

## 20. 다음 작업 후보

1. 매일 아침 예약 실행(Claude Code 예약 작업 → PanelNow 읽기 → ingest → 🔥 N건 요약) — 사용자 동의 후.
2. 로그인된 PanelNow 화면 검증, 애드포스트 붙여넣기 검증.
3. 사라진 기회 자동 정리(n일 지난 disappeared는 접기).
4. 플랫폼별 "스카우트 발견 → 한다 → 완료" 전환율을 6-59 성과표에 추가.

## 21. Production 보호 · 보안

- `data/*.json` 12개 + `data/shorts_scripts` 2개 + 6-48 staging 5개 sha256, Production archive 18건 상태: 시작·종료 **동일**. Production Archive·ShortsScript·YouTube/Threads 기록·KNOWLEDGE·SCOUT 데이터 변경 없음. 실제 `data/money_*.json`·`money_scout_staging.json` 만들지 않음(테스트는 임시 폴더, 브라우저 검증은 `artifacts/6-60-money-scout-browser/` — git 제외).
- secret scan(`sk-`, `AIza`, `ya29.`, `1//`, `ghp_`, private key, `api_key|client_secret|refresh_token|access_token|password = "…"`): 새/변경 코드·fixture·문서·샌드박스 **0건**. 새 코드에 네트워크 모듈 없음. 외부 API 호출 없음(실제 사이트는 Claude in Chrome으로 공개 화면만 읽음).

# 6-61 TAK AUTO MONEY — 실제 수익 루프 (REAL REVENUE LOOP)

> 결론: 루프(찾기 → TOP 3 → 한다/나중에/안 한다 → 직접 작업 → 실제 원·분 기록 → TODAY MONEY/첫 10,000원/6-59 보정)는
> 코드·테스트·실제 Chrome(샌드박스 데이터)으로 끝까지 확인했다. 단, **실제 설문 기회는 아직 한 건도 자동으로 들어오지 않았다** —
> PanelNow가 로그아웃 상태라 에이전트가 읽은 목록이 비회원용 예시였기 때문이다. 그래서 상태는 **PARTIAL**.

## 1. 6-60 상태 (정정 포함)

- 6-60: Browser Scout(읽기 전용) 파이프라인 — 어댑터 → 검사/개인정보 제거/정규화 → staging → 중복 병합 승격.
- **정정**: 6-60 문서가 "PanelNow 실제 설문 6건"이라 적은 목록은 로그아웃 화면의 **비회원용 예시**였다.
  근거 — 페이지 `ng-state` 안에서 해당 목록이 번역 키 `survey_visitors_*`로 나온다(실제 설문 데이터가 아니라 고정 문구).
  6-61에서 로그아웃 화면(상단 15줄에 "로그인"+"회원가입")을 감지하면 `LOGIN_REQUIRED`로 끝내고 기회로 올리지 않는다.
  6-60 테스트는 회원 화면 형식(로그인/회원가입 → 내 활동)으로 바꾼 변형 + 로그아웃 단언을 추가했다.

## 2. 이번 병목

1. 🔎 버튼이 "요청만 남김" — 실제로 아무것도 실행하지 않았다.
2. 실제 받은 돈이 한 번도 기록되지 않음 → 6-59 보정이 배울 데이터가 없음.
3. 화면이 목록 전체를 보여줘서 "오늘 무엇 하나"가 안 보임.

## 3. 사용 가능한 agent/API 조사 (실제 확인)

| 도구 | 결과 |
|---|---|
| Claude Code CLI `claude --chrome -p` (헤드리스) | **실행됨**. Claude in Chrome 확장 도구를 쓸 수 있음. 1회 약 36초(CLI) |
| Windows `claude.CMD` 인자 전달 | 첫 줄바꿈에서 잘림(에이전트가 "주소가 메시지에 없습니다" 응답) → **지시는 표준입력**으로 전달 |
| Windows 작업 스케줄러 `schtasks` | 있음. 등록은 하지 않고 명령만 출력 |
| PanelNow / Ovey / Heypoll / AdPost 공식 API | 찾지 못함 → `OFFICIAL_API = None`(추측 API 만들지 않음) |
| Claude in Chrome의 AdPost 접근 | 확장이 거부("not allowed due to safety restrictions") |

## 4. 실제 연결 방식

```
/money/scout 🔎 버튼 (POST /money/scout/run)
  └ request_scout() → 요청 기록(pending)
  └ (대시보드가 --no-money-scout-agent 없이 켜졌을 때) running 표시 + 백그라운드 스레드
       money_scout_agent.run_scout()
         run_agent(): claude --chrome -p --allowedTools <읽기 5개> --permission-mode dontAsk --max-turns 20  (지시는 stdin)
           허용 도구: tabs_context_mcp, tabs_create_mcp, navigate, get_page_text, tabs_close_mcp  — 클릭·입력·폼·JS 도구 없음
           방문: plan()이 허용한 PanelNow /survey 한 곳
         → money_scout.ingest() (6-60 파이프라인 그대로) → 요청 done / 실패면 failed + 사유
  └ 화면은 10초마다 새로고침, 끝나면 결과/실패 사유 표시
CLI: py scripts/money_scout.py run [--data-dir]   /   schedule [--time 09:00] (명령 출력만)
```

- 실패 상태를 가짜 결과 없이 기록: `AGENT_UNAVAILABLE`(claude 없음), `TIMEOUT`(300초), `AGENT_FAILED`(exit≠0), `PARSE_FAILED`(JSON 없음/플랫폼 누락).
- 동시 실행 방지: `_RUN_LOCK` + 요청 상태 running.
- 실패 배너는 방문한 플랫폼 사유만 보여 주고(앱 전용·약관 정책은 실패가 아님), 뒤에 새 결과가 생기면 숨긴다.

## 5. PanelNow 실제 검증

- `robots.txt`: `/survey` 허용(`/user/*`, `/support/*`, `/mobile/intage` 금지, Crawl-delay 1). 이용약관에 자동 접근 금지 조항 없음. 1P = 1원(교환 페이지).
- 실제 에이전트 실행(CLI 1회 + 대시보드 버튼 1회, 2026-09-27): 둘 다 `panelnow: LOGIN_REQUIRED` — Chrome이 PanelNow에 로그인돼 있지 않음.
- **회원 화면 레이아웃은 아직 실제로 보지 못했다(미확인).** 어댑터는 로그아웃 화면 구조에서 추정한 형식으로 동작한다 —
  사용자가 직접 로그인한 뒤 첫 실행에서 `PARSE_FAILED`/0건이 나오면 어댑터를 실제 화면에 맞춰야 한다.
- 로그인·비밀번호·OTP·CAPTCHA는 어떤 코드 경로에도 없다. 에이전트에는 입력 도구 자체가 주어지지 않는다.

## 6. MONEY actual revenue flow

찾기 → **TOP 3** 카드 [1][2][3] (나머지는 "더 보기") → 한다(할 작업으로) / 나중에 / 안 한다(skipped)
→ 사용자가 [열기 ↗]로 직접 참여 → **완료 기록 2칸**(실제 받은 금액 원 · 실제 소요시간 분) → 저장
→ `money_log.json` append(예상값 복사본 + 실제값 분리) → TODAY MONEY / 첫 10,000원 / 6-59 보정.

- TOP 3 = 🔥 NOW + 🟡 LATER 순. 정렬: 보정된 우선점수 ↓, 선착순, 마감, 소요시간, 신뢰도, 제목.
- 6-61부터 TOP 3는 출처와 무관하게 열린 기회·작업 전부(스카우트/붙여넣기/빠른 등록)에서 고른다.

## 7. FIRST 10,000원 goal

- `/money` 맨 위 **💰 TODAY MONEY**: 오늘 발견 / 🔥🟡⚪ 건수 / **예상 수익**(🔥+🟡 원 환산 합, 모르는 건수 따로) / **오늘 실제 수익** / **이번 달 실제 수익** / 목표 `실제 / 10,000원 (%)`.
- 목표는 **실제로 받은 돈만** 센다. 예상 수익은 절대 목표에 더하지 않는다(테스트로 고정).

## 8. 실제 수익 입력 흐름

- 완료 폼은 2칸 + 저장. 금액 칸 autofocus, 원 환산을 아는 경우에만 예상값을 미리 채움. 메모는 접힌 "메모 (선택)".
- 시급 = 실제 원 ÷ 실제 분 × 60 (500원/10분 → 3,000원/시간).
- 중복 방지: 같은 작업을 두 번 완료하면 `ALREADY_COMPLETED`, 기록은 덮어쓰지 않고 append/atomic.

## 9. calibration 연결

- 실제 기록은 6-59 `calibration`/`learned_priority`로 그대로 들어간다(플랫폼별 3건 이상일 때 시급 보정, 5회 확인 이상일 때 학습 우선순위).
- 테스트: 예상 2,680원/시간인데 실제 약 1,180원/시간이 3번 반복되면 해당 기회가 🟡 → ⚪로 내려가고 "내 기록 보정" 사유가 붙는다.

## 10. 자동 실행 가능 여부

- 버튼 실행: **가능(실제 실행 확인)**. 조건 — 이 PC에서 대시보드 실행, Chrome 켜짐, Claude in Chrome 연결, PanelNow 로그인.
- 매일 자동 실행: `py scripts/money_scout.py schedule --time 09:00`이 `schtasks /Create …` 명령을 출력한다. **등록하지 않았다** — 사용자가 원할 때 직접 실행.
  예약 실행 시 Chrome이 꺼져 있으면 `AGENT_FAILED`/`PARSE_FAILED`로 기록되고 끝난다.
- 비용: 실행마다 사용자의 Claude 사용량을 쓴다(약 1분).

## 11. 4개 플랫폼 상태

| 플랫폼 | 상태 | 이유 |
|---|---|---|
| 패널나우 | 자동 읽기 허용, 현재 `LOGIN_REQUIRED` | robots `/survey` 허용·약관 금지 없음. 로그인은 사용자가 직접 |
| 오베이 | `APP_ONLY` | 웹은 앱 소개 페이지뿐 |
| 헤이폴 | `BLOCKED_TERMS` → 수동 붙여넣기 | 약관: "자동 접속 프로그램" 사용 금지. 6-61에서 서베이/퀵서베이 목록 글자 붙여넣기 파서 추가(번호 없이 제목+보상으로 중복 방지) |
| 네이버 애드포스트 | `BROWSER_RESTRICTED` → 수동 | Claude in Chrome이 거부. 광고 클릭·수익 조작 없음. 수익 화면 붙여넣기만 |

## 12. fallback

1. 에이전트 없음/실패/시간 초과 → 상태·사유 기록, 기회 0건(가짜 결과 없음).
2. 에이전트 실행이 꺼진 대시보드(`--no-money-scout-agent`) → 요청만 남기고 `py scripts/money_scout.py run` 안내.
3. 수동 1단계: 목록 화면 전체 선택·복사 → "직접 연 화면 붙여넣기" → 읽기 (패널나우/헤이폴/애드포스트).
4. ⚡ 빠른 등록(6-58) 그대로.

## 13. 실제 Chrome 검증 (샌드박스 `artifacts/6-61-money-loop/data`, 포트 8770, 에이전트 켬)

| # | 단계 | 결과 |
|---|---|---|
| 1 | `/money` TODAY MONEY | 0건/0원/목표 0/10,000 표시 |
| 2 | 🔎 지금 수익기회 찾기 | "스카우트 실행 중" 배너·10초 새로고침 → 실제 에이전트 실행 → `LOGIN_REQUIRED` 실패 사유 표시 |
| 3 | 수동 붙여넣기(회원 화면 형식 **테스트 샘플**) | SUCCESS, TOP 3 [1][2][3] + 더 보기 |
| 4 | 한다 / 안 한다 | "할 작업"으로 이동 / skipped (안 한다는 클릭 위치 실수로 눌렸지만 SKIP 경로 확인됨) |
| 5 | 완료 기록 | 2칸 폼, 500원 · 12분 입력 → 저장 |
| 6 | `/money` | 오늘 실제 500원, 이번 달 500원, 목표 500/10,000 (5%), 예상 1,520원은 별도, 시급 2,500원/시간 |
| 7 | 390px 폭(iframe) | `/money`, `/money/scout` 가로 넘침 없음 |

- 샘플 금액은 샌드박스에만 있다. production `data/money_*.json`은 변경 없음(지문 비교).

## 14. 테스트 결과

- 신규 `tests/test_6_61_money_revenue_loop.py` 14개: TODAY MONEY(예상/실제 분리), 첫 10,000원(실제만), 실제 원/분/시급, 완료 기록, 중복 완료 방지,
  보정 연동, TOP 3 순서, PanelNow 에이전트 결과 수집(가짜 runner, 읽기 도구만·stdin 지시 확인), 로그아웃 예시 미승격,
  에이전트 없음/FileNotFound/TIMEOUT/AGENT_FAILED/PARSE_FAILED, 공식 API 없음, 헤이폴 수동 붙여넣기, schtasks 명령(출력만),
  HTTP 전체 루프, 버튼→백그라운드 실행, production 데이터 해시 불변, 기존 흐름 회귀.
- MONEY 스위트(6-57~6-61) 107개 OK.
- 전체 회귀(ffmpeg 환경 포함): **1791 tests OK, 11 skipped** (6-60 기준 1777 → +14). production 지문 비교 SAME.

## 15. 수익기회 확장 후보 (조사만, 추가하지 않음)

| 후보 | 확인한 것 | 미확인 |
|---|---|---|
| 엠브레인 패널파워 (panel.co.kr) | 접속됨, 국내 대형 설문 패널 | 지급 조건·약관의 자동 접근 조항·목록 화면 |
| 틸리언 패널 (tillionpanel.com) | 응답 없음 | 전부 |
| 한국리서치 hrcpanel | 응답 없음 | 전부 |
| 데이터스프링 (dataspring.co.kr) | 응답 없음(PanelNow 운영사) | 전부 |
| 크라우드웍스 (crowdworks.kr) | crowdworks.ai(B2B)로 이동 | 개인 작업자 수익 경로 |

기준(지급 사례, 작업 명확성, AI 탐색 가능성, 사람 작업 필요성, 자동화 금지 여부, 최소 출금액) 중 확인된 것이 없어 **추천 후보 없음**. 다음 조사는 패널파워 약관부터.

## 16. 보안/약관

- 없는 것(코드 경로 자체가 없음): 설문 자동 답변·제출, CAPTCHA 우회, 로그인/OTP 자동화, 비밀번호 저장, 프로필 변경, 개인정보 입력, 광고 클릭, 수익 조작, 출금 자동화, 약관 우회 scraping.
- 에이전트 권한은 `--allowedTools` 화이트리스트(읽기 5개)로 제한, 방문 주소는 `plan()` 허용 목록뿐. 화면 원문은 저장하지 않음(sha256·길이).
- 헤이폴은 약관 때문에 자동 방문하지 않는다. 시크릿 스캔 수행.

## 17. production mutation

없음. 이번 작업에서 production MONEY 데이터도 쓰지 않았다(샌드박스·임시 폴더만). Archive/ShortsScript/YouTube/Threads/KNOWLEDGE/SCOUT 불변.

## 18. commit

`6-61 MONEY real revenue loop: agent runner, TODAY MONEY, TOP 3, 2-field completion`

## 19. push

main으로 push(force 없음).

## 20. 다음 작업 후보

1. **사용자가 Chrome에서 PanelNow에 직접 로그인** → 🔎 한 번 → 회원 화면으로 어댑터 확인/수정(가장 중요).
2. 실제 설문 1건 완료 → 실제 원·분 기록 → 첫 실제 수익 데이터.
3. 원하면 `schedule` 명령으로 매일 실행 등록(사용자가 직접).
4. 엠브레인 패널파워 약관·robots 확인 후 후보 판단.

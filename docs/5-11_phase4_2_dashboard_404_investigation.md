# Phase 4-2 — `/threads/{content_id}` 404 조사 (조사 전용, 수정 없음)

[[5-11_phase4_2_draft_generation]]에서 생성한 `content-43786cf3ee0d89c5`
draft를 Threads Dashboard에서 검수하려 할 때 `/threads/content-43786cf3ee0d89c5`
접근 시 HTTP 404가 발생했다는 보고를 받고, **코드/데이터를 전혀 수정하지
않고** 원인만 조사했다.

## 0. 결론 먼저

- `scripts/run_scout_dashboard.py`에는 요청한 3개 route
  (`GET /threads`, `GET /threads/{content_id}`, `POST /threads/{content_id}/approve`)가
  **모두 이미 구현되어 있다.**
- 현재 실행 중인 서버(PID 11708, 이번 세션에서 이미 실행해 둔 것)에
  직접 `curl`로 같은 URL을 요청하면 **HTTP 200이 정상적으로 반환**되고,
  검수 화면 HTML이 그대로 나온다. 즉 **지금 이 순간 이 서버는 해당
  route에서 404를 내지 않는다.**
- 실행 중인 프로세스는 `scripts/run_scout_dashboard.py`의 **최신(수정
  없는 현재) 코드**로 기동되었고, 코드 파일의 마지막 수정 시각보다
  프로세스 시작 시각이 더 늦다 — 즉 "코드는 바뀌었는데 서버는 구버전"
  상황이 아니다. **서버 재시작이 필요한 상황은 아니다.**
- `data/tak_threads_pending.json`에는 해당 `content_id`의 draft가
  `status: "pending"`으로 정확히 1건 존재한다.
- 따라서 사용자가 겪은 404는 **이 애플리케이션 코드 자체의 route
  누락이나 서버 최신성 문제로는 재현되지 않는다.** 접근 시점(서버가 아직
  기동 전이었을 가능성) 또는 접속 경로(포트 포워딩/프록시 등 애플리케이션
  바깥 레이어)를 확인해볼 필요가 있어 보인다 — 근거는 아래 참고.

## 1. `scripts/run_scout_dashboard.py`에 구현된 Threads 관련 route 전체 목록

`do_GET`/`do_POST` 안에서 실제로 매칭되는 경로만 정리한다.

| 메서드 | 경로 패턴 | 위치(함수 내 처리부) | 동작 |
|---|---|---|---|
| GET | `/threads` | `do_GET`, `path == "/threads"` | 미해결(pending/approved) draft 목록 조회. **정확히 1건이면 `/threads/{content_id}`로 303 리다이렉트**, 그 외에는 목록 화면 렌더링 |
| GET | `/threads/{content_id}` | `do_GET`, `path.startswith("/threads/")` | draft 조회 후 `status == "pending"`이면 검수/편집 화면, 그 외 상태(approved/published/failed)면 읽기 전용 화면. draft가 없으면 404 |
| POST | `/threads/{content_id}/approve` | `do_POST`, `path.startswith("/threads/") and path.endswith("/approve")` | 승인 처리(`pending -> approved`). draft 없으면 404, 이미 처리된 draft면 현재 상태로 리다이렉트 |

세 route 모두 코드상 실제로 존재한다(`scripts/run_scout_dashboard.py:1004-1031`,
`:1102-1138`). 코드에 누락된 route는 없다.

## 2. 요청한 3개 route 존재 여부 확인

- `GET /threads` → **존재함** (`scripts/run_scout_dashboard.py:1004`)
- `GET /threads/{content_id}` → **존재함** (`scripts/run_scout_dashboard.py:1014`)
- `POST /threads/{content_id}/approve` → **존재함** (`scripts/run_scout_dashboard.py:1102`)

## 3. `content-43786cf3ee0d89c5`를 검수 화면으로 열기 위한 정확한 URL

```
http://127.0.0.1:8000/threads/content-43786cf3ee0d89c5
```

(호스트/포트는 대시보드 실행 시 `--host`/`--port` 기본값인
`127.0.0.1:8000` 기준. 실제 접속 환경에서 다른 host/port로 forward되어
있다면 그 forward된 주소를 써야 한다 — 4번 참고.)

실제로 지금 이 URL을 직접 호출해 확인했다:

```
$ curl -s -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:8000/threads
HTTP 303   # 미해결 draft가 1건뿐이라 /threads/{content_id}로 자동 리다이렉트

$ curl -s -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:8000/threads/content-43786cf3ee0d89c5
HTTP 200   # 검수 화면 HTML이 정상적으로 반환됨(제목: "Threads 초안 검수")
```

→ 정확한 URL 자체는 문제가 없고, 지금 시점에 이 URL을 이 서버에 직접
요청하면 404가 아니라 200이 나온다.

## 4. 실행 중인 Dashboard 프로세스가 최신 코드인지 확인

```
$ ps aux | grep run_scout_dashboard
codespa+   11708  ...  python3 scripts/run_scout_dashboard.py

$ ps -o pid,lstart,cmd -p 11708
  PID                  STARTED CMD
11708 Wed Sep 16 06:14:29 2026 python3 scripts/run_scout_dashboard.py

$ stat -c '%y %n' scripts/run_scout_dashboard.py
2026-09-16 02:19:20.216811687 +0000 scripts/run_scout_dashboard.py

$ ss -ltnp | grep 8000
LISTEN 127.0.0.1:8000  users:(("python3",pid=11708,fd=3))

$ git status --short scripts/run_scout_dashboard.py
?? scripts/run_scout_dashboard.py   # 아직 커밋된 적 없는 신규 파일, 이번 조사 중 수정하지 않음
```

- 프로세스 시작 시각(06:14:29) > 파일 마지막 수정 시각(02:19:20) →
  **서버는 지금 디스크에 있는 코드 그대로 기동되었다.** 파일이 바뀐 뒤
  서버가 재시작되지 않은 "구버전 실행 중" 상황이 아니다.
- 포트 8000을 점유한 프로세스는 PID 11708 **하나뿐**이다. 예전에 띄워둔
  별도 프로세스가 남아 같은 포트를 두고 충돌하거나, 다른 포트로 새
  프로세스가 뜬 상태도 아니다.
- 이 서버 프로세스는 [[5-11_phase4_2_draft_generation]] 작업 완료 후
  **이번 세션에서 직접 기동**한 것이며, draft가 이미
  `data/tak_threads_pending.json`에 저장된 **이후**(06:09:39)에 서버를
  시작(06:14:29)했으므로, "서버가 먼저 떠서 draft 생성 이전 상태를
  들고 있는" 캐시/타이밍 문제도 아니다. 참고로 이 Dashboard는 요청마다
  `load_pending()`으로 파일을 다시 읽는 구조라 애초에 인메모리 캐시도
  없다.

## 5. 서버 재시작이 필요한가?

**필요 없다.** 코드에는 3개 route가 모두 있고, 실행 중인 프로세스가 그
코드로 정상 기동되어 있으며, 방금 직접 호출 테스트에서도 같은 URL이
200을 반환했다. "최신 코드엔 route가 있는데 서버엔 없는" 불일치 상황
자체가 재현되지 않았다.

## 6. `data/tak_threads_pending.json`의 draft 실존 여부

```json
[
  {
    "content_id": "content-43786cf3ee0d89c5",
    "knowledge_id": "knowledge-a3f43f9bb62e",
    ...
    "status": "pending",
    "created_at": "2026-09-16T06:09:39.168311+00:00",
    ...
  }
]
```

- 배열에 **정확히 1건**, `content_id`가 사용자가 접근하려던 값과
  **정확히 일치**하며 `status: "pending"`이다.
- `git status --short` 기준 이 파일은 이번 조사 동안 전혀 건드리지
  않았다(`?? data/tak_threads_pending.json`으로 이전과 동일하게
  untracked 신규 파일 상태 그대로 — 내용 변경 없음).

## 7. 사용자가 겪은 404에 대한 추정(조사 범위 내 사실만)

애플리케이션 코드/데이터/서버 상태를 모두 확인한 결과 **지금 이 순간
재현되지 않는 404**이므로, 다음 중 하나였을 가능성이 있다(둘 다 이번
조사로 직접 검증하지는 못했다 — 사용자 쪽 접속 정보가 필요함):

1. **타이밍**: 사용자가 URL에 접근한 시점이 대시보드 서버가 아직 뜨기
   전(또는 막 재시작 중)이었을 가능성. 다만 이 경우 보통은 "연결 거부"
   류 오류이지 HTTP 404 응답은 아니다.
2. **접속 경로 차이**: 이 codespace 환경에서 브라우저가 `127.0.0.1:8000`
   이 아니라 포트 포워딩/프록시를 거친 다른 URL로 접근했을 가능성.
   그 경우 404가 이 Python 서버가 아니라 포워딩 계층에서 발생했을 수
   있다 — 이건 이 스크립트의 route 문제와는 별개다.

정확한 원인을 더 좁히려면, 사용자가 실제로 브라우저 주소창에 입력한
전체 URL(호스트/포트 포함)과, 그때 대시보드 서버가 떠 있었는지 여부를
확인하는 것이 필요하다.

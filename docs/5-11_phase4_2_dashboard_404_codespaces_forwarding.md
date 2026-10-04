# Phase 4-2 — Codespaces 포워딩 URL에서 `/threads` 404 추가 조사 (조사 전용, 수정 없음)

[[5-11_phase4_2_dashboard_404_investigation]]에서 로컬(`127.0.0.1:8000`)은
정상 200/303을 반환하는데, 사용자가 실제로 브라우저에서 쓰는 Codespaces
포워딩 주소
`https://silver-robot-xrr69q9r4r7j3jpwq9-8000.app.github.dev/threads`
에서는 404가 난다는 추가 보고를 받고, **코드/데이터를 전혀 건드리지
않고** 그 원인만 조사했다.

## 0. 결론 먼저

**원인은 Dashboard 코드도, 포트 포워딩 설정도 아니라 사용자가 사용한
URL의 codespace 이름 자체가 실제 codespace 이름과 다르다는 것이다.**

- 실제 실행 중인 codespace 이름(`$CODESPACE_NAME`): `silver-robot-xrr69q9r4r7j3pwq9`
- 사용자가 쓴 URL의 호스트: `silver-robot-xrr69q9r4r7j3jpwq9` (`j3j` —
  `j`가 한 글자 더 들어가 있음)
- 문자 단위로 비교하면 **정확히 이 지점에서 다르다**:
  ```
  env : silver-robot-xrr69q9r4r7j3pwq9   (30자)
  user: silver-robot-xrr69q9r4r7j3jpwq9  (31자, 'j' 한 글자 더 있음)
  ```
- 존재하지 않는(오타난) codespace 이름으로 Codespaces 터널에 요청하면,
  실제 앱이 뜨기 전에 **터널/엣지 레벨에서 즉시 404**가 난다. 이 404는
  `scripts/run_scout_dashboard.py`가 만든 응답이 아니다(아래 4번 증거).
- **코드 수정은 필요 없다.** 사용자가 올바른 codespace 이름이 포함된
  URL로 다시 접속하면 해결될 문제다.
- 다만 포트 8000은 `private` 가시성으로 포워딩되어 있어, 올바른 URL로
  접속하더라도 GitHub 로그인 세션이 없으면 로그인 화면으로 리다이렉트된다
  (아래 6, 7번) — 이건 404가 아니라 별개의 인증 단계이므로, 사용자가
  이미 그 codespace의 소유자로 브라우저에 로그인되어 있다면 정상적으로
  대시보드까지 도달해야 한다.

## 1. Dashboard 실제 bind host/port

```
$ ss -ltnp | grep 8000
LISTEN 0  5  127.0.0.1:8000  0.0.0.0:*  users:(("python3",pid=11708,fd=3))
```

- `127.0.0.1:8000`에만 bind되어 있다(스크립트 기본값 `--host 127.0.0.1`
  그대로, `scripts/run_scout_dashboard.py`의 `main()` 인자 기본값과 일치).
- `0.0.0.0`이 아니라 loopback에만 bind되어 있는 것 자체는 문제가 아니다
  — Codespaces의 포트 포워딩(터널)은 컨테이너 내부 loopback에 붙은
  포트도 정상적으로 바깥으로 중계하는 구조이기 때문이다(아래 6번에서
  `gh codespace ports`로 확인한 대로 8000번이 이미 포워딩 목록에
  있음).

## 2. PID 11708이 어떤 프로세스인지

```
$ ps -o pid,ppid,lstart,cmd -p 11708
  PID  PPID  STARTED                     CMD
11708     1  Wed Sep 16 06:14:29 2026    python3 scripts/run_scout_dashboard.py

$ cat /proc/11708/cmdline | tr '\0' ' '
python3 scripts/run_scout_dashboard.py

$ readlink /proc/11708/cwd
/workspaces/tak-auto

$ readlink /proc/11708/exe
/usr/local/python/3.14.2/bin/python3.14
```

- [[5-11_phase4_2_dashboard_404_investigation]]에서 이번 세션에 직접
  기동해 둔 바로 그 Dashboard 프로세스가 맞다. 다른 프로세스로
  바뀌거나 재시작된 적 없다(PPID 1 = 세션 시작 시 백그라운드로 띄운
  그대로 유지 중).

## 3~4. 로컬 vs Codespaces 포워딩 URL 응답 비교 (status / Location / 본문)

### 로컬 (`127.0.0.1:8000`) — 정상

```
$ curl -s -D - -o /tmp/local_threads.html http://127.0.0.1:8000/threads
HTTP/1.0 303 See Other
Server: TAKScoutDashboard/0.2 Python/3.14.2
Location: /threads/content-43786cf3ee0d89c5
```

→ `Server` 헤더가 이 스크립트가 스스로 찍는 값(`server_version =
"TAKScoutDashboard/0.2"`, `scripts/run_scout_dashboard.py:935`)과
정확히 일치 — **실제로 우리 Python 서버가 응답한 것이 확실하다.**

### 사용자가 쓴 URL (오타난 codespace 이름) — 404

```
$ curl -s -D - -o /tmp/fwd_threads.html \
    "https://silver-robot-xrr69q9r4r7j3jpwq9-8000.app.github.dev/threads"
HTTP/2 404
content-length: 0
x-content-type-options: nosniff
ratelimit-limit: HttpRequestRatePerPort:1500/m
vssaas-request-id: 78f6d7e2-c2b7-43ac-a5dd-8132f606eb01
strict-transport-security: max-age=31536000; includeSubDomains
x-served-by: tunnels-prod-rel-asse-v3-cluster
```

- 본문은 완전히 비어 있음(`content-length: 0`).
- `Server: TAKScoutDashboard/0.2 ...` 헤더가 **없다** — 우리 Python
  서버가 만든 응답이 아니라는 뜻이다.
- 대신 `vssaas-request-id`, `x-served-by: tunnels-prod-rel-asse-v3-cluster`
  헤더가 있다 — 이건 **GitHub Codespaces 터널/엣지 인프라 자체가
  찍는 헤더**다. 즉 이 404는 Dashboard 애플리케이션이 아니라 **터널
  레벨에서 발생**했다.

### 올바른 codespace 이름으로 같은 포트에 접속하면?

```
$ curl -s -D - -o /dev/null "https://${CODESPACE_NAME}-8000.app.github.dev/threads"
HTTP/2 302
location: https://github.dev/pf-signin?id=neat-shoe-cnrksbx&cluster=asse&name=silver-robot-xrr69q9r4r7j3pwq9&port=8000&pb=...%2Fauth%2Fpostback%2Ftunnel...
vssaas-request-id: 4c667300-a70a-4109-b263-226e69b5edf3
x-served-by: tunnels-prod-rel-asse-v3-cluster
```

→ 404가 아니라 **302로 GitHub 로그인 페이지(`pf-signin`)로
리다이렉트**된다. `curl`은 브라우저 로그인 세션이 없어서 여기서 막히지만,
실제 브라우저가 이미 해당 codespace 소유 GitHub 계정으로 로그인되어
있다면 이 리다이렉트를 자동으로 통과해 실제 Dashboard까지 도달하는 것이
정상 흐름이다(Codespaces `private` 포트의 표준 동작).

### 대조 실험: "존재하지 않는 host/port 조합은 전부 같은 404를 낸다"

```
# 오타난 이름 + 실제로 열려 있는 다른 포트(29689)
$ curl -s -D - -o /dev/null "https://silver-robot-xrr69q9r4r7j3jpwq9-29689.app.github.dev/"
HTTP/2 404   (x-served-by: tunnels-prod-rel-asse-v3-cluster, 본문 없음)

# 올바른 이름 + 한 번도 포워딩된 적 없는 포트(8001)
$ curl -s -D - -o /dev/null "https://${CODESPACE_NAME}-8001.app.github.dev/"
HTTP/2 404   (x-served-by: tunnels-prod-rel-asse-v3-cluster, 본문 없음)
```

두 경우 모두 사용자가 겪은 것과 완전히 동일한 패턴(빈 본문, 같은
`x-served-by`, `Server` 헤더 없음)의 404다. 즉 이 404는 "codespace
이름은 맞는데 그 포트가 아직 안 열렸다"거나 "우리 Flask/HTTP 서버가
route를 못 찾았다"가 아니라, **터널이 요청받은 host(codespace 이름)나
port 조합 자체를 모른다**는 뜻이다 — 사용자 URL의 codespace 이름이
실제와 다르다는 결론과 정확히 들어맞는다.

## 5. Dashboard 루트 `/`에서 실제로 생성되는 Threads 링크

```
$ curl -s http://127.0.0.1:8000/ -o /tmp/root.html
$ grep -o 'href="[^"]*threads[^"]*"' /tmp/root.html   # 결과 없음
$ grep -c "threads" /tmp/root.html                     # 0
```

**루트 화면(`/`)에는 `/threads`로 가는 링크가 전혀 없다.**
`render_candidate_list_html()`(`scripts/run_scout_dashboard.py:270-315`)을
직접 봐도 SCOUT 후보 카드와 "이 소재로 답변하기"/"원문 보기"/"관심 없음"
버튼만 만들 뿐, Threads 검수 화면으로 가는 네비게이션 자체가 코드에
없다. 다른 화면(`render_turn_html`, `render_review_html` 등)에도
`/threads`로 가는 링크는 없다.

→ 즉 사용자가 겪은 문제는 "링크의 href가 잘못 만들어져서"가 아니라,
애초에 **`/threads` URL을 직접 주소창에 입력해서 접근해야만 하는 구조**
이고(설계상 아직 그 네비게이션 UI가 없음), 이번엔 그 직접 입력한 URL의
codespace 이름 부분에 오타가 있었던 것이다.

## 6. Codespaces Port 8000의 포워딩 상태 / public URL

```
$ gh codespace ports --codespace "$CODESPACE_NAME"
  8000   private   https://silver-robot-xrr69q9r4r7j3pwq9-8000.app.github.dev
  18543  private   https://silver-robot-xrr69q9r4r7j3pwq9-18543.app.github.dev
  29602  private   https://silver-robot-xrr69q9r4r7j3pwq9-29602.app.github.dev
  ... (그 외 여러 내부 포트, 전부 private)
```

- 포트 8000은 **이미 정상적으로 포워딩되어 있다** (`private` 가시성).
- 올바른 forwarded URL은 다음과 같다:
  ```
  https://silver-robot-xrr69q9r4r7j3pwq9-8000.app.github.dev/threads
  ```
  (사용자가 쓴 URL과 비교하면 `xrr69q9r4r7j3pwq9` 부분에서 `j`가
  하나 적다 — `j3j` 아니라 `j3`.)
- `private`이므로 이 codespace 소유자로 로그인된 브라우저 세션이
  아니면 GitHub 로그인 화면을 거치게 된다(3~4번에서 확인한 302
  `pf-signin` 리다이렉트). 이건 정상 동작이며 코드/설정을 바꿀 필요는
  없다 — 사용자가 이미 로그인된 브라우저로 접근 중이라면 자동으로
  통과된다.

## 7. 가능성 구분 — 최종 판정

| 가능성 | 해당 여부 | 근거 |
|---|---|---|
| 포트 포워딩 문제 (8000이 포워딩 안 됨) | **아니다** | `gh codespace ports`에 8000이 이미 `private`로 정상 포워딩되어 있음 |
| 다른 서버/프로세스가 8000을 물고 있음 | **아니다** | `ss -ltnp`, `ps` 확인 결과 8000은 PID 11708(우리 Dashboard) 하나만 점유 |
| URL path 처리 문제 (`/threads` 라우팅 오류) | **아니다** | 같은 path `/threads`를 올바른 host로 curl하면 302(로그인 리다이렉트)까지는 정상 도달 — path 자체는 터널을 통과함 |
| Dashboard 코드의 route 문제 | **아니다** | [[5-11_phase4_2_dashboard_404_investigation]]에서 이미 로컬 200/303 확인, route 코드 3개 모두 존재 |
| bind host 문제 (127.0.0.1이라 외부 접근 불가) | **아니다** | Codespaces 터널은 컨테이너 내부 loopback 포트도 정상 중계함 — 포워딩 목록에 8000이 이미 떠 있는 것이 그 증거 |
| **URL의 codespace 이름 오타** | **그렇다 (근본 원인)** | 사용자 URL `...xrr69q9r4r7j3jpwq9...` vs 실제 `$CODESPACE_NAME` `...xrr69q9r4r7j3pwq9...` — 문자 단위 비교로 `j` 한 글자 차이 확인. 존재하지 않는 host/port 조합에 curl하면 이번 404와 완전히 동일한 패턴(빈 본문, `x-served-by: tunnels-prod-rel-asse-v3-cluster`, `Server` 헤더 없음)이 재현됨 |

## 8. 해결을 위해 코드 수정이 필요한가?

**필요 없다.** 원인이 애플리케이션 코드가 아니라 사용자가 입력한 URL의
codespace 이름 오타이므로, 코드/설정 변경 없이 **올바른 URL로 다시
접속**하면 해결된다:

```
https://silver-robot-xrr69q9r4r7j3pwq9-8000.app.github.dev/threads
```

(참고: 5번에서 확인했듯 Dashboard 루트 `/`에는 애초에 `/threads`로 가는
링크가 없어 매번 URL을 직접 입력/기억해야 하는 불편함은 있다. 이건
404의 원인은 아니지만, 필요하면 별도 지시로 네비게이션 링크 추가 여부를
판단해 달라 — 이번 조사 범위에서는 코드를 건드리지 않았다.)

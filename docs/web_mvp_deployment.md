# TAK AUTO 웹 MVP 배포 (Render)

## 배포 방식

현재 Python 표준 라이브러리 기반 통합 대시보드를 Render Web Service로 실행한다. 정적 페이지로 축소하지 않고 기존 `/trends`, `/research`, `/knowledge`, `/media`, `/operator` 흐름을 유지한다.

- 배포 설정: 저장소 루트 `render.yaml`
- 영속 데이터: Render Persistent Disk `/var/data`를 저장소 `data/`에 연결
- 로그인: `TAK_WEB_USERNAME` / `TAK_WEB_PASSWORD` Basic Authentication
- 상태 변경 POST: 동일 출처 `Origin` 검사로 CSRF 요청 차단
- 상태 확인: 인증정보가 필요 없는 최소 `/health`만 공개
- 게시: 외부 플랫폼 자동 게시를 활성화하지 않는다.

## 배포 절차

1. Render 계정에서 **New + → Blueprint**를 선택한다.
2. GitHub 저장소 `sopptak/tak-auto`를 연결한다.
3. 배포 브랜치는 `feature/perplexity-research-provider`를 선택한다. 기능 검증이 끝나기 전 main으로 병합하지 않는다.
4. Render가 `render.yaml`을 읽고 Web Service와 Persistent Disk의 예상 요금을 보여주면 확인한다. 유료 리소스 생성은 요금 확인 후 사용자가 직접 승인한다.
5. 환경변수 입력 화면에서 다음 두 값은 반드시 설정한다.
   - `TAK_WEB_USERNAME`: 추측하기 어려운 로그인 ID
   - `TAK_WEB_PASSWORD`: 충분히 길고 고유한 비밀번호
6. 선택적으로 API 키를 설정한다.
   - `TAK_SCOUT_PERPLEXITY_API_KEY`
   - `NAVER_DATALAB_CLIENT_ID`
   - `NAVER_DATALAB_CLIENT_SECRET`
   - `TAK_MEDIA_LLM_API_KEY`
   - `TAK_MEDIA_LLM_ENDPOINT`
   - `TAK_MEDIA_LLM_MODEL`
7. Deploy가 끝나면 Render가 발급한 HTTPS 주소에 접속한다. 브라우저 로그인 창에 위 사용자명과 비밀번호를 입력한다.

## 보안 및 데이터 주의

- 외부 바인딩(`0.0.0.0`)인데 로그인 환경변수가 없으면 앱은 모든 화면 요청을 거부한다( fail closed ).
- `/health`는 Render 상태 점검용으로만 공개하며 콘텐츠나 운영 데이터를 반환하지 않는다.
- 상태 변경 POST는 `Origin`이 요청 Host와 일치해야 한다. 브라우저 외부 출처에서 제출된 폼은 403으로 거부한다.
- 재시작 시 영속 디스크에 기존 SCOUT 데이터가 있으면 RSS를 다시 수집하지 않고 저장된 데이터로 대시보드를 시작한다. 최초 배포처럼 데이터가 없을 때만 RSS 수집을 수행한다.
- Basic Auth는 MVP의 단일 운영자 접근 통제다. 여러 사용자·역할·감사 로그가 필요한 운영 서비스로 확장하기 전에는 정식 계정 인증과 사용자별 권한·감사 로그를 추가해야 한다.
- 데이터는 Persistent Disk에 저장한다. 디스크가 연결되지 않거나 삭제되면 운영 기록이 보존되지 않을 수 있다. 별도 백업 정책은 후속 작업이다.
- GitHub Actions에서 생성한 `data/` 파일은 Render 디스크에 자동 동기화되지 않는다. 배포 인스턴스에서 첫 SCOUT 수집을 실행해 초기 데이터를 만든다.
- API 키는 Render 환경변수에만 저장하고 GitHub 저장소나 로그에 기록하지 않는다.
- Render Blueprint 생성은 호스팅 요금이 발생할 수 있다. 요금 화면을 확인하고 승인하기 전에는 서비스를 생성하지 않는다.

## 배포 후 확인

- `/health`: `ok` 반환
- `/trends`: RSS 트렌드 대시보드
- `/research`: 조사 결과 목록
- `/knowledge`: 사람 승인/거절
- `/media`: 콘텐츠 초안
- `/operator`: 운영 상태

배포 직후에는 트렌드 수집 완료 여부와 `/operator`의 데이터 상태를 확인한다. 첫 관측일에는 급상승 키워드가 비어 있을 수 있다.

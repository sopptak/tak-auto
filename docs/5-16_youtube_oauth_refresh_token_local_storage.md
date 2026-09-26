# 5-16. YouTube OAuth refresh_token을 터미널 대신 로컬 파일로 저장

## 배경

GitHub Codespaces에 `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET` Secret 등록을
완료한 뒤 실제 OAuth 인증(Device Authorization Grant)을 진행하려 했으나, 기존
`scripts/youtube_oauth_setup.py`는 인증 완료 후 `refresh_token`을 터미널에 1회
출력하는 방식이었다. 이 값을 Claude Code 세션을 통해 실행하면 세션 로그(대화
transcript)에도 값이 그대로 남아, "Secret 값은 절대 로그에 노출하지 않는다"는
기존 지침과 충돌한다. 사용자도 "터미널에서 Refresh Token을 복사하는 방식은
사용하기 어렵다"고 판단해, 터미널 출력 대신 로컬 파일 저장 방식으로 변경을
요청했다.

## 변경 내용

### `scripts/youtube_oauth_setup.py`

- OAuth 인증 방식(Device Authorization Grant, scope 등)은 그대로 유지했다.
- `write_refresh_token_file()` 함수를 추가했다. `refresh_token`을
  `os.open(..., O_CREAT|O_TRUNC, 0o600)`으로 생성과 동시에 소유자 전용 권한을
  부여해 저장한다(생성 후 `chmod`하는 방식은 그 사이 다른 사용자가 파일을 읽을 수
  있는 race condition이 있어 피했다). 상위 디렉터리도 `0700`으로 맞춘다.
- 기본 저장 경로는 `secrets/youtube_refresh_token.txt` (`DEFAULT_OUTPUT_PATH`
  상수), `--output`으로 변경 가능하다.
- `main()`이 인증 성공 후 더 이상 `refresh_token` 값 자체를 `print()`하지 않는다.
  대신 저장된 파일의 **경로**와 GitHub Codespaces Secrets 화면에 옮기는 절차
  안내만 출력한다.

### `.gitignore`

- `secrets/` 디렉터리 전체를 추가했다(주석으로 이유 명시: OAuth refresh_token 등
  실제 인증정보를 담는 로컬 전용 디렉터리이므로 git에 커밋하지 않음).

### `tests/test_youtube_oauth_setup.py`

기존 scope 검증 테스트(4건)는 그대로 두고 6건을 추가했다(총 10건):

- `DefaultOutputPathTests` (2건): 기본 저장 경로가 `secrets/` 하위인지,
  `.gitignore`에 `secrets/`가 실제로 등록돼 있는지.
- `WriteRefreshTokenFileTests` (2건): 저장된 파일 내용이 정확한지, 파일 권한이
  `0600`(소유자만 읽기/쓰기)인지, 재실행 시 기존 파일을 append가 아니라 덮어쓰는지.
- `MainNeverPrintsRefreshTokenTests` (1건): `main()`을 성공 경로로 실행했을 때
  `refresh_token` 값이 stdout/stderr 어디에도 출력되지 않고, 저장된 파일에만
  존재하는지 (stdout/stderr를 캡처해 값이 포함되지 않음을 직접 assert).
- `MainUsesDefaultScopeTests`: 임시 디렉터리로 `--output`을 지정하도록 수정해
  테스트 실행 중 저장소에 실제 파일을 남기지 않게 했다.

## 테스트 결과

```
$ python3 -m unittest tests.test_youtube_oauth_setup -v
Ran 10 tests in 0.007s
OK
```

전체 테스트 스위트:

```
$ python3 -m unittest discover -s tests -p 'test*.py'
Ran 513 tests in 28.620s
FAILED (failures=1)
```

실패한 테스트 1건은 이번 변경과 무관하다:

- `tests/test_upload_youtube_short_cli.py::test_live_without_credentials_fails_with_clear_configuration_error`
- 원인: 이 테스트는 `YOUTUBE_CLIENT_ID`/`YOUTUBE_CLIENT_SECRET`이 **없을 때**
  CLI가 설정 오류를 내는지 검증하는데, subprocess를 부모 프로세스 env를 물려받은
  채로 실행한다. 이번 세션에서 사용자가 실제로 이 두 Secret을 Codespaces에
  등록했기 때문에, 지금은 이 Codespace 환경 자체에 두 값이 존재해 "credentials
  없음" 전제가 깨진 것이다.
- 검증: `env -u YOUTUBE_CLIENT_ID -u YOUTUBE_CLIENT_SECRET python3 -m unittest ...`
  로 두 환경변수를 제거하고 그 테스트만 단독 실행하면 통과한다. `youtube_oauth_setup.py`
  관련 코드는 전혀 건드리지 않았으므로 이번 변경이 원인이 아니다.
- 이번 작업 범위(`scripts/youtube_oauth_setup.py` 및 그 테스트) 밖이라 수정하지
  않았다. 필요하면 `tests/test_upload_youtube_short_cli.py`의 `_run()`이 자식
  프로세스 env에서 두 변수를 명시적으로 지우도록 고치면 된다(별도 작업으로 진행 권장).

## 사용자가 해야 할 다음 작업

1. Codespace 터미널(아무 곳이나, 저와의 대화창일 필요 없음)에서 실행:
   ```bash
   python3 scripts/youtube_oauth_setup.py
   ```
2. 출력되는 URL을 열고 코드를 입력해 Google 계정으로 승인한다.
3. 인증이 끝나면 값 자체는 화면에 출력되지 않고, 아래 파일에 저장된다:
   `secrets/youtube_refresh_token.txt` (저장소 루트 기준, 소유자 전용 권한).
4. VS Code 탐색기에서 `secrets/` 폴더를 열거나 `code secrets/youtube_refresh_token.txt`
   로 파일을 열어 값을 확인한다. (`secrets/`는 `.gitignore` 대상이라 커밋되지 않는다.)
5. GitHub 저장소 **Settings → Secrets and variables → Codespaces** 화면에서
   `YOUTUBE_REFRESH_TOKEN` Secret 값으로 그 값을 직접 붙여넣는다.
6. 값을 옮긴 뒤에는 `secrets/youtube_refresh_token.txt`를 삭제해 로컬 사본을
   남기지 않는 것을 권장한다.
7. 이번 세션에서는 실제 YouTube 업로드를 진행하지 않았다 - Secret 등록 확인 후
   다음 단계로 진행하면 된다.

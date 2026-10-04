# 5-14. YouTube OAuth scope 수정 (Device Authorization Grant 허용 목록 위반 수정)

## 문제

Device Authorization Grant(TVs and Limited Input devices) 흐름에서 Google이
문서화한 허용 YouTube scope는 다음 둘뿐이다.

- `https://www.googleapis.com/auth/youtube`
- `https://www.googleapis.com/auth/youtube.readonly`

`https://www.googleapis.com/auth/youtube.upload`는 이 목록에 없다. 그런데
`scripts/youtube_oauth_setup.py`의 `DEFAULT_SCOPE`가 `youtube.upload`를 요청하도록
구현되어 있었다.

## 원인 조사

`youtube.upload` 문자열을 저장소 전체에서 검색해 이 값을 참조하는 곳이
`scripts/youtube_oauth_setup.py`의 `DEFAULT_SCOPE` 상수 단 한 곳뿐임을 확인했다.
`content_engine/youtube_publisher.py`(업로드 클라이언트)는 scope를 전혀 다루지
않는다 - access_token이 이미 발급 시점에 부여된 scope를 담고 있으므로, 업로드/토큰
갱신 코드에는 scope 관련 로직이 없다. 따라서 수정 지점은 단 하나였고, 다른 곳에
`youtube.upload`를 추가하는 우회는 필요하지도, 발생하지도 않았다.

## 수정 파일

- `scripts/youtube_oauth_setup.py`
  - `DEFAULT_SCOPE`를 `https://www.googleapis.com/auth/youtube.upload` →
    `https://www.googleapis.com/auth/youtube`로 변경.
  - 왜 이 값을 쓰는지(Device Flow 허용 scope 제약, `videos.insert`가 전체 `youtube`
    scope로도 정상 동작함) 주석으로 명시.
- `docs/5-13_youtube_shorts_upload.md`
  - OAuth 동의 화면에 추가할 스코프 안내를 `youtube.upload` → `youtube`로 수정하고,
    이 문서(5-14)를 가리키는 주석 추가.
- `tests/test_youtube_oauth_setup.py` (신규)
  - `DEFAULT_SCOPE`가 정확히 `https://www.googleapis.com/auth/youtube`인지
  - `youtube.upload` 문자열을 포함하지 않는지
  - `request_device_code()`가 실제 HTTP 요청 바디에 `scope=https://www.googleapis.com/auth/youtube`를
    담아 보내는지 (urlopen 모킹, 실제 네트워크 호출 없음)
  - `main()`이 `--scope`를 지정하지 않았을 때도 `DEFAULT_SCOPE`를 그대로
    `request_device_code()`에 전달하는지

  총 5건의 테스트를 추가했다.

`content_engine/youtube_publisher.py`, `content_engine/youtube_upload_history.py`,
`scripts/upload_youtube_short.py`는 scope와 무관하므로 수정하지 않았다. TAK BRAIN,
TAK MEDIA, Threads 관련 파일도 전혀 건드리지 않았다.

## 업로드 기능이 새 scope로 정상 동작하는가

YouTube Data API v3의 `videos.insert`(업로드) 메서드가 요구하는 인가 scope 목록에는
`youtube.upload`뿐 아니라 상위 scope인 `youtube`(전체 읽기/쓰기 권한)도 포함된다.
즉 `youtube` scope로 발급받은 access_token은 업로드 권한을 포함하므로,
`content_engine/youtube_publisher.py`의 업로드 로직(resumable upload 요청 구성,
access_token 헤더 부착 등)은 코드 변경 없이 그대로 동작한다. 이는 access_token을
발급하는 `youtube_oauth_setup.py`와 그 access_token을 소비하는
`youtube_publisher.py`가 서로 독립적으로 설계되어 있어(access_token은 단순
Bearer 토큰 문자열로만 전달됨) 가능하다.

## 테스트 결과

```
$ python3 -m unittest discover -s tests -p 'test*.py'
Ran 487 tests in 28.1s

OK
```

기존 482건 + 신규 scope 검증 5건 = 487건 전체 통과. 실제 YouTube API/OAuth 서버
호출은 이번에도 전혀 발생하지 않았다(모두 urlopen 모킹).

## 실제 인증 전에 사용자가 해야 할 작업

1. Google Cloud Console의 OAuth 동의 화면에서 스코프가 `youtube.upload`로 등록되어
   있었다면 `youtube`(전체)로 다시 확인/추가한다. (아직 OAuth 클라이언트를 만들지
   않았다면 처음부터 `youtube` scope로 설정하면 된다 - `docs/5-13_youtube_shorts_upload.md`
   3-1 참고.)
2. 만약 이전에 `scripts/youtube_oauth_setup.py`를 이미 실행해 `youtube.upload` scope로
   refresh_token을 발급받은 적이 있다면, 그 토큰은 Device Flow 정책상 애초에
   발급되지 않았거나 향후 무효화될 수 있으므로 폐기하고 **다시 발급**받아야 한다.
   `scripts/youtube_oauth_setup.py`를 다시 실행하면 이번에는 자동으로 `youtube` scope로
   요청한다 (별도 옵션 지정 불필요).
3. 발급받은 새 `YOUTUBE_REFRESH_TOKEN` 값을 기존에 저장해둔 GitHub Secret/로컬
   `.env`가 있다면 새 값으로 교체한다.
4. 이번 세션에서도 실제 YouTube 업로드/실제 OAuth 인증은 수행하지 않았다 - 다음
   단계에서 위 재인증을 완료한 뒤 실제 private 업로드 테스트를 진행하면 된다.

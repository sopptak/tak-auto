# 네이버 RSS 검증 기록

2026-09-10에 `https://rss.blog.naver.com/tmong2.xml`을 공개 HTTPS 요청으로 확인했습니다. 로그인, CAPTCHA, 접근 제한 우회는 사용하지 않았습니다.

## 확인 결과

- RSS HTTP 응답: `200 OK`
- RSS XML item 수: `50`
- `--limit 10` 결과: 게시물 10개
- 확인 가능한 필드: 제목, `pubDate`, `link`, `guid`, category, tag, description
- RSS 본문 전체 여부: 첫 10개 중 2개만 절단 표식이 없었고, 8개는 `.......`로 끝났습니다. 따라서 RSS description을 전체 본문으로 간주하지 않습니다.
- 개인정보 위험: 현재 위험 탐지 규칙 기준 0건
- 내부정보 위험: 현재 위험 탐지 규칙 기준 0건

개별 게시물 URL도 하나를 HTTPS로 요청했을 때 `200 OK`였지만, 응답은 본문이 들어 있는 문서가 아니라 `PostView.naver`를 가리키는 iframe 프레임셋이었습니다. 이 프로젝트는 그 iframe이나 다른 엔드포인트를 따라가 본문을 우회 수집하지 않습니다.

## 운영 원칙

RSS 어댑터는 RSS에서 실제로 확보한 description만 RAW `body`로 연결하고 `body_is_complete`를 별도로 표시합니다. 전체 원문이 필요하면 사용자가 직접 확보한 Markdown/JSON 파일을 `input/`에 넣어야 합니다.
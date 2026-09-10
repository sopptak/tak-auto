# 네이버 공개 게시물 본문 검증 기록

2026-09-10에 RSS에서 확인한 다음 공개 게시물 하나를 대상으로 일반 HTTP 요청을 실행했습니다.

`https://blog.naver.com/tmong2/224407187378`

## 결과

- 게시물 페이지 HTTP 상태: `200`
- 게시물 페이지 HTML: 확보 가능
- 첫 응답: `mainFrame` iframe을 포함한 프레임셋
- 공개 iframe HTTP 상태: `200`
- 실제 본문 영역: `se-main-container` 식별 가능
- 제목: HTML에서 추출 가능
- 게시일: `se_publishDate`에서 `1시간 전` 표지 추출 가능
- 본문 텍스트: 추출 가능, 공백 정제 후 1,931자
- 본문 원문: 터미널 출력 및 Git commit에서 제외

게시일은 개별 HTML에서 상대값으로 노출되므로 정확한 절대 게시일은 RSS의 `pubDate`를 사용해야 합니다. 개별 HTML은 일반 HTTP 요청으로 접근 가능한 공개 iframe을 사용했으며 로그인, CAPTCHA, robots.txt, 접근 제한 우회는 하지 않았습니다.

## 구현 범위

`blog_importer/naver_post.py`와 `scripts/check_naver_post.py`는 공개 HTML의 구조를 점검하는 프로토타입입니다. `se-main-container` 안의 텍스트를 정제할 수 있지만, 현재는 TAK BRAIN RAW 저장이나 KNOWLEDGE 생성을 수행하지 않습니다.

본문 추출은 자동화할 수 있으나 네이버 HTML class와 iframe 구조에 의존하므로 변경에 취약합니다. 다음 단계에서 RSS의 절대 날짜, 공개 HTML의 본문, 사용자가 확보한 원문을 어떤 우선순위로 RAW에 기록할지 정책을 먼저 정해야 합니다.
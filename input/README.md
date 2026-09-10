# TAK BRAIN 입력 폴더

사용자가 보관 중인 블로그 글을 이 폴더에 **복사해서** 넣습니다. import 도구는 이 폴더의 원본 파일을 읽기만 하며 수정하거나 삭제하지 않습니다.

## 글 하나 추가하기

1. 아래 JSON 또는 Markdown 예시 중 하나를 복사합니다.
2. 실제 글의 제목, 작성일, 본문, 태그, 원본 URL을 채웁니다.
3. 파일을 `input/` 아래에 저장합니다. 파일 하나가 글 하나입니다.
4. 프로젝트 루트에서 `python3 scripts/import_posts.py`를 실행합니다.
5. 화면의 위험 수를 확인하고, RAW 출력은 사람이 검토한 뒤 사용합니다.

JSON 예시:

```json
{
  "id": "my-post-001",
  "title": "글 제목",
  "published_at": "2024-01-01",
  "body": "블로그 원문 전체",
  "tags": ["기록"],
  "source_url": "https://blog.naver.com/example/1",
  "source": "manual_naver_export"
}
```

Markdown 예시:

```markdown
---
id: my-post-002
title: 글 제목
published_at: 2024-01-02
tags: [기록]
source_url: https://blog.naver.com/example/2
source: manual_naver_export
---
블로그 원문 전체
```

`id`, `title`, `published_at`, `body`, `source_url`, `source`는 필수입니다. `tags`와 `collected_at`은 생략할 수 있습니다. `collected_at`은 import 시각으로 생성되고 `content_hash`는 자동 생성됩니다.

입력 파일에는 주민등록번호, 연락처, 이메일, 기관 내부정보 등이 포함될 수 있으므로 import 결과의 위험 수를 반드시 확인합니다. 네이버 로그인, CAPTCHA, 접근 제한 우회와 무단 크롤링은 사용하지 않습니다.
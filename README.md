# 탁자동 (TAK AUTO)

> 탁멍이가 결정하면, AI가 실행한다.

이번 단계는 2003년부터 축적한 네이버 블로그 글을 TAK BRAIN의 원천 데이터로 넣기 위한 작은 Python MVP입니다. 네이버 로그인, 크롤링, 게시 자동화는 포함하지 않습니다. JSON 또는 Markdown 파일 10~20개를 수동으로 넣고 데이터 경계를 검증하는 데 초점을 둡니다.

## 설치

Python 3.11 이상을 권장합니다. 현재 구현은 표준 라이브러리만 사용하므로 별도 패키지 설치가 필요하지 않습니다.

```bash
git clone https://github.com/sopptak/tak-auto.git
cd tak-auto
```

## 실행

샘플 파일을 RAW 표준 모델로 읽고 content hash로 중복 제거합니다.

```bash
python3 - <<'PY'
from blog_importer import import_files
from tak_brain import BrainRepository

result = import_files(["tests/fixtures/sample_posts"])
brain = BrainRepository()
brain.add_many(list(result.posts))
print(f"imported={len(brain.all())}, duplicates={result.duplicate_count}")
PY
```

현재 저장소는 MVP용 메모리 저장소입니다. 프로세스가 종료되면 저장 내용은 사라지며, 파일 import 결과의 표준화와 검증을 먼저 안정화하는 단계입니다.

## 폴더 구조

```text
blog_importer/                 JSON/Markdown 로더와 원본 모델
tak_brain/                     RAW 저장소와 분리된 KNOWLEDGE 모델
content_engine/                향후 AI 분석 엔진 자리
tak_scout/                     향후 공개 자료 탐색 자리
operator/                      향후 운영 명령 자리
tests/fixtures/sample_posts/   검증용 샘플 3개
tests/test_mvp.py              자동 테스트
```

`operator/`는 Python 표준 라이브러리의 `operator`와 이름이 충돌하므로 현재 패키지 초기화 파일을 두지 않습니다.

## 데이터 구조

입력 원본은 다음 필드를 사용합니다.

`id`, `title`, `published_at`, `body`, `tags`, `source_url`, `source`, `collected_at`, `content_hash`

`collected_at`이 없으면 import 시 UTC 시각을 만들고, `content_hash`가 없으면 제목·작성일·본문·태그·출처 URL·출처를 정규화해 SHA-256을 생성합니다. 같은 hash는 한 번만 저장합니다.

TAK BRAIN에서는 원본을 `RawContent`로 그대로 보존하고, AI 분석 결과는 별도 `KnowledgeRecord`에 둡니다. 분석 결과가 아직 없을 때는 `knowledge=None`입니다. 자동 생성되는 metadata에는 `verification_required`, `privacy_risk`, `internal_information_risk`가 포함됩니다.

지원 category는 금융, 대출, 경매, 부동산, 인간관계, 심리, 자기계발, 독서, 건강, 가족, 골프, 기타이며, knowledge_type은 경험, 사례, 판단기준, 정보, 의견입니다.

## 샘플 데이터 넣기

JSON은 객체 하나 또는 객체 배열을 지원합니다.

```json
{
	"id": "post-001",
	"title": "제목",
	"published_at": "2024-01-01",
	"body": "원문",
	"tags": ["금융"],
	"source_url": "https://example.com/post-001",
	"source": "manual_naver_export"
}
```

Markdown은 파일 시작과 끝에 `---`를 둔 간단한 `key: value` front matter를 사용하고, 그 아래에 원문을 둡니다. `tags`는 `[금융, 경험]` 형식입니다. 파일 또는 디렉터리를 `import_files([...])`에 전달하면 됩니다.

## 테스트

```bash
python3 -m unittest discover -s tests -p 'test*.py' -v
```

테스트는 정상 import, 필수 필드, hash 생성과 중복 방지, 원본 보존, metadata 생성, 개인정보 위험, 금융기관 내부정보 위험을 확인합니다.

## 향후 네이버 입력 어댑터

향후 어댑터는 네이버에서 합법적으로 확보한 export 또는 사용자가 제공한 파일을 읽어 `BlogPost.from_mapping()`에 전달하면 됩니다. 새 어댑터도 기존 파일 로더와 동일하게 필수 필드를 채우고 원문을 수정하지 않아야 합니다.

다음 동작은 구현하지 않습니다.

- 네이버 로그인, CAPTCHA, 접근 제한 우회
- 개인정보 자동 공개
- 금융기관 내부정보 자동 공개
- 자동 SNS 게시

위험 플래그가 있는 콘텐츠는 사람이 검토하기 전 외부에 공개하지 않는 것을 기본 원칙으로 합니다.

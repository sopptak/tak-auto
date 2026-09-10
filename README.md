# 탁자동 (TAK AUTO)

> 탁멍이가 결정하면, AI가 실행한다.

현재 프로젝트는 2003년부터 축적한 네이버 블로그 글을 TAK BRAIN의 원천 데이터로 넣는 파일럿 환경입니다. 네이버 로그인, 크롤링, 게시 자동화는 포함하지 않습니다. 사용자가 글 10개를 JSON 또는 Markdown 파일로 `input/`에 넣고 데이터 경계를 검증하는 데 초점을 둡니다.

## 설치

Python 3.11 이상을 권장합니다. 현재 구현은 표준 라이브러리만 사용하므로 별도 패키지 설치가 필요하지 않습니다.

```bash
git clone https://github.com/sopptak/tak-auto.git
cd tak-auto
```

## 실행

실제 글 파일을 `input/`에 복사한 뒤 아래 명령 하나를 실행합니다.

```bash
python3 scripts/import_posts.py
```

결과에는 총 글 수, 신규 글 수, 중복 글 수, 검증 오류 수, 개인정보 위험 수, 내부정보 위험 수가 표시됩니다. 표준 RAW와 metadata는 `data/tak_brain_raw.json`에 누적 저장되며, `data/` 출력 파일은 입력 원본과 별개입니다.

입력 폴더 사용법과 JSON/Markdown 템플릿은 [input/README.md](input/README.md)에 있습니다. 입력 파일은 import 과정에서 읽기만 하며 수정하거나 삭제하지 않습니다.

실제 글은 글 하나당 파일 하나로 저장하고, 파일명은 `YYYYMMDD-간단한-slug-고유id.json` 또는 `.md` 규칙을 사용합니다. 10개를 넣은 뒤 첫 실행에서 `전체 10`, `신규 10`인지 확인하고, 같은 명령을 다시 실행했을 때 `중복 10`인지 확인합니다. 현재 `input/`에는 실제 글이 제공되지 않았으므로 예시 원문을 넣지 않았습니다.

## 폴더 구조

```text
blog_importer/                 JSON/Markdown 로더와 원본 모델
tak_brain/                     RAW 저장소와 분리된 KNOWLEDGE 모델
scripts/import_posts.py        입력 폴더 일괄 import CLI
scripts/import_naver_rss.py    네이버 RSS 공개 정보 점검 CLI
input/                         사용자가 넣는 원본 JSON/Markdown
data/                          누적 RAW 출력 위치(자동 생성, Git 제외)
content_engine/                향후 AI 분석 엔진 자리
tak_scout/                     향후 공개 자료 탐색 자리
operator/                      향후 운영 명령 자리
tests/fixtures/sample_posts/   기존 검증용 샘플 3개
tests/test_import_pilot.py     파일럿 테스트 4개
tests/test_mvp.py              MVP 회귀 테스트 4개
```

`operator/`는 Python 표준 라이브러리의 `operator`와 이름이 충돌하므로 현재 패키지 초기화 파일을 두지 않습니다.

## 데이터 구조

입력 원본은 다음 필드를 사용합니다.

`id`, `title`, `published_at`, `body`, `tags`, `source_url`, `source`, `collected_at`, `content_hash`

`collected_at`이 없으면 import 시 UTC 시각을 만들고, `content_hash`가 없으면 제목·작성일·본문·태그·출처 URL·출처를 정규화해 SHA-256을 생성합니다. 같은 hash는 한 번만 저장합니다.

TAK BRAIN에서는 원본을 `RawContent`로 그대로 보존하고, AI 분석 결과는 별도 `KnowledgeRecord`에 둡니다. 분석 결과가 아직 없을 때는 `knowledge=None`입니다. 자동 생성되는 metadata에는 `verification_required`, `privacy_risk`, `internal_information_risk`가 포함됩니다.

지원 category는 금융, 대출, 경매, 부동산, 인간관계, 심리, 자기계발, 독서, 건강, 가족, 골프, 기타이며, knowledge_type은 경험, 사례, 판단기준, 정보, 의견입니다.

## 샘플 데이터 넣기

실제 파일은 `input/`에 글 하나당 하나씩 저장하는 방식을 권장합니다. JSON은 객체 하나 또는 객체 배열을 지원합니다.

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

`id`, `title`, `published_at`, `body`, `source_url`, `source`는 필수입니다. `body`가 비어 있거나 공백뿐인 파일, JSON이 깨진 파일은 검증 오류로 집계하고 다른 파일은 계속 처리합니다. `collected_at`은 생략하면 import 시각으로 생성되고 `content_hash`는 자동 생성됩니다.

## 테스트

```bash
python3 -m unittest discover -s tests -p 'test*.py' -v
```

테스트는 정상 import, 필수 필드, hash 생성과 중복 방지, 원본 보존, metadata 생성, 개인정보 위험, 금융기관 내부정보 위험과 함께 10개 파일 import, 반복 import, 잘못된 파일, 빈 본문을 확인합니다.

## 향후 네이버 입력 어댑터

향후 어댑터는 네이버에서 합법적으로 확보한 export 또는 사용자가 제공한 파일을 읽어 `BlogPost.from_mapping()`에 전달하면 됩니다. 새 어댑터도 기존 파일 로더와 동일하게 필수 필드를 채우고 원문을 수정하지 않아야 합니다.

다음 동작은 구현하지 않습니다.

- 네이버 로그인, CAPTCHA, 접근 제한 우회
- 개인정보 자동 공개
- 금융기관 내부정보 자동 공개
- 자동 SNS 게시

위험 플래그가 있는 콘텐츠는 사람이 검토하기 전 외부에 공개하지 않는 것을 기본 원칙으로 합니다.

## 네이버 RSS 점검

네이버가 제공하는 RSS만 먼저 확인하려면 다음 명령을 사용합니다. 기본값은 최대 10개이며, RSS에서 확보한 제목·날짜·URL·description과 위험 플래그를 출력합니다.

```bash
python3 scripts/import_naver_rss.py --url https://rss.blog.naver.com/tmong2.xml --limit 10
```

RSS description은 전체 본문이 아닐 수 있으므로 자동으로 본문 전체라고 간주하거나 개별 페이지를 우회 수집하지 않습니다. 실제 전체 원문이 필요하면 사용자가 확보한 Markdown/JSON을 `input/`에 넣습니다. 실제 확인 결과는 [docs/naver_rss_verification.md](docs/naver_rss_verification.md)에 기록되어 있습니다.

## 3단계 이후 설계

RAW 원본을 검토한 뒤의 지식 추출 설계는 [docs/knowledge_extraction_design.md](docs/knowledge_extraction_design.md)에 정리했습니다. 이 단계에서는 AI API를 연결하지 않고 데이터 구조와 원본-지식 연결 관계만 검증합니다.

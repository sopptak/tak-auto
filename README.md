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
tak_brain/article_types.py     제목·본문 기반 글 유형 분류기
tak_brain/knowledge_transformers.py 유형별 근거 기반 KNOWLEDGE 변환기
scripts/import_posts.py        입력 폴더 일괄 import CLI
scripts/import_naver_rss.py    네이버 RSS 공개 정보 점검 CLI
scripts/check_naver_post.py    공개 게시물 본문 영역 점검 CLI
scripts/collect_naver_raw.py   RSS 메타데이터와 공개 본문 RAW 수집 CLI
scripts/create_knowledge.py    RAW 한 건을 KNOWLEDGE 초안으로 변환하는 CLI
scripts/generate_knowledge.py  RAW 전체를 중복 방지하며 KNOWLEDGE 초안으로 변환하는 CLI
scripts/review_knowledge.py    KNOWLEDGE review 상태 조회·저장 CLI
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

`id`, `title`, `published_at`, `body`, `tags`, `source_url`, `source`, `collected_at`, `content_hash`, `extraction_method`, `extraction_status`

`collected_at`이 없으면 import 시 UTC 시각을 만들고, `content_hash`가 없으면 제목·작성일·본문·태그·출처 URL·출처를 정규화해 SHA-256을 생성합니다. 같은 hash 또는 같은 `source_url`은 한 번만 저장합니다. `extraction_method`는 `naver_public_html`, `naver_rss_description` 등을, `extraction_status`는 `full`, `partial`, `failed`를 기록합니다.

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

## 네이버 RSS와 공개 본문 RAW 수집

네이버 RSS 메타데이터와 공개 게시물 본문을 결합해 로컬 RAW에 저장하려면 다음 명령을 사용합니다. 기본값은 `tmong2` RSS의 최대 10개이며 본문 원문은 터미널에 출력하지 않습니다.

```bash
python3 scripts/collect_naver_raw.py --url https://rss.blog.naver.com/tmong2.xml --limit 10
```

수집 순서는 RSS `pubDate`, `title`, item URL을 기준 메타데이터로 고정한 뒤 공개 HTML 본문을 시도하는 방식입니다. RSS 날짜가 게시일 1순위이고 HTML 날짜는 보조값이며, `1시간 전` 같은 상대값은 저장하지 않습니다. HTML 본문 성공 시 `naver_public_html/full`, 실패 시 RSS description을 `naver_rss_description/partial`로 저장합니다. 위험 검사는 개인정보·연락처·이메일·계좌번호·고객 식별 정보·내부정보를 대상으로 하며, 위험 RAW를 삭제하지 않고 metadata에 flag를 기록합니다.

RAW 파일은 기본적으로 `data/tak_brain_raw.json`에 저장되며 `.gitignore`로 Git에서 제외됩니다. 실제 네이버 원문과 RAW는 GitHub에 commit하지 않고, 코드·테스트·문서만 commit합니다. 이 단계에서는 KNOWLEDGE 자동 생성을 수행하지 않습니다.

## 첫 KNOWLEDGE 변환

규칙 기반 변환기로 RAW 한 건을 KNOWLEDGE 초안으로 만들 수 있습니다. 외부 AI API는 사용하지 않으며, 원문 근거는 `evidence`, 규칙 기반 일반화는 `derived_insight`로 분리하고 `inference_method`에 `rule_based_template`을 기록합니다. 실제 LLM 연결 시 `ai_inference`를 별도 필드로 추가할 수 있습니다.

```bash
python3 scripts/create_knowledge.py \
	--source-url "https://blog.naver.com/tmong2/224407187378?fromRss=true&trackingCode=rss"
```

KNOWLEDGE는 `id`, `source_raw_id`, `source_url`, `title`, `domain`, `knowledge_type`, `experience`, `problem`, `action`, `decision`, `result`, `lesson`, `reusable_principle`, `evidence`, `derived_insight`, `inference_method`, `confidence`, `created_at`을 가집니다. 현재 규칙 기반 변환에서는 근거 없는 `confidence`를 저장하지 않습니다. 자동 생성 직후 `knowledge_review_status`는 `pending`입니다. `approved`만 이후 콘텐츠 생성 대상이며 `pending`과 `rejected`는 제외합니다. 실제 KNOWLEDGE 파일도 `data/` 아래에 저장되어 GitHub에 commit하지 않습니다.

RAW에서 KNOWLEDGE를 만들 때는 `ArticleTypeClassifier`가 제목과 본문을 함께 확인해 `experience`, `finance`, `workplace`, `ai_business`, `book_philosophy`, `general` 중 하나를 선택합니다. 유형별 transformer는 근거가 없는 필드를 `null`로 두며, 기존 앱 제작용 규칙을 다른 글에 적용하지 않습니다.

실제 RAW 전체를 재수집하지 않고 KNOWLEDGE 초안으로 누적하려면 다음 명령을 사용합니다. 이미 같은 `source_raw_id`가 있으면 건너뛰고, 기존 approved 레코드는 변경하지 않습니다.

```bash
python3 scripts/generate_knowledge.py
```

KNOWLEDGE review 상태는 로컬 JSON에 영속화할 수 있습니다.

```bash
python3 scripts/review_knowledge.py --pending
python3 scripts/review_knowledge.py --show knowledge-da6ddf5aa459
python3 scripts/review_knowledge.py --report
python3 scripts/review_knowledge.py --id knowledge-da6ddf5aa459 --approve
python3 scripts/review_knowledge.py --id knowledge-da6ddf5aa459 --reject --note "검토 결과 승인하지 않음"
```

review 변경은 `knowledge_review_status`, `reviewed_at`, 선택적 `review_note`만 갱신하며, `source_raw_id`와 `source_url` 및 나머지 KNOWLEDGE 필드는 보존합니다.

`--pending`은 pending 레코드의 상세 필드와 자동 품질 판정(A/B/C)을 보여주고, `--report`는 제목·유형·도메인·품질·핵심 판단·주의사항·승인 권고를 요약합니다. 승인 권고는 사람 검토를 돕기 위한 표시일 뿐 review 상태를 변경하지 않습니다.

RSS 메타데이터만 확인하려면 다음 명령을 사용합니다.

```bash
python3 scripts/import_naver_rss.py --url https://rss.blog.naver.com/tmong2.xml --limit 10
```

RSS에서 얻은 공개 게시물 하나의 HTML 구조만 점검하려면 다음 명령을 사용합니다. 페이지와 응답에 명시된 공개 iframe을 일반 HTTP로 요청하고 `se-main-container` 텍스트의 존재와 길이만 출력하며, 본문 원문은 출력하지 않습니다.

```bash
python3 scripts/check_naver_post.py --url "https://blog.naver.com/tmong2/224407187378"
```

실제 게시물 점검 결과는 [docs/naver_post_verification.md](docs/naver_post_verification.md)에 기록되어 있습니다. 이 프로토타입은 RAW 저장이나 KNOWLEDGE 생성을 수행하지 않습니다.

## 3단계 이후 설계

RAW 원본을 검토한 뒤의 지식 추출 설계는 [docs/knowledge_extraction_design.md](docs/knowledge_extraction_design.md)에 정리했습니다. 이 단계에서는 AI API를 연결하지 않고 데이터 구조와 원본-지식 연결 관계만 검증합니다.

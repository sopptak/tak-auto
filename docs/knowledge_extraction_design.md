# TAK BRAIN 지식 추출 설계

이 문서는 실제 글 10개의 RAW 보존과 품질 검증이 끝난 뒤 적용할 다음 단계의 데이터 구조입니다. 현재 단계에서는 AI API나 자동 분석을 연결하지 않습니다.

## RAW와 KNOWLEDGE의 경계

하나의 `BrainRecord`는 `raw`와 `knowledge`를 별도 객체로 가집니다.

```text
BrainRecord
├── raw          사용자가 제공한 원문과 출처. 수정 금지.
├── metadata     hash, 수집일, 위험 플래그 등 시스템 메타데이터
└── knowledge    사람이 승인하거나 추출한 지식. 없을 수 있음.
```

RAW의 `id`, `source_url`, `published_at`, `body`, `tags`, `source`, `collected_at`, `content_hash`는 원본 입력 그대로 보존합니다. 요약문이나 분류값으로 RAW를 덮어쓰지 않습니다.

## KNOWLEDGE 필드

첫 변환 단계의 대표 레코드는 다음 필드를 사용합니다.

| 필드 | 내용 |
| --- | --- |
| `id` | KNOWLEDGE 식별자 |
| `source_raw_id` | 원본 RAW의 id |
| `source_url` | 원본 게시물 URL |
| `title` | RSS에서 보존한 제목 |
| `domain` | 기존 category 체계의 도메인 |
| `knowledge_type` | 경험, 사례, 판단기준, 정보, 의견 |
| `experience` ~ `reusable_principle` | 구조화된 경험·문제·행동·결과·교훈·재사용 원칙 |
| `evidence` | 원문에서 확인한 근거 목록 |
| `derived_insight` | 원문에서 직접 확인되지 않고 규칙 기반 템플릿이 도출한 정리·일반화 |
| `inference_method` | 도출 방식. 현재는 `rule_based_template` |
| `confidence` | 향후 근거와 영향 필드를 설계한 뒤 도입. 현재 규칙 기반 변환에서는 저장하지 않음 |
| `created_at` | KNOWLEDGE 생성 시각 |
| `knowledge_review_status` | `pending`, `approved`, `rejected` |

| 필드 | 내용 |
| --- | --- |
| `category` | 금융, 대출, 경매, 부동산, 인간관계, 심리, 자기계발, 독서, 건강, 가족, 골프, 기타 |
| `knowledge_type` | 경험, 사례, 판단기준, 정보, 의견 |
| `summary` | 원문과 분리된 짧은 요약 |
| `key_points` | 핵심 주장 또는 관찰 목록 |
| `experience` | 작성자의 경험으로 추출된 내용 |
| `case` | 특정 사례로 추출된 내용 |
| `judgment_rule` | 반복 적용 가능한 판단 기준 |
| `opinion` | 사실과 구분된 의견 |
| `factual_information` | 별도 확인이 필요한 사실 정보 |
| `current_validity` | 현재도 유효함, 일부 유효, 확인 필요, 유효하지 않음 |
| `verification_required` | 사람의 사실 확인이 필요한지 여부 |
| `privacy_risk` | 개인정보 포함 또는 재식별 위험 |
| `internal_information_risk` | 금융기관 등 내부정보 위험 |

`knowledge_type`은 글 전체에 하나만 강제하지 않고, 필요하면 key point 단위로 근거와 함께 여러 유형을 기록할 수 있습니다. 다만 초기 검증에서는 대표 유형 하나와 근거 문장을 함께 저장합니다.

현재 규칙 기반 변환기는 대표 KNOWLEDGE 하나만 생성합니다. 자동 생성 결과는 항상 `pending`이며, `select_approved()`가 `approved`만 후속 콘텐츠 생성 대상으로 선택합니다. 외부 AI API 연결은 이 인터페이스 뒤에 별도 구현합니다.

review 상태는 로컬 KNOWLEDGE JSON에서 `review_knowledge.py`로 영속화합니다. 상태 변경 시 `knowledge_review_status`, `reviewed_at`, 선택적 `review_note`만 갱신하고, RAW 연결 필드와 분석 내용은 보존합니다.

## RAW → KNOWLEDGE 변환 흐름

1. RAW의 `content_hash`로 원본을 고정합니다.
2. `ArticleTypeClassifier`가 제목과 본문 근거를 함께 읽어 글 유형을 분류합니다.
3. 유형별 transformer가 경험·금융·직장·AI 사업·독서·일반 글에 맞는 필드만 채웁니다.
4. 본문에 근거가 없는 필드는 `null`로 둡니다.
5. `evidence`가 실제 근거를 가리키는지 공통 validation으로 확인합니다.
6. 개인정보 및 내부정보 위험도를 다시 판정합니다.
7. 사람이 결과를 검토한 뒤 KNOWLEDGE를 저장합니다.

현재 유형은 `experience`, `finance`, `workplace`, `ai_business`, `book_philosophy`, `general`입니다. 확신이 낮으면 `general`로 분류하며, 원문에 없는 사실을 유형별 transformer가 보완하지 않습니다.

`scripts/generate_knowledge.py`는 저장된 RAW를 재수집하지 않고 순회합니다. 기존 `source_raw_id`가 있는 KNOWLEDGE는 건너뛰며, 새 레코드는 `pending`으로 생성합니다. 후속 콘텐츠 생성에는 `select_approved()`가 반환한 승인 레코드만 사용합니다.

사람 검토는 `scripts/review_knowledge.py --pending` 또는 `--report`로 수행합니다. 두 명령은 저장된 KNOWLEDGE를 읽기만 하며, A/B/C 품질과 승인 권고를 표시해도 `knowledge_review_status`를 자동 변경하지 않습니다.

## 원본과 추출 지식의 연결

KNOWLEDGE 레코드는 다음 연결값을 필수로 가집니다.

```text
raw_id            원본 BlogPost.id
raw_content_hash  원본 본문 기준 SHA-256
source_url        원본 URL의 복사본
source_span       근거가 된 원문 문장/단락 위치
extraction_status 초안, 검토 필요, 승인, 반려
```

`raw_content_hash`가 바뀌면 기존 KNOWLEDGE를 자동으로 최신이라고 간주하지 않습니다. 원본 버전을 새로 저장하고 지식 재검토 대상으로 표시합니다.

## 안전 원칙

- AI API는 승인된 범위와 비식별화 정책이 정해진 뒤 연결합니다.
- 위험 플래그가 있으면 외부 공개나 자동 게시를 하지 않습니다.
- 현재 유효성은 금융·법률·건강처럼 변할 수 있는 정보에서 기본적으로 `확인 필요`로 시작합니다.
- 원본 URL과 작성일은 분석 결과가 없어도 항상 보존합니다.
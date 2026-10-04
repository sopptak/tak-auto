# TAK AUTO 5-2차: 수익화 전환 분석 및 로드맵 설계

---

## [1] TAK AUTO 현재 전체 구조

```
input/ (원문 JSON/MD)
  → blog_importer/ (RAW 표준화·로드)
    → tak_brain/ (RAW→KNOWLEDGE 규칙기반 변환, 승인 워크플로우)
      → content_engine/ (KNOWLEDGE→Blog/Shorts/Threads Draft 생성 + LLM 재작성 + 검증)
        → scripts/publish_threads.py (Threads 자동 선택·게시·이력)
          → .github/workflows/daily-threads-post.yml (스케줄 실행)

tak_scout/   → __init__.py 한 줄, "향후 공개 자료 탐색 자리" 주석뿐. 코드 없음 (순수 placeholder)
operator/    → README.md 한 줄, "향후 운영 명령/사람 승인 흐름 자리" 주석뿐. 코드 없음 (순수 placeholder)
```

- **실제 구현됨**: `blog_importer`, `tak_brain`(RAW 저장·분류·KNOWLEDGE 변환·승인), `content_engine`(Draft 생성기, LLM rewrite, Threads publisher, publish history), `scripts/*.py`(CLI 전부), Threads GitHub Actions 자동화.
- **완전 placeholder**: `tak_scout/`(수익원 발굴·공개자료 탐색용으로 추정되나 내용 0), `operator/`(사람 승인 플로우용으로 추정되나 내용 0).
- **README가 실제 코드보다 훨씬 뒤처져 있음**: README는 여전히 "content_engine은 향후 AI 분석 엔진 자리", "자동 SNS 게시는 구현하지 않는다"고 서술하지만, 실제로는 이미 LLM 재작성 엔진과 Threads 실 게시가 완성·운영 중입니다. 문서와 실제 상태의 괴리가 큽니다(이번 작업에서 수정하지 않음, [10]에서 문서 업데이트를 별도 항목으로 제안).

---

## [2] 현재 구현 기능

| 기능 | 상태 |
|---|---|
| 네이버 RSS/공개 HTML → RAW 수집 | ✅ 구현 (`collect_naver_raw.py`, 읽기 전용) |
| RAW → KNOWLEDGE 규칙기반 변환 | ✅ 구현 (`create_knowledge.py`, `generate_knowledge.py`) |
| KNOWLEDGE 사람 승인 워크플로우 | ✅ 구현 (`review_knowledge.py`, pending/approved/rejected) |
| KNOWLEDGE → Blog(1)/Shorts(3)/Threads(5) Draft 생성 | ✅ 구현 (`generator.py`, 규칙 기반 템플릿) |
| Draft → LLM 재작성 + 사실경계 검증 | ✅ 구현 (`rewrite.py`, `llm_provider.py`) |
| Threads 자동 선택·게시·이력 관리 | ✅ 구현 + **실제 게시 성공 확인됨** |
| Blog 자동 게시(네이버) | ❌ 없음 — `check_naver_post.py`는 읽기 전용 점검일 뿐, 게시 기능 자체가 존재하지 않음 |
| Shorts(영상) 생성/게시 | ❌ 없음 — `ShortDraft`는 텍스트(title/body)만 있는 데이터클래스, 영상·TTS·이미지 합성 코드 전무 |
| 수익 추적(광고 수익, 제휴 클릭 등) | ❌ 없음 — 관련 필드/모듈 자체가 코드 어디에도 없음(grep 결과 0건) |
| 공개 자료 탐색(`tak_scout`) | ❌ placeholder |
| 운영자 승인 흐름(`operator`) | ❌ placeholder |

---

## [3] 플랫폼별 자동화 상태

`generator.py`/`pipeline.py`를 직접 확인한 기준:

| 플랫폼 | ① 생성 가능 | ② 검증 가능 | ③ 파일 저장 가능 | ④ 자동 게시 가능 | ⑤ 현재 실제 운영 중 |
|---|:---:|:---:|:---:|:---:|:---:|
| **Naver Blog** | ✅ (`BlogDraft` 1건/KNOWLEDGE) | ✅ (`RewriteService` 공통 검증) | ✅ (`MediaBatchReport.save_json`) | ❌ 게시 코드 없음 | ❌ |
| **Threads** | ✅ (`ThreadDraft` 5건/KNOWLEDGE) | ✅ | ✅ | ✅ (`publish_threads.py` + `ThreadsClient`) | ✅ **실제 게시 성공 확인됨** |
| **YouTube Shorts** | ⚠️ 텍스트 초안만 가능 (`ShortDraft` 3건/KNOWLEDGE) — 영상 자체는 생성 안 됨 | ✅ (텍스트 검증만) | ✅ | ❌ | ❌ |
| **기타(쿠팡/전자책 등)** | ❌ | ❌ | ❌ | ❌ | ❌ |

**중요한 정정**: "YouTube Shorts"라는 이름이 코드/모델(`ShortDraft`)에 붙어 있지만, 실제로는 짧은 텍스트 콘텐츠(캡션/스크립트 초안) 생성기이며 영상 합성·TTS·업로드 기능은 전혀 없습니다. 현재 "Shorts"는 유튜브 자동화가 아니라 "Threads보다 조금 긴 텍스트 초안" 수준입니다.

---

## [4] Threads 현재 운영 상태

5-1차 분석에서 확인된 사실을 그대로 재확인합니다(이번 작업에서 재검증하지 않고 확인된 사실로 기록):

- 하루 1개 게시 구조적 보장 (`--auto` 단일 선택 + workflow 배타적 if 조건)
- content_id는 `knowledge_id/platform/source_url/evidence_unit_ids/original_title/original_body` 기반 SHA-256 결정적 해시(LLM 재작성 결과 제외)
- publish history(`data/threads_publish_log.json`) 기반 중복 방지
- GitHub Actions `daily-threads-post.yml`, cron `0 23 * * *`(KST 08:00), `workflow_dispatch`(dry_run 기본 true)
- concurrency 그룹으로 동시 실행 차단
- **실제 Threads 게시 성공 확인됨**: `origin/main`의 `data/threads_publish_log.json`에 `threads_post_id: "18114019807999154"` 기록 존재.

→ Threads는 "콘텐츠 생산 파이프라인"으로서는 이미 안정적으로 도는 유일한 채널입니다. 그러나 **Threads 자체는 직접적인 수익 채널이 아니라는 점**이 5-2차의 핵심 문제의식입니다(아래 [5]).

---

## [5] 현재 수익화 상태

- **현재 실제 돈이 발생하는 부분**: **없습니다.** 코드베이스 전체(grep 기준)에 광고, 제휴 링크, 결제, 수익 필드, 트래픽/전환 추적과 관련된 코드가 단 한 줄도 없습니다.
- **돈을 벌 연결고리가 없는 부분**: 사실상 전체입니다. Threads는 팔로워/도달을 만들 수는 있지만 Threads 자체에 인앱 수익화(광고 공유, 팁 등)가 걸려 있지 않고, 코드에도 그런 연동이 없습니다.
- **자동화되지 않은 채널**: Naver Blog(애드센스/네이버 애드포스트 등 검색 유입 기반 광고 수익의 실질적 창구), YouTube Shorts(영상 자체), 제휴(쿠팡파트너스 등), 디지털 상품 판매.
- **자동화보다 먼저 콘텐츠 품질 검증이 필요한 채널**: **Naver Blog**(금융/부동산/대출 등 검색 유입이 실제 수익으로 이어지는 카테고리일수록, 사실관계 오류·과장이 검색 신뢰도·법적 리스크·구글 SEO 페널티로 직결됨), 그리고 **금융·부동산 지식 콘텐츠 전반**(현재도 `_criterion_blog`에 금융 관련 주의문구가 자동 삽입되는 로직은 있으나, 이는 여전히 규칙 기반 문구 삽입이지 사람의 사실 검증을 대체하지 못함).
- **수익 추적이 필요한 지점**: (1) 블로그 글별 조회수/애드포스트 수익, (2) 제휴 링크 클릭·전환, (3) Threads → Blog 유입 전환율. 현재 이 세 곳 모두 추적 코드가 전무합니다.

---

## [6] 수익원별 평가

| 수익원 | 수익 발생 구조 | 필요한 추가 개발 | 자동화 가능 정도 | 예상 난이도 | 장기 가치 | 우선순위 |
|---|---|---|---|---|---|---|
| **A. 네이버 블로그 광고(애드포스트)** | 검색 유입 → 블로그 조회수 → 네이버 애드포스트 수익 배분 | 블로그 자동/반자동 게시 스크립트, 네이버 로그인/세션 처리(README상 "네이버 로그인은 구현하지 않는다"는 기존 원칙과 충돌 — 정책 재검토 필요), SEO 최적화(제목/키워드) | 중 (게시는 자동화 가능하나 네이버 로그인 자동화는 약관·기술적 제약 있음) | 중 | 높음 (기존 파이프라인 대부분 재사용 가능 — `BlogDraft` 이미 존재) | **1순위 후보** |
| **B. 쿠팡파트너스/제휴** | 블로그·콘텐츠 내 제휴 링크 클릭 → 구매 전환 → 수수료 | 콘텐츠 유형별 제휴 링크 삽입 로직, 클릭 추적, 제휴 정책 준수 검토 | 중 (링크 삽입은 쉬우나 실제 전환은 콘텐츠 품질·주제 적합성에 크게 의존) | 중 | 중 (금융/제품 리뷰류 KNOWLEDGE에서만 자연스러움, 현재 KNOWLEDGE 대부분은 경험/직장/독서형이라 제휴 적합도 낮음) | 3순위 |
| **C. YouTube Shorts 광고수익** | 영상 조회 → 유튜브 파트너 프로그램 수익 | 영상 합성(TTS+이미지/자막), 업로드 API, 채널 개설·수익화 조건(구독자/시청시간) 충족까지의 별도 성장 곡선 | 낮음 (텍스트→영상 변환이 완전히 새로운 기술 스택 요구, 현재 `ShortDraft`는 텍스트뿐) | 높음 (신규 개발 규모 큼) | 중장기적으로 높음이나 시간이 오래 걸림 | 4순위(장기 과제) |
| **D. Threads 유입/브랜드 성장** | 직접 수익 아님 — 팔로워/브랜드 인지도 축적 → 다른 채널(Blog 등)로 유입 연결 시 간접 수익 | Threads 게시물에 블로그/상품 링크 삽입(Threads는 인앱 링크 제약이 있어 실질 효과 제한적), 팔로워 성장 추적 | 이미 자동화됨(생산 자체는) | 낮음(이미 완료) | 낮음~중(직접 수익 아님, 다른 채널의 마중물 역할) | 유지만, 신규 투자 우선순위 낮음 |
| **E. 전자책/디지털 상품** | KNOWLEDGE 누적분을 묶어 판매(예: "직장생활 판단기준 모음") | 상품화 파이프라인(원고 취합→디자인→플랫폼 등록), 결제 연동, 별도 마케팅 | 낮음 (사람 개입이 많이 필요, 자동화 여지 적음) | 중 | 중 (콘텐츠 자산 재활용 관점에서는 매력적이나 지금은 KNOWLEDGE 절대량이 10건뿐이라 시기상조) | 5순위(콘텐츠 축적 이후) |
| **F. 금융·부동산 지식 콘텐츠 상품** | 블로그/전자책 등 위 채널을 통해 실현(그 자체로 독립 채널이 아니라 A/E의 소재 카테고리) | KNOWLEDGE 카테고리 확장(현재 `article_types.py`엔 부동산 분류기 키워드가 없음 — README의 지원 category 목록엔 "부동산"이 있으나 실제 분류 로직엔 미반영), 사실 검증 강화 | A/E에 종속 | A/E와 동일 | 검색 수요가 크고 애드포스트/제휴 단가가 높은 영역이라 잠재력 큼 | 콘텐츠 소재 우선순위로는 상위, 채널 자체 우선순위는 아님 |
| **G. 기타(뉴스레터 협찬, 강의 등)** | 별도 채널 구독자/청중 확보 후 협찬·강의 수익 | 전혀 없음, 초기 논의 단계에도 못 미침 | 낮음 | 높음 | 불확실 | 후순위 |

**보수적 평가 원칙에 따른 코멘트**: 위 표의 어떤 항목도 현재 코드/데이터로 예상 수익액을 추정할 근거가 없습니다(트래픽 데이터, 클릭률, CPC 등 전무). 이번 보고서에서는 금액을 제시하지 않으며, "우선 자동화 vs 사람 개입 필요 vs 시기상조"라는 상대적 우선순위만 제공합니다.

---

## [7] KNOWLEDGE → CONTENT → TRAFFIC → MONEY 구조

현재 KNOWLEDGE의 `article_type`(experience/finance/workplace/ai_business/book_philosophy/general)과 README가 명시한 `domain`/`category`(금융, 대출, 경매, 부동산, 인간관계, 심리, 자기계발, 독서, 건강, 가족, 골프, 기타) 구조를 근거로 설계:

```
[finance / 대출 / 부동산 KNOWLEDGE]  (article_type=finance, 향후 부동산 분류 추가 필요)
  → Blog (_criterion_blog, 이미 금융 주의문구 자동 삽입 로직 있음)
  → 네이버/구글 검색 유입 (대출·부동산은 검색 수요·CPC가 높은 대표 카테고리)
  → 애드포스트 광고 + 금융상품 제휴(신중 검토 후)
  → [사람 승인 필수 — 6-A]

[workplace / 인간관계 / 심리 KNOWLEDGE]  (현재 승인 KNOWLEDGE 10건 중 5건이 이 유형 — 최다)
  → Blog + Threads + Shorts(텍스트)
  → 공감 기반 검색·SNS 유입 (낮은 CPC지만 안정적 트래픽)
  → 애드포스트(소액) + 브랜드 팔로워 축적
  → [AI 자동 처리 가능, 리스크 낮음]

[experience(개발/앱 제작 등) / ai_business KNOWLEDGE]
  → Threads(현재 실제 운영 중) + Shorts
  → 팔로워·브랜드 성장 (직접 수익 아님)
  → 향후 전자책/강의 상품화 시 소재로 재활용
  → [AI 자동 처리 가능]

[book_philosophy KNOWLEDGE]
  → Blog
  → 저품질 검색 유입(광고 단가 낮음), 브랜드 톤 유지 목적이 더 큼
  → 낮은 우선순위 채널
```

이 매핑에서 가장 먼저 손대야 할 조합은 **finance/부동산 KNOWLEDGE → Blog → 검색 유입 → 애드포스트**입니다. 이유: (1) 이미 `_criterion_blog`에 금융 프로파일 처리가 구현되어 있어 재사용 가능, (2) 검색 기반 트래픽은 Threads의 SNS 트래픽보다 광고 단가가 높은 경향, (3) README가 지원한다고 명시한 카테고리 중 실제 수요가 가장 확실한 영역.

---

## [8] TAK MEDIA 확장 방향

현재 구조(코드로 확인):
```
KNOWLEDGE (1건, approved)
  → generate_content_bundle()
      → Blog ×1 (BLOG_COUNT=1)
      → Shorts ×3 (SHORTS_COUNT=3, 텍스트 초안)
      → Threads ×5 (THREADS_COUNT=5)
  → RewriteService.rewrite() : draft 1건당 LLM 호출 1회 (총 9회/KNOWLEDGE)
  → MediaBatchReport (valid/rejected/error 상태별 items)
```

**향후 확장 제안 (마이크로서비스화 지양, 단일 저장소·단일 파이프라인 유지)**:

1. **퍼블리셔를 플랫폼별 모듈로만 분리**하되 오케스트레이터는 지금처럼 하나(`run_daily.py` 패턴)로 유지. 예: `content_engine/naver_blog_publisher.py`를 `threads_publisher.py`와 동일한 패턴(설정→클라이언트→게시→PublishHistory 재사용)으로 신설. **`PublishHistory`/`compute_content_id`는 플랫폼 필드가 이미 지문에 포함되어 있으므로 그대로 재사용 가능** — 새 저장소나 새 스키마 불필요.
2. **수익 추적은 별도 실시간 시스템이 아니라, 기존 `publish_history` 레코드에 필드를 추가하는 방식**으로 단순하게 시작(예: `platform`, `content_id`별로 나중에 조회수/수익을 수동 또는 배치로 채워 넣는 `revenue_log.json` 하나를 추가하는 정도). 실시간 대시보드나 별도 DB/서비스는 이 단계에서 과설계.
3. **다중 플랫폼 게시라도 워크플로우는 여전히 "하루 1회, 오케스트레이터 1개"** 원칙 유지 — 플랫폼마다 워크플로우 파일을 늘리기보다, `run_daily.py`가 순차적으로 플랫폼별 publisher를 호출하는 구조가 지금 코드 스타일과 가장 잘 맞음.
4. 마이크로서비스, 메시지 큐, 별도 DB 서버 등은 **현재 콘텐츠량(승인 KNOWLEDGE 10건 미만)과 트래픽 규모에서 전혀 정당화되지 않으므로 제안하지 않음.**

---

## [9] 1순위 MVP

**② 네이버 블로그 수익화 자동화**

근거:
- 사용자의 목적이 "콘텐츠 생산"이 아니라 "수익화"로 명시적으로 전환됨.
- Threads(①)는 이미 안정적으로 도는 채널이지만, **Threads 자체에는 현재 코드/플랫폼 구조상 직접적인 수익 연결고리가 없음**([5] 참고). 고도화해도 수익으로 바로 연결되지 않음.
- YouTube Shorts(③)는 텍스트→영상이라는 완전히 새로운 기술 스택이 필요해 개발 난이도·소요 시간이 가장 큼([6]-C 참고).
- 반면 블로그(②)는 **`BlogDraft` 생성·검증 로직이 이미 존재**하고, 네이버 검색 유입은 애드포스트라는 구체적이고 즉시 연결 가능한 수익 모델을 가지고 있어 "가장 적은 신규 개발로 가장 먼저 실제 수익 구조를 완성할 수 있는 채널"입니다.

---

## [10] AI/사람 역할 분리

| 구분 | 대상 |
|---|---|
| **AI 자동** | RAW→KNOWLEDGE 초안 변환, KNOWLEDGE→Draft 생성, LLM 재작성, 사실경계/형식 검증(500자 제한 등), content_id 계산·중복 체크, Threads 게시 실행 |
| **사람 승인** | KNOWLEDGE `pending→approved` 전환(이미 존재하는 게이트), **finance/부동산/대출 카테고리 Blog 게시 직전 최종 확인**(신설 필요), 제휴 링크 삽입 여부 |
| **사람 최종 판단** | 실제 금전적 조언으로 오인될 수 있는 문구("이건 확정 수익입니다" 류)가 있는지 여부, 법적 책임이 걸리는 표현(대출 승인 가능성 단정 등)의 최종 게이트 |

**금융/대출/부동산 콘텐츠의 품질·사실관계 검증 제안**:
- 현재도 `_criterion_blog`가 `profile == "finance"`일 때 "금융기관의 공식 심사 기준으로 해석하지 않습니다"라는 주의문구를 자동 삽입하지만, 이는 **면책 문구이지 사실 검증이 아님**.
- 제안: finance/부동산 계열 KNOWLEDGE는 **KNOWLEDGE 승인 단계(review_knowledge.py)에서 이미 일반 승인보다 한 단계 더 엄격한 체크리스트**(원문 근거 문장 존재 여부, 확정적 단정 표현 여부)를 통과해야 `approved`로 전환되도록 하고, Blog 게시 전에는 **자동 게시가 아니라 "게시 대기(draft) 상태로 저장 후 사람이 최종 확인 버튼을 누르는" 반자동 방식**을 Threads와 다르게 적용하는 것을 권장합니다. Threads(경험/직장 콘텐츠 중심)와 동일한 완전자동 기준을 금융/부동산에 그대로 적용하지 않는 것이 핵심입니다.

---

## [11] 🔴 반드시 필요한 작업

- 해당 없음(이번 분석 단계에서는). 다만 "블로그 자동 게시를 만들기 전에 네이버 로그인/게시 자동화가 README의 기존 원칙(로그인 자동화 미구현)과 충돌한다"는 점은 **다음 단계(5-3) 착수 전에 반드시 정책적으로 확인해야 할 전제 조건**입니다(코드 문제가 아니라 정책/약관 문제).

## [12] 🟡 개선 작업

1. **README/폴더 설명이 실제 구현 상태를 반영하지 못함** — `content_engine`을 "향후 AI 분석 엔진 자리"로, "자동 SNS 게시는 구현하지 않는다"로 서술한 부분은 현재 사실과 다름. 신규 기여자·향후 세션의 혼선을 막기 위해 업데이트 권장(단, 이번 작업 범위 아님).
2. **`article_types.py`의 부동산 분류 키워드 부재** — README는 부동산을 지원 category로 명시하지만 실제 분류기(`ARTICLE_TYPES`, 키워드 목록)에는 "부동산" 관련 키워드가 없어 부동산 RAW가 들어와도 `finance`나 `general`로 오분류될 가능성.
3. **`tak_scout`/`operator` placeholder 방치** — 이름만 있고 내용이 없어, 향후 "운영자 승인" 기능을 만들 때 이 자리를 쓸지 새로 만들지 혼란 소지.
4. **수익 추적 데이터 모델 부재** — 지금 만들어두지 않으면 나중에 블로그/제휴가 붙었을 때 소급 추적이 불가능(과거 게시물의 수익 기여도를 나중에 복원할 수 없음).

## [13] 🟢 이미 완료된 부분

- KNOWLEDGE 승인 게이트, Threads 완전 자동화 파이프라인(생성→검증→게시→이력), 중복 방지 설계, 콘텐츠 생성기(Blog/Shorts/Threads 9종 템플릿)는 모두 안정적으로 동작 중이며 5-3 이후 단계에서 그대로 재사용 가능한 견고한 기반입니다.

---

## [14] 단계별 수익화 로드맵

| 단계 | 목표 | 수정 예상 파일 | 외부 서비스 필요 | 위험도 | 완료 기준 |
|---|---|---|---|---|---|
| **5-3. Naver Blog 게시 자동화(MVP)** | approved KNOWLEDGE의 `BlogDraft`를 네이버 블로그에 실제 게시 | `content_engine/naver_blog_publisher.py`(신규), `scripts/publish_blog.py`(신규), `run_daily.py`(연결) | 필요 (네이버 블로그 API 또는 계정 인증 — 정책 확인 선행) | 중~높음(네이버 로그인 자동화의 약관/기술 제약) | 블로그 1건 실제 게시 성공 + 이력 기록 |
| **5-4. 애드포스트 연결 확인 및 SEO 기본 보강** | 게시된 블로그가 실제 애드포스트 수익 조건(방문자수 등)을 충족하는지 확인, 제목/키워드 최적화 | `content_engine/generator.py`(제목 전략 보강) | 필요(네이버 애드포스트 심사) | 낮음 | 애드포스트 승인 완료 |
| **5-5. 부동산/금융 KNOWLEDGE 분류 보강 + 사람 검증 게이트 강화** | `article_types.py`에 부동산 키워드 추가, finance/부동산 전용 승인 체크리스트 도입 | `tak_brain/article_types.py`, `scripts/review_knowledge.py` | 불필요 | 낮음 | 부동산 RAW가 올바르게 분류되고, 강화된 게이트 통과 테스트 통과 |
| **5-6. 수익 추적 최소 기록 체계** | 플랫폼×content_id별 수익(조회수/광고수익/제휴클릭)을 수기 또는 배치로 기록할 최소 파일 구조 도입 | `content_engine/revenue_log.py`(신규, `publish_history.py`와 유사 패턴) | 불필요(1차는 수동 입력도 허용) | 낮음 | 최소 1건의 실제 수익 데이터가 content_id에 연결되어 조회 가능 |
| **5-7. 쿠팡파트너스 등 제휴 링크 삽입(선택적)** | 적합한 KNOWLEDGE(finance/제품 관련)에 한해 Blog 본문에 제휴 링크 자동 삽입 | `content_engine/generator.py` | 필요(쿠팡파트너스 가입/승인) | 중(콘텐츠 신뢰성 저하 리스크) | 제휴 링크 삽입 + 클릭 추적 최소 동작 |
| **5-8. YouTube Shorts 실제 영상화(장기)** | 텍스트 Draft → TTS/이미지 합성 → 영상 업로드 | `content_engine/`에 신규 영상 생성 모듈, `scripts/publish_youtube.py`(신규) | 필요(TTS API, 영상 합성 라이브러리, YouTube API) | 높음(완전히 새 기술 스택) | 영상 1건 실제 업로드 성공 |
| **5-9. 콘텐츠 성과 분석/우선순위 재조정** | 어떤 KNOWLEDGE 유형이 실제 수익에 기여하는지 분석해 향후 RAW 수집·승인 우선순위에 반영 | 분석 스크립트(신규, 코드 변경 최소) | 불필요 | 낮음 | 유형별 수익 기여도 보고서 1회 생성 |

---

## [15] 최종 방향 판단

**지금부터는 "Threads 자동게시 고도화"보다 "수익화 중심(Naver Blog 우선)"으로 방향을 전환하는 것이 맞습니다.**

이유:
1. Threads 파이프라인은 이미 [3][4]에서 확인했듯 "안정적으로 도는 상태"에 도달했습니다 — 여기에 더 투자해도 한계 수익 증가분이 작습니다(콘텐츠 생산량은 늘지만, Threads 자체에 수익 연결고리가 없다는 근본 문제는 고도화로 해결되지 않음).
2. 반면 Naver Blog는 **콘텐츠 생성·검증 로직(`BlogDraft`, `RewriteService`)이 이미 완성되어 있고**, 남은 것은 "게시" 한 단계뿐입니다. 즉 Threads가 걸어온 것과 거의 동일한 패턴(생성→검증→게시→이력)을 재사용할 수 있어, **투입 대비 산출이 Threads 고도화보다 훨씬 큽니다.**
3. 애드포스트라는 구체적이고 검증된 수익 모델이 존재하며, 이는 사용자가 원하는 "돈이 되는 시스템"이라는 목표와 직접 연결됩니다.
4. 단, 전면 전환이 아니라 **점진적 전환**을 권장합니다 — Threads는 유지·모니터링만 하고(이미 완성됐으므로 유지비용이 낮음), 신규 개발 리소스는 5-3(Blog 게시 자동화)에 집중하는 것이 가장 합리적입니다.

---

## [16] 이번 작업 수정 파일

**없음.** 이번 5-2차 작업은 분석·설계만 수행했으며, 코드/문서/데이터 파일을 생성·수정·삭제하지 않았습니다. GitHub Actions 실행, Threads/기타 외부 API 호출, Secrets 조회/출력은 전혀 수행하지 않았습니다.

---

## [17] git status

```
On branch main
Your branch is behind 'origin/main' by 1 commit, and can be fast-forwarded.
  (use "git pull" to update your local branch)
nothing to commit, working tree clean
```

- 5-1차 분석 이후 로컬에서 추가로 `git fetch`/`git add`/`git commit`/`git push`를 수행하지 않았습니다(상태는 5-1차 종료 시점과 동일).
- 이번 세션에서도 `git status` 조회 외 어떤 git 쓰기 작업도 하지 않았습니다.

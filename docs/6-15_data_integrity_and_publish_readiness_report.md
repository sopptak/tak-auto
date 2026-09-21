# 6-15 Data Integrity & Publish Readiness Report

## 1. 작업 목적

6-14가 만든 Publish Readiness 감사(`scripts/audit_publish_candidates.py`)를 실제로
돌려 보니, Production Archive 18건 중 16건이 승인(approved)됐음에도 전부
`NEEDS_HUMAN_REVIEW`로 분류되고 있었다(READY 0). 그중 `knowledge-scout-6d1d0e2fa762`
(Microsoft/Mustafa Suleyman의 AI 의식 가능성 발언을 다룬 의견 콘텐츠)는 `category`가
"금융"으로 잘못 표시돼 있었다. 이번 6-15는:

1. 이 오분류가 1건의 데이터 오류인지, category 판정 로직 자체의 구조적 문제인지 코드
   수준에서 추적하고,
2. `article_type`/`category`/`domain`/`review_required`가 서로 암묵적으로 연결되지
   않는다는 6-04의 원칙이 현재 코드와 **현재 데이터** 양쪽에서 실제로 지켜지고 있는지
   재검증하고,
3. Threads pending draft(`data/tak_threads_pending.json`)와 실제 게시 이력
   (`data/threads_publish_log.json`)의 전수 정합성을 점검·안전하게 복구하고,
4. 그 결과로 Publish Readiness가 어떻게, 왜 바뀌었는지 원인별로 기록하는 것이 목적이다.

절대 원칙(작업 지시 0장)에 따라 실제 외부 플랫폼(Naver/Threads/YouTube)에는 아무것도
게시하지 않았고, LLM을 호출하지 않았고, Production Archive/Generation Pool을
재생성하지 않았다. 사용자에게 `/media`, `/publish-readiness` 링크를 열어보라고
요청하지 않았다 - 모든 조사는 코드·JSON·git history를 직접 읽어서 수행했다.

## 2. 작업 전 상태

- branch `main`, HEAD `fc13577`(6-14 report follow-up commit), `origin/main`과 완전히
  동기화된 상태로 세션을 시작했다(`git fetch` 후 `git log origin/main..HEAD`/
  `git log HEAD..origin/main` 모두 빈 결과).
- `git status --short`: 6-14 종료 시점과 동일한 기존 미커밋 목록(`.gitignore`,
  `content_engine/__init__.py`, `content_engine/generator.py`,
  `content_engine/llm_provider.py`, `content_engine/rewrite.py`,
  `data/tak_brain_knowledge.json`, `data/tak_threads_pending.json`,
  `tests/test_content_engine.py`, `tests/test_media_batch.py`)과 다수의 untracked
  문서/스크립트만 있었다 - 이번 세션에서 손대지 않았다.
- `python -m pytest -q` 기준선: **980 passed, 68 subtests passed, 0 failed**.
- `docs/publish_readiness_latest.md`(2026-09-21T02:21:32 생성) 실측: 전체 18,
  READY 0, NEEDS_HUMAN_REVIEW 16, BLOCKED 2, ALREADY_PUBLISHED 0, ERROR 0.
- Production Archive(`data/tak_media_archive.json`) 실측: 18건, 오직 2개
  knowledge_id만 사용(`knowledge-scout-b28b782b2a33` 9건,
  `knowledge-scout-6d1d0e2fa762` 9건) - 두 KNOWLEDGE 레코드의 category 판정이
  Publish Readiness 전체를 좌우하는 구조였다.
- KNOWLEDGE(`data/tak_brain_knowledge.json`) 실측: 28건. SCOUT 유래 18건 전부
  `category`="금융"/`domain`="금융"이었다(예외 없음).
- Threads pending(`data/tak_threads_pending.json`) 5건, Threads 게시 이력
  (`data/threads_publish_log.json`) 6건.

## 3. KNOWLEDGE category 문제 원인

### 3-1. 추적 경로

`tak_scout/collector.py:46` → `tak_scout/knowledge_bridge.py:_map_category()` →
`KnowledgeRecord.category`/`domain`을 코드로 직접 추적했다.

```
data/scout_sources.json: "BBC Business" 소스의 category = "finance"
    -> tak_scout/collector.py: candidate.category = source["category"] (그대로)
    -> tak_scout/knowledge_bridge.py::_map_category(): "finance" -> "금융"(CATEGORY_ALIASES)
    -> KnowledgeRecord.category = KnowledgeRecord.domain = "금융"  (이 후보 기사 1건의
       실제 내용과 무관하게, 그 후보가 어느 RSS 피드에서 왔는지만 반영)
```

### 3-2. 1건의 오류가 아니라 구조적 문제

`data/scout_sources.json`에 등록된 소스는 "BBC Business"(category="finance")와
"Hacker News"(category="tech") 단 2개뿐이다. SCOUT은 이 블랭킷 category를 후보
기사 개별 내용 분석 없이 그대로 복사한다. 실제 KNOWLEDGE 파일을 전수 조사한 결과,
**SCOUT 유래 18건 전부**가 실제 기사 내용과 무관하게 `category`="금융"이었다:

| 실제 내용 | 건수 | category="금융"이 맞는가 |
| --- | --- | --- |
| AI 위험/윤리/개발속도 논쟁(Anthropic, Microsoft, Trump 등) | 8 | 아니오 |
| 정치/무역/비즈니스 문화(관세, 총리 발언, SNS 설전) | 3 | 아니오 |
| 생활 안전/물류 사고(도난 방지, 화물기 추락) | 2 | 아니오 |
| 실제 금융시장/통화정책(기준금리, JP Morgan 유가 전망) | 4 | 예 |
| 임대료/부동산 시장 | 1 | "부동산"이 더 정확 |

→ **결론: 단순한 1건의 잘못된 데이터가 아니라, SCOUT → KNOWLEDGE 경로 전체가 개별
기사 내용을 전혀 분석하지 않고 RSS 피드 단위 블랭킷 category를 그대로 쓰는 구조적
설계다.** `tak_scout/knowledge_bridge.py`의 기존 주석(6-04)이 이미 이 사실을 정확히
인지하고 있었다 - "이 경로에는 신뢰할 수 있는 content-based 분류 신호가 아예 없다."

### 3-3. 예상보다 큰 2차 발견: `article_type`도 재발 직전이었다

`category`를 조사하던 중 **article_type이 같은 방식으로 더 심각하게 오염돼 있음을
발견했다.** 6-04는 SCOUT 경로의 `article_type`을 항상 `None`으로 두도록
`tak_scout/knowledge_bridge.py`를 고쳤지만, 그 코드 변경은 **새로 생성되는
KNOWLEDGE에만** 적용된다. 기존에 이미 만들어진 SCOUT KNOWLEDGE 레코드들은 여전히
과거 코드가 남긴 `article_type="finance"` 값을 그대로 갖고 있었다.

6-05/6-07 세션은 이 문제를 발견하고 **딱 2건만**(`knowledge-scout-b28b782b2a33`,
`knowledge-scout-6d1d0e2fa762` - 둘 다 Production Archive에 이미 콘텐츠가 생성돼
있던 것) 수동으로 `article_type=None`으로 정정했다. 하지만 **나머지 16건은 정정되지
않은 채 남아 있었다** - 전수 조사로 확인:

```
$ python3 -c 조사 결과: 16건이 여전히 article_type="finance"
knowledge-scout-e981e03d8737(rejected), knowledge-scout-a5e1a31ccbd6(pending),
knowledge-scout-624fd3789798(rejected), knowledge-scout-c8a717882561(rejected),
knowledge-scout-d21393bd1af0(rejected), knowledge-scout-70346e8dbd16(rejected),
knowledge-scout-9ee1fb847bed(rejected), knowledge-scout-da6d70cade1b(rejected),
knowledge-scout-26c322127579(rejected), knowledge-scout-56f0f4f75183(rejected),
knowledge-scout-b62fe658b086(pending), knowledge-scout-197c07e40b54(pending),
knowledge-scout-ca2f90bd732d(pending), knowledge-scout-b10962d51c7d(pending),
knowledge-scout-8e4677efb4fe(pending), knowledge-scout-709efcdd9a98(pending)
```

이 중 **6건이 pending**이다 - 즉 사람이 검토 화면에서 이 중 하나(예:
"Uncontrolled AI..."를 다룬 `knowledge-scout-197c07e40b54`)를 승인하는 순간,
`content_engine/generator.py::_profile()`이 `article_type=="finance"`를 보고
finance 템플릿("재무 판단...", 금융기관 심사 기준 면책 문구)을 AI 콘텐츠에 다시
적용했을 것이다 - **6-04가 고쳤다고 여겼던 버그가 재발 대기 상태였다.** 이는 작업
지시 3장이 가장 우려한 "암묵적 연결이 다시 존재하면 안 된다"의 실제 사례였다.

## 4. category / domain / article_type 관계

코드 재확인 결과, 의도된 분리는 **코드 수준에서는** 정확히 지켜지고 있었다:

- `content_engine/generator.py::_profile()`(109행)과
  `content_engine/rewrite.py::_finance_errors()`(232행)는 **오직
  `article_type`만** 참조한다. `category`/`domain`을 읽지 않는다 - grep으로
  전수 확인.
- `content_engine/blog_publish_pack.py::is_review_required()`(84행)는 반대로
  **`category`/`domain`/`article_type` 셋 다** 확인한다(의도된 안전장치 - 하나만
  깨져도 다른 신호로 잡히도록).
- 문제는 코드의 암묵적 연결이 아니라, **오래된 레코드에 남은 값 자체**가 두 코드
  경로 각각의 신뢰 전제(article_type="신뢰 가능한 content 분류 신호가 없으면
  None", category="RSS 피드 단위 신호, 개별 신뢰도는 낮지만 보수적으로 사용")를
  어기고 있었다는 것이다.

기존 CATEGORIES 어휘(`tak_brain/models.py`: 금융/대출/경매/부동산/인간관계/심리/
자기계발/독서/건강/가족/골프/기타)를 그대로 사용했다 - 새 category를 만들지 않았다.

## 5. review_required 판정 구조

`content_engine/blog_publish_pack.py::is_review_required()`의 판정 로직(코드)
자체는 **바꾸지 않았다** - 지시 7장대로, 정책이 불명확하면 코드를 건드리지 않고
기록만 남긴다:

```python
if knowledge.article_type == "finance": return True
if knowledge.category in ("금융","대출","경매","부동산"): return True
if knowledge.domain and any(kw in knowledge.domain for kw in (...)): return True
```

이 함수는 "category라는 이름"과 "실제 금융 위험 콘텐츠"를 동일하게 취급하는 게
맞다 - 그것이 원래 설계 의도다(면책 문구가 이 판단을 대체하지 않는다는 docstring
참고). 문제는 함수가 아니라 **입력값(category)이 틀렸던 것**이었으므로, category를
정확하게 고치는 것만으로 review_required가 올바르게 동작하게 됐다 - 정책을
완화한 것이 아니라, 정확한 입력에 기존 정책을 그대로 적용한 것이다.

## 6. 수정한 KNOWLEDGE 데이터

### 6-1. category/domain 수정(13건)

| knowledge_id | before | after | 이유 |
| --- | --- | --- | --- |
| knowledge-scout-6d1d0e2fa762 | 금융/금융 | 기타/기타 | AI 의식 가능성 의견 콘텐츠(Microsoft/Suleyman/Anthropic) - 금융/대출/경매/부동산과 무관. **최초 지시 대상** |
| knowledge-scout-197c07e40b54 | 금융/금융 | 기타/기타 | 위와 동일 원문의 중복 후보(pending) |
| knowledge-scout-56f0f4f75183 | 금융/금융 | 기타/기타 | Anthropic Dario Amodei AI 속도 완화 촉구(rejected) |
| knowledge-scout-e981e03d8737 | 금융/금융 | 기타/기타 | AI 위협 대응 법안 촉구 위원회(rejected) |
| knowledge-scout-624fd3789798 | 금융/금융 | 기타/기타 | 영국 기업 문화 전환 촉구, 총리 발언(rejected) |
| knowledge-scout-c8a717882561 | 금융/금융 | 기타/기타 | 대학생 도난 방지 팁(rejected) |
| knowledge-scout-d21393bd1af0 | 금융/금융 | 기타/기타 | Amazon 화물기 추락사고(rejected) |
| knowledge-scout-70346e8dbd16 | 금융/금융 | 기타/기타 | Trump AI 위험 경고 축소 발언(rejected) |
| knowledge-scout-9ee1fb847bed | 금융/금융 | 기타/기타 | 전 Anthropic 연구원 AI 위험 경고(rejected) |
| knowledge-scout-da6d70cade1b | 금융/금융 | 기타/기타 | 실리콘밸리 AI 경고 회의론(rejected) |
| knowledge-scout-26c322127579 | 금융/금융 | 기타/기타 | Trump 아일랜드 위스키 관세 철폐 발언(rejected) |
| knowledge-scout-b10962d51c7d | 금융/금융 | 기타/기타 | 경제부 장관-국무장관 SNS 설전(pending) |
| knowledge-scout-a5e1a31ccbd6 | 금융/금융 | 부동산/부동산 | 임대료 상승 전망(Zoopla) - "금융"보다 "부동산"이 정확. FINANCE_REVIEW_KEYWORDS에 "부동산"도 포함돼 안전장치 유지(pending) |

Downstream 영향: 위 13건 중 **Production Archive에 이미 생성된 콘텐츠가 있는 것은
`knowledge-scout-6d1d0e2fa762` 뿐**이다(9건). 나머지 12건은 pending/rejected
상태라 아직 어떤 콘텐츠도 생성되지 않았으므로 즉각적인 다운스트림 영향이 없다 -
향후 승인 시 올바른 category로 review_required가 판정된다는 예방적 효과만 있다.

### 6-2. 의도적으로 변경하지 않은 category(5건)

| knowledge_id | category | 이유 |
| --- | --- | --- |
| knowledge-scout-b62fe658b086 | 금융(유지) | 일본 기준금리 인상 - 실제 금융/통화정책 콘텐츠 |
| knowledge-scout-ca2f90bd732d | 금융(유지) | JP Morgan 유가 전망 - 실제 금융시장 콘텐츠 |
| knowledge-scout-8e4677efb4fe | 금융(유지) | 영란은행 기준금리 동결 - 실제 금융/통화정책 콘텐츠 |
| knowledge-scout-709efcdd9a98 | 금융(유지) | JP Morgan 유가 전망(중복) - 실제 금융시장 콘텐츠 |
| **knowledge-scout-b28b782b2a33** | **금융(유지, 의도적)** | **아래 6장 참고 - 내용은 AI 콘텐츠로 금융과 무관하지만, 이미 승인된 archive 레코드가 수정되지 않은 finance-template 잔재를 포함하고 있어 안전장치를 유지함** |

### 6-3. article_type 수정(16건)

3-3에서 발견한 stale `article_type="finance"`를 전부 `None`으로 정정했다(6-05/
6-07이 이미 정정한 2건과 동일한 방식·동일한 근거) - `category`/`domain`/승인
상태/시각/본문 등 다른 모든 필드는 전혀 건드리지 않았다.

```
knowledge-scout-e981e03d8737, knowledge-scout-a5e1a31ccbd6, knowledge-scout-624fd3789798,
knowledge-scout-c8a717882561, knowledge-scout-d21393bd1af0, knowledge-scout-70346e8dbd16,
knowledge-scout-9ee1fb847bed, knowledge-scout-da6d70cade1b, knowledge-scout-26c322127579,
knowledge-scout-56f0f4f75183, knowledge-scout-b62fe658b086, knowledge-scout-197c07e40b54,
knowledge-scout-ca2f90bd732d, knowledge-scout-b10962d51c7d, knowledge-scout-8e4677efb4fe,
knowledge-scout-709efcdd9a98
```

전부 pending 또는 rejected 상태였다(승인된 레코드는 하나도 없음) - 즉시 영향은
없지만, 향후 승인 시 finance 템플릿이 잘못 적용되는 재발을 막는다.

### 6-4. 중요: `knowledge-scout-b28b782b2a33`는 왜 고치지 않았는가 (CRITICAL)

Production Archive를 레코드별로 직접 읽어 확인한 결과, `knowledge-scout-b28b782b2a33`
(내용은 6d1d0e2fa762와 마찬가지로 AI 콘텐츠, 금융과 무관)의 9건 중
**`content-5971ed5204437cdd`(blog, review_status=approved)는 지금도 제목
"재무 판단에서 함께 볼 기준"과 "금융기관의 공식 심사 기준으로 해석하지 않습니다"
면책 문구를 포함한 **finance 템플릿 잔재**를 갖고 있다.**

원인: 이 archive 레코드는 6-04 코드 수정 **이전**, `article_type="finance"`였던
시점에 생성됐다(6-05 보고서/커밋 확인). 6-05는 KNOWLEDGE의 `article_type`만
정정하고 실제 재생성 결과는 별도 gitignored 파일
(`data/tak_media_archive_6-05_b28b782b2a33_regeneration.json`, 정정된 버전:
`content-afc6060bc1957867`, 제목 "두려움보다 먼저, 직접 확인하는 태도")에만 남긴
채, **Production Archive의 기존 9건을 덮어쓰지 않았다**(사람이 이미 승인한
콘텐츠를 임의로 바꾸지 않는다는 원칙 때문). 즉 approved 상태인
`content-5971ed5204437cdd`는 지금도 finance 템플릿이 낀 콘텐츠 그대로다.

`category=="금융"`은 현재 이 결함 있는 승인 레코드가 `READY`로 넘어가지 않게
막는 **유일한 안전장치**다. 이번 세션에서 만약 category를 "AI 콘텐츠니까"라는
이유만으로 "기타"로 바꿨다면, `is_review_required()`가 False가 되어 이 9건
전부가 즉시 `READY`(그중 finance 템플릿이 낀 1건 포함)로 넘어갔을 것이다 - 지시
0장의 "문제를 발견하면 임의로 덮어쓰지 않는다"를 정면으로 어기는 결과였을 것이다.
그래서 **category는 의도적으로 그대로 두었다.**

**사람이 판단해야 하는 항목(NEEDS_HUMAN_REVIEW로 명확히 표시)**:
`content-5971ed5204437cdd`를 다음 중 하나로 처리해야 한다 -
(a) 승인을 취소하고 다시 검수하거나, (b) 이미 만들어져 있는 정정 버전
(`content-afc6060bc1957867`, 별도 파일에 존재)으로 교체하거나, (c) 콘텐츠를
사람이 직접 수정한다. 이 결정과 실행은 이번 세션의 범위 밖이다(Production Archive
재생성/LLM 재생성 금지 원칙).

## 7. Threads publish consistency 전수 점검

새로 만든 `content_engine/threads_consistency.py` + `scripts/audit_threads_publish_consistency.py`
(읽기 전용)로 pending 5건 × 게시 이력 6건, 합집합 11개 content_id를 전수 대조했다.

| 상태 | 건수 | 설명 |
| --- | --- | --- |
| PUBLISHED_BUT_PENDING_STALE | 1 | `content-43786cf3ee0d89c5` - 아래 8장 |
| PENDING_WITHOUT_PUBLISH_LOG | 4 | 정상(아직 게시 전) |
| ORPHAN | 6 | 게시 이력에는 있으나 pending에 없음 - 아래 참고 |
| CONSISTENT / FAILED / DUPLICATE | 0 | - |

**ORPHAN 6건은 조사 결과 정상으로 확인됐다**: 전부 레거시 완전 자동 발행 경로
(`scripts/publish_threads.py`, `data/threads_publish_log.json`만 기록하고
`tak_threads_pending.json`은 전혀 import하지 않음 - grep으로 확인)로 게시된
콘텐츠였다. 2026년 9월 11일 도입된 사람 검수 게이트(5-11 설계) 이전 방식이라
애초에 pending draft가 없는 것이 설계상 정상이다 - 데이터 이상이 아니다.

## 8. Threads 수정 내역

`content-43786cf3ee0d89c5`(지시 9장이 명시한 대상)를 전수 검증한 결과 3가지 조건을
모두 충족했다: (1) 게시 이력에 실제 `threads_post_id`("17895093546607157")가 존재,
(2) content_id가 정확히 일치, (3) 게시 이력에 중복 없음. `status`도 "approved"라서
기존에 이미 있던 `scripts/publish_approved_threads.py`의 안전한 동기화 경로(이미
게시 이력에 있는 content_id는 Threads API를 다시 호출하지 않고 pending 상태만
동기화 - 코드 확인됨)를 그대로 사용할 수 있었다.

**새 동기화 스크립트를 만들지 않았다** - 지시 10장대로 이미 존재하는 기능을
재사용했다. 대신 dry-run으로 먼저 확인 후 실행했다:

```
$ python3 scripts/publish_approved_threads.py --id content-43786cf3ee0d89c5 --dry-run
안내: content_id=content-43786cf3ee0d89c5는 이미 게시 이력에 존재합니다. Threads API를 호출하지 않습니다.

$ python3 scripts/publish_approved_threads.py --id content-43786cf3ee0d89c5 --execute
안내: content_id=content-43786cf3ee0d89c5는 이미 게시 이력에 존재합니다. Threads API를 호출하지 않습니다.
```

결과: `status: "approved"` → `"published"`, `published_at`/`threads_post_id`가
게시 이력 값과 동일하게 채워짐. `data/threads_publish_log.json`(SHA256 불변 확인)은
전혀 건드리지 않았다 - 실제 Threads API도 호출되지 않았다(로그 메시지로 확인).

나머지 4건(`content-cbcf705b6056c9fc`, `content-dbf0fb4eb5cfd791`,
`content-4015df0692e0bcc4`, `content-81d4e7c5723598f6`)은 게시 이력이 전혀 없는
`PENDING_WITHOUT_PUBLISH_LOG` 상태로, 수정하지 않았다(정상).

## 9. Publish Readiness 변경 전/후

```
                       변경 전    변경 후
READY                     0         9
NEEDS_HUMAN_REVIEW       16         7
BLOCKED                   2         2
ALREADY_PUBLISHED         0         0
ERROR                     0         0
전체                      18        18
```

**원인 구분** (지시 11장 요구):

- **READY 9건 증가는 전부 category 수정(6장) 때문이다** -
  `knowledge-scout-6d1d0e2fa762`의 category가 "금융"→"기타"로 정정되면서
  `is_review_required()`가 False가 됐고, 그 9건(blog 1·shorts 3·threads 5)은
  다른 조건(승인/유효/필수 필드/Shorts Script 존재)을 이미 만족하고 있었으므로
  즉시 READY로 이동했다.
- **NEEDS_HUMAN_REVIEW 16→7 감소는 전부 위와 같은 원인**(9건이 READY로 이동) -
  review_required 판정 로직 변경은 없었다(5장).
- **BLOCKED은 2건 그대로**(unreviewed/rejected 레코드 2건) - 이번 작업과 무관.
- Shorts Script 생성이나 Threads stale 정리(8장)는 Publish Readiness 수치에
  영향을 주지 않았다 - stale 정리 대상(`content-43786cf3ee0d89c5`)은 Threads
  게시(별도 knowledge_id, Production Archive에 없음)일 뿐 audit_publish_candidates.py의
  대상(Production Archive)과 무관한 파일이었다.
- **`knowledge-scout-b28b782b2a33`의 7건은 의도적으로 그대로 NEEDS_HUMAN_REVIEW다**
  (6-4장 참고) - READY가 늘었다고 전부 좋은 신호로 임의 판단하지 않았다.

## 10. 실제 데이터 무결성 검증

| 파일 | 수정 전 SHA256 | 수정 후 SHA256 | 비고 |
| --- | --- | --- | --- |
| data/tak_brain_knowledge.json | `a4cbb521...` | `e2ad1d39...` | 의도된 수정(6장) |
| data/tak_threads_pending.json | `9dd8a8c0...` | `d122a0b6...` | 의도된 수정(8장, 1건만) |
| data/threads_publish_log.json | `d8907429...` | `d8907429...` (불변) | **의도적으로 건드리지 않음 - 확인됨** |
| data/tak_media_archive.json | `ebe1249f...` | `ebe1249f...` (불변) | **Production Archive 재생성 금지 - 확인됨** |

Generation Pool(`data/tak_media_generation_6-07_knowledge-scout-6d1d0e2fa762.json`
등 gitignored 1회성 파일)도 이번 세션에서 열거나 쓰지 않았다.

## 11. 테스트 결과

- 작업 시작 시 기준선: `python -m pytest -q` → **980 passed, 68 subtests passed, 0 failed**.
- 최종: `python -m pytest -q` → **998 passed, 68 subtests passed, 0 failed**.
- 증가한 18건은 전부 이번 세션에서 추가한 신규 테스트다:
  - `tests/test_threads_consistency.py`(14건) - 6개 분류 전부, safe_to_sync 판정
    (pending vs approved 상태 차이), Markdown 렌더링.
  - `tests/test_audit_threads_publish_consistency_cli.py`(4건) - CLI가 dry-run에서
    어떤 파일도 쓰지 않는지, `--no-report`, `--fail-on-anomaly` 동작.
- 기존 테스트 중 2건은 수정했다(삭제/약화 아님 - 옛 값을 고정 assert하던 것을 6-15
  정정 후 값으로 갱신하고 이유를 docstring에 남김):
  `tests/test_second_knowledge_correction_and_generation_pool.py::test_other_fields_are_unchanged_from_6_05_report`
  (category/domain 기대값 갱신), `::test_corrected_knowledge_still_requires_human_review`
  → `::test_corrected_knowledge_no_longer_requires_finance_review`(의도된 동작 변경 반영).
- 회귀 확인: `test_blog_publish_pack.py`(finance/non-finance 분류를
  `is_review_required()`로 동적으로 계산하는 fixture라 데이터 변경에도 별도 수정
  없이 통과), `test_publish_audit.py`, `test_audit_publish_candidates_cli.py`,
  Generation Pool/Promotion 관련 테스트 전부 통과.

## 12. 수정 파일 목록

**데이터(2)**: `data/tak_brain_knowledge.json`, `data/tak_threads_pending.json`

**신규 코드(2)**: `content_engine/threads_consistency.py`,
`scripts/audit_threads_publish_consistency.py`

**신규 테스트(2)**: `tests/test_threads_consistency.py`,
`tests/test_audit_threads_publish_consistency_cli.py`

**수정 테스트(1)**: `tests/test_second_knowledge_correction_and_generation_pool.py`

**보고서(2)**: `docs/publish_readiness_latest.md`(재생성),
`docs/threads_publish_consistency_latest.md`(신규),
`docs/6-15_data_integrity_and_publish_readiness_report.md`(이 문서)

## 13. Git / Commit / Push

세션 시작 시 존재하던 기존 미커밋 변경(`.gitignore`, `content_engine/__init__.py`,
`content_engine/generator.py`, `content_engine/llm_provider.py`,
`content_engine/rewrite.py`, `tests/test_content_engine.py`,
`tests/test_media_batch.py`, 다수의 untracked 5월~6월 문서/스크립트,
`data/tak_media_archive.json`)는 이번 세션과 무관하므로 **일절 stage하지 않았다**.

## 14. 남은 문제

**CRITICAL**
- `content-5971ed5204437cdd`(blog, `knowledge-scout-b28b782b2a33`, approved)가
  finance 템플릿 잔재("재무 판단에서 함께 볼 기준" + 금융기관 심사 기준 면책
  문구)를 그대로 가진 채 승인 상태로 Production Archive에 남아 있다. 현재는
  `category=="금융"` 안전장치가 이 레코드를 NEEDS_HUMAN_REVIEW에 묶어 두고 있지만,
  근본적으로는 승인이 취소되거나 이미 만들어진 정정 버전
  (`content-afc6060bc1957867`, `data/tak_media_archive_6-05_b28b782b2a33_regeneration.json`)
  으로 교체돼야 한다.

**HIGH**
- SCOUT → KNOWLEDGE 경로에는 여전히 개별 기사 내용 기반 category 분류기가 없다
  (RSS 피드 단위 블랭킷 category만 사용). 이번에는 18건을 수동으로 정정했지만,
  앞으로 SCOUT이 새 후보를 수집할 때마다 이 문제가 그대로 재발한다 - `article_type`
  처럼 "신뢰 신호 없음 = None" 원칙을 category에도 적용할지, 아니면 최소한의 영문
  키워드 기반 분류기를 새로 만들지는 사람의 판단이 필요하다(안전장치를 약화시키는
  방향이라 신중해야 한다).

**MEDIUM**
- `data/blog_publish_log.json`이 파일 자체가 존재하지 않는다(`PublishHistory`가
  파일 없음을 빈 이력으로 처리해 오류는 아니지만, Blog가 실제로 몇 건 게시됐는지
  이 경로로는 확인 불가 - Naver 게시 이력 확인 방법을 별도로 점검할 필요).
- Threads pending 게이트 도입 이전 레거시 게시 이력 6건(ORPHAN)은 정상으로
  확인됐지만, 두 발행 경로(레거시 자동/신규 검수)가 계속 공존하는 것이 장기적으로
  혼란을 줄 수 있다 - 레거시 경로의 완전 폐기 시점을 결정할 필요.

**LOW**
- `knowledge-scout-a5e1a31ccbd6`의 category를 "부동산"으로 정정했는데, 이 레코드는
  아직 pending이라 실제 영향은 없다 - 승인 시 재확인 권장.

## 15. 다음 5~6시간 작업 추천

1. **CRITICAL 해결**: `content-5971ed5204437cdd` 승인 취소 또는
   `content-afc6060bc1957867`로 교체하는 절차를 사람이 결정하고, 그 결정을
   `scripts/promote_media_generation.py`(이미 존재)로 안전하게 반영.
2. **HIGH 해결 설계**: SCOUT category 판정을 어떻게 개선할지(신뢰 신호 없음 원칙
   확장 vs 최소 키워드 분류기 신규 도입) 설계 문서 작성 후 구현.
3. `data/blog_publish_log.json` 부재 원인 조사 - Naver 블로그 실제 게시 이력을
   추적하는 다른 방법이 있는지, 없다면 왜 없는지, Publish Readiness의 Blog
   ALREADY_PUBLISHED 판정이 지금 항상 False로만 나오는 구조적 리스크가 있는지 확인.
4. Threads 레거시/신규 발행 경로 공존 정리 계획 수립.
5. `/threads-consistency` 같은 읽기 전용 Dashboard 라우트 추가(6-14의
   `/publish-readiness`와 동일한 패턴) - 사람이 CLI를 직접 실행하지 않아도 보도록.

## 16. 최종 결론

KNOWLEDGE category 오분류는 1건의 데이터 오류가 아니라 SCOUT→KNOWLEDGE 경로의
구조적 한계(RSS 피드 단위 블랭킷 category)였고, 조사 과정에서 그보다 더 위험한
잠재 재발 지점(article_type stale 값 16건, 그중 6건 pending)도 함께 발견해 고쳤다.
Production Archive와 게시 이력은 원칙대로 건드리지 않았고, 유일하게 승인된 레코드 중
과거 버그의 잔재를 가진 1건(`content-5971ed5204437cdd`)은 category 안전장치를
그대로 남겨 자동으로 노출되지 않도록 보호하면서 CRITICAL로 명시했다 - "문제를
발견하면 임의로 덮어쓰지 않는다"는 원칙을 실제 트레이드오프 상황에서 지켰다.
Threads 정합성 문제(`content-43786cf3ee0d89c5`)는 이미 존재하던 안전한 동기화
경로로 복구했고 새 복구 스크립트를 만들지 않았다. 테스트는 980→998(전부 통과, 0
실패)로 늘었고, 실제 외부 게시는 이번 세션에서도 수행하지 않았다.

# TAK AUTO 5-3차: 네이버 블로그 수익화 MVP 구현 결과

## [1] 구현 요약

TAK MEDIA가 이미 만들던 `BlogDraft`(생성→LLM 재작성→검증) 파이프라인은 **전혀 수정하지 않고**, 그 결과물을 "네이버 블로그 게시 후보(Blog Publishing Pack)"로 변환하는 계층만 새로 추가했습니다.

```
KNOWLEDGE(approved) → run_media_batch (기존, 무수정) → BlogDraft(valid)
  → build_blog_publish_pack() [신규]
      - select_blog_publish_candidates(): 서로 다른 KNOWLEDGE 우선 + 최대 5개 + 이미 게시된 content_id 제외
      - suggest_category/keywords/hashtags/image_ideas/is_review_required()
  → render_markdown() / save_markdown() [신규]
  → data/blog_publish_pack_daily.md  (사람이 복사/붙여넣기)
      ↓
   사람이 네이버 블로그에서 직접 예약 발행
      ↓
   scripts/mark_blog_published.py [신규, 사람이 수동 실행] → data/blog_publish_log.json 기록
```

네이버 로그인 자동화, 브라우저 자동 게시, 캡차 우회는 구현하지 않았습니다(요청대로).

## [2] 변경 파일

| 파일 | 종류 |
|---|---|
| `content_engine/blog_publish_pack.py` | 신규 — 선정/제안/렌더링 핵심 로직 |
| `scripts/generate_blog_publish_pack.py` | 신규 — CLI 오케스트레이터 |
| `scripts/mark_blog_published.py` | 신규 — 사람이 실제 게시 후 수동 기록하는 CLI |
| `tests/test_blog_publish_pack.py` | 신규 — 19개 테스트 |
| `content_engine/__init__.py` | 수정(추가) — 새 모듈 export만 추가, 기존 export는 그대로 |
| `.gitignore` | 수정(추가) — `!data/blog_publish_log.json`(추적), `data/blog_publish_pack_daily.md`(휘발성, 미추적) 규칙 추가 |
| `generator.py`/`rewrite.py`/`pipeline.py`/`llm_provider.py`/`models.py`/`publish_history.py`/`publish_threads.py`/`run_daily.py`/workflow yml | **수정 없음** |

## [3] 새 기능 사용 방법

```bash
# 1) 오늘의 Blog 게시 후보 생성 (최대 5개, LLM 실제 호출)
python3 scripts/generate_blog_publish_pack.py

# → data/blog_publish_pack_daily.md 생성됨. 사람이 열어서 검토.

# 2) 사람이 네이버 블로그에 실제로 복사/붙여넣기하고 예약 발행 완료 후:
python3 scripts/mark_blog_published.py --content-id content-xxxxxxxx \
    --knowledge-id knowledge-xxxx --source-url "https://blog.naver.com/..."

# → data/blog_publish_log.json에 기록되어, 다음 Pack 생성부터 후보에서 제외됨.
```

## [4] 하루 5개 생성 흐름

1. `tak_brain.select_approved()`로 approved KNOWLEDGE 전체 로드(기존 코드, 무수정).
2. `run_media_batch()`로 각 KNOWLEDGE당 BlogDraft 1개 생성→LLM 재작성→검증(기존 코드, 무수정).
3. `platform=="blog" and status=="valid"` 항목만 추출.
4. `select_blog_publish_candidates()`: `data/blog_publish_log.json`에 이미 기록된 content_id 제외 → **서로 다른 KNOWLEDGE 우선** 1차 선택 → 슬롯 남으면 동일 KNOWLEDGE의 나머지 항목으로 2차 채움 → 최대 5개.
5. 각 후보에 카테고리/키워드/해시태그/이미지 아이디어/`review_required`를 부여해 `BlogPublishItem` 생성.
6. Markdown으로 렌더링해 `data/blog_publish_pack_daily.md`에 저장.

## [5] 실제 생성 결과 예시

`MockRewriteProvider`(네트워크 없음, 실제 LLM/네이버 API 미호출)로 현재 저장소의 실제 approved KNOWLEDGE 4건을 대상으로 로컬 실행한 결과(스크래치패드에만 저장, 프로젝트 `data/`는 건드리지 않음):

```
TAK BRAIN: 승인 KNOWLEDGE 4건 확인
TAK MEDIA 완료: 총 Draft 36건 (valid 36, rejected 0, error 0)
Blog Publishing Pack 생성 완료: 4건 (사람 확인 필요 1건)
```

생성된 Markdown 중 1건 발췌:

```
━━━━━━━━━━━━━━━━━━━━
[2번 글]
카테고리: 금융/재테크
제목: 재무 판단에서 함께 볼 기준

본문:
글은 "대출 판단에서 매출만으로 충분한지 질문하는 글이다"라는 질문을 던집니다.
원문에서는 "원문은 매출뿐 아니라 함께 확인할 재무 항목을 제시한다"고 설명합니다.
이를 적용할 때는 "금융 판단에서는 원문에 제시된 여러 재무 지표를 함께 확인한다"는 원칙을 제시합니다.
이 글의 금융 관련 내용은 원문 작성자의 설명이며, 금융기관의 공식 심사 기준으로 해석하지 않습니다.

핵심 키워드:
금융, 재무, 판단에서, 함께, 기준

해시태그:
#금융 #재무 #판단에서 #함께 #기준

이미지 권장:
- 대표 이미지: 제목의 핵심 주제를 상징적으로 보여주는 이미지 1장
- 본문 이미지 1: 글에서 다루는 상황·문제를 보여주는 이미지
- 본문 이미지 2: 결과·교훈·판단기준을 정리한 이미지 또는 간단한 인포그래픽

검토:
□ 일반 콘텐츠
☑ 금융/부동산/대출 → 사람 확인 필요

원본:
knowledge-e1cc05264953
source_url: https://blog.naver.com/tmong2/224407146649?fromRss=true&trackingCode=rss
━━━━━━━━━━━━━━━━━━━━
```

나머지 3건(경험/직장 유형)은 모두 `☑ 일반 콘텐츠`로 정상 표시되었습니다.

## [6] 금융/부동산 안전장치

- `is_review_required()`가 `article_type=="finance"` 또는 `category`/`domain`에 금융·대출·경매·부동산 키워드가 있으면 `True`. KNOWLEDGE를 찾지 못하는 예외 상황도 안전 측(`True`)으로 기본값 처리.
- 기존 `_criterion_blog`의 면책 문구("금융기관의 공식 심사 기준으로 해석하지 않습니다")는 그대로 유지했지만, **이를 사실 검증의 대체물로 취급하지 않고** Pack에 별도의 `☑/□` 체크박스를 명시해 사람이 반드시 원문 근거·확정적 표현·현재 규정 의존 여부를 직접 확인하도록 안내문을 Markdown 헤더에 고정 삽입.
- 실제 데이터 기준 finance 계열 KNOWLEDGE(`knowledge-e1cc05264953`)가 정확히 `review_required=True`, 카테고리 "금융/재테크"로 분류됨을 확인.

## [7] Threads 기존 기능 영향

- Threads 관련 파일(`generator.py`, `rewrite.py`, `pipeline.py`, `llm_provider.py`, `publish_history.py`, `publish_threads.py`, `run_daily.py`, `daily-threads-post.yml`) **어느 하나도 수정하지 않았습니다.**
- 새로 만든 것은 전부 별도 파일(`content_engine/blog_publish_pack.py`, `scripts/generate_blog_publish_pack.py`, `scripts/mark_blog_published.py`)이며, Blog 이력은 Threads 이력(`data/threads_publish_log.json`)과 분리된 `data/blog_publish_log.json`을 사용해 서로 간섭하지 않습니다.
- 기존 Threads 테스트(176개) 전부 그대로 통과 확인.

## [8] 테스트 결과

```
python3 -m unittest discover -s tests -p 'test*.py'
Ran 195 tests in 1.43s
OK
```

- 기존 176개 전부 통과(무변경 확인).
- 신규 19개 전부 통과: Pack 생성, 최대 5개 제한(기본값/커스텀), 서로 다른 KNOWLEDGE 우선 선택, 이미 게시된 content_id 제외(단건/전체 소진), finance→`review_required=True`, 일반→`False`, KNOWLEDGE 미존재 시 안전 기본값, Markdown 필수 섹션·체크박스·"보장하지 않습니다" 문구·빈 Pack 메시지, 파일 저장, `mark_blog_published.py` 정상 기록/멱등성.

## [9] git status

```
## main...origin/main [behind 1]
 M .gitignore
 M content_engine/__init__.py
?? content_engine/blog_publish_pack.py
?? docs/5-2_monetization_analysis.md
?? scripts/generate_blog_publish_pack.py
?? scripts/mark_blog_published.py
?? tests/test_blog_publish_pack.py
```

`git add`/`commit`/`push`는 수행하지 않았습니다. (`docs/5-2_monetization_analysis.md`는 직전 5-2차 작업에서 이미 생성된 파일입니다.) `data/` 아래에는 어떤 실제 파일도 새로 만들지 않았습니다(데모 실행은 세션 스크래치패드에서만 수행).

## [10] 다음 단계 제안

1. **실제 승인 KNOWLEDGE로 1회 실전 테스트**: `python3 scripts/generate_blog_publish_pack.py` 실행 후, 사람이 실제로 네이버 블로그에 1건이라도 복사/붙여넣기 → 예약 발행 → `mark_blog_published.py`로 기록해보고 전체 흐름을 검증.
2. **키워드 추출 품질 개선(선택)**: 현재 키워드 추출은 순수 정규식 기반 토큰화라 "직접", "얻은" 같은 조사/어미 결합형 단어가 섞여 나옵니다. 사실을 추가하지 않는 범위에서 불용어 필터를 보강하면 검색 키워드 품질이 나아질 수 있음(시급하지 않음).
3. **부동산 카테고리 분류 키워드 보강**: 5-2차에서 지적한 대로 `tak_brain/article_types.py`에 부동산 관련 키워드가 없어, 향후 부동산 RAW가 들어오면 오분류될 수 있음(이번 작업 범위 밖, 별도 처리 권장).
4. **GitHub Actions 연동 여부는 별도 결정**: 이번 MVP는 의도적으로 `run_daily.py`/workflow에 연결하지 않았습니다. Blog는 "사람 최종 확인"이 필수인 반자동 흐름이라, Threads처럼 매일 자동 트리거할지, 아니면 당분간 사람이 수동으로 CLI를 실행할지는 운영 패턴을 좀 더 지켜본 뒤 결정하는 것을 권장.

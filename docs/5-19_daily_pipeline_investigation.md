# 5-19. Daily Tmong Content Pipeline — 조사 보고 + 구현 계획 (코드 수정 없음)

목표: "매일 아침 티몽이 약 5분만 참여하면 하나의 원본 KNOWLEDGE와 여러 콘텐츠 초안이
만들어지는 실제 운영 파이프라인"을 **기존 기능을 연결해서** 만든다.

이 문서는 조사 결과와 구현 계획만 담는다. **코드는 한 줄도 수정하지 않았다.**

---

## 0. 결론 먼저

파이프라인의 8단계(SCOUT 수집 → 점수화 → 후보 선정 → 인터뷰 → KNOWLEDGE →
TAK MEDIA → Shorts 렌더링 → 승인 대기 → YouTube 업로드) 중 **6.5단계는 이미
구현되어 있고 실제로 맞물려 동작한다.** 새로 짜야 하는 로직은 사실상
**"ShortDraft(title+body) → ShortsScript(표지/카드/마무리) 변환 어댑터" 하나**뿐이다.

다만 **중요한 충돌 하나**를 발견했다: 기존 `daily-threads-post.yml`이 지금도 매일
08:00 KST에 **사람 승인 없이 실제 Threads에 자동 게시**하고 있다. 이는 5-19의
원칙 4/5("처음에는 자동 공개하지 않는다", "최종 공개 전 승인 단계 유지")와
정면으로 충돌한다 — 아래 3번에서 상세히 다룬다.

---

## 1. 기존 기능 중 그대로 연결할 수 있는 것 (수정 없이 재사용)

| 파이프라인 단계 | 기존 구현 | 상태 |
|---|---|---|
| SCOUT 수집 | `scripts/run_scout.py` → `tak_scout.collector` (공개 RSS만, dedup) | ✅ 그대로 사용 |
| 점수화 | `tak_scout.scoring.rank_candidates/top_candidates` (LLM 없는 rule-based 100점) | ✅ 그대로 사용 — Dashboard `/` 화면이 이미 이 함수로 정렬해서 보여줌 |
| 후보 선정 UI | `scripts/run_scout_dashboard.py` `/` 페이지 (모바일 반응형 HTML) | ✅ 그대로 사용 |
| 인터뷰(멀티턴, LLM 후속질문) | `tak_scout.interview_session` + `tak_scout.interview_llm.InterviewLLMProvider` + Dashboard `/candidate/<id>` | ✅ 그대로 사용 — 원칙 6/7/8을 이미 코드로 강제하고 있음(아래 2-a 참고) |
| 중복 인터뷰 방지 | `InterviewSession`이 `scout_id` 키로 저장, `get_or_start_session`이 기존 세션 반환 | ✅ 그대로 사용 — 새 로직 불필요(아래 2-b 참고) |
| KNOWLEDGE 생성 | `tak_scout.knowledge_bridge.append_scout_knowledge` (Dashboard `/candidate/<id>/finalize`에서 호출) | ✅ 그대로 사용, 항상 `pending` 상태로 생성 |
| KNOWLEDGE 승인 | `scripts/review_knowledge.py --approve` (기존 TAK BRAIN 승인 흐름) | ✅ 그대로 사용 — 원칙 10 그대로 충족 |
| TAK MEDIA (Blog 1 + Shorts 3 + Threads 5) | `scripts/run_media_batch.py` / `content_engine.pipeline.run_media_batch` | ✅ 그대로 사용 |
| Blog 초안 → 사람이 직접 게시 | `scripts/generate_blog_publish_pack.py` → `data/blog_publish_pack_daily.md` → 사람이 네이버에 수동 게시 → `scripts/mark_blog_published.py` | ✅ 그대로 사용 (원래부터 자동 게시 없음) |
| Threads 초안 → 승인 → 게시 | `scripts/generate_threads_draft.py` → Dashboard `/threads` 승인 → `scripts/publish_approved_threads.py` | ✅ 그대로 사용 — 승인 게이트 있음 (아래 3번 충돌 참고) |
| Shorts 대본 스키마 + 화면 분할 | `content_engine/shorts_script.py` (`ShortsScript`, `build_screen_plan`) | ✅ 그대로 사용 |
| Shorts 브랜드 렌더링 | `content_engine/shorts_renderer.py` + `scripts/render_youtube_short.py` | ✅ 그대로 사용 (5-17에서 완성, 5-18에서 안전성 보강) |
| YouTube 업로드 | `content_engine/youtube_publisher.py` + `scripts/upload_youtube_short.py` + `.github/workflows/youtube-shorts-upload.yml`(수동 dispatch, dry-run 기본값 true) | ✅ 그대로 사용 — 이미 "자동 공개 안 함" 원칙을 지키고 있음 |
| 08:00 KST cron 패턴 | `.github/workflows/daily-threads-post.yml`의 `cron: '0 23 * * *'` (UTC 전날 23시 = KST 08시) | ✅ cron 표현식 자체는 재사용 가능 |

---

## 2. 상세 확인 사항

### 2-a. 인터뷰가 원칙 6/7/8을 이미 코드로 강제하고 있음

`tak_scout/interview_llm.py`의 시스템 프롬프트(`_first_question_system_prompt`,
`_follow_up_system_prompt`)가 명시적으로 "뉴스 요약이 아니라 사용자의 생각을
끌어내는 것"이라고 지시하고, `source_fact`(기사 사실)와 사용자 의견을 분리해서
다루도록 강제한다. `decide_next_turn()`은 최대 3턴까지만 후속 질문을 생성하고,
3턴째는 LLM을 아예 호출하지 않고 무조건 종료한다(비용 상한을 코드 구조로
강제). `FORCED_OPTION_D`로 D(직접 입력) 옵션은 서버가 항상 강제 삽입해 LLM이
변조할 수 없다.

### 2-b. 중복 인터뷰 방지가 이미 구조적으로 보장됨

`InterviewSession`은 `data/tak_interview_sessions.json`에 `scout_id`를 키로
저장한다. `get_or_start_session()`은 기존 세션이 있으면 **그대로 반환하고 LLM도
호출하지 않는다.** `scout_id`는 `title+source_url`의 SHA256 해시(`compute_scout_id`)라
결정적이라서, 같은 기사가 다음날 다시 RSS에 걸려도 같은 `scout_id`가 나와 자동으로
"이미 답변함"으로 인식된다(Dashboard 목록 화면의 `status` 뱃지, `tak_auto.py`의
`[이미 답변함]` 표시 등에서 이미 이 프로퍼티를 활용 중).

### 2-c. ShortDraft ↔ ShortsScript는 완전히 분리되어 있음 (유일한 실질적 공백)

`content_engine/shorts_script.py` 파일 docstring이 스스로 명시: "TAK MEDIA의
ShortDraft(title + 단일 body 문자열)와는 별도로, 렌더러는 이미 화면 단위로
나뉜 대본만 입력으로 받는다." 실제로 저장소 전체에서 `ShortDraft`와
`ShortsScript`를 함께 참조하는 코드가 하나도 없다(grep으로 확인).

- `ShortDraft.body`는 `content_engine/generator.py`의 `_short()`가
  `\n\n`으로 문단을 구분해 만든다(현재는 최대 3문단 정도). LLM 재작성
  (`RewriteService`)을 거치면 이 구분이 유지된다는 보장은 없다 — `rewrite.py`는
  플랫폼별 구조를 전혀 구분하지 않는 범용 검증기다.
- `ShortsScript`는 `title`(필수) + `subtitle`(선택, 검증 없음) + `cards`(1~8개,
  각각 비어있으면 안 됨) + `takeaway`(필수) + `brand`(기본값 있음)를 요구한다.

**→ 이 변환 어댑터가 5-19에서 새로 만들어야 하는 사실상 유일한 로직이다.**

---

## 3. 현재 구조에서 충돌 가능성이 있는 부분

### 3-a. ⚠️ 가장 중요: Threads 자동 게시 cron이 이미 살아있고, 승인 게이트가 없음

`.github/workflows/daily-threads-post.yml`은 **지금도 매일 08:00 KST에**
`scripts/run_daily.py` → `scripts/publish_threads.py --auto` 경로로 **사람의
승인 없이 실제 Threads API에 게시**한다. 이 workflow는 5-11 인간 승인 설계
(`generate_threads_draft.py` → Dashboard `/threads` 승인 → `publish_approved_threads.py`)
**이전에 만들어진 구(舊) 경로**이며, `publish-approved-threads.yml`의 주석에
"cron 추가는 기존 daily-threads-post.yml의 cron 비활성화와 정확히 같은 시점에만
검토한다"고 적혀 있는 것으로 보아, **팀이 이미 이 구경로를 끄고 새 경로로
전환할 계획을 세워뒀지만 아직 실행하지 않은 상태**로 보인다.

5-19의 원칙 4("처음에는 자동 공개하지 않는다")와 5("최종 공개 전 티몽의 승인
단계를 유지한다")를 Threads에도 일관되게 적용하려면, **이 구경로(cron)를 끄는
결정이 5-19 구현의 사실상 첫 단계**가 되어야 한다. 이건 순수 코드 문제가
아니라 "이미 운영 중인 자동 게시를 멈출지" 결정이 필요한 사안이라 먼저
확인을 받아야 한다고 판단했다.

### 3-b. 두 개의 서로 다른 인터뷰 경로

`scripts/tak_auto.py`(TAK OPERATOR MVP, 터미널 CLI, `input()` 기반, 단일 A/B/C/D
고정 질문 1개)와 `scripts/run_scout_dashboard.py`(웹, 모바일 대응, 최대 3턴
LLM 후속질문)가 **둘 다 살아있고 둘 다 SCOUT→KNOWLEDGE를 만들 수 있다.**
5-19 원칙 6/7("실제 경험 추출", "짧게 답하면 후속 질문")을 만족하는 쪽은
Dashboard뿐이므로, 5-19는 **Dashboard 경로만 쓰고 tak_auto.py는 건드리지 않는다**
(원칙 2: 기존 기능을 함부로 재작성하지 않는다 — 그대로 둔다, 단지 새 자동화가
그 경로를 타지 않게 할 뿐).

### 3-c. Shorts에는 아직 "승인" 단계가 없음

Blog(사람이 직접 네이버에 복붙 후 `mark_blog_published.py`)와 Threads(Dashboard
`/threads` 승인)는 각각 사람 개입 지점이 명확하다. Shorts는 TAK MEDIA가
`ShortDraft` 3건을 만드는 것까지만 기존 구조가 있고, "3건 중 어떤 걸 실제
영상으로 만들지" 고르는 단계와 그 결과(렌더링된 mp4)를 사람이 검토하는
단계가 아직 정의돼 있지 않다. 다만 YouTube 업로드 자체가 이미 수동
workflow_dispatch(+ dry-run 기본값)로 막혀 있어서, **최소 구현에서는 "티몽이
렌더링된 mp4 파일을 직접 열어보고 괜찮으면 수동으로 업로드 workflow를 실행"
하는 것만으로 원칙 4/5를 만족할 수 있다** — 새로운 승인 UI를 반드시 먼저
만들 필요는 없다고 판단한다.

### 3-d. SCOUT 후보 선정이 "점수 기반"이 아니라 "수집 순서 기반"

`run_scout.py`가 쓰는 `collector.select_candidates()`는 점수를 전혀 보지 않고
RSS에서 모인 순서 그대로 앞에서 `--max`개만 자른다. 실제 "오늘의 후보
3~5개"를 점수 기준으로 선정하려면 `tak_scout.scoring.top_candidates()`를
수집 단계에 연결해야 한다(이미 있는 순수 함수를 호출 순서만 바꾸는 수준 —
새 로직 아님). 현재는 Dashboard의 `/` 목록 화면이 점수순으로 "보여주기만"
할 뿐, 후보 자체의 개수를 줄이지는 않는다.

### 3-e. RSS source가 2개뿐

`data/scout_sources.json`에 BBC Business, Hacker News 2개만 등록되어 있다.
코드 문제는 아니지만, "매일 3~5개 후보"가 안정적으로 나오려면 소스 추가가
운영상 필요할 수 있다(이 문서 범위 밖의 운영 데이터 이슈로만 기록).

---

## 4. 매일 오전 8시 실행을 위해 필요한 구성

- **자동화 가능한 부분은 SCOUT 수집 + 점수화뿐이다.** 인터뷰는 사람(티몽)이
  실제로 답을 입력해야 하므로 08:00에 무인으로 끝까지 돌릴 수 없다 — 이건
  설계상 당연한 제약이지 버그가 아니다.
- 기존 `daily-threads-post.yml`의 `cron: '0 23 * * *'`(UTC) 패턴을 그대로
  재사용해 **"SCOUT 수집 + 점수화 + 오늘의 후보 파일(`tak_scout_daily.json`) 갱신"만**
  수행하는 새 workflow를 만드는 것이 합리적이다 — Threads/YouTube처럼 실제
  게시/업로드가 없는 단계이므로 `contents: write` 권한과 결과 파일 commit/push
  정도만 있으면 되고(`data/tak_scout_daily.json`, `.md`, 나중엔 scored 버전),
  `workflow_dispatch`도 함께 열어 수동 재수집을 허용하는 기존 관례를 따른다.
- **Dashboard(`run_scout_dashboard.py`)는 08:00 cron이 아니라 티몽이 인터뷰하려는
  시점에 직접 띄워야 한다.** 상시 실행 서버로 돌리려면 Codespace를 계속 켜두거나
  별도 항상-켜진 호스트가 필요한데, 이건 이 저장소의 현재 범위(로컬/Codespace
  전용, `--host 127.0.0.1` 기본값)를 벗어나는 인프라 결정이라 5-19 범위에서는
  "필요하면 검토"로만 남겨둔다.
- KNOWLEDGE 승인(`review_knowledge.py --approve`), TAK MEDIA 실행
  (`run_media_batch.py --execute` 또는 `generate_threads_draft.py`/
  `generate_blog_publish_pack.py`), Shorts 렌더링(`render_youtube_short.py`),
  YouTube 업로드는 전부 **사람이 트리거하는 후속 단계**로 남긴다(아래 6번).

## 5. 사용자 인터뷰를 모바일에서 수행할 수 있는 현재 방법 (이미 존재, 5-11에서 검증됨)

1. Codespace 안에서 `python3 scripts/run_scout_dashboard.py`를 실행(기본
   `127.0.0.1:8000`).
2. Codespaces가 8000번 포트를 자동으로 포워딩한다(`private` 가시성 — GitHub
   로그인 필요).
3. 티몽이 모바일 브라우저에서 `https://<정확한-codespace-이름>-8000.app.github.dev/`로
   접속 — 이미 그 codespace 소유 계정으로 GitHub에 로그인되어 있으면 바로
   Dashboard가 뜬다(5-11 phase4_2 문서에서 실측 확인: codespace 이름 오타가
   404의 원인이었고, 정확한 이름이면 정상 동작).
4. `_PAGE_STYLE`에 `viewport` 메타태그와 `@media (max-width: 480px)` 반응형
   CSS가 이미 있어 모바일 화면에서 바로 쓸 수 있는 폭으로 렌더링된다.
5. **제약**: Codespace가 꺼져 있으면 접속 자체가 안 된다 — 티몽이 인터뷰하려면
   그 시점에 Codespace가 켜져 있어야 한다(자동 유지 여부는 GitHub Codespaces
   자체의 idle timeout 정책을 따름, 이 저장소 밖의 설정).

## 6. 자동화 후에도 사용자가 직접 해야 하는 작업

원칙 3/4/5를 그대로 지키면, 자동화 이후에도 남는 사람의 작업은:

1. **인터뷰 답변** (필수, 매일 약 5분 — 목표 그대로)
2. **KNOWLEDGE 승인/거부** (`review_knowledge.py --approve|--reject`, 이미 사람이 하던 일)
3. **Threads 초안 승인** (Dashboard `/threads`, 5-11에서 이미 사람이 하던 일)
4. **Threads 실제 게시 트리거** (`publish-approved-threads.yml` 수동 실행 — 단, 3-a의
   구경로 cron을 끄지 않으면 이 단계 자체가 무의미해진다)
5. **Blog 게시** (네이버에 직접 복붙 — 원래부터 자동화 대상 아님, API 없음)
6. **Shorts mp4 검수** (렌더링된 영상을 직접 재생해 확인 — 3-c에서 설명한 대로 별도 승인 UI 없이 파일 확인으로 대체 가능)
7. **YouTube 업로드 트리거** (`youtube-shorts-upload.yml` 수동 dispatch, dry-run 기본값 유지)

---

## 7. 구현 계획 (승인 후 진행 — 아직 코드 수정 안 함)

우선순위 순서로 제안한다. 각 단계는 "기존 기능 연결"이 먼저, "신규 최소
기능"은 2단계뿐이다.

1. **(결정 필요) 3-a 처리 방침 확정** — `daily-threads-post.yml`의 자동
   게시 cron을 끌지, 그대로 둘지, 아니면 5-19 파이프라인은 이 workflow와
   완전히 무관하게 별도로만 취급할지 먼저 정한다. 이건 코드보다 운영 결정이
   먼저다.
2. **(신규, 최소) `ShortDraft → ShortsScript` 어댑터** — 새 함수 하나
   (예: `content_engine/shorts_adapter.py`). `title`은 그대로, `body`를
   문단(`\n\n`) 단위로 쪼개 `cards`로, 마지막 문단(또는 KNOWLEDGE의
   `reusable_principle`)을 `takeaway`로 매핑한다. `cards`가 8개를 넘거나
   1개 미만이면(예: rewrite 후 단일 문단이 됨) 안전하게 처리하는 규칙만
   새로 정하면 된다 — 기존 `ShortsScript`/`build_screen_plan`/`render_shorts_video`는
   무수정.
3. **(연결) SCOUT 수집을 점수 기반 선정으로 바꾸기** — `run_scout.py` 또는
   새 wrapper에서 `collector.select_candidates()` 대신 `scoring.top_candidates()`를
   쓰도록 순서만 바꾼다(기존 두 함수 모두 무수정, 호출 순서 변경뿐).
4. **(신규, 최소) 08:00 SCOUT-only GitHub Actions workflow** — 기존
   `daily-threads-post.yml`의 cron/concurrency/권한 패턴을 그대로 본떠
   "수집 + 점수화 + 결과 commit"까지만 하는 workflow 1개 추가. Threads/
   YouTube 실제 게시는 전혀 건드리지 않는다.
5. **(연결) Shorts 렌더링 CLI를 KNOWLEDGE/MediaBatch 출력에 연결** — 2번
   어댑터를 사용해 `run_media_batch`가 만든 valid Shorts draft를
   `render_shorts_video()`로 넘기는 작은 CLI(예: `scripts/render_knowledge_shorts.py`).
   기존 `render_youtube_short.py`/`shorts_renderer.py`는 무수정, 입력을
   만들어주는 얇은 계층만 추가.
6. **문서화 + 운영 가이드** — 티몽이 매일 무엇을 언제 하면 되는지
   (Dashboard 접속 → 인터뷰 → 승인 → Shorts 확인 → 업로드 트리거) 순서를
   정리한 짧은 운영 문서.

이 계획대로 진행해도 되는지, 특히 1번(Threads 자동 게시 cron 처리 방침)과
2번(ShortsScript 매핑 규칙 — 특히 8개 초과/문단 없음 같은 예외 처리를 어떻게
할지)에 대해 확인을 받은 뒤 구현을 시작하겠다.

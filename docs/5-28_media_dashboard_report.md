# [MEDIA DASHBOARD 구현 완료]

TAK MEDIA Human Review Dashboard(`/media`) 구현 최종 보고. 목표 흐름:

```
SCOUT → 인터뷰 → KNOWLEDGE → 승인 → TAK MEDIA 9개 생성 → 영구 ARCHIVE
→ 📱 휴대폰 Dashboard에서 확인 → 사람이 수정/승인
→ 승인된 콘텐츠만 기존 채널별 발행 대기열로 이동 → 실제 발행은 별도 단계
```

이번 단계는 "Dashboard 검수/승인"까지만 구현한다. 실제 SNS/YouTube/Naver 발행은
절대 실행하지 않는다.

## 1. 변경 파일
- `scripts/run_scout_dashboard.py` — 기존 `/media-archive`(읽기 전용 최소 기반)를
  제거하고 `/media`, `/media/<content_id>` 라우트로 전면 확장. 필터/그룹핑/승인
  로직, CSS, 홈 화면 nav 링크 추가.

## 2. 신규 파일
- `tests/test_media_dashboard.py` — A~J 회귀 테스트 19건 (실제 소켓을 여는 HTTP
  통합 테스트, `tests/test_threads_dashboard.py`와 동일한 패턴)

## 3. Dashboard URL
- 목록: `GET /media` (필터: `?platform=&generation_status=&review_status=`)
- 상세: `GET /media/<content_id>`
- 승인: `POST /media/<content_id>/approve`
- 홈(`/`)에 `📱 TAK MEDIA` 메뉴 링크 추가

## 4. 구현한 기능
- KNOWLEDGE별 그룹핑 카드 목록(9개가 한 KNOWLEDGE에서 나왔다는 사실이 한눈에
  보임), created_at 최신순
- 카드: 플랫폼(BLOG/SHORTS/THREADS) · 생성상태(VALID/REJECTED/ERROR) ·
  검수상태(검수대기/승인/보류) · 제목 · 본문 미리보기
- platform / generation_status / review_status 3종 필터(단순 AND, 링크형
  pill UI)
- 상세 화면 6개 섹션(①KNOWLEDGE ②원본 Draft ③AI 생성 결과 ④검증 결과
  ⑤생성 정보 ⑥검수 상태) 전부 구현
- 모바일 우선 카드형 UI, 기존 SCOUT/Threads 화면과 동일한 CSS 시스템
  재사용(새 프레임워크 없음)

## 5. 승인 흐름
- VALID + 미승인일 때만 `[승인]` 버튼 노출 → 클릭 시
  `review_status: unreviewed → approved`
- REJECTED/ERROR에는 버튼 자체가 렌더링되지 않음
- 이미 approved면 버튼 미노출 + POST로 재요청해도 idempotent(중복 레코드 없음,
  그대로 반환)
- 승인 후 "승인되었습니다." 배너 표시

## 6. Threads 연결 여부
**연결됨.** `platform=="threads"`이고 승인되면 기존
`content_engine.threads_review.upsert_pending()`을 그대로 재사용해
`status="pending"`인 `ThreadsPendingDraft`를 `data/tak_threads_pending.json`에
생성 — 발행 승인이 아니라 기존 "Threads 검수 대기열"로 이동만 함. 이미 같은
content_id의 draft가 있으면(예: rotation이 먼저 만들었거나 이미
published/failed) **절대 덮어쓰지 않음**(테스트로 검증).

## 7. Blog 연결 여부
**archive의 review_status만 승인으로 변경.** Blog 전용 pending 저장소는
기존에도 없었으므로 새로 만들지 않았고, `tak_threads_pending.json`도 건드리지
않음(테스트로 확인). 단, 기존 `build_blog_publish_pack()`은 아직
`review_status`를 참조하지 않아 이 승인이 Blog Publishing Pack 선정에 자동
반영되지는 않음 — 다음 단계 과제로 남김.

## 8. Shorts 연결 여부
**archive의 review_status만 승인으로 변경.** MP4 렌더링은 전혀 실행하지
않음(`shorts_renderer`/`shorts_adapter` import 없음).

## 9. 테스트 결과
A~J 전부 작성·통과 (19 passed): 목록 렌더링, platform/generation_status/
review_status 필터, VALID만 승인 버튼, REJECTED/ERROR 버튼 없음, 승인 시
review_status 저장, 중복 방지, Threads 연결(+기존 draft 비파괴), 외부 API
미호출(소스 레벨 + 기능적 검증) 모두 확인.

## 10. 전체 pytest 결과
**638 passed, 68 subtests passed** (실패 0)

## 11. 실제 LLM 호출 여부
**없음** — 이 화면은 LLM을 아예 호출하지 않는 코드 경로(순수 archive
읽기/쓰기)

## 12. 실제 외부 발행 여부
**없음.** `ThreadsClient`/`YouTubeClient`/Naver 게시 코드는
`scripts/run_scout_dashboard.py`에 import조차 되어 있지 않음(정적 검사 + 실제
승인 흐름 실행 테스트로 이중 확인). Threads 승인도 발행이 아니라 기존 pending
검수열 진입까지만.

## 13. commit
`9329770` — "feat: add TAK MEDIA Human Review Dashboard (/media)"

## 14. push
`origin/main`에 반영 완료 (`73fd5d0..9329770`)

## 15. 남은 작업
- Blog: `build_blog_publish_pack()`이 아직 `review_status`를 보지 않음 —
  MEDIA 승인이 실제 Publishing Pack 후보 선정에 반영되도록 연결 필요
- Shorts: "승인 → 렌더링" 다음 단계(승인된 Shorts를 실제로
  `shorts_adapter`/렌더러에 넘기는 연결) 미구현
- "보류(dismissed)" 액션 버튼 없음 — 필터는 지원하지만 상태를 dismissed로
  바꾸는 UI는 이번에 넣지 않음(요청 범위에 없었음)
- Draft 본문 직접 수정 기능 미구현(요청대로 이번 단계 제외, 다만 구조적으로
  나중에 넣기 쉽게 `review_status`/archive 스키마 분리해둠)
- `content_engine/__init__.py`, `generator.py`, `llm_provider.py`,
  `rewrite.py`, `data/tak_brain_knowledge.json`, `tests/test_content_engine.py`,
  `tests/test_media_batch.py`는 여전히 이전 세션의 미커밋 변경 상태 그대로 —
  이번에도 손대지 않고 남겨둠

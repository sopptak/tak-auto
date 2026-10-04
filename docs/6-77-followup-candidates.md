# 6-77 후속·재활용 콘텐츠 후보 (성과 → 후속 콘텐츠 연결)

## 배경
파이프라인(소재 → 초안 → 변환 → 발행 → 성과) 중 **성과 → 후속 콘텐츠**가 코드로 연결되어 있지 않았다.
`content_engine/performance_insight.py`는 파생 분석만 제공하고 다음에 무엇을 만들지는 사람이 수동으로 정했다.

## 추가된 것
- `content_engine/followup.py` — 승인된 KNOWLEDGE + 발행 이력 + 미디어 archive + 최신 성과 스냅샷으로 후보 생성.
  - `repurpose`: 발행된 소재의 아직 없는 채널(blog/shorts/threads) 변환 후보.
  - `amplify`: 성과 합계가 중앙값 이상인 소재의 확장 후보(우선순위 +20).
  - 검색 의도(`how_to/comparison/problem_solving/informational/experience`)를 키워드로 결정적으로 분류, 검색 의도가 분명한 blog 후보는 +10.
  - 네이버/티스토리 출처 소재는 blog를 이미 발행한 것으로 본다.
- `scripts/generate_followups.py` — 기본은 미리보기, `--write`로 `data/tak_followup_candidates.json`에 append, `--set-status ID accepted|rejected`로 사람이 결정.
- `tests/test_followup.py`

## 경계
입력(성과/발행 이력/KNOWLEDGE/MEDIA)은 읽기만 하며, 후보는 별도 저장소에 `candidate`로만 쌓인다. 콘텐츠 생성·발행은 하지 않는다. 같은 `candidate_id`는 재실행해도 중복되지 않고 사람이 바꾼 상태를 보존한다.

## 알려진 환경 제약
Shorts 렌더러(`shorts_renderer.py`, `shorts_v2_renderer.py`)는 `C:/Windows/Fonts`의 한글 폰트를 요구해 Linux(Codespaces)에서 `tests/test_6_55_shorts_studio.py` 26건이 실패한다. 이 브랜치의 변경과 무관한 기존 제약이다.

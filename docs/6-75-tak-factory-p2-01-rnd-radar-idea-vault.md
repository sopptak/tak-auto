# TAK AUTO P2-01 — R&D Radar + IDEA VAULT Foundation

## 목적과 범위

외부에서 발견한 AI·개발·자동화 정보를 안전하게 기록하고, 사람이 TAK AUTO 적용 가치를 판단한 아이디어와 분리해 관리한다. 이번 단계는 저장·정규화·중복 후보·상태 관리 기반이며 외부 자동 수집, LLM 평가, 브라우저 제어, 게시 기능은 구현하지 않았다.

작업 기준은 GitHub `main`의 `fa9eb32`에서 fetch된 최신 HEAD `fa9eb32`다. 로컬 기존 checkout에 사용자 변경이 있어 별도 worktree/branch `p2-01-rnd-radar`에서 작업했다. PROJECT 2030, Production Archive, Threads 게시·Performance Collection(P1)은 수정하지 않았다.

## 설계 결정

- `tak_scout`는 콘텐츠 소재 후보와 RSS 수집에, `tak_brain`은 블로그 RAW와 작성자 지식에 맞춰져 있다. R&D discovery와 제품 적용 아이디어의 수명주기·필드가 달라 기존 모델에 억지로 합치지 않고 독립 `tak_rnd` 패키지로 둔다.
- P1 Performance 저장소는 콘텐츠 성과 시계열 전용이므로 의존하거나 변경하지 않는다.
- 별도 DB 없이 UTF-8 JSON 배열과 표준 라이브러리를 쓴다. 파일은 임시 파일에 쓴 후 `replace()`로 교체한다. 기존 데이터 migration은 없다.
- Git에서 사람이 diff를 확인할 수 있도록 R&D와 IDEA JSON 저장소만 명시적으로 추적 가능하게 했다. 이번 기본 파일은 빈 배열이며 기존 운영 데이터는 가져오지 않았다.
- R&D 발견과 IDEA는 다른 파일·모델이다. R&D를 가져오거나 등록하는 것만으로 IDEA가 생성되지 않는다.

## 저장 위치 및 데이터 모델

- `data/tak_rnd_items.json`: 발견 정보, 근거 수준, 점수, 중복 후보, 검토 상태
- `data/tak_idea_vault.json`: 적용 아이디어, 개발 추정, 우선순위 입력, 상태, 검증·구현 결과
- `tak_rnd/models.py`: frozen dataclass, `to_dict()`/`from_dict()`, URL 및 필드 검증
- `tak_rnd/store.py`: JSON persistence, 중복 후보 탐지, 승격·상태·priority 조회

R&D item은 `id`, `captured_at`, `last_updated_at`, `source`, `source_url`, `canonical_url`, `source_author`, `source_item_id`, `title`, `summary`, `key_points`, `technologies`, `categories`, `media`, 1~5 범위의 optional `relevance_score`/`novelty_score`/`expected_impact_score`, `implementation_difficulty`, `evidence_status`, `duplicate_candidate_ids`, 선택적 `canonical_id`, `notes`, `status`를 가진다. URL 또는 source item ID가 있으면 source·정규화된 식별자·제목으로 결정적 `rnd-` + 12자리 SHA-256 prefix ID를 만든다. 외부 JSON을 반복 import해도 동일 source item은 재추가되지 않는다. 고유 외부 식별자가 없는 수동 입력은 충돌 방지를 위해 `rnd-` + 임의 12자리 hex를 사용한다.

IDEA는 `id`, `created_at`, `source_rnd_ids`, `title`, `description`, `why_important`, `application_areas`, `expected_impact`, `implementation_difficulty`, optional `estimated_effort_hours`, 우선순위 입력 점수, `status`, `related_features`, `needs_validation`, `validation_plan`, `implemented_at`, `implementation_result`, `outcome`, `related_content_ids`, duplicate/canonical 연결, `last_updated_at`을 가진다. `related_content_ids`는 향후 게시 플랫폼·언어·포맷·성과 레코드와 join할 수 있는 연결점이며 이번 작업은 성과 집계 로직을 추가하지 않았다.

`source` 값은 `threads`, `web`, `github`, `youtube`, `manual`, `aside`, `other`다. 분류 category는 `ai`, `ai_agent`, `claude_code`, `github`, `automation`, `browser_automation`, `content`, `seo`, `threads`, `youtube`, `shorts`, `multilingual`, `data`, `monetization`, `other`다. 미입력 점수는 `null`이며 자동으로 추정하지 않는다.

## 입력과 중복 처리

수동 CLI 등록과 JSON import가 같은 `RndItem.from_mapping()` 입력 경계를 사용한다. JSON import는 다음을 받을 수 있다.

- Aside 예시 형태의 객체: `source`, `url`, `author`, `captured_at`, `title`, `text`, `media`, `tags`
- 객체 배열
- `{"items": [...]}` wrapper

`platform`은 `source` 별칭, `source_url`은 `url`, `source_author`는 `author`, `summary`는 `text`, `technologies`는 `tags`의 별칭이다. HTTP(S) URL만 허용하며 사용자 정보가 든 URL은 거부한다. canonical 비교 시 scheme/host 대소문자, 기본 port, 끝 slash, fragment, `utm_*`, `fbclid`, `gclid`를 정규화한다. JSON adapter import는 동일 source/source item 또는 stable ID가 이미 저장되어 있으면 건너뛴다. 수동 CLI 등록은 사용자가 의도적으로 다시 입력한 발견도 보존하도록 새 ID를 만들고 중복 후보로 표시한다.

R&D 중복 후보는 동일 canonical URL, 동일 source + `source_item_id`, 정규화한 동일 제목을 사용한다. IDEA는 동일/유사 제목과 공유 `source_rnd_ids`를 후보 기준으로 쓴다. 등록 내용을 자동 삭제하거나 병합하지 않는다. 항목을 별도 보존하며 `duplicate_candidate_ids`에 기존 ID를 기록한다. 검토 후 `link-canonical`으로 canonical 레코드를 지정할 수 있다.

IDEA 우선순위는 전략 적합도·예상 효과·신규성·난이도 입력이 모두 있을 때만 계산한다. 난이도 점수는 low=1, medium=3, high=5이며 공식은 `2 × 적합도 + 2 × 예상 효과 + 신규성 - 난이도`다. 각 입력은 1~5다. 누락 점수는 미평가로 남고 우선순위 목록에서 제외된다. `implemented`, `validated`, `rejected`, `parked` 상태도 현재 개발 후보 우선순위 목록에서 제외한다. 이 점수는 사람 검토용 정렬 값이지 자동 승인 기준이 아니다.

## 상태

- R&D: `captured` → `reviewing` → 필요 시 `promoted`; 또는 `archived`/`rejected`
- IDEA: `captured` → `triaged` → `research` → `proposed` → `approved` → `implementing` → `implemented` → `validated`; 필요하면 `rejected`/`parked`
- 상태 이름은 검증하지만 강제 전이 그래프는 두지 않는다. 사람의 재검토·되돌림을 허용한다.
- `validated`로 바꾸면 `needs_validation=false`가 된다. 거절/보류된 IDEA는 검증 대기 목록에서 제외된다.

## CLI 사용법

저장소 루트에서 실행한다. 기본 JSON 파일 대신 시험 파일을 쓰려면 모든 명령 앞에 `--rnd-store 경로 --idea-store 경로`를 지정한다.

```bash
python3 scripts/tak_rnd.py add-rnd --source threads --url "https://threads.net/@maker/post/123" --author "@maker" --title "Aside 브라우저 에이전트" --summary "브라우저 작업을 보조하는 에이전트" --category browser_automation --technology Aside
python3 scripts/tak_rnd.py list-rnd
python3 scripts/tak_rnd.py import-rnd --file aside-captures.json
python3 scripts/tak_rnd.py show-rnd --id rnd-<id>
python3 scripts/tak_rnd.py promote --rnd-id rnd-<id> --idea-title "TAK AUTO 브라우저 실행 레이어에 Aside 연계"
python3 scripts/tak_rnd.py add-idea --title "브라우저 실행 레이어" --description "Aside 연계 검토" --why-important "반복 수집 작업 시간을 줄일 수 있다" --area browser_automation --difficulty medium --effort-hours 8 --fit-score 4 --impact-score 4 --novelty-score 3
python3 scripts/tak_rnd.py set-status --type idea --id idea-<id> --status research
python3 scripts/tak_rnd.py duplicates
python3 scripts/tak_rnd.py link-canonical --type rnd --duplicate-id rnd-<duplicate> --canonical-id rnd-<canonical>
python3 scripts/tak_rnd.py priority
python3 scripts/tak_rnd.py needs-validation
```

R&D 등록 → 중복 후보/근거 검토 → `promote`로 별도 IDEA 생성 → 우선순위 평가 → research/approved/implementing 상태 관리 → 구현 후 `implemented`/`validated`와 결과 기록 순으로 운영한다. 실제 발견 URL, 작성자, 요약을 확인하고 상태/점수는 사람이 입력한다.

## Aside 연계와 P1 관계

Aside나 다른 브라우저 도구는 로그인/탐색 권한을 TAK AUTO에 넘기지 않고, 수집한 metadata를 JSON으로 내보내 `import-rnd --file`에 전달하면 된다. TAK AUTO는 정규화·중복 후보·저장·IDEA 승격을 맡는다. 이 구현은 브라우저 자동 조작, Threads 크롤링/API, 외부 쓰기, 게시를 수행하지 않는다.

P1 Threads Performance Collection 코드는 변경하지 않았다. IDEA의 `related_content_ids`로 향후 성과 레코드 연결만 준비했으며 P1 스키마·workflow·실제 Threads 호출은 이번 범위가 아니다.

## 검증 및 제한사항

- 신규 R&D/IDEA 모델·저장·CLI 집중 테스트: **15 passed**.
- P1 Performance 전체 관련 테스트(`test_performance_*.py`, `test_collect_performance*.py`): **119 passed**. 사전 기준선의 핵심 P1 테스트 37개도 모두 통과했다.
- 전체 `tests/` 회귀: **1,760 passed, 31 failed, 118 skipped, 297 subtests passed**. 31개 실패는 모두 기존 `tests/test_6_55_shorts_studio.py`에서 Windows 전용 `C:/Windows/Fonts/NotoSansKR-VF.ttf`가 Linux에 없어 발생한 폰트 오류 또는 그로 인한 대시보드 연결 종료다. 알려진 환경 제한이며 이번 변경에서 Shorts Studio 코드는 건드리지 않았다.
- `git diff --check`: 통과. P1 테스트 외 기존 회귀 중 새 R&D/IDEA 관련 실패는 없다.
- 실제 Threads 호출, 로그인, 게시, 외부 서비스 write는 실행하지 않는다.
- 관련성·신규성·효과·난이도 평가는 수동이며, 중복 후보는 휴리스틱이므로 사람이 확인해야 한다. URL이 없는 수동 입력은 제목으로만 R&D 중복을 찾는다.
- JSON은 작은 Git 기반 운영 규모를 위한 단계다. 동시 다중 writer나 대량 조회/검색/권한 관리는 해결하지 않는다.

## 다음 단계

1. 운영자가 수동 등록과 Aside JSON import를 사용하며 입력 필드와 중복 후보 품질을 확인한다.
2. 검토 사례가 쌓이면 category/priority rubric과 duplicate 판정 기준을 조정한다.
3. 필요성이 확인된 뒤에만 브라우저 adapter 또는 성과/Content DNA 연결을 설계한다.

## 완료 기록

- 기준 원격: `origin/main` = `fa9eb32` (2026-10-04 확인)
- 작업 branch: `p2-01-rnd-radar`
- 구현 commit SHA: `cdef92d` (`feat: add TAK AUTO R&D radar and idea vault`)
- push 여부: 완료. `origin/p2-01-rnd-radar`에 push했고 `main`은 수정하지 않았다.
- PR: 아직 생성하지 않았다. push 응답의 제안 URL은 `https://github.com/sopptak/tak-auto/pull/new/p2-01-rnd-radar`.

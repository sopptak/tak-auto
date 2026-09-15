# 5-10 Phase 4-4 — Threads KNOWLEDGE Rotation 구현 보고서

## 1. 문제 정의

직전 원인 분석(`docs/5-10_phase4_4_threads_duplicate_analysis.md`)에서
확정된 문제: Threads 자동 게시(`--auto`)가 "생성 순서대로 첫 번째
unpublished + valid Threads"만 고르기 때문에, 승인 목록 맨 앞에 있고
항상 valid인 KNOWLEDGE 하나(`knowledge-da6ddf5aa459`)가 자신의 Threads
슬롯 5개를 전부 소진할 때까지(최대 5일) 다른 KNOWLEDGE로 절대 넘어가지
못한다. 실제로 2026-09-13~15 3일 연속 이 KNOWLEDGE의 서로 다른 문장이
게시됐다 - content_id는 매번 다르지만 같은 소스 스토리라 "비슷한
소재가 반복된다"는 인상을 준다.

## 2. Phase 4-3까지의 기존 구조

- `content_engine/publish_history.py::select_unpublished_threads_item(items, history)`가
  선택 로직 전부를 담당한다. `items`(배치 결과의 `all_items`)를 **입력
  순서 그대로** 스캔하며, `platform=="threads"`, `status=="valid"`,
  `compute_content_id(item)`이 `history`에 없는 **첫 항목**을 그대로
  반환한다.
- `scripts/publish_threads.py --auto`는 이 함수를 한 번 호출해 결과를
  그대로 게시하고, 성공 시 `history.append(PublishRecord(...))`로 이력을
  남긴다.
- `scripts/run_daily.py`는 `run_media_batch()`로 만든 배치 결과 파일을
  `publish_threads.py --auto --history <path>`에 그대로 넘기기만 한다.
- `PublishHistory`(로드/저장/조회)와 `compute_content_id()`(LLM 재작성
  결과와 무관한 결정적 지문)는 이미 정상 동작하고 있었다(Phase 4-4 원인
  분석에서 재확인) - 문제는 이 둘이 아니라 "이 이력을 어떻게 활용해
  다음 항목을 고르는가"라는 **선택 정책**에만 있었다.

## 3. 실제 원인

`select_unpublished_threads_item()`이 KNOWLEDGE 단위의 "형평성"을 전혀
고려하지 않고, 오직 "배치 결과에 나타난 순서 + 이력에 없음"만으로
고른다. `run_media_batch()`는 승인 KNOWLEDGE를 파일에 등장한 순서
그대로 처리하며 각 KNOWLEDGE마다 Blog 1 + Shorts 3 + Threads 5를 연속
생성하므로, 파일 순서상 가장 앞선 KNOWLEDGE의 Threads 5개가 배치
결과에서도 가장 앞쪽에 몰려 있다. 그 결과 해당 KNOWLEDGE의 Threads
슬롯이 모두 소진되기 전까지는 뒤에 있는 다른 KNOWLEDGE의 Threads가
선택될 기회 자체가 없다.

## 4. 수정한 선택 정책

`select_unpublished_threads_item()` 내부에서만 다음 2단계로 바꿨다
(함수 시그니처·반환 타입은 그대로):

1. **후보 수집**: 기존과 동일하게 `platform=="threads"`,
   `status=="valid"`, 이력에 없는 `content_id`인 항목만 입력 순서대로
   모은다(중복 방지 규칙 무변경).
2. **1순위(rotation)**: 그 후보들 중, `knowledge_id`가 게시 이력에
   **한 번도 등장한 적 없는** 후보를 후보 목록 순서 그대로 찾아 반환한다.
3. **2순위(fallback, 기존 동작)**: 그런 후보가 하나도 없다면(=순환할
   새 KNOWLEDGE가 남아있지 않다면) 후보 목록의 첫 항목을 그대로
   반환한다 - 이것이 정확히 "수정 전" 동작이다.

```python
def _used_knowledge_ids(history: PublishHistory) -> set[str]:
    return {
        str(record.get("knowledge_id") or "")
        for record in history.load()
        if isinstance(record.get("knowledge_id"), str) and record.get("knowledge_id")
    }


def select_unpublished_threads_item(items, history):
    published_ids = history.published_content_ids()
    candidates = []
    for item in items:
        if item.get("platform") != "threads" or item.get("status") != "valid":
            continue
        content_id = compute_content_id(item)
        if content_id in published_ids:
            continue
        candidates.append((item, content_id))

    if not candidates:
        return None

    used_knowledge_ids = _used_knowledge_ids(history)
    for item, content_id in candidates:
        if str(item.get("knowledge_id") or "") not in used_knowledge_ids:
            return item, content_id

    return candidates[0]
```

"최근 N일" 같은 시간 기반 쿨다운이 아니라, **history 전체를 통틀어 그
KNOWLEDGE가 한 번이라도 게시된 적이 있는지**만 본다 - 지시받은 대로
쿨다운 정책은 이번 단계에 넣지 않았다.

## 5. 수정 파일

- `content_engine/publish_history.py` — `select_unpublished_threads_item()`
  내부 로직 + 작은 private 헬�퍼 `_used_knowledge_ids()` 추가. 함수
  시그니처, `compute_content_id()`, `PublishHistory` 클래스, `PublishRecord`는
  **전혀 수정하지 않았다.**
- `tests/test_publish_history.py` — rotation 테스트 9개 추가(기존 테스트는
  한 줄도 수정하지 않음).
- `tests/test_publish_threads_auto_select.py` — CLI(`--auto`) 수준
  회귀 테스트 1개 추가(기존 테스트는 한 줄도 수정하지 않음).

`scripts/publish_threads.py`, `scripts/run_daily.py`,
`.github/workflows/*`, LLM 관련 코드, Blog/Shorts 로직, Naver 관련
코드는 전혀 건드리지 않았다.

## 6. 추가 테스트

`tests/test_publish_history.py::SelectUnpublishedThreadsItemRotationTests`
(9개):

| # | 테스트 | 검증 내용 |
|---|---|---|
| 1 | `test_prefers_knowledge_id_not_yet_in_history` | 서로 다른 knowledge_id가 있으면, 이력에 이미 등장한 KNOWLEDGE보다 아직 등장하지 않은 KNOWLEDGE를 우선 선택 |
| 2 | `test_earlier_generation_order_does_not_override_rotation` | K1의 다음 후보가 생성 순서상 K2보다 앞에 있어도, 아직 미사용인 K2가 우선됨 |
| 3 | `test_falls_back_to_same_knowledge_when_no_other_candidate_exists` | 다른 KNOWLEDGE(K2)에 valid 후보가 없으면 K1의 다음 valid 후보로 fallback |
| 4 | `test_single_knowledge_id_behaves_like_before` | 모든 후보가 같은 knowledge_id면 기존과 동일하게 다음 unpublished 후보 선택 |
| 5 | `test_already_published_content_id_never_reselected_in_rotation` | 이미 이력에 있는 content_id는 rotation에서도 절대 재선택되지 않음 |
| 6 | `test_invalid_candidates_excluded_from_rotation` | valid가 아닌 후보는 rotation 대상에서 제외 |
| 7 | `test_non_threads_platform_excluded_from_rotation` | Blog/Shorts는 rotation 대상에서 제외 |
| 8(회귀) | `test_four_knowledge_records_rotate_before_repeating` | KNOWLEDGE 4개(각 Threads 2개) fixture에서 연속 4회 자동 선택 시 K1→K2→K3→K4 순서로 서로 다른 knowledge_id가 선택되고, 5번째는 다시 K1의 남은 후보로 돌아옴 |
| - | `test_all_items_already_published_returns_none` 등 기존 9개 | 전부 무수정 유지, 재실행하여 통과 재확인 |

`tests/test_publish_threads_auto_select.py`에 추가한 1개
(`test_auto_cli_rotates_across_knowledge_before_repeating`)은 순수
함수가 아니라 `main(["--auto"])` CLI 전체 경로로 3회 연속 실행해
`k-001 → k-002 → k-001` 순서를 확인한다 - `select_unpublished_threads_item()`뿐
아니라 `publish_threads.py`의 호출 지점까지 통합적으로 검증한다.

## 7. 전체 테스트 결과

```
python3 -m unittest discover -s tests -p 'test_*.py'
Ran 360 tests in 13.276s
OK
```

Phase 4-3 종료 시점(351개) + 이번 신규 9개 = **360개 전부 PASS**. 기존
`test_publish_history.py`/`test_publish_threads_auto_select.py`의
기존 테스트(각각 22개, 12개)도 한 줄도 수정하지 않고 전부 재실행해
통과를 재확인했다.

## 8. rotation 시나리오 테스트 결과

`test_four_knowledge_records_rotate_before_repeating`(핵심 회귀 테스트)
결과: K1, K2, K3, K4 각 2개씩 Threads 후보가 있는 fixture에서

- 1회차: K1 (K1의 첫 항목, evidence_unit_ids=["K1:1"])
- 2회차: K2 (K1은 이미 이력에 있으므로 아직 미사용인 K2로 이동)
- 3회차: K3
- 4회차: K4
- **5회차: 다시 K1** - 단, K1의 **두 번째** 항목(evidence_unit_ids=["K1:2"])이
  선택됨 (K1의 이미 게시된 첫 항목이 아니라, 그 다음 미게시 항목으로
  정확히 이어짐)

기대한 순서(`K1→K2→K3→K4→K1(다음 후보)`)와 정확히 일치했다.

## 9. fallback 테스트 결과

- `test_falls_back_to_same_knowledge_when_no_other_candidate_exists`:
  K2의 유일한 Threads 후보가 `status="rejected"`인 상황에서, K1이 이미
  한 번 게시됐음에도 **K1의 다음 후보(K1-2)**가 정상적으로 선택됐다 -
  "다른 KNOWLEDGE의 valid unpublished 후보가 없으면 게시를 막지
  않는다"는 예외 조건이 정확히 구현됨을 확인.
- `test_single_knowledge_id_behaves_like_before`: 승인 KNOWLEDGE가
  사실상 1개뿐인 상황(다른 knowledge_id 자체가 없음)에서는 rotation
  로직이 개입할 여지가 없어 기존과 100% 동일하게 동작함을 확인.

## 10. PublishHistory 중복 방지 유지 여부

**완전히 유지됨.**

- `compute_content_id()`는 한 글자도 수정하지 않았다.
- `PublishHistory.load/append/published_content_ids/is_published`도
  전혀 수정하지 않았다.
- `test_already_published_content_id_never_reselected_in_rotation`으로,
  이미 게시된 content_id 2건(K1, K2 각 1건씩)이 있는 상황에서
  rotation 로직이 개입해도 **어느 쪽도 재선택되지 않고 `None`을
  반환**함을 확인했다 - rotation이 기존 중복 방지 규칙보다 절대
  우선하지 않는다(중복 방지가 항상 먼저 걸러진 뒤에만 rotation이
  적용됨).
- `ComputeContentIdTests`, `PublishHistoryStorageTests`(기존 18개)도
  전부 무수정으로 재실행해 통과했다.

## 11. 운영 데이터 무결성

이번 단계는 코드/테스트 파일만 수정했다. 모든 테스트는
`tempfile.TemporaryDirectory()` 기반 임시 파일만 사용했다. 추가로
**read-only 진단**을 위해 GitHub `origin/main`의 실제
`data/tak_brain_knowledge.json`/`data/threads_publish_log.json`을
`git show origin/main:<path> > /tmp/...`로 임시 파일에 복사해서만
읽었다 - 로컬 `data/` 디렉터리는 전혀 쓰지 않았다(`git status --short
data/` 결과 이번 세션 시작 전부터 있던 `tak_brain_knowledge.json`의
미커밋 변경 외에 새로운 변경 없음을 확인).

**read-only 진단 결과**(origin/main 실제 데이터 기준, 수정 전후 비교):

| KNOWLEDGE | article_type | Threads 5개 상태 |
|---|---|---|
| `knowledge-da6ddf5aa459` (파일 순서 0번째) | None(경험형) | 3개 published, 2개 unpublished |
| `knowledge-e1cc05264953` (1번째) | finance | 5개 전부 unpublished |
| `knowledge-da8e52862a79` (2번째) | workplace | 5개 전부 unpublished |
| `knowledge-a3f43f9bb62e` (9번째) | workplace | 5개 전부 unpublished |

이 실제 데이터로 **다음 선택**을 시뮬레이션(MockRewriteProvider로 재작성
단계를 우회해 rotation 로직만 확인, 실제 파일에 쓰지 않음)한 결과:

- **수정 전(기존) 알고리즘이 골랐을 항목**: `knowledge-da6ddf5aa459`의
  "문제가 남긴 교훈"(4일 연속 같은 KNOWLEDGE)
- **수정 후(신규) 알고리즘이 실제로 고른 항목**:
  `knowledge-e1cc05264953`(은행 대출 재무제표 소재)의 "원문이 제시한
  판단"

실제 운영 데이터로도 수정 효과가 정확히 재현됨을 확인했다(단, 이
시뮬레이션은 읽기 전용이며 실제 파일을 쓰거나 실제 게시를 하지 않았다).

## 12. 실제 발행 여부

**없음.** 실제 Threads API를 호출하지 않았다(모든 테스트가
`ThreadsClient.from_environment`를 mock으로 대체). 실제
GitHub Actions를 실행하지 않았다. 실제 `data/threads_publish_log.json`을
변경하지 않았다(11번 read-only 진단은 `/tmp` 임시 파일에만 썼다).

## 13. 남은 문제

- 이번 rotation은 "이력에 한 번도 없던 KNOWLEDGE 우선"이라는 **이진
  판단**이다. KNOWLEDGE가 3개면 3일 주기로, 10개면 10일 주기로 도는
  식이라 승인 KNOWLEDGE 수가 적을수록 완전한 균등 분배까지는 시간이
  걸린다 - 다만 이는 "승인 KNOWLEDGE를 늘리면 자연히 개선된다"는 성격의
  운영 이슈이지 이번 코드 변경의 결함은 아니다.
  실제로 지금(승인 4건) 기준으로는 최소 4일 안에 KNOWLEDGE가 모두 한
  번씩 소개되고, 이전(최대 5일 동안 한 KNOWLEDGE에 갇힘)보다 뚜렷하게
  나아진다.
- "몇 번이나 게시됐는지"(빈도)까지 고려하는 정교한 균등 분배(예:
  가장 적게 게시된 KNOWLEDGE 우선)는 이번 범위 밖이다 - 지시받은 대로
  "한 번이라도 등장했는지"만 보는 가장 단순한 rotation만 구현했다.
- 요청받은 대로 시간 기반 쿨다운(예: "최근 N일 이내 재게시 금지")은
  추가하지 않았다 - 필요하다면 별도 Phase에서 검토한다.

## 14. 결론

**PASS.**

`select_unpublished_threads_item()` 함수 내부의 최소 변경(약 15줄)만으로
목표를 달성했다: `PublishHistory`/`compute_content_id`/history 저장
로직/`run_daily.py`/GitHub Actions/LLM/Blog/Shorts/Naver 관련 코드는
전혀 건드리지 않았고, 기존 `--index` 수동 선택과 기존 `--auto` 중복
방지 계약도 그대로 유지됐다(기존 테스트 34개 무수정 통과). 신규 9개
테스트로 "다른 KNOWLEDGE 우선 → 후보 없으면 fallback → 이미 게시된
항목은 rotation에서도 재선택 안 됨"이라는 정책이 정확히 구현됐음을
확인했고, 핵심 회귀 시나리오(KNOWLEDGE 4개, 연속 4회 서로 다른 선택 →
5회차에 첫 KNOWLEDGE의 다음 후보로 복귀)도 기대대로 재현됐다. 실제
운영 데이터(read-only)로 시뮬레이션한 결과, 이 수정이 없었다면 4일
연속 같은 KNOWLEDGE가 선택됐을 상황에서 실제로 다른 KNOWLEDGE(은행
대출 소재)로 넘어가는 것을 확인했다 - 다음 실제 스케줄 실행부터 이
효과가 바로 나타날 것으로 예상된다.

---

## 최종 확인

- **수정 파일**: `content_engine/publish_history.py`
- **추가 테스트**: 9개(`tests/test_publish_history.py` 8개 +
  `tests/test_publish_threads_auto_select.py` 1개)
- **전체 테스트**: 360/360 PASS(기존 351 + 신규 9)
- **rotation 시나리오**: K1→K2→K3→K4→K1(다음 후보) 정확히 재현
- **fallback**: 다른 KNOWLEDGE에 valid 후보 없으면 같은 KNOWLEDGE의
  다음 후보로 정상 대체
- **PublishHistory 중복 방지**: 완전히 유지(무수정 + 회귀 테스트로 재확인)
- **운영 데이터**: 변경 없음(read-only 진단만 수행)
- **실제 발행/Actions 실행**: 없음
- **git commit/push**: 없음

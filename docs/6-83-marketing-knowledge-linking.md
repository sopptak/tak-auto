# 6-83 MarketingBrief ↔ 승인 KNOWLEDGE 연결 CLI

> 브리프의 `knowledge_ids`를 JSON 직접 편집 없이 CLI로 관리한다. 6-82까지 완성한 lineage 앞단의 운영 UX다.

코드: `content_engine/marketing/knowledge_links.py`(판정), `content_engine/marketing/store.py`(`link_knowledge`/`unlink_knowledge`), `content_engine/marketing/generation.py`(게이트), CLI: `scripts/marketing_brief.py knowledge`
테스트: `tests/test_marketing_knowledge_links.py`
관련 문서: [6-80](6-80-marketing-brief-to-content.md), [6-82](6-82-marketing-persistence-and-media-bridge-plan.md), 운영 E2E: [6-84](6-84-marketing-operational-e2e.md)

## 왜 필요한가

- generation은 `brief.knowledge_ids`에 있는 **approved** KNOWLEDGE만 사용한다.
- 그런데 `draft --research`가 넣는 KNOWLEDGE는 pending이다. 이미 승인된 다른 KNOWLEDGE를 브리프에 붙이는 방법은 지금까지 `data/tak_marketing_briefs.json`을 직접 편집하는 것뿐이었다.

## 사용

```
python scripts/marketing_brief.py knowledge add BRIEF_ID KNOWLEDGE_ID              # 미리보기
python scripts/marketing_brief.py --write knowledge add BRIEF_ID KNOWLEDGE_ID      # 연결 저장
python scripts/marketing_brief.py knowledge remove BRIEF_ID KNOWLEDGE_ID           # 미리보기
python scripts/marketing_brief.py --write knowledge remove BRIEF_ID KNOWLEDGE_ID   # 해제 저장
```

`add` 미리보기 출력: brief_id(브리프 status), knowledge_id, KNOWLEDGE 존재 여부, KNOWLEDGE status와 approved 여부, 이미 연결되어 있는지, 연결 가능 여부 또는 불가 사유.
`remove` 미리보기 출력: 연결 여부, 제거 후 `knowledge_ids`, 경고(마지막 KNOWLEDGE, approved 브리프, 이미 연결된 콘텐츠), 불가 사유.

종료 코드: 차단되면 `2`, 그 외(미리보기, 저장, 이미 연결됨)는 `0`이다.

KNOWLEDGE는 `data/tak_brain_knowledge.json`에서 읽는다(`tak_brain.knowledge.load_knowledge_records`). KNOWLEDGE 승인 자체는 기존 KNOWLEDGE 검토 도구(`scripts/review_knowledge.py`)로 한다.

### 운영 예

```
# 1) 승인할 KNOWLEDGE가 pending이면 먼저 기존 KNOWLEDGE 검토로 승인한다
python scripts/review_knowledge.py ...
# 2) 연결 미리보기 → 저장
python scripts/marketing_brief.py knowledge add brief-abc knowledge-123
python scripts/marketing_brief.py --write knowledge add brief-abc knowledge-123
# 3) 브리프 상태와 생성 차단 사유 확인 → (approved라면) 생성
python scripts/marketing_brief.py review brief-abc
python scripts/marketing_brief.py --write generate brief-abc --rewrite mock
# 4) 브리프/결정 파일 커밋은 사람이 결정한다(6-82: tak_marketing_briefs.json은 Git source of truth)
```

## 규칙

| 조건 | add | remove |
|---|---|---|
| 브리프가 rejected | 차단 | 차단(rejected 브리프는 편집 불가, `set`과 같은 규칙) |
| KNOWLEDGE가 없음 | 차단 | 허용(이미 연결된 id면 해제 가능) |
| KNOWLEDGE가 pending/rejected | 차단(강제 옵션 없음) | 허용 |
| 이미 연결됨 / 연결 안 됨 | 쓰지 않고 "이미 연결됨" 표시 | 차단("연결되어 있지 않은 KNOWLEDGE") |
| 마지막 KNOWLEDGE 제거 | - | 허용 + 경고. 이후 generate/bridge 차단 |

## 안전 원칙

- **KNOWLEDGE 승인 상태를 우회하지 않는다.** approved만 연결되고, pending/rejected를 강제로 연결하는 옵션은 없다.
  - 연결 이후 KNOWLEDGE가 승인 취소되어도 기존과 같이 생성 단계(`generate_candidates`)가 approved만 다시 고른다.
- **연결은 브리프 승인이 아니다.** `knowledge add/remove`는 브리프 status를 바꾸지 않는다.
  - draft 브리프는 draft로 남는다.
  - approved 브리프도 approved로 남는다. 승인 대상은 마케팅 요소이고, 연결은 생성 입력의 선택이기 때문이다.
- **관계만 바꾼다.** 바뀌는 것은 `knowledge_ids`뿐이다.
  - `content_ids`, `media_generations`(lineage), 후보(`tak_marketing_contents.json`), generation pool, production archive, 성과 데이터는 읽지도 쓰지도 않는다.
  - 이 점은 테스트(`test_remove_keeps_generated_media_and_performance_data`)가 바이트 단위로 확인한다.
- **게이트:** `generation_blockers`에 "연결된 KNOWLEDGE 없음"이 추가되었다. 마지막 KNOWLEDGE를 제거하면 generate와 bridge가 차단되고, 이미 만든 데이터는 그대로 남는다.
- **저장 방식:** 미리보기는 파일을 쓰지 않는다. `--write`는 기존 `store._update`(tempfile + replace 원자적 쓰기)로 브리프 파일만 갱신한다.
- **하위 호환:** `knowledge_ids` 키가 없는 기존 브리프 JSON도 `()`로 읽히고, 연결하면 그 키가 추가된다.

## 수정하지 않은 것

MEDIA 계층(`media_archive.py`, `pipeline.py`, `generator.py`, `run_scout_dashboard.py`, `promote_media_generation.py`, `performance/*`, publisher)과 KNOWLEDGE 저장소/검토 코드(`tak_brain/*`, `scripts/review_knowledge.py`).

## 한계

- 연결 시점의 KNOWLEDGE 품질(근거 단위 수)은 확인하지 않는다. 근거가 부족한 KNOWLEDGE는 기존처럼 generate 단계에서 `insufficient_distinct_evidence`로 건너뛴다.
- 연결/해제 이력(누가, 언제)은 기록하지 않는다. 브리프 파일의 Git 이력이 감사 기록 역할을 한다.
- (6-84에서 해결) 이제 `review`가 연결된 KNOWLEDGE별 현재 승인 상태와 생성 가능한 approved 건수를 출력한다.

## 검증 결과 (2026-10-04)

| 항목 | 결과 |
|---|---|
| 새 테스트 `tests/test_marketing_knowledge_links.py` | 18 passed |
| 전체 테스트 | 2049 passed, 33 failed, 108 skipped (작업 전 2031 passed / 33 failed) |
| 신규 실패 | 없음. 33개는 기존 알려진 실패: `test_6_55_shorts_studio.py`(Windows 폰트/네트워크, 테스트 24 + subtest 7), `test_second_knowledge_correction_and_generation_pool.py`(production archive count 2) |
| 금지 파일 변경(ea90cdc 이후) | 없음: MEDIA 계층, publisher, `tak_brain/*`, `review_knowledge.py`, `.vscode`, `data/` |
| `git diff --check` / secret scan | 통과 / 발견 없음 |
| 커밋 | a703a9f(API+게이트), 5db3ba3(CLI), e748431(문서) |

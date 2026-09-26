# 6-45 Production Shorts Candidate Readiness

## 최종 상태: **BLOCKED_WITH_EXACT_REASON**

> 이 PC에서 사람이 승인할 운영 Shorts 후보를 준비할 수 없다.
> 1. **Production Archive, generation pool, 복구 원본이 어디에도 없다**(git 이력 포함, 사례 A).
> 2. 후보를 만드는 유일한 운영 경로 `scripts/run_media_batch.py --execute`는 **외부 LLM 재작성**이 필수인데,
>    필요한 `TAK_MEDIA_LLM_API_KEY` / `TAK_MEDIA_LLM_ENDPOINT` / `TAK_MEDIA_LLM_MODEL`이 **3개 모두 NOT_SET**이다(Process/User/Machine 범위).
> 3. LLM 없이 생성하는 유일한 방법은 테스트용 `MockRewriteProvider`다. 이것으로 만든 초안을 운영 후보로 generation pool에 넣으면
>    "LLM 재작성과 검증을 거친 후보"로 **위장**하는 셈이라 하지 않았다(지시 5장).
>
> 해제에 필요한 사람의 행동: LLM 자격증명 3개를 설정하거나(권장), 다른 PC의 운영 data/를 recovery source로 가져오기(10장).

| 항목 | 결과 |
|---|---|
| data state | TRACKED 운영 파일 7개 VALID, Production/pool/ShortsScript NOT_PRESENT |
| Production Archive | NOT_PRESENT(사례 A: 실제로 존재하지 않음, git에 커밋된 적도 없음) |
| Shorts 후보 | **0** |
| human approval | BLOCKED(검토할 후보가 없음) |
| 자동 승인·승격·게시·업로드 | 없음 |
| YouTube API 호출 | **0** |
| 외부 API 호출 | 0(LLM 포함) |
| production mutation | 없음(data/ 해시 전후 동일, 새 파일 없음) |
| 코드 변경 | Operator가 이 blocker를 정확히 표시하도록 최소 수정(9장) |
| 테스트 | 1516 tests, failures 0, errors 9(사전 존재 Windows 이슈), skipped 17. 신규 7 tests |
| secret scan | 깨끗함 |

## 1. 6-44 BLOCKED 원인

6-44는 "approved production Shorts가 없다"로 멈췄다. 이번에 그 원인을 끝까지 추적했다:
Production Archive가 없을 뿐 아니라, 그 앞 단계인 **MEDIA generation 자체가 이 PC에서 한 번도 실행된 적이 없고**(pool 파일 0개),
실행하려면 LLM 자격증명이 필요한데 그것이 없다. KNOWLEDGE 승인 단계(6건 approved)까지만 진행된 상태다.

## 2. 현재 PC 데이터 상태

`scripts/audit_data_state.py`(읽기 전용) 결과 요약:

| 파일/경로 | 상태 | Git |
|---|---|---|
| data/tak_media_archive.json | **NOT_PRESENT** | UNTRACKED(화이트리스트에 있지만 한 번도 커밋되지 않음) |
| data/tak_brain_knowledge.json | VALID(28건) | TRACKED |
| data/tak_threads_pending.json | VALID(5건: pending/published) | TRACKED |
| data/scout_sources.json, tak_scout_daily.json | VALID | TRACKED |
| data/threads_publish_log.json | VALID(7건) | TRACKED |
| data/youtube_publish_log.json | VALID(2건: legacy 1, test 1 — 6-43) | TRACKED |
| data/tak_media_batch_e2e_test.json | VALID(샘플, items 0) | TRACKED |
| data/shorts_scripts/ | **NOT_PRESENT** | — |
| data/tak_media_generation_*.json(generation pool) | **NOT_PRESENT(0개)** | 의도적 미추적 |
| data/shorts/ | NOT_PRESENT | — |
| data/blog_publish_log.json | NOT_PRESENT | 미추적 |

git: main == origin/main(`1e6495e`), 시작 시 working tree clean. 브랜치는 main 하나(원격도 origin/main뿐).

## 3. Production Archive 상태 — 사례 판정

| 사례 | 판정 | 근거 |
|---|---|---|
| A. 정말 없음 | **해당** | 파일 없음. `git log --all -- data/tak_media_archive.json` 결과 0건 |
| B. 있지만 비어 있음 | 아님 | 파일 자체가 없음 |
| C. 있지만 못 읽음 | 아님 | 파일 자체가 없음 |
| D. .gitignore 때문에 Git에 없는 운영 데이터 | 아님 | `.gitignore`는 `!data/tak_media_archive.json`로 추적을 **허용**한다. 이 PC에도 없다 |
| E. pool은 있지만 승격 안 됨 | 아님 | pool 파일 0개 |
| F. 복구 가능한 기존 데이터 | **발견 못 함** | 아래 G 검색 결과 |
| G. 다른 경로에 운영 데이터 | **발견 못 함** | 사용자 폴더 전체(AppData 제외)에서 `tak_media*.json`, `*generation*.json`, 다른 `tak-auto*` 폴더를 검색 → 이 저장소의 `tak_media_batch_e2e_test.json`(샘플)만 나옴. D:/E: 드라이브 없음. 원격 브랜치 없음 |

git 이력의 `data/tak_media_batch*.json`/`tak_media_generation*`도 샘플 1건(`c055d71`) 외에는 없다.

## 4. KNOWLEDGE 상태

- 전체 28건, **approved 6건**, pending 13건(Operator: KNOWLEDGE REVIEW 13건).
- approved 6건(전부 `verification_required=True`):

| knowledge_id | article_type / domain | 전략 감사(Operator BLOCKED/RISK) |
|---|---|---|
| knowledge-da6ddf5aa459 | — / 자기계발 | 표시 없음 |
| knowledge-e1cc05264953 | finance / 금융 | STRATEGY_REVIEW_REQUIRED(HIGH_RISK_TOPIC, CATEGORY_UNKNOWN) |
| knowledge-da8e52862a79 | workplace / 직장·인간관계 | 표시 없음 |
| knowledge-a3f43f9bb62e | workplace / 직장·인간관계 | 표시 없음 |
| knowledge-scout-b28b782b2a33 | — / 금융 | STRATEGY_DUPLICATE_RISK |
| knowledge-scout-6d1d0e2fa762 | — / 기타 | STRATEGY_DUPLICATE_RISK |

위험 표시가 없는 3건(`da6ddf5aa459`, `da8e52862a79`, `a3f43f9bb62e`)이 첫 Shorts 생성 대상으로 가장 적합하다.

## 5. MEDIA generation 상태

- generation pool: **0개**. 이 PC에서 MEDIA 생성이 실행된 흔적이 없다.
- `py scripts/run_media_batch.py`(dry-run, 네트워크 없음): 승인 KNOWLEDGE 6건, 예상 Draft 54건(1건당 Blog 1, **Shorts 3**, Threads 5) → 모두 생성하면 Shorts 후보는 최대 18건.
- `--execute`에는 `OpenAICompatibleRewriteProvider.from_environment()`가 필요하다 → LLM 자격증명 3개 모두 **NOT_SET**이라 실행할 수 없다.
- 파이프라인 코드는 provider를 주입할 수 있고 테스트용 `MockRewriteProvider`(docstring: "테스트용 provider")가 있지만, 운영 CLI에는 LLM 없이 생성하는 모드가 없다. 테스트 경로로 운영 후보를 만들지 않았다.

## 6. Shorts 후보 상태

**0건.** Production 승인 Shorts 0, pool의 Shorts 0, ShortsScript 0.
6-40 QA 대본(`artifacts/6-40-content-preview/shorts_scripts/`)과 6-41 장면 설계는 content_id가 없는 QA 산출물이라 후보가 아니다.

## 7. 발견한 lineage

운영 lineage는 **KNOWLEDGE(approved 6건)에서 끊긴다.**

```
KNOWLEDGE approved 6건 ──✗── MEDIA generation(0) ── review ── promote ── Production(0) ── ShortsScript(0) ── MP4 ── YouTube
                        (LLM 자격증명 없음)
```

YouTube 쪽 기록(6-43)은 content_id가 없는 test/legacy 업로드 2건뿐이라 이 lineage와 연결되지 않는다.

## 8. Recovery 가능 여부

- 기존 흐름: `scripts/audit_recovery_source.py --source <다른 PC의 data 사본>`(항상 DRY-RUN, 읽기 전용) → staging → validation → reconciliation → 사람 검토 → `scripts/recover_media_archive.py` 적용.
- **이 PC에는 recovery source가 없다**(3장 G). 그래서 실행할 대상이 없고, 아무것도 staging·적용하지 않았다.
- 다른 PC(예: 과거 문서의 노트북1/Codespaces)에 운영 archive가 있다면 그 `data/` 사본을 가져와 위 흐름으로 **운영자 승인 후에만** 적용해야 한다.

## 9. MEDIA Dashboard 준비 상태

- 코드 경로는 준비돼 있다(이미 구현됨, 다시 만들지 않음): `scripts/run_scout_dashboard.py`가 `data/tak_media_generation_*.json`을 자동 탐색하고,
  `/media/generations` 화면이 후보별로 제목/본문/content_id/generation_id/source_url/검증 상태와 승인·보류 폼을 보여준다
  (테스트 `test_pool_candidate_is_reviewable_in_dashboard`로 확인). 승격 버튼은 없다 — CLI로만 한다(의도된 설계).
- 검토할 데이터가 없어서 지금 Dashboard를 열어도 후보는 0건이다.
- **이번 수정(최소):** Operator가 MEDIA 단계에서 `run_media_batch.py --execute`만 안내하고, 그 명령이 LLM 자격증명 없이는 실패한다는 사실을 보여주지 않았다.
  - `OperatorInputs.media_llm_credentials_present`(새 선택 필드, 기본 None = 확인 안 함 → 기존 호출부·테스트 동작 그대로).
  - MEDIA 단계 WHY에 "TAK_MEDIA_LLM_* 환경변수가 없어 지금은 실행할 수 없습니다" 추가, ACTION을 실제 필요한 인자(`--as-generation --archive data/tak_media_generation_<YYYYMMDD>.json --id <knowledge_id>`)로 구체화.
  - HUMAN ACTION에 "MEDIA LLM: ACTION_REQUIRED" 추가(pool과 Production이 모두 없고 자격증명이 없을 때만). YOUTUBE OAUTH 행과 같은 패턴이다.
  - `operator_control_center.py`와 Dashboard의 Operator 화면이 환경변수 존재 여부(값 아님)를 넘긴다.
- 실제 출력:
  ```
  MEDIA: NOT_PRESENT
      WHY: 아직 MEDIA generation이 없습니다. 생성에 필요한 TAK_MEDIA_LLM_* 환경변수가 없어 지금은 실행할 수 없습니다.
      ACTION: python scripts/run_media_batch.py --execute --as-generation --archive data/tak_media_generation_<YYYYMMDD>.json --id <knowledge_id>
  MEDIA LLM: ACTION_REQUIRED
      WHY: MEDIA generation도 Production Archive도 없고, 생성에 필요한 TAK_MEDIA_LLM_API_KEY/ENDPOINT/MODEL이 설정되지 않았습니다.
  ```

## 10. 운영자가 해야 할 작업

1. **LLM 자격증명 설정**(사람): `TAK_MEDIA_LLM_API_KEY`, `TAK_MEDIA_LLM_ENDPOINT`, `TAK_MEDIA_LLM_MODEL`을 Windows 사용자 환경변수 또는 `.env`(gitignore됨)에 넣는다. 값은 저장소에 쓰지 않는다.
   — 또는 다른 PC의 운영 `data/`가 있으면 8장 recovery 흐름을 쓴다.
2. 후보 생성(권장: 위험 표시 없는 KNOWLEDGE 1건부터, **generation pool로만**):
   ```
   py scripts/run_media_batch.py --execute --as-generation --archive data/tak_media_generation_20260926.json --id knowledge-da8e52862a79
   ```
   Production Archive는 바뀌지 않는다. 결과는 `review_status=unreviewed`로 들어간다.
3. (선택) 후보 영상 미리보기: 승인 전 대본을 로컬에서 렌더링해 본다(업로드 없음).
4. **사람이** `py scripts/run_scout_dashboard.py` → `/media/generations`에서 Shorts 후보를 읽고 승인하거나 보류한다.
5. 승인한 것만 `py scripts/promote_media_generation.py … --execute`로 Production Archive에 승격한다.
6. 그 뒤 6-44 15장 절차(ShortsScript → 렌더 → dry-run 가드 → PRIVATE 업로드 1회)로 이어간다.

## 11. YouTube upload를 하지 않은 이유

이번 작업의 범위가 아니고(지시: PUBLIC/UNLISTED/PRIVATE 업로드 모두 금지), 업로드할 approved content_id도 없다.
이번 세션에서 YouTube API는 **0회** 호출했다(자격증명을 불러오지도 않았다). LLM 등 다른 외부 API도 호출하지 않았다.

## 12. 테스트 결과

| 실행 | 결과 |
|---|---|
| 신규 `tests/test_6_45_shorts_candidate_readiness.py` | **7 OK** — Archive 없음 + LLM 없음 시 정확한 안내, 자격증명이 있거나 확인 안 했을 때는 행동 없음, pool이 있으면 MEDIA REVIEW로 전환, 생성 결과는 unreviewed만·Production 미생성·KNOWLEDGE 불변(테스트는 Mock provider + 임시 pool), Dashboard에 후보 필드와 승인 폼 표시, ShortsScript는 valid+approved+active Shorts만(invalid/미승인/superseded/blog 제외, archive 불변), Archive 없음 → 후보 0. 모든 테스트에서 YouTube urlopen 차단 |
| 전체 회귀 `py -m unittest discover -s tests`(ffmpeg 지정) | **1516 tests, failures 0, errors 9, skipped 17** |

errors 9는 사전 존재 오류다(`subprocess.run(capture_output=True)`의 `stdout=None`, Windows 환경):
test_content_engine 1, test_knowledge_review 1, test_media_batch 2, test_media_viewer 1, test_run_scout_cli 1, test_threads_publisher 3 — 6-41~6-44와 같은 9건이며, 신규 오류는 0건이다.

## 13. 보안 검사

| 검사 | 결과 |
|---|---|
| 자격증명 이름의 추적·미추적 파일 | 0건 |
| 작업 트리 패턴(Google client secret, access/refresh token, API key, OAuth client id, `sk-` 형식 LLM 키) | 0건 |
| git 전체 이력 같은 패턴 | 0건 |
| 환경변수 | 존재 여부(SET/NOT_SET)만 확인하고 값은 읽거나 출력하지 않음 |

## 14. 다음 단계

1. 운영자가 10장 1번(LLM 자격증명) 또는 recovery source를 준비한다 → 준비되면 6-46에서 generation pool 생성까지 진행하고 **READY_FOR_HUMAN_APPROVAL**로 멈춘다(자동 승인 없음).
2. 운영자가 Dashboard에서 승인한 뒤에만 promotion → ShortsScript → 렌더 → PRIVATE 업로드 1회(6-44 절차).
3. 운영 PC 간 Production Archive 동기화 정책(커밋 여부)을 결정한다 — 화이트리스트는 허용하지만 한 번도 커밋되지 않아 PC마다 상태가 다르다.
4. (선택) 사용자가 좋게 본 6-41 v2 렌더러를 ShortsScript 입력과 연결한다.

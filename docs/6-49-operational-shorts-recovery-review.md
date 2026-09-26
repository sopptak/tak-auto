# 6-49 Operational Shorts Recovery Review

## 결론 요약

| 항목 | 결과 |
|---|---|
| candidates | **5** |
| SAFE_TO_APPLY | **2** — content-e787c9201b94a948, content-3ae2d78568210164 |
| FACT_CHECK_REQUIRED | **3** — content-ec0c38b9a20c424c, content-e3b8d986ea6db98e, content-91869ed8be17f3f3 |
| SCHEMA_INVALID / DUPLICATE / CONFLICT / SUPERSEDED / INVALID | 0 / 0 / 0 / 0 / 0 |
| archive apply | **NO** — Production Archive(`data/tak_media_archive.json`)는 여전히 NOT_PRESENT |
| YouTube / Threads / Naver / LLM API | 0 / 0 / 0 / 0 |
| production mutation | NO (`data/` 해시 전후 동일) |
| 테스트 | 1534 tests, failures 0, errors 9(사전 존재 Windows 이슈), skipped 17. 신규 4 tests |
| secret scan | 깨끗함 |

SAFE_TO_APPLY는 "이전에 사람이 승인한 상태 그대로 Production Archive에 되돌려도 안전하다"는 뜻이다.
게시해도 된다는 뜻이 아니다. 게시 전에는 별도 검토가 필요하다(13장).

## 1. recovery source

| 항목 | 값 |
|---|---|
| branch | `origin/codespace-silver-robot-xrr69q9r4r7j3pwq9` → `0547065b4f9b65ada8af6a3c33cc636d97b43345`(main보다 30 커밋 뒤, 데이터 source로만 사용) |
| 사용 방식 | merge / checkout / reset / rebase / cherry-pick 없음. 6-48 staging(`artifacts/6-48-recovery-staging/data`, gitignore 대상)의 파일을 이번에 다시 `git hash-object`로 원본 blob과 대조 → archive 1개, ShortsScript 5개 **모두 일치** |
| main 상태 | branch main, HEAD == origin/main == `2c2ffbd`(6-48), 시작 시 clean. `data/tak_media_archive.json`, `data/shorts_scripts/` 둘 다 없음 |
| 교차 확인 | 기존 테스트(`test_media_versioning_and_promotion`, 이 PC에서는 Production Archive가 없어 skip)의 설명 "6-12 이후 production archive 총 레코드 수는 18(9 legacy + 9 신규)"이 export archive(18건 = generation 없음 9 + `gen-20260920T033856-6e8d98fb` 9)와 정확히 일치한다. export는 6-12 이후의 운영 상태로 보인다 |

## 2. candidate count

export Production Archive 18건 중 조건(platform=shorts, generation_status=valid, review_status=approved, superseded 아님, content_id 있음, 실제 ShortsScript 있음)을 만족하는 것은 **5건**이다.
제외: `example_manman.json`(샘플, content_id 없음), `content-cabd37f3a2745724`(shorts, rejected/unreviewed).

## 3~7. 실제 Shorts 5개 — 식별·상태

| content_id | generation_id | 제목 | knowledge_id | source | review / generation | superseded | main archive | duplicate | schema |
|---|---|---|---|---|---|---|---|---|---|
| content-e787c9201b94a948 | (없음, legacy) | 새로운 기술을 마주하는 나의 기준 | knowledge-scout-b28b782b2a33 | BBC `c14dpgm0rg4o` | approved / valid | 아님 | 없음 | 아님 | OK(cards 2) |
| content-3ae2d78568210164 | (없음, legacy) | 신기술을 마주하는 내 기준 | knowledge-scout-b28b782b2a33 | BBC `c14dpgm0rg4o` | approved / valid | 아님 | 없음 | 아님 | OK(cards 2) |
| content-ec0c38b9a20c424c | gen-20260920T033856-6e8d98fb | AI 의식 연구, 어디까지 허용할까? | knowledge-scout-6d1d0e2fa762 | BBC `c6n07ypqz8kzo` | approved / valid | 아님 | 없음 | 아님 | OK(cards 4) |
| content-e3b8d986ea6db98e | gen-20260920T033856-6e8d98fb | AI 의식 연구, 어디까지 허용해야 할까? | knowledge-scout-6d1d0e2fa762 | BBC `c6n07ypqz8kzo` | approved / valid | 아님 | 없음 | 아님 | OK(cards 3) |
| content-91869ed8be17f3f3 | gen-20260920T033856-6e8d98fb | AI 의식 연구, 어디까지 허용할까? | knowledge-scout-6d1d0e2fa762 | BBC `c6n07ypqz8kzo` | approved / valid | 아님 | 없음 | 아님 | OK(cards 2) |

schema: 현재 `load_archive()`와 `ShortsScript.from_dict()`로 모두 읽힌다. 파일명 = 내부 content_id, ShortsScript의 knowledge_id = archive의 knowledge_id.
두 KNOWLEDGE 모두 현재 main에 있고 `approved`, `verification_required=True`, `current_validity="확인 필요"`이며, Operator에서는 `STRATEGY_DUPLICATE_RISK`로 표시된다.

## 8. fact-check 결과 — 실제 콘텐츠 검토

5개 ShortsScript 전문과 archive의 원본/재작성 본문, evidence를 모두 읽었다. 공통: subtitle 없음, hook은 제목이 맡는다, 별도 CTA 없음,
마지막 화면은 "출처: <BBC URL>", 브랜드는 "티몽의 지혜". 날짜·수치 주장은 5개 모두 없다.

### 8-1. content-e787c9201b94a948 — "새로운 기술을 마주하는 나의 기준"
- card 1: "AI 모델이 전 세계적으로 심각한 피해를 일으킬 수 있다는 우려가 커지는 가운데 나온 요청입니다." — **외부 사실**(BBC 기사 요약문을 한국어로 옮김)
- card 2: "내가 남긴 기준은 분명합니다. 신기술은 두려워 말고 부딪혀서 느껴봐야 한다." — **티몽 의견**(KNOWLEDGE `reusable_principle`)
- 실존 인물·기업 이름: 없음.
- 근거: archive evidence `SOURCE FACT: The call comes amid growing concerns that AI models may become able to inflict serious damage worldwide.`가 KNOWLEDGE `factual_information`과 **글자 그대로 일치**하고, 번역도 원문 의미를 넘지 않는다.
- 판정: **SAFE_TO_APPLY**.
- 참고(게시 전): "나온 요청"이 무엇인지 화면에 설명되지 않는다. 원 기사 제목은 "Anthropic boss Dario Amodei calls for AI development to slow down"이지만 Shorts에는 나오지 않는다.

### 8-2. content-3ae2d78568210164 — "신기술을 마주하는 내 기준"
- card 1: "나는 신기술을 두려워하기보다 직접 부딪혀 느껴봐야 한다고 생각한다." — 의견
- card 2: "다만 AI 모델이 전 세계에 심각한 피해를 줄 수 있게 될지도 모른다는 우려가 커지는 가운데 이런 요청이 나왔다는 점은 함께 살펴볼 필요가 있다." — 외부 사실 + 의견
- 실존 인물·기업 이름: 없음. 근거는 8-1과 같다(evidence = KNOWLEDGE factual_information).
- 판정: **SAFE_TO_APPLY**. 참고: 8-1과 같은 KNOWLEDGE라 주제가 거의 같다. "이런 요청"이 무엇인지 설명이 없다.
- 이력: 이 KNOWLEDGE는 6-05에서 정정·재생성됐다. 6-05/6-16/6-17은 이 두 Shorts에 finance 프로파일 오염이 없고 승인 상태를 유지한다고 결론 냈다(오염은 blog 1건뿐). 정정 재생성본(예: `content-4a2e38caa47ba717`)은 export archive에 승격돼 있지 않다.

### 8-3~8-5. AI consciousness 관련 3건 — 실존 인물 발언 인용 (별도 표시)

| content_id | 인용 방식 | 실존 인물·기업 |
|---|---|---|
| content-ec0c38b9a20c424c | card 1이 **영어 원문 한 문장을 그대로** 표시: `Mustafa Suleyman says he believes rival AI firm Anthropic is in effect teaching Claude it "may be conscious".` 이어서 card 2~4에 의견 3개(투명한 연구·감독 아래 제한적 허용, 범위와 대상 명확화 + 독립 검토, 검증 가능한 피해가 생기면 중단) | Mustafa Suleyman, Anthropic, Claude |
| content-e3b8d986ea6db98e | card 1~2는 의견, **card 3이 같은 영어 문장**을 그대로 표시 | 같음 |
| content-91869ed8be17f3f3 | card 1이 한국어 번역: "Mustafa Suleyman은 경쟁 AI 기업 Anthropic이 Claude에게 '의식이 있을 수 있다'고 사실상 가르치고 있다고 믿는다고 말했습니다. 원문 표현은 \"may be conscious\"입니다." card 2는 의견 3개 | 같음 |

검증 근거 조사(로컬 데이터와 저장소 문서만, 외부 조회 없음):
- 이 문장의 로컬 근거는 **BBC RSS 항목의 한 줄 summary뿐**이다: `data/tak_scout_daily.json` 항목(title "Uncontrolled AI could lead to 'silicon species' rivalling humans, warns Microsoft", published_at 2026-09-17T08:22:12Z)의 summary가 이 문장과 같고, KNOWLEDGE `knowledge-scout-6d1d0e2fa762`의 `lesson`/`factual_information`도 이 문장을 옮긴 것이다.
- 기사 본문, 발언 전문, 발언 시점·장소, 인물의 직함은 **로컬 어디에도 저장돼 있지 않다**. 6-07 문서에 "당시 Microsoft AI 총괄"이라는 설명이 있지만 출처가 적혀 있지 않다.
- KNOWLEDGE는 `verification_required=True`, `current_validity="확인 필요"`이고, 승인 메모는 "SCOUT 인터뷰 테스트 승인"이다.
- 결론: "BBC 피드가 이렇게 요약했다"는 것까지만 로컬에서 확인된다. **Suleyman이 실제로 그렇게 말했는지, 제3자(Anthropic)에 대한 이 주장이 정확히 전달됐는지는 확정할 수 없다.**
- 추가 품질 메모(판정과 별개): ec0c38b9와 e3b8d986은 한국어 Shorts에 영어 문장을 번역 없이 넣었다. ec0c38b9와 91869ed8은 제목이 같다("AI 의식 연구, 어디까지 허용할까?"). 세 개 모두 같은 KNOWLEDGE에서 나와 게시하면 중복된다.
- 판정: 3건 모두 **FACT_CHECK_REQUIRED**. 이 판정은 사실 확인 전에는 SAFE_TO_APPLY로 바꾸지 않는다.

## 9. duplicate 결과

- main에 Production Archive와 ShortsScript가 없다 → 같은 content_id, 같은 content_id/generation_id 없음. **DUPLICATE 0**.
- `data/youtube_publish_log.json`에 5개 content_id 모두 없다(미업로드). 이미 게시된 것도 없다.
- 후보끼리의 중복은 기록 대상이 아니지만, 운영상 같은 KNOWLEDGE에서 2건/3건이 나와 게시 시 내용이 겹친다(8장).

## 10. reconciliation 결과 (기존 도구 재사용, 전부 DRY-RUN)

`scripts/audit_recovery_source.py --source artifacts/6-48-recovery-staging/data`: Archive VALID 18, Conflicts 0, Warnings 1(`example_manman` INVALID), Action REVIEW_REQUIRED.
`scripts/recover_media_archive.py --source … --production-archive data/tak_media_archive.json --verbose`: IDENTICAL 0, NEW 18, CONFLICT 0, BLOCKED 0, INVALID 0, SUPERSEDED 0 → ADD 18, Approval NOT_APPROVED, "Apply는 실행되지 않았습니다".
5개 후보 모두 `[SAFE_TO_REVIEW/ADD]`("target production archive에 이 content_id가 없습니다 - 신규 추가 후보").

| 경우 | 결과 |
|---|---|
| A. 완전히 동일 | 0 |
| B. source에만 존재 | **18(후보 5 포함)** |
| C. main에만 존재 | 0 (main archive 없음) |
| D. 같은 content_id, 다른 generation_id | 0 |
| E. 같은 content_id/generation_id, 다른 내용 SHA | 0 |
| F. superseded 관계 | 0 (export에 superseded 레코드 없음) |
| G. 상태 충돌 | 0 |

도구의 `SAFE_TO_REVIEW`는 구조적 판정이다. 8장의 내용 판정(FACT_CHECK_REQUIRED)은 그것과 별개이고 더 우선한다.

## 11~13. 판정 개수

| 판정 | 개수 | content_id |
|---|---|---|
| SAFE_TO_APPLY | **2** | content-e787c9201b94a948, content-3ae2d78568210164 |
| FACT_CHECK_REQUIRED | **3** | content-ec0c38b9a20c424c, content-e3b8d986ea6db98e, content-91869ed8be17f3f3 |
| CONFLICT | **0** | — |
| SCHEMA_INVALID / DUPLICATE / SUPERSEDED / INVALID | 0 | — |

## 14. 적용하지 않은 이유

1. 이번 단계의 지시가 "검토까지, APPLY 금지"다.
2. 적용은 `--approve <content_id>`로 **사람이 하나씩** 명시해야 한다(기존 recovery 설계). 자동 승인은 없다.
3. 3건은 사실 확인이 끝나지 않았다.
4. 나머지 13건(Threads 9, Blog 2, rejected 2)을 함께 복구할지는 운영자가 정한다 — 이번 검토 범위는 Shorts 5건이다.

## 15. 다음 적용 명령 (운영자가 실행)

사전: `py scripts/audit_data_state.py`로 현재 상태를 기록한다. `data/tak_media_archive.json`이 없으므로 도구가 새로 만든다(기존 데이터를 덮어쓰지 않음).

**SAFE_TO_APPLY 2건만 복구:**
```
py scripts/recover_media_archive.py --source artifacts/6-48-recovery-staging/data --production-archive data/tak_media_archive.json --approve content-e787c9201b94a948 --approve content-3ae2d78568210164 --verbose
py scripts/recover_media_archive.py --source artifacts/6-48-recovery-staging/data --production-archive data/tak_media_archive.json --approve content-e787c9201b94a948 --approve content-3ae2d78568210164 --apply
```
(첫 줄은 dry-run 확인, 둘째 줄이 실제 반영이다. Apply Guard가 막으면 아무것도 쓰지 않는다.)

그 다음 ShortsScript 2개를 복사하고 해시를 확인한다(recovery 도구는 downstream 파일을 쓰지 않는다):
```
mkdir data\shorts_scripts
copy artifacts\6-48-recovery-staging\data\shorts_scripts\content-e787c9201b94a948.json data\shorts_scripts\
copy artifacts\6-48-recovery-staging\data\shorts_scripts\content-3ae2d78568210164.json data\shorts_scripts\
```
기대 SHA-256: e787… = `067e8dbbba11c94456e55cbb49b0166094e0e533a44e794eb9c6dc3277f96970`, 3ae2… = `9c220c5b2f20ef78ca04a15ef60046da43a92a7545230753bd623a5609d83489`.

**FACT_CHECK_REQUIRED 3건:** 운영자가 BBC 기사 원문(`https://www.bbc.co.uk/news/articles/c6n07ypqz8kzo`)에서 발언과 인용을 확인한다. 확인되면 같은 명령에 `--approve`를 추가해 복구하고, 확인되지 않으면 복구하지 않는다(archive에 없으면 게시 경로에 들어가지 않는다).
영어 문장을 그대로 쓴 2건은 게시 전에 편집 여부도 판단한다.

사후: `py scripts/audit_data_state.py`, `py scripts/operator_control_center.py`(Production Archive VALID, RECOVERY 상태 변화), 전체 테스트.

## 안전성 확인

| guard | 확인 |
|---|---|
| archive overwrite guard | main에 archive가 없어 덮어쓸 대상이 없다. 기존 `test_p1_archive_overwrite_guard_closure` 통과. 6-48 테스트: 같은 승인을 다시 실행해도 IDENTICAL, 파일 바이트가 그대로 |
| duplicate guard | reconciliation IDENTICAL/SKIP 경로. 6-48 테스트 + `test_youtube_upload_history_dedup` 통과 |
| superseded guard | export에 superseded 0건. `test_media_superseded_lifecycle`, `test_superseded_downstream_safeguards` 통과 |
| promotion conflict guard | 같은 content_id의 다른 generation은 CONFLICT로 적용되지 않는다(6-48 테스트). `test_media_versioning_and_promotion`, `test_batch_promotion`, `test_generation_review_and_promotion` 통과 |
| git diff | 신규 테스트 1개와 이 문서뿐. `data/` 변경 없음 |

## 테스트

| 실행 | 결과 |
|---|---|
| 신규 `tests/test_6_49_recovered_shorts_review.py`(실제 export commit 기준, 없으면 skip) | **4 OK** — 5건이 valid/approved/active shorts이고 스크립트가 읽히며 출처 URL이 표기됨, 실존 인물·기업 이름이 들어간 후보가 정확히 3건, 그 근거가 `verification_required` KNOWLEDGE의 한 줄 요약뿐, 나머지 2건의 evidence가 KNOWLEDGE 출처 사실과 글자 그대로 일치 |
| recovery/archive/duplicate/superseded/reconciliation/promotion 12개 파일 | 222 tests OK(skip 3: 모두 실제 `data/tak_media_archive.json`이 필요한 기존 테스트) |
| 전체 회귀(ffmpeg 지정) | **1534 tests, failures 0, errors 9, skipped 17** |

errors 9는 사전 존재 오류다(Windows `subprocess.run(capture_output=True)` → `stdout=None`):
test_content_engine 1, test_knowledge_review 1, test_media_batch 2, test_media_viewer 1, test_run_scout_cli 1, test_threads_publisher 3. 신규 오류는 0건이다.

## 보안

| 검사 | 결과 |
|---|---|
| 자격증명 파일(추적·미추적) | 0 |
| 작업 트리 secret 값 패턴 | 0(기존 테스트의 가짜 누출 마커 5건 제외) |
| staging(`artifacts/6-48-recovery-staging`) | 0 |
| export commit 전체 | 0 |

## 외부 호출 / 데이터 변경

YouTube 0, Threads 0, Naver 0, LLM 0, 외부 웹 조회 0.
`data/` 파일 해시 전후 동일: scout_sources `62b192f7…`, tak_brain_knowledge `b10724da…`, tak_media_batch_e2e_test `48ef75ee…`, tak_scout_daily `16e069e1…`,
tak_threads_pending `c9a51eae…`, threads_publish_log `5e7eeede…`, youtube_publish_log `07a027e1…`. Production Archive는 여전히 없다.

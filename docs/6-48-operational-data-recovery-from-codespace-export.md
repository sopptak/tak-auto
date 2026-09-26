# 6-48 Operational Data Recovery from Codespace Export

## 결론 요약

| 항목 | 결과 |
|---|---|
| source branch | **FOUND** — `origin/codespace-silver-robot-xrr69q9r4r7j3pwq9` (commit `0547065`) |
| Production Archive(export) | **VALID, 18건**, 현재 main 스키마와 **COMPATIBLE**(migration 불필요) |
| ShortsScript(export) | 6개 — 운영 5개(content_id 일치, 현재 `ShortsScript` 스키마로 읽힘) + 샘플 1개(`example_manman.json`, content_id 없음 → 제외) |
| approved Shorts | **5건** (valid + approved + not superseded + shorts) — 지시에 적힌 5개 content_id 모두 실제로 존재 |
| recovery | **READY_FOR_HUMAN_APPROVAL** — staging, validation, reconciliation, dry-run까지 끝냈다. **main의 `data/`에는 아무것도 적용하지 않았다** |
| duplicate check | 충돌 0 — main에 Production Archive·ShortsScript가 없어 같은 content_id가 없다. YouTube 기록에도 5개 모두 없다 |
| merge / checkout / rebase / reset | 하지 않음. export 브랜치는 `git show`로 데이터 파일만 읽었다 |
| YouTube API / LLM API | 0 / 0 |
| production mutation | **없음** (data/ 해시 전후 동일, Production Archive는 여전히 NOT_PRESENT) |
| 테스트 | 1530 tests, failures 0, errors 9(사전 존재 Windows 이슈), skipped 17. 신규 7 tests, 기존 테스트 1개를 사실에 맞게 보정(17장) |
| secret scan | export commit 0건, staging 0건. 저장소 패턴 검색에서 나온 5건은 기존 테스트의 가짜 누출 감지 마커(false positive, 18장) |

## 1. Codespace Export 발견

GitHub Codespace의 "Export changes to a branch"로 만든 원격 브랜치에, 이 PC에는 없던 과거 운영 데이터가 커밋돼 있었다.
6-44~6-46에서 "이 PC에는 Production Archive가 없고 git 이력에도 없다"고 한 판단은 **fetch 전 이 clone 기준**으로는 맞았다.
원천은 Codespace 작업 공간에만 있었고, 이번 export로 처음 원격에 올라왔다.

## 2. Export branch 이름

`codespace-silver-robot-xrr69q9r4r7j3pwq9` → `origin/codespace-silver-robot-xrr69q9r4r7j3pwq9` = `0547065b4f9b65ada8af6a3c33cc636d97b43345`
("Pending changes exported from your codespace", 2026-09-26 02:56:18 UTC, author sopptak).

## 3. branch와 main의 관계

- 공통 조상(merge-base): `b5afc71`(2026-09-22, "6-19: record commit hash and push confirmation in report").
- export 브랜치는 그 위에 **커밋 1개**(`0547065`). main은 그 뒤로 **30개 커밋**을 더 진행했다(6-20 ~ 6-46).
- export 커밋이 바꾼 것: 문서 다수(5-10 ~ 5-24), 코드(`content_engine/*`, `scripts/*`, `tests/*`, `.github/workflows/youtube-shorts-upload.yml`, `requirements.txt`),
  Firebase 설정(`.firebaserc`, `firebase.json`, `public/*`), 그리고 **데이터**(`data/tak_media_archive.json`, `data/shorts_scripts/*.json` 6개, `data/blog_draft_0{1,2}_*.md`).

## 4. 전체 merge를 하지 않은 이유

- export 커밋의 코드는 6-19 시점 기반이다. main의 6-20~6-46 변경(recovery, superseded 보호, operator, 6-40/6-41 렌더러, 6-42~6-45 YouTube lineage)과 겹치는 파일을 되돌리거나 충돌시킬 수 있다
  — 예: export에도 `content_engine/shorts_renderer.py`(781줄, 5-17 시절 렌더러로 보임)와 `scripts/render_youtube_short.py`, `youtube_oauth_setup.py`가 있어 main의 같은 경로 파일과 부딪힌다.
- 지시 5장: 운영 데이터만 복구하고 코드·테스트·워크플로·Firebase 설정은 가져오지 않는다.
- 그래서 브랜치를 checkout하지 않고, `git show 0547065:<path>`로 **데이터 파일 7개만** 저장소 밖 staging(`artifacts/`, gitignore 대상)에 꺼냈다.
  꺼낸 파일의 git blob id를 원본 blob id와 비교해 **바이트 단위로 같음**을 확인했다(7개 전부).
- 참고: export의 옛 렌더러·Firebase 페이지·blog 초안 2개는 이번 범위 밖이다. 필요하면 운영자가 따로 판단한다(19장).

## 5. 발견된 Production Archive

`data/tak_media_archive.json` — 39,346 bytes, 18건, content_id 중복 0, `load_archive()`(현재 main 코드) 정상.

| platform | generation_status | review_status | 건수 |
|---|---|---|---|
| threads | valid | approved | 9 |
| shorts | valid | approved | **5** |
| blog | valid | approved | 2 |
| shorts | rejected | unreviewed | 1 (`content-cabd37f3a2745724`, 사유: "사실 범위를 넓히는 표현이 추가되었습니다: 기준") |
| threads | rejected | unreviewed | 1 |

- superseded 레코드 0건. validation_errors가 있는 레코드 2건(= rejected 2건).
- 연결된 KNOWLEDGE: `knowledge-scout-b28b782b2a33`, `knowledge-scout-6d1d0e2fa762` — **둘 다 현재 main의 `data/tak_brain_knowledge.json`에 있고 approved**.
- Threads 10건 중 4건의 content_id가 현재 main의 `data/tak_threads_pending.json`에 이미 있다(같은 lineage라는 증거). `threads_publish_log.json`과 겹치는 것은 0건.

## 6. 발견된 ShortsScript

| 파일 | 내부 content_id | archive 레코드 | knowledge_id 일치 | 현재 `ShortsScript` 스키마 | 판정 |
|---|---|---|---|---|---|
| content-3ae2d78568210164.json | 일치 | shorts/valid/approved | 일치 | OK(cards 2) | 후보 |
| content-91869ed8be17f3f3.json | 일치 | shorts/valid/approved | 일치 | OK(cards 2) | 후보 |
| content-e3b8d986ea6db98e.json | 일치 | shorts/valid/approved | 일치 | OK(cards 3) | 후보 |
| content-e787c9201b94a948.json | 일치 | shorts/valid/approved | 일치 | OK(cards 2) | 후보 |
| content-ec0c38b9a20c424c.json | 일치 | shorts/valid/approved | 일치 | OK(cards 4) | 후보 |
| example_manman.json | **없음** | 없음 | — | OK(cards 4) | **제외**(샘플, 파일명·content_id 불일치 — `audit_recovery_source.py`도 INVALID로 분류) |

## 7. 발견된 approved Shorts 수

**5건.** 지시 7장에 적힌 5개 content_id는 모두 실제로 존재하고, 조건(platform=shorts, valid, approved, not superseded, content_id 있음)을 모두 만족한다. 이 밖의 정상 후보는 없다.

## 8. content_id 목록

approved Shorts(5):

| content_id | knowledge_id | generation_id | 제목(final_title) |
|---|---|---|---|
| content-e787c9201b94a948 | knowledge-scout-b28b782b2a33 | (없음, legacy) | 새로운 기술을 마주하는 나의 기준 |
| content-3ae2d78568210164 | knowledge-scout-b28b782b2a33 | (없음, legacy) | 신기술을 마주하는 내 기준 |
| content-ec0c38b9a20c424c | knowledge-scout-6d1d0e2fa762 | gen-20260920T033856-6e8d98fb | AI 의식 연구, 어디까지 허용할까? |
| content-e3b8d986ea6db98e | knowledge-scout-6d1d0e2fa762 | gen-20260920T033856-6e8d98fb | AI 의식 연구, 어디까지 허용해야 할까? |
| content-91869ed8be17f3f3 | knowledge-scout-6d1d0e2fa762 | gen-20260920T033856-6e8d98fb | AI 의식 연구, 어디까지 허용할까? |

archive 전체 content_id(18): content-3ae2d78568210164, content-4015df0692e0bcc4, content-5971ed5204437cdd, content-5a6b175ac6023db1, content-5e9c2842373b859b,
content-62450803823399d3, content-696790d5bda07e90, content-80a05485e895abf4, content-81d4e7c5723598f6, content-8dc32a88a18c0ede, content-91869ed8be17f3f3,
content-c04f9f6efc86969e, content-cabd37f3a2745724, content-cbcf705b6056c9fc, content-dbf0fb4eb5cfd791, content-e3b8d986ea6db98e, content-e787c9201b94a948, content-ec0c38b9a20c424c.

## 9. generation_id 목록

- `gen-20260920T033856-6e8d98fb` — 9건(knowledge-scout-6d1d0e2fa762에서 생성된 것)
- 없음(None, 6-06 이전 legacy generation) — 9건

## 10. schema compatibility

**COMPATIBLE.**
- export 레코드의 키는 모두 현재 `MediaArchiveRecord` 스키마 안에 있다(모르는 키 0).
- 현재 스키마에서 export에 없는 키는 `superseded_by` 하나(18건 모두). 이 필드는 6-17에서 "없으면 None"으로 읽도록 설계됐다(migration 불필요). `load_archive()`로 18건 모두 정상 로드.
- ShortsScript 5개는 현재 `ShortsScript.from_dict()`와 6-40 렌더러 입력으로 그대로 읽힌다. 6-41 v2 변환(`spec_from_shorts_script`)도 검증을 통과했다(v2 렌더링 자체는 하지 않음).

## 11. recovery 결과

**READY_FOR_HUMAN_APPROVAL** — 적용 전 단계까지만 수행했다.

staging(`C:\Users\soppt\tak-auto\artifacts\6-48-recovery-staging\`, gitignore 대상):
```
data/tak_media_archive.json                      ← export 원본(바이트 동일)
data/tak_media_generation_codespace_export.json  ← 같은 내용의 사본(recover_media_archive.py가 후보를 generation pool 이름 규칙으로 읽기 때문)
data/shorts_scripts/content-*.json (5) + example_manman.json  ← export 원본(바이트 동일)
preview/content-91869ed8be17f3f3.mp4, frame.png  ← 로컬 미리보기(업로드 없음)
```

미리보기: 6-40 운영 렌더러(`scripts/render_youtube_short.py`)로 `content-91869ed8be17f3f3`를 렌더링 → 1080×1920, h264, 16.0초. 프레임을 확인했을 때 한글이 정상이고 잘림도 없었다.
**운영자 참고:** 이 Shorts는 "Mustafa Suleyman은 … Anthropic이 Claude에게 '의식이 있을 수 있다'고 사실상 가르치고 있다고 믿는다고 말했습니다. 원문 표현은 'may be conscious'입니다" 같은
실존 인물의 발언 인용을 담고 있다. 해당 KNOWLEDGE는 `verification_required=True`이고, 현재 Operator에서 두 KNOWLEDGE 모두 `STRATEGY_DUPLICATE_RISK`로 표시된다. 승인 전에 사실 확인이 필요하다.

## 12. staging/reconciliation 결과

1. `py scripts/audit_recovery_source.py --source artifacts/6-48-recovery-staging/data --verbose`(항상 DRY-RUN):
   Archive VALID 18건, Archive issues 없음, Shorts 6 → APPROVED 5(field_consistency=MATCH), INVALID 1(example_manman), **Conflicts 0**, Warnings 1, Action REVIEW_REQUIRED.
2. `py scripts/recover_media_archive.py --source artifacts/6-48-recovery-staging/data --production-archive data/tak_media_archive.json --verbose`(DRY-RUN, `--approve` 없음):
   Reconciliation **NEW 18, IDENTICAL 0, CONFLICT 0, BLOCKED 0, INVALID 0, SUPERSEDED 0** → Potential actions ADD 18. Approval NOT_APPROVED → "Apply는 실행되지 않았습니다".
3. 임시 경로에서 적용 경로 확인(운영 파일 아님): 같은 source로 `--approve content-91869ed8be17f3f3 --apply --production-archive <임시>/tak_media_archive.json` → Apply Guard PASS, 1건만 기록,
   원본 레코드와 **필드 차이 0**. `superseded_by`는 null로 채워진다(설계대로). 이 임시 파일은 scratchpad에만 있고 저장소와 무관하다.

## 13. 충돌 여부

| 비교 | 결과 |
|---|---|
| main `data/tak_media_archive.json` | 없음 → 같은 content_id 없음(SKIP 0, CONFLICT 0) |
| main `data/shorts_scripts/` | 없음 → 충돌 0 |
| main `data/youtube_publish_log.json` | content_id 기록 없음 → 5개 모두 미업로드 |
| main `data/threads_publish_log.json` | export Threads content_id와 겹침 0 |
| main `data/tak_threads_pending.json` | 4건 같은 content_id(같은 lineage). 이번 복구는 pending을 건드리지 않는다 |
| 같은 content_id + 다른 generation | 해당 없음(테스트로 CONFLICT 처리·미적용 확인) |

## 14. SHA-256

source(`git show 0547065:<path>`) = staging(복사본). git blob id도 7개 모두 일치한다.

| 파일 | bytes | SHA-256 |
|---|---|---|
| data/tak_media_archive.json | 39346 | `ebe1249fe36c3fe681660c3659d2199f5ecd4f6949b7890479fac9a4e8ea8d33` (blob `d7db57db565b2d681d2448efec8bbbfe4adf24f9`) |
| data/shorts_scripts/content-3ae2d78568210164.json | 698 | `9c220c5b2f20ef78ca04a15ef60046da43a92a7545230753bd623a5609d83489` |
| data/shorts_scripts/content-91869ed8be17f3f3.json | 988 | `b5e12b374bb506e9fcb5cd9f2654581f37dbf30f918a399cc9b4d5ffea4eae83` |
| data/shorts_scripts/content-e3b8d986ea6db98e.json | 938 | `3655a9c6f7fd64a6743ed5cfebad3b99faab869a4416aec95250e1bb6039831a` |
| data/shorts_scripts/content-e787c9201b94a948.json | 654 | `067e8dbbba11c94456e55cbb49b0166094e0e533a44e794eb9c6dc3277f96970` |
| data/shorts_scripts/content-ec0c38b9a20c424c.json | 952 | `e2a6d05734c22d1a83cd1c3746d44a43724b1e548dd1dd048881a7a21cd2431a` |
| data/shorts_scripts/example_manman.json(제외) | 698 | `39206a0f0b09f433abe31b0b5555a18f713a810bfe825124bca6af73ae4fb28f` |
| data/tak_media_generation_codespace_export.json(staging 사본) | 39346 | `ebe1249f…8d33`(archive와 동일) |
| preview/content-91869ed8be17f3f3.mp4 | — | `e2ca0e7a55b4981c35284f413e8f7670ba2e6526d4e06faf5f6b64fecc2fdaab` |

main `data/` 해시(작업 전후 동일): tak_brain_knowledge `b10724da…`, tak_threads_pending `c9a51eae…`, threads_publish_log `5e7eeede…`,
youtube_publish_log `07a027e1…`, scout_sources `62b192f7…`, tak_scout_daily `16e069e1…`, tak_media_batch_e2e_test `48ef75ee…`.

## 15. YouTube API 호출

**0회.** 업로드·조회 모두 없다. 자격증명도 불러오지 않았다.

## 16. LLM API 호출

**0회.** 새 콘텐츠를 생성하지 않았다(렌더링은 로컬 Pillow + ffmpeg).

## 17. 테스트 결과

| 실행 | 결과 |
|---|---|
| 신규 `tests/test_6_48_codespace_recovery.py` | **7 OK** — legacy export 스키마(superseded_by 없음) 그대로 로드, approved Shorts 판정(superseded/rejected/threads 제외), 승인 없으면 쓰지 않음, `--apply` 없으면 DRY-RUN, 승인한 content_id만 원본과 같은 내용으로 추가·재실행 시 IDENTICAL(중복 추가 없음, 파일 바이트 불변), 같은 content_id의 다른 generation은 CONFLICT로 미적용, **실제 export commit으로 18건·5 approved Shorts·ShortsScript 일치 확인**(export commit이 로컬에 없으면 skip). 소켓 차단(네트워크 없음) |
| 전체 회귀(ffmpeg 지정) | **1530 tests, failures 0, errors 9, skipped 17** |

- errors 9는 사전 존재 오류다(Windows `subprocess.run(capture_output=True)` → `stdout=None`): test_content_engine 1, test_knowledge_review 1, test_media_batch 2, test_media_viewer 1, test_run_scout_cli 1, test_threads_publisher 3.
- **1차 실행에서 신규 실패 1건**: `test_6_39 … test_production_archive_was_never_committed`. 원인은 코드가 아니라 **사실 변화**다 — export 브랜치를 fetch한 뒤에는 `git log --all`에 `data/tak_media_archive.json`이 있으므로 `_ever_tracked_in_git()`가 True(STATE B)를 돌려주는 것이 맞다.
  테스트를 "main 이력에는 없음" + "함수 결과 == `git log --all` 결과"로 나눠 정확하게 고쳤다(skip·삭제 없음). 그 결과 Operator RECOVERY가 `RECOVERY_REQUIRED(STATE B)` — "git 이력에는 있지만 이 PC에는 없음, audit_recovery_source로 검토"를 표시한다. 지금 상황과 정확히 맞다.

## 18. 보안 검사

| 검사 | 결과 |
|---|---|
| export commit 전체(`git show 0547065`) secret 값 패턴 | **0건** |
| export commit의 파일 중 이름이 자격증명류인 것 | `.firebaserc`, `firebase.json`(Firebase 프로젝트 설정), OAuth 관련 문서·스크립트·테스트 — **전부 복구 대상 아님**(코드·설정·문서). `.env`, OAuth JSON, token 파일은 없다 |
| staging(복구 대상) secret 값·키 패턴 | 0건 |
| 저장소 추적·미추적 자격증명 파일 | 0건 |
| 저장소 트리·git 전체 이력 값 패턴 | 5건 — 전부 기존 테스트의 **가짜 누출 감지 마커**(`sk-secret-marker-…-should-never-leak` 등, test_6_35~6_38). 이번 검사부터 `sk-` 패턴에 `-`와 `_`를 포함해 나타난 false positive이며 실제 키가 아니다. export 브랜치에서 온 것이 아니다 |

## 19. 다음 운영자 승인 단계

아래는 **사람이** 판단하고 실행한다. 자동 승인·자동 적용·자동 게시·자동 업로드는 없다.

1. **내용 검토**: staging의 ShortsScript 5개와 미리보기 MP4를 읽는다. 특히 AI 의식 관련 3건은 실존 인물 인용의 사실 확인이 필요하다(11장). 두 KNOWLEDGE의 `STRATEGY_DUPLICATE_RISK` 표시도 확인한다(`py scripts/audit_media_strategy.py`).
2. **Production Archive 복구(content_id별 명시 승인)** — 백업부터:
   ```
   py scripts/audit_data_state.py
   py scripts/recover_media_archive.py --source artifacts/6-48-recovery-staging/data --production-archive data/tak_media_archive.json --verbose
   py scripts/recover_media_archive.py --source artifacts/6-48-recovery-staging/data --production-archive data/tak_media_archive.json ^
       --approve <content_id> [--approve <content_id> ...] --apply
   ```
   Shorts만 먼저 복구할지, Threads/Blog 13건까지 함께 복구할지도 운영자가 정한다(`--approve`로 고른 것만 들어간다). rejected 2건은 복구할 이유가 없다.
3. **ShortsScript 복구**: recovery 도구는 downstream 파일을 쓰지 않는다(설계). 승인한 Shorts만 staging의 `data/shorts_scripts/<content_id>.json`을 `data/shorts_scripts/`로 복사하고 14장 SHA-256과 비교한다.
   (또는 `py scripts/generate_approved_shorts_script.py --content-id <id>`로 다시 만들 수 있지만 `created_at`이 새 값이 되므로, 원본 lineage를 지키려면 복사를 권장한다.)
4. **확인**: `py scripts/audit_data_state.py`, `py scripts/operator_control_center.py`(Production Archive VALID, RECOVERY 상태 변화), 전체 테스트.
5. **Production Archive를 git에 커밋할지** 정책을 정한다(`.gitignore`는 허용하지만 main에는 한 번도 커밋되지 않았다 — 이번 작업에서는 커밋하지 않았다).
6. 복구와 확인이 끝나면 6-44 15장 절차로 이어간다: ShortsScript → 렌더(6-40 또는 v2) → `upload_youtube_short.py --content-id … --privacy private --dry-run` → 가드 통과 시 PRIVATE 업로드 1회.
7. export 브랜치 정리: 필요한 데이터를 복구한 뒤에도 브랜치는 원본 증거로 남겨 두기를 권장한다. 옛 코드(렌더러·Firebase 페이지·blog 초안)가 필요한지는 별도로 판단한다.

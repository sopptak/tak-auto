# 6-46 Operational Data Export Manifest

## 결론 요약

| 항목 | 결과 |
|---|---|
| 판정 | **BLOCKED(목적 데이터 없음)**. 이 PC는 운영 데이터를 가진 PC가 **아니다**. 6-44가 필요로 한 approved production Shorts의 원천(Production Archive / generation pool / ShortsScript)이 이 PC에 없다 |
| 이 PC 확인 | repo `C:\Users\soppt\tak-auto`, branch `main`, HEAD == origin/main(`0bf5955`, 시작 시 clean) — 6-44/6-45를 수행한 같은 PC |
| source data(Production 계열) | **NOT_FOUND** |
| Production Archive | NOT_PRESENT(git 이력에도 없음) |
| Shorts candidates | **0** |
| content lineage | BLOCKED — content_id / generation_id가 0개 |
| export package | **READY — 다만 이 PC에 있는 운영 파일 9개의 스냅샷일 뿐**이고, 그중 8개는 git이 이미 동기화한다. Production 데이터는 들어 있지 않다 |
| export 도구 | **READY** — `scripts/export_operational_data.py`. 실제 운영 데이터를 가진 PC에서 이 도구를 실행해야 한다 |
| secret scan | 깨끗함(package, 작업 트리, git 전체 이력에서 secret 값 0건, 자격증명 파일 0건) |
| YouTube / LLM API 호출 | 0 / 0 |
| production mutation | 없음(원본 해시 전후 동일, destination 적용 없음) |
| 테스트 | 1523 tests, failures 0, errors 9(사전 존재 Windows 이슈), skipped 17. 신규 7 tests |

이번 작업의 본래 목적은 "운영 데이터 보유 PC에서 export"다. 이 PC에서 실행한 결과는 "없다"를 해시와 함께 증명한 것이고,
실제 이관은 **운영 데이터가 있는 PC에서 아래 도구를 실행**해야 가능하다(16장).

## 0. 사용한 도구

`scripts/export_operational_data.py`(신규, 읽기 전용, 네트워크 없음):
- **대상 경로**: `scripts/audit_data_state.py`의 `FILE_SPECS`/`DIR_SPECS`/generation pool 규칙(코드가 실제로 참조하는 경로, 6-21 분류)을 그대로 쓰고,
  코드 grep으로 확인한 참조 경로(성과·인터뷰·스카우트 보조 파일, 배치 스냅샷 `tak_media_batch_*.json`, 6-43 migration 백업, `data/blog_drafts/`)를 더했다.
- **상태 분류**: `content_engine.data_state`의 NOT_PRESENT / EMPTY / VALID / CORRUPTED(CORRUPTED도 숨기지 않고 표시).
- **복사**: 존재하는 파일만 같은 상대 경로(`data/...`)로 복사. 복사 전 원본 해시 → 복사본 해시 → 원본 해시 재확인(원본 변경 감지).
- **자격증명 제외**: 파일 이름이 `.env*`, `client_secret`, `credential`, `token`, `oauth`, `.pem/.p12/.key`이면 내용과 상관없이 복사하지 않고 목록만 남긴다(소스 코드 `.py` 제외).
- **secret 값 검사**: 복사본 내용에서 Google client secret(`GOCSPX-`), access token(`ya29.`), refresh token(`1//0…`), API key(`AIza…`, `sk-…`), OAuth client id,
  `"client_secret"/"refresh_token"/"access_token"/"api_key": "<8자 이상 값>"`을 찾는다. 하나라도 있으면 **package 전체를 지우고 중단**하며, 파일 경로만 보고하고 값은 출력하지 않는다.
- **lineage**: Production Archive와 generation pool을 `load_archive()`로 읽어 content_id / generation_id / knowledge_id를 모으고,
  Production의 `platform=shorts AND generation_status=valid AND review_status=approved AND superseded_by 없음`만 Shorts 후보로 센다.
  후보마다 `data/shorts_scripts/<content_id>.json`, `data/shorts/<content_id>.mp4`, YouTube 기록의 video_id를 연결한다.
- **안전**: 비어 있지 않은 출력 폴더는 덮어쓰지 않는다. `--dry-run`은 아무것도 쓰지 않는다. destination에 적용(APPLY)하는 기능은 없다.

## 1. Export 대상 파일 목록 (이 PC에서 존재하는 것)

| # | 경로 | 분류 | 상태 | Git |
|---|---|---|---|---|
| 1 | data/tak_brain_knowledge.json | KNOWLEDGE(모든 MEDIA의 입력) | VALID | TRACKED |
| 2 | data/tak_threads_pending.json | Threads 검수 대기열 | VALID | TRACKED |
| 3 | data/scout_sources.json | SCOUT 설정 | VALID | TRACKED |
| 4 | data/tak_scout_daily.json | SCOUT 일일 결과 | VALID | TRACKED |
| 5 | data/tak_scout_daily.md | SCOUT 일일 보고 | VALID | TRACKED |
| 6 | data/threads_publish_log.json | publish history(Threads) | VALID | TRACKED |
| 7 | data/youtube_publish_log.json | publish history(YouTube) | VALID | TRACKED |
| 8 | data/tak_media_batch_e2e_test.json | CLI 기본값 샘플 | VALID | TRACKED |
| 9 | data/youtube_publish_log.backup-6-43-20260926T012204Z.json | recovery snapshot(6-43 migration 전) | VALID | IGNORED(`data/*.json`) |

## 2. 실제 경로

source root: `C:\Users\soppt\tak-auto\` + 위 상대 경로.
package: `C:\Users\soppt\tak-auto\artifacts\6-46-operational-data-export\` + 같은 상대 경로, 그리고 `export_manifest.json`.
(`artifacts/`는 `.gitignore` 대상 — package는 git에 들어가지 않는다.)

## 3~5. 파일 크기, SHA-256, schema/status

복사 전 원본 해시와 복사본 해시가 **9개 모두 같다**. 복사 후 원본 해시도 그대로다.

| 경로 | bytes | SHA-256 | status |
|---|---|---|---|
| data/tak_brain_knowledge.json | 58992 | `b10724daf197ab81f72589a8faeed90db0d5ee0414e4f18e29cffa7dd1211a31` | VALID(list, 28) |
| data/tak_threads_pending.json | 8197 | `c9a51eae8ca1b1dc802967587bd79236761c0ef3c36edee0cc7e810ca1326a9a` | VALID(list, 5) |
| data/scout_sources.json | 286 | `62b192f7355159b19683b66a88945b35686d88cee233e6a6fe229e07fcd86e7b` | VALID |
| data/tak_scout_daily.json | 2710 | `16e069e1cd4163ecffb163ab6be47076c440b6b310b971d5a03efc4834416d85` | VALID |
| data/tak_scout_daily.md | 2935 | `cfe2246fe2ba4297c8b6163cafd14a968ced1388e049270a1828e18026229fa1` | VALID |
| data/threads_publish_log.json | 2308 | `5e7eeede28dc8599e4c3cc253b8a3fc38fb13b282c6fa1f0a11ce16de86a8c4a` | VALID(list, 7) |
| data/youtube_publish_log.json | 1479 | `07a027e167033db4bcef85691340ba7087b283b7fd260b464b9594a0d22b20d3` | VALID(list, 2) |
| data/tak_media_batch_e2e_test.json | 38068 | `48ef75eefc8b056b272d5247868cde0779ca3064bc7e30b5bf1963ea1524b983` | VALID(items 0) |
| data/youtube_publish_log.backup-6-43-20260926T012204Z.json | 853 | `e3dcb1cb6bb169a6fb67582c48f712cfbd57026c36eb5fde3195f344eae2505a` | VALID(list, 2) |

코드가 참조하지만 **이 PC에 없는** 경로(NOT_PRESENT, 11개):
`data/tak_media_archive.json`, `data/blog_publish_log.json`, `data/blog_publish_pack_daily.md`, `data/tak_performance.json`,
`data/tak_performance_insights.json`, `data/tak_interview_answers.json`, `data/tak_interview_sessions.json`,
`data/tak_interview_questions.json`, `data/tak_interview_questions.md`, `data/tak_scout_title_translations.json`,
`data/tak_scout_dashboard_skipped.json`. 추가로 `data/shorts_scripts/`, `data/shorts/`, `data/tak_media_generation_*.json`, `data/blog_drafts/`는 파일 0개.
CORRUPTED/EMPTY 파일은 없다. recovery staging 폴더나 recovery report도 없다(`audit_recovery_source.py`에 넘길 source 자체가 없음, 6-45 8장).

## 6. 데이터 간 lineage

```
KNOWLEDGE (28건, approved 6)
   ✗  MEDIA generation pool: 없음
   ✗  Production Archive: 없음 → content_id 0 / generation_id 0
   ✗  ShortsScript: 없음
   ✗  MP4(data/shorts): 없음
YouTube publish log: 2건, 둘 다 content_id 없음(legacy 1, test 1 — 6-43) → 운영 lineage와 연결되지 않음
```

## 7. Shorts candidate 수

**0** (조건: valid AND approved AND not superseded AND platform=shorts, Production Archive 기준).

## 8. content_id 목록

없음(0개). YouTube 기록의 content_id도 전부 빈 값이다.

## 9. generation_id 목록

없음(0개).

## 10. knowledge_id 목록

Production/pool에서 참조하는 knowledge_id: 없음(0개).
참고 — KNOWLEDGE 파일의 approved 6건: knowledge-da6ddf5aa459, knowledge-e1cc05264953, knowledge-da8e52862a79,
knowledge-a3f43f9bb62e, knowledge-scout-b28b782b2a33, knowledge-scout-6d1d0e2fa762(6-45 4장).

## 11. artifact 목록

| artifact | 연결 | package 포함 |
|---|---|---|
| 운영 Shorts MP4(`data/shorts/<content_id>.mp4`) | 없음 | — |
| `artifacts/6-41-shorts-v2/shorts_v2_finance.mp4`(sha256 `aba5b3a8ffd8665a2f42b98c4deea5afeb29808fd2be758175ebd0e4d97944cb`) | YouTube 기록 `RAZ3E4UBj6E`의 `artifact_sha256`(test 업로드) | **제외** — 운영 콘텐츠가 아닌 QA 산출물(28MB). 해시가 publish log에 있어 파일 없이도 재업로드 차단이 동작한다 |
| 그 밖의 6-40/6-41 QA MP4/PNG | 운영 lineage 없음 | 제외 |

## 12. 복구 순서 (source 쪽)

운영 데이터가 있는 PC에서:
1. `git pull` 후 `py scripts/audit_data_state.py`로 상태를 확인한다.
2. `py scripts/export_operational_data.py --dry-run`으로 대상과 Shorts 후보 수를 먼저 확인한다.
3. `py scripts/export_operational_data.py --output <repo 밖 또는 artifacts/ 아래 빈 폴더>`를 실행한다.
4. package의 `export_manifest.json`과 출력의 SHA-256을 기록한다. 중단되면 보고된 파일부터 조사한다(값은 출력되지 않는다).
5. package를 USB나 개인 클라우드 등 **git이 아닌 방법**으로 옮긴다.

## 13. 제외된 secret/credential 파일

- 저장소 안(이 PC): 이름 규칙에 걸린 파일 **0개**(`.env` 없음, OAuth JSON 없음, token/credential 파일 없음).
- 저장소 밖(도구가 스캔하지 않는 위치, 6-42 기록 기준): `%USERPROFILE%\Downloads\client_secret_<client-id>.apps.googleusercontent.com*.json`(OAuth Desktop client JSON 2개) — **절대 package에 넣지 않는다.**
- YouTube 자격증명 3개는 Windows 사용자 환경변수(HKCU)에만 있다 — 파일이 아니라 export 대상이 아니다. destination PC에서는 `scripts/youtube_oauth_authorize.py`로 **새로 인증**한다.
- package 내용 검사: secret 값 0건. 키워드 검색에서 나온 1건(`export_manifest.json`의 `excluded_credential_files`, 빈 목록)은 필드 이름이라 false positive다.

## 14. Git에 넣으면 안 되는 파일

- `artifacts/**`(export package 포함) — gitignore 대상.
- `data/youtube_publish_log.backup-*.json`, generation pool `data/tak_media_generation_*.json`, 배치 스냅샷 — `data/*.json` 규칙으로 무시된다(의도된 설계).
- `.env`, OAuth client JSON, token/credential 파일 — 어떤 경우에도 커밋 금지.
- `data/tak_media_archive.json`: `.gitignore`는 커밋을 **허용**하지만 지금까지 커밋된 적이 없다. 커밋할지는 운영자의 정책 결정이다(6-45 14장). 이번 작업에서는 커밋하지 않았다.

## 15. destination PC에서 필요한 import 순서

아래 "Destination Import Order"를 따른다. 핵심: git으로 이미 동기화되는 TRACKED 8개는 `git pull`이 원본이다.
package의 사본과 해시가 다르면 **덮어쓰지 말고** 어느 쪽이 최신인지 사람이 판단한다.
package에서만 가져와야 하는 것은 Production Archive, generation pool, ShortsScript, MP4, 무시되는 백업 같은 **git 밖 데이터**다.

## 16. 이 PC의 결과가 BLOCKED인 이유와 다음 단계

- 이 PC에는 옮길 Production 데이터가 없다. 만든 package는 이 PC의 현재 상태를 해시로 남긴 스냅샷이다(비교 기준으로 쓸 수 있음).
- **다음 단계:** 운영 데이터가 있는 PC(과거 문서의 "노트북1" 또는 Codespaces 등)에서 `git pull` → `py scripts/export_operational_data.py --dry-run` → 후보 수를 확인한 뒤 export한다.
  그런 PC가 없다면 이관할 원천이 없는 것이므로 6-45 10장 경로(LLM 자격증명 설정 → generation pool → 사람 승인)로 새로 만들어야 한다.

## 17. 테스트 결과

| 실행 | 결과 |
|---|---|
| 신규 `tests/test_6_46_export_operational_data.py` | **7 OK** — manifest 해시·크기·상태(CORRUPTED/NOT_PRESENT 포함), 복사본 해시 = 원본, 자격증명 파일(.env/client_secret/token) 제외·목록화, Shorts 후보 = Production의 valid+approved+active shorts만(superseded/invalid/미승인/blog/미승격 pool 제외), lineage(ShortsScript·MP4·video_id), 원본 불변과 dry-run 무기록, secret 값이면 중단·package 삭제·값 미노출, 비어 있지 않은 출력 폴더 거부, Production 없음 → 후보 0. 모든 테스트에서 소켓 연결을 막았다(네트워크 없음 보장) |
| 전체 회귀 `py -m unittest discover -s tests`(ffmpeg 지정) | **1523 tests, failures 0, errors 9, skipped 17** |

errors 9는 사전 존재 오류다(Windows의 `subprocess.run(capture_output=True)` → `stdout=None`):
test_content_engine 1, test_knowledge_review 1, test_media_batch 2, test_media_viewer 1, test_run_scout_cli 1, test_threads_publisher 3 — 6-41~6-45와 같은 9건이며, 신규 오류는 0건이다.

## 18. Production mutation / API 호출

- 원본 `data/*` 해시는 export 전후 동일하다(`diff` 결과 없음). destination 적용은 없다.
- YouTube API 0회, LLM API 0회. 도구는 네트워크 모듈을 import하지 않는다.
- git 변경: `scripts/export_operational_data.py`, `tests/test_6_46_export_operational_data.py`, 이 문서. package는 커밋하지 않았다.

### Destination Import Order

1. **backup destination** — destination PC의 `data/` 전체를 날짜가 붙은 폴더로 복사하고 해시를 기록한다.
2. **copy export package** — package를 destination 저장소 **밖**(예: `C:\tak-import\<날짜>\`)에 복사한다. `data/`에 바로 넣지 않는다.
3. **verify SHA-256** — `export_manifest.json`의 `sha256_package` 값과 복사한 파일의 해시를 하나씩 비교한다. 하나라도 다르면 중단한다.
4. **audit data state** — destination에서 `py scripts/audit_data_state.py`로 현재 상태를 기록한다.
5. **staging** — package의 `data/`를 recovery source로 지정한다(운영 `data/`와 분리).
6. **validation** — `py scripts/audit_recovery_source.py --source <package>/data --verbose`(항상 dry-run)로 스키마·무결성을 확인한다.
7. **reconciliation** — 같은 도구의 conflicts/warnings로 destination의 기존 데이터(특히 git으로 받은 TRACKED 파일과 publish log)와 비교한다. 충돌은 자동으로 해결하지 않는다.
8. **human review** — 운영자가 충돌·후보(content_id/generation_id/approved 상태)를 직접 검토하고 무엇을 적용할지 결정한다.
9. **explicit apply** — 운영자 승인 후에만 `py scripts/recover_media_archive.py --source <package>/data --production-archive data/tak_media_archive.json --approve <content_id> ... --apply`로 반영한다(`--apply`와 content_id별 `--approve`가 없으면 DRY-RUN). 자동 적용은 없다.
10. **post-import audit** — `py scripts/audit_data_state.py`, `py scripts/operator_control_center.py`, 전체 테스트를 다시 실행해 Production Archive 상태, Shorts 후보 수, publish log 해시를 확인한다.

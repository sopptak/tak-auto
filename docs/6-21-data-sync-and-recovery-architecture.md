# 6-21 Data Sync and Recovery Architecture

## 1. 목적

노트북1(집) / 노트북2(수협) / 향후 Codespaces가 같은 TAK AUTO 코드베이스를
쓰면서도 Production Archive 및 운영 데이터가 유실되거나 잘못 덮어써지지
않도록, 데이터 동기화·보존 구조를 조사하고 설계한다.

이 문서는 "노트북2에 없는 운영 데이터를 복구하는 작업"이 아니다. 노트북2는
새 clone 환경이며, 이 작업 종료 시점까지도 Production Archive는 여전히
`NOT_PRESENT` 상태로 남는다(13장). 이 작업은 그 상태를 **설명 가능하고
안전하게** 만드는 작업이다.

## 2. 현재 운영 데이터 전체 목록

| 파일/디렉터리 | 존재(노트북2) | 생성 주체 | 소비 주체 |
|---|---|---|---|
| `data/tak_brain_knowledge.json` | 있음 | 사람(KNOWLEDGE 승인, Dashboard) | 모든 MEDIA 생성의 입력 |
| `data/tak_threads_pending.json` | 있음 | `content_engine/threads_review.py`(생성 시), 사람(승인) | `publish-approved-threads.yml`, Dashboard |
| `data/scout_sources.json` | 있음 | 사람(직접 편집) | `daily-scout.yml`, `run_scout_dashboard.py` |
| `data/tak_scout_daily.json` / `.md` | 있음 | `daily-scout.yml`(매일 덮어씀) | 사람(Dashboard 열람), `run_interview.py` |
| `data/threads_publish_log.json` | 있음 | `daily-threads-post.yml`, `publish-approved-threads.yml` | 중복 게시 방지(`publish_history.py`) |
| `data/youtube_publish_log.json` | 있음 | `scripts/upload_youtube_short.py` | 중복 업로드 방지 |
| `data/tak_media_batch_e2e_test.json` | 있음 | 과거 세션이 수동 커밋한 샘플 | `publish_threads.py`/`view_media_batch.py`의 CLI 기본값 |
| `data/tak_media_archive.json` | **없음** | `scripts/run_media_batch.py`, `promote_media_generation.py`, `supersede_media_record.py`, MEDIA Dashboard | 거의 모든 downstream(Blog Pack, Shorts, Threads draft, YouTube 업로드, publish eligibility) |
| `data/tak_media_generation_*.json` (generation pool) | 없음 | `scripts/run_media_batch.py --generation-pool` | `promote_media_generation.py`(승격 전 검토) |
| `data/shorts_scripts/*.json` | 없음 | `scripts/generate_approved_shorts_script.py`, `daily-media-prepare.yml` | `scripts/upload_youtube_short.py`, `audit_publish_candidates.py` |
| `data/blog_publish_pack_daily.md` | 없음 | `scripts/generate_blog_publish_pack.py` | 사람(수동 네이버 게시) |
| `data/blog_publish_log.json` | 없음 | `scripts/mark_blog_published.py` | `generate_blog_publish_pack.py`(중복 후보 제외) |
| `data/shorts/*.mp4` | 없음 | 이 저장소 코드가 생성하지 않음(외부 렌더링 산출물로 추정) | `audit_publish_candidates.py`(참고 표시만) |

전체 실제 상태는 이번에 만든 `scripts/audit_data_state.py`(11장)로 언제든
재확인할 수 있다.

## 3. 데이터별 Git 추적 정책

| 파일 | 현재 Git 추적 | `.gitignore` 상태 | 분류 | 유실 시 영향 | 다른 PC에서 필요? | 별도 백업 필요? |
|---|---|---|---|---|---|---|
| `tak_brain_knowledge.json` | TRACKED | 화이트리스트 | A | KNOWLEDGE 승인 이력 전체 유실 | 예(필수) | Git history로 충분 |
| `tak_threads_pending.json` | TRACKED | 화이트리스트 | A | 검수 대기 draft 유실 | 예(필수) | Git history로 충분 |
| `scout_sources.json` | TRACKED | 화이트리스트 | A | 수집 대상 설정 유실 | 예(필수) | Git history로 충분 |
| `tak_scout_daily.json`/`.md` | TRACKED | 화이트리스트 | A | 당일 후보 재계산 필요(치명적 아님) | 예 | 불필요 |
| `threads_publish_log.json` | TRACKED | 화이트리스트 | E | 중복 게시 방지 근거 상실 → 실제 중복 게시 위험 | 예(필수) | Git history로 충분 |
| `youtube_publish_log.json` | TRACKED | 화이트리스트 | E | 중복 업로드 위험 | 예(필수) | Git history로 충분 |
| `tak_media_batch_e2e_test.json` | TRACKED | 화이트리스트 | D | CLI 기본값 예시 상실(운영 영향 없음) | 아니오 | 불필요 |
| `tak_media_archive.json` | **UNTRACKED**(화이트리스트는 있으나 커밋 이력 없음) | 화이트리스트(`!`) | A | **모든 승인/거절/수정 이력 유실 — 가장 치명적** | 예(필수) | 4장 참고 |
| `tak_media_generation_*.json` | IGNORED | 블랭킷 규칙 | C/D | 승격 전 초안 유실(승격된 것은 production archive에 남아 있어 무관) | 아니오(의도적) | 불필요 |
| `shorts_scripts/*.json` | 추적 가능(블랭킷 규칙 밖) | 규칙 없음 | A | "이미 생성됨" 판단 근거 상실 → 중복 생성 | 예 | Git history로 충분 |
| `blog_publish_pack_daily.md` | IGNORED | 명시적 ignore | C | 없음(매 실행 재생성) | 아니오 | 불필요(artifact 14일 보관) |
| `blog_publish_log.json` | IGNORED | 블랭킷 규칙, **화이트리스트 없음** | C(원래 E여야 함) | 블로그 중복 게시 판단 근거가 PC/CI 간 동기화 안 됨 | **정책 불일치 — 8장** | 8장 참고 |

**핵심 조사 질문에 대한 답:**

1. **왜 일부 운영 데이터는 Git에 들어가는가?** — GitHub Actions 러너는 매
   실행마다 새 checkout이라 상태가 없다(stateless). 사람이 로컬/Dashboard에서
   내린 승인·검수 결정이 다음 workflow 실행에서도 보이려면, 그 결정이 담긴
   파일이 git에 있어야 한다(`daily-media-prepare.yml` 주석이 이 원칙을 직접
   명시하고 있다 — 9장 참고).
2. **왜 일부 결과물은 Git에 들어가지 않는가?** — 매 실행마다 결정적으로
   재생성 가능하거나(`tak_scout_daily.*`), 승격 전 임시 초안이라 참고용으로만
   필요하거나(generation pool), 완전히 휘발성 산출물이라 커밋할 이유가
   없기 때문이다(`blog_publish_pack_daily.md`).
3. **현재 정책과 실제 저장소 상태가 일치하는가?** — **아니오, 한 곳
   불일치가 있다.** `tak_media_archive.json`은 화이트리스트에 있지만 main
   브랜치 어떤 커밋에도 존재한 적이 없다(6-20이 이미 발견, 이번에 재확인).
   `blog_publish_log.json`은 threads/youtube 이력과 같은 성격(E: publish
   history/audit)인데 화이트리스트에서 빠져 있다(8장에서 별도 논의).
4. **운영 데이터가 GitHub에 올라가지 않았을 때 어떤 기능이 깨지는가?** —
   9장 참고.
5. **여러 PC에서 사용할 경우 현재 정책의 문제점은 무엇인가?** — 정책(어떤
   파일을 커밋해야 하는가) 자체는 대체로 타당하다. 문제는 **정책을 지키는
   책임이 전적으로 사람에게 있고, 이를 돕는 가시성 도구가 없었다는 점**이다
   — "이 PC에 Production Archive가 있는가/없는가/커밋되어 있는가"를
   확인하려면 지금까지는 `ls`와 `git status`를 수동으로 조합해야 했다. 이번에
   `scripts/audit_data_state.py`(11장)로 이 공백을 메웠다.

**이번에 정책을 바꾸지 않은 것**: `blog_publish_log.json`을 화이트리스트에
추가할지 여부(8장), `tak_media_archive.json`을 실제로 커밋할지 여부(4장의
전제)는 모두 "먼저 조사·설계"만 하고 실행하지 않았다 — 실제 Production
Archive가 생기기 전까지는 이 정책을 실전 검증할 방법이 없고, 지시사항이
"판단은 실제 코드/문서 근거로, 바로 바꾸지 마라"였기 때문이다.

## 4. Production Archive 보호 정책

Production Archive(`data/tak_media_archive.json`)에 대한 방어 로직을
코드에서 직접 확인한 결과, **6-06/6-17/6-18/6-19를 거치며 이미 대부분
구현되어 있었다**. 6-21에서 새로 코드를 추가한 부분은 "파일이 없음"을
드러내는 가시성 하나뿐이다.

| 상황 | 현재 동작(코드 근거) | 6-21에서 추가한 것 |
|---|---|---|
| 존재하지 않을 때 | `load_archive()`(`media_archive.py:338`)가 빈 목록 반환. **파일을 새로 쓰지 않는다** — `save_archive()`는 실제 write 함수(`run_media_batch.py`, `promote_media_generation.py`, `supersede_media_record.py`)가 명시적으로 호출할 때만 실행된다. | `audit_data_state.py`가 이 상태를 `EMPTY`가 아니라 `NOT_PRESENT`로 명확히 표시(11장) |
| 비어 있을 때(`[]`) | `VALID`, 0건. "승인된 콘텐츠가 아직 없음"으로 정상 해석됨 | `audit_data_state.py`가 `VALID`/0건으로 명확히 구분 |
| 손상됐을 때(JSON 파싱 실패) | `load_archive()`가 `MediaArchiveError` 발생(`media_archive.py:346-349`). 모든 호출부(`audit_publish_candidates.py:120-124` 등)가 이를 catch해 오류 메시지 출력 후 종료 코드 1 반환 | `audit_data_state.py`가 `CORRUPTED`로 표시(내용은 출력하지 않음) |
| JSON schema가 잘못됐을 때 | `MediaArchiveRecord.from_dict`/`__post_init__`(`media_archive.py:182-208`)이 필수 필드 누락·잘못된 상태값·`superseded_by`/`review_status` 불일치를 전부 `MediaArchiveError`로 차단 | 없음(이미 충분) |
| 다른 generation의 동일 content_id | `check_promotion_conflict()`(6-18, `media_archive.py:381-411`)가 `ArchiveConflictError`로 자동 overwrite 차단, 명시적 supersede 절차를 안내 | 없음(이미 충분) |
| superseded 상태 | `REVIEW_STATUS_TRANSITIONS` + 6-19 downstream 안전장치(Blog/Shorts/Threads/YouTube 전부 차단, 21개 테스트로 검증됨) | 없음(이미 충분) |

**핵심 원칙 확인**: "새 PC에서 Production Archive가 없다고 해서 빈 archive를
만들어 정상 운영 상태인 것처럼 보이게 하면 안 된다"는 이미 코드 구조에
반영되어 있다 — 어떤 read 경로도 archive를 미리 만들지 않는다. 이번 6-21
작업 중 실행한 935개 테스트, `audit_data_state.py` 실행 전후로도 이 파일은
계속 `NOT_PRESENT`로 남아 있었다(13장에서 검증).

## 5. 멀티 PC 운영 시나리오

### 노트북1
6-19/6-20 이전 세션 문서에서 "노트북1"로 지칭된 환경으로, 과거 세션 기록상
Production Archive를 보유했을 가능성이 있는 환경으로 추정된다(6-20 11장).
이번 작업에서는 접근하지 않았고, 접근을 가정하지도 않았다(지시사항 준수).

### 노트북2
이번 작업을 수행한 환경. 새 clone, Production Archive `NOT_PRESENT`(2장).

### Codespaces
아직 실사용 전. `.github/workflows/daily-media-prepare.yml` 주석이 이미
"사람이 로컬 또는 Codespace에서 MEDIA Dashboard로 승인"이라고 명시하고
있어, Codespaces도 노트북과 동일하게 **로컬 승인 → 커밋 → push**의 한
축으로 설계되어 있었다(기존 설계, 이번에 새로 정의하지 않음). Codespaces
컨테이너가 매번 재생성되는 환경이라면, 컨테이너 재생성 시 커밋되지 않은
`tak_media_archive.json` 변경분은 그대로 유실된다는 점을 노트북보다 더
주의해야 한다.

### 시나리오별 정책

| 시나리오 | 정책 | 근거 |
|---|---|---|
| **A**: 노트북2 코드 작업 → commit → push → 노트북1 작업 시작 | **허용**(표준 git flow) | 코드는 이미 GitHub로 정상 동기화되고 있음(1번째 원칙). 노트북1은 작업 시작 전 `git pull`만 하면 됨 |
| **B**: 노트북1에 Production Archive 존재, 노트북2에는 없음 | **수동 확인 필요** — 노트북2에서 MEDIA 생성/승격/발행 작업을 시작하기 전에 `git log --all -- data/tak_media_archive.json`으로 원격에 커밋 이력이 있는지 먼저 확인. 있으면 pull. 없으면(현재처럼) "이게 최초 생성인지, 노트북1이 아직 push 안 한 것인지"를 코드가 자동으로 구분할 수 없으므로 사람이 먼저 노트북1 상태를 확인해야 함 | 코드에는 "다른 PC의 미push 상태"를 알 방법이 없음(당연히) — 이건 순수히 운영 규율의 문제 |
| **C**: 노트북1/노트북2에 서로 다른 Production Archive 존재 | **자동 merge 금지 + 수동 확인 + 백업 필요** | JSON 배열의 git merge는 라인 단위이므로 자동 merge 시 배열 구조가 깨질 위험이 큼. 병합 전 양쪽 파일을 모두 별도로 백업(단순 `cp`)한 뒤, content_id 단위로 사람이 직접 대조해야 함. 이런 병합 도구는 이번 6-21에서 만들지 않았다 — 실제로 이 상황이 아직 한 번도 발생하지 않았고, "코드를 만들기 위한 코드"를 만들지 말라는 지시와 상충하기 때문 |
| **D**: 동일 content_id가 서로 다른 generation_id로 존재 | **이미 코드로 차단됨** | 6-18 `check_promotion_conflict()`가 `ArchiveConflictError`를 던짐(4장). 멀티 PC 상황이라고 이 보호가 약해지지 않는다 — 어느 PC에서 promotion을 실행하든 동일하게 적용됨 |
| **E**: 한쪽에서 supersede 발생 후 다른 PC가 이전 archive를 push하려는 경우 | **차단(force push 금지) + 수동 확인** | git이 non-fast-forward push를 기본적으로 거부한다(표준 동작, 절대 금지사항의 force push 금지와 일치). pull 시 merge conflict가 나면 자동 merge하지 말고, superseded 상태를 가진 레코드가 있는 쪽을 우선시하며 content_id 단위로 수동 병합 |
| **F**: 두 PC가 서로 다른 운영 데이터를 수정한 뒤 Git conflict 발생 | **자동 merge 금지(특히 JSON) + 수동 확인** | 코드 파일 충돌은 표준 git 방식으로 해결 가능하지만, JSON 운영 데이터는 줄 단위 병합이 의미를 보장하지 않으므로 항상 사람이 `content_id`/`platform` 단위로 직접 검토 |

이 정책들은 기존 SUPERSEDED(6-17), promotion conflict(6-18), same content_id
protection(6-18), publish eligibility(6-15/6-19) 구조와 충돌하지 않는다 —
오히려 D/E 시나리오는 그 기존 보호가 멀티 PC 상황에서도 그대로 작동함을
확인한 것뿐이다.

## 6. Push / Pull 운영 규칙

1. **작업 시작 전 항상 `git fetch` + `git status`로 현재 HEAD와
   origin/main을 비교한다**(이번 6-21 시작 전 검증에서 실제로 수행한 절차와
   동일).
2. HEAD가 origin/main보다 뒤처져 있으면 `git pull --ff-only`만 사용한다.
   `git reset --hard`나 강제 병합으로 로컬 변경을 덮어쓰지 않는다.
3. Production Archive를 다루는 스크립트(`run_media_batch.py`,
   `promote_media_generation.py`, `supersede_media_record.py`)를 실행하기
   전에 `python scripts/audit_data_state.py`로 현재 상태를 먼저 확인한다.
4. Production Archive에 실제 변경이 생겼다면(사람이 승인/거절/supersede),
   그 커밋은 **사람이 직접 검토 후 커밋/push**한다 — 이 저장소의 어떤
   workflow도 `tak_media_archive.json`을 대신 커밋하지 않는다(9장).
5. Force push는 어떤 경우에도 하지 않는다(0번 절대 금지사항과 동일).

## 7. Production Archive 동기화 규칙

- Production Archive는 **사람이 명시적으로 커밋해야만** 다른 PC/CI에
  전파된다 — 코드나 workflow가 자동으로 동기화하지 않는다(설계상 의도,
  `daily-media-prepare.yml` 주석이 명시).
- 동기화 전 반드시 `audit_data_state.py`로 로컬 상태를 확인한다.
- 다른 PC의 Production Archive를 아직 확인하지 못한 상태에서 로컬에 없는
  Production Archive를 새로 생성하는 작업(= 첫 `run_media_batch.py` 실행)을
  시작하기 전에는, 그 PC가 "최초 생성"이 맞는지 사람이 먼저 확인한다
  (5장 시나리오 B).
- generation pool(`tak_media_generation_*.json`)은 동기화 대상이 아니다 —
  승격된 결과만 production archive를 통해 동기화된다(의도된 설계, 4장).

## 8. Superseded / Conflict와 데이터 동기화 관계

- `superseded_by` 필드는 production archive 레코드에만 저장되는 단방향
  필드다(6-17 설계, `media_archive.py:167-180`). 즉 supersede 상태 자체가
  production archive 안에 있으므로, **archive가 정상적으로 동기화되기만
  하면 supersede 상태도 함께 동기화된다** — 별도의 동기화 메커니즘이
  필요하지 않다.
- 문제는 archive가 아직 한 번도 커밋된 적이 없다는 점(3장)이므로, supersede
  상태의 동기화 자체보다 "archive를 언제 처음 커밋할 것인가"가 선행
  과제다.
- 6-19의 downstream 안전장치(Threads/Shorts/YouTube publish 차단)는 로컬
  archive 파일을 읽는 시점의 상태만 본다 — 즉 한 PC가 supersede를 커밋하지
  않은 채 다른 PC에서 구버전 archive로 발행 스크립트를 실행하면, 6-19
  보호는 "그 PC가 보는 archive 기준"으로는 정상 통과된다(구버전에는
  superseded 표시가 없으므로). 이는 코드 버그가 아니라 "동기화되지 않은
  데이터를 신뢰하는" 운영 리스크이며, 해결책은 코드가 아니라 6장의 push/pull
  규칙(작업 전 항상 최신 상태 확인)이다.

## 9. GitHub Actions 영향

`.github/workflows/` 4개 전부를 조사했다(`daily-scout.yml`,
`daily-media-prepare.yml`, `daily-threads-post.yml`,
`publish-approved-threads.yml`).

| workflow | data/ 읽기 | data/ 쓰기+commit | 외부 발행 |
|---|---|---|---|
| `daily-scout.yml` | `scout_sources.json` | `tak_scout_daily.json`, `.md` | 없음 |
| `daily-media-prepare.yml` | `tak_media_archive.json`(읽기 전용), `tak_threads_pending.json` | `shorts_scripts/*.json`만 commit. `blog_publish_pack_daily.md`는 workflow artifact로만(14일 보관, git commit 안 함) | 없음(Threads/YouTube/Naver 전부 미호출 — 파일 상단 주석이 명시) |
| `daily-threads-post.yml` | `tak_threads_pending.json` | `threads_publish_log.json` | Threads 실제 게시 |
| `publish-approved-threads.yml` | `tak_threads_pending.json`, `threads_publish_log.json` | 위 두 파일 | Threads 실제 게시 |

어떤 workflow도 `tak_media_archive.json`을 쓰지 않는다 — 오직 사람이 로컬에서
쓰고 커밋해야 한다(7장).

**"새 노트북에서 git clone만 했을 때" 답**:

- **바로 동작**: `daily-scout.yml`(수집 대상 설정이 이미 커밋돼 있음),
  `daily-media-prepare.yml`은 "실행은 되지만"(에러 없음) Production Archive가
  없으므로 Blog Pack 후보 0건·신규 Shorts 0건으로 사실상 빈 결과를 낸다(정상
  종료, 실패 아님 — `load_archive()`가 빈 목록을 반환할 뿐).
- **운영 데이터가 없어 실질적으로 의미 없는 결과만 내는 것**:
  `daily-threads-post.yml`/`publish-approved-threads.yml`은 `tak_threads_pending.json`에
  이미 커밋된 승인 draft(현재 5건)가 있으면 동작은 하지만, 이 draft들이
  가리키는 원본이 Production Archive에 없으므로 6-19의 supersede 검사 등
  일부 검증이 "archive에 해당 content_id 없음(orphan)"으로 처리될 수 있다
  (6-19 `ThreadsSupersedeBlockTests.test_missing_archive_record_is_not_blocked_orphan_policy_preserved`가
  검증하는 바로 그 정책 — orphan은 차단하지 않는다).
- **로컬에서만 가능**: `run_media_batch.py`로 Production Archive를 처음부터
  새로 생성하는 것, MEDIA Dashboard에서 승인/거절/supersede하는 것 — 전부
  workflow가 아니라 사람이 로컬(또는 Codespaces)에서 실행해야 한다.

## 10. Backup / Recovery

| 방법 | 장점 | 단점 | 채택 여부 |
|---|---|---|---|
| A. Git history | 이미 존재하는 인프라, 추가 설정 불필요, `git log`/`git show`로 임의 시점 복구 가능, 커밋 메시지로 변경 이유 추적 가능 | **archive가 실제로 커밋되어 있어야만** 효과가 있음(현재는 한 번도 커밋된 적 없어 히스토리 자체가 없음) | **주 백업 수단으로 채택** — 단, 4장/7장 원칙(사람이 승인 후 커밋)을 지키는 것이 전제 |
| B. GitHub Actions artifact | 자동 실행 시점의 스냅샷 보존 | `daily-media-prepare.yml`은 `tak_media_archive.json`을 읽기만 하고 artifact로도 남기지 않음(`blog_publish_pack_daily.md`만 artifact) — 현재 archive에는 적용되지 않음, 14일 후 자동 삭제라 장기 보관 부적합 | 채택하지 않음(archive에는 미적용 상태) |
| C. 로컬 백업(수동 cp) | 구현 즉시 가능, 외부 의존성 없음 | 그 PC가 고장/분실되면 함께 유실, 사람이 잊으면 무의미 | 위험한 작업(promotion, supersede) 직전 1회성 수동 백업으로 **보조 수단** 권장(자동화하지 않음) |
| D. 별도 backup 파일(예: `.bak` 커밋) | 별도 구현 불필요 | Git history(A)와 정보 중복 — 사실상 이중 source of truth 위험 | 채택하지 않음(7장 원칙 — 새 source of truth를 불필요하게 만들지 않는다) |
| E. 향후 DB/Supabase | 동시성/조회 성능/멀티 writer에 유리 | 이번 작업 범위 밖(지시사항 명시), 현재 규모(레코드 수십~수백 건)에서 필요성 낮음 | **이번에 도입하지 않음**(지시사항 준수) |
| F. 기타(atomic write) | `media_archive.py`의 `save_archive()`가 이미 `tempfile` + `Path.replace()`로 원자적 쓰기를 하고 있어, 쓰기 도중 프로세스가 죽어도 파일이 반쯤 쓰인 상태로 손상되지 않음 | 이미 있는 보호라 새로 할 일 없음 | 기존 구현 확인만(변경 없음) |

**결론**: 새 백업 시스템을 만들지 않는다. Git history를 주 백업 수단으로
삼되, 그 전제(archive가 실제로 커밋되어 있어야 함)가 아직 충족되지 않았다는
사실 자체가 이번 조사의 핵심 발견이다(3장/4장). 이 전제를 충족시킬지
말지(= archive를 언제 처음 커밋할지)는 실제 Production 운영이 시작되는
시점에 사람이 결정할 사안이며, 이번 6-21 범위에서 그 결정을 대신 내리지
않는다.

## 11. Test Environment와 Production Data 분리

6-20에서 이미 이 원칙 대부분을 구현했다(`skipUnless(PRODUCTION_ARCHIVE_PATH.exists(), ...)`
가드 3곳). 6-21은 이를 재검증하고, 새로 추가한 테스트에도 동일 원칙을
적용했다.

- **Unit test**: `tests/test_audit_data_state.py`의 `JsonFileStatusTests`,
  `DirStatusTests`는 전부 `tempfile.TemporaryDirectory()`만 사용하고 실제
  `data/`를 전혀 참조하지 않는다.
- **Integration test**: `MainDoesNotMutateRepositoryTests`는 실제
  `scripts/audit_data_state.py`를 실행하되, 검증 대상이 "실행 전후로
  `data/` 아래 파일 목록이 바뀌지 않았는가"이므로 읽기 전용성 자체가 테스트
  대상이다(쓰기를 검증하는 게 아니라 "안 쓴다"를 검증).
- **Production regression test**: 기존 6-20이 가드한 3곳은 이번에도 그대로
  유지했다(코드를 건드리지 않았으므로 변경 없음) — Production Archive가
  있는 환경에서는 여전히 엄격하게 실행된다.
- **6-19 tests**: 21/21 PASS, 이번 세션에서 코드/테스트 어느 쪽도 건드리지
  않았다.

## 12. 구현한 코드

- **`scripts/audit_data_state.py`**(신규): 운영 데이터 상태를 보여주는
  읽기 전용 CLI. `NOT_PRESENT`/`EMPTY`/`VALID`/`CORRUPTED` 네 가지 상태를
  구분하며, 파일 내용(특히 secrets)은 절대 출력하지 않는다. 12개 파일/디렉터리
  대상을 다루며, `--json` 플래그로 자동화 스크립트에서도 파싱 가능하다.
- **`data/data_manifest.json`은 만들지 않았다** — 7장 지시사항대로 먼저
  검토한 결과, 정적 manifest 파일은 실행할 때마다 오래된 정보가 될 위험이
  있고(파일이 바뀔 때마다 수동 갱신 필요) 기존 데이터와 사실상 중복되는
  두 번째 source of truth가 된다. 대신 `audit_data_state.py`를 **그때그때
  실행해서 계산하는 방식**으로 대체했다 — 이것이 "더 안전한 방법"이라고
  판단한 근거다(7장 지시사항의 "더 안전한 방법이 있다면 그 방법을
  선택하라"에 해당).
- 그 외 `content_engine`/`scripts`의 기존 코드는 **전혀 수정하지 않았다** —
  4장에서 확인했듯 Production Archive 보호 로직은 이미 충분히 구현되어
  있었고, 새로 발견된 유일한 실제 공백(NOT_PRESENT/EMPTY 구분 가시성)은
  read-only 신규 스크립트로 해결 가능했다.

## 13. 테스트 결과

| 구분 | 결과 |
|---|---|
| 신규 테스트(`tests/test_audit_data_state.py`) | 11 passed, 0 failed, 0 errors |
| 6-19 회귀(`tests/test_superseded_downstream_safeguards.py`) | 21 passed, 0 failed, 0 errors (작업 전후 동일) |
| 전체(`python -m unittest discover -s tests -p "test_*.py"`) | **935 passed(집계상 918 실행+17 skip=935 총계), 0 failed, 0 errors** — `Ran 935 tests ... OK (skipped=17)`. 6-20 종료 시점 924개에서 이번에 추가한 11개(신규 테스트)만큼 늘어난 것과 정확히 일치 |
| skip 17건 | 전부 6-20이 이미 추가한 "Production Archive 파일이 없어 실제 운영 데이터 회귀 테스트를 검증할 수 없다"는 명시적 사유의 skip — 이번에 새로 skip을 추가하지 않았다 |

## 14. 운영 데이터 변경 여부

작업 전후로 확인했다(`git status --short`, `git diff --stat -- data/`).

- `git status --short` 결과: 이번 세션이 만든 `scripts/audit_data_state.py`,
  `tests/test_audit_data_state.py`, 그리고 이 문서(`docs/6-21-*.md`) 외에는
  **아무 변경 없음**.
- `git diff --stat -- data/`: 빈 결과(변경 없음).
- `data/tak_media_archive.json`: 생성되지 않음(여전히 `NOT_PRESENT`).
- `data/tak_media_generation_*.json`: 생성되지 않음.
- `data/shorts_scripts/`: 생성되지 않음.
- `data/blog_drafts/`: 이 이름의 디렉터리는 애초에 이 코드베이스 어디에서도
  참조되지 않는다(`grep -rl blog_drafts`로 확인 — 유일한 참조는 6-20 문서의
  금지 목록 문구뿐). 실존하는 개념이 아니므로 "생성되지 않았다"는 사실
  자체가 당연하다.
- 실제 Threads 게시, YouTube 업로드, Naver 블로그 게시, 외부 API 호출은
  이번 세션에서 전혀 수행하지 않았다(6-19 테스트 로그에 보이는
  "YouTube Shorts 업로드 완료" 등은 전부 테스트 fixture의 fake client 출력이다).

## 15. 남은 위험

- **Production Archive가 아직 한 번도 커밋되지 않았다**는 사실 자체가 가장
  큰 남은 위험이다(3장/4장/10장). 이 문서는 이 상태를 "설명 가능하고
  가시적으로" 만들었을 뿐, 해소하지는 않았다 — 해소하려면 실제 운영
  데이터(사람의 승인 결정)가 먼저 존재해야 하는데, 그 데이터를 이번
  작업에서 만들어서는 안 된다는 절대 금지사항과 직접 상충하기 때문이다.
- `blog_publish_log.json`이 threads/youtube 이력과 달리 화이트리스트에
  없어 PC/CI 간 동기화되지 않는 정책 불일치(3장/8장)는 이번에 고치지
  않았다 — 실제로 이 파일이 아직 어느 PC에도 존재하지 않아, 지금 정책을
  바꿔도 검증할 데이터가 없다.
- 5장 시나리오 C(서로 다른 Production Archive 병합)에 대한 실제 도구는
  아직 없다 — 이 시나리오가 실제로 발생한 적이 없어 지금 만들면 추측성
  구현이 될 위험이 크다.
- `data/shorts/*.mp4`를 실제로 생성하는 코드가 이 저장소 안에 없다 — 렌더링
  파이프라인이 어디에 있는지(다른 저장소인지, 사람이 수동으로 만드는지)는
  이번 조사 범위 밖이라 확인하지 못했다.

## 16. 향후 10월 1일 이후 개선안

- Production Archive를 언제·어떻게 처음 커밋할지에 대한 사람의 결정이
  내려지면, 그 결정에 맞춰 `.gitignore` 주석과 `daily-media-prepare.yml`
  주석을 실태에 맞게 정리한다(6-20 11장에서 이미 제기된 질문의 연장).
- `blog_publish_log.json`의 화이트리스트 포함 여부를 결정한다(8장).
- 시나리오 C(서로 다른 Production Archive 병합)가 실제로 발생하면, 그때
  `content_id` 단위 diff/병합 CLI를 만든다(추측성으로 미리 만들지 않는다는
  이번 판단을 유지).
- `data/shorts/*.mp4` 렌더링 파이프라인의 소재를 확인하고, 필요하다면 이
  문서의 2장 표에 정확한 생성 주체를 채운다.
- **운영 원칙 요약(이번 작업에서 확정)**:
  - 코드는 GitHub를 통해 동기화한다.
  - 운영 데이터는 코드와 동일한 방식으로 자동 동기화된다고 가정하지 않는다.
  - Production Archive는 존재 여부와 무결성을 먼저 확인한다
    (`scripts/audit_data_state.py`).
  - 원본 운영 데이터를 발견하기 전 빈 archive를 생성하지 않는다.
  - 동일 content_id의 무단 덮어쓰기를 허용하지 않는다(6-18, 이미 코드로
    강제됨).

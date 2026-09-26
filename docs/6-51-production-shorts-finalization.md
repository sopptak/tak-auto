# 6-51 Production Shorts Finalization & Local Preview

LOCAL PREVIEW ONLY. YouTube/Threads/Naver/LLM API 호출 0. Production Archive·ShortsScript 변경 없음
(렌더 전후 sha256 동일). MP4는 `artifacts/`(git ignore)에만 있다.

## 결론 요약

| 항목 | 결과 |
|---|---|
| 최종 후보 | **5** (FACT_CHECK_FAILED 0건이라 제외 없음) |
| fact-check | PASSED 2(ec0c38b9, e3b8d986), PARTIAL 1(91869ed8), 대상 아님 2(6-50 적용분) |
| PARTIAL 처리 | 수정 draft 1건 작성(`review_status: draft`, 미적용·미승인). 원본 그대로 |
| MP4 | **5개**, 전부 1080x1920 / H.264 / AAC stereo / 30fps, 품질검사 5/5 PASS |
| lineage | 5/5 content_id·generation_id·ShortsScript sha256·spec sha256·MP4 sha256 기록 |
| 지금 업로드 가드 통과 | **2** (e787c920, 3ae2d785). 나머지 3건은 Production Archive에 없어 ORPHAN으로 차단됨(정상) |
| production archive mutation | NO — `data/tak_media_archive.json` sha256 `bdc4cdb6…f269`(6-50과 동일) |
| 테스트 | 최종 1536 tests OK, skipped 11(1차 실행 failures 1은 6-50 커밋이 깨뜨린 기존 테스트 가정 — 보정) |
| secret scan | 깨끗함 |

## 1. 현재 상태 확인 (main `f2b74a2`, clean)

| 대상 | 상태 |
|---|---|
| Production Archive `data/tak_media_archive.json` | VALID, 2건(content-e787c9201b94a948, content-3ae2d78568210164). 둘 다 approved / valid / superseded_by null |
| `data/shorts_scripts/` | 2개(위 2건). sha256이 6-50 기록과 일치 |
| generation pool | Production에는 없음. staging(`artifacts/6-48-recovery-staging/data/`)에 export 18건 |
| fact-check 3건 | staging archive에만 있음. approved / valid / superseded_by null, generation `gen-20260920T033856-6e8d98fb` |
| Operator | PRODUCTION ARCHIVE VALID(2), YouTube Shorts NEEDS_HUMAN_REVIEW(2), RECOVERY NOT_REQUIRED |
| YouTube publish log | 5개 content_id 모두 업로드 기록 없음 |

## 2. 최종 후보 5개

| # | content_id | generation_id | title | knowledge_id | platform | review | generation | fact check | superseded | publish readiness |
|---|---|---|---|---|---|---|---|---|---|---|
| 01 | content-e787c9201b94a948 | (없음, legacy) | 새로운 기술을 마주하는 나의 기준 | knowledge-scout-b28b782b2a33 | shorts | approved | valid | 대상 아님(6-50 적용분) | 아님 | **ELIGIBLE**(업로드 가드 통과), 사람 검토 필요 |
| 02 | content-3ae2d78568210164 | (없음, legacy) | 신기술을 마주하는 내 기준 | knowledge-scout-b28b782b2a33 | shorts | approved | valid | 대상 아님(6-50 적용분) | 아님 | **ELIGIBLE**, 사람 검토 필요 |
| 03 | content-ec0c38b9a20c424c | gen-20260920T033856-6e8d98fb | AI 의식 연구, 어디까지 허용할까? | knowledge-scout-6d1d0e2fa762 | shorts | approved | valid | **PASSED** | 아님 | BLOCKED — Production Archive에 없음(ORPHAN) |
| 04 | content-e3b8d986ea6db98e | gen-20260920T033856-6e8d98fb | AI 의식 연구, 어디까지 허용해야 할까? | knowledge-scout-6d1d0e2fa762 | shorts | approved | valid | **PASSED** | 아님 | BLOCKED — ORPHAN |
| 05 | content-91869ed8be17f3f3 | gen-20260920T033856-6e8d98fb | AI 의식 연구, 어디까지 허용할까? | knowledge-scout-6d1d0e2fa762 | shorts | approved | valid | **PARTIAL** (별도 표시) | 아님 | BLOCKED — ORPHAN + PARTIAL |

publish readiness는 기존 `scripts/upload_youtube_short.py`의 `check_shorts_upload_eligibility()`(순수 함수, API 없음)로 판정했다.

## 3. PARTIAL 처리 (content-91869ed8be17f3f3)

문제 문장(card 1): `Mustafa Suleyman은 경쟁 AI 기업 Anthropic이 Claude에게 “의식이 있을 수 있다”고 사실상 가르치고 있다고 믿는다고 말했습니다. 원문 표현은 "may be conscious"입니다.`

판정: **의역을 인용처럼 표기**한 것. 6-50 근거상 직접 인용으로 확인된 건 영어 구절 `may be conscious`뿐이다(BBC 2026-09-17, Suleyman 에세이 2026-09-16). 한국어 “의식이 있을 수 있다”는 번역이고, 1차 출처는 말이 아니라 글이다.

draft(원본 미변경, 자동 승인 없음) — `artifacts/6-51-shorts-preview/drafts/content-91869ed8be17f3f3.draft.json`, `review_status: "draft"`, `applied: false`:

| | 문장 |
|---|---|
| before | Mustafa Suleyman은 경쟁 AI 기업 Anthropic이 Claude에게 **“의식이 있을 수 있다”**고 사실상 가르치고 있다고 **믿는다고 말했습니다**. 원문 표현은 "may be conscious"입니다. |
| after(draft) | Mustafa Suleyman은 경쟁 AI 기업 Anthropic이 사실상 Claude에게 의식이 있을 수 있다고 가르치고 있다고 **주장했습니다**. 원문 표현은 "may be conscious"입니다. |

- 한국어 번역 따옴표 제거(의역 표시), "믿는다고 말했습니다" → "주장했습니다". 영어 직접 인용은 그대로.
- 새 사실 추가 없음, 의미 확대 없음, 발언 창작 없음. card 2(의견)는 그대로.
- 반영하려면 기존 흐름(Dashboard edit → 재검증 → supersede/새 generation)으로 사람이 진행해야 한다. 이번에는 하지 않았다.
- **MP4 05는 draft가 아니라 원본(approved) ShortsScript로 렌더했다** — lineage를 원본 content_id에 정확히 묶기 위해서다.

## 4. Renderer 연결

- 6-41 Shorts V2 렌더러(`content_engine/shorts_v2_renderer.py`)를 수정 없이 사용. STYLE C "ai"(검정 + 라임, Noto Sans KR 900, 어절 pop, punch 전환, 진행 바, 워터마크, 브랜드 엔드카드 "티몽의 지혜"), 120 BPM.
- 새 스크립트 `scripts/render_production_shorts_preview.py`: ShortsScript → V2 장면 설계 → MP4 → ffprobe → 미리보기 → 품질검사 → manifest. 6-41 `render_shorts_v2.py`의 `probe()`/`extract_previews()` 재사용.
- 장면 구성: HOOK = title, INFO = 카드 문장, 마지막 INFO에 출처 보조문구, BRAND 엔드카드.
- **문장은 한 글자도 바꾸지 않았다.** 6-41 규칙(한 화면 최대 3줄, 폰트 축소 금지, 안전영역)에 맞추려고 문장 경계 → 어절 경계에서만 장면을 나눴다(길이 균등 분할). 안전영역보다 긴 어절 하나(`conscious"입니다.`, 05)는 공백을 넣지 않고 닫는 따옴표 뒤에 줄바꿈만 넣었다.
- 출처: 화면에는 `출처: bbc.co.uk`(전체 경로는 안전영역 폭 초과). 전체 URL은 manifest/이 문서에 있다.
- 01·02는 글이 적어 25초 하한에 못 미쳐, 새 문장 없이 본문 장면을 박자 단위로 더 오래 보여준다(장면당 4~5.5초).
- `*강조*` 표시는 원문에 없어 넣지 않았다(콘텐츠를 바꾸지 않기 위해). 그래서 6-41 샘플보다 강조 박스가 없다.

## 5. 생성된 MP4 (`C:\Users\soppt\tak-auto\artifacts\6-51-shorts-preview\`)

```
01_content-e787c9201b94a948.mp4
02_content-3ae2d78568210164.mp4
03_content-ec0c38b9a20c424c.mp4
04_content-e3b8d986ea6db98e.mp4
05_content-91869ed8be17f3f3.mp4
manifest.json            lineage + ffprobe + 품질검사 전체
specs/*.spec.json        각 MP4를 만든 장면 설계
preview/*_{01,15,mid,80,last}.png, preview/guides/*_safe.png   (MP4에서 추출, 안전영역 가이드)
frames/<name>/sceneNN.png                                        (장면별 가운데 프레임, 빈 화면 검사용)
drafts/content-91869ed8be17f3f3.draft.json
```

## 6. MP4 metadata (ffprobe)

| # | size (bytes) | duration | resolution | fps | video | audio | 장면 |
|---|---|---|---|---|---|---|---|
| 01 | 21,493,685 | 25.0s | 1080x1920 | 30 | h264 | aac 2ch | 6 |
| 02 | 21,499,593 | 25.0s | 1080x1920 | 30 | h264 | aac 2ch | 7 |
| 03 | 31,360,550 | 35.5s | 1080x1920 | 30 | h264 | aac 2ch | 12 |
| 04 | 30,699,813 | 35.0s | 1080x1920 | 30 | h264 | aac 2ch | 12 |
| 05 | 31,591,616 | 35.0s | 1080x1920 | 30 | h264 | aac 2ch | 14 |

## 7. Lineage

| # | content_id | generation_id | archive 출처 | ShortsScript (sha256 앞 16) | MP4 sha256 |
|---|---|---|---|---|---|
| 01 | content-e787c9201b94a948 | null | data/tak_media_archive.json | data/shorts_scripts/content-e787c9201b94a948.json (067e8dbbba11c944) | 309aed051dc31bc94b0527eb1e34a451b2f6cd239fbc8f594992163e35d66e67 |
| 02 | content-3ae2d78568210164 | null | data/tak_media_archive.json | data/shorts_scripts/content-3ae2d78568210164.json (9c220c5b2f20ef78) | af30d9ab556939cd6e75e1a77d8f822ae273fe01cec5717fc49d89768f7a9beb |
| 03 | content-ec0c38b9a20c424c | gen-20260920T033856-6e8d98fb | staging archive | artifacts/6-48-recovery-staging/data/shorts_scripts/content-ec0c38b9a20c424c.json (e2a6d05734c22d1a) | 875ebb6680f2692f0ef6ca593536d017bf0e77e376225cfb1880664b860a6042 |
| 04 | content-e3b8d986ea6db98e | gen-20260920T033856-6e8d98fb | staging archive | …/content-e3b8d986ea6db98e.json (3655a9c6f7fd64a6) | 96676befb98fcc74d37e73f5551840ed9e75c375d39bece85ff9f38d39cb5ec2 |
| 05 | content-91869ed8be17f3f3 | gen-20260920T033856-6e8d98fb | staging archive | …/content-91869ed8be17f3f3.json (b5e12b374bb506e9) | e1ccee1a1c7983ec30d79e6c06a5b8e61af93965ae10b3ac0d4093f15b97e68d |

- 스크립트는 파일 이름만 믿지 않고, ShortsScript 내부 `content_id`/`knowledge_id`가 archive 레코드와 같지 않으면 실패한다.
- MP4 파일명 = `<순서>_<content_id>.mp4`. 다른 content_id의 영상을 연결하지 않았다.
- 03~05의 generation_id·archive 레코드는 staging에만 있다. 업로드하려면 먼저 `--approve`로 Production에 복구해야 하고, 그러면 lineage의 archive 출처가 Production으로 바뀐다.

## 8. 품질검사 (5/5 PASS)

| 검사 | 방법 | 결과 |
|---|---|---|
| 파일 존재/크기 | stat | 5/5 |
| 파일 손상 | `ffmpeg -v error -i <mp4> -f null -` 전체 디코드, stderr 비어야 함 | 5/5 |
| duration 0 / 길이 | ffprobe duration == 장면 설계 합계(±0.2s) | 5/5 |
| resolution | 1080x1920 | 5/5 |
| codec | h264 + aac | 5/5 |
| 빈 화면 / 렌더 실패 | 장면마다 가운데 프레임을 MP4에서 추출, 밝기 표준편차 < 6이면 빈 화면 | 빈 장면 0 |
| 텍스트 overflow / 화면 밖 텍스트 | 6-41 렌더러의 `layout_text`(3줄 초과 시 실패) + 안전영역 bbox 검사(벗어나면 실패)가 전 장면에서 통과 | 5/5 |
| 원문 보존 | 나눈 장면 텍스트를 이어 붙이면 카드 원문과 글자 동일(공백/줄바꿈 제외) | 5/5 |
| lineage 누락 | manifest의 content_id/generation_id/ShortsScript/sha256 | 누락 0 |
| data 무변경 | 렌더 전후 `data/tak_media_archive.json`, `data/shorts_scripts/*` sha256 | 동일 |

미리보기 프레임을 눈으로도 확인했다(HOOK, 영어 문장 장면, `"may be conscious"` 줄바꿈 장면, 안전영역 가이드, 엔드카드).

## 9. YouTube 업로드 가능 여부

- API 호출·업로드 0회. 판정만 했다.
- **01, 02: 기술적으로 가능**(가드 통과) — 단 사람 검토 전에는 올리지 않는다.
- **03, 04: 불가** — Production Archive에 없음. 운영자가 1건 골라 `recover_media_archive.py --approve <id> --apply`로 복구한 뒤 가능.
- **05: 불가** — ORPHAN + PARTIAL. draft 반영·재검증 전에는 올리지 않는 것을 권고.

## 10. 사람의 최종 확인이 필요한 항목

1. **01/02 내용**: 6-49에서 지적한 대로 "나온 요청" / "이런 요청"이 무엇인지 영상 안에서 설명되지 않는다. 시청자는 맥락을 모른다. 01·02는 같은 KNOWLEDGE라 둘 중 하나만 게시 권고.
2. **03/04 영어 문장**: 한국어 Shorts에 영어 보도 문장이 3장면(약 12초) 그대로 나온다(6-50 12장 권고 1). 사실은 맞지만 시청성은 낮다.
3. **03/04/05 중복**: 같은 KNOWLEDGE·같은 generation, 03과 05는 제목이 같다. 1건만 게시 권고.
4. **05 PARTIAL**: draft 문장을 승인할지, 아니면 PASSED 03/04 중 하나를 쓸지.
5. **균형 문장**: Anthropic 입장("불확실하다")이 영상에 없다(6-50 12장 권고 3).
6. **페이싱**: 01·02는 25초 하한을 맞추려고 장면당 4~5.5초로 느리다. 강조 표시가 없어 6-41 샘플보다 밋밋할 수 있다.
7. 출처 표기가 `bbc.co.uk` 도메인만이다. YouTube 설명란에 전체 URL을 넣을 것.
8. 음악은 6-41 합성 사운드트랙(AI 스타일). 내레이션 없음.

## 테스트

| 실행 | 결과 |
|---|---|
| 전체 회귀(`TAK_TEST_FFMPEG` 지정) 1차 | 1536 tests, **failures 1**, errors 0, skipped 11 |
| 보정 후 전체 회귀 | **1536 tests OK, skipped 11** |
| 신규 `tests/test_6_51_production_shorts_preview.py` | 2 tests OK |

- failures 1 = `test_6_39…test_production_archive_was_never_committed`. "archive는 main 어떤 커밋에도 없다"를 가정했는데, **6-50 커밋 `f2b74a2`가 운영자 지시로 archive를 처음 커밋**해서 깨졌다(6-50 테스트 실행은 그 커밋 전이라 드러나지 않았음). 6-51 변경과 무관한 기존 가정 문제다. "main에서 이 파일을 처음 커밋한 것은 6-50이어야 한다"로 바꿨고, `--all` 일관성 검증은 그대로 둔다.
- 기존 Windows subprocess 오류 9건(6-50 기록)은 이번 실행에서는 발생하지 않았다(errors 0).

## 보안 / 외부 호출

| 검사 | 결과 |
|---|---|
| 자격증명 파일(추적·미추적) | 0 |
| secret 값 패턴(Google API key, OAuth token/refresh, sk-/sk-ant-, ghp_, private key, EAA, GOCSPX) | 0 |
| YouTube / Threads / Naver / LLM API | 0 / 0 / 0 / 0 |
| 외부 웹 조회 | 0 |

## 이번에 커밋한 것

- `scripts/render_production_shorts_preview.py` (신규, 로컬 미리보기·검증 도구)
- `tests/test_6_51_production_shorts_preview.py` (신규)
- `tests/test_6_39_first_operating_day_and_data_readiness.py` (6-50 이후 사실에 맞게 1개 테스트 보정)
- 이 문서

MP4·프레임·manifest·draft는 `.gitignore`의 `artifacts/` 정책에 따라 커밋하지 않았다.

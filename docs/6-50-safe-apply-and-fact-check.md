# 6-50 Safe Apply and Fact-Check

## 결론 요약

| 항목 | 결과 |
|---|---|
| SAFE_TO_APPLY | 2 |
| applied | **2** — content-e787c9201b94a948, content-3ae2d78568210164(기존 `recover_media_archive.py`, content_id별 `--approve` + `--apply`) |
| FACT_CHECK_PASSED | **2** — content-ec0c38b9a20c424c, content-e3b8d986ea6db98e |
| FACT_CHECK_PARTIAL | **1** — content-91869ed8be17f3f3 |
| FACT_CHECK_FAILED | 0 |
| fact-check 3건의 archive 적용 | **안 함**(이번 지시는 2건만 적용). 승인 상태도 바꾸지 않음 |
| archive | `data/tak_media_archive.json` **VALID, 2건**(전에는 NOT_PRESENT) |
| YouTube / Threads / Naver / LLM API | 0 / 0 / 0 / 0 |
| 외부 웹 조회 | 공개 웹 검색 3회, 페이지 조회 4회(아래 출처). bbc.co.uk는 이 도구에서 직접 열리지 않아 BBC 기사는 Yahoo 신디케이션본으로 확인 |
| production mutation | **YES(의도된 것)** — archive 신규 생성(2건 추가)과 ShortsScript 2개 복원. 기존 데이터 삭제·덮어쓰기 없음 |
| 테스트 | 1534 tests, failures 0, errors 9(사전 존재 Windows 이슈), skipped 11. 기존 테스트 4개 파일을 부분 복구 상황에 맞게 보정(8장) |
| secret scan | 깨끗함 |

## 1. SAFE_TO_APPLY 2개 — 적용 전 재확인

시작 상태: branch main, HEAD == origin/main == `1aa0369`(6-49), clean. `data/tak_media_archive.json`과 `data/shorts_scripts/` 없음.
source branch `codespace-silver-robot-xrr69q9r4r7j3pwq9`(`0547065`)는 데이터 원본으로만 썼다(merge·checkout 없음). staging 파일은 원본 blob과 다시 대조해 일치를 확인했다.

| content_id | generation_id | 제목 | platform | review | generation | superseded | duplicate | conflict | schema |
|---|---|---|---|---|---|---|---|---|---|
| content-e787c9201b94a948 | (없음, legacy) | 새로운 기술을 마주하는 나의 기준 | shorts | approved | valid | 아님 | 아님 | 아님 | OK |
| content-3ae2d78568210164 | (없음, legacy) | 신기술을 마주하는 내 기준 | shorts | approved | valid | 아님 | 아님 | 아님 | OK |

target(main) 상태: 두 content_id 모두 없음(archive 파일 자체가 없음).

## 2. 실제 apply 결과

기존 recovery architecture만 사용했다(새 복구 로직 없음):
```
py scripts/recover_media_archive.py --source artifacts/6-48-recovery-staging/data --production-archive data/tak_media_archive.json \
    --approve content-e787c9201b94a948 --approve content-3ae2d78568210164 --verbose     # dry-run: Apply Guard PASS, 쓰기 없음
py scripts/recover_media_archive.py … --approve content-e787c9201b94a948 --approve content-3ae2d78568210164 --apply   # Apply 결과 SUCCESS, 2건 반영
```
- 승인하지 않은 16건(Threads 9, Blog 2, rejected 2, fact-check 대상 Shorts 3)은 들어가지 않았다.
- **재실행 확인**: 같은 명령을 다시 실행하면 두 건 모두 `IDENTICAL` → guard `[safe_status_only] … 기존 production 레코드를 덮어쓰지 않습니다`로 막히고, archive 파일 바이트가 변하지 않았다(overwrite guard 동작 확인).
- ShortsScript 2개: recovery 도구는 downstream 파일을 쓰지 않으므로(설계) staging에서 `data/shorts_scripts/`로 복사하고 해시를 확인했다.

## 3. source/target SHA

| 대상 | source | target(적용 후) | 비교 |
|---|---|---|---|
| content-e787c9201b94a948 레코드 | canonical JSON sha256 `cf4c944d…1730` | `22b52891…`(canonical) | **필드 차이 0**. 현재 스키마가 `superseded_by: null`을 추가해 canonical 해시만 다르다. `MediaArchiveRecord` 정규화 후 동일 |
| content-3ae2d78568210164 레코드 | `b0a50e78…1d0e` | `f0a839d1…` | 위와 같음(필드 차이 0, 정규화 후 동일) |
| data/tak_media_archive.json(파일) | — | `bdc4cdb66adb61bdf0fa6b47765db2c361070eb8768653ccd4cbb58af5b4f269`(3,414 bytes) | 재실행·전체 테스트 후에도 동일 |
| data/shorts_scripts/content-e787c9201b94a948.json | `067e8dbbba11c94456e55cbb49b0166094e0e533a44e794eb9c6dc3277f96970` | 동일 | 일치 |
| data/shorts_scripts/content-3ae2d78568210164.json | `9c220c5b2f20ef78ca04a15ef60046da43a92a7545230753bd623a5609d83489` | 동일 | 일치 |

## 4. Production Archive 적용 전후 record count

| | 적용 전 | 적용 후 |
|---|---|---|
| data/tak_media_archive.json | NOT_PRESENT(0) | **VALID, 2** |
| data/shorts_scripts/ | 없음 | 2 |
| audit_data_state | NOT_PRESENT | VALID(3,414 bytes) |
| Operator | PRODUCTION ARCHIVE NOT_PRESENT, RECOVERY_REQUIRED | PRODUCTION ARCHIVE VALID(2), YouTube Shorts NEEDS_HUMAN_REVIEW(2), RECOVERY NOT_REQUIRED |

## 5. 적용된 content_id

content-e787c9201b94a948, content-3ae2d78568210164. 게시·업로드는 하지 않았다. Operator가 게시 전 사람 검토(NEEDS_HUMAN_REVIEW)를 요구한다.

## 6. FACT_CHECK 3개 — 실제 문장

| content_id | 해당 문장(ShortsScript 원문 그대로) | 성격 |
|---|---|---|
| content-ec0c38b9a20c424c | card 1: `Mustafa Suleyman says he believes rival AI firm Anthropic is in effect teaching Claude it "may be conscious".` | 외부 사실(보도 문장). 영어 원문 그대로 |
| | card 2~4: "이 논란을 보며 나는 … 투명한 연구와 감독 아래 제한적으로 허용하고, 사회적 논의를 이어가야 한다고 생각한다." / "연구 범위와 실험 대상을 명확히 정하고, 독립적인 검토를 받는 것도 우선해야 한다." / "다만 검증 가능한 피해가 발생한다면 연구를 중단해야 한다." | 티몽 의견(B: 논쟁에 대한 의견) |
| content-e3b8d986ea6db98e | card 1~2: 위와 같은 취지의 의견 | 의견 |
| | card 3: 위 card 1과 **같은 영어 문장** | 외부 사실. 영어 원문 그대로 |
| content-91869ed8be17f3f3 | card 1: "Mustafa Suleyman은 경쟁 AI 기업 Anthropic이 Claude에게 “의식이 있을 수 있다”고 사실상 가르치고 있다고 믿는다고 말했습니다. 원문 표현은 \"may be conscious\"입니다." | 외부 사실의 한국어 번역 |
| | card 2: 의견 3개(위와 같은 취지) | 의견 |

세 개 모두 "AI가 의식이 있다"고 단정하지 않는다. AI welfare/AI rights라는 단어는 쓰지 않는다. 인물 발언으로 보이는 부분은 Suleyman 문장 하나뿐이다.

## 7~10. claim · source · date · 직접 인용/의역

| # | CLAIM | SOURCE | DATE | 직접 인용 여부 | 확인 결과 |
|---|---|---|---|---|---|
| C1 | "Mustafa Suleyman says he believes rival AI firm Anthropic is in effect teaching Claude it 'may be conscious'." | BBC News, Laura Cress(Technology reporter), "Uncontrolled AI could lead to 'silicon species' rivalling humans, warns Microsoft" — BBC 링크(`bbc.co.uk/news/articles/c6n07ypqz8kzo`)는 이 도구에서 차단돼, 같은 기사의 Yahoo 신디케이션본으로 확인 | 2026-09-17 | 문장 전체는 **기자의 요약(lede)**이다. 따옴표 안의 `may be conscious`만 인용 표시 | 보도 문장이 Shorts와 **글자 그대로 일치**(ec0c38b9, e3b8d986) |
| C2 | Suleyman 본인이 그런 주장을 했는가 | Mustafa Suleyman, "A warning about 'model welfare'", mustafa-suleyman.ai(본인 에세이, 1차 출처) | 2026-09-16 | **직접 인용 확인**: "In effect, Anthropic is training Claude that it may be conscious, and if it is, then it may deserve rights as a 'moral patient'" | C1의 핵심 주장이 1차 출처와 일치. BBC의 "teaching"은 에세이의 "training"을 옮긴 표현이고, "may be conscious"는 에세이의 표현 그대로다. 에세이에는 "AIs are not conscious. They do not feel, experience, or suffer."도 있다 |
| C3 | 발언 장소·직함 | BBC(신디케이션본), Euronews(Roselyne Min) | 2026-09-17 | — | Microsoft AI CEO. BBC Today 인터뷰와 본인 에세이 두 곳에서 Anthropic을 비판했다. "may be conscious" 문구는 에세이에 있다 |
| C4 | Anthropic 입장(B 구분용) | Anthropic의 Claude constitution(2026-01 공개)에 대한 보도·요약(검색 결과: TechCrunch, Fortune 2026-01-21 등), Suleyman 에세이의 constitution 인용 | 2026-01 | Suleyman 에세이가 인용한 constitution 문장: "We are not sure whether Claude is a moral patient, and if it is, what kind of weight its interests warrant" | Anthropic 입장은 "불확실하다"이지 "Claude는 의식이 있다"가 아니다. **Anthropic의 응답**: BBC 기사에는 "Anthropic has been approached for comment"만 있고 응답이 없다 |

주의: 기자의 요약(C1)을 Suleyman의 직접 발언으로 바꾸지 않았다. 직접 인용으로 확인된 것은 C2의 에세이 문장뿐이다.

## 11. 판정

| content_id | 판정 | 근거 |
|---|---|---|
| content-ec0c38b9a20c424c | **FACT_CHECK_PASSED** | 인용한 문장이 BBC 보도 문장과 글자 그대로 같고, 그 핵심 주장이 Suleyman 본인 에세이(1차 출처)의 직접 문장으로 확인된다. "says he believes"로 Suleyman의 주장임이 표시돼 있고, 뒤 문장은 논쟁에 대한 의견으로 구분된다. AI 의식을 사실로 단정하지 않는다 |
| content-e3b8d986ea6db98e | **FACT_CHECK_PASSED** | 같은 문장(card 3), 같은 근거 |
| content-91869ed8be17f3f3 | **FACT_CHECK_PARTIAL** | 핵심 내용은 확인된다. 다만 (1) 한국어 번역 “의식이 있을 수 있다”를 따옴표로 묶어 Suleyman의 직접 발언처럼 보인다(원문 표기는 뒤에 따로 적었음), (2) "말했습니다" — 이 문구의 1차 출처는 **글(에세이)**이고, BBC가 "says"로 요약한 것이다. 인용 표현의 정확성이 일부 불확실하다 |

approved 상태와 archive는 바꾸지 않았다. 3건 모두 Production Archive에 적용하지 않았다.

## 12. 추가 수정이 필요한 문장 (게시 전 권고, 이번에는 수정하지 않음)

1. **ec0c38b9 card 1, e3b8d986 card 3** — 한국어 Shorts에 영어 문장이 그대로 들어가 있다. 예시:
   "Microsoft AI CEO 무스타파 술레이만은 Anthropic이 Claude에게 사실상 '의식이 있을 수 있다(may be conscious)'고 훈련시키고 있다고 주장했습니다(2026년 9월 16일 본인 에세이, BBC 보도)."
2. **91869ed8 card 1** — 번역을 직접 인용처럼 쓰지 않도록 한다. 예시:
   "술레이만은 Anthropic이 사실상 Claude가 '의식이 있을 수 있다'고 믿도록 훈련시킨다고 주장했습니다(원문: \"may be conscious\", 2026-09-16 에세이)." — "말했습니다" 대신 "주장했습니다/썼습니다".
3. **세 건 공통(균형)** — Anthropic의 입장이 빠져 있다. 한 줄 추가를 권고한다: "Anthropic은 Claude의 도덕적 지위가 '매우 불확실하다'는 입장입니다." 그리고 "술레이만 본인은 'AI는 의식이 없다'고 봅니다."를 넣으면 논쟁 구도가 정확해진다.
4. **중복** — ec0c38b9와 91869ed8은 제목이 같고, 세 건 모두 같은 KNOWLEDGE에서 나왔다. 게시는 1건만 고르는 편이 낫다.
5. 수정은 기존 흐름(Dashboard edit → 재검증 → supersede/새 generation)으로 해야 한다. 승인된 레코드를 직접 고치지 않는다.

## 13. 다음 작업 권고

1. 적용된 2건: 게시 전 사람 검토. 6-49에서 적은 것처럼 "이런 요청"이 무엇인지 화면에 설명되지 않는다. 필요하면 수정한 뒤 6-44 절차로 ShortsScript → 렌더 → `--content-id` PRIVATE 업로드 dry-run으로 진행한다.
2. fact-check 3건: 12장대로 수정하고 재검증한 뒤, 운영자가 `--approve`로 1건만 복구하는 방안을 권고한다(PASSED 2건 중 하나, 수정 후).
3. 나머지 Threads 9, Blog 2건 복구 여부 결정(4건은 현재 `tak_threads_pending.json`에 이미 있음).
4. Production Archive git 커밋 정책: 이번에 처음 커밋했다(운영자 지시 "정확히 2개의 운영 데이터 복구 commit"). 앞으로도 커밋할지 정한다.
5. KNOWLEDGE 두 건의 `current_validity`("확인 필요")를 이번 확인 결과로 갱신할지 운영자가 결정한다(이번에는 바꾸지 않음).

## 테스트

| 실행 | 결과 |
|---|---|
| 전체 회귀(ffmpeg 지정) | **1534 tests, failures 0, errors 9, skipped 11** |
| recovery / archive / duplicate / conflict / superseded / reconciliation / promotion | 전체 회귀에 포함, 모두 통과 |

- errors 9는 사전 존재 오류다(Windows `subprocess.run(capture_output=True)` → `stdout=None`): test_content_engine 1, test_knowledge_review 1, test_media_batch 2, test_media_viewer 1, test_run_scout_cli 1, test_threads_publisher 3.
- **archive가 생긴 뒤 새로 드러난 실패 6건과 처리**(모두 전에는 archive가 없어 skip되던 기존 테스트):
  - `test_recovery_review_and_approval…no_production_file_created_by_report_only`, `test_recovery_staging…test_16_no_production_file_created`: "CLI 실행 후 archive 파일이 없어야 한다"를 가정했다 → 운영자가 복구한 archive가 있을 수 있으므로 **"CLI가 파일을 만들지도 바꾸지도 않는다(실행 전후 바이트 동일)"**로 바꿨다. 보호 의도는 같고, 기존 파일이 있을 때도 검증한다.
  - `test_media_versioning_and_promotion`의 legacy 9건 테스트 2개, `test_same_content_id_overwrite_protection`의 18건·`content-5971ed5204437cdd` 테스트 2개: 이 PC의 실제 archive가 6-12 시점 전체 스냅샷(18건)이라고 가정했다. 지금 archive는 운영자가 승인한 2건만 있는 부분 복구본이다 →
    스냅샷 사실(18건, legacy 9건, 5971… approved)은 **스냅샷 원본(export commit `0547065`)으로 검증**하고, 실제 archive에 대해서는 **"스냅샷에 있는 레코드는 한 필드도 바뀌지 않았다"**를 추가로 검증하도록 했다. export commit이 없는 환경에서는 예전처럼 실제 파일로 스냅샷 사실을 검증한다. 삭제·skip한 테스트는 없다.
  - 그 결과 skip이 17 → 11로 줄었다(실제 archive를 읽는 6개 테스트가 이제 실행되고 통과한다).
- `scripts/audit_data_state.py`의 고정 설명 문구("main에 커밋된 적이 없다")를 사실에 맞게 고쳤다(동작 변경 없음).

## 보안 / 외부 호출

| 검사 | 결과 |
|---|---|
| 자격증명 파일(추적·미추적) | 0 |
| 작업 트리 secret 값 패턴 | 0(기존 테스트의 가짜 누출 마커 제외) |
| 커밋할 운영 데이터 3개 파일 | 0 |
| YouTube / Threads / Naver / LLM API | 0 / 0 / 0 / 0 |

외부 조회(공개 웹, 인증 없음): 웹 검색 3회. 페이지 조회: BBC 원문(도구에서 차단돼 실패), Yahoo 신디케이션(BBC 기사), Euronews, mustafa-suleyman.ai 에세이.

출처:
- BBC News(Yahoo 신디케이션): https://tech.yahoo.com/ai/claude/articles/microsoft-says-ai-rival-anthropic-140241305.html (원문: https://www.bbc.co.uk/news/articles/c6n07ypqz8kzo)
- Mustafa Suleyman, "A warning about 'model welfare'": https://mustafa-suleyman.ai/a-warning-about-model-welfare
- Euronews: https://www.euronews.com/2026/09/17/ai-could-create-a-silicon-species-that-rivals-humans-microsoft-chief-warns
- Anthropic constitution 관련 보도(검색 결과): https://techcrunch.com/2026/01/21/anthropic-revises-claudes-constitution-and-hints-at-chatbot-consciousness , https://www.fortune.com/2026/01/21/anthropic-claude-ai-chatbot-new-rules-safety-consciousness

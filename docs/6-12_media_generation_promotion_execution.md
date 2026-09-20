# TAK AUTO 6-12 — 실제 Generation 승인 + Batch Promotion 실행(Production 반영)

## 1. 작업 목적

6-11에서 완성한 Human Review 화면(`/media/generations`, KNOWLEDGE 제목 표시,
출처 링크, 편집 기능)을 이용해, 실제 대상 콘텐츠를 사람이 직접 검토하고
승인한 뒤 실제로 Production Archive에 반영하는 것 — 그동안(6-06~6-11)
안전장치만 계속 쌓아 온 파이프라인을 실제로 한 번 끝까지 실행하는 작업이다.

이 작업은 코드 수정이 아니라 **운영(operation)** 이다 - 이번 문서는 기존에
구현·테스트된 기능(`/media/generations` 승인 화면, `scripts/promote_media_generation.py`
batch 모드)을 그대로 사용해 실제 데이터에 대해 순서대로 실행한 명령과 그
검증 결과만 기록한다. 코드나 테스트는 전혀 수정하지 않았다.

대상:

- knowledge_id: `knowledge-scout-6d1d0e2fa762`
- generation_id: `gen-20260920T033856-6e8d98fb`
- 파일: `data/tak_media_generation_6-07_knowledge-scout-6d1d0e2fa762.json`
- 총 9건(Blog 1 · Shorts 3 · Threads 5)

## 2. 사전 준비 — Dashboard 실행

사람이 실제로 화면에서 검토할 수 있도록 `scripts/run_scout_dashboard.py`를
백그라운드로 실행했다(포트 8000, GitHub Codespaces 포트 포워딩으로 접속).

```
$ python3 scripts/run_scout_dashboard.py --host 127.0.0.1 --port 8000 &
TAK MEDIA Generation Pool: 자동 탐색됨 (1개) - tak_media_generation_6-07_knowledge-scout-6d1d0e2fa762.json
TAK SCOUT Dashboard 실행 중: http://127.0.0.1:8000
```

`GET /media/generations` 응답을 확인해 실제 9건이 카드 9개로 정상
렌더링되고, 6-11에서 추가한 KNOWLEDGE 제목("Uncontrolled AI could lead to
'silicon species' rivalling humans, warns Microsoft")이 그룹 헤더에
표시되는 것을 확인했다.

## 3. 1차 Dry-Run(승인 전) — 기준선 확인

사람이 아직 아무것도 승인하지 않은 시점에 먼저 dry-run을 실행해 현재
상태를 정확히 확인했다.

```
$ python3 scripts/promote_media_generation.py \
    --archive data/tak_media_generation_6-07_knowledge-scout-6d1d0e2fa762.json \
    --production-archive data/tak_media_archive.json \
    --generation-id gen-20260920T033856-6e8d98fb

=== MEDIA Generation Batch Promotion [DRY-RUN (파일 변경 없음)] ===
총 record: 9 (valid 9 / rejected 0 / error 0)
approved: 0 / unreviewed: 9 / dismissed: 0
promotion 예정: 0건
skip: 9건 (전부 "review_status=unreviewed (아직 검토 전)")
```

Production archive SHA-256 해시가 dry-run 전후 완전히 동일함을 확인했다
(`b19efa9c...` → `b19efa9c...`, 변경 없음). 이 시점에는 승인된 것이
하나도 없어 전부 skip이었다 - 사용자에게 이 사실을 그대로 보고했다.

## 4. Generation 전체 승인(approve-all)

사용자가 Dashboard 화면에서 9건을 모두 검토했다고 확인한 뒤, 기존에
구현된 "generation 전체 승인" 기능을 코드 수정 없이 그대로 호출했다.

```
$ curl -X POST http://127.0.0.1:8000/media/generations/generation/gen-20260920T033856-6e8d98fb/approve-all
HTTP 303 (redirect, 성공)
```

이 라우트가 호출하는 `handle_generation_approve_all_submission()`은
`generation_id`가 정확히 일치하고 `generation_status == "valid"`이며
`review_status != "approved"`인 레코드만 골라 `approved`로 바꾼다(6-08
구현) - 다른 generation, legacy 콘텐츠(generation_id 없음), 다른
KNOWLEDGE는 이 함수 시그니처 자체가 건드릴 수 없는 구조다.

**처리 후 재검증**(generation pool 파일을 다시 읽어서 확인):

```
총 9개 / approved 9개 / unreviewed 0개 / dismissed 0개
generation_status: valid 9개
edited_title/edited_body: 전부 None (콘텐츠 내용 변경 없음)
```

## 5. 2차 Dry-Run(승인 후)

```
$ python3 scripts/promote_media_generation.py \
    --archive data/tak_media_generation_6-07_knowledge-scout-6d1d0e2fa762.json \
    --production-archive data/tak_media_archive.json \
    --generation-id gen-20260920T033856-6e8d98fb

=== MEDIA Generation Batch Promotion [DRY-RUN (파일 변경 없음)] ===
총 record: 9 (valid 9 / rejected 0 / error 0)
approved: 9 / unreviewed: 0 / dismissed: 0
promotion 예정: 9건 (전부 PROMOTE) / skip: 0건 / error: 0건
  Blog 1 · Shorts 3 · Threads 5
```

Production archive 해시가 dry-run 전후 동일함을 재확인했다(`53d56a72...`).
`--execute`는 사용하지 않았다.

## 6. 실제 Promotion 실행(Production 반영)

사용자가 실행을 명시적으로 지시한 뒤, 동일한 명령에 `--execute`만 추가해
실행했다.

```
$ python3 scripts/promote_media_generation.py \
    --archive data/tak_media_generation_6-07_knowledge-scout-6d1d0e2fa762.json \
    --production-archive data/tak_media_archive.json \
    --generation-id gen-20260920T033856-6e8d98fb \
    --execute

=== MEDIA Generation Batch Promotion [EXECUTE] ===
(위 dry-run과 동일한 계획 - 9건 전부 PROMOTE)
승격 완료: 9건을 data/tak_media_archive.json에 반영했습니다.
```

## 7. 실행 후 검증

**Production archive**(promotion 직후):

```
총 18건 = 기존 legacy 9건(knowledge-scout-b28b782b2a33, generation_id=None) 그대로 보존
        + 신규 9건(knowledge-scout-6d1d0e2fa762, generation_id=gen-20260920T033856-6e8d98fb)

신규 9건 platform 분포: Blog 1 · Shorts 3 · Threads 5
신규 9건 review_status: 전부 approved
content_id 중복: 없음(18건 전부 유일)
```

**Generation pool 파일**(promotion으로 전혀 바뀌지 않아야 함):

```
promotion 실행 전후 SHA-256 해시 동일(9aa3677e...)
9건 그대로 유지, review_status=approved 9개, generation_status=valid 9개
```

`scripts/promote_media_generation.py`는 generation pool을 읽기만 하고
쓰지 않는 구조라(`plan_batch_promotion`은 `load_archive`만 호출,
`upsert_archive`는 production archive 경로에만 호출) 이 결과는 코드
구조상으로도 보장된다.

## 8. 관찰된 사실 — 동시에 진행된 별개의 사용자 활동(legacy `/media`)

이번 세션 도중, production archive(`data/tak_media_archive.json`)의
해시가 내가 실행한 명령과 무관하게 여러 차례 바뀐 것을 관찰했다:

- 세션 시작 시점(6-11 종료): `823ba839...`
- 1차 dry-run 직전: `b19efa9c...` (이미 변경됨)
- approve-all 직전: `53d56a72...` (또 변경됨)
- promotion 실행 후 최종 확인: `ebe1249f...`

내용을 비교한 결과, 이 변화는 전부 **legacy KNOWLEDGE
(`knowledge-scout-b28b782b2a33`, `generation_id=None`)의 기존 9건**에 대해
사용자가 `/media`(production) 화면에서 직접 승인 조작을 한 결과였다 -
이 legacy 9건의 `content_id` 집합과 개수는 세션 전체에서 정확히 동일하게
유지됐고(9971ed52.../e787c920.../3ae2d785.../cabd37f3.../dbf0fb4e.../
81d4e7c5.../4015df06.../5a6b175a.../cbcf705b...), 이번 6-12 작업(승인 대상
generation의 9건)과는 완전히 별개다. `data/tak_threads_pending.json`에
legacy Threads content_id 4건(`content-cbcf705b...`, `content-dbf0fb4e...`,
`content-4015df06...`, `content-81d4e7c5...`)의 pending draft가 새로
추가된 것도 이 legacy `/media` 승인의 부수 효과(기존 5-28
`handle_media_approve_submission`의 정상 동작 - platform=="threads"
승인 시 자동으로 pending draft 생성)이며, 이번 작업이 만든 변경이 아니다.

이번 6-12가 실제로 쓴 파일은 정확히 두 개뿐이다:
`data/tak_media_generation_6-07_knowledge-scout-6d1d0e2fa762.json`
(approve-all, review_status만) 과 `data/tak_media_archive.json`
(promotion execute, 신규 9건 추가만) - 둘 다 대상 9건 외에는 건드리지
않았다.

## 9. 6-11 보고서 파일 이상 발견 및 복구

이번 세션 도중 `docs/6-11_human_review_readiness.md`가 디스크에서 **0바이트로
빈 파일**이 되어 있는 것을 발견했다(원인 불명 - 에디터 자동 저장 등으로
추정, 원인을 확정할 근거는 없다). `git diff`로 확인한 결과 마지막 커밋
(`7867125`)의 내용(405줄)이 전부 삭제된 상태였다. 이는 의도된 수정이
아니라 명백한 사고성 데이터 손실로 판단해, `git checkout --
docs/6-11_human_review_readiness.md`로 마지막 커밋 상태로 복구했다 - 다른
어떤 파일도 이 명령의 영향을 받지 않았다(`git status --short`로 확인).

## 10. 요약

| 단계 | 명령/액션 | production archive 변경 |
| --- | --- | --- |
| 1 | Dashboard 실행 | 없음 |
| 2 | 1차 dry-run(승인 전) | 없음(9건 전부 skip) |
| 3 | `POST .../approve-all` | 없음(generation pool 파일만 변경) |
| 4 | 2차 dry-run(승인 후) | 없음(9건 전부 promote 예정 확인만) |
| 5 | `--execute` 실행 | **있음** - 9건 추가(18건으로 증가) |

- 최종 production archive: 18건(legacy 9 + 신규 9, 신규 9건은 Blog 1 ·
  Shorts 3 · Threads 5, 전부 approved, 중복 없음).
- 최종 generation pool: 9건 그대로, 전부 approved(promotion으로 값이
  바뀌지 않음 - 승인 시점 상태 그대로 보존).
- 콘텐츠 내용(제목/본문/edited_title/edited_body)은 이번 세션에서 한 번도
  수정하지 않았다 - 순수하게 상태 전이(unreviewed → approved →
  production 승격)만 실행했다.
- 코드/테스트 수정 없음(이번 문서는 운영 기록이다).
- LLM 호출 없음.

# 6-81 마케팅 데이터 보존 방식 / MEDIA 검토 시스템 연결 조사

조사 시점: 2026-10-04, 브랜치 `chore/untracked-file-triage-20261004` @ 1a60ed9. 코드는 수정하지 않았다(읽기 전용 조사).

## [현재 데이터 보존 방식]

마케팅 계층 파일은 모두 `.gitignore`의 `data/*.json` 규칙에 걸리고, 화이트리스트(`!data/...`)에 없다.

| 파일 | 내용 | Git | audit_data_state / export(6-46) |
|---|---|---|---|
| `data/tak_market_demands.json`, `data/tak_idea_candidates.json` | 시장 수요 입력, 아이디어 후보 | 무시됨 | 미등록 |
| `data/tak_marketing_briefs.json` | 브리프, 사람이 채운 요소, approved/rejected 결정, `content_ids` 연결 | 무시됨 | 미등록 |
| `data/tak_marketing_suggestions.json` | 제안과 사람의 accept/reject 결정 | 무시됨 | 미등록 |
| `data/tak_marketing_contents.json` | review_required 후보(LLM 재작성 결과 포함) | 무시됨 | 미등록 |
| `data/tak_brain_knowledge.json` | `draft --research --write`가 추가한 pending KNOWLEDGE | **추적됨(화이트리스트)** | 등록됨 |

기존 프로젝트의 전략(6-21, 6-46, 6-48)과 비교:

- **A(사람의 결정/운영 상태)는 git 화이트리스트에 둔다.** `tak_brain_knowledge.json`, `tak_threads_pending.json`, `tak_media_archive.json`, 발행 로그가 여기에 해당한다. 이유는 다른 PC, Codespace, GitHub Actions의 새 checkout에서도 승인 상태가 보여야 하기 때문이다(6-21 3장).
- **C/D(재생성 가능하거나 승격 전 초안)는 무시한다.** generation pool(`tak_media_generation_*.json`), `shorts_scripts/`, `blog_publish_pack_daily.md`가 여기에 해당한다. 사람이 승인한 결과는 production archive로 승격되어 A에 남으므로, 초안을 잃어도 괜찮다는 전제다.
- **git 밖의 파일은 6-46 export package로 옮긴다.** `audit_data_state.py`의 FILE_SPECS와 `export_operational_data.py`의 EXTRA_FILES에 있는 경로만 대상이다. 6-48에서 이 package로 복구했다.

마케팅 파일은 A 성격(사람의 승인, 편집, 제안 결정)인데도 C처럼 처리되고 있다. export 대상에도 없어서 현재는 **이 Codespace의 디스크에만** 존재한다.

- Codespace를 stop/start하거나 rebuild하면 `/workspaces`가 유지되므로 남는다.
- Codespace를 삭제하거나 비활성 보존 기간이 지나 자동 삭제되면 모두 사라진다. 새 Codespace, 다른 PC, Actions checkout에서도 보이지 않는다.
- 현재 이 Codespace에는 마케팅 data 파일이 아직 하나도 생성되지 않았다. 지금 시점에 실제로 잃은 데이터는 없다.

## [잠재적인 문제]

1. **사람의 결정이 사라진다.** 브리프 승인/반려, 요소 편집, 제안 accept/reject는 재생성할 수 없다. 결정적으로 다시 만들 수 있는 것은 근거 인용형 제안 문구뿐이다.
2. **lineage가 반쪽만 남는다.**
   - `--research --write`로 만든 pending KNOWLEDGE는 git에 남는다. 그 KNOWLEDGE를 참조하는 브리프(`knowledge_ids`)는 사라진다. 결국 "이 KNOWLEDGE가 어떤 시장 근거/브리프에서 왔는가"를 잃는다.
   - `tak_performance.json`은 git에 남는다. 그러나 성과와 브리프를 잇는 `brief.content_ids`가 사라지므로 `insights`(속성별 lift)를 계산할 수 없다.
3. **review_required 후보는 재현할 수 없다.** 규칙 기반 초안은 같은 KNOWLEDGE에서 다시 만들 수 있다. 하지만 LLM 재작성 결과와 `created_at`은 다시 만들 수 없다.
4. **audit/export 도구가 존재를 모른다.** `audit_data_state.py`가 마케팅 파일의 유무나 손상을 보고하지 않는다. 6-46 export package에도 들어가지 않는다. 6-48 방식으로 복구할 수 없다.
5. **content_id가 기존 MEDIA와 겹친다(발견 사항).** blog/threads/shorts 후보의 `content_id`는 `run_media_batch`가 같은 KNOWLEDGE로 만든 항목과 완전히 같다. `compute_content_id`는 재작성 결과를 보지 않고, 원본 초안은 같은 생성기에서 나오기 때문이다.
   - 같은 content_id가 "브리프 가이드로 재작성한 버전"과 "기존 배치 버전"을 구분하지 못한다.
   - production archive에 넣을 때는 6-06/6-18의 `check_promotion_conflict` 대상이 된다.
6. **YouTube의 platform이 하위 시스템과 맞지 않는다(발견 사항).** 후보는 `platform="youtube"`로 저장되고 `content_id`도 `"youtube"`로 계산된다. 그런데 하위 시스템은 모두 `platform == "shorts"`를 요구한다.
   - `scripts/upload_youtube_short.py:87`, `scripts/generate_approved_shorts_script.py:75`, `shorts_adapter.approved_media_archive_record_to_shorts_script`가 그렇다.
   - 이 상태로 archive에 넣으면 업로드/스크립트 경로에서 걸러진다. 또 `brief.content_ids`의 youtube ID는 archive나 성과 데이터의 shorts ID와 일치하지 않는다.
7. **`rewrite_status="not_requested"` 후보는 validator를 거치지 않았다.** archive의 `generation_status="valid"`는 "RewriteValidator를 통과했다"는 뜻이다. 그래서 재작성하지 않은 후보를 `valid`로 옮기면 의미가 달라진다.

## [기존 MEDIA 검토 시스템 구조]

```
run_media_batch (pipeline.MediaBatchItem / MediaBatchReport)
  ↓ archive_generation_report(report, path, generation_id)        content_engine/media_archive.py
Generation Pool  data/tak_media_generation_*.json  (git 무시, (content_id, generation_id) 복합 키)
  ↓ Dashboard /media/generations  (scripts/run_scout_dashboard.py, discover_generation_pool_paths가 glob으로 자동 발견)
  │   handle_generation_review_submission / handle_generation_edit_submission → review_status, edited_*
  ↓ scripts/promote_media_generation.py  (generation_status=valid && review_status=approved만, 기본 dry-run, check_promotion_conflict)
Production Archive  data/tak_media_archive.json  (git 화이트리스트, content_id 단독 키, source of truth)
  ↓ Dashboard /media  (handle_media_approve/edit/dismiss_submission)
  ↓ 기존 downstream: blog_publish_pack(platform=blog) / threads_review·publish_approved_threads(threads)
     / generate_approved_shorts_script·upload_youtube_short(shorts) / collect_performance(content_id)
```

핵심 데이터 구조는 `MediaArchiveRecord`다.

- **식별/근거 필드:** `content_id, knowledge_id, platform(blog|shorts|threads), source_url, evidence, evidence_unit_ids, created_at`
- **텍스트 필드:** `original_*`, `rewritten_*`, `edited_*`. 최종값은 `final_title`/`final_body`가 edited → rewritten → original 순서로 고른다.
- **상태 필드:** `generation_status ∈ {valid, rejected, error}`(배치/검증 결과), `review_status ∈ {unreviewed, approved, dismissed, superseded}`(사람의 결정)
- **기타 필드:** `validation_errors, error_message, generation_id, superseded_by`

`brief_id`나 marketing 메타데이터 필드는 없다.

## [연결에 필요한 adapter]

기존 모듈을 수정하지 않고, 새 adapter 1개(예: `content_engine/marketing/media_bridge.py`)로 연결한다.

1. **후보 → `MediaBatchItem` 변환.** `pipeline.MediaBatchItem`을 그대로 사용한다.
   - platform: `youtube → "shorts"`로 바꾸고 `content_id`도 `"shorts"` 기준으로 다시 계산한다.
   - 상태: `rewritten → valid`, `rejected → rejected`, `error → error`로 옮긴다.
   - `not_requested`는 bridge 대상에서 빼거나, `RewriteValidator`(또는 identity provider인 `MockRewriteProvider`)를 거친 결과만 `valid`로 인정한다.
   - 필드: `rejection_reasons ← validation_errors`, `error_message ← rewrite_error`.
2. **Generation Pool 저장.** `MediaBatchReport`로 묶은 뒤 기존 `media_archive.archive_generation_report()`를 호출한다.
   - 파일 이름은 `data/tak_media_generation_marketing-<brief_id>.json`처럼 glob 규칙(`tak_media_generation_*.json`)을 지킨다. 그래야 대시보드 `/media/generations`가 별도 설정 없이 발견한다.
   - `generation_id`를 브리프 단위로 부여해 기존 배치 generation과 분리한다. 이것으로 5번(content_id 충돌) 문제를 6-06 방식으로 흡수한다.
3. **검토와 승격은 기존 것을 그대로 쓴다.** 사람이 `/media/generations`에서 approve/edit/dismiss하고, `promote_media_generation.py`(dry-run → `--execute`, conflict 검사)로 production archive에 올린다. bridge는 승인이나 승격을 하지 않는다.
4. **lineage 매핑.** `MediaArchiveRecord`에 brief_id를 추가하지 않는다(스키마 변경 금지). 대신 `tak_marketing_contents.json` 후보에 `generation_id`와 `media_content_id`(shorts 기준)를 기록해 `(content_id, generation_id) → brief_id`를 역참조한다. `brief.content_ids`에는 archive/성과와 같은 content_id를 연결한다.
5. **상태 동기화(읽기 전용).** marketing 후보의 상태는 pool/archive의 `review_status`를 읽어서 보여주기만 한다. 두 저장소에 따로 쓰지 않는다.
6. **보존 경로 등록.** `audit_data_state.py`의 FILE_SPECS와 `export_operational_data.py`의 EXTRA_FILES에 마케팅 파일을 추가한다. 이것은 기존 도구에 경로만 추가하는 일이다.

## [다음 개발 우선순위]

1. **보존 정책 결정과 등록(가장 먼저, 작은 변경).**
   - 브리프와 제안은 사람의 결정(A 성격)이므로 화이트리스트에 넣을지 사람이 결정한다. 6-21과 같은 원칙으로, 커밋 여부도 사람이 정한다.
   - `tak_marketing_contents.json`은 bridge가 생기면 C(승격 전 초안)로 분류하고 계속 무시해도 된다.
   - 결정과 관계없이 audit/export 도구에는 모두 등록한다.
2. **YouTube platform/content_id 정합성 수정.** 실제 `--write`로 저장하기 전에 `draft_platform="shorts"` 기준 content_id를 기록해, 브리프 연결과 성과 귀속이 archive와 일치하게 한다.
3. **`media_bridge` adapter 구현.** 위 1~5를 구현하고 테스트한다. 테스트 범위는 pool 파일 이름 규칙, 대시보드 발견, platform 매핑, not_requested 제외, 발행 미호출이다.
4. **lineage 역참조와 insights 연결 검증.** promote 이후 `collect_performance` → `insights`가 브리프까지 이어지는지 E2E로 확인한다.
5. **6-80 문서의 "한계" 갱신, 운영 리허설.** 최소 1건의 승인 브리프를 생성 → pool → 검토 → 승격까지 dry-run으로 수행한다.

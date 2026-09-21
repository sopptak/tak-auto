# Threads Publish Consistency

생성 시각(UTC): 2026-09-21T07:09:31.574827+00:00

## Summary

- 전체 대상 content_id: 11
- CONSISTENT: 1
- PUBLISHED_BUT_PENDING_STALE: 0
- PENDING_WITHOUT_PUBLISH_LOG: 4
- FAILED: 0
- ORPHAN: 6
- DUPLICATE: 0

⚠️ 이 보고서는 읽기 전용 점검 결과입니다. 어떤 파일도 이 보고서 생성 과정에서
수정되지 않습니다. safe_to_sync=예인 항목만
`python scripts/publish_approved_threads.py --id <content_id> --execute`로
안전하게 동기화할 수 있습니다(이미 게시된 이력이 있으므로 실제 Threads API를
다시 호출하지 않습니다).

## 전체 내역

| content_id | 상태 | pending status | log post_id | safe_to_sync | 사유 |
| --- | --- | --- | --- | --- | --- |
| content-4015df0692e0bcc4 | PENDING_WITHOUT_PUBLISH_LOG | pending | - | 아니오 | status=pending - 아직 게시 이력이 없습니다(정상). |
| content-43786cf3ee0d89c5 | CONSISTENT | published | 17895093546607157 | 아니오 | - |
| content-45d8e97f0fab7b16 | ORPHAN | - | 18134252149645663 | 아니오 | 게시 이력에는 있지만 pending 파일에 해당 content_id가 없습니다. |
| content-6de1e17342ba9642 | ORPHAN | - | 18161477902482941 | 아니오 | 게시 이력에는 있지만 pending 파일에 해당 content_id가 없습니다. |
| content-81d4e7c5723598f6 | PENDING_WITHOUT_PUBLISH_LOG | pending | - | 아니오 | status=pending - 아직 게시 이력이 없습니다(정상). |
| content-b4b9a05c461ad595 | ORPHAN | - | 18099811769051475 | 아니오 | 게시 이력에는 있지만 pending 파일에 해당 content_id가 없습니다. |
| content-cbcf705b6056c9fc | PENDING_WITHOUT_PUBLISH_LOG | pending | - | 아니오 | status=pending - 아직 게시 이력이 없습니다(정상). |
| content-ce61d77ee620c435 | ORPHAN | - | 18106714145192600 | 아니오 | 게시 이력에는 있지만 pending 파일에 해당 content_id가 없습니다. |
| content-dbf0fb4eb5cfd791 | PENDING_WITHOUT_PUBLISH_LOG | pending | - | 아니오 | status=pending - 아직 게시 이력이 없습니다(정상). |
| content-f2082a27c88c26ca | ORPHAN | - | 18114019807999154 | 아니오 | 게시 이력에는 있지만 pending 파일에 해당 content_id가 없습니다. |
| content-ff8909844fa80b99 | ORPHAN | - | 18150952027524083 | 아니오 | 게시 이력에는 있지만 pending 파일에 해당 content_id가 없습니다. |

## 사람이 확인해야 하는 항목

- `content-45d8e97f0fab7b16` (ORPHAN): 게시 이력에는 있지만 pending 파일에 해당 content_id가 없습니다.
- `content-6de1e17342ba9642` (ORPHAN): 게시 이력에는 있지만 pending 파일에 해당 content_id가 없습니다.
- `content-b4b9a05c461ad595` (ORPHAN): 게시 이력에는 있지만 pending 파일에 해당 content_id가 없습니다.
- `content-ce61d77ee620c435` (ORPHAN): 게시 이력에는 있지만 pending 파일에 해당 content_id가 없습니다.
- `content-f2082a27c88c26ca` (ORPHAN): 게시 이력에는 있지만 pending 파일에 해당 content_id가 없습니다.
- `content-ff8909844fa80b99` (ORPHAN): 게시 이력에는 있지만 pending 파일에 해당 content_id가 없습니다.

## 자동 복구 가능(safe_to_sync) 항목

자동 복구 가능한 항목이 없습니다.

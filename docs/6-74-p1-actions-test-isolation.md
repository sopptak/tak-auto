# 6-74 P1 Actions 테스트 격리 보고서

1. 시작 commit: `eb4ce91`
2. 최종 commit: 이 문서를 포함한 커밋 (`git log -1`로 확인)
3. 수정 파일: `tests/test_collect_performance_live_gate.py`, `docs/6-74-tak-factory-p1-performance-automation.md`, 본 문서
4. 수정 이유: 테스트가 러너의 `GITHUB_ACTIONS=true`에 의존해 Actions에서만 실패했다. production guard(`TAK_PERFORMANCE_ALLOW_GITHUB_ACTIONS`)와 workflow는 변경하지 않았다.
5. 수정 전 실패(`GITHUB_ACTIONS=true`, 81건 중 3건 실패, 재현 확인):
   - `test_threads_confirm_live_proceeds_with_mocked_client`
   - `test_youtube_confirm_live_proceeds_with_mocked_client`
   - `test_no_dry_run_no_confirm_live_is_rejected`
6. 수정 후: 81건 모두 통과.
7. 일반 환경: performance 8개 모듈 81 OK.
8. `GITHUB_ACTIONS=true`: 81 OK.
9. 전체 non-game pytest: 1740 passed, 31 failed, 118 skipped, 271 subtests (일반/Actions 환경 동일). 31건 실패는 모두 `tests/test_6_55_shorts_studio.py`(Windows 폰트 경로)이며 신규 실패는 없다.
10. workflow 정적 검증: schedule `30 7 * * *`, `workflow_dispatch` 존재, 기본 `dry_run=true`, live step은 `--scheduled --confirm-live`와 `TAK_PERFORMANCE_ALLOW_GITHUB_ACTIONS=true`, `THREADS_ACCESS_TOKEN` secret 사용, dry-run step은 credential 미전달, 오류 시 snapshot 미저장, commit은 `data/tak_performance.json`만 대상. 기존 `tests/test_performance_workflow.py`가 이를 검증한다.
11. 실제 API 호출: 없음. `--scheduled --dry-run`만 실행했고 `data/tak_performance.json`은 실행 전후 md5가 동일하다.
12. 24h snapshot: 없음. dry-run은 P0(`content-3978f6da76aebf01`, post `18085925933320004`)를 window=24h due target 1건으로 판정했고 initial snapshot은 24h로 세지 않았다. 중복 방지, `measurement_window=24h`, `source=threads_api`, lineage 유지는 mock 기반 `tests/test_collect_performance_scheduled_cli.py`와 schedule 테스트로 검증됐다.
13. 72h snapshot: 없음 (72h 마감 2026-10-04 07:23 UTC).
14. push 여부: 본 보고서 작성 시점에는 미수행. push 후 결과는 채팅 보고를 따른다.
15. 다음 실제 운영 검증 조건: 수정 commit이 main에 반영된 뒤 scheduled run(또는 권한 있는 수동 dispatch)에서 테스트 step 통과, `THREADS_ACCESS_TOKEN` 유효, 24h 이상 72h 미만 구간에서 24h snapshot이 1건 저장되고 `chore: collect due Threads performance snapshots` commit이 생성되는지 확인.

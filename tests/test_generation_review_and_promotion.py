"""6-08 회귀 테스트: Generation Pool 인간검수(승인/보류) + 안전한 Promotion.

docs/6-08_generation_review_and_promotion.md 참고. 실제 LLM은 호출하지 않는다.
실제 production archive(``data/tak_media_archive.json``)와 실제 generation pool
파일(``data/tak_media_generation_*.json``)은 이 테스트 파일이 만든 fixture와
완전히 별개다 - 전부 ``tempfile.TemporaryDirectory()`` 안에서만 동작한다.

이 파일이 다루는 범위(6-07의 test_second_knowledge_correction_and_generation_pool.py
의 GenerationPoolDashboardRouteTests와 중복되지 않는 것만):
    - auto-discovery(``discover_generation_pool_paths``/``resolve_generation_archive_paths``)
    - 개별 승인/보류 HTTP 라우트가 review_status만 바꾸고 production archive는
      절대 건드리지 않는지
    - generation 전체 승인(approve-all)이 다른 generation을 섞지 않는지
    - ``scripts/promote_media_generation.py``의 promotion gate(unreviewed/rejected
      차단, approved+valid만 허용, idempotent, 부분 승인 시 승인분만 승격)
"""

from __future__ import annotations

from http.server import ThreadingHTTPServer
from pathlib import Path
import hashlib
import io
import contextlib
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from content_engine.media_archive import (
    MediaArchiveRecord,
    load_archive,
    save_archive,
    upsert_generation_archive,
)
from scripts.run_scout_dashboard import (
    DashboardConfig,
    discover_generation_pool_paths,
    group_generation_records_by_knowledge_and_generation,
    group_records_by_platform,
    make_handler_class,
    resolve_generation_archive_paths,
)
from scripts.promote_media_generation import PromotionError, main as promote_main, plan_promotion


def _record(**overrides) -> MediaArchiveRecord:
    fields = {
        "content_id": "content-6-08-test-1",
        "knowledge_id": "knowledge-6-08-test",
        "platform": "blog",
        "generation_status": "valid",
        "original_title": "원본 제목",
        "original_body": "원본 본문",
        "rewritten_title": "재작성 제목",
        "rewritten_body": "재작성 본문",
        "source_url": "https://example.test/6-08",
        "evidence": ("SOURCE FACT: 예시",),
        "evidence_unit_ids": ("lesson:1",),
        "created_at": "2026-09-20T00:00:00+00:00",
        "review_status": "unreviewed",
        "generation_id": "gen-6-08-a",
    }
    fields.update(overrides)
    return MediaArchiveRecord(**fields)


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- A/B: auto-discovery ------------------------------------------------


class AutoDiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data_dir = Path(self._tmp.name)

    def test_discovers_matching_generation_pool_files(self):
        (self.data_dir / "tak_media_generation_a.json").write_text("[]", encoding="utf-8")
        (self.data_dir / "tak_media_generation_b.json").write_text("[]", encoding="utf-8")

        found = discover_generation_pool_paths(self.data_dir)

        self.assertEqual(
            {path.name for path in found},
            {"tak_media_generation_a.json", "tak_media_generation_b.json"},
        )

    def test_production_archive_is_never_discovered(self):
        """production archive(``tak_media_archive.json``)는 이름 규칙이
        ``tak_media_generation_*``와 다르므로 glob 대상에서 구조적으로 제외된다."""
        (self.data_dir / "tak_media_archive.json").write_text("[]", encoding="utf-8")
        (self.data_dir / "tak_media_generation_x.json").write_text("[]", encoding="utf-8")

        found = discover_generation_pool_paths(self.data_dir)

        self.assertEqual([path.name for path in found], ["tak_media_generation_x.json"])

    def test_missing_data_dir_returns_empty_tuple(self):
        missing = self.data_dir / "does-not-exist"
        self.assertEqual(discover_generation_pool_paths(missing), ())

    def test_resolve_prefers_explicit_paths_over_discovery(self):
        explicit = (self.data_dir / "legacy_name.json",)
        (self.data_dir / "tak_media_generation_auto.json").write_text("[]", encoding="utf-8")

        resolved = resolve_generation_archive_paths(explicit, self.data_dir)

        self.assertEqual(resolved, explicit)

    def test_resolve_falls_back_to_discovery_when_no_explicit_paths(self):
        (self.data_dir / "tak_media_generation_auto.json").write_text("[]", encoding="utf-8")

        resolved = resolve_generation_archive_paths((), self.data_dir)

        self.assertEqual([path.name for path in resolved], ["tak_media_generation_auto.json"])


# --- C/D/E/L/M: 승인/보류 HTTP 라우트 + Production Archive 보호 -----------


class DashboardApprovalRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.directory = Path(self._tmp.name)

        self.knowledge_path = self.directory / "tak_brain_knowledge.json"
        self.knowledge_path.write_text("[]", encoding="utf-8")

        self.archive_path = self.directory / "tak_media_archive.json"
        save_archive(
            [
                MediaArchiveRecord(
                    content_id="content-existing-production",
                    knowledge_id="knowledge-existing",
                    platform="blog",
                    generation_status="valid",
                    original_title="기존 production 제목",
                    original_body="기존 production 본문",
                    rewritten_title="기존 production 재작성 제목",
                    rewritten_body="기존 production 재작성 본문",
                    source_url="https://example.test/production",
                    evidence=(),
                    evidence_unit_ids=(),
                    created_at="2026-09-01T00:00:00+00:00",
                    review_status="approved",
                )
            ],
            self.archive_path,
        )

        self.pool_path = self.directory / "tak_media_generation_test.json"
        upsert_generation_archive(
            self.pool_path,
            [
                _record(content_id="content-gen-1", platform="blog", generation_id="gen-target"),
                _record(content_id="content-gen-2", platform="shorts", generation_id="gen-target"),
                _record(
                    content_id="content-gen-rejected",
                    platform="threads",
                    generation_id="gen-target",
                    generation_status="rejected",
                    validation_errors=("threads 500자 초과",),
                ),
                _record(content_id="content-other-gen", platform="blog", generation_id="gen-other"),
            ],
        )

        self.config = DashboardConfig(
            daily_pack_path=self.directory / "tak_scout_daily.json",
            answers_path=self.directory / "tak_interview_answers.json",
            knowledge_path=self.knowledge_path,
            skipped_path=self.directory / "tak_scout_dashboard_skipped.json",
            sessions_path=self.directory / "tak_interview_sessions.json",
            pending_path=self.directory / "tak_threads_pending.json",
            media_archive_path=self.archive_path,
            shorts_scripts_path=self.directory / "shorts_scripts",
            blog_history_path=self.directory / "blog_publish_log.json",
            generation_archive_paths=(self.pool_path,),
        )
        self._start_server()

    def _start_server(self) -> None:
        handler_class = make_handler_class(self.config)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler_class)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._shutdown)

    def _shutdown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _post(self, path: str) -> tuple[int, str]:
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=b"", method="POST")
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            return error.code, error.read().decode("utf-8")

    def _records_by_content_id(self) -> dict[str, MediaArchiveRecord]:
        return {record.content_id: record for record in load_archive(self.pool_path)}

    def test_approve_single_record_updates_only_that_record(self):
        status, _ = self._post("/media/generations/record/content-gen-1/gen-target/approve")

        self.assertEqual(status, 200)
        records = self._records_by_content_id()
        self.assertEqual(records["content-gen-1"].review_status, "approved")
        self.assertEqual(records["content-gen-2"].review_status, "unreviewed")

    def test_approving_generation_pool_never_touches_production_archive(self):
        before_hash = _file_hash(self.archive_path)

        self._post("/media/generations/record/content-gen-1/gen-target/approve")
        self._post("/media/generations/generation/gen-target/approve-all")

        after_hash = _file_hash(self.archive_path)
        self.assertEqual(before_hash, after_hash)
        production_records = load_archive(self.archive_path)
        self.assertEqual(len(production_records), 1)
        self.assertEqual(production_records[0].content_id, "content-existing-production")

    def test_dismiss_sets_review_status_to_dismissed(self):
        """dismiss는 아직 approved가 아닌(unreviewed) 레코드에만 적용된다 - 이미
        approved된 레코드는 _can_review_generation_record()가 False가 되어 UI에
        액션 버튼 자체가 사라지고, 서버도 review_status=="approved"인 레코드는
        재검토 대상이 아니라고 보고 그대로 반환한다(승인 후 실수로 dismiss를
        보내도 승인 상태가 뒤집히지 않는 안전장치)."""
        status, _ = self._post("/media/generations/record/content-gen-2/gen-target/dismiss")

        self.assertEqual(status, 200)
        self.assertEqual(self._records_by_content_id()["content-gen-2"].review_status, "dismissed")

    def test_dismiss_does_not_revert_an_already_approved_record(self):
        self._post("/media/generations/record/content-gen-1/gen-target/approve")
        status, _ = self._post("/media/generations/record/content-gen-1/gen-target/dismiss")

        self.assertEqual(status, 200)
        self.assertEqual(self._records_by_content_id()["content-gen-1"].review_status, "approved")

    def test_approve_all_marks_only_valid_records_in_that_generation(self):
        status, _ = self._post("/media/generations/generation/gen-target/approve-all")

        self.assertEqual(status, 200)
        records = self._records_by_content_id()
        self.assertEqual(records["content-gen-1"].review_status, "approved")
        self.assertEqual(records["content-gen-2"].review_status, "approved")
        # rejected 레코드는 "전체 승인"을 눌러도 승인되지 않는다.
        self.assertEqual(records["content-gen-rejected"].review_status, "unreviewed")

    def test_approve_all_does_not_touch_a_different_generation(self):
        self._post("/media/generations/generation/gen-target/approve-all")

        records = self._records_by_content_id()
        self.assertEqual(records["content-other-gen"].review_status, "unreviewed")

    def test_approve_nonexistent_record_returns_404(self):
        status, body = self._post("/media/generations/record/content-does-not-exist/gen-target/approve")
        self.assertEqual(status, 404)
        self.assertIn("찾을 수 없습니다", body)

    def test_approve_rejected_record_is_rejected_with_400(self):
        status, body = self._post("/media/generations/record/content-gen-rejected/gen-target/approve")
        self.assertEqual(status, 400)
        self.assertIn("VALID", body)
        self.assertEqual(self._records_by_content_id()["content-gen-rejected"].review_status, "unreviewed")

    def test_double_approve_is_idempotent(self):
        self._post("/media/generations/record/content-gen-1/gen-target/approve")
        status, _ = self._post("/media/generations/record/content-gen-1/gen-target/approve")

        self.assertEqual(status, 200)
        self.assertEqual(self._records_by_content_id()["content-gen-1"].review_status, "approved")


# --- L/M: generation 그룹핑 -----------------------------------------------


class GenerationGroupingTests(unittest.TestCase):
    def test_same_knowledge_different_generation_ids_are_kept_separate(self):
        records = [
            _record(content_id="c1", knowledge_id="k1", generation_id="gen-1"),
            _record(content_id="c2", knowledge_id="k1", generation_id="gen-2"),
        ]

        groups = group_generation_records_by_knowledge_and_generation(records)

        keys = [key for key, _ in groups]
        self.assertEqual(len(keys), 2)
        self.assertIn(("k1", "gen-1"), keys)
        self.assertIn(("k1", "gen-2"), keys)

    def test_group_records_by_platform_orders_blog_shorts_threads_first(self):
        records = [
            _record(content_id="c1", platform="threads"),
            _record(content_id="c2", platform="blog"),
            _record(content_id="c3", platform="shorts"),
        ]

        grouped = group_records_by_platform(records)

        self.assertEqual([platform for platform, _ in grouped], ["blog", "shorts", "threads"])


# --- F/G/H/I/N: Promotion 안전성 검증 (임시 archive만 사용) ----------------


class PromotionSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.directory = Path(self._tmp.name)
        self.generation_path = self.directory / "tak_media_generation_promo_test.json"
        self.production_path = self.directory / "tak_media_archive_6-08_test.json"

    def _seed_pool(self, records: list[MediaArchiveRecord]) -> None:
        save_archive(records, self.generation_path)

    def test_case_a_unreviewed_valid_blocks_promotion(self):
        self._seed_pool([_record(content_id="c-a", review_status="unreviewed", generation_status="valid")])

        with self.assertRaises(PromotionError):
            plan_promotion(self.generation_path, self.production_path, "c-a", "gen-6-08-a")

    def test_case_b_approved_rejected_blocks_promotion(self):
        self._seed_pool([_record(content_id="c-b", review_status="approved", generation_status="rejected")])

        with self.assertRaises(PromotionError):
            plan_promotion(self.generation_path, self.production_path, "c-b", "gen-6-08-a")

    def test_case_c_approved_valid_is_allowed(self):
        self._seed_pool([_record(content_id="c-c", review_status="approved", generation_status="valid")])

        candidate, current_active = plan_promotion(
            self.generation_path, self.production_path, "c-c", "gen-6-08-a"
        )

        self.assertEqual(candidate.content_id, "c-c")
        self.assertIsNone(current_active)

    def test_case_d_execute_writes_into_temporary_production_archive_only(self):
        self._seed_pool([_record(content_id="c-d", review_status="approved", generation_status="valid")])
        self.assertFalse(self.production_path.exists())

        exit_code = self._run_promote_main(content_id="c-d", generation_id="gen-6-08-a", execute=True)

        self.assertEqual(exit_code, 0)
        production_records = load_archive(self.production_path)
        self.assertEqual(len(production_records), 1)
        self.assertEqual(production_records[0].content_id, "c-d")
        self.assertEqual(production_records[0].generation_id, "gen-6-08-a")

    def test_case_d_dry_run_does_not_create_production_archive(self):
        self._seed_pool([_record(content_id="c-d2", review_status="approved", generation_status="valid")])

        exit_code = self._run_promote_main(content_id="c-d2", generation_id="gen-6-08-a", execute=False)

        self.assertEqual(exit_code, 0)
        self.assertFalse(self.production_path.exists())

    def test_case_e_repeated_promotion_is_idempotent(self):
        self._seed_pool([_record(content_id="c-e", review_status="approved", generation_status="valid")])
        self._run_promote_main(content_id="c-e", generation_id="gen-6-08-a", execute=True)
        after_first = load_archive(self.production_path)
        first_hash = _file_hash(self.production_path)

        exit_code = self._run_promote_main(content_id="c-e", generation_id="gen-6-08-a", execute=True)

        self.assertEqual(exit_code, 0)
        after_second = load_archive(self.production_path)
        second_hash = _file_hash(self.production_path)
        self.assertEqual(len(after_first), len(after_second), 1)
        self.assertEqual(first_hash, second_hash)

    def test_case_f_partial_approval_only_promotes_approved_record(self):
        """같은 generation 안에서 일부 record만 approved일 때, approved record만
        promotion 대상이 된다는 것을 확인한다. 현재 promote_media_generation.py는
        (content_id, generation_id) 단위로 승격하는 설계이므로(generation 전체를
        하나의 단위로 승격하지 않는다), 이 정책을 그대로 검증한다 - 새로 만들지
        않는다."""
        self._seed_pool(
            [
                _record(content_id="c-f-approved", review_status="approved", generation_status="valid"),
                _record(content_id="c-f-pending", review_status="unreviewed", generation_status="valid"),
            ]
        )

        approved_exit_code = self._run_promote_main(
            content_id="c-f-approved", generation_id="gen-6-08-a", execute=True
        )
        self.assertEqual(approved_exit_code, 0)

        with self.assertRaises(PromotionError):
            plan_promotion(self.generation_path, self.production_path, "c-f-pending", "gen-6-08-a")

        production_content_ids = {record.content_id for record in load_archive(self.production_path)}
        self.assertEqual(production_content_ids, {"c-f-approved"})

    def _run_promote_main(self, *, content_id: str, generation_id: str, execute: bool) -> int:
        argv = [
            "--archive",
            str(self.generation_path),
            "--production-archive",
            str(self.production_path),
            "--content-id",
            content_id,
            "--generation-id",
            generation_id,
        ]
        if execute:
            argv.append("--execute")
        with contextlib.redirect_stdout(io.StringIO()):
            return promote_main(argv)


if __name__ == "__main__":
    unittest.main()

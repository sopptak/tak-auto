"""scripts/publish_threads.py의 --auto 자동 선정 및 게시 이력 기록/미기록 동작 검증.

실제 Threads API는 절대 호출하지 않는다. ``ThreadsClient.from_environment``를 patch하여
네트워크 대신 가짜 transport로 프로필 조회/게시 성공·실패를 시뮬레이션한다.

6-25(docs/6-25-threads-publish-path-consolidation.md)에서 이 스크립트에 Production
Archive 기반 eligibility 게이트가 추가됐다 - 이 파일의 모든 기존 테스트는 이제
"이 batch 항목들이 production archive에 approved 상태로 이미 존재한다"를 기본 전제로
삼는다(``_write_batch()``가 자동으로 매칭되는 approved archive record를 함께 쓴다).
게이트 자체(미승인/superseded/orphan 차단)를 검증하는 테스트는
``PublishThreadsEligibilityGateTests``에 별도로 있다.
"""

from pathlib import Path
import json
import tempfile
import unittest
from unittest import mock

from content_engine.media_archive import MediaArchiveRecord, save_archive
from content_engine.publish_history import PublishHistory, PublishRecord, compute_content_id
from content_engine.threads_publisher import ThreadsAPIError, ThreadsClient
from scripts.publish_threads import main


def _batch_data(items):
    return {"all_items": items}


def _threads_item(**overrides):
    base = {
        "knowledge_id": "k-001",
        "platform": "threads",
        "status": "valid",
        "source_url": "https://example.test/source",
        "original_title": "원문 제목",
        "original_body": "원문 본문",
        "rewritten_title": "재작성 제목",
        "rewritten_body": "1인칭으로 다시 쓴 본문입니다.",
        "evidence_unit_ids": ["lesson:1"],
    }
    base.update(overrides)
    return base


def _success_transport(post_id="th_post_auto_1"):
    def transport(method, url, headers, payload, timeout):
        if method == "GET":
            return {"id": "111", "username": "tmong_wisdom", "name": "티몽의 지혜"}
        return {"id": post_id}

    return transport


def _failure_transport():
    def transport(method, url, headers, payload, timeout):
        if method == "GET":
            return {"id": "111", "username": "tmong_wisdom", "name": "티몽의 지혜"}
        raise ThreadsAPIError("Threads HTTP 500: message=Internal error")

    return transport


def _approved_record_for(item: dict) -> MediaArchiveRecord:
    """batch 항목과 같은 content_id를 갖는, 이미 approved인 production archive
    레코드를 만든다(6-25 - 이 게시 경로가 이제 요구하는 승인 상태)."""
    return MediaArchiveRecord(
        content_id=compute_content_id(item),
        knowledge_id=str(item.get("knowledge_id") or ""),
        platform=str(item.get("platform") or "threads"),
        generation_status="valid",
        original_title=str(item.get("original_title") or ""),
        original_body=str(item.get("original_body") or ""),
        rewritten_title=item.get("rewritten_title"),
        rewritten_body=item.get("rewritten_body"),
        source_url=str(item.get("source_url") or ""),
        evidence=tuple(item.get("evidence") or ()),
        evidence_unit_ids=tuple(item.get("evidence_unit_ids") or ()),
        created_at="2026-01-01T00:00:00Z",
        review_status="approved",
    )


class PublishThreadsAutoSelectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.tmp_path = Path(self.tmp_dir.name)
        self.input_path = self.tmp_path / "batch.json"
        self.history_path = self.tmp_path / "threads_publish_log.json"
        self.archive_path = self.tmp_path / "tak_media_archive.json"

    def _write_batch(self, items) -> None:
        """batch 파일을 쓰고, 6-25 eligibility 게이트를 통과하도록 같은
        content_id로 approved production archive record도 함께 쓴다(이 파일의
        기존 테스트들은 전부 "이미 승인된 콘텐츠"를 전제로 하기 때문 - 게이트
        자체를 검증하는 테스트는 별도 클래스에 있다)."""
        self.input_path.write_text(
            json.dumps(_batch_data(items), ensure_ascii=False), encoding="utf-8"
        )
        threads_items = [item for item in items if item.get("platform") == "threads"]
        save_archive([_approved_record_for(item) for item in threads_items], self.archive_path)

    def _run(self, extra_args):
        return main(
            [
                "--input", str(self.input_path),
                "--history", str(self.history_path),
                "--production-archive", str(self.archive_path),
                *extra_args,
            ]
        )

    # --- 이력 파일이 없는 경우 / 비어 있는 경우 -----------------------------------

    def test_auto_dry_run_without_history_file_selects_first_valid_item(self):
        self._write_batch([_threads_item()])

        exit_code = self._run(["--auto", "--dry-run"])

        self.assertEqual(exit_code, 0)
        self.assertFalse(self.history_path.exists(), "dry-run은 이력 파일을 생성하면 안 됩니다.")

    def test_auto_dry_run_with_empty_history_file(self):
        self.history_path.write_text("[]", encoding="utf-8")
        self._write_batch([_threads_item()])

        exit_code = self._run(["--auto", "--dry-run"])

        self.assertEqual(exit_code, 0)

    # --- valid Threads 콘텐츠가 여러 개인 경우 -------------------------------------

    def test_auto_selects_first_candidate_among_multiple_valid_items(self):
        items = [
            _threads_item(knowledge_id="k-001", evidence_unit_ids=["a:1"]),
            _threads_item(knowledge_id="k-002", evidence_unit_ids=["a:2"]),
        ]
        self._write_batch(items)

        fake_client = ThreadsClient(access_token="fake-token", transport=_success_transport("th_post_1"))
        with mock.patch.object(ThreadsClient, "from_environment", return_value=fake_client):
            exit_code = self._run(["--auto"])

        self.assertEqual(exit_code, 0)
        records = PublishHistory(self.history_path).load()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["knowledge_id"], "k-001")

    # --- 이미 게시한 콘텐츠가 포함된 경우: 다음 미게시 항목을 선택 ------------------------

    def test_auto_skips_already_published_item(self):
        items = [
            _threads_item(knowledge_id="k-001", evidence_unit_ids=["a:1"]),
            _threads_item(knowledge_id="k-002", evidence_unit_ids=["a:2"]),
        ]
        self._write_batch(items)

        history = PublishHistory(self.history_path)
        history.append(
            PublishRecord(
                content_id=compute_content_id(items[0]),
                published_at="2026-09-12T23:00:00+00:00",
                threads_post_id="th_post_already",
            )
        )

        fake_client = ThreadsClient(access_token="fake-token", transport=_success_transport("th_post_2"))
        with mock.patch.object(ThreadsClient, "from_environment", return_value=fake_client):
            exit_code = self._run(["--auto"])

        self.assertEqual(exit_code, 0)
        records = PublishHistory(self.history_path).load()
        self.assertEqual(len(records), 2)
        self.assertEqual(records[-1]["knowledge_id"], "k-002")
        self.assertEqual(records[-1]["threads_post_id"], "th_post_2")

    # --- 모든 콘텐츠가 이미 게시된 경우: "게시할 콘텐츠 없음" 정상 종료 ------------------

    def test_auto_returns_no_content_when_all_items_already_published(self, ):
        items = [_threads_item(knowledge_id="k-001", evidence_unit_ids=["a:1"])]
        self._write_batch(items)

        history = PublishHistory(self.history_path)
        history.append(
            PublishRecord(
                content_id=compute_content_id(items[0]),
                published_at="t",
                threads_post_id="p",
            )
        )

        with mock.patch.object(ThreadsClient, "from_environment") as from_env:
            exit_code = self._run(["--auto"])

        from_env.assert_not_called()
        self.assertEqual(exit_code, 0)
        # 이력은 변하지 않아야 한다 (신규 게시가 없었으므로)
        self.assertEqual(len(history.load()), 1)

    # --- invalid 콘텐츠만 있는 경우 -------------------------------------------------

    def test_auto_returns_no_content_when_only_invalid_items_exist(self):
        # load_valid_threads_items가 이미 platform/status로 걸러내므로 valid_items 자체가 비어
        # "알림: ... valid 상태의 Threads 콘텐츠가 없습니다." 경로로 빠지는 것이 정상이다.
        items = [
            _threads_item(status="rejected", knowledge_id="k-001"),
            _threads_item(platform="blog", status="valid", knowledge_id="k-002"),
        ]
        self._write_batch(items)

        exit_code = self._run(["--auto"])

        self.assertEqual(exit_code, 1)
        self.assertFalse(self.history_path.exists())

    # --- dry-run에서는 실제 게시 이력을 기록하지 않는다 -------------------------------

    def test_dry_run_never_writes_history_even_when_candidate_exists(self):
        self._write_batch([_threads_item()])

        with mock.patch.object(ThreadsClient, "from_environment") as from_env:
            exit_code = self._run(["--auto", "--dry-run"])

        from_env.assert_not_called()
        self.assertEqual(exit_code, 0)
        self.assertFalse(self.history_path.exists())

    # --- 실제 게시 성공 시에만 이력 기록 ---------------------------------------------

    def test_real_publish_success_records_history_with_post_id(self):
        self._write_batch([_threads_item(knowledge_id="k-001")])

        fake_client = ThreadsClient(access_token="fake-token", transport=_success_transport("th_post_success"))
        with mock.patch.object(ThreadsClient, "from_environment", return_value=fake_client):
            exit_code = self._run(["--auto"])

        self.assertEqual(exit_code, 0)
        records = PublishHistory(self.history_path).load()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["threads_post_id"], "th_post_success")
        self.assertEqual(records[0]["knowledge_id"], "k-001")
        self.assertIn("published_at", records[0])

    # --- 실제 게시 실패 시 이력 미기록 -----------------------------------------------

    def test_real_publish_failure_does_not_record_history(self):
        self._write_batch([_threads_item(knowledge_id="k-001")])

        fake_client = ThreadsClient(access_token="fake-token", transport=_failure_transport())
        with mock.patch.object(ThreadsClient, "from_environment", return_value=fake_client):
            exit_code = self._run(["--auto"])

        self.assertEqual(exit_code, 1)
        self.assertFalse(self.history_path.exists(), "게시 실패 시 이력 파일이 생성되면 안 됩니다.")

    def test_real_publish_failure_leaves_existing_history_untouched(self):
        items = [
            _threads_item(knowledge_id="k-001", evidence_unit_ids=["a:1"]),
            _threads_item(knowledge_id="k-002", evidence_unit_ids=["a:2"]),
        ]
        self._write_batch(items)
        history = PublishHistory(self.history_path)
        history.append(
            PublishRecord(
                content_id=compute_content_id(items[0]),
                published_at="t",
                threads_post_id="p",
            )
        )

        fake_client = ThreadsClient(access_token="fake-token", transport=_failure_transport())
        with mock.patch.object(ThreadsClient, "from_environment", return_value=fake_client):
            exit_code = self._run(["--auto"])

        self.assertEqual(exit_code, 1)
        records = history.load()
        self.assertEqual(len(records), 1, "실패한 게시 시도가 기존 이력에 추가되면 안 됩니다.")

    # --- 기존 --index 수동 지정 방식과의 호환성 -------------------------------------

    def test_manual_index_still_works_and_records_history_on_success(self):
        items = [
            _threads_item(knowledge_id="k-001", evidence_unit_ids=["a:1"]),
            _threads_item(knowledge_id="k-002", evidence_unit_ids=["a:2"]),
        ]
        self._write_batch(items)

        fake_client = ThreadsClient(access_token="fake-token", transport=_success_transport("th_post_manual"))
        with mock.patch.object(ThreadsClient, "from_environment", return_value=fake_client):
            exit_code = self._run(["--index", "2"])

        self.assertEqual(exit_code, 0)
        records = PublishHistory(self.history_path).load()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["knowledge_id"], "k-002")

    def test_manual_index_dry_run_unaffected_by_auto_changes(self):
        self._write_batch([_threads_item()])

        exit_code = self._run(["--index", "1", "--dry-run"])

        self.assertEqual(exit_code, 0)
        self.assertFalse(self.history_path.exists())

    # --- 5-10 Phase 4-4: --auto 전체 CLI 경로에서도 KNOWLEDGE rotation이 적용되는지 ----

    def test_auto_cli_rotates_across_knowledge_before_repeating(self):
        items = [
            _threads_item(knowledge_id="k-001", evidence_unit_ids=["a:1"]),
            _threads_item(knowledge_id="k-001", evidence_unit_ids=["a:2"]),
            _threads_item(knowledge_id="k-002", evidence_unit_ids=["b:1"]),
        ]
        self._write_batch(items)
        fake_client = ThreadsClient(access_token="fake-token", transport=_success_transport("th_post_x"))

        selected_knowledge_ids = []
        for _ in range(3):
            with mock.patch.object(ThreadsClient, "from_environment", return_value=fake_client):
                exit_code = self._run(["--auto"])
            self.assertEqual(exit_code, 0)
            selected_knowledge_ids.append(PublishHistory(self.history_path).load()[-1]["knowledge_id"])

        # 1회차 k-001(첫 항목) -> 2회차 아직 등장하지 않은 k-002 우선 -> 3회차 다시 k-001(남은 항목)
        self.assertEqual(selected_knowledge_ids, ["k-001", "k-002", "k-001"])


# --- 6-25: Production Archive eligibility 게이트 자체(음성 시나리오) ------------------


class PublishThreadsEligibilityGateTests(unittest.TestCase):
    """``_write_batch()``의 자동 승인을 쓰지 않고, archive 상태를 직접 통제해
    게이트가 실제로 차단하는지 확인한다(docs/6-25-threads-publish-path-consolidation.md
    5장 Eligibility Contract)."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.tmp_path = Path(self.tmp_dir.name)
        self.input_path = self.tmp_path / "batch.json"
        self.history_path = self.tmp_path / "threads_publish_log.json"
        self.archive_path = self.tmp_path / "tak_media_archive.json"

    def _write_batch_only(self, items) -> None:
        self.input_path.write_text(json.dumps(_batch_data(items), ensure_ascii=False), encoding="utf-8")

    def _write_archive(self, records) -> None:
        save_archive(records, self.archive_path)

    def _run(self, extra_args):
        return main(
            [
                "--input", str(self.input_path),
                "--history", str(self.history_path),
                "--production-archive", str(self.archive_path),
                *extra_args,
            ]
        )

    def test_missing_production_archive_file_blocks_auto(self) -> None:
        """archive 파일 자체가 없으면(NOT_PRESENT) load_archive()가 빈 목록을
        반환하므로 모든 후보가 '레코드 없음'으로 차단된다."""
        self._write_batch_only([_threads_item()])
        # self.archive_path를 아예 쓰지 않는다(NOT_PRESENT).

        with mock.patch.object(ThreadsClient, "from_environment") as from_env:
            exit_code = self._run(["--auto"])

        self.assertEqual(exit_code, 0)  # "게시할 콘텐츠 없음"은 오류가 아니라 정상 종료
        from_env.assert_not_called()
        self.assertFalse(self.history_path.exists())

    def test_missing_archive_record_blocks_index(self) -> None:
        item = _threads_item()
        self._write_batch_only([item])
        self._write_archive([])  # archive는 있지만 이 content_id가 없음(orphan)

        with mock.patch.object(ThreadsClient, "from_environment") as from_env:
            exit_code = self._run(["--index", "1"])

        self.assertEqual(exit_code, 1)
        from_env.assert_not_called()

    def test_unreviewed_record_blocks_publish(self) -> None:
        item = _threads_item()
        self._write_batch_only([item])
        self._write_archive([_record_with_status(item, "unreviewed")])

        with mock.patch.object(ThreadsClient, "from_environment") as from_env:
            exit_code = self._run(["--index", "1"])

        self.assertEqual(exit_code, 1)
        from_env.assert_not_called()

    def test_dismissed_record_blocks_publish(self) -> None:
        item = _threads_item()
        self._write_batch_only([item])
        self._write_archive([_record_with_status(item, "dismissed")])

        with mock.patch.object(ThreadsClient, "from_environment") as from_env:
            exit_code = self._run(["--index", "1"])

        self.assertEqual(exit_code, 1)
        from_env.assert_not_called()

    def test_superseded_record_blocks_publish(self) -> None:
        item = _threads_item()
        new_content_item = _threads_item(knowledge_id="k-002", evidence_unit_ids=["b:1"])
        new_record = _approved_record_for(new_content_item)
        old_record_dict = {**_approved_record_for(item).to_dict(), "review_status": "superseded", "superseded_by": new_record.content_id}
        old_record = MediaArchiveRecord.from_dict(old_record_dict)
        self._write_batch_only([item])
        self._write_archive([old_record, new_record])

        with mock.patch.object(ThreadsClient, "from_environment") as from_env:
            exit_code = self._run(["--index", "1"])

        self.assertEqual(exit_code, 1)
        from_env.assert_not_called()

    def test_approved_and_not_superseded_is_eligible(self) -> None:
        """대조군: approved + 정상 레코드는 정상적으로 발행된다."""
        item = _threads_item()
        self._write_batch_only([item])
        self._write_archive([_approved_record_for(item)])

        fake_client = ThreadsClient(access_token="fake-token", transport=_success_transport("th_eligible"))
        with mock.patch.object(ThreadsClient, "from_environment", return_value=fake_client):
            exit_code = self._run(["--index", "1"])

        self.assertEqual(exit_code, 0)
        records = PublishHistory(self.history_path).load()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["threads_post_id"], "th_eligible")

    def test_auto_skips_ineligible_and_selects_eligible(self) -> None:
        """--auto가 후보 여러 건 중 승인된 것만 골라야 한다."""
        ineligible_item = _threads_item(knowledge_id="k-001", evidence_unit_ids=["a:1"])
        eligible_item = _threads_item(knowledge_id="k-002", evidence_unit_ids=["a:2"])
        self._write_batch_only([ineligible_item, eligible_item])
        self._write_archive([
            _record_with_status(ineligible_item, "unreviewed"),
            _approved_record_for(eligible_item),
        ])

        fake_client = ThreadsClient(access_token="fake-token", transport=_success_transport("th_auto_eligible"))
        with mock.patch.object(ThreadsClient, "from_environment", return_value=fake_client):
            exit_code = self._run(["--auto"])

        self.assertEqual(exit_code, 0)
        records = PublishHistory(self.history_path).load()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["knowledge_id"], "k-002")


def _record_with_status(item: dict, review_status: str) -> MediaArchiveRecord:
    record_dict = {**_approved_record_for(item).to_dict(), "review_status": review_status}
    return MediaArchiveRecord.from_dict(record_dict)


if __name__ == "__main__":
    unittest.main()

"""scripts/publish_threads.py의 --auto 자동 선정 및 게시 이력 기록/미기록 동작 검증.

실제 Threads API는 절대 호출하지 않는다. ``ThreadsClient.from_environment``를 patch하여
네트워크 대신 가짜 transport로 프로필 조회/게시 성공·실패를 시뮬레이션한다.
"""

from pathlib import Path
import json
import tempfile
import unittest
from unittest import mock

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


class PublishThreadsAutoSelectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.tmp_path = Path(self.tmp_dir.name)
        self.input_path = self.tmp_path / "batch.json"
        self.history_path = self.tmp_path / "threads_publish_log.json"

    def _write_batch(self, items) -> None:
        self.input_path.write_text(
            json.dumps(_batch_data(items), ensure_ascii=False), encoding="utf-8"
        )

    def _run(self, extra_args):
        return main(
            [
                "--input", str(self.input_path),
                "--history", str(self.history_path),
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


if __name__ == "__main__":
    unittest.main()

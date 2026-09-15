from pathlib import Path
import json
import tempfile
import unittest

from content_engine.publish_history import (
    PublishHistory,
    PublishHistoryError,
    PublishRecord,
    compute_content_id,
    select_unpublished_threads_item,
)


def _threads_item(**overrides):
    base = {
        "knowledge_id": "k-001",
        "platform": "threads",
        "status": "valid",
        "source_url": "https://example.test/source",
        "original_title": "원문 제목",
        "original_body": "원문 본문",
        "rewritten_title": "재작성 제목",
        "rewritten_body": "재작성 본문",
        "evidence_unit_ids": ["lesson:1"],
    }
    base.update(overrides)
    return base


class ComputeContentIdTests(unittest.TestCase):
    def test_same_stable_fields_produce_same_id(self):
        item_a = _threads_item(rewritten_body="첫 번째 재작성")
        item_b = _threads_item(rewritten_body="두 번째 재작성")  # LLM 재작성만 다름

        self.assertEqual(compute_content_id(item_a), compute_content_id(item_b))

    def test_different_evidence_unit_ids_produce_different_id(self):
        item_a = _threads_item(evidence_unit_ids=["lesson:1"])
        item_b = _threads_item(evidence_unit_ids=["lesson:2"])

        self.assertNotEqual(compute_content_id(item_a), compute_content_id(item_b))

    def test_different_platform_or_knowledge_produce_different_id(self):
        threads_item = _threads_item()
        shorts_item = _threads_item(platform="shorts")
        other_knowledge_item = _threads_item(knowledge_id="k-002")

        ids = {
            compute_content_id(threads_item),
            compute_content_id(shorts_item),
            compute_content_id(other_knowledge_item),
        }
        self.assertEqual(len(ids), 3)

    def test_content_id_is_deterministic_across_calls(self):
        item = _threads_item()
        self.assertEqual(compute_content_id(item), compute_content_id(item))

    def test_missing_optional_fields_do_not_raise(self):
        minimal_item = {"platform": "threads", "status": "valid"}
        content_id = compute_content_id(minimal_item)
        self.assertTrue(content_id.startswith("content-"))


class PublishHistoryStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.history_path = Path(self.tmp_dir.name) / "threads_publish_log.json"

    def test_missing_file_loads_as_empty(self):
        history = PublishHistory(self.history_path)
        self.assertEqual(history.load(), [])
        self.assertEqual(history.published_content_ids(), set())
        self.assertFalse(self.history_path.exists())

    def test_empty_file_loads_as_empty(self):
        self.history_path.write_text("", encoding="utf-8")
        history = PublishHistory(self.history_path)
        self.assertEqual(history.load(), [])

    def test_whitespace_only_file_loads_as_empty(self):
        self.history_path.write_text("   \n\t  ", encoding="utf-8")
        history = PublishHistory(self.history_path)
        self.assertEqual(history.load(), [])

    def test_corrupted_json_raises_publish_history_error(self):
        self.history_path.write_text("{not valid json", encoding="utf-8")
        history = PublishHistory(self.history_path)
        with self.assertRaises(PublishHistoryError):
            history.load()

    def test_non_list_json_raises_publish_history_error(self):
        self.history_path.write_text(json.dumps({"unexpected": "object"}), encoding="utf-8")
        history = PublishHistory(self.history_path)
        with self.assertRaises(PublishHistoryError):
            history.load()

    def test_append_creates_file_when_missing(self):
        history = PublishHistory(self.history_path)
        history.append(
            PublishRecord(
                content_id="content-abc123",
                published_at="2026-09-13T08:00:00+00:00",
                threads_post_id="th_post_1",
                knowledge_id="k-001",
                source_url="https://example.test/source",
            )
        )

        self.assertTrue(self.history_path.exists())
        records = history.load()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["content_id"], "content-abc123")
        self.assertEqual(records[0]["threads_post_id"], "th_post_1")
        self.assertIn("published_at", records[0])

    def test_append_preserves_existing_records(self):
        history = PublishHistory(self.history_path)
        history.append(
            PublishRecord(content_id="content-1", published_at="t1", threads_post_id="p1")
        )
        history.append(
            PublishRecord(content_id="content-2", published_at="t2", threads_post_id="p2")
        )

        records = history.load()
        self.assertEqual([r["content_id"] for r in records], ["content-1", "content-2"])
        self.assertEqual(history.published_content_ids(), {"content-1", "content-2"})

    def test_is_published_reflects_recorded_ids(self):
        history = PublishHistory(self.history_path)
        self.assertFalse(history.is_published("content-1"))
        history.append(
            PublishRecord(content_id="content-1", published_at="t1", threads_post_id="p1")
        )
        self.assertTrue(history.is_published("content-1"))
        self.assertFalse(history.is_published("content-2"))


class SelectUnpublishedThreadsItemTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.history_path = Path(self.tmp_dir.name) / "threads_publish_log.json"
        self.history = PublishHistory(self.history_path)

    def test_no_history_file_selects_first_valid_threads_item(self):
        items = [
            _threads_item(knowledge_id="k-001", evidence_unit_ids=["lesson:1"]),
            _threads_item(knowledge_id="k-002", evidence_unit_ids=["lesson:2"]),
        ]

        selection = select_unpublished_threads_item(items, self.history)

        self.assertIsNotNone(selection)
        selected_item, content_id = selection
        self.assertEqual(selected_item["knowledge_id"], "k-001")
        self.assertEqual(content_id, compute_content_id(items[0]))

    def test_empty_history_behaves_like_no_history(self):
        self.history_path.write_text("[]", encoding="utf-8")
        items = [_threads_item()]

        selection = select_unpublished_threads_item(items, self.history)

        self.assertIsNotNone(selection)

    def test_multiple_valid_candidates_uses_existing_order(self):
        items = [
            _threads_item(knowledge_id="k-001", evidence_unit_ids=["a:1"]),
            _threads_item(knowledge_id="k-002", evidence_unit_ids=["a:2"]),
            _threads_item(knowledge_id="k-003", evidence_unit_ids=["a:3"]),
        ]

        selection = select_unpublished_threads_item(items, self.history)

        self.assertEqual(selection[0]["knowledge_id"], "k-001")

    def test_already_published_item_is_skipped(self):
        first = _threads_item(knowledge_id="k-001", evidence_unit_ids=["a:1"])
        second = _threads_item(knowledge_id="k-002", evidence_unit_ids=["a:2"])
        self.history.append(
            PublishRecord(
                content_id=compute_content_id(first),
                published_at="t1",
                threads_post_id="p1",
            )
        )

        selection = select_unpublished_threads_item([first, second], self.history)

        self.assertEqual(selection[0]["knowledge_id"], "k-002")

    def test_all_items_already_published_returns_none(self):
        items = [
            _threads_item(knowledge_id="k-001", evidence_unit_ids=["a:1"]),
            _threads_item(knowledge_id="k-002", evidence_unit_ids=["a:2"]),
        ]
        for item in items:
            self.history.append(
                PublishRecord(
                    content_id=compute_content_id(item),
                    published_at="t",
                    threads_post_id="p",
                )
            )

        selection = select_unpublished_threads_item(items, self.history)

        self.assertIsNone(selection)

    def test_no_candidates_when_no_items(self):
        self.assertIsNone(select_unpublished_threads_item([], self.history))

    def test_invalid_status_items_are_ignored(self):
        items = [
            _threads_item(status="rejected", knowledge_id="k-001"),
            _threads_item(status="error", knowledge_id="k-002"),
        ]

        self.assertIsNone(select_unpublished_threads_item(items, self.history))

    def test_non_threads_platform_items_are_ignored(self):
        items = [
            _threads_item(platform="blog", knowledge_id="k-001"),
            _threads_item(platform="shorts", knowledge_id="k-002"),
        ]

        self.assertIsNone(select_unpublished_threads_item(items, self.history))

    def test_mixed_valid_and_invalid_selects_only_valid_threads(self):
        items = [
            _threads_item(platform="blog", status="valid", knowledge_id="k-blog"),
            _threads_item(platform="threads", status="rejected", knowledge_id="k-rejected"),
            _threads_item(platform="threads", status="valid", knowledge_id="k-good"),
        ]

        selection = select_unpublished_threads_item(items, self.history)

        self.assertEqual(selection[0]["knowledge_id"], "k-good")


class SelectUnpublishedThreadsItemRotationTests(unittest.TestCase):
    """5-10 Phase 4-4: 같은 knowledge_id가 연속으로 선택되지 않도록,
    아직 게시 이력에 없는 다른 KNOWLEDGE를 우선하는 rotation 정책을 검증한다.

    PublishHistory의 기존 중복 방지(content_id 기준)는 전혀 바뀌지 않았다 -
    이 테스트들은 "이미 게시 이력에 없는 후보들" 중에서 어떤 것을 우선
    고르는지만 다룬다.
    """

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.history_path = Path(self.tmp_dir.name) / "threads_publish_log.json"
        self.history = PublishHistory(self.history_path)

    def _record(self, item):
        self.history.append(
            PublishRecord(
                content_id=compute_content_id(item),
                published_at="t",
                threads_post_id="p",
                knowledge_id=str(item.get("knowledge_id") or ""),
            )
        )

    # 1. 서로 다른 knowledge_id가 있으면, history에 이미 등장한 KNOWLEDGE보다
    #    아직 등장하지 않은 다른 KNOWLEDGE를 우선 선택한다.
    def test_prefers_knowledge_id_not_yet_in_history(self):
        k1_1 = _threads_item(knowledge_id="k-001", evidence_unit_ids=["a:1"])
        k1_2 = _threads_item(knowledge_id="k-001", evidence_unit_ids=["a:2"])
        k2_1 = _threads_item(knowledge_id="k-002", evidence_unit_ids=["b:1"])
        k2_2 = _threads_item(knowledge_id="k-002", evidence_unit_ids=["b:2"])
        items = [k1_1, k1_2, k2_1, k2_2]

        # 첫 선택은 기존과 동일하게 생성 순서상 첫 항목(k1_1) - history가 비어 있으므로
        # "아직 등장하지 않은 KNOWLEDGE"가 여러 개라 원래 순서를 그대로 따른다.
        first = select_unpublished_threads_item(items, self.history)
        self.assertEqual(first[0]["knowledge_id"], "k-001")
        self._record(first[0])

        # 두 번째 선택: k-001은 이미 history에 있으므로, 생성 순서상 k1_2가 더
        # 앞에 있어도 아직 history에 없는 k-002(k2_1)를 우선해야 한다.
        second = select_unpublished_threads_item(items, self.history)
        self.assertEqual(second[0]["knowledge_id"], "k-002")
        self.assertEqual(second[1], compute_content_id(k2_1))

    # 2. K1의 다음 후보가 생성 순서상 K2보다 앞에 있어도 K2(아직 미사용 KNOWLEDGE)가 우선된다.
    def test_earlier_generation_order_does_not_override_rotation(self):
        k1_1 = _threads_item(knowledge_id="k-001", evidence_unit_ids=["a:1"])
        k1_2 = _threads_item(knowledge_id="k-001", evidence_unit_ids=["a:2"])
        k2_1 = _threads_item(knowledge_id="k-002", evidence_unit_ids=["b:1"])
        # k1_2가 k2_1보다 배치 결과상 앞에 오도록 순서를 구성한다.
        items = [k1_1, k1_2, k2_1]
        self._record(k1_1)  # k-001은 이미 한 번 게시됨

        selection = select_unpublished_threads_item(items, self.history)

        self.assertEqual(selection[0]["knowledge_id"], "k-002")
        self.assertEqual(selection[1], compute_content_id(k2_1))

    # 3. K2가 유효한 미게시 후보를 갖고 있지 않으면 K1의 다음 valid 후보로 fallback한다.
    def test_falls_back_to_same_knowledge_when_no_other_candidate_exists(self):
        k1_1 = _threads_item(knowledge_id="k-001", evidence_unit_ids=["a:1"])
        k1_2 = _threads_item(knowledge_id="k-001", evidence_unit_ids=["a:2"])
        k2_rejected = _threads_item(knowledge_id="k-002", status="rejected", evidence_unit_ids=["b:1"])
        items = [k1_1, k1_2, k2_rejected]
        self._record(k1_1)  # k-001만 이미 게시됨, k-002는 valid 후보가 없음(rejected)

        selection = select_unpublished_threads_item(items, self.history)

        self.assertEqual(selection[0]["knowledge_id"], "k-001")
        self.assertEqual(selection[1], compute_content_id(k1_2))

    # 4. 모든 후보가 같은 knowledge_id라면 기존처럼 다음 unpublished valid 후보를 선택한다.
    def test_single_knowledge_id_behaves_like_before(self):
        k1_1 = _threads_item(knowledge_id="k-001", evidence_unit_ids=["a:1"])
        k1_2 = _threads_item(knowledge_id="k-001", evidence_unit_ids=["a:2"])
        k1_3 = _threads_item(knowledge_id="k-001", evidence_unit_ids=["a:3"])
        items = [k1_1, k1_2, k1_3]
        self._record(k1_1)

        selection = select_unpublished_threads_item(items, self.history)

        self.assertEqual(selection[1], compute_content_id(k1_2))

    # 5. history에 이미 기록된 content_id는 rotation에서도 다시 선택되지 않는다.
    def test_already_published_content_id_never_reselected_in_rotation(self):
        k1_1 = _threads_item(knowledge_id="k-001", evidence_unit_ids=["a:1"])
        k2_1 = _threads_item(knowledge_id="k-002", evidence_unit_ids=["b:1"])
        items = [k1_1, k2_1]
        self._record(k1_1)
        self._record(k2_1)  # 둘 다 이미 게시됨

        selection = select_unpublished_threads_item(items, self.history)

        self.assertIsNone(selection)

    # 6. valid가 아닌 후보는 rotation 대상으로 쓰이지 않는다(기존 필터 유지 재확인).
    def test_invalid_candidates_excluded_from_rotation(self):
        k1_1 = _threads_item(knowledge_id="k-001", evidence_unit_ids=["a:1"])
        k2_rejected = _threads_item(knowledge_id="k-002", status="rejected", evidence_unit_ids=["b:1"])
        items = [k1_1, k2_rejected]
        self._record(k1_1)

        selection = select_unpublished_threads_item(items, self.history)

        self.assertIsNone(selection)

    # 7. Threads가 아닌 Blog/Shorts 후보는 rotation 대상에서 제외된다(기존 필터 유지 재확인).
    def test_non_threads_platform_excluded_from_rotation(self):
        k1_1 = _threads_item(knowledge_id="k-001", evidence_unit_ids=["a:1"])
        k2_blog = _threads_item(knowledge_id="k-002", platform="blog", evidence_unit_ids=["b:1"])
        items = [k1_1, k2_blog]
        self._record(k1_1)

        selection = select_unpublished_threads_item(items, self.history)

        self.assertIsNone(selection)

    # 회귀 테스트: KNOWLEDGE 4개, 각 2개의 Threads 후보 -> 연속 4회는 서로 다른
    # knowledge_id(K1->K2->K3->K4)가 선택되고, 5번째는 다시 K1의 다음 후보로 돌아온다.
    def test_four_knowledge_records_rotate_before_repeating(self):
        knowledge_ids = ["K1", "K2", "K3", "K4"]
        items = [
            _threads_item(knowledge_id=k, evidence_unit_ids=[f"{k}:{slot}"])
            for k in knowledge_ids
            for slot in (1, 2)
        ]
        # items 순서: K1-1, K1-2, K2-1, K2-2, K3-1, K3-2, K4-1, K4-2 (생성 순서 그대로)

        selected_knowledge_ids = []
        for _ in range(4):
            selection = select_unpublished_threads_item(items, self.history)
            self.assertIsNotNone(selection)
            item, content_id = selection
            selected_knowledge_ids.append(item["knowledge_id"])
            self._record(item)

        self.assertEqual(selected_knowledge_ids, ["K1", "K2", "K3", "K4"])

        # 5번째 선택 - 모든 KNOWLEDGE가 이미 한 번씩 등장했으므로, 생성 순서상 가장
        # 앞선 미게시 후보(K1의 두 번째 항목)로 되돌아간다.
        fifth = select_unpublished_threads_item(items, self.history)
        self.assertIsNotNone(fifth)
        self.assertEqual(fifth[0]["knowledge_id"], "K1")
        self.assertEqual(fifth[0]["evidence_unit_ids"], ["K1:2"])


if __name__ == "__main__":
    unittest.main()

"""content_engine.blog_publish_pack 검증.

TAK AUTO는 네이버 블로그에 자동 게시하지 않는다. 이 테스트는 Blog Publishing Pack
생성·선정·Markdown 렌더링 로직만 검증하며, 실제 네이버/LLM/Threads API는 호출하지 않는다.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import json
import tempfile
import unittest
from unittest import mock

from content_engine.blog_publish_pack import (
    DEFAULT_MAX_CANDIDATES,
    BlogPublishItem,
    build_blog_publish_pack,
    is_review_required,
    render_markdown,
    save_markdown,
    select_blog_publish_candidates,
    suggest_category,
)
from content_engine.models import ContentDraft
from content_engine.pipeline import run_media_batch
from content_engine.publish_history import PublishHistory, PublishRecord, compute_content_id
from content_engine.rewrite import MockRewriteProvider, RewriteProvider, RewriteRequest
from scripts.generate_blog_publish_pack import main as generate_blog_publish_pack_main
from tak_brain import KnowledgeRecord, load_knowledge_records


KNOWLEDGE_PATH = Path(__file__).parents[1] / "data" / "tak_brain_knowledge.json"


class BlogPublishPackFixtureMixin:
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.history_path = Path(self.tmp_dir.name) / "blog_publish_log.json"
        self.history = PublishHistory(self.history_path)

        records = load_knowledge_records(KNOWLEDGE_PATH)
        self.approved_records = tuple(r for r in records if r.knowledge_review_status == "approved")
        self.finance_records = tuple(r for r in self.approved_records if r.article_type == "finance")
        self.non_finance_records = tuple(r for r in self.approved_records if r.article_type != "finance")


class BuildBlogPublishPackTests(BlogPublishPackFixtureMixin, unittest.TestCase):
    # --- 1. Blog Publishing Pack 생성 ---------------------------------------------

    def test_build_pack_generates_items_from_approved_knowledge(self):
        report = run_media_batch(self.approved_records, provider=MockRewriteProvider())

        items = build_blog_publish_pack(report, self.approved_records, self.history)

        self.assertGreater(len(items), 0)
        for item in items:
            self.assertIsInstance(item, BlogPublishItem)
            self.assertTrue(item.title)
            self.assertTrue(item.body)
            self.assertTrue(item.content_id.startswith("content-"))
            self.assertTrue(item.knowledge_id)
            self.assertTrue(item.source_url)
            self.assertGreaterEqual(item.sequence, 1)

    def test_pack_sequence_numbers_are_1_indexed_and_ordered(self):
        report = run_media_batch(self.approved_records, provider=MockRewriteProvider())

        items = build_blog_publish_pack(report, self.approved_records, self.history)

        self.assertEqual([item.sequence for item in items], list(range(1, len(items) + 1)))

    # --- 2. 최대 5개(또는 지정값) 제한 -----------------------------------------------

    def test_default_max_candidates_is_five(self):
        self.assertEqual(DEFAULT_MAX_CANDIDATES, 5)

    def test_pack_never_exceeds_default_max_count(self):
        report = run_media_batch(self.approved_records, provider=MockRewriteProvider())

        items = build_blog_publish_pack(report, self.approved_records, self.history)

        self.assertLessEqual(len(items), DEFAULT_MAX_CANDIDATES)

    def test_pack_respects_custom_max_count(self):
        report = run_media_batch(self.approved_records, provider=MockRewriteProvider())

        items = build_blog_publish_pack(report, self.approved_records, self.history, max_count=1)

        self.assertLessEqual(len(items), 1)

    # --- 3. 서로 다른 KNOWLEDGE 우선 선택 --------------------------------------------

    def test_selection_prefers_distinct_knowledge_ids_first(self):
        base = self.approved_records[0]
        # 같은 KNOWLEDGE의 Blog 항목 2개(같은 knowledge_id, 다른 platform-neutral 필드는 없음)와
        # 서로 다른 KNOWLEDGE의 Blog 항목 1개를 인위적으로 구성해 선정 순서를 검증한다.
        item_same_a = {
            "knowledge_id": "k-same",
            "platform": "blog",
            "status": "valid",
            "source_url": "https://example.test/a",
            "original_title": "제목A",
            "original_body": "본문A",
            "rewritten_title": "제목A",
            "rewritten_body": "본문A",
            "evidence_unit_ids": ["lesson:1"],
        }
        item_same_b = {
            "knowledge_id": "k-same",
            "platform": "blog",
            "status": "valid",
            "source_url": "https://example.test/a",
            "original_title": "제목B",
            "original_body": "본문B",
            "rewritten_title": "제목B",
            "rewritten_body": "본문B",
            "evidence_unit_ids": ["lesson:2"],
        }
        item_other = {
            "knowledge_id": "k-other",
            "platform": "blog",
            "status": "valid",
            "source_url": "https://example.test/b",
            "original_title": "제목C",
            "original_body": "본문C",
            "rewritten_title": "제목C",
            "rewritten_body": "본문C",
            "evidence_unit_ids": ["lesson:1"],
        }
        # 입력 순서상 같은 KNOWLEDGE(k-same) 항목 2개가 먼저 나오지만, 서로 다른 KNOWLEDGE를
        # 우선하므로 k-other가 두 번째로 선택되어야 한다(첫 번째는 k-same의 첫 항목).
        selection = select_blog_publish_candidates(
            [item_same_a, item_same_b, item_other], self.history, max_count=2
        )

        selected_knowledge_ids = [item["knowledge_id"] for item, _ in selection]
        self.assertEqual(selected_knowledge_ids, ["k-same", "k-other"])

    # --- 4. 중복 Blog content_id 방지 ------------------------------------------------

    def test_already_published_content_id_is_excluded(self):
        report = run_media_batch(self.approved_records, provider=MockRewriteProvider())
        blog_items = [
            item.to_dict() for item in report.items if item.platform == "blog" and item.status == "valid"
        ]
        self.assertGreater(len(blog_items), 0)
        first_content_id = compute_content_id(blog_items[0])
        self.history.append(
            PublishRecord(
                content_id=first_content_id,
                published_at="2026-09-14T00:00:00+00:00",
                threads_post_id="manual",
                knowledge_id=str(blog_items[0].get("knowledge_id")),
                platform="blog",
                source_url=str(blog_items[0].get("source_url")),
            )
        )

        items = build_blog_publish_pack(report, self.approved_records, self.history)

        self.assertNotIn(first_content_id, [item.content_id for item in items])

    def test_all_blog_items_already_published_yields_empty_pack(self):
        report = run_media_batch(self.approved_records, provider=MockRewriteProvider())
        blog_items = [
            item.to_dict() for item in report.items if item.platform == "blog" and item.status == "valid"
        ]
        for item in blog_items:
            self.history.append(
                PublishRecord(
                    content_id=compute_content_id(item),
                    published_at="t",
                    threads_post_id="manual",
                )
            )

        items = build_blog_publish_pack(report, self.approved_records, self.history)

        self.assertEqual(items, ())

    # --- 5 / 6. finance/일반 콘텐츠의 review_required ---------------------------------

    def test_finance_knowledge_requires_human_review(self):
        self.assertGreater(len(self.finance_records), 0, "픽스처에 finance KNOWLEDGE가 없습니다.")
        record = self.finance_records[0]

        self.assertTrue(is_review_required(record))
        self.assertEqual(suggest_category(record), "금융/재테크")

    def test_non_finance_knowledge_does_not_require_review(self):
        self.assertGreater(len(self.non_finance_records), 0)
        for record in self.non_finance_records:
            self.assertFalse(is_review_required(record))

    def test_missing_knowledge_defaults_to_review_required_true(self):
        # knowledge를 찾을 수 없는 예외적 상황에서는 안전한 쪽(True)으로 기본값을 둔다.
        self.assertTrue(is_review_required(None))

    def test_pack_marks_finance_items_review_required(self):
        report = run_media_batch(self.approved_records, provider=MockRewriteProvider())

        items = build_blog_publish_pack(report, self.approved_records, self.history)

        finance_knowledge_ids = {record.id for record in self.finance_records}
        for item in items:
            if item.knowledge_id in finance_knowledge_ids:
                self.assertTrue(item.review_required)
            else:
                self.assertFalse(item.review_required)


class RenderMarkdownTests(BlogPublishPackFixtureMixin, unittest.TestCase):
    # --- 7. Markdown 출력 형식 ------------------------------------------------------

    def _sample_item(self, **overrides) -> BlogPublishItem:
        base = BlogPublishItem(
            sequence=1,
            title="샘플 제목",
            body="샘플 본문입니다.",
            category="일상/자기계발",
            keywords=("샘플", "키워드"),
            hashtags=("#샘플", "#키워드"),
            image_ideas=("대표 이미지: 예시",),
            knowledge_id="knowledge-sample",
            source_url="https://example.test/sample",
            review_required=False,
            content_id="content-sample1234",
        )
        return replace(base, **overrides)

    def test_markdown_contains_required_sections(self):
        markdown = render_markdown([self._sample_item()], generated_at="2026-09-14T00:00:00+00:00")

        for expected in (
            "[1번 글]",
            "카테고리: 일상/자기계발",
            "제목: 샘플 제목",
            "본문:",
            "샘플 본문입니다.",
            "핵심 키워드:",
            "해시태그:",
            "이미지 권장:",
            "검토:",
            "일반 콘텐츠",
            "금융/부동산/대출",
            "원본:",
            "knowledge-sample",
            "source_url: https://example.test/sample",
        ):
            self.assertIn(expected, markdown)

    def test_markdown_marks_review_required_checkbox(self):
        markdown = render_markdown([self._sample_item(review_required=True)])

        # 금융/부동산/대출 체크박스가 체크(☑)되고, 일반 콘텐츠는 체크되지 않아야 한다(□).
        # 안내 문구(헤더)에도 "금융/부동산/대출" 문자열이 등장하므로, 체크박스로 시작하는
        # 실제 검토 항목 줄만 골라서 비교한다.
        checkbox_lines = [
            line.strip() for line in markdown.splitlines()
            if line.strip().startswith(("☑", "□"))
        ]
        general_line = next(line for line in checkbox_lines if "일반 콘텐츠" in line)
        finance_line = next(line for line in checkbox_lines if "금융/부동산/대출" in line)
        self.assertTrue(general_line.startswith("□"))
        self.assertTrue(finance_line.startswith("☑"))

    def test_markdown_does_not_promise_search_ranking(self):
        markdown = render_markdown([self._sample_item()])
        self.assertIn("보장하지 않습니다", markdown)

    def test_empty_pack_renders_no_candidate_message(self):
        markdown = render_markdown([])
        self.assertIn("후보가 없습니다", markdown)

    def test_save_markdown_writes_file(self):
        target = Path(self.tmp_dir.name) / "pack.md"
        save_markdown([self._sample_item()], target)

        self.assertTrue(target.exists())
        self.assertIn("샘플 제목", target.read_text(encoding="utf-8"))


class MarkBlogPublishedScriptTests(unittest.TestCase):
    """scripts/mark_blog_published.py의 최소 동작 검증."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.history_path = Path(self.tmp_dir.name) / "blog_publish_log.json"

    def test_marks_content_as_published(self):
        from scripts.mark_blog_published import main

        exit_code = main(
            [
                "--content-id", "content-manualtest1",
                "--knowledge-id", "knowledge-x",
                "--source-url", "https://example.test/x",
                "--history", str(self.history_path),
            ]
        )

        self.assertEqual(exit_code, 0)
        history = PublishHistory(self.history_path)
        self.assertTrue(history.is_published("content-manualtest1"))

    def test_marking_twice_is_idempotent(self):
        from scripts.mark_blog_published import main

        args = ["--content-id", "content-dup1", "--history", str(self.history_path)]
        first_exit = main(args)
        second_exit = main(args)

        self.assertEqual(first_exit, 0)
        self.assertEqual(second_exit, 0)
        history = PublishHistory(self.history_path)
        self.assertEqual(len(history.load()), 1)


class _CountingRewriteProvider(RewriteProvider):
    """실제 네트워크를 쓰지 않는 Fake provider. 호출 횟수만 센다(test_media_batch.py의
    CrashingProvider/PartiallyFailingProvider와 동일한 패턴)."""

    def __init__(self) -> None:
        self.call_count = 0

    def rewrite(self, request: RewriteRequest) -> ContentDraft:
        self.call_count += 1
        return request.draft


class GenerateBlogPublishPackIdFilterTests(unittest.TestCase):
    """5-10 Phase 4-2 수정 #3: scripts/generate_blog_publish_pack.py --id 필터.

    실제 LLM API는 절대 호출하지 않는다 - OpenAICompatibleRewriteProvider.from_environment()를
    호출 횟수만 세는 Fake provider로 교체하고, 그 외 run_media_batch/build_blog_publish_pack 등
    나머지 실제 로직은 그대로 실행한다(네트워크 계층만 차단).
    """

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.tmp_path = Path(self.tmp_dir.name)

        records = load_knowledge_records(KNOWLEDGE_PATH)
        approved = [r for r in records if r.knowledge_review_status == "approved"]
        self.assertGreaterEqual(len(approved), 2, "테스트에는 승인 KNOWLEDGE가 최소 2건 필요합니다.")
        self.record_a, self.record_b = approved[0], approved[1]

        self.knowledge_path = self.tmp_path / "knowledge.json"
        self.knowledge_path.write_text(
            json.dumps([self.record_a.to_dict(), self.record_b.to_dict()], ensure_ascii=False),
            encoding="utf-8",
        )

    def _run(self, extra_args: list[str]) -> tuple[int, Path, _CountingRewriteProvider]:
        output = self.tmp_path / "media_batch.json"
        history = self.tmp_path / "history.json"
        pack = self.tmp_path / "pack.md"
        archive = self.tmp_path / "media_archive.json"
        provider = _CountingRewriteProvider()
        with mock.patch(
            "scripts.generate_blog_publish_pack.OpenAICompatibleRewriteProvider.from_environment",
            return_value=provider,
        ):
            exit_code = generate_blog_publish_pack_main(
                [
                    "--knowledge", str(self.knowledge_path),
                    "--output", str(output),
                    "--history", str(history),
                    "--pack-output", str(pack),
                    "--archive", str(archive),
                    *extra_args,
                ]
            )
        return exit_code, output, provider

    # 1. --id 없음 -> 기존 동작(승인된 전체 KNOWLEDGE 처리)
    def test_without_id_processes_all_approved_knowledge(self):
        exit_code, output, provider = self._run([])

        self.assertEqual(exit_code, 0)
        data = json.loads(output.read_text(encoding="utf-8"))
        knowledge_ids = {item["knowledge_id"] for item in data["all_items"]}
        self.assertEqual(knowledge_ids, {self.record_a.id, self.record_b.id})
        self.assertEqual(provider.call_count, 18)  # 2건 x 9 draft

    # 2, 3, 5. --id 있음 -> 정확히 1개 KNOWLEDGE만 처리, 다른 KNOWLEDGE는 대상이 아님,
    # 호출 횟수(9회)가 처리 대상 수(1건 x 9 draft)와 일치
    def test_id_processes_only_that_knowledge(self):
        exit_code, output, provider = self._run(["--id", self.record_a.id])

        self.assertEqual(exit_code, 0)
        data = json.loads(output.read_text(encoding="utf-8"))
        knowledge_ids = {item["knowledge_id"] for item in data["all_items"]}
        self.assertEqual(knowledge_ids, {self.record_a.id})
        self.assertNotIn(self.record_b.id, knowledge_ids)
        self.assertEqual(provider.call_count, 9)

    # 4. 존재하지 않는 ID -> 안전하게 종료(오류 코드, LLM 호출 없음, 결과 파일 없음)
    def test_unknown_id_exits_safely_without_calling_llm(self):
        exit_code, output, provider = self._run(["--id", "knowledge-does-not-exist"])

        self.assertEqual(exit_code, 1)
        self.assertFalse(output.exists())
        self.assertEqual(provider.call_count, 0)


if __name__ == "__main__":
    unittest.main()

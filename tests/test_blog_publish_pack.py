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
    build_blog_publish_pack_from_archive,
    is_review_required,
    render_markdown,
    save_markdown,
    select_approved_blog_candidates_from_archive,
    select_blog_publish_candidates,
    suggest_category,
)
from content_engine.media_archive import MediaArchiveRecord
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
        # is_review_required()는 article_type == "finance"뿐 아니라 category/domain의
        # 금융 관련 키워드로도 True가 된다(6-05: knowledge-scout-b28b782b2a33처럼
        # article_type은 null로 정정됐지만 category="금융"은 그대로인 레코드가 존재).
        # 이 fixture는 실제 안전 판단 함수와 동일한 기준으로 분류해야 두 그룹이
        # is_review_required()의 실제 동작과 어긋나지 않는다.
        self.finance_records = tuple(r for r in self.approved_records if is_review_required(r))
        self.non_finance_records = tuple(r for r in self.approved_records if not is_review_required(r))


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


def _archive_record(**overrides) -> MediaArchiveRecord:
    fields = {
        "content_id": "content-blog-archive-1",
        "knowledge_id": "knowledge-blog-archive-1",
        "platform": "blog",
        "generation_status": "valid",
        "original_title": "원본 제목",
        "original_body": "원본 본문",
        "rewritten_title": "AI 재작성 제목",
        "rewritten_body": "AI가 재작성한 본문입니다.",
        "source_url": "https://blog.example.test/original-post",
        "evidence": ("SOURCE FACT: 예시",),
        "evidence_unit_ids": ("lesson:1",),
        "created_at": "2026-09-19T00:00:00+00:00",
        "validation_errors": (),
        "error_message": None,
        "review_status": "approved",
    }
    fields.update(overrides)
    return MediaArchiveRecord(**fields)


def _knowledge_record(**overrides) -> KnowledgeRecord:
    fields = {
        "id": "knowledge-blog-archive-1",
        "source_url": "https://blog.example.test/original-post",
        "title": "원문 기사 제목",
        "article_type": "experience",
        "domain": "자기계발",
        "knowledge_type": "경험",
        "knowledge_review_status": "approved",
    }
    fields.update(overrides)
    return KnowledgeRecord(**fields)


class BlogPublishPackFromArchiveTests(unittest.TestCase):
    """5-29: MEDIA archive에서 승인된 Blog만 Publishing Pack 후보로 연결(N),
    중복 생성 방지(Q)를 검증한다. 기존 build_blog_publish_pack()/
    select_blog_publish_candidates()는 여기서 전혀 쓰지 않는다 - 완전히 별도인
    build_blog_publish_pack_from_archive() 경로만 검증한다.
    """

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.history_path = Path(self.tmp_dir.name) / "blog_publish_log.json"
        self.history = PublishHistory(self.history_path)

    # --- N. 승인된 Blog만 Publishing Pack 후보로 연결되는가 -------------------------

    def test_only_approved_blog_records_become_candidates(self):
        records = [
            _archive_record(content_id="c-approved", knowledge_id="k1", review_status="approved"),
            _archive_record(content_id="c-unreviewed", knowledge_id="k2", review_status="unreviewed"),
            _archive_record(content_id="c-dismissed", knowledge_id="k3", review_status="dismissed"),
        ]
        candidates = select_approved_blog_candidates_from_archive(records, self.history)
        self.assertEqual([c.content_id for c in candidates], ["c-approved"])

    def test_only_valid_generation_status_becomes_candidate_even_if_approved(self):
        # generation_status가 rejected/error인데 review_status만 approved인 것은
        # (정상적으로는 승인 버튼 자체가 안 보이므로 발생하지 않지만) 방어적으로도
        # 후보에서 제외되어야 한다.
        records = [
            _archive_record(content_id="c-rejected", knowledge_id="k1", generation_status="rejected"),
        ]
        candidates = select_approved_blog_candidates_from_archive(records, self.history)
        self.assertEqual(candidates, [])

    def test_only_blog_platform_becomes_candidate(self):
        records = [
            _archive_record(content_id="c-threads", knowledge_id="k1", platform="threads"),
            _archive_record(content_id="c-shorts", knowledge_id="k2", platform="shorts"),
        ]
        candidates = select_approved_blog_candidates_from_archive(records, self.history)
        self.assertEqual(candidates, [])

    def test_build_pack_from_archive_uses_final_title_and_body(self):
        records = [_archive_record(edited_title="사람이 고친 제목", edited_body="사람이 고친 본문")]
        knowledge = [_knowledge_record()]

        items = build_blog_publish_pack_from_archive(records, knowledge, self.history)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "사람이 고친 제목")
        self.assertEqual(items[0].body, "사람이 고친 본문")

    def test_build_pack_from_archive_uses_generated_content_when_not_edited(self):
        records = [_archive_record()]
        knowledge = [_knowledge_record()]

        items = build_blog_publish_pack_from_archive(records, knowledge, self.history)

        self.assertEqual(items[0].title, "AI 재작성 제목")
        self.assertEqual(items[0].body, "AI가 재작성한 본문입니다.")

    def test_build_pack_from_archive_preserves_review_required_safety_rule(self):
        """기존 is_review_required()의 금융 안전장치가 archive 경로에서도 그대로
        적용되는지 - 새로 판단 로직을 만들지 않았다는 증거."""
        records = [_archive_record()]
        finance_knowledge = [_knowledge_record(article_type="finance")]

        items = build_blog_publish_pack_from_archive(records, finance_knowledge, self.history)

        self.assertTrue(items[0].review_required)

    # --- Q. 동일 content_id 중복 생성 방지(승인 -> Pack 생성 -> 다시 승인 -> 다시 생성) --

    def test_repeated_pack_generation_does_not_duplicate_unpublished_candidate(self):
        """아직 실제로 게시(mark_blog_published)하지 않았다면, 같은 승인 항목을 Pack을
        여러 번 생성해도 매번 동일한 후보 1건만 나온다(누적되지 않는다) - Pack 자체가
        상태를 갖지 않는 순수 함수이므로 자연히 성립하지만, 이 성질을 명시적으로
        고정한다."""
        records = [_archive_record()]
        knowledge = [_knowledge_record()]

        first_items = build_blog_publish_pack_from_archive(records, knowledge, self.history)
        second_items = build_blog_publish_pack_from_archive(records, knowledge, self.history)

        self.assertEqual(len(first_items), 1)
        self.assertEqual(len(second_items), 1)
        self.assertEqual(first_items[0].content_id, second_items[0].content_id)

    def test_candidate_excluded_after_marked_published(self):
        """실제로 게시된 뒤(PublishHistory에 기록됨)에는 같은 content_id가 더 이상
        후보로 나오지 않는다 - Threads/기존 Blog 경로와 동일한 중복 방지 규칙."""
        records = [_archive_record()]
        self.history.append(
            PublishRecord(
                content_id="content-blog-archive-1",
                published_at="2026-09-19T01:00:00+00:00",
                threads_post_id="",
                knowledge_id="knowledge-blog-archive-1",
                platform="blog",
                source_url="https://blog.example.test/original-post",
            )
        )

        candidates = select_approved_blog_candidates_from_archive(records, self.history)
        self.assertEqual(candidates, [])

    def test_max_count_and_distinct_knowledge_priority_preserved(self):
        """기존 select_blog_publish_candidates()의 선정 규칙(서로 다른 KNOWLEDGE
        우선, max_count 제한)이 archive 경로에서도 동일하게 적용되는지."""
        records = [
            _archive_record(content_id="c1", knowledge_id="k1"),
            _archive_record(content_id="c2", knowledge_id="k1"),  # 같은 KNOWLEDGE 2번째 -> 후순위
            _archive_record(content_id="c3", knowledge_id="k2"),
        ]
        candidates = select_approved_blog_candidates_from_archive(records, self.history, max_count=2)

        self.assertEqual(len(candidates), 2)
        self.assertEqual({c.content_id for c in candidates}, {"c1", "c3"})  # c2(같은 KNOWLEDGE)는 밀림


class GenerateBlogPublishPackFromArchiveCliTests(unittest.TestCase):
    """scripts/generate_blog_publish_pack.py --from-archive 모드 검증. 이 모드는
    LLM을 전혀 호출하지 않는다(run_media_batch/OpenAICompatibleRewriteProvider를
    거치지 않는 완전히 다른 코드 경로이므로, provider mock조차 필요 없다)."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.tmp_path = Path(self.tmp_dir.name)

        self.knowledge_path = self.tmp_path / "knowledge.json"
        self.knowledge_path.write_text(
            json.dumps([_knowledge_record().to_dict()], ensure_ascii=False), encoding="utf-8"
        )

        self.archive_path = self.tmp_path / "archive.json"
        self.history_path = self.tmp_path / "history.json"
        self.pack_output = self.tmp_path / "pack.md"

    def _seed_archive(self, *records: MediaArchiveRecord) -> None:
        from content_engine.media_archive import upsert_archive

        upsert_archive(self.archive_path, list(records))

    def _run(self, extra_args: list[str] | None = None) -> int:
        args = [
            "--knowledge", str(self.knowledge_path),
            "--archive", str(self.archive_path),
            "--history", str(self.history_path),
            "--pack-output", str(self.pack_output),
            "--from-archive",
        ]
        if extra_args:
            args.extend(extra_args)
        return generate_blog_publish_pack_main(args)

    def test_from_archive_builds_pack_without_calling_llm(self):
        self._seed_archive(_archive_record())

        with mock.patch(
            "scripts.generate_blog_publish_pack.OpenAICompatibleRewriteProvider.from_environment"
        ) as mocked_from_env:
            exit_code = self._run()

        self.assertEqual(exit_code, 0)
        mocked_from_env.assert_not_called()

        markdown = self.pack_output.read_text(encoding="utf-8")
        self.assertIn("AI 재작성 제목", markdown)

    def test_from_archive_ignores_unapproved_records(self):
        self._seed_archive(_archive_record(review_status="unreviewed"))

        exit_code = self._run()

        self.assertEqual(exit_code, 0)
        markdown = self.pack_output.read_text(encoding="utf-8")
        self.assertNotIn("AI 재작성 제목", markdown)

    def test_from_archive_warns_when_limit_is_ignored(self):
        import contextlib
        import io

        self._seed_archive(_archive_record())

        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            exit_code = self._run(["--limit", "2"])

        self.assertEqual(exit_code, 0)
        self.assertIn("--limit이 사용되지 않습니다", captured.getvalue())


if __name__ == "__main__":
    unittest.main()

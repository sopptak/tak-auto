"""6-27 Blog Publish Readiness 통합 테스트(docs/6-27-blog-publish-readiness.md
16장 Synthetic E2E). 개별 단위 테스트는 tests/test_blog_publish_pack.py가 이미
담당한다 - 이 파일은 여러 모듈에 걸친 시나리오(Pack 생성 → supersede →
mark_blog_published 차단)와, 아직 다른 파일이 다루지 않는 나머지 시나리오만
다룬다. 실제 Naver API/브라우저 자동화는 이 코드베이스 어디에도 없으므로
호출할 것 자체가 없다(17장에서 이를 소스 레벨로 재확인한다).
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from content_engine.blog_publish_pack import (
    build_blog_publish_pack_from_archive,
    select_approved_blog_candidates_from_archive,
)
from content_engine.media_archive import MediaArchiveRecord, save_archive
from content_engine.publish_history import PublishHistory
from scripts.mark_blog_published import main as mark_blog_published_main


def _record(**overrides) -> MediaArchiveRecord:
    defaults = dict(
        content_id="c1",
        knowledge_id="k1",
        platform="blog",
        generation_status="valid",
        original_title="원본 제목",
        original_body="원본 본문입니다.",
        rewritten_title="재작성 제목",
        rewritten_body="재작성 본문입니다.",
        source_url="https://example.test/1",
        evidence=(),
        evidence_unit_ids=(),
        created_at="2026-01-01T00:00:00Z",
        review_status="approved",
    )
    defaults.update(overrides)
    return MediaArchiveRecord(**defaults)


class PackToMarkPublishedSupersedeScenarioTests(unittest.TestCase):
    """시나리오 12: Pack 생성 시점에는 READY였던 항목이, 사람이 실제로 게시하기
    전에 supersede되면 mark_blog_published.py(최종 기록 단계)가 이를 차단하는지
    확인한다 - Blog에는 "발행 직전 API 재검증"을 넣을 지점이 없으므로(사람이
    직접 게시하기 때문), 자동화가 개입할 수 있는 마지막 지점인
    mark_blog_published.py가 이 역할을 겸한다(docs/6-27-blog-publish-readiness.md
    8장/12장)."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.tmp_path = Path(self.tmp_dir.name)
        self.archive_path = self.tmp_path / "tak_media_archive.json"
        self.blog_history_path = self.tmp_path / "blog_publish_log.json"

    def test_pack_built_then_superseded_then_mark_published_is_blocked(self) -> None:
        # 시점 A: Pack 생성 - 이 시점에는 approved라 정상 후보다.
        record = _record(content_id="c1", review_status="approved")
        save_archive([record], self.archive_path)
        history = PublishHistory(self.blog_history_path)
        candidates = select_approved_blog_candidates_from_archive([record], history)
        self.assertEqual([c.content_id for c in candidates], ["c1"])

        pack = build_blog_publish_pack_from_archive([record], [], history)
        self.assertEqual(len(pack), 1)
        self.assertIn("content_id: c1", "\n".join(f"content_id: {item.content_id}" for item in pack))

        # 시점 B: 사람이 아직 게시하지 않은 사이, 정정본(c2)이 나와 c1이 supersede된다.
        superseded = replace(record, review_status="superseded", superseded_by="c2")
        new_record = _record(content_id="c2", review_status="approved")
        save_archive([superseded, new_record], self.archive_path)

        # 시점 C: 사람이 (이미 손에 들고 있던 stale pack을 보고) 게시했다고
        # 신고하며 mark_blog_published를 실행한다 - 차단되어야 한다.
        exit_code = mark_blog_published_main(
            [
                "--content-id", "c1",
                "--history", str(self.blog_history_path),
                "--production-archive", str(self.archive_path),
            ]
        )
        self.assertEqual(exit_code, 1)
        self.assertFalse(PublishHistory(self.blog_history_path).is_published("c1"))

        # 정정본(c2)은 정상적으로 기록 가능해야 한다(대체품 자체는 막히지 않음).
        exit_code_new = mark_blog_published_main(
            [
                "--content-id", "c2",
                "--history", str(self.blog_history_path),
                "--production-archive", str(self.archive_path),
            ]
        )
        self.assertEqual(exit_code_new, 0)
        self.assertTrue(PublishHistory(self.blog_history_path).is_published("c2"))


class PackRegenerationIdempotencyTests(unittest.TestCase):
    """시나리오 20: Pack을 다시 생성해도(기존 파일을 덮어써도) 아직 게시되지
    않은 후보가 사라지지 않는다 - 선정 로직이 PublishHistory 기준으로만
    제외하므로, "덮어쓰기"가 실제로 데이터를 잃어버리는 것은 아니다(휘발성
    설계가 안전한 이유)."""

    def test_regenerating_pack_without_marking_published_keeps_same_candidate(self) -> None:
        record = _record(content_id="c1", review_status="approved")
        history = PublishHistory(Path(tempfile.mkdtemp()) / "blog_publish_log.json")

        first_pack = build_blog_publish_pack_from_archive([record], [], history)
        second_pack = build_blog_publish_pack_from_archive([record], [], history)

        self.assertEqual([i.content_id for i in first_pack], [i.content_id for i in second_pack])

    def test_after_marking_published_regeneration_excludes_it(self) -> None:
        record = _record(content_id="c1", review_status="approved")
        archive_path = Path(tempfile.mkdtemp()) / "tak_media_archive.json"
        save_archive([record], archive_path)
        history_path = Path(tempfile.mkdtemp()) / "blog_publish_log.json"
        history = PublishHistory(history_path)

        first_pack = build_blog_publish_pack_from_archive([record], [], history)
        self.assertEqual(len(first_pack), 1)

        exit_code = mark_blog_published_main(
            [
                "--content-id", "c1",
                "--history", str(history_path),
                "--production-archive", str(archive_path),
            ]
        )
        self.assertEqual(exit_code, 0)

        second_pack = build_blog_publish_pack_from_archive([record], [], PublishHistory(history_path))
        self.assertEqual(second_pack, ())


class MarkBlogPublishedHistoryWriteFailureTests(unittest.TestCase):
    """시나리오 18: history 기록 자체가 실패하면(디스크 오류 등) "기록 완료"를
    출력하지 않고 오류로 종료해야 한다 - 성공하지도 않았는데 성공 메시지가
    나오면 안 된다."""

    def test_history_append_failure_does_not_report_success(self) -> None:
        tmp_dir = tempfile.mkdtemp()
        archive_path = Path(tmp_dir) / "tak_media_archive.json"
        save_archive([_record(content_id="c1", review_status="approved")], archive_path)
        history_path = Path(tmp_dir) / "blog_publish_log.json"

        with mock.patch.object(PublishHistory, "append", side_effect=OSError("disk full (simulated)")):
            exit_code = mark_blog_published_main(
                [
                    "--content-id", "c1",
                    "--history", str(history_path),
                    "--production-archive", str(archive_path),
                ]
            )

        self.assertEqual(exit_code, 1)
        self.assertFalse(PublishHistory(history_path).is_published("c1"))


class NoExternalNaverAutomationTests(unittest.TestCase):
    """시나리오 19 / 17장: 이 코드베이스에는 Naver 자동 게시/브라우저 자동화/
    비공식 API 호출 코드가 전혀 없다는 것을 소스 레벨로 재확인한다(새로
    만들지 않았다는 것의 회귀 보증)."""

    def test_blog_modules_never_reference_browser_or_naver_login_automation(self) -> None:
        import content_engine.blog_publish_pack as blog_pack_module
        import scripts.generate_blog_publish_pack as generate_pack_module
        import scripts.mark_blog_published as mark_published_module

        forbidden = ["selenium", "playwright", "webdriver", "requests.post", "urlopen", "webbrowser", "cookie"]
        for module in (blog_pack_module, mark_published_module, generate_pack_module):
            source = Path(module.__file__).read_text(encoding="utf-8")
            for needle in forbidden:
                self.assertNotIn(needle, source.lower(), f"{module.__file__}에 '{needle}'가 있습니다.")


if __name__ == "__main__":
    unittest.main()

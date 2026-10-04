from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from content_engine.marketing import EvidenceItem, append_briefs, load_briefs
from scripts import marketing_brief as cli
from tests.test_marketing_generation import approved_brief, knowledge


def research(aspect, snippet, url):
    return EvidenceItem(kind="research", title=aspect, url=url, snippet=snippet, provider="perplexity", aspect=aspect)


class MarketingCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name)
        self.briefs = self.data / "tak_marketing_briefs.json"
        self.contents = self.data / "tak_marketing_contents.json"
        self.suggestions = self.data / "tak_marketing_suggestions.json"
        (self.data / "tak_brain_knowledge.json").write_text(
            json.dumps([knowledge().to_dict()], ensure_ascii=False), encoding="utf-8")

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(["--data-dir", str(self.data), *args])
        return code, out.getvalue(), err.getvalue()

    def add(self, brief):
        append_briefs(self.briefs, [brief])
        return brief

    def stored(self, brief_id):
        return next(item for item in load_briefs(self.briefs) if item.brief_id == brief_id)

    def test_suggest_preview_then_write_and_accept(self):
        brief = self.add(replace(approved_brief("blog", status="draft"), psychology=replace(
            approved_brief().psychology, curiosity=""), evidence=(
            approved_brief().evidence[0], research("recurring_questions", "AI 보고서는 어떻게 자동화하나요", "https://q/1"))))
        code, out, _ = self.run_cli("suggest", brief.brief_id)
        self.assertEqual(code, 0)
        self.assertIn("psychology.curiosity", out)
        self.assertIn("미리보기", out)
        self.assertFalse(self.suggestions.exists())

        self.assertEqual(self.run_cli("--write", "suggest", brief.brief_id)[0], 0)
        rows = json.loads(self.suggestions.read_text(encoding="utf-8"))
        sug = next(row for row in rows if row["element"] == "curiosity")
        self.assertEqual(self.stored(brief.brief_id).psychology.curiosity, "")  # 아직 반영 안 됨

        code, out, _ = self.run_cli("review", brief.brief_id)
        self.assertIn(sug["suggestion_id"], out)
        self.assertIn("생성 차단", out)

        code, out, _ = self.run_cli("suggestion", "accept", sug["suggestion_id"])
        self.assertEqual(code, 0)
        self.assertIn("accepted", out)
        self.assertIn("AI 보고서", self.stored(brief.brief_id).psychology.curiosity)
        # 이미 처리된 제안은 다시 처리할 수 없다.
        self.assertEqual(self.run_cli("suggestion", "reject", sug["suggestion_id"])[0], 2)

    def test_suggestion_reject_leaves_brief(self):
        brief = self.add(replace(approved_brief("blog", status="draft"), psychology=replace(
            approved_brief().psychology, curiosity=""), evidence=(
            approved_brief().evidence[0], research("recurring_questions", "자주 묻는 질문", "https://q/2"))))
        self.run_cli("--write", "suggest", brief.brief_id)
        sug = json.loads(self.suggestions.read_text(encoding="utf-8"))[0]
        code, out, _ = self.run_cli("suggestion", "reject", sug["suggestion_id"])
        self.assertEqual(code, 0)
        self.assertIn("rejected", out)
        self.assertEqual(self.stored(brief.brief_id), brief)

    def test_set_approve_reject(self):
        brief = self.add(approved_brief("threads", status="draft"))
        code, out, _ = self.run_cli("set", brief.brief_id, "sales.offer", "사람이 다시 쓴 오퍼 문구입니다")
        self.assertEqual(code, 0)
        self.assertEqual(self.stored(brief.brief_id).sales.offer, "사람이 다시 쓴 오퍼 문구입니다")
        self.assertEqual(self.run_cli("set", brief.brief_id, "nope.x", "v")[0], 2)

        self.assertEqual(self.run_cli("approve", brief.brief_id)[0], 0)
        self.assertEqual(self.stored(brief.brief_id).status, "approved")
        # 승인 후 편집하면 draft로 돌아간다.
        self.run_cli("set", brief.brief_id, "sales.offer", "다시 수정한 오퍼 문구입니다")
        self.assertEqual(self.stored(brief.brief_id).status, "draft")

        self.assertEqual(self.run_cli("reject", brief.brief_id)[0], 0)
        self.assertEqual(self.stored(brief.brief_id).status, "rejected")
        code, _, err = self.run_cli("approve", brief.brief_id)
        self.assertEqual(code, 2)
        self.assertIn("되살릴 수 없습니다", err)

    def test_approve_blocked_when_not_ready(self):
        brief = self.add(approved_brief("blog", status="draft", evidence=()))
        code, _, err = self.run_cli("approve", brief.brief_id)
        self.assertEqual(code, 2)
        self.assertIn("승인 조건 미충족", err)
        self.assertEqual(self.stored(brief.brief_id).status, "draft")

    def test_generate_preview_does_not_write(self):
        brief = self.add(approved_brief("threads"))
        code, out, _ = self.run_cli("generate", brief.brief_id)
        self.assertEqual(code, 0)
        self.assertIn("후보 5건", out)
        self.assertIn("미리보기", out)
        self.assertFalse(self.contents.exists())
        self.assertEqual(self.stored(brief.brief_id).content_ids, ())

    def test_generate_write_saves_review_required_and_links(self):
        brief = self.add(approved_brief("youtube"))
        code, out, _ = self.run_cli("--write", "generate", brief.brief_id, "--rewrite", "mock")
        self.assertEqual(code, 0)
        rows = json.loads(self.contents.read_text(encoding="utf-8"))
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(row["status"] == "review_required" and row["shorts_script"] for row in rows))
        self.assertEqual(list(self.stored(brief.brief_id).content_ids), [row["content_id"] for row in rows])
        # 다시 실행해도 중복 저장/연결이 없다.
        self.run_cli("--write", "generate", brief.brief_id, "--rewrite", "mock")
        self.assertEqual(len(json.loads(self.contents.read_text(encoding="utf-8"))), 3)
        self.assertEqual(len(self.stored(brief.brief_id).content_ids), 3)

    def test_generate_blocked_for_draft_brief(self):
        brief = self.add(approved_brief("blog", status="draft"))
        code, _, err = self.run_cli("--write", "generate", brief.brief_id)
        self.assertEqual(code, 2)
        self.assertIn("생성 차단", err)
        self.assertFalse(self.contents.exists())

    def test_generate_without_approved_knowledge(self):
        brief = self.add(approved_brief("blog", knowledge_ids=("missing",)))
        code, out, _ = self.run_cli("--write", "generate", brief.brief_id)
        self.assertEqual(code, 2)
        self.assertIn("approved KNOWLEDGE가 없습니다", out)
        self.assertFalse(self.contents.exists())

    def test_generate_llm_requires_environment_and_no_network_by_default(self):
        brief = self.add(approved_brief("blog"))
        with mock.patch.dict("os.environ", {}, clear=True), \
                mock.patch("urllib.request.urlopen", side_effect=AssertionError("network")) as urlopen:
            code, _, err = self.run_cli("generate", brief.brief_id, "--rewrite", "llm")
            self.assertEqual(self.run_cli("generate", brief.brief_id)[0], 0)
        self.assertEqual(code, 2)
        self.assertIn("TAK_MEDIA_LLM_API_KEY", err)
        urlopen.assert_not_called()


if __name__ == "__main__":
    unittest.main()

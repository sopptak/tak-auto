"""6-82 Marketing 데이터 보존 정책: Git 화이트리스트, audit/export 등록, 새 환경에서의 참조 유지."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from content_engine.market_demand import load_demands, load_ideas
from content_engine.marketing import load_briefs
import scripts.audit_data_state as audit_module
import scripts.export_operational_data as export_module
from scripts import market_demand as demand_cli
from scripts import marketing_brief as brief_cli

ROOT = Path(__file__).resolve().parents[1]
SOURCE_OF_TRUTH = (
    "data/tak_market_demands.json",
    "data/tak_idea_candidates.json",
    "data/tak_marketing_briefs.json",
    "data/tak_marketing_suggestions.json",
)
PRE_PROMOTION = ("data/tak_marketing_contents.json", "data/tak_media_generation_marketing-brief-x.json")


def _git_ignored(relative_path: str) -> bool | None:
    try:
        result = subprocess.run(["git", "check-ignore", "-q", relative_path], cwd=ROOT, check=False)
    except FileNotFoundError:
        return None
    if result.returncode not in (0, 1):
        return None
    return result.returncode == 0


def _quiet(fn, argv):
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        return fn(argv)


class GitPolicyTests(unittest.TestCase):
    def setUp(self):
        if _git_ignored("data/tak_marketing_contents.json") is None:
            self.skipTest("git 저장소가 아닙니다.")

    def test_source_of_truth_files_are_trackable(self):
        for path in SOURCE_OF_TRUTH:
            self.assertFalse(_git_ignored(path), path)

    def test_pre_promotion_candidates_stay_ignored(self):
        for path in PRE_PROMOTION:
            self.assertTrue(_git_ignored(path), path)


class AuditExportRegistrationTests(unittest.TestCase):
    def test_all_marketing_paths_registered_in_audit(self):
        specs = {spec.relative_path: spec.category for spec in audit_module.FILE_SPECS}
        for path in SOURCE_OF_TRUTH:
            self.assertTrue(specs[path].startswith("A:"), path)
        self.assertTrue(specs["data/tak_marketing_contents.json"].startswith("C/D:"))

    def test_export_discovers_marketing_paths_and_marketing_pool(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            (root / "data" / "tak_media_generation_marketing-brief-x.json").write_text("[]", encoding="utf-8")
            entries, _ = export_module.discover(root)
            paths = {entry.relative_path for entry in entries}
        for path in (*SOURCE_OF_TRUTH, *PRE_PROMOTION):
            self.assertIn(path, paths)


class FreshEnvironmentTests(unittest.TestCase):
    """작업 환경 A에서 만든 데이터 중 Git이 추적 가능한 파일만 새 환경 B로 옮겨도
    Market Demand -> Idea -> MarketingBrief 참조가 유지되는지 확인한다."""

    def setUp(self):
        if _git_ignored("data/tak_marketing_contents.json") is None:
            self.skipTest("git 저장소가 아닙니다.")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.env_a, self.env_b = base / "a" / "data", base / "b" / "data"
        self.env_a.mkdir(parents=True)
        self.env_b.mkdir(parents=True)
        rows = base / "demands.json"
        rows.write_text(json.dumps([
            {"source": "flippa", "title": "AI newsletter", "category": "newsletter", "price": 5000,
             "verified_transaction": "true", "competition_signal": 0.2, "demand_signal": 0.7, "url": "https://x/1"},
        ]), encoding="utf-8")
        self.assertEqual(_quiet(demand_cli.main, ["--input", str(rows), "--min-score", "30", "--data-dir",
                                                  str(self.env_a), "--write"]), 0)
        self.idea = load_ideas(self.env_a / "tak_idea_candidates.json")[0]
        self.assertEqual(_quiet(brief_cli.main, ["--data-dir", str(self.env_a), "--write", "draft",
                                                 self.idea.idea_id]), 0)
        # 승격 전 후보 파일(무시 대상)도 A에는 존재한다.
        (self.env_a / "tak_marketing_contents.json").write_text("[]", encoding="utf-8")

    def _fresh_checkout(self) -> list[str]:
        carried = []
        for path in sorted(self.env_a.iterdir()):
            if not _git_ignored(f"data/{path.name}"):
                shutil.copy2(path, self.env_b / path.name)
                carried.append(path.name)
        return carried

    def test_references_survive_fresh_checkout(self):
        carried = self._fresh_checkout()
        self.assertIn("tak_market_demands.json", carried)
        self.assertIn("tak_idea_candidates.json", carried)
        self.assertIn("tak_marketing_briefs.json", carried)
        self.assertNotIn("tak_marketing_contents.json", carried)

        demand_ids = {demand.demand_id for demand in load_demands(self.env_b / "tak_market_demands.json")}
        ideas = {idea.idea_id: idea for idea in load_ideas(self.env_b / "tak_idea_candidates.json")}
        self.assertTrue(set(ideas[self.idea.idea_id].demand_ids) <= demand_ids)
        brief = load_briefs(self.env_b / "tak_marketing_briefs.json")[0]
        self.assertIn(brief.idea_id, ideas)
        self.assertTrue(any(item.kind == "market_demand" for item in brief.evidence))
        # 새 환경에서도 draft(Market Demand -> Idea -> Brief)가 다시 동작한다.
        self.assertEqual(_quiet(brief_cli.main, ["--data-dir", str(self.env_b), "draft", self.idea.idea_id]), 0)

    def test_draft_fails_without_demands(self):
        """demands를 옮기지 않으면 draft가 실패한다 - 화이트리스트가 필요한 이유."""
        shutil.copy2(self.env_a / "tak_idea_candidates.json", self.env_b / "tak_idea_candidates.json")
        self.assertEqual(_quiet(brief_cli.main, ["--data-dir", str(self.env_b), "draft", self.idea.idea_id]), 2)


if __name__ == "__main__":
    unittest.main()

"""6-49 복구 후보 Shorts 5건 검토 판정의 근거를 고정한다(실제 Codespace export commit 기준).

판정 규칙(docs/6-49-operational-shorts-recovery-review.md 4장):
- 실존 인물/기업 발언을 인용하는데 원문이 로컬에 RSS 한 줄 요약뿐이면 FACT_CHECK_REQUIRED
- 인물 발언 인용이 없고, 문장이 KNOWLEDGE에 기록된 출처 사실과 일치하면 SAFE_TO_APPLY

export commit이 로컬 git에 없으면 skip한다. 네트워크/데이터 쓰기 없음.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from content_engine.media_archive import load_archive
from content_engine.shorts_script import ShortsScript

ROOT = Path(__file__).resolve().parents[1]
EXPORT_COMMIT = "0547065b4f9b65ada8af6a3c33cc636d97b43345"
PERSON_QUOTE = {"content-ec0c38b9a20c424c", "content-e3b8d986ea6db98e", "content-91869ed8be17f3f3"}
NO_PERSON_QUOTE = {"content-e787c9201b94a948", "content-3ae2d78568210164"}
REAL_ENTITIES = ("Suleyman", "Anthropic", "Claude", "Microsoft", "Amodei")


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True)


def _available() -> bool:
    try:
        return _git("cat-file", "-e", f"{EXPORT_COMMIT}:data/tak_media_archive.json").returncode == 0
    except OSError:
        return False


@unittest.skipUnless(_available(), "Codespace export commit이 로컬 git에 없습니다.")
class RecoveredShortsReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.json"
            path.write_bytes(_git("show", f"{EXPORT_COMMIT}:data/tak_media_archive.json").stdout)
            cls.records = {r.content_id: r for r in load_archive(path)}
        cls.scripts = {
            cid: json.loads(_git("show", f"{EXPORT_COMMIT}:data/shorts_scripts/{cid}.json").stdout.decode("utf-8"))
            for cid in PERSON_QUOTE | NO_PERSON_QUOTE
        }
        cls.knowledge = {k["id"]: k for k in json.loads((ROOT / "data" / "tak_brain_knowledge.json").read_text(encoding="utf-8"))}

    def _text(self, cid: str) -> str:
        s = self.scripts[cid]
        return " ".join([s["title"], *s["cards"], s["takeaway"]])

    def test_five_candidates_are_valid_approved_active_shorts_with_readable_scripts(self) -> None:
        for cid in PERSON_QUOTE | NO_PERSON_QUOTE:
            r = self.records[cid]
            self.assertEqual((r.platform, r.generation_status, r.review_status, r.superseded_by), ("shorts", "valid", "approved", None))
            ShortsScript.from_dict(self.scripts[cid])
            self.assertEqual(self.scripts[cid]["knowledge_id"], r.knowledge_id)
            self.assertIn(r.source_url, self.scripts[cid]["takeaway"])  # 출처 URL이 화면에 표기된다

    def test_real_person_quote_split_is_exact(self) -> None:
        quoted = {cid for cid in PERSON_QUOTE | NO_PERSON_QUOTE if any(e in self._text(cid) for e in REAL_ENTITIES)}
        self.assertEqual(quoted, PERSON_QUOTE)

    def test_person_quote_is_backed_only_by_a_one_line_source_summary(self) -> None:
        # 근거가 KNOWLEDGE의 factual_information(= RSS 요약 1문장)뿐이고 검증 필요로 표시돼 있다
        k = self.knowledge["knowledge-scout-6d1d0e2fa762"]
        self.assertTrue(k["verification_required"])
        self.assertEqual(k["current_validity"], "확인 필요")
        self.assertIn("Suleyman", k["factual_information"])
        for cid in PERSON_QUOTE:
            self.assertEqual(self.records[cid].knowledge_id, "knowledge-scout-6d1d0e2fa762")

    def test_no_person_quote_candidates_match_recorded_source_fact(self) -> None:
        k = self.knowledge["knowledge-scout-b28b782b2a33"]
        for cid in NO_PERSON_QUOTE:
            r = self.records[cid]
            self.assertIn(f"SOURCE FACT: {k['factual_information']}", r.evidence)
            self.assertEqual(r.knowledge_id, "knowledge-scout-b28b782b2a33")


if __name__ == "__main__":
    unittest.main()

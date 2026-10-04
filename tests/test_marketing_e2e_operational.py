"""6-84 Marketing Factory 운영 E2E: 운영자가 쓰는 CLI를 실제 순서대로 subprocess로 실행한다.

Market Demand -> Idea -> Brief -> KNOWLEDGE 승인(review_knowledge.py) -> knowledge add -> review/approve
-> generate --rewrite mock -> bridge -> /media/generations 검토 handler(API) -> promote_media_generation dry-run/execute
(임시 production) -> PerformanceRecord(API) -> insights CLI -> brief_id 귀속.

- 모든 데이터는 임시 디렉터리(--data-dir/--input/--archive/--production-archive)에만 쓴다.
- subprocess CLI는 ``sitecustomize`` 가드로 실행한다: 소켓 연결과 publisher 모듈 import가 일어나면 즉시 실패한다.
- 실제 저장소 data/ 파일은 테스트 전후 SHA-256이 같아야 한다.
"""

from __future__ import annotations

from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

from content_engine.marketing import load_briefs, resolve_brief
from content_engine.media_archive import archive_generation_report, load_archive
from content_engine.performance.models import PerformanceRecord
from content_engine.performance.store import append_snapshot
from content_engine.pipeline import run_media_batch
from content_engine.publish_history import compute_content_id
from content_engine.rewrite import MockRewriteProvider
from scripts.run_scout_dashboard import discover_generation_pool_paths, handle_generation_review_submission
from tests.test_marketing_generation import knowledge

ROOT = Path(__file__).resolve().parents[1]
FILLED = "매주 3개 사례를 숫자로 보여주는 구체적인 문장"
# 승인 조건(approval_blockers)을 사람이 set으로 채우는 요소.
HUMAN_ELEMENTS = (
    "brief.target_audience", "brief.customer_problem", "brief.desired_action", "storytelling.hook",
    "sales.value_proposition", "sales.call_to_action", "psychology.pain", "psychology.trust",
    "sales.target_customer", "sales.customer_problem", "sales.benefit", "sales.objection", "sales.proof",
    "sales.offer", "sales.conversion_goal", "storytelling.call_to_action", "psychology.attention",
    "design.visual_hook", "design.thumbnail_concept", "storytelling.transformation",
)
DEMANDS = [{"source": "flippa", "title": "AI newsletter", "category": "newsletter", "price": 5000,
            "verified_transaction": "true", "competition_signal": 0.2, "demand_signal": 0.7, "url": "https://x/1"}]
EXPERIENCE_KNOWLEDGE = "knowledge-exp-1"

GUARD = textwrap.dedent('''
    """6-84 테스트 가드: 네트워크 연결과 publisher 호출을 금지한다.

    content_engine/__init__.py가 threads_publisher를 패키지 수준에서 import하므로 모든 CLI가 publisher
    모듈을 '로드'한다. 로드는 허용하고, publisher client의 모든 메서드와 기본 HTTP transport '호출'을 막는다.
    호출되면 예외와 함께 TAK_6_84_GUARD_LOG 파일에 기록한다(CLI가 예외를 삼켜도 감지된다).
    """
    import os, socket

    def _trip(what):
        log = os.environ.get("TAK_6_84_GUARD_LOG")
        if log:
            with open(log, "a", encoding="utf-8") as handle:
                handle.write(what + "\\n")
        raise RuntimeError(f"6-84 guard: {what} blocked")

    def _network(*args, **kwargs):
        _trip("network")

    socket.socket.connect = _network
    socket.socket.connect_ex = _network
    socket.create_connection = _network
    socket.getaddrinfo = _network

    def _block_publishers():
        from content_engine import threads_publisher, youtube_publisher
        for module, class_name in ((threads_publisher, "ThreadsClient"), (youtube_publisher, "YouTubeClient")):
            cls = getattr(module, class_name)
            for name, attr in list(vars(cls).items()):
                if name == "__init__" or (not name.startswith("__") and (callable(attr) or isinstance(attr, (classmethod, staticmethod)))):
                    label = f"publisher {class_name}.{name}"
                    setattr(cls, name, (lambda label: (lambda *a, **k: _trip(label)))(label))
            for name in [n for n in vars(module) if n.startswith("_default_") and n.endswith("transport")]:
                setattr(module, name, (lambda label: (lambda *a, **k: _trip(label)))(f"publisher {module.__name__}.{name}"))

    _block_publishers()
''')


def _fingerprint(directory: Path) -> dict[str, str]:
    if not directory.exists():
        return {}
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(directory.iterdir()) if path.is_file()}


class Operator:
    """임시 데이터 디렉터리에서 운영 CLI를 실행하는 운영자."""

    def __init__(self, base: Path):
        self.base = base
        self.data = base / "data"
        self.data.mkdir()
        guard_dir = base / "guard"
        guard_dir.mkdir()
        (guard_dir / "sitecustomize.py").write_text(GUARD, encoding="utf-8")
        self.guard_log = base / "guard.log"
        self.env = {**os.environ, "PYTHONPATH": os.pathsep.join((str(guard_dir), str(ROOT))),
                    "PYTHONDONTWRITEBYTECODE": "1", "TAK_6_84_GUARD_LOG": str(self.guard_log)}
        for key in [k for k in self.env if k.startswith(("TAK_MEDIA_LLM_", "THREADS_", "YOUTUBE_", "PERPLEXITY"))]:
            self.env.pop(key)
        self.log: list[tuple[str, int, str]] = []

    def run(self, script: str, *args: str) -> tuple[int, str]:
        result = subprocess.run([sys.executable, str(ROOT / "scripts" / script), *args], cwd=self.base,
                                env=self.env, capture_output=True, text=True, timeout=120)
        output = result.stdout + result.stderr
        self.log.append((" ".join((script, *args)), result.returncode, output))
        if "6-84 guard" in output or self.guard_log.exists():
            raise AssertionError(f"guard tripped: {script} {args}\n{output}")
        return result.returncode, output

    def mb(self, *args: str) -> tuple[int, str]:
        return self.run("marketing_brief.py", "--data-dir", str(self.data), *args)

    def ok(self, code_output: tuple[int, str]) -> str:
        code, output = code_output
        if code != 0:
            raise AssertionError(f"exit {code}: {self.log[-1][0]}\n{output}")
        return output

    def json(self, name: str):
        return json.loads((self.data / name).read_text(encoding="utf-8"))

    @property
    def knowledge_path(self) -> Path:
        return self.data / "tak_brain_knowledge.json"

    @property
    def production(self) -> Path:
        return self.data / "tak_media_archive.json"

    # --- 운영 단계 ---------------------------------------------------------------------------------
    def demand_to_brief(self) -> str:
        demands = self.base / "demands.json"
        demands.write_text(json.dumps(DEMANDS), encoding="utf-8")
        # 운영자가 이미 가지고 있는 경험 KNOWLEDGE(아직 pending) - 생성 입력이 되는 KNOWLEDGE.
        self.knowledge_path.write_text(json.dumps(
            [knowledge(EXPERIENCE_KNOWLEDGE, status="pending").to_dict()], ensure_ascii=False), encoding="utf-8")
        self.ok(self.run("market_demand.py", "--input", str(demands), "--min-score", "30",
                         "--data-dir", str(self.data), "--write"))
        idea_id = self.json("tak_idea_candidates.json")[0]["idea_id"]
        self.ok(self.mb("--write", "draft", idea_id, "--research", "mock"))
        brief_id = self.json("tak_marketing_briefs.json")[0]["brief_id"]
        output = self.ok(self.mb("--write", "platforms", brief_id))
        return next(line.split()[2] for line in output.splitlines() if line.startswith("- youtube:"))

    def approve_knowledge(self, knowledge_id: str = EXPERIENCE_KNOWLEDGE) -> str:
        return self.ok(self.run("review_knowledge.py", "--input", str(self.knowledge_path), "--id", knowledge_id,
                                "--approve", "--note", "6-84 operational e2e"))

    def fill_and_approve(self, brief_id: str) -> str:
        for key in HUMAN_ELEMENTS:
            self.ok(self.mb("set", brief_id, key, FILLED))
        return self.ok(self.mb("approve", brief_id))

    def through_bridge(self) -> str:
        brief_id = self.demand_to_brief()
        self.approve_knowledge()
        self.ok(self.mb("--write", "knowledge", "add", brief_id, EXPERIENCE_KNOWLEDGE))
        self.fill_and_approve(brief_id)
        self.ok(self.mb("--write", "generate", brief_id, "--rewrite", "mock"))
        self.ok(self.mb("--write", "bridge", brief_id))
        return brief_id

    def pool(self, brief_id: str) -> Path:
        return self.data / f"tak_media_generation_marketing-{brief_id}.json"

    def promote(self, pool: Path, generation_id: str, execute: bool) -> tuple[int, str]:
        args = ["--archive", str(pool), "--production-archive", str(self.production), "--generation-id", generation_id]
        return self.run("promote_media_generation.py", *args, *(["--execute"] if execute else []))

    def record_performance(self, content_id: str) -> None:
        append_snapshot(self.data / "tak_performance.json", PerformanceRecord(
            content_id=content_id, knowledge_id=EXPERIENCE_KNOWLEDGE, platform="youtube",
            published_at="2026-10-04T00:00:00+00:00", metric_collected_at="2026-10-05T00:00:00+00:00",
            metrics={"views": 1000, "likes": 40, "clicks": 12}, source="manual"))


class OperationalE2EBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo_data_before = _fingerprint(ROOT / "data")

    @classmethod
    def tearDownClass(cls):
        # 실제 운영 data/는 이 테스트 전후로 바이트 단위까지 같아야 한다.
        assert _fingerprint(ROOT / "data") == cls.repo_data_before, "실제 data/가 변경되었습니다"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.op = Operator(Path(self.tmp.name))


class HappyPathTests(OperationalE2EBase):
    def test_complete_operational_loop(self):
        op = self.op
        # Demand -> Idea -> Brief(공통) -> platforms -> youtube 브리프
        brief_id = op.demand_to_brief()
        self.assertEqual(len(op.json("tak_market_demands.json")), 1)
        idea = op.json("tak_idea_candidates.json")[0]
        common = op.json("tak_marketing_briefs.json")[0]
        self.assertEqual(common["idea_id"], idea["idea_id"])
        self.assertTrue(any(item["kind"] == "market_demand" for item in common["evidence"]))
        youtube = next(b for b in load_briefs(op.data / "tak_marketing_briefs.json") if b.brief_id == brief_id)
        self.assertEqual((youtube.platform, youtube.status), ("youtube", "draft"))

        # KNOWLEDGE: 기존 review_knowledge.py로 승인 -> knowledge add 미리보기 -> --write
        self.assertIn(f"{EXPERIENCE_KNOWLEDGE}: approved", op.approve_knowledge())
        before = (op.data / "tak_marketing_briefs.json").read_bytes()
        preview = op.ok(op.mb("knowledge", "add", brief_id, EXPERIENCE_KNOWLEDGE))
        self.assertIn("KNOWLEDGE status: approved (approved: 예)", preview)
        self.assertEqual((op.data / "tak_marketing_briefs.json").read_bytes(), before)
        op.ok(op.mb("--write", "knowledge", "add", brief_id, EXPERIENCE_KNOWLEDGE))

        # review: 연결된 KNOWLEDGE의 승인 상태와 생성 차단 사유가 보인다(6-84 수정 1)
        review = op.ok(op.mb("review", brief_id))
        self.assertIn(f"{EXPERIENCE_KNOWLEDGE} [approved]", review)
        self.assertIn("[pending]", review)  # draft --research가 출처로 연결한 리서치 KNOWLEDGE
        self.assertIn("생성 가능한 approved KNOWLEDGE 1건", review)
        self.assertIn("생성 차단:", review)

        # approve(사람) -> generate 미리보기 -> --write
        self.assertEqual(op.fill_and_approve(brief_id).strip(), "approved")
        preview = op.ok(op.mb("generate", brief_id, "--rewrite", "mock"))
        self.assertIn("후보 3건", preview)
        self.assertFalse((op.data / "tak_marketing_contents.json").exists())
        op.ok(op.mb("--write", "generate", brief_id, "--rewrite", "mock"))
        contents = op.json("tak_marketing_contents.json")
        self.assertEqual(len(contents), 3)
        for row in contents:
            self.assertEqual((row["platform"], row["media_platform"], row["status"], row["rewrite_status"]),
                             ("youtube", "shorts", "review_required", "rewritten"))

        # bridge 미리보기 -> --write: 기존 대시보드 규칙의 pool, unreviewed
        pool = op.pool(brief_id)
        self.assertIn("bridge 대상 3건", op.ok(op.mb("bridge", brief_id)))
        self.assertFalse(pool.exists())
        op.ok(op.mb("--write", "bridge", brief_id))
        self.assertEqual(discover_generation_pool_paths(op.data), (pool,))
        records = load_archive(pool)
        self.assertEqual({(r.platform, r.review_status, r.generation_status) for r in records},
                         {("shorts", "unreviewed", "valid")})
        generation_id = records[0].generation_id
        self.assertEqual({r.content_id for r in records}, {row["content_id"] for row in contents})

        # MEDIA Review: 기존 /media/generations handler로 사람이 1건 승인
        target = records[0]
        updated, error = handle_generation_review_submission(
            discover_generation_pool_paths(op.data), target.content_id, generation_id, "approved")
        self.assertIsNone(error)
        self.assertEqual(updated.review_status, "approved")

        # Promotion: dry-run은 production을 만들지 않는다 -> --execute(임시 production)
        code, output = op.promote(pool, generation_id, execute=False)
        self.assertEqual(code, 0, output)
        self.assertIn(f"{target.content_id}  [shorts]", output)
        self.assertIn("-> PROMOTE", output)
        self.assertEqual(output.count("-> SKIP"), 2)
        self.assertFalse(op.production.exists())
        code, output = op.promote(pool, generation_id, execute=True)
        self.assertEqual(code, 0, output)
        production = load_archive(op.production)
        self.assertEqual([(r.content_id, r.generation_id, r.platform) for r in production],
                         [(target.content_id, generation_id, "shorts")])

        # Performance(production content_id) -> insights CLI(6-84 수정 2) -> brief_id
        op.record_performance(target.content_id)
        insights = op.ok(op.mb("insights"))
        self.assertIn("연결된 콘텐츠 성과 1건", insights)
        self.assertIn(f"brief={brief_id} platform=youtube content={target.content_id} generation={generation_id}",
                      insights)
        self.assertIn("attention=1000.0 engagement=40.0 conversion=12.0", insights)
        self.assertEqual(resolve_brief(load_briefs(op.data / "tak_marketing_briefs.json"),
                                       target.content_id, generation_id), brief_id)

        # 파일 검증: 운영 순서대로 만들어진 파일만 존재한다(발행 로그 없음).
        self.assertEqual(set(_fingerprint(op.data)), {
            "tak_brain_knowledge.json", "tak_idea_candidates.json", "tak_market_demands.json",
            "tak_marketing_briefs.json", "tak_marketing_contents.json", pool.name, "tak_media_archive.json",
            "tak_performance.json",
        })


class GateTests(OperationalE2EBase):
    def test_unapproved_brief_is_not_generated(self):
        op = self.op
        brief_id = op.demand_to_brief()
        op.approve_knowledge()
        op.ok(op.mb("--write", "knowledge", "add", brief_id, EXPERIENCE_KNOWLEDGE))
        code, output = op.mb("--write", "generate", brief_id, "--rewrite", "mock")
        self.assertEqual(code, 2)
        self.assertIn("approved 브리프만 생성할 수 있습니다", output)
        code, output = op.mb("--write", "bridge", brief_id)
        self.assertEqual(code, 2)
        self.assertFalse((op.data / "tak_marketing_contents.json").exists())
        self.assertFalse(op.pool(brief_id).exists())

    def test_unapproved_knowledge_is_not_linked(self):
        op = self.op
        brief_id = op.demand_to_brief()
        before = (op.data / "tak_marketing_briefs.json").read_bytes()
        code, output = op.mb("--write", "knowledge", "add", brief_id, EXPERIENCE_KNOWLEDGE)  # 아직 pending
        self.assertEqual(code, 2)
        self.assertIn("approved KNOWLEDGE만 연결할 수 있습니다(현재 pending)", output)
        op.ok(op.run("review_knowledge.py", "--input", str(op.knowledge_path), "--id", EXPERIENCE_KNOWLEDGE,
                     "--reject"))
        code, output = op.mb("--write", "knowledge", "add", brief_id, EXPERIENCE_KNOWLEDGE)
        self.assertEqual(code, 2)
        self.assertIn("현재 rejected", output)
        code, output = op.mb("--write", "knowledge", "add", brief_id, "knowledge-missing")
        self.assertEqual(code, 2)
        self.assertEqual((op.data / "tak_marketing_briefs.json").read_bytes(), before)

    def test_brief_without_usable_knowledge_is_not_generated_or_bridged(self):
        op = self.op
        brief_id = op.demand_to_brief()
        op.fill_and_approve(brief_id)
        # draft --research가 연결한 리서치 KNOWLEDGE는 pending이라 생성에 쓰이지 않는다.
        code, output = op.mb("--write", "generate", brief_id, "--rewrite", "mock")
        self.assertEqual(code, 2)
        self.assertIn("approved KNOWLEDGE가 없습니다", output)
        # 연결을 모두 해제하면 게이트 자체가 막는다.
        for knowledge_id in load_briefs(op.data / "tak_marketing_briefs.json")[-1].knowledge_ids:
            op.ok(op.mb("--write", "knowledge", "remove", brief_id, knowledge_id))
        for command in (("--write", "generate", brief_id, "--rewrite", "mock"), ("--write", "bridge", brief_id)):
            code, output = op.mb(*command)
            self.assertEqual(code, 2)
            self.assertIn("연결된 KNOWLEDGE 없음", output)
        self.assertFalse((op.data / "tak_marketing_contents.json").exists())
        self.assertFalse(op.pool(brief_id).exists())


class MediaSafetyTests(OperationalE2EBase):
    def setUp(self):
        super().setUp()
        self.brief_id = self.op.through_bridge()
        self.pool = self.op.pool(self.brief_id)
        self.generation_id = load_archive(self.pool)[0].generation_id

    def test_bridge_does_not_approve_or_promote(self):
        records = load_archive(self.pool)
        self.assertTrue(all(r.review_status == "unreviewed" for r in records))
        self.assertFalse(self.op.production.exists())
        code, output = self.op.promote(self.pool, self.generation_id, execute=False)
        self.assertEqual(code, 0, output)
        self.assertNotIn("-> PROMOTE", output)
        self.assertEqual(output.count("-> SKIP"), 3)
        # --execute여도 승인된 것이 없으면 production은 그대로다.
        self.op.production.write_text("[]\n", encoding="utf-8")
        before = self.op.production.read_bytes()
        self.op.promote(self.pool, self.generation_id, execute=True)
        self.assertEqual(self.op.production.read_bytes(), before)

    def test_dry_run_does_not_modify_existing_production(self):
        existing = run_media_batch([knowledge("knowledge-other")], provider=MockRewriteProvider())
        archive_generation_report(existing, self.op.data / "tak_media_generation_seed.json", generation_id="gen-seed")
        self.op.production.write_text(json.dumps([r.to_dict() for r in load_archive(
            self.op.data / "tak_media_generation_seed.json")][:1], ensure_ascii=False), encoding="utf-8")
        before = self.op.production.read_bytes()
        target = load_archive(self.pool)[0]
        handle_generation_review_submission((self.pool,), target.content_id, target.generation_id, "approved")
        code, output = self.op.promote(self.pool, self.generation_id, execute=False)
        self.assertEqual(code, 0, output)
        self.assertIn("-> PROMOTE", output)
        self.assertEqual(self.op.production.read_bytes(), before)
        code, output = self.op.promote(self.pool, self.generation_id, execute=True)
        self.assertEqual(code, 0, output)
        after = load_archive(self.op.production)
        self.assertEqual(len(after), 2)
        self.assertEqual(after[0].to_dict(), json.loads(before)[0])  # 기존 production 레코드는 그대로

    def test_same_content_id_other_generation_not_attributed(self):
        op = self.op
        batch_pool = op.data / "tak_media_generation_batch.json"
        archive_generation_report(run_media_batch([knowledge(EXPERIENCE_KNOWLEDGE)], provider=MockRewriteProvider()),
                                  batch_pool, generation_id="gen-batch")
        target = load_archive(self.pool)[0]
        batch_record = next(r for r in load_archive(batch_pool) if r.content_id == target.content_id)
        handle_generation_review_submission(discover_generation_pool_paths(op.data), batch_record.content_id,
                                            "gen-batch", "approved")
        op.ok(op.promote(batch_pool, "gen-batch", execute=True))
        self.assertEqual([(r.content_id, r.generation_id) for r in load_archive(op.production)],
                         [(target.content_id, "gen-batch")])
        op.record_performance(target.content_id)
        output = op.ok(op.mb("insights"))
        self.assertIn("연결된 콘텐츠 성과 0건", output)
        self.assertNotIn(f"content={target.content_id}", output)

    def test_youtube_content_id_is_shorts_slot(self):
        contents = self.op.json("tak_marketing_contents.json")
        batch = run_media_batch([knowledge(EXPERIENCE_KNOWLEDGE)], provider=MockRewriteProvider())
        shorts_ids = [compute_content_id(item.to_dict()) for item in batch.items if item.platform == "shorts"]
        self.assertEqual([row["content_id"] for row in contents], shorts_ids)
        self.assertTrue(all(row["platform"] == "youtube" and row["media_platform"] == "shorts" for row in contents))
        self.assertEqual([r.content_id for r in load_archive(self.pool)], shorts_ids)
        self.assertTrue(all(r.platform == "shorts" for r in load_archive(self.pool)))

    def test_knowledge_remove_preserves_existing_data_and_lineage(self):
        op = self.op
        target = load_archive(self.pool)[0]
        handle_generation_review_submission((self.pool,), target.content_id, target.generation_id, "approved")
        op.ok(op.promote(self.pool, self.generation_id, execute=True))
        op.record_performance(target.content_id)
        briefs_path = op.data / "tak_marketing_briefs.json"
        brief_before = next(b for b in load_briefs(briefs_path) if b.brief_id == self.brief_id)
        others_before = {name: digest for name, digest in _fingerprint(op.data).items()
                         if name != briefs_path.name}

        output = op.ok(op.mb("--write", "knowledge", "remove", self.brief_id, EXPERIENCE_KNOWLEDGE))
        self.assertIn("이미 연결된 콘텐츠 3건과 lineage는 변경하지 않습니다", output)
        brief_after = next(b for b in load_briefs(briefs_path) if b.brief_id == self.brief_id)
        self.assertNotIn(EXPERIENCE_KNOWLEDGE, brief_after.knowledge_ids)
        self.assertEqual((brief_after.status, brief_after.content_ids, brief_after.media_generations),
                         (brief_before.status, brief_before.content_ids, brief_before.media_generations))
        self.assertEqual({n: d for n, d in _fingerprint(op.data).items() if n != briefs_path.name}, others_before)
        # 기존 lineage로 성과 귀속은 그대로 동작한다.
        self.assertIn(f"brief={self.brief_id} platform=youtube content={target.content_id}",
                      op.ok(op.mb("insights")))


class GuardTests(OperationalE2EBase):
    def test_guard_blocks_network_and_publishers_in_cli_subprocesses(self):
        probe = self.op.base / "probe.py"
        probe.write_text(textwrap.dedent('''
            import socket
            from content_engine.threads_publisher import ThreadsClient
            from content_engine.youtube_publisher import YouTubeClient
            results = []
            for name, call in (("network", lambda: socket.create_connection(("example.com", 443), timeout=1)),
                               ("threads", lambda: ThreadsClient("token")),
                               ("youtube", lambda: YouTubeClient.from_environment({}))):
                try:
                    call()
                    results.append(name + "-open")
                except RuntimeError as error:
                    results.append(str(error))
            print("|".join(results))
        '''), encoding="utf-8")
        result = subprocess.run([sys.executable, str(probe)], cwd=self.op.base, env=self.op.env,
                                capture_output=True, text=True, timeout=60)
        self.assertNotIn("-open", result.stdout, result.stdout + result.stderr)
        self.assertEqual(result.stdout.count("6-84 guard"), 3, result.stdout + result.stderr)
        self.assertEqual(self.op.guard_log.read_text(encoding="utf-8").splitlines(),
                         ["network", "publisher ThreadsClient.__init__", "publisher YouTubeClient.from_environment"])

    def test_full_loop_runs_under_guard(self):
        # through_bridge + promote의 모든 CLI가 가드 아래에서 성공한다(가드 위반 시 Operator.run이 실패시킨다).
        brief_id = self.op.through_bridge()
        pool = self.op.pool(brief_id)
        target = load_archive(pool)[0]
        handle_generation_review_submission((pool,), target.content_id, target.generation_id, "approved")
        self.op.ok(self.op.promote(pool, target.generation_id, execute=True))
        self.assertTrue(all(code == 0 for _, code, _ in self.op.log))
        self.assertGreaterEqual(len(self.op.log), 25)
        self.assertFalse(any(path.name.endswith("publish_log.json") for path in self.op.data.iterdir()))
        self.assertFalse(self.op.guard_log.exists())


if __name__ == "__main__":
    unittest.main()

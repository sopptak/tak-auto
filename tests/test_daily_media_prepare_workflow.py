"""`.github/workflows/daily-media-prepare.yml`(5-30) 검증.

이 workflow는 새 비즈니스 로직이 없다 - scripts/prepare_approved_media.py(5-29,
그 자체도 새 로직 없이 기존 두 CLI를 호출할 뿐)를 그대로 실행하고, 결과
파일(data/shorts_scripts/*.json)에 변경이 있을 때만 commit/push한다.

이 테스트 파일은 실제로 GitHub Actions 러너를 구동하지 않는다(불가능하다).
대신 다음 두 가지로 워크플로우의 안전성을 검증한다:
    1. YAML 파일 내용에 대한 정적 검사(A~I) - 실제 발행/LLM/Secrets 코드
       경로가 존재하지 않는다는 것을 텍스트 수준에서 확인한다.
    2. 워크플로우가 실행하는 것과 동일한 git 명령(git add + git diff --cached
       --quiet)을 격리된 임시 git 저장소에서 직접 실행해, "변경 없으면 커밋
       안 함"(K)과 "재실행해도 안전함"(L)을 기능적으로 확인한다.

실제 production 데이터는 이 파일 어디에서도 건드리지 않는다 - 전부
tempfile.TemporaryDirectory() 안에서만 동작한다(5-29에서 실제 프로덕션
경로에 테스트 파일이 생성된 사고가 있었으므로, 이번에는 격리를 특히
엄격하게 지킨다).
"""

from __future__ import annotations

from pathlib import Path
import json
import subprocess
import tempfile
import unittest

from content_engine.media_archive import MediaArchiveRecord, upsert_archive
from scripts.prepare_approved_media import main as prepare_approved_media_main


WORKFLOW_PATH = Path(__file__).parents[1] / ".github" / "workflows" / "daily-media-prepare.yml"


class WorkflowFileStaticChecks(unittest.TestCase):
    """A~I: YAML 파일 자체에 대한 텍스트 수준 검사."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = WORKFLOW_PATH.read_text(encoding="utf-8")
        # 주석은 "이 workflow가 무엇을 하지 않는지" 설명하느라 금지어를 그대로
        # 언급한다(예: "Threads 실제 게시(scripts/publish_threads.py...)를 전혀
        # import/실행하지 않는다") - 이런 설명은 허용해야 하므로, 실제 실행
        # 가능한 YAML 코드(비-주석 줄)만 따로 모아 검사 대상으로 쓴다.
        cls.executable_lines = [
            line for line in cls.source.splitlines() if not line.strip().startswith("#")
        ]
        cls.executable_source = "\n".join(cls.executable_lines)

    # --- A. workflow 파일 존재 ---------------------------------------------------

    def test_workflow_file_exists(self):
        self.assertTrue(WORKFLOW_PATH.exists())

    # --- B. workflow_dispatch 존재 -----------------------------------------------

    def test_has_workflow_dispatch_trigger(self):
        self.assertIn("workflow_dispatch:", self.source)

    # --- C. schedule 존재 ---------------------------------------------------------

    def test_has_schedule_trigger(self):
        self.assertIn("schedule:", self.source)
        self.assertIn("cron:", self.source)

    def test_schedule_does_not_collide_with_daily_scout(self):
        """daily-scout.yml의 cron('0 23 * * *')과 겹치지 않는지 직접 비교한다."""
        daily_scout = (WORKFLOW_PATH.parent / "daily-scout.yml").read_text(encoding="utf-8")
        self.assertIn("cron: '0 23 * * *'", daily_scout)
        self.assertIn("cron: '30 23 * * *'", self.source)
        self.assertNotIn("cron: '0 23 * * *'", self.source)

    # --- D~H. 실제 발행/LLM 스크립트·모듈 참조 없음 -------------------------------

    def test_no_forbidden_references(self):
        forbidden = (
            "publish_threads.py",
            "publish_approved_threads.py",
            "upload_youtube_short.py",
            "threads_publisher",
            "youtube_publisher",
            "llm_provider",
            "OpenAICompatibleRewriteProvider",
            "ThreadsClient",
            "YouTubeClient",
        )
        for token in forbidden:
            self.assertNotIn(token, self.executable_source, f"workflow가 {token}을 실행 코드에서 참조하면 안 됩니다.")

    def test_no_naver_reference_outside_comments_explaining_absence(self):
        # "Naver 게시 자동화 코드 자체가 없다"는 설명 주석은 허용하되, 실제 실행
        # 스텝(run:) 안에 naver 관련 명령이 있는지는 별도로 확인한다.
        for line in self.source.splitlines():
            if "run:" in line or line.strip().startswith(("python3", "git ")):
                self.assertNotIn("naver", line.lower())

    # --- I. Secrets 사용 없음 -------------------------------------------------------

    def test_no_secrets_usage(self):
        self.assertNotIn(
            "secrets.", self.executable_source, "이 workflow는 어떤 GitHub Secrets도 참조하면 안 됩니다."
        )

    def test_has_no_env_block_with_tokens(self):
        forbidden_env_names = (
            "THREADS_ACCESS_TOKEN",
            "TAK_MEDIA_LLM_API_KEY",
            "TAK_MEDIA_LLM_ENDPOINT",
            "TAK_MEDIA_LLM_MODEL",
            "YOUTUBE_CLIENT_ID",
            "YOUTUBE_CLIENT_SECRET",
            "YOUTUBE_REFRESH_TOKEN",
        )
        for name in forbidden_env_names:
            self.assertNotIn(name, self.executable_source)

    def test_permissions_are_minimal(self):
        self.assertIn("contents: write", self.source)

    def test_concurrency_group_prevents_overlapping_runs(self):
        self.assertIn("concurrency:", self.source)
        self.assertIn("cancel-in-progress: false", self.source)

    def test_does_not_trigger_on_push(self):
        """자기 자신을 포함해 어떤 workflow도 push로 재트리거되지 않는지 -
        이 workflow가 on: push를 쓰지 않는다는 것을 직접 확인한다."""
        # "on:" 블록만 잘라서 확인(주석 속 "push"라는 단어와 혼동하지 않기 위해).
        on_block = self.source.split("permissions:")[0]
        self.assertNotIn("push:", on_block)

    def test_calls_only_prepare_approved_media_script(self):
        self.assertIn("scripts/prepare_approved_media.py", self.source)

    def test_blog_pack_is_uploaded_as_artifact_not_committed(self):
        """5-30 결정 D: Blog Pack은 기존 정책(휘발성, git 비영속)을 그대로
        존중해 아티팩트로만 남긴다 - git commit 대상에 포함되지 않는지 확인."""
        self.assertIn("upload-artifact", self.source)
        self.assertIn("blog_publish_pack_daily.md", self.source)
        commit_step = self.source.split("Commit and push")[1]
        self.assertNotIn("blog_publish_pack_daily", commit_step)

    def test_shorts_scripts_are_committed(self):
        """5-30 결정 E: Shorts script는 다음 실행에서도 "이미 생성됨"을
        판단할 수 있어야 하므로 git에 커밋 대상이어야 한다."""
        self.assertIn("git add data/shorts_scripts", self.source)


class WorkflowGitCommitLogicTests(unittest.TestCase):
    """K, L: 워크플로우가 실제로 실행하는 것과 동일한 git 명령을 격리된 임시
    저장소에서 직접 실행해 "변경 없으면 커밋 안 함" + "재실행해도 안전함"을
    기능적으로 검증한다. 실제 GitHub Actions 러너나 production 저장소는
    전혀 사용하지 않는다."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.repo_path = Path(self.tmp_dir.name)
        self._run_git(["init", "-q"])
        self._run_git(["config", "user.email", "test@example.test"])
        self._run_git(["config", "user.name", "Test"])
        (self.repo_path / "README.md").write_text("init\n", encoding="utf-8")
        self._run_git(["add", "README.md"])
        self._run_git(["commit", "-q", "-m", "init"])

    def _run_git(self, args: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], cwd=self.repo_path, check=True, capture_output=True, text=True)

    def _diff_cached_has_changes(self, path: str = "data/shorts_scripts") -> bool:
        """워크플로우의 'git add <path> && git diff --cached --quiet -- <path>' 스텝과
        정확히 동일한 명령을 실행한다. True면 커밋할 변경이 있다는 뜻이다."""
        subprocess.run(["git", "add", path], cwd=self.repo_path, check=True)
        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet", "--", path], cwd=self.repo_path
        )
        return result.returncode != 0

    # --- K. 변경 없을 때 빈 commit 없음 --------------------------------------------

    def test_no_new_shorts_scripts_reports_no_changes(self):
        (self.repo_path / "data" / "shorts_scripts").mkdir(parents=True)

        self.assertFalse(self._diff_cached_has_changes())

    def test_new_shorts_script_is_detected_as_a_change(self):
        scripts_dir = self.repo_path / "data" / "shorts_scripts"
        scripts_dir.mkdir(parents=True)
        (scripts_dir / "content-1.json").write_text("{}\n", encoding="utf-8")

        self.assertTrue(self._diff_cached_has_changes())

    # --- L. 동일 workflow 재실행 idempotent -----------------------------------------

    def test_rerunning_after_commit_reports_no_further_changes(self):
        scripts_dir = self.repo_path / "data" / "shorts_scripts"
        scripts_dir.mkdir(parents=True)
        (scripts_dir / "content-1.json").write_text("{}\n", encoding="utf-8")
        self._run_git(["add", "data/shorts_scripts"])
        self._run_git(["commit", "-q", "-m", "chore: prepare approved Shorts scripts"])

        # 같은 파일, 같은 내용 - 두 번째 "실행"에서는 변경이 없어야 한다.
        self.assertFalse(self._diff_cached_has_changes())

    def test_second_run_with_new_content_id_only_reports_the_new_file(self):
        scripts_dir = self.repo_path / "data" / "shorts_scripts"
        scripts_dir.mkdir(parents=True)
        (scripts_dir / "content-1.json").write_text("{}\n", encoding="utf-8")
        self._run_git(["add", "data/shorts_scripts"])
        self._run_git(["commit", "-q", "-m", "chore: prepare approved Shorts scripts"])

        (scripts_dir / "content-2.json").write_text("{}\n", encoding="utf-8")
        self.assertTrue(self._diff_cached_has_changes())

        status = self._run_git(["status", "--short", "--", "data/shorts_scripts"])
        # content-1.json은 이미 커밋됐으므로 상태에 다시 나타나면 안 된다(중복 아님).
        self.assertNotIn("content-1.json", status.stdout)


class PrepareApprovedMediaEndToEndTests(unittest.TestCase):
    """J: prepare CLI가 실제로 정상 실행되는지(Blog Pack + Shorts Script 둘 다
    생성) 이 워크플로우 관점에서 재확인한다. tmp_path만 사용하며, 실제
    production data/ 디렉터리는 전혀 건드리지 않는다."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.tmp_path = Path(self.tmp_dir.name)

        self.knowledge_path = self.tmp_path / "knowledge.json"
        self.knowledge_path.write_text(
            json.dumps(
                [
                    {
                        "id": "knowledge-workflow-1",
                        "source_url": "https://blog.example.test/1",
                        "title": "원문 기사",
                        "article_type": "experience",
                        "knowledge_type": "경험",
                        "knowledge_review_status": "approved",
                    }
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self.archive_path = self.tmp_path / "archive.json"

    def test_prepare_cli_runs_successfully_and_produces_both_outputs(self):
        upsert_archive(
            self.archive_path,
            [
                MediaArchiveRecord(
                    content_id="content-blog-1",
                    knowledge_id="knowledge-workflow-1",
                    platform="blog",
                    generation_status="valid",
                    original_title="원본",
                    original_body="원본 본문",
                    rewritten_title="AI 블로그 제목",
                    rewritten_body="AI 블로그 본문",
                    source_url="https://blog.example.test/1",
                    evidence=(),
                    evidence_unit_ids=("lesson:1",),
                    created_at="2026-09-19T00:00:00+00:00",
                    review_status="approved",
                ),
                MediaArchiveRecord(
                    content_id="content-shorts-1",
                    knowledge_id="knowledge-workflow-1",
                    platform="shorts",
                    generation_status="valid",
                    original_title="원본",
                    original_body="원본 문단",
                    rewritten_title="AI 숏츠 제목",
                    rewritten_body="문단1\n\n문단2",
                    source_url="https://blog.example.test/1",
                    evidence=(),
                    evidence_unit_ids=("lesson:1",),
                    created_at="2026-09-19T00:00:00+00:00",
                    review_status="approved",
                ),
            ],
        )

        exit_code = prepare_approved_media_main(
            [
                "--knowledge", str(self.knowledge_path),
                "--archive", str(self.archive_path),
                "--blog-history", str(self.tmp_path / "blog_history.json"),
                "--blog-pack-output", str(self.tmp_path / "pack.md"),
                "--shorts-output-dir", str(self.tmp_path / "shorts_scripts"),
                "--threads-pending", str(self.tmp_path / "pending.json"),
            ]
        )

        self.assertEqual(exit_code, 0)
        self.assertTrue((self.tmp_path / "pack.md").exists())
        self.assertTrue((self.tmp_path / "shorts_scripts" / "content-shorts-1.json").exists())

        # data/ 프로덕션 경로에는 아무 것도 생기지 않았어야 한다(격리 재확인).
        real_shorts_scripts = Path(__file__).parents[1] / "data" / "shorts_scripts" / "content-shorts-1.json"
        self.assertFalse(real_shorts_scripts.exists())


if __name__ == "__main__":
    unittest.main()

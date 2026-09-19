"""scripts/run_daily.py 오케스트레이터 검증.

실제 외부 API(LLM, Threads)는 절대 호출하지 않는다. 경계는 두 곳뿐이다.

- ``OpenAICompatibleRewriteProvider.from_environment`` (TAK MEDIA의 LLM 어댑터 생성)
- ``ThreadsClient.from_environment`` (Threads 게시, publish_threads.py 내부에서 사용)

그 사이(TAK BRAIN 로드, TAK MEDIA 생성/검증, publish_threads.py의 자동 선정/이력 기록)는
실제 코드를 그대로 통과시켜, run_daily.py가 기존 구현을 재구현하지 않고 올바르게
연결하는지를 검증한다.
"""

from pathlib import Path
import json
import tempfile
import unittest
from unittest import mock

from content_engine.llm_provider import LLMConfigurationError, OpenAICompatibleRewriteProvider
from content_engine.pipeline import MediaBatchReport
from content_engine.publish_history import PublishHistory
from content_engine.rewrite import MockRewriteProvider
from content_engine.threads_publisher import ThreadsAPIError, ThreadsClient
from scripts.run_daily import main


# 1차 작업(검증)에서 확인한 실제 승인 KNOWLEDGE 레코드를 그대로 고정 픽스처로 사용한다.
# (data/tak_brain_knowledge.json은 이후 바뀔 수 있으므로 테스트를 독립시키기 위해 값을 복제한다.)
APPROVED_EXPERIENCE_RECORD = {
    "id": "knowledge-da6ddf5aa459",
    "source_raw_id": "https://blog.naver.com/tmong2/224407187378",
    "source_url": "https://blog.naver.com/tmong2/224407187378?fromRss=true&trackingCode=rss",
    "title": "57화) 개발을 모르는 내가 앱을 만들다",
    "domain": "자기계발",
    "knowledge_type": "경험",
    "experience": "개발자가 아니고 코딩을 몰랐던 작성자가 ChatGPT로 아이디어와 기획을 정리하고 클로드코드로 결과물을 만들면서, 첫 앱 '나만의 골프기록'과 두 번째 앱 제작까지 진행한 경험이다.",
    "problem": "아이디어를 앱으로 만들려면 개발자에게 부탁해야 한다고 생각했지만, 코딩을 모르는 상태에서 직접 구현해야 했다. 제작 중 문제가 생길 때마다 다음 수정과 테스트로 해결해야 했다.",
    "action": "아이디어를 ChatGPT에 설명해 기획과 명령어를 정리하고, 그 명령어를 클로드코드에 전달해 앱을 만들었다. 문제가 생기면 다시 질문하고 수정·테스트를 반복했으며, 직접 구글 개발자 등록도 하고 비공개 테스트를 진행했다.",
    "decision": "개발자에게만 맡기는 대신 AI와 대화하며 자신이 직접 앱 제작에 도전하기로 판단했다.",
    "result": "첫 번째 앱 '나만의 골프기록'을 만들고 비공개 테스트에 들어갔으며, 테스터 12명이 참여해 14일 이상의 테스트를 진행했다.",
    "lesson": "코딩을 몰라도 완벽하게 알고 시작할 때까지 기다리지 않고, 만들면서 배우고 문제가 생기면 수정할 수 있다는 경험을 얻었다.",
    "reusable_principle": "아이디어를 완전히 구현할 수 있을 때까지 기다리기보다, AI 도구로 기획과 첫 결과물을 만든 뒤 문제마다 질문·수정·테스트를 반복하고 실제 사용자 테스트까지 진행한다.",
    "evidence": [
        "'내가 아이디어를 이야기하면 ChatGPT가 기획을 정리하고 필요한 명령어를 만들어준다.'",
        "'문제가 생기면 다시 물어보고, 수정하고, 테스트하고, 또 수정한다.'",
        "'나만의 골프기록' 앱의 비공개 테스트에 테스터 12명이 참여했고 14일 이상의 테스트 기간을 진행했다.",
    ],
    "derived_insight": "AI를 아이디어를 실제 결과물로 옮기는 작업 파트너로 활용하고, 반복 수정과 사용자 테스트를 거치면 비개발자도 앱 제작을 진행할 수 있다는 지식이다.",
    "inference_method": "rule_based_template",
    "confidence": None,
    "created_at": "2026-09-10T10:03:26.653539+00:00",
    "knowledge_review_status": "approved",
    "category": "자기계발",
    "key_points": [],
    "case": "비개발자의 앱 제작 사례",
    "judgment_rule": "낯선 영역은 직접 시도하고 테스트하면서 검증한다.",
    "opinion": None,
    "factual_information": None,
    "current_validity": "확인 필요",
    "verification_required": True,
    "privacy_risk": False,
    "internal_information_risk": False,
    "reviewed_at": "2026-09-10T10:13:58.556711+00:00",
    "review_note": "테스트 픽스처용 복제본",
}


def _pending_record(**overrides):
    record = {**APPROVED_EXPERIENCE_RECORD, "id": "knowledge-pending-test", "knowledge_review_status": "pending"}
    record.update(overrides)
    return record


def _success_threads_transport(post_id="th_daily_success"):
    def transport(method, url, headers, payload, timeout):
        if method == "GET":
            return {"id": "111", "username": "tmong_wisdom", "name": "티몽의 지혜"}
        return {"id": post_id}

    return transport


def _failure_threads_transport():
    def transport(method, url, headers, payload, timeout):
        if method == "GET":
            return {"id": "111", "username": "tmong_wisdom", "name": "티몽의 지혜"}
        raise ThreadsAPIError("Threads HTTP 500: message=Internal error")

    return transport


class RunDailyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.tmp_path = Path(self.tmp_dir.name)
        self.knowledge_path = self.tmp_path / "knowledge.json"
        self.output_path = self.tmp_path / "batch_daily.json"
        self.history_path = self.tmp_path / "threads_publish_log.json"
        self.archive_path = self.tmp_path / "tak_media_archive.json"

    def _write_knowledge(self, records) -> None:
        self.knowledge_path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")

    def _run(self, extra_args=None):
        args = [
            "--knowledge", str(self.knowledge_path),
            "--output", str(self.output_path),
            "--history", str(self.history_path),
            "--archive", str(self.archive_path),
        ]
        if extra_args:
            args.extend(extra_args)
        return main(args)

    def _mock_llm(self):
        """OpenAICompatibleRewriteProvider.from_environment를 patch해 실제 LLM 호출 없이
        MockRewriteProvider(원본 그대로 반환)를 흘려보낸다."""
        return mock.patch.object(
            OpenAICompatibleRewriteProvider, "from_environment", return_value=MockRewriteProvider()
        )

    # --- 승인 KNOWLEDGE 정상 처리 + Threads 게시 성공 ------------------------------

    def test_approved_knowledge_end_to_end_success(self):
        self._write_knowledge([APPROVED_EXPERIENCE_RECORD])
        fake_client = ThreadsClient(access_token="fake-token", transport=_success_threads_transport("th_1"))

        with self._mock_llm(), mock.patch.object(ThreadsClient, "from_environment", return_value=fake_client):
            exit_code = self._run()

        self.assertEqual(exit_code, 0)
        self.assertTrue(self.output_path.exists(), "TAK MEDIA 배치 결과 파일이 생성되어야 합니다.")
        batch_data = json.loads(self.output_path.read_text(encoding="utf-8"))
        self.assertEqual(batch_data["summary"]["approved_knowledge_count"], 1)
        self.assertGreaterEqual(batch_data["summary"]["valid_count"], 1)

        history_records = PublishHistory(self.history_path).load()
        self.assertEqual(len(history_records), 1)
        self.assertEqual(history_records[0]["threads_post_id"], "th_1")

    # --- 승인 KNOWLEDGE 없음 → exit 0 --------------------------------------------

    def test_no_approved_knowledge_exits_zero(self):
        self._write_knowledge([_pending_record()])

        with self._mock_llm() as mocked_from_env:
            exit_code = self._run()

        self.assertEqual(exit_code, 0)
        mocked_from_env.assert_not_called()  # 승인 건이 없으면 LLM provider조차 만들지 않아야 함
        self.assertFalse(self.output_path.exists())
        self.assertFalse(self.history_path.exists())

    def test_empty_knowledge_list_exits_zero(self):
        self._write_knowledge([])

        exit_code = self._run()

        self.assertEqual(exit_code, 0)

    # --- KNOWLEDGE 파일 로드 실패 → exit 1 ----------------------------------------

    def test_missing_knowledge_file_exits_one(self):
        # self.knowledge_path를 쓰지 않음 -> 파일 없음
        exit_code = self._run()

        self.assertEqual(exit_code, 1)

    def test_corrupted_knowledge_file_exits_one(self):
        self.knowledge_path.write_text("{not valid json", encoding="utf-8")

        exit_code = self._run()

        self.assertEqual(exit_code, 1)

    # --- LLM 환경변수 설정 오류 → exit 1 ------------------------------------------

    def test_llm_configuration_error_exits_one(self):
        self._write_knowledge([APPROVED_EXPERIENCE_RECORD])

        with mock.patch.object(
            OpenAICompatibleRewriteProvider,
            "from_environment",
            side_effect=LLMConfigurationError("TAK_MEDIA_LLM_API_KEY 환경변수가 필요합니다."),
        ):
            exit_code = self._run()

        self.assertEqual(exit_code, 1)
        self.assertFalse(self.output_path.exists(), "LLM 설정 오류 시 배치 결과가 생성되면 안 됩니다.")

    # --- TAK MEDIA 실행 실패 → exit 1 --------------------------------------------

    def test_media_batch_execution_failure_exits_one(self):
        self._write_knowledge([APPROVED_EXPERIENCE_RECORD])

        with self._mock_llm(), mock.patch(
            "scripts.run_daily.run_media_batch", side_effect=RuntimeError("배치 실행 중 알 수 없는 오류")
        ):
            exit_code = self._run()

        self.assertEqual(exit_code, 1)
        self.assertFalse(self.output_path.exists())

    # --- 배치 JSON 저장 실패 → exit 1 --------------------------------------------

    def test_batch_save_failure_exits_one(self):
        self._write_knowledge([APPROVED_EXPERIENCE_RECORD])

        with self._mock_llm(), mock.patch.object(
            MediaBatchReport, "save_json", side_effect=OSError("디스크에 쓸 수 없습니다")
        ):
            exit_code = self._run()

        self.assertEqual(exit_code, 1)

    # --- Threads publish 실패 → exit 1, 이력 미기록 -------------------------------

    def test_threads_publish_failure_exits_one_and_records_no_history(self):
        self._write_knowledge([APPROVED_EXPERIENCE_RECORD])
        fake_client = ThreadsClient(access_token="fake-token", transport=_failure_threads_transport())

        with self._mock_llm(), mock.patch.object(ThreadsClient, "from_environment", return_value=fake_client):
            exit_code = self._run()

        self.assertEqual(exit_code, 1)
        self.assertFalse(self.history_path.exists())

    # --- 게시할 콘텐츠 없음(전부 이미 게시됨) → publish_threads가 0 반환 -> run_daily도 0 --

    def test_all_candidates_already_published_still_exits_zero(self):
        self._write_knowledge([APPROVED_EXPERIENCE_RECORD])

        # 1차 실행: 실제로 1건 게시 (모의 성공)
        fake_client_1 = ThreadsClient(access_token="fake-token", transport=_success_threads_transport("th_a"))
        with self._mock_llm(), mock.patch.object(ThreadsClient, "from_environment", return_value=fake_client_1):
            first_exit = self._run()
        self.assertEqual(first_exit, 0)
        first_history = PublishHistory(self.history_path).load()
        self.assertEqual(len(first_history), 1)

        # 2차 실행: publish_threads.main을 직접 mock해서 "선택할 후보가 있다면 즉시 게시 시도할
        # 것"이 아니라 자동 선정 로직 자체(1차 작업 구현)에 맡긴다. 같은 KNOWLEDGE는 Threads
        # 초안 5개를 만들므로 아직 4개가 남아있어 정상적으로는 다음 항목이 선택된다.
        fake_client_2 = ThreadsClient(access_token="fake-token", transport=_success_threads_transport("th_b"))
        with self._mock_llm(), mock.patch.object(ThreadsClient, "from_environment", return_value=fake_client_2):
            second_exit = self._run()
        self.assertEqual(second_exit, 0)
        second_history = PublishHistory(self.history_path).load()
        self.assertEqual(len(second_history), 2)
        # 서로 다른 content_id/게시물이어야 한다 (중복 게시 아님).
        self.assertNotEqual(first_history[0]["content_id"], second_history[1]["content_id"])
        self.assertNotEqual(second_history[1]["threads_post_id"], "th_a")

    def test_no_unpublished_candidate_left_exits_zero_without_calling_threads(self):
        self._write_knowledge([APPROVED_EXPERIENCE_RECORD])

        # 미리 이력을 채워 5개 Threads 후보를 전부 "이미 게시됨"으로 만든다.
        from content_engine.pipeline import run_media_batch
        from content_engine.publish_history import PublishRecord, compute_content_id
        from tak_brain import load_knowledge_records

        records = load_knowledge_records(self.knowledge_path)
        report = run_media_batch(records, provider=MockRewriteProvider())
        history = PublishHistory(self.history_path)
        for item in report.items:
            if item.platform == "threads" and item.status == "valid":
                history.append(
                    PublishRecord(
                        content_id=compute_content_id(item.to_dict()),
                        published_at="2026-09-13T00:00:00+00:00",
                        threads_post_id="already-posted",
                    )
                )

        with self._mock_llm(), mock.patch.object(ThreadsClient, "from_environment") as from_env:
            exit_code = self._run()

        from_env.assert_not_called()
        self.assertEqual(exit_code, 0)

    # --- publish_threads.main()에 --auto/--history/--input이 정확히 전달되는지 -----

    def test_publish_threads_main_receives_expected_argv(self):
        self._write_knowledge([APPROVED_EXPERIENCE_RECORD])

        with self._mock_llm(), mock.patch(
            "scripts.run_daily.publish_threads_main", return_value=0
        ) as mocked_publish:
            exit_code = self._run()

        self.assertEqual(exit_code, 0)
        mocked_publish.assert_called_once()
        (called_argv,), _ = mocked_publish.call_args
        self.assertIn("--auto", called_argv)
        self.assertIn("--history", called_argv)
        self.assertIn(str(self.history_path), called_argv)
        self.assertIn("--input", called_argv)
        self.assertIn(str(self.output_path), called_argv)
        self.assertNotIn("--dry-run", called_argv)

    def test_dry_run_flag_is_forwarded_to_publish_threads(self):
        self._write_knowledge([APPROVED_EXPERIENCE_RECORD])

        with self._mock_llm(), mock.patch(
            "scripts.run_daily.publish_threads_main", return_value=0
        ) as mocked_publish:
            exit_code = self._run(["--dry-run"])

        self.assertEqual(exit_code, 0)
        (called_argv,), _ = mocked_publish.call_args
        self.assertIn("--dry-run", called_argv)

    def test_dry_run_still_creates_real_provider_not_mock(self):
        """--dry-run이 provider를 조용히 Mock으로 바꾸면 안 된다는 요구사항을 검증한다.

        from_environment가 그대로 호출되는지(=운영 경로와 동일한 provider 생성 경로를 탄다는 것)
        를 확인한다. 여기서는 네트워크를 피하기 위해 from_environment 자체를 patch하지만,
        핵심은 run_daily.py가 dry-run이라는 이유로 이 호출을 건너뛰거나 MockRewriteProvider를
        직접 생성해 대체하지 않는다는 점이다.
        """
        self._write_knowledge([APPROVED_EXPERIENCE_RECORD])

        with self._mock_llm() as mocked_from_env, mock.patch(
            "scripts.run_daily.publish_threads_main", return_value=0
        ):
            self._run(["--dry-run"])

        mocked_from_env.assert_called_once()

    # --- --knowledge / --output / --history 옵션이 제대로 전달되는지 ----------------

    def test_custom_knowledge_output_history_paths_are_honored(self):
        custom_knowledge = self.tmp_path / "custom_knowledge.json"
        custom_output = self.tmp_path / "nested" / "custom_batch.json"
        custom_history = self.tmp_path / "nested" / "custom_history.json"
        custom_archive = self.tmp_path / "nested" / "custom_archive.json"
        custom_knowledge.write_text(json.dumps([APPROVED_EXPERIENCE_RECORD], ensure_ascii=False), encoding="utf-8")

        fake_client = ThreadsClient(access_token="fake-token", transport=_success_threads_transport("th_custom"))
        with self._mock_llm(), mock.patch.object(ThreadsClient, "from_environment", return_value=fake_client):
            exit_code = main(
                [
                    "--knowledge", str(custom_knowledge),
                    "--output", str(custom_output),
                    "--history", str(custom_history),
                    "--archive", str(custom_archive),
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertTrue(custom_output.exists())
        self.assertTrue(custom_history.exists())
        self.assertTrue(custom_archive.exists())

    # --- --limit / --id 전달 확인 (기존 run_media_batch.py와 동일한 의미) -----------

    def test_limit_option_restricts_number_of_approved_knowledge_processed(self):
        second_record = {**APPROVED_EXPERIENCE_RECORD, "id": "knowledge-second"}
        self._write_knowledge([APPROVED_EXPERIENCE_RECORD, second_record])

        with self._mock_llm(), mock.patch(
            "scripts.run_daily.publish_threads_main", return_value=0
        ):
            exit_code = self._run(["--limit", "1"])

        self.assertEqual(exit_code, 0)
        batch_data = json.loads(self.output_path.read_text(encoding="utf-8"))
        self.assertEqual(batch_data["summary"]["approved_knowledge_count"], 1)

    def test_id_option_selects_single_knowledge_and_missing_id_exits_one(self):
        self._write_knowledge([APPROVED_EXPERIENCE_RECORD])

        exit_code = self._run(["--id", "does-not-exist"])
        self.assertEqual(exit_code, 1)

        with self._mock_llm(), mock.patch(
            "scripts.run_daily.publish_threads_main", return_value=0
        ):
            exit_code = self._run(["--id", APPROVED_EXPERIENCE_RECORD["id"]])
        self.assertEqual(exit_code, 0)

    # --- 1차 작업의 publish history 기능과 충돌하지 않는지 -------------------------

    def test_two_sequential_runs_do_not_duplicate_publish_history(self):
        self._write_knowledge([APPROVED_EXPERIENCE_RECORD])

        for label, post_id in (("first", "th_seq_1"), ("second", "th_seq_2")):
            fake_client = ThreadsClient(access_token="fake-token", transport=_success_threads_transport(post_id))
            with self._mock_llm(), mock.patch.object(ThreadsClient, "from_environment", return_value=fake_client):
                exit_code = self._run()
            self.assertEqual(exit_code, 0, f"{label} 실행이 실패했습니다.")

        records = PublishHistory(self.history_path).load()
        self.assertEqual(len(records), 2)
        content_ids = [r["content_id"] for r in records]
        self.assertEqual(len(set(content_ids)), 2, "두 번의 실행이 같은 content_id를 중복 기록하면 안 됩니다.")
        post_ids = [r["threads_post_id"] for r in records]
        self.assertEqual(post_ids, ["th_seq_1", "th_seq_2"])


if __name__ == "__main__":
    unittest.main()

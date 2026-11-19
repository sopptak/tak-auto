from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stderr
from types import SimpleNamespace
from unittest.mock import patch
import zipfile

from content_engine.trend_data_backup import (
    ENCRYPTED_HEADER_BYTES,
    ENCRYPTED_MAGIC,
    BackupError,
    create_backup,
    restore_backup,
    verify_backup,
)
from content_engine import trend_data_backup
from scripts import backup_trend_factory_data as backup_cli


class TrendDataBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "data"
        self.source.mkdir()
        (self.source / "queue.json").write_text('[{"id":"queue-1"}]\n', encoding="utf-8")
        (self.source / "media_assets").mkdir()
        (self.source / "media_assets" / "approved.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42\x00media")
        (self.source / "social_oauth_tokens.enc").write_bytes(b"encrypted-token-fixture")
        self.archive = self.root / "backup.zip"

    def test_create_verify_and_restore_round_trip(self):
        manifest = create_backup(self.source, self.archive)
        self.assertEqual(len(manifest["files"]), 3)
        self.assertEqual(verify_backup(self.archive), manifest)
        restored = self.root / "restored-data"
        result = restore_backup(self.archive, restored)
        self.assertEqual(result, manifest)
        for relative in ("queue.json", "media_assets/approved.mp4", "social_oauth_tokens.enc"):
            self.assertEqual((restored / relative).read_bytes(), (self.source / relative).read_bytes())

    def test_encrypted_archive_verifies_and_restores_with_passphrase(self):
        passphrase = "correct horse battery staple"
        large_payload = os.urandom(2 * 1024 * 1024 + 137)
        (self.source / "large-random.bin").write_bytes(large_payload)
        manifest = create_backup(self.source, self.archive, passphrase=passphrase)
        encrypted = self.archive.read_bytes()
        self.assertTrue(encrypted.startswith(ENCRYPTED_MAGIC))
        self.assertNotEqual(encrypted[ENCRYPTED_HEADER_BYTES:ENCRYPTED_HEADER_BYTES + 4], b"PK\x03\x04")
        self.assertNotIn(b"encrypted-token-fixture", encrypted)
        self.assertNotIn(b"queue-1", encrypted)
        self.assertEqual(list(self.root.glob(".backup.zip.*")), [])
        with self.assertRaisesRegex(BackupError, "암호화되어 있습니다"):
            verify_backup(self.archive)
        self.assertEqual(verify_backup(self.archive, passphrase=passphrase), manifest)

        restored = self.root / "restored-encrypted-data"
        self.assertEqual(restore_backup(self.archive, restored, passphrase=passphrase), manifest)
        for relative in ("queue.json", "media_assets/approved.mp4", "social_oauth_tokens.enc", "large-random.bin"):
            self.assertEqual((restored / relative).read_bytes(), (self.source / relative).read_bytes())

    def test_encrypted_archive_rejects_wrong_passphrase_and_tampering(self):
        passphrase = "correct horse battery staple"
        create_backup(self.source, self.archive, passphrase=passphrase)
        with self.assertRaisesRegex(BackupError, "암호문구가 틀렸거나"):
            verify_backup(self.archive, passphrase="totally wrong passphrase")

        changed = bytearray(self.archive.read_bytes())
        changed[-20] ^= 0x01
        tampered = self.root / "tampered.takbak"
        tampered.write_bytes(changed)
        with self.assertRaisesRegex(BackupError, "암호문구가 틀렸거나"):
            restore_backup(tampered, self.root / "must-not-exist", passphrase=passphrase)
        self.assertFalse((self.root / "must-not-exist").exists())

    def test_encryption_requires_a_long_passphrase_and_leaves_no_archive(self):
        with self.assertRaisesRegex(BackupError, "16자 이상"):
            create_backup(self.source, self.archive, passphrase="too-short")
        self.assertFalse(self.archive.exists())
        self.assertEqual(list(self.root.glob(".backup.zip.*")), [])

    def test_create_rejects_source_changed_before_archive_write(self):
        original_digest = trend_data_backup._file_digest
        original_queue = '[{"id":"queue-1"}]\n'

        for label, passphrase in (
            ("plaintext", None),
            ("encrypted", "correct horse battery staple"),
        ):
            with self.subTest(mode=label):
                (self.source / "queue.json").write_text(original_queue, encoding="utf-8")
                archive = self.root / f"backup-{label}.zip"
                mutated = False

                def digest_then_change_source(path):
                    nonlocal mutated
                    result = original_digest(path)
                    if path.name == "queue.json" and not mutated:
                        mutated = True
                        path.write_text('[{"id":"changed"}]\n', encoding="utf-8")
                    return result

                with patch.object(trend_data_backup, "_file_digest", side_effect=digest_then_change_source):
                    with self.assertRaisesRegex(BackupError, "검증에 실패"):
                        create_backup(self.source, archive, passphrase=passphrase)

                self.assertTrue(mutated)
                self.assertFalse(archive.exists())
                self.assertEqual(list(self.root.glob(f".{archive.name}.*")), [])

    def test_create_rejects_new_source_file_added_during_backup(self):
        original_verify = trend_data_backup._verify_zip_archive
        for label, passphrase in (
            ("plaintext", None),
            ("encrypted", "correct horse battery staple"),
        ):
            with self.subTest(mode=label):
                archive = self.root / f"backup-new-file-{label}.zip"
                late_file = self.source / "late-added.json"

                def verify_then_add_file(path):
                    manifest = original_verify(path)
                    late_file.write_text('{"arrived":"during backup"}\n', encoding="utf-8")
                    return manifest

                with patch.object(
                    trend_data_backup, "_verify_zip_archive", side_effect=verify_then_add_file,
                ):
                    with self.assertRaisesRegex(BackupError, "파일 목록이 변경"):
                        create_backup(self.source, archive, passphrase=passphrase)

                self.assertFalse(archive.exists())
                self.assertEqual(list(self.root.glob(f".{archive.name}.*")), [])
                late_file.unlink()

    def test_create_refuses_to_overwrite_existing_archive(self):
        self.archive.write_bytes(b"keep this")
        with self.assertRaisesRegex(BackupError, "이미 있습니다"):
            create_backup(self.source, self.archive)
        self.assertEqual(self.archive.read_bytes(), b"keep this")

    def test_backup_must_be_outside_source_tree(self):
        with self.assertRaisesRegex(BackupError, "밖에 저장"):
            create_backup(self.source, self.source / "backup.zip")

    def test_symlink_is_rejected_instead_of_followed(self):
        link = self.source / "outside.json"
        try:
            link.symlink_to(self.root / "secret.json")
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation is unavailable")
        with self.assertRaisesRegex(BackupError, "심볼릭 링크"):
            create_backup(self.source, self.archive)

    def test_verify_rejects_changed_file_bytes(self):
        create_backup(self.source, self.archive)
        changed = self.root / "changed.zip"
        with zipfile.ZipFile(self.archive) as original, zipfile.ZipFile(changed, "w") as edited:
            for name in original.namelist():
                data = original.read(name)
                if name == "queue.json":
                    data += b"tampered"
                edited.writestr(original.getinfo(name), data)
        with self.assertRaisesRegex(BackupError, "queue.json"):
            verify_backup(changed)

    def test_verify_stops_when_file_exceeds_manifest_size(self):
        oversized = self.root / "oversized.takbak"
        payload = b"x" * (4 * 1024 * 1024)
        with zipfile.ZipFile(oversized, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            info = zipfile.ZipInfo("oversized.bin")
            info.external_attr = (0o100600 << 16)
            bundle.writestr(info, payload)
            bundle.writestr(trend_data_backup.MANIFEST_NAME, json.dumps({
                "format_version": 1,
                "files": [{
                    "path": "oversized.bin", "size": 0,
                    "sha256": hashlib.sha256(b"").hexdigest(),
                }],
            }))

        original_read = zipfile.ZipExtFile.read
        decompressed_sizes = []

        def track_payload_read(entry, size=-1):
            chunk = original_read(entry, size)
            if entry.name == "oversized.bin":
                decompressed_sizes.append(len(chunk))
            return chunk

        with patch.object(zipfile.ZipExtFile, "read", new=track_payload_read):
            with self.assertRaisesRegex(BackupError, "manifest 선언을 초과"):
                verify_backup(oversized)

        self.assertEqual(sum(decompressed_sizes), 1024 * 1024)

    def test_verify_rejects_path_traversal_manifest(self):
        malicious = self.root / "malicious.zip"
        payload = b"do not write outside"
        manifest = {"format_version": 1, "files": [{
            "path": "../outside.txt", "size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }]}
        with zipfile.ZipFile(malicious, "w") as bundle:
            bundle.writestr("../outside.txt", payload)
            bundle.writestr("tak-auto-backup-manifest.json", json.dumps(manifest))
        with self.assertRaisesRegex(BackupError, "경로가 올바르지"):
            verify_backup(malicious)
        self.assertFalse((self.root.parent / "outside.txt").exists())

    def test_verify_rejects_symlink_archive_entries(self):
        malicious = self.root / "symlink.zip"
        info = zipfile.ZipInfo("linked-file")
        info.create_system = 3
        info.external_attr = (0o120777 << 16)
        with zipfile.ZipFile(malicious, "w") as bundle:
            bundle.writestr(info, "../../outside.txt")
            bundle.writestr("tak-auto-backup-manifest.json", json.dumps({
                "format_version": 1,
                "files": [{"path": "linked-file", "size": 19,
                           "sha256": hashlib.sha256(b"../../outside.txt").hexdigest()}],
            }))
        with self.assertRaisesRegex(BackupError, "일반 파일이 아닌"):
            verify_backup(malicious)

    def test_restore_refuses_to_overwrite_existing_directory(self):
        create_backup(self.source, self.archive)
        destination = self.root / "existing"
        destination.mkdir()
        sentinel = destination / "keep.txt"
        sentinel.write_text("keep", encoding="utf-8")
        with self.assertRaisesRegex(BackupError, "덮어쓰지 않습니다"):
            restore_backup(self.archive, destination)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")

    def test_restore_refuses_destination_created_after_preflight(self):
        create_backup(self.source, self.archive)
        destination = self.root / "restored-data"
        original_rename = trend_data_backup._rename_directory_without_replacing

        def create_racing_destination(source, target):
            target.mkdir()
            return original_rename(source, target)

        with patch.object(
            trend_data_backup, "_rename_directory_without_replacing",
            side_effect=create_racing_destination,
        ):
            with self.assertRaisesRegex(BackupError, "이미 있습니다"):
                restore_backup(self.archive, destination)

        self.assertTrue(destination.is_dir())
        self.assertEqual(list(destination.iterdir()), [])
        self.assertEqual(list(self.root.glob(".restored-data.restore-*")), [])

    def test_restore_refuses_to_replace_a_broken_destination_symlink(self):
        create_backup(self.source, self.archive)
        destination = self.root / "restored-data"
        missing_target = self.root / "target-that-does-not-exist"
        try:
            destination.symlink_to(missing_target, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation is unavailable")

        with self.assertRaisesRegex(BackupError, "덮어쓰지 않습니다"):
            restore_backup(self.archive, destination)

        self.assertTrue(destination.is_symlink())
        self.assertEqual(destination.resolve(strict=False), missing_target.resolve(strict=False))

    def test_restore_checks_free_space_before_creating_staging_directory(self):
        create_backup(self.source, self.archive)
        destination = self.root / "restored-data"
        with patch.object(trend_data_backup.shutil, "disk_usage", return_value=SimpleNamespace(free=1)):
            with self.assertRaisesRegex(BackupError, "여유 공간이 부족합니다"):
                restore_backup(self.archive, destination)

        self.assertFalse(destination.exists())
        self.assertEqual(list(self.root.glob(".restored-data.restore-*")), [])

    def test_restore_reports_disk_space_query_failure_without_creating_destination(self):
        create_backup(self.source, self.archive)
        destination = self.root / "restored-data"
        with patch.object(trend_data_backup.shutil, "disk_usage", side_effect=OSError("unavailable")):
            with self.assertRaisesRegex(BackupError, "여유 공간을 확인하지 못했습니다"):
                restore_backup(self.archive, destination)

        self.assertFalse(destination.exists())
        self.assertEqual(list(self.root.glob(".restored-data.restore-*")), [])

    def test_backup_permissions_are_private_on_posix(self):
        create_backup(self.source, self.archive)
        if os.name == "posix":
            self.assertEqual(self.archive.stat().st_mode & 0o777, 0o600)

    def test_encrypted_backup_permissions_are_private_on_posix(self):
        create_backup(self.source, self.archive, passphrase="correct horse battery staple")
        if os.name == "posix":
            self.assertEqual(self.archive.stat().st_mode & 0o777, 0o600)


class TrendDataBackupCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "data"
        self.source.mkdir()
        (self.source / "queue.json").write_text('{"id":"queue-1"}\n', encoding="utf-8")
        self.archive = self.root / "backup.takbak"

    def test_create_requires_explicit_encryption_or_plaintext_choice(self):
        with self.assertRaises(SystemExit):
            backup_cli.build_parser().parse_args([
                "create", "--source", str(self.source), "--output", str(self.archive),
            ])

    def test_create_requires_an_explicit_data_source(self):
        with self.assertRaises(SystemExit):
            backup_cli.build_parser().parse_args([
                "create", "--output", str(self.archive), "--encrypt",
            ])

    def test_cli_prompts_securely_for_encryption_and_verification(self):
        passphrase = "correct horse battery staple"
        fake_stdin = type("FakeStdin", (), {"isatty": lambda self: True})()
        with patch.object(backup_cli.sys, "stdin", fake_stdin):
            with patch.object(backup_cli.getpass, "getpass", side_effect=[passphrase, passphrase]):
                self.assertEqual(backup_cli.main([
                    "create", "--source", str(self.source), "--output", str(self.archive), "--encrypt",
                ]), 0)
            with patch.object(backup_cli.getpass, "getpass", return_value=passphrase):
                self.assertEqual(backup_cli.main(["verify", "--archive", str(self.archive)]), 0)

            wrong_passphrase = "wrong horse battery staple"
            destination = self.root / "must-not-restore"
            errors = io.StringIO()
            with patch.object(backup_cli.getpass, "getpass", return_value=wrong_passphrase):
                with redirect_stderr(errors):
                    exit_code = backup_cli.main([
                        "restore", "--archive", str(self.archive), "--destination", str(destination),
                    ])
            self.assertEqual(exit_code, 2)
            self.assertFalse(destination.exists())
            self.assertNotIn(wrong_passphrase, errors.getvalue())

    def test_cli_prompt_cancellation_is_clean_and_creates_no_archive(self):
        fake_stdin = type("FakeStdin", (), {"isatty": lambda self: True})()
        args = [
            "create", "--source", str(self.source), "--output", str(self.archive), "--encrypt",
        ]
        for prompts, label in (
            ([EOFError()], "EOF at first prompt"),
            (["correct horse battery staple", KeyboardInterrupt()], "interrupt at confirmation"),
        ):
            with self.subTest(stage=label):
                errors = io.StringIO()
                with patch.object(backup_cli.sys, "stdin", fake_stdin):
                    with patch.object(backup_cli.getpass, "getpass", side_effect=prompts):
                        with redirect_stderr(errors):
                            exit_code = backup_cli.main(args)
                self.assertEqual(exit_code, 2)
                self.assertIn("암호문구 입력이 취소되었습니다", errors.getvalue())
                self.assertFalse(self.archive.exists())

    def test_encrypted_verify_prompt_cancellation_does_not_expose_traceback(self):
        create_backup(self.source, self.archive, passphrase="correct horse battery staple")
        fake_stdin = type("FakeStdin", (), {"isatty": lambda self: True})()
        errors = io.StringIO()
        with patch.object(backup_cli.sys, "stdin", fake_stdin):
            with patch.object(backup_cli.getpass, "getpass", side_effect=EOFError()):
                with redirect_stderr(errors):
                    exit_code = backup_cli.main(["verify", "--archive", str(self.archive)])
        self.assertEqual(exit_code, 2)
        self.assertIn("암호문구 입력이 취소되었습니다", errors.getvalue())
        self.assertNotIn("Traceback", errors.getvalue())
        self.assertTrue(self.archive.exists())

    def test_plaintext_requires_explicit_flag_and_remains_readable(self):
        self.assertEqual(backup_cli.main([
            "create", "--source", str(self.source), "--output", str(self.archive),
            "--allow-unencrypted",
        ]), 0)
        self.assertEqual(verify_backup(self.archive)["format_version"], 1)


if __name__ == "__main__":
    unittest.main()

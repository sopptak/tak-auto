#!/usr/bin/env python3
"""Back up, verify, and restore TAK AUTO trend-factory data locally."""
from __future__ import annotations

import argparse
import getpass
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_engine.trend_data_backup import (
    BackupError,
    create_backup,
    is_encrypted_backup,
    restore_backup,
    verify_backup,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create", help="create a new backup archive")
    create.add_argument(
        "--source",
        type=Path,
        required=True,
        help="explicit stopped or consistent data-directory copy to back up",
    )
    create.add_argument("--output", type=Path, required=True)
    encryption = create.add_mutually_exclusive_group(required=True)
    encryption.add_argument(
        "--encrypt", action="store_true", help="encrypt the archive with a passphrase prompt"
    )
    encryption.add_argument(
        "--allow-unencrypted", action="store_true", help="explicitly create a plaintext ZIP"
    )

    verify = commands.add_parser("verify", help="verify archive contents and checksums")
    verify.add_argument("--archive", type=Path, required=True)

    restore = commands.add_parser("restore", help="restore into a new, unused directory")
    restore.add_argument("--archive", type=Path, required=True)
    restore.add_argument("--destination", type=Path, required=True)
    return parser


def _prompt_passphrase(*, confirm: bool) -> str:
    if not sys.stdin.isatty():
        raise BackupError("암호문구는 보안 입력이 가능한 터미널에서 직접 입력해야 합니다.")

    def read_hidden(prompt: str) -> str:
        try:
            return getpass.getpass(prompt)
        except (EOFError, KeyboardInterrupt):
            raise BackupError("암호문구 입력이 취소되었습니다.") from None

    passphrase = read_hidden("백업 암호문구(최소 16자): ")
    if len(passphrase) < 16:
        raise BackupError("백업 암호문구는 16자 이상이어야 합니다.")
    if confirm and read_hidden("백업 암호문구를 다시 입력하세요: ") != passphrase:
        raise BackupError("암호문구가 일치하지 않습니다.")
    return passphrase


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "create":
            passphrase = _prompt_passphrase(confirm=True) if args.encrypt else None
            manifest = create_backup(args.source, args.output, passphrase=passphrase)
            encryption_status = "암호화" if args.encrypt else "평문"
            print(f"{encryption_status} 백업 생성 완료: {args.output} ({len(manifest['files'])}개 파일)")
        elif args.command == "verify":
            passphrase = _prompt_passphrase(confirm=False) if is_encrypted_backup(args.archive) else None
            manifest = verify_backup(args.archive, passphrase=passphrase)
            print(f"백업 검증 완료: {args.archive} ({len(manifest['files'])}개 파일)")
        else:
            passphrase = _prompt_passphrase(confirm=False) if is_encrypted_backup(args.archive) else None
            manifest = restore_backup(args.archive, args.destination, passphrase=passphrase)
            print(f"복구 완료: {args.destination} ({len(manifest['files'])}개 파일)")
        return 0
    except BackupError as error:
        print(f"오류: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

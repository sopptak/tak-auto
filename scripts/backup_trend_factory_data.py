#!/usr/bin/env python3
"""Back up, verify, and restore TAK AUTO trend-factory data locally."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_engine.trend_data_backup import BackupError, create_backup, restore_backup, verify_backup


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create", help="create a new backup archive")
    create.add_argument("--source", type=Path, default=Path(os.getenv("TAK_AUTO_DATA_DIR", "data")))
    create.add_argument("--output", type=Path, required=True)

    verify = commands.add_parser("verify", help="verify archive contents and checksums")
    verify.add_argument("--archive", type=Path, required=True)

    restore = commands.add_parser("restore", help="restore into a new, unused directory")
    restore.add_argument("--archive", type=Path, required=True)
    restore.add_argument("--destination", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "create":
            manifest = create_backup(args.source, args.output)
            print(f"백업 생성 완료: {args.output} ({len(manifest['files'])}개 파일)")
        elif args.command == "verify":
            manifest = verify_backup(args.archive)
            print(f"백업 검증 완료: {args.archive} ({len(manifest['files'])}개 파일)")
        else:
            manifest = restore_backup(args.archive, args.destination)
            print(f"복구 완료: {args.destination} ({len(manifest['files'])}개 파일)")
        return 0
    except BackupError as error:
        print(f"오류: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

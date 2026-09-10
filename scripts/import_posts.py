#!/usr/bin/env python3
"""input/의 게시물을 TAK BRAIN RAW 파일로 import합니다."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from blog_importer.pilot import import_directory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TAK BRAIN RAW 파일 import")
    parser.add_argument("--input", default=str(ROOT / "input"), help="JSON/Markdown 입력 디렉터리")
    parser.add_argument("--output", default=str(ROOT / "data" / "tak_brain_raw.json"), help="누적 RAW 출력 파일")
    args = parser.parse_args(argv)

    input_path = Path(args.input)
    if not input_path.is_dir():
        parser.error(f"입력 디렉터리가 없습니다: {input_path}")

    report = import_directory(input_path, args.output)
    print(f"총 글 수: {report.total_posts}")
    print(f"신규 글 수: {report.new_posts}")
    print(f"중복 글 수: {report.duplicate_posts}")
    print(f"검증 오류 수: {report.validation_errors}")
    print(f"개인정보 위험 수: {report.privacy_risks}")
    print(f"내부정보 위험 수: {report.internal_information_risks}")
    print(f"RAW 출력: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
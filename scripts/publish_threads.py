#!/usr/bin/env python3
"""TAK MEDIA 검증 완료된 Threads 콘텐츠를 Threads 공식 API로 단건 게시하는 CLI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_engine import (
    ThreadsAPIError,
    ThreadsClient,
    ThreadsConfigurationError,
)


def load_valid_threads_items(input_path: Path | str) -> list[dict]:
    path = Path(input_path)
    if not path.exists():
        raise FileNotFoundError(f"입력 파일을 찾을 수 없습니다: {path}")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        raise ValueError(f"유효하지 않은 JSON 파일입니다: {err}") from err

    all_items = data.get("all_items", [])
    valid_threads = [
        item for item in all_items
        if item.get("platform") == "threads" and item.get("status") == "valid"
    ]
    return valid_threads


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TAK MEDIA Threads Publisher (단건 게시)")
    parser.add_argument(
        "--input",
        type=Path,
        default=ROOT / "data" / "tak_media_batch_e2e_test.json",
        help="배치 결과 JSON 경로 (기본값: data/tak_media_batch_e2e_test.json)",
    )
    parser.add_argument(
        "--index",
        type=int,
        default=1,
        help="게시할 Threads 콘텐츠 번호 (1-based, 기본값: 1)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="실제 API 호출 없이 게시 예정 내용을 확인합니다.",
    )
    args = parser.parse_args(argv)

    try:
        valid_items = load_valid_threads_items(args.input)
    except (FileNotFoundError, ValueError) as err:
        print(f"오류: {err}", file=sys.stderr)
        return 1

    if not valid_items:
        print(f"알림: '{args.input}' 파일에 valid 상태의 Threads 콘텐츠가 없습니다.", file=sys.stderr)
        return 1

    if args.index < 1 or args.index > len(valid_items):
        print(
            f"오류: 유효하지 않은 index입니다. (입력: {args.index}, 선택 가능 범위: 1 ~ {len(valid_items)})",
            file=sys.stderr,
        )
        return 1

    target_item = valid_items[args.index - 1]
    publish_text = (target_item.get("rewritten_body") or target_item.get("original_body") or "").strip()

    if not publish_text:
        print("오류: 게시할 텍스트 본문이 비어 있습니다.", file=sys.stderr)
        return 1

    if len(publish_text) > 500:
        print(f"오류: Threads text exceeds 500 characters: {len(publish_text)}", file=sys.stderr)
        return 1

    knowledge_id = target_item.get("knowledge_id", "unknown")
    source_url = target_item.get("source_url", "unknown")

    if args.dry_run:
        print("=== TAK MEDIA Threads Publish (Dry-run) ===")
        print(f"대상 파일: {args.input}")
        print(f"선택 항목: [{args.index}/{len(valid_items)}] (KNOWLEDGE: {knowledge_id})")
        print(f"출처 URL: {source_url}")
        print("-" * 50)
        print("게시 예정 내용:")
        print(publish_text)
        print("-" * 50)
        print("네트워크 호출 없음. 실제 게시에는 --dry-run 없이 THREADS_ACCESS_TOKEN 환경변수가 필요합니다.")
        return 0

    try:
        client = ThreadsClient.from_environment()
        profile = client.get_profile()
        print(f"Threads 계정 확인 완료: @{profile.username} (ID: {profile.id})")
        print(f"게시 중: [{args.index}/{len(valid_items)}] KNOWLEDGE={knowledge_id}...")

        result = client.publish_text(publish_text)
        print(f"성공: Threads 게시 완료! (Post ID: {result.id})")
        return 0
    except ThreadsConfigurationError as err:
        print(f"설정 오류: {err}", file=sys.stderr)
        return 1
    except ThreadsAPIError as err:
        print(f"Threads API 오류: {err}", file=sys.stderr)
        return 1
    except ValueError as err:
        print(f"오류: {err}", file=sys.stderr)
        return 1
    except Exception as err:
        print(f"게시 실패: {type(err).__name__}: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

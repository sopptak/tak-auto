"""파일럿 import 실행과 누적 RAW 출력."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import tempfile
from typing import Any

from .loaders import load_file
from .models import BlogPost, ValidationError
from tak_brain.models import build_metadata


@dataclass
class PilotImportReport:
    total_posts: int = 0
    new_posts: int = 0
    duplicate_posts: int = 0
    validation_errors: int = 0
    privacy_risks: int = 0
    internal_information_risks: int = 0
    imported_posts: list[BlogPost] = field(default_factory=list)


def _read_existing(output_path: Path) -> tuple[set[str], set[str], list[dict[str, Any]]]:
    if not output_path.exists() or output_path.stat().st_size == 0:
        return set(), set(), []
    data = json.loads(output_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValidationError(f"RAW 출력 파일은 객체 목록이어야 합니다: {output_path}")
    hashes: set[str] = set()
    source_urls: set[str] = set()
    records: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            raise ValidationError(f"RAW 출력 레코드가 객체가 아닙니다: {output_path}")
        raw = item.get("raw", item)
        post = BlogPost.from_mapping(raw)
        hashes.add(post.content_hash)
        source_urls.add(post.source_url)
        records.append(item if "raw" in item else {"raw": post.to_dict(), "metadata": build_metadata(post)})
    return hashes, source_urls, records


def _write_output(output_path: Path, records: list[dict[str, Any]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=output_path.parent, delete=False) as handle:
        json.dump(records, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary_path = Path(handle.name)
    temporary_path.replace(output_path)


def import_directory(input_path: str | Path, output_path: str | Path) -> PilotImportReport:
    input_dir = Path(input_path)
    output_file = Path(output_path)
    existing_hashes, existing_urls, output_records = _read_existing(output_file)
    report = PilotImportReport()
    seen_hashes = set(existing_hashes)
    seen_urls = set(existing_urls)

    files = sorted(path for path in input_dir.rglob("*") if path.is_file() and path.suffix.lower() in {".json", ".md", ".markdown"})
    for file_path in files:
        try:
            posts = load_file(file_path)
        except (OSError, ValueError, ValidationError, json.JSONDecodeError):
            report.validation_errors += 1
            continue
        for post in posts:
            report.total_posts += 1
            metadata = build_metadata(post)
            report.privacy_risks += int(metadata["privacy_risk"])
            report.internal_information_risks += int(metadata["internal_information_risk"])
            if post.content_hash in seen_hashes or post.source_url in seen_urls:
                report.duplicate_posts += 1
                continue
            seen_hashes.add(post.content_hash)
            seen_urls.add(post.source_url)
            report.new_posts += 1
            report.imported_posts.append(post)
            output_records.append({"raw": post.to_dict(), "metadata": metadata})

    _write_output(output_file, output_records)
    return report


def append_posts(posts: list[BlogPost], output_path: str | Path) -> tuple[int, int]:
    """검증된 게시물을 누적 RAW 파일에 추가하고 신규/중복 수를 반환합니다."""
    output_file = Path(output_path)
    existing_hashes, existing_urls, output_records = _read_existing(output_file)
    new_count = 0
    duplicate_count = 0
    for post in posts:
        if post.content_hash in existing_hashes or post.source_url in existing_urls:
            duplicate_count += 1
            continue
        existing_hashes.add(post.content_hash)
        existing_urls.add(post.source_url)
        output_records.append({"raw": post.to_dict(), "metadata": build_metadata(post)})
        new_count += 1
    _write_output(output_file, output_records)
    return new_count, duplicate_count
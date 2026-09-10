"""JSON과 간단한 front matter Markdown 입력기."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import BlogPost, ValidationError


def _markdown_mapping(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    metadata: dict[str, Any] = {}
    body = text
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end < 0:
            raise ValidationError(f"Markdown front matter가 닫히지 않았습니다: {path}")
        front_matter = text[4:end]
        body = text[end + len("\n---"):].lstrip("\n")
        for line in front_matter.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            value = value.strip()
            if key.strip() == "tags":
                value = value.strip("[]")
                metadata[key.strip()] = [item.strip().strip("'\"") for item in value.split(",") if item.strip()]
            else:
                metadata[key.strip()] = value.strip("'\"")
    metadata["body"] = body
    return metadata


def load_file(path: str | Path) -> list[BlogPost]:
    file_path = Path(path)
    if file_path.suffix.lower() == ".json":
        data = json.loads(file_path.read_text(encoding="utf-8"))
        records = data if isinstance(data, list) else [data]
    elif file_path.suffix.lower() in {".md", ".markdown"}:
        records = [_markdown_mapping(file_path)]
    else:
        raise ValueError(f"지원하지 않는 파일 형식입니다: {file_path.suffix}")
    if not all(isinstance(record, dict) for record in records):
        raise ValidationError(f"각 입력 레코드는 객체여야 합니다: {file_path}")
    return [BlogPost.from_mapping(record) for record in records]


def load_paths(paths: list[str | Path]) -> list[BlogPost]:
    files = []
    for path in paths:
        candidate = Path(path)
        if candidate.is_file():
            files.append(candidate)
            continue
        files.extend(sorted(candidate.glob("*.json")))
        files.extend(sorted(candidate.glob("*.md")))
    return [post for file_path in files for post in load_file(file_path)]
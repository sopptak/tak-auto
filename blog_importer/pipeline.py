"""파일 입력을 중복 제거된 원본 목록으로 만드는 파이프라인."""

from dataclasses import dataclass
from pathlib import Path

from .loaders import load_paths
from .models import BlogPost


@dataclass(frozen=True)
class ImportResult:
    posts: tuple[BlogPost, ...]
    duplicate_count: int


def import_files(paths: list[str | Path]) -> ImportResult:
    unique: dict[str, BlogPost] = {}
    duplicate_count = 0
    for post in load_paths(paths):
        if post.content_hash in unique:
            duplicate_count += 1
            continue
        unique[post.content_hash] = post
    return ImportResult(tuple(unique.values()), duplicate_count)
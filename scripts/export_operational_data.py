#!/usr/bin/env python3
"""TAK AUTO 운영 데이터 Export Package 생성기(6-46) - SOURCE -> AUDIT -> EXPORT PACKAGE -> HASH MANIFEST.

운영 데이터를 가진 PC에서 실행해, 다른 PC로 옮길 파일만 별도 폴더에 복사하고 SHA-256 manifest를 만든다.
원본은 읽기만 한다(복사 전후 원본 해시가 같은지 확인). destination에 적용(APPLY)하지 않는다.
네트워크를 쓰지 않는다(YouTube/LLM API 호출 없음).

대상 경로는 ``scripts/audit_data_state.py``가 이미 정의한 "코드가 실제로 참조하는 경로"를 재사용하고,
그 목록에 없는 코드 참조 경로(성과/인터뷰/스카우트 보조 파일, 배치 스냅샷, migration 백업)를 더한다.

자격증명(.env, OAuth client JSON, token/credential 파일)은 절대 복사하지 않는다. 복사본 내용에서
secret 값 패턴이 발견되면 package를 지우고 중단한다(값은 출력하지 않고 파일명만 보고).

사용 예:
    py scripts/export_operational_data.py --output artifacts/6-46-operational-data-export
    py scripts/export_operational_data.py --dry-run
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_engine.data_state import CORRUPTED, EMPTY, NOT_PRESENT, VALID, json_file_status, text_file_status  # noqa: E402
from content_engine.media_archive import MediaArchiveError, load_archive  # noqa: E402
from scripts.audit_data_state import DIR_SPECS, FILE_SPECS, GENERATION_POOL_GLOB  # noqa: E402

# audit_data_state.py 목록 밖이지만 코드가 실제로 참조하는 운영 경로(grep으로 확인한 것만).
EXTRA_FILES = (
    "data/tak_performance.json",
    "data/tak_performance_insights.json",
    "data/tak_interview_answers.json",
    "data/tak_interview_sessions.json",
    "data/tak_interview_questions.json",
    "data/tak_interview_questions.md",
    "data/tak_scout_daily.md",
    "data/tak_scout_title_translations.json",
    "data/tak_scout_dashboard_skipped.json",
)
EXTRA_GLOBS = (
    ("data", "tak_media_batch_*.json"),          # 배치 스냅샷(run_media_batch --output)
    ("data", "youtube_publish_log.backup-*.json"),  # 6-43 migration before snapshot
    ("data/blog_drafts", "*"),
)
PRODUCTION_ARCHIVE = "data/tak_media_archive.json"
SHORTS_SCRIPTS_DIR = "data/shorts_scripts"
SHORTS_MP4_DIR = "data/shorts"
YOUTUBE_LOG = "data/youtube_publish_log.json"

# 파일 이름만으로 제외하는 자격증명류(내용과 무관하게 절대 복사 안 함)
_SECRET_NAME = re.compile(r"(^\.env)|client_secret|credential|token|oauth|\.pem$|\.p12$|\.key$", re.IGNORECASE)
# 복사본 내용에서 찾는 secret "값" 패턴(키 이름만 있는 문서/코드는 false positive라 값 형태로 판정)
_SECRET_VALUE = re.compile(
    r"GOCSPX-[A-Za-z0-9_-]{10,}|ya29\.[A-Za-z0-9_-]{20,}|1//0[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{35}"
    r"|sk-[A-Za-z0-9_-]{20,}|[0-9]{8,}-[a-z0-9]{20,}\.apps\.googleusercontent\.com"
    r'|"(client_secret|refresh_token|access_token|api_key)"\s*:\s*"[^"]{8,}"',
    re.IGNORECASE,
)


class ExportAborted(RuntimeError):
    """secret 발견 등으로 export를 중단했다(메시지에 값 없음)."""


@dataclass(frozen=True)
class Entry:
    relative_path: str
    category: str


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_status(path: Path) -> str:
    if not path.exists():
        return NOT_PRESENT
    if path.suffix == ".json":
        return json_file_status(path)[0]
    return text_file_status(path) if path.suffix in (".md", ".txt") else (VALID if path.stat().st_size else EMPTY)


def discover(root: Path) -> tuple[list[Entry], list[str]]:
    """(export 후보 파일 목록, 이름 때문에 제외한 자격증명류 파일 목록)."""
    seen: dict[str, Entry] = {}

    def add(rel: str, category: str) -> None:
        if rel not in seen:
            seen[rel] = Entry(rel, category)

    for spec in FILE_SPECS:
        add(spec.relative_path, spec.category)
    for rel in EXTRA_FILES:
        add(rel, "운영 보조 데이터(코드 참조)")
    for spec in DIR_SPECS:
        for path in sorted((root / spec.relative_path).glob(spec.glob)):
            add(path.relative_to(root).as_posix(), spec.category)
    for path in sorted((root / "data").glob(GENERATION_POOL_GLOB)):
        add(path.relative_to(root).as_posix(), "C/D: generation pool")
    for directory, pattern in EXTRA_GLOBS:
        for path in sorted((root / directory).glob(pattern)):
            if path.is_file():
                add(path.relative_to(root).as_posix(), "스냅샷/초안(코드 참조)")

    excluded = sorted(
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file() and _SECRET_NAME.search(p.name)
        and not any(part in (".git", "__pycache__", ".venv", "venv", "node_modules") for part in p.parts)
        and p.suffix != ".py"  # 소스 코드(예: youtube_oauth_setup.py)는 운영 데이터가 아니다
    )
    entries = [e for e in seen.values() if not _SECRET_NAME.search(Path(e.relative_path).name)]
    return entries, excluded


def analyze_lineage(root: Path) -> dict:
    """Production/pool/ShortsScript/MP4/YouTube 기록을 읽어 Shorts 후보와 lineage를 계산한다(읽기 전용)."""
    production_path = root / PRODUCTION_ARCHIVE
    result: dict = {"production_archive": file_status(production_path), "shorts_candidates": [],
                    "content_ids": [], "generation_ids": [], "knowledge_ids": [], "errors": []}
    records = []
    sources = [production_path, *sorted((root / "data").glob(GENERATION_POOL_GLOB))]
    for path in sources:
        if not path.exists():
            continue
        try:
            for record in load_archive(path):
                records.append((path.relative_to(root).as_posix(), record))
        except (MediaArchiveError, ValueError, OSError) as error:
            result["errors"].append(f"{path.relative_to(root).as_posix()}: {type(error).__name__}")
    youtube = {}
    log_path = root / YOUTUBE_LOG
    if json_file_status(log_path)[0] == VALID:
        for item in json.loads(log_path.read_text(encoding="utf-8")):
            if isinstance(item, dict) and item.get("content_id"):
                youtube[item["content_id"]] = item.get("video_id", "")
    result["content_ids"] = sorted({r.content_id for _, r in records})
    result["generation_ids"] = sorted({r.generation_id for _, r in records if r.generation_id})
    result["knowledge_ids"] = sorted({r.knowledge_id for _, r in records})
    for source, r in records:
        if source != PRODUCTION_ARCHIVE:
            continue  # 운영 후보는 Production Archive에 승격된 것만(pool의 approved는 아직 승격 전)
        if r.platform == "shorts" and r.generation_status == "valid" and r.review_status == "approved" and not r.superseded_by:
            script = root / SHORTS_SCRIPTS_DIR / f"{r.content_id}.json"
            mp4 = root / SHORTS_MP4_DIR / f"{r.content_id}.mp4"
            result["shorts_candidates"].append({
                "content_id": r.content_id, "knowledge_id": r.knowledge_id, "generation_id": r.generation_id or "",
                "shorts_script": script.relative_to(root).as_posix() if script.exists() else "",
                "mp4": mp4.relative_to(root).as_posix() if mp4.exists() else "",
                "youtube_video_id": youtube.get(r.content_id, ""),
            })
    return result


def build_package(root: Path, output: Path, *, dry_run: bool = False) -> dict:
    entries, excluded = discover(root)
    rows = []
    for entry in entries:
        path = root / entry.relative_path
        status = file_status(path)
        row = {"path": entry.relative_path, "category": entry.category, "status": status}
        if status != NOT_PRESENT:
            row.update(size=path.stat().st_size, sha256_source=sha256_of(path))
        rows.append(row)
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_root": str(root),
        "files": rows,
        "excluded_credential_files": excluded,
        "lineage": analyze_lineage(root),
        "network_calls": 0,
    }
    if dry_run:
        return manifest
    if output.exists() and any(output.iterdir()):
        raise ExportAborted(f"출력 폴더가 비어 있지 않습니다: {output} (덮어쓰지 않음)")
    try:
        for row in rows:
            if row["status"] == NOT_PRESENT:
                continue
            source = root / row["path"]
            target = output / row["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            row["sha256_package"] = sha256_of(target)
            if sha256_of(source) != row["sha256_source"]:
                raise ExportAborted(f"복사 중 원본이 바뀌었습니다: {row['path']}")
            if row["sha256_package"] != row["sha256_source"]:
                raise ExportAborted(f"복사본 해시가 원본과 다릅니다: {row['path']}")
            if _SECRET_VALUE.search(target.read_text(encoding="utf-8", errors="ignore")):
                raise ExportAborted(f"secret 값 패턴 발견으로 중단: {row['path']}")
        (output / "export_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    except ExportAborted:
        shutil.rmtree(output, ignore_errors=True)  # 부분 package를 남기지 않는다
        raise
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TAK AUTO 운영 데이터 Export Package(읽기 전용, 네트워크 없음)")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts" / "6-46-operational-data-export")
    parser.add_argument("--dry-run", action="store_true", help="복사하지 않고 감사/manifest만 출력")
    args = parser.parse_args(argv)
    try:
        manifest = build_package(args.root.resolve(), args.output, dry_run=args.dry_run)
    except ExportAborted as error:
        print(f"중단: {error}", file=sys.stderr)
        return 1
    present = [r for r in manifest["files"] if r["status"] != NOT_PRESENT]
    lineage = manifest["lineage"]
    print(f"대상 {len(manifest['files'])}개 경로 중 존재 {len(present)}개, 제외한 자격증명류 파일 {len(manifest['excluded_credential_files'])}개")
    for row in manifest["files"]:
        digest = row.get("sha256_source", "")[:16]
        print(f"  [{row['status']}] {row['path']} {row.get('size', '')} {digest}")
    print(f"Production Archive: {lineage['production_archive']} / Shorts 후보: {len(lineage['shorts_candidates'])}건 / content_id {len(lineage['content_ids'])}개")
    if CORRUPTED in {r["status"] for r in manifest["files"]}:
        print("주의: CORRUPTED 파일이 있습니다 - 그대로 복사했지만 destination에서 import하기 전에 원인을 확인하세요.")
    print("dry-run: 복사하지 않았습니다." if args.dry_run else f"package: {args.output} (export_manifest.json 포함)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

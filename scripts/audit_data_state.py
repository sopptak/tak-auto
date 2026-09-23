#!/usr/bin/env python3
"""운영 데이터 파일들의 현재 상태를 사람이 한눈에 확인할 수 있게 보여주는
읽기 전용(read-only) 감사 CLI(6-21, docs/6-21-data-sync-and-recovery-architecture.md).

이 스크립트는:
    - 어떤 파일도 생성/수정/삭제하지 않는다(디렉터리를 mkdir하지도 않는다).
    - 파일 내용을 절대 출력하지 않는다 - 존재 여부/크기/수정 시각/JSON 파싱
      가능 여부/최상위 record 개수/Git 추적 상태만 보여준다. API key/token/
      secret 값이 데이터 파일 안에 있더라도 이 스크립트가 그것을 읽어 화면에
      내보내는 일은 없다(값 자체를 로드하지 않고 구조만 검사한다).
    - Production Archive(``data/tak_media_archive.json``)가 없을 때 이를
      "EMPTY"(존재하지만 레코드가 0건)와 혼동하지 않고 "NOT_PRESENT"로 명확히
      구분해서 보여준다. ``content_engine.media_archive.load_archive()``는
      파일이 없든 비어 있든 똑같이 빈 목록을 반환하므로(그 함수 자체의 설계는
      바꾸지 않는다 - 기존 호출부가 "파일이 없어도 빈 목록으로 취급"하는 동작에
      의존하고 있다), 이 스크립트는 그 함수를 거치지 않고 파일 시스템을 직접
      검사해서 네 가지 상태(NOT_PRESENT/EMPTY/VALID/CORRUPTED)를 구분한다.

멀티 PC(노트북1/노트북2/Codespaces) 환경에서 "이 컴퓨터에 지금 어떤 운영
데이터가 있고, 그중 무엇이 Git에 커밋되어 있는가"를 작업 시작 전에 빠르게
확인하는 용도로 만들었다.

상태 판정 로직(NOT_PRESENT/EMPTY/VALID/CORRUPTED) 자체는 6-22에서
``content_engine/data_state.py``로 옮겨 이 스크립트와 Recovery Staging
(``content_engine/recovery_staging.py``, ``scripts/audit_recovery_source.py``)이
같은 구현을 공유한다 - 이 파일은 그 함수들을 그대로 재노출(re-export)한다.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content_engine.data_state import (  # noqa: E402
    CORRUPTED,
    EMPTY,
    NOT_PRESENT,
    VALID,
    dir_status as _dir_status,
    format_mtime as _format_mtime,
    json_file_status as _json_file_status,
    text_file_status as _text_file_status,
)

TRACKED = "TRACKED"
IGNORED = "IGNORED"
UNTRACKED = "UNTRACKED"


@dataclass(frozen=True)
class DataFileSpec:
    """감사 대상 파일 1건의 정적 메타데이터(경로/설명/분류)."""

    relative_path: str
    category: str
    note: str


@dataclass(frozen=True)
class DataDirSpec:
    """감사 대상 디렉터리 1건(JSON 파일이 여러 개 쌓이는 산출물)."""

    relative_path: str
    category: str
    note: str
    glob: str = "*"


# 6-21 조사 결과에 따른 분류(docs/6-21-data-sync-and-recovery-architecture.md
# 3장 표와 정확히 대응한다). 이 목록은 "현재 코드가 실제로 참조하는 경로"만
# 담는다 - 추측성 경로는 넣지 않았다.
FILE_SPECS: tuple[DataFileSpec, ...] = (
    DataFileSpec(
        "data/tak_media_archive.json",
        "A: Production Archive (source of truth)",
        "사람이 MEDIA Dashboard에서 승인한 review_status가 이 파일에만 있다. "
        ".gitignore가 !data/tak_media_archive.json으로 추적을 허용하지만 "
        "이 저장소 main 브랜치 어떤 커밋에도 아직 커밋된 적이 없다(6-20/6-21 확인).",
    ),
    DataFileSpec(
        "data/tak_brain_knowledge.json",
        "A: 운영 상태 (Git 추적)",
        "KNOWLEDGE 승인 상태. 모든 MEDIA 생성의 입력.",
    ),
    DataFileSpec(
        "data/tak_threads_pending.json",
        "A: 운영 상태 (Git 추적)",
        "Threads 검수 대기열. publish-approved-threads.yml이 읽고 쓴다.",
    ),
    DataFileSpec(
        "data/scout_sources.json",
        "A: 설정 (Git 추적)",
        "TAK SCOUT가 수집할 소스 목록. 사람이 직접 편집하는 설정 파일.",
    ),
    DataFileSpec(
        "data/tak_scout_daily.json",
        "A: 운영 상태 (Git 추적)",
        "daily-scout.yml이 매일 덮어쓰고 커밋한다.",
    ),
    DataFileSpec(
        "data/threads_publish_log.json",
        "E: publish history/audit (Git 추적)",
        "daily-threads-post.yml / publish-approved-threads.yml이 커밋한다. "
        "중복 게시 방지의 근거.",
    ),
    DataFileSpec(
        "data/youtube_publish_log.json",
        "E: publish history/audit (Git 추적)",
        "scripts/upload_youtube_short.py가 갱신한다. 중복 업로드 방지의 근거.",
    ),
    DataFileSpec(
        "data/blog_publish_log.json",
        "E: publish history/audit (Git 미추적 - !whitelist 없음)",
        "scripts/mark_blog_published.py가 갱신한다. threads/youtube 이력과 달리 "
        "현재 .gitignore 화이트리스트에 없어 PC/CI 간 동기화되지 않는다 - "
        "3장 '정책 불일치' 참고.",
    ),
    DataFileSpec(
        "data/tak_media_batch_e2e_test.json",
        "D: CLI 기본값/샘플 데이터 (Git 추적)",
        "scripts/publish_threads.py, scripts/view_media_batch.py의 --batch 기본값.",
    ),
    DataFileSpec(
        "data/blog_publish_pack_daily.md",
        "C: ephemeral 산출물 (Git 미추적)",
        "scripts/generate_blog_publish_pack.py가 매 실행마다 새로 생성. "
        "daily-media-prepare.yml에서 workflow artifact로만 보존(14일).",
    ),
)

DIR_SPECS: tuple[DataDirSpec, ...] = (
    DataDirSpec(
        "data/shorts_scripts",
        "A: 운영 상태 (Git 추적 대상, 개별 파일이 data/*.json 블랭킷 규칙 밖)",
        "ShortsScript JSON 1건당 1파일, content_id 기준 영구 산출물. "
        "daily-media-prepare.yml이 새로 생긴 파일만 commit/push한다.",
        glob="*.json",
    ),
    DataDirSpec(
        "data/shorts",
        "C: ephemeral 산출물 (렌더링된 mp4, 이 저장소 코드는 생성하지 않음)",
        "audit_publish_candidates.py가 참고용으로 존재 여부만 표시한다.",
        glob="*.mp4",
    ),
)

# data/tak_media_generation_*.json (generation pool)은 파일명이 고정되어 있지
# 않고(호출부가 --generation-pool로 임의 경로를 지정), .gitignore의
# data/*.json 블랭킷 규칙에 걸려 기본적으로 추적되지 않는다(승격 전 초안
# 저장소이므로 의도된 동작 - 4장 참고). 고정 경로가 없어 파일별 감사 대상
# 목록에는 넣지 않고, 대신 패턴 존재 여부만 별도로 보여준다.
GENERATION_POOL_GLOB = "tak_media_generation_*.json"


def _run_git(*args: str) -> tuple[int, str]:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return 1, ""
    return result.returncode, result.stdout.strip()


def _git_status_for(relative_path: str) -> str:
    code, out = _run_git("ls-files", "--error-unmatch", relative_path)
    if code == 0 and out:
        return TRACKED
    code, out = _run_git("check-ignore", relative_path)
    if code == 0:
        return IGNORED
    return UNTRACKED


def audit_file(spec: DataFileSpec) -> dict[str, object]:
    path = ROOT / spec.relative_path
    is_json = path.suffix == ".json"
    if is_json:
        status, record_count = _json_file_status(path)
    else:
        status, record_count = _text_file_status(path), None
    size = path.stat().st_size if path.exists() else None
    return {
        "path": spec.relative_path,
        "category": spec.category,
        "note": spec.note,
        "status": status,
        "record_count": record_count,
        "size_bytes": size,
        "mtime": _format_mtime(path),
        "git": _git_status_for(spec.relative_path),
    }


def audit_dir(spec: DataDirSpec) -> dict[str, object]:
    path = ROOT / spec.relative_path
    status, count = _dir_status(path, spec.glob)
    return {
        "path": spec.relative_path + "/",
        "category": spec.category,
        "note": spec.note,
        "status": status,
        "record_count": count,
        "size_bytes": None,
        "mtime": _format_mtime(path),
        "git": "N/A (directory)",
    }


def audit_generation_pool() -> dict[str, object]:
    matches = sorted((ROOT / "data").glob(GENERATION_POOL_GLOB))
    status = VALID if matches else NOT_PRESENT
    return {
        "path": f"data/{GENERATION_POOL_GLOB}",
        "category": "C/D: generation pool (Git 미추적, 의도된 동작)",
        "note": "승격(promote) 전 초안 저장소. 파일명이 호출부마다 달라 개별 감사 대상이 아니다.",
        "status": status,
        "record_count": len(matches) if matches else None,
        "size_bytes": None,
        "mtime": "-",
        "git": IGNORED if matches else "N/A",
    }


def _print_row(row: dict[str, object]) -> None:
    print(f"[{row['status']}] {row['path']}")
    print(f"    분류      : {row['category']}")
    if row.get("size_bytes") is not None:
        print(f"    크기      : {row['size_bytes']} bytes")
    if row.get("record_count") is not None:
        print(f"    최상위 개수: {row['record_count']}")
    print(f"    수정 시각  : {row['mtime']}")
    print(f"    Git 상태  : {row['git']}")
    print(f"    비고      : {row['note']}")
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "운영 데이터 파일/디렉터리의 존재 여부·크기·JSON 유효성·Git 추적 상태를 "
            "보여주는 읽기 전용 감사 CLI. 어떤 파일도 생성/수정하지 않는다."
        )
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="사람이 읽는 표 형식 대신 JSON으로 출력한다(자동화 스크립트에서 파싱용).",
    )
    args = parser.parse_args(argv)

    rows = [audit_file(spec) for spec in FILE_SPECS]
    rows += [audit_dir(spec) for spec in DIR_SPECS]
    rows.append(audit_generation_pool())

    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0

    print("=== TAK AUTO 운영 데이터 상태 감사 (읽기 전용) ===")
    print(f"저장소 루트: {ROOT}")
    print()
    for row in rows:
        _print_row(row)

    archive_row = rows[0]
    print("--- 요약 ---")
    print(f"Production Archive(data/tak_media_archive.json): {archive_row['status']}")
    if archive_row["status"] == NOT_PRESENT:
        print(
            "  -> 이 컴퓨터에는 아직 Production Archive가 없습니다. "
            "빈 archive를 만들어 정상 운영 상태처럼 보이게 하지 마세요."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

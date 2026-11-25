"""Atomic file replacement with bounded recovery from Windows sharing conflicts."""
from __future__ import annotations

from pathlib import Path
import time


def replace_file(source: Path, destination: Path) -> None:
    for attempt in range(6):
        try:
            source.replace(destination)
            return
        except PermissionError as error:
            if getattr(error, "winerror", None) not in (5, 32) or attempt == 5:
                raise
            time.sleep(0.01 * (attempt + 1))

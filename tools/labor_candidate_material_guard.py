#!/usr/bin/env python3
"""Reject raw business materials from an overseas-labor release candidate."""

from __future__ import annotations

import codecs
import sys
from pathlib import Path
from typing import Iterable, Sequence


APPROVED_BINARY_ASSETS = frozenset(
    {
        "bonus_platform/static/assets/bonus-logo-dark.png",
        "bonus_platform/static/assets/bonus-logo-header-blue.png",
        "bonus_platform/static/assets/overseas-labor-logo-2026.png",
        "bonus_platform/static/assets/workbench-logo-2026.png",
        "bonus_platform/static/assets/workbench-sigma-mark.png",
        "labor-worker-desktop/assets/overseas-labor-worker.icns",
        "labor-worker-desktop/assets/overseas-labor-worker.ico",
        "labor-worker-desktop/assets/overseas-labor-worker.png",
    }
)

RAW_MATERIAL_SUFFIXES = frozenset(
    {
        ".7z",
        ".avif",
        ".bmp",
        ".bz2",
        ".csv",
        ".doc",
        ".docx",
        ".eml",
        ".gif",
        ".gz",
        ".heic",
        ".heif",
        ".ico",
        ".icns",
        ".jfif",
        ".jp2",
        ".jpeg",
        ".jpg",
        ".jxl",
        ".msg",
        ".ods",
        ".odt",
        ".pdf",
        ".png",
        ".ppt",
        ".pptx",
        ".rar",
        ".rtf",
        ".svg",
        ".tar",
        ".tgz",
        ".tif",
        ".tiff",
        ".tsv",
        ".webp",
        ".xls",
        ".xlsb",
        ".xlsm",
        ".xlsx",
        ".xz",
        ".zip",
    }
)


def _looks_binary(path: Path) -> bool:
    with path.open("rb") as handle:
        raw_sample = handle.read(8193)
    sample = raw_sample[:8192]
    sample_was_truncated = len(raw_sample) > len(sample)
    if b"\x00" in sample:
        return True
    try:
        decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
        decoder.decode(sample, final=not sample_was_truncated)
    except UnicodeDecodeError:
        return True
    return False


def find_raw_material_paths(paths: Iterable[str], *, root: Path) -> list[str]:
    """Return existing candidate paths that look like raw business materials.

    Deleted paths are ignored so a release can remove leaked material. Approved
    product artwork is exact-path allowlisted; all other known material formats
    and unknown binary/symlink payloads fail closed.
    """

    root = root.resolve()
    violations: list[str] = []
    for raw_path in paths:
        relative_path = raw_path.strip().replace("\\", "/")
        if not relative_path:
            continue
        candidate = root / relative_path
        if not candidate.exists() and not candidate.is_symlink():
            continue
        try:
            candidate.resolve(strict=False).relative_to(root)
        except ValueError:
            violations.append(relative_path)
            continue
        if candidate.is_symlink():
            violations.append(relative_path)
            continue
        if relative_path in APPROVED_BINARY_ASSETS:
            continue
        if candidate.suffix.lower() in RAW_MATERIAL_SUFFIXES or (
            candidate.is_file() and _looks_binary(candidate)
        ):
            violations.append(relative_path)
    return violations


def main(argv: Sequence[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    root = Path(args[0]) if args else Path.cwd()
    changed_paths = [line.rstrip("\n") for line in sys.stdin]
    violations = find_raw_material_paths(changed_paths, root=root)
    if not violations:
        return 0
    print(
        "Overseas Labor candidate contains raw material files; "
        "commit only synthetic JSON/aggregate fixtures:",
        file=sys.stderr,
    )
    print("\n".join(violations), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

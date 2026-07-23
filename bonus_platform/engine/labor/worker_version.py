from __future__ import annotations

import re


_STABLE_VERSION = re.compile(r"^(0|[1-9]\d{0,2})\.(0|[1-9]\d{0,2})\.(0|[1-9]\d{0,2})$")


def parse_stable_worker_version(value: object) -> tuple[int, int, int]:
    """Parse the bounded stable version format accepted by both queue backends."""
    candidate = str(value or "").strip()
    match = _STABLE_VERSION.fullmatch(candidate)
    if not match:
        raise ValueError("Worker 版本必须是三段式稳定版本，例如 0.3.0。")
    return tuple(int(part) for part in match.groups())


def worker_version_code(value: object) -> int:
    major, minor, patch = parse_stable_worker_version(value)
    return major * 10**6 + minor * 10**3 + patch


def worker_version_at_least(current: object, required: object) -> bool:
    try:
        return parse_stable_worker_version(current) >= parse_stable_worker_version(required)
    except ValueError:
        return False

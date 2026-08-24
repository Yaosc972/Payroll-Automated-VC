from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import re
from typing import Any


ALLOWED_TEMPLATE_SUFFIXES = {".xls", ".xlsx"}
_DEFAULT_LIBRARY_PARTS = ("社保AI提效--测试资料", "社保增员表+批量增员数据")
_SUBJECT_ALIASES = (
    "易可达", "云途", "云颂", "云享", "云盟", "云岚", "闽行", "闽星",
)


def template_library_root() -> Path | None:
    configured = os.environ.get("SIGMA_SOCIAL_INSURANCE_TEMPLATE_LIBRARY_DIR")
    root = Path(configured).expanduser() if configured else Path.home().joinpath("Documents", *_DEFAULT_LIBRARY_PARTS)
    return root.resolve() if root.is_dir() else None


def _route_from_name(name: str) -> str:
    normalized = str(name or "")
    if "成都" in normalized:
        return "chengdu-medical" if "医保" in normalized else "chengdu-social"
    if "郑州" in normalized:
        return "zhengzhou-medical"
    if "武汉" in normalized:
        return "wuhan-medical"
    if "东莞" in normalized:
        return "dongguan-social"
    if "广州" in normalized:
        return "guangzhou-social"
    if any(marker in normalized for marker in ("杭州", "宁波", "义乌", "浙江")):
        return "zhejiang-social-medical"
    if "深圳" in normalized:
        return "shenzhen-social-medical"
    return ""


def _period_key(path: Path) -> str:
    for value in (path.parent.name, path.name):
        match = re.search(r"(?<!\d)(2\d{3}|20\d{4})(?!\d)", value)
        if match:
            token = match.group(1)
            return f"20{token}" if len(token) == 4 else token[:6]
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y%m")


def _subject_score(subject: str, filename: str) -> int:
    normalized_subject = re.sub(r"\s+", "", str(subject or ""))
    score = 0
    for alias in _SUBJECT_ALIASES:
        if alias in filename and alias in normalized_subject:
            score = max(score, len(alias) * 10)
    compact_name = re.sub(
        r"社保|医保|批量|人员|参保|登记|报盘|模板|增员|申报|信息表|大陆居民|职工|深圳|东莞|广州|成都|郑州|武汉|杭州|宁波|义乌|浙江|\W|\d",
        "",
        Path(filename).stem,
    )
    for size in range(min(6, len(compact_name)), 1, -1):
        if any(compact_name[index:index + size] in normalized_subject for index in range(len(compact_name) - size + 1)):
            score = max(score, size)
            break
    return score


def list_template_library() -> list[dict[str, Any]]:
    root = template_library_root()
    paths: list[Path] = []
    configured_shenzhen = os.environ.get("SIGMA_SOCIAL_INSURANCE_TEMPLATE_FILE")
    if configured_shenzhen:
        configured_path = Path(configured_shenzhen).expanduser()
        if configured_path.is_file():
            paths.append(configured_path.resolve())
    if root is not None:
        paths.extend(path.resolve() for path in root.rglob("*") if path.is_file())
    output: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        if not path.is_file() or path.suffix.lower() not in ALLOWED_TEMPLATE_SUFFIXES:
            continue
        if path.name.startswith("~$") or "员工社保报表" in path.name:
            continue
        route = _route_from_name(path.name)
        if not route and configured_shenzhen and path == Path(configured_shenzhen).expanduser().resolve():
            route = "shenzhen-social-medical"
        if not route:
            continue
        output.append({
            "route": route,
            "filename": path.name,
            "period": _period_key(path),
            "size": path.stat().st_size,
            "path": path,
            "configured": bool(
                configured_shenzhen
                and path == Path(configured_shenzhen).expanduser().resolve()
            ),
        })
    return sorted(output, key=lambda item: (item["route"], item["period"], item["filename"]), reverse=True)


def match_template(route: str, subject: str) -> dict[str, Any] | None:
    candidates = [item for item in list_template_library() if item["route"] == route]
    if not candidates:
        return None
    ranked = sorted(
        candidates,
        key=lambda item: (_subject_score(subject, item["filename"]), item["period"], item["filename"]),
        reverse=True,
    )
    selected = ranked[0]
    score = _subject_score(subject, selected["filename"])
    configured = bool(selected.get("configured"))
    return {
        **selected,
        "matchQuality": "configured" if configured else ("subject" if score > 0 else "route-only"),
        "subjectMatched": configured or score > 0,
    }


def public_template_match(route: str, subject: str) -> dict[str, Any] | None:
    matched = match_template(route, subject)
    if matched is None:
        return None
    return {key: value for key, value in matched.items() if key != "path"}

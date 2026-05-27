from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from pathlib import Path
from typing import List


@dataclass(frozen=True)
class SupplierExtractionProfile:
    key: str
    aliases: List[str] = field(default_factory=list)
    prompt_notes: List[str] = field(default_factory=list)
    image_page_policy: str = "all"


DEFAULT_PROFILE = SupplierExtractionProfile(key="default")


BUILTIN_PROFILES = [
    SupplierExtractionProfile(
        key="onesource",
        aliases=["onesource", "one source", "one source staffing"],
        prompt_notes=[
            "ONESOURCE invoices may include separate timecard/detail pages after the amount invoice page.",
            "For ONESOURCE, only extract rows from pages that include charge amount columns or visible invoice totals.",
            "Ignore pages that only show working hours, overtime notes, handwritten RG/OT calculations, or no currency amounts.",
        ],
        image_page_policy="first_page_only",
    )
]


def resolve_supplier_profile(supplier: str, profiles_path: str | Path | None = None) -> SupplierExtractionProfile:
    normalized = _normalize_supplier(supplier)
    for profile in _profiles_for_resolution(profiles_path):
        if any(alias in normalized for alias in profile.aliases):
            return profile
    return DEFAULT_PROFILE


def _profiles_for_resolution(profiles_path: str | Path | None) -> List[SupplierExtractionProfile]:
    profiles: List[SupplierExtractionProfile] = []
    if profiles_path:
        try:
            profiles.extend(load_supplier_profiles(profiles_path))
        except (OSError, ValueError, json.JSONDecodeError):
            pass
    profiles.extend(BUILTIN_PROFILES)
    return profiles


def load_supplier_profiles(path: str | Path) -> List[SupplierExtractionProfile]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("供应商抽取 Profile 配置必须是数组。")
    profiles: List[SupplierExtractionProfile] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        if not key:
            continue
        profiles.append(
            SupplierExtractionProfile(
                key=key,
                aliases=[str(alias) for alias in item.get("aliases", []) if str(alias).strip()],
                prompt_notes=[str(note) for note in item.get("prompt_notes", []) if str(note).strip()],
                image_page_policy=str(item.get("image_page_policy") or "all"),
            )
        )
    return profiles


def _normalize_supplier(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", str(value or "").lower())
    return re.sub(r"\s+", " ", text).strip()

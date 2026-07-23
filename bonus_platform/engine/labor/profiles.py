from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
import logging
import re
from pathlib import Path
from typing import Dict, List

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SupplierExtractionProfile:
    key: str
    aliases: List[str] = field(default_factory=list)
    prompt_notes: List[str] = field(default_factory=list)
    authoritative_total_methods: List[str] = field(default_factory=list)
    line_item_aliases: Dict[str, str] = field(default_factory=dict)
    image_page_policy: str = "first_page_only"
    version: int = 1
    failure_count: int = 0
    deprecated: bool = False
    status: str = "builtin"
    approved_by: str = ""
    approved_at: str = ""
    created_from: str = "builtin"


DEFAULT_PROFILE = SupplierExtractionProfile(key="default", image_page_policy="all")


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
    ),
    SupplierExtractionProfile(
        key="fairway",
        aliases=["fairway", "fairway staffing", "fairway staffing service"],
        prompt_notes=[
            "FAIRWAY invoices typically include employee charge rows on the first billing page.",
            "Extract all charge rows including meal premiums even if hours are zero.",
            "Look for rows with amounts in the TOTAL column.",
            "Ignore timecard detail pages and pages without charge amount columns.",
        ],
        image_page_policy="first_page_only",
    ),
    SupplierExtractionProfile(
        key="prompt",
        aliases=["prompt", "prompt priority", "prompt priority inc", "china express"],
        prompt_notes=[
            "PROMPT Priority invoices may be scanned image PDFs named with DEPT# or CHINA EXPRESS warehouse identifiers.",
            "Extract the warehouse_id from DEPT#/CHINA EXPRESS filename or visible DEPT field and keep only the numeric part.",
            "Only extract employee billing rows with charge amounts; ignore summary/header/footer text and rows without payable amounts.",
        ],
        image_page_policy="all",
    ),
    SupplierExtractionProfile(
        key="citistaff",
        aliases=["citistaff", "citi staff", "citistaff solutions"],
        prompt_notes=[
            "CitiStaff invoices may use US Elogistics Service Corp pages with LOC.# warehouse identifiers.",
            "Extract warehouse_id from LOC.# or invoice number context when visible.",
            "Employee names can appear as Last, First on PDF and First Last in the workbook; propose name mappings as candidates before clearing differences.",
        ],
        image_page_policy="all",
    ),
    SupplierExtractionProfile(
        key="osi",
        aliases=["osi", "osi staffing", "osi staffing inc"],
        prompt_notes=[
            "OSI invoices use a vertical format with Date, Description, Hours, Pay Code, Type, Pay Rate, Bill Rate, Amount columns.",
            "Each employee may have multiple rows for different pay codes (Reg, OT, DT).",
            "Sum hours and amounts for the same employee across all rows.",
        ],
        image_page_policy="first_page_only",
    ),
    SupplierExtractionProfile(
        key="adecco",
        aliases=["adecco", "adecco staffing"],
        prompt_notes=[
            "ADECCO invoices may use various formats depending on the region.",
            "Look for employee names followed by hours and amounts.",
            "Handle both horizontal and vertical layouts.",
        ],
        image_page_policy="first_page_only",
    ),
    SupplierExtractionProfile(
        key="randstad",
        aliases=["randstad", "randstad staffing"],
        prompt_notes=[
            "RANDSTAD invoices typically include employee ID, name, hours, and amounts.",
            "Extract rows from the main billing table.",
            "Ignore summary rows and totals.",
        ],
        image_page_policy="first_page_only",
    ),
    SupplierExtractionProfile(
        key="manpower",
        aliases=["manpower", "manpower group"],
        prompt_notes=[
            "MANPOWER invoices may include multiple line items per employee.",
            "Sum hours and amounts for the same employee.",
            "Look for the main billing section, not timecard details.",
        ],
        image_page_policy="first_page_only",
    ),
]


def resolve_supplier_profile(supplier: str, profiles_path: str | Path | None = None) -> SupplierExtractionProfile:
    normalized = _normalize_supplier(supplier)
    matches: list[tuple[tuple[int, int], SupplierExtractionProfile]] = []
    for profile in _profiles_for_resolution(profiles_path):
        for raw_alias in profile.aliases:
            alias = _normalize_supplier(raw_alias)
            score = supplier_alias_match_score(normalized, alias)
            if score is None:
                continue
            matches.append((score, profile))
    if matches:
        best_score = max(score for score, _profile in matches)
        best_matches = [profile for score, profile in matches if score == best_score]
        external_matches = [profile for profile in best_matches if profile.status != "builtin"]
        best_profiles = {profile.key: profile for profile in (external_matches or best_matches)}
        if len(best_profiles) == 1:
            return next(iter(best_profiles.values()))
        logger.warning(
            "供应商 Profile 匹配冲突，已回退默认 Profile: supplier=%s, profiles=%s",
            supplier,
            sorted(best_profiles),
        )
    return DEFAULT_PROFILE


def _supplier_alias_matches(normalized_supplier: str, normalized_alias: str) -> bool:
    supplier_tokens = normalized_supplier.split()
    alias_tokens = normalized_alias.split()
    if not supplier_tokens or not alias_tokens or len(alias_tokens) > len(supplier_tokens):
        return False
    width = len(alias_tokens)
    return any(
        supplier_tokens[index : index + width] == alias_tokens
        for index in range(len(supplier_tokens) - width + 1)
    )


def supplier_alias_match_score(supplier: str, alias: str) -> tuple[int, int] | None:
    normalized_supplier = _normalize_supplier(supplier)
    normalized_alias = _normalize_supplier(alias)
    if not normalized_alias or not _supplier_alias_matches(normalized_supplier, normalized_alias):
        return None
    return len(normalized_alias.split()), len(normalized_alias)


def _profiles_for_resolution(profiles_path: str | Path | None) -> List[SupplierExtractionProfile]:
    profiles: List[SupplierExtractionProfile] = []
    if profiles_path:
        path = Path(profiles_path)
        try:
            if path.is_dir():
                # 目录模式：扫描目录下所有 .json 文件
                for json_file in sorted(path.glob("*.json")):
                    try:
                        profiles.extend(load_supplier_profiles(json_file))
                    except (OSError, ValueError, json.JSONDecodeError) as exc:
                        logger.warning(f"供应商 Profile 文件加载失败，跳过: {json_file}, error={exc}")
            elif path.is_file():
                # 文件模式：原有逻辑
                profiles.extend(load_supplier_profiles(path))
            else:
                # 路径不存在，记录 warning 并跳过
                logger.warning(f"供应商 Profile 路径不存在，使用内置 Profile: {profiles_path}")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            logger.warning(f"供应商 Profile 加载失败，使用内置 Profile: {profiles_path}, error={exc}")
    # External Profiles are runtime configuration. Missing or incomplete
    # approval metadata must fail closed instead of silently becoming active.
    profiles = [profile for profile in profiles if is_runtime_approved_profile(profile)]
    profiles.extend(BUILTIN_PROFILES)
    return profiles


def load_supplier_profiles(path: str | Path) -> List[SupplierExtractionProfile]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        raise ValueError("供应商抽取 Profile 配置必须是数组或对象。")
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
                authoritative_total_methods=[str(method) for method in item.get("authoritative_total_methods", []) if str(method).strip()],
                line_item_aliases={
                    str(label).strip().lower(): str(item_type).strip()
                    for label, item_type in (item.get("line_item_aliases") or {}).items()
                    if str(label).strip() and str(item_type).strip()
                },
                image_page_policy=str(item.get("image_page_policy") or "all"),
                version=_profile_version(item.get("version")),
                failure_count=int(item.get("failure_count") or 0),
                deprecated=bool(item.get("deprecated", False)),
                status=str(item.get("status") or "draft").strip().lower(),
                approved_by=str(item.get("approvedBy") or item.get("approved_by") or "").strip(),
                approved_at=str(item.get("approvedAt") or item.get("approved_at") or "").strip(),
                created_from=str(item.get("created_from") or "").strip(),
            )
        )
    return profiles


def _profile_version(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def is_runtime_approved_profile(profile: SupplierExtractionProfile) -> bool:
    return bool(
        not profile.deprecated
        and profile.status == "approved"
        and profile.version > 0
        and profile.approved_by
        and _is_timezone_aware_iso_timestamp(profile.approved_at)
    )


def _is_timezone_aware_iso_timestamp(value: str) -> bool:
    candidate = str(value or "").strip()
    if not candidate:
        return False
    try:
        parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _normalize_supplier(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", str(value or "").lower())
    return re.sub(r"\s+", " ", text).strip()


def generate_profile_from_extraction(
    supplier: str,
    pdf_rows: list,
    pages_used: list | None = None,
    layout_info: dict | None = None,
    extraction_quality_level: str = "ok",
) -> dict:
    """从 AI 抽取结果自动生成供应商 Profile。

    分析抽取结果推断 image_page_policy、prompt_notes 等配置，
    供下次同供应商复用，减少 AI 调用。

    Args:
        supplier: 供应商名称
        pdf_rows: LaborLineItem 列表（抽取结果）
        pages_used: 实际使用的页面列表（来自智能筛选）
        layout_info: 布局分析信息（可选）
        extraction_quality_level: 抽取质量级别，critical 时不生成

    Returns:
        Profile 字典，可直接序列化为 JSON
    """
    key = _normalize_supplier(supplier)
    if not key:
        key = "unknown"

    # 推断 image_page_policy
    if pages_used and len(pages_used) > 0:
        # 有页面筛选信息：如果筛选后页数少于原始，说明只用首页
        total_pages = layout_info.get("total_pages") if layout_info else None
        if total_pages and len(pages_used) < total_pages:
            image_page_policy = "first_page_only"
        else:
            image_page_policy = "all"
    else:
        # 无页面信息，默认读全部页（更安全，避免漏掉多页格式的员工数据）
        image_page_policy = "all"

    # 从行特征推断 prompt_notes
    prompt_notes = []
    if pdf_rows:
        zero_hours_with_amount = sum(1 for r in pdf_rows if r.hours == 0 and r.amount > 0)
        if zero_hours_with_amount > 0:
            prompt_notes.append("Extract all charge rows including meal premiums even if hours are zero.")

        has_warehouse = any(getattr(r, 'warehouse_id', '') for r in pdf_rows)
        if has_warehouse:
            prompt_notes.append("Invoice includes warehouse/dept identifiers — extract warehouse_id from DEPT codes.")

        # 姓名模式分析
        names = [r.employee_name_raw for r in pdf_rows if r.employee_name_raw]
        has_chinese = any(any('一' <= c <= '鿿' for c in name) for name in names)
        has_english = any(any(c.isalpha() and ord(c) < 128 for c in name) for name in names)
        if has_chinese and has_english:
            prompt_notes.append("Names may include mixed Chinese and English characters.")

    profile = {
        "key": key,
        "aliases": [supplier.lower().strip()] if supplier else [],
        "prompt_notes": prompt_notes,
        "authoritative_total_methods": [],
        "line_item_aliases": _line_item_aliases(pdf_rows),
        "image_page_policy": image_page_policy,
        "version": 1,
        "created_from": "auto_generation",
        "status": "draft",
        "extraction_quality_level": extraction_quality_level,
    }

    # 如果有布局信息，记录列映射
    if layout_info and isinstance(layout_info, dict):
        column_mapping = layout_info.get("column_mapping") or layout_info.get("columns")
        if column_mapping:
            profile["column_mapping"] = column_mapping

    return profile


def _line_item_aliases(pdf_rows: list) -> Dict[str, str]:
    """Build a reviewable label map; callers still govern whether it becomes active."""
    aliases: Dict[str, str] = {}
    conflicts: set[str] = set()
    for row in pdf_rows or []:
        description = " ".join(str(getattr(row, "description", "") or "").lower().split())
        item_type = str(getattr(row, "item_type", "") or "").strip()
        if not description or item_type in {"", "unknown"}:
            continue
        if description in aliases and aliases[description] != item_type:
            conflicts.add(description)
            continue
        aliases[description] = item_type
    for description in conflicts:
        aliases.pop(description, None)
    return dict(sorted(aliases.items()))


def save_supplier_profile(profile: dict, output_dir: Path) -> Path:
    """保存自动生成的 Profile JSON 到指定目录。

    Args:
        profile: generate_profile_from_extraction 的返回值
        output_dir: 输出目录（通常是 run_dir / "profiles"）

    Returns:
        保存的文件路径
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    key = profile.get("key") or "unknown"
    # 文件名安全处理
    safe_key = re.sub(r"[^a-z0-9_-]", "_", key.lower())
    file_path = output_dir / f"{safe_key}.json"
    file_path.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"供应商 Profile 已保存: {file_path}")
    return file_path


def record_profile_failure(profile_path: Path) -> dict | None:
    """记录 Profile 失效事件，增加 failure_count。

    连续失败 3 次后标记为 deprecated，下次 resolve 时将跳过。

    Args:
        profile_path: Profile JSON 文件路径

    Returns:
        更新后的 Profile 字典，失败时返回 None
    """
    try:
        data = json.loads(profile_path.read_text(encoding="utf-8"))
        current_count = int(data.get("failure_count") or 0)
        data["failure_count"] = current_count + 1
        if data["failure_count"] >= 3:
            data["deprecated"] = True
            logger.warning(f"Profile '{data.get('key')}' 连续失败 {data['failure_count']} 次，已标记为 deprecated")
        profile_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info(f"Profile 失效记录已更新: {profile_path.name}, failure_count={data['failure_count']}")
        return data
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        logger.warning(f"Profile 失效记录更新失败: {profile_path}, error={exc}")
        return None


def reset_profile_failure(profile_path: Path) -> None:
    """重置 Profile 失效计数（抽取成功时调用）。

    Args:
        profile_path: Profile JSON 文件路径
    """
    try:
        data = json.loads(profile_path.read_text(encoding="utf-8"))
        if data.get("failure_count") or data.get("deprecated"):
            data["failure_count"] = 0
            data.pop("deprecated", None)
            profile_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            logger.info(f"Profile 失效计数已重置: {profile_path.name}")
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(f"Profile 失效计数重置失败: {profile_path}, error={exc}")

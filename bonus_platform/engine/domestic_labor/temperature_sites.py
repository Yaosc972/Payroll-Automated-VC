"""Batch-scoped temperature site matching; candidates are not a business master list."""
from __future__ import annotations

from collections import Counter
import re
import unicodedata

from .engines.gaowen_butie import (
    CHASHAN_SITE, FENGGANG_SITE, JIASHAN_SITE, JINJIANG_SITE,
    LIAOBU_SITE, QINGXI_SITE, YIWU_SITE,
)


TEMPERATURE_SITE_CANDIDATES = (
    LIAOBU_SITE, FENGGANG_SITE, CHASHAN_SITE, QINGXI_SITE,
    JIASHAN_SITE, YIWU_SITE, JINJIANG_SITE,
)


def normalize_temperature_site(value) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    # Formatting only: never infer aliases by removing words such as 仓/枢纽.
    return re.sub(r"\s+", "", text).translate(str.maketrans({"–": "-", "—": "-", "−": "-"}))


def validate_temperature_site_mapping(mapping) -> dict:
    if not isinstance(mapping, dict) or len(mapping) > 200:
        raise ValueError("网点名称对照格式错误")
    result = {}
    for source, target in mapping.items():
        if not isinstance(source, str) or not isinstance(target, str) or max(len(source), len(target)) > 200:
            raise ValueError("网点名称对照格式错误")
        key, value = normalize_temperature_site(source), normalize_temperature_site(target)
        if not key or not value or (key in result and result[key] != value):
            raise ValueError("网点名称对照存在空名称或冲突")
        result[key] = value
    if any(target in result and result[target] != target for target in result.values()):
        raise ValueError("网点名称对照须直接指向最终名称，不能循环或连续转写")
    return result


class TemperatureSiteConfirmationRequired(ValueError):
    def __init__(self, records, candidates):
        super().__init__("发现无法对应的网点名称，请确认本次核算的名称对照，或返回文件补充一致的测温网点。")
        self.detail = {
            "code": "temperature_site_confirmation_required",
            "message": str(self), "records": records, "candidate_sites": candidates,
        }


def prepare_temperature_sites(loader, mapping=None) -> dict:
    """Accept custom names shared by attendance and measurements; gate unmatched names.

    Mutate only this loader after every match is validated, and retain source names
    for audit. No shared alias registry or payroll rate is changed.
    """
    mapping = validate_temperature_site_mapping(mapping if mapping is not None else {})
    daily = loader.daily.rows if loader.daily else []
    measurements = loader.temperature.rows if loader.temperature else []
    groups = {"日考勤": daily, "测温登记": measurements}
    counts = {label: Counter(str(row.get("测温网点") or "").strip() for row in rows
                            if str(row.get("测温网点") or "").strip())
              for label, rows in groups.items()}
    source_names = {normalize_temperature_site(name) for count in counts.values() for name in count}
    candidates = set(TEMPERATURE_SITE_CANDIDATES) | source_names
    if any(source not in source_names or target not in candidates for source, target in mapping.items()):
        raise ValueError("网点名称对照必须使用本次上传名称或程序匹配候选名称")

    def mapped(name):
        name = normalize_temperature_site(name)
        return mapping.get(name, name)

    daily_names = {mapped(name) for name in counts["日考勤"]}
    measurement_names = {mapped(name) for name in counts["测温登记"]}
    matched_custom = daily_names & measurement_names
    pending = []
    if measurements:
        for name in sorted({name for count in counts.values() for name in count}):
            if mapped(name) not in set(TEMPERATURE_SITE_CANDIDATES) | matched_custom:
                pending.append({"name": name, "sources": {label: count[name] for label, count in counts.items() if count[name]}})
    if pending:
        raise TemperatureSiteConfirmationRequired(pending, sorted(candidates))

    audit = []
    for label, rows in groups.items():
        for name, count in counts[label].items():
            target = mapped(name)
            audit.append({"original": name, "matched": target, "source": label, "count": count,
                          "method": "confirmed" if normalize_temperature_site(name) in mapping else "format" if name != target else "exact"})
        for row in rows:
            original = str(row.get("测温网点") or "").strip()
            if original:
                row["原始测温网点"] = original
                row["测温网点"] = mapped(original)
    return {"temperature_site_matches": audit}

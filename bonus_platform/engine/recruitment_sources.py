from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tempfile
from typing import Any, Iterable
from xml.etree import ElementTree as ET
import zipfile

from .recruitment_import_validation import (
    _convert_xls_to_xlsx,
    _first_worksheet_path,
    _local_name,
    _parse_xlsx_row,
    _read_shared_strings,
    _text,
    build_auto_import_rows,
    write_exception_workbook,
    write_standard_import_workbook,
)


HISTORICAL_BASELINE = "historical_baseline"
EHR_ROSTER = "ehr_roster"
OEHR_ROSTER = "oehr_roster"
DOMESTIC_OFFER = "domestic_offer"
OVERSEAS_OFFER = "overseas_offer"
EHR_RESIGNATIONS = "ehr_resignations"
OEHR_RESIGNATIONS = "oehr_resignations"
SPECIAL_APPROVALS = "special_approvals"
EXTERNAL_SUPPLEMENT = "external_supplement"

SOURCE_ROLE_LABELS = {
    HISTORICAL_BASELINE: "可信历史基线",
    EHR_ROSTER: "EHR花名册",
    OEHR_ROSTER: "OEHR花名册",
    DOMESTIC_OFFER: "国内Offer",
    OVERSEAS_OFFER: "海外Offer",
    EHR_RESIGNATIONS: "EHR离职数据",
    OEHR_RESIGNATIONS: "OEHR离职数据",
    SPECIAL_APPROVALS: "特殊事项审批",
    EXTERNAL_SUPPLEMENT: "体系外补充数据",
}

REQUIRED_SOURCE_ROLES = {
    HISTORICAL_BASELINE,
    EHR_ROSTER,
    OEHR_ROSTER,
    DOMESTIC_OFFER,
    OVERSEAS_OFFER,
}

OPTIONAL_SOURCE_ROLES = {
    EHR_RESIGNATIONS,
    OEHR_RESIGNATIONS,
    SPECIAL_APPROVALS,
    EXTERNAL_SUPPLEMENT,
}

_ROLE_SIGNATURES: dict[str, dict[str, int]] = {
    HISTORICAL_BASELINE: {
        "验证唯一": 8,
        "核算月份": 5,
        "候选人入职时间": 5,
        "周期天数剔除": 5,
        "周期剔除天数": 5,
        "招聘负责人入职奖金明细": 4,
        "推荐人工号": 3,
        "招聘负责人工号": 3,
    },
    EHR_ROSTER: {
        "JobNumber": 5,
        "parent_Name": 5,
        "EmployeeStatus": 4,
        "EntryDate": 4,
        "parent_IDNumber": 3,
        "OIdJobPosition_Name": 3,
        "OIdJobLevel": 3,
    },
    OEHR_ROSTER: {
        "姓名": 2,
        "工号": 3,
        "offer流程编号": 5,
        "人员状态": 4,
        "入职日期": 3,
        "证件号码": 3,
        "二级部门": 3,
        "直接上级工号": 3,
    },
    DOMESTIC_OFFER: {
        "LookupPrefix_LURecord_JobNumber": 7,
        "LookupPrefix_RecruitmentRequirement_extzhiweifenlei_109025_933701443": 5,
        "LookupPrefix_RecruitmentRequirement_CreateDate": 5,
        "HrDutyUserId-StaffCode": 4,
        "ApprovalStatus": 3,
        "IDNumber": 3,
    },
    OVERSEAS_OFFER: {
        "offer编码": 7,
        "招聘需求编码": 5,
        "编制ABC分类": 4,
        "招聘负责人工号": 3,
        "其他渠道": 4,
        "状态": 2,
    },
    EHR_RESIGNATIONS: {
        "JobNumber": 4,
        "LastWorkDate": 6,
        "ChangeReason": 5,
        "TransitionTypeOID": 4,
        "ApprovalStatus": 3,
    },
    OEHR_RESIGNATIONS: {
        "标题": 3,
        "工号": 2,
        "最后工作日": 6,
        "离职类型": 4,
        "审批状态": 4,
        "是否作废": 4,
    },
    SPECIAL_APPROVALS: {
        "事项分类": 7,
        "申请单编号": 5,
        "申请说明": 5,
        "招聘周期特殊剔除时间（天）": 5,
        "文档状态": 3,
    },
    EXTERNAL_SUPPLEMENT: {
        "体系外人员编号": 9,
        "数据动作": 5,
        "招聘负责人工号": 3,
        "招聘负责人编号": 3,
        "入职日期": 2,
        "姓名": 2,
    },
}

_FILENAME_HINTS: dict[str, tuple[str, ...]] = {
    HISTORICAL_BASELINE: ("历史", "上月", "核算明细", "招聘奖金"),
    EHR_ROSTER: ("ehr花名册", "ehr roster"),
    OEHR_ROSTER: ("oehr花名册", "oehr roster"),
    DOMESTIC_OFFER: ("国内offer", "domestic offer"),
    OVERSEAS_OFFER: ("海外offer", "overseas offer"),
    EHR_RESIGNATIONS: ("ehr离职", "ehr resignation"),
    OEHR_RESIGNATIONS: ("oehr离职", "oehr resignation"),
    SPECIAL_APPROVALS: ("特殊事项", "特殊审批", "special approval"),
    EXTERNAL_SUPPLEMENT: ("体系外", "external supplement"),
}


@dataclass(frozen=True)
class SourceInspection:
    filename: str
    path: Path
    role: str
    role_label: str
    confidence: str
    score: int
    header_row: int
    headers: tuple[str, ...]
    alternatives: tuple[tuple[str, int], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "role": self.role,
            "roleLabel": self.role_label,
            "confidence": self.confidence,
            "score": self.score,
            "headerRow": self.header_row,
            "headerPreview": list(self.headers[:12]),
            "alternatives": [
                {"role": role, "roleLabel": SOURCE_ROLE_LABELS.get(role, role), "score": score}
                for role, score in self.alternatives
            ],
        }


def inspect_recruitment_source(path: Path | str, filename: str | None = None) -> SourceInspection:
    source_path = Path(path)
    display_name = Path(filename or source_path.name).name
    candidates = _workbook_header_candidates(source_path)
    filename_scores = _filename_role_scores(display_name)
    ranked: list[tuple[int, str, int, tuple[str, ...]]] = []
    for row_number, headers in candidates:
        normalized = {_normalize_header(header): header for header in headers if _text(header)}
        for role, signature in _ROLE_SIGNATURES.items():
            score = filename_scores.get(role, 0)
            score += sum(weight for header, weight in signature.items() if _normalize_header(header) in normalized)
            ranked.append((score, role, row_number, tuple(headers)))

    if not ranked:
        return SourceInspection(display_name, source_path, "unknown", "无法识别", "low", 0, 0, (), ())

    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    best_score, best_role, header_row, headers = ranked[0]
    best_by_role: dict[str, int] = {}
    for score, role, _row_number, _headers in ranked:
        best_by_role[role] = max(score, best_by_role.get(role, 0))
    alternatives = tuple(
        (role, score)
        for role, score in sorted(best_by_role.items(), key=lambda item: item[1], reverse=True)[:3]
    )
    second_score = alternatives[1][1] if len(alternatives) > 1 else 0
    if best_score < 8:
        role = "unknown"
        confidence = "low"
    elif best_score >= 15 and best_score - second_score >= 4:
        role = best_role
        confidence = "high"
    else:
        role = best_role
        confidence = "medium"
    return SourceInspection(
        display_name,
        source_path,
        role,
        SOURCE_ROLE_LABELS.get(role, "无法识别"),
        confidence,
        best_score,
        header_row,
        headers,
        alternatives,
    )


def inspect_recruitment_source_package(
    files: Iterable[tuple[str, Path | str]],
) -> dict[str, Any]:
    inspections = [inspect_recruitment_source(path, filename) for filename, path in files]
    by_role: dict[str, list[SourceInspection]] = {}
    for inspection in inspections:
        by_role.setdefault(inspection.role, []).append(inspection)

    missing = sorted(REQUIRED_SOURCE_ROLES - set(by_role), key=_role_sort_key)
    duplicates = {
        role: rows
        for role, rows in by_role.items()
        if role != "unknown" and len(rows) > 1
    }
    unresolved = by_role.get("unknown", [])
    unsupported = by_role.get(EXTERNAL_SUPPLEMENT, [])
    optional_missing = sorted(OPTIONAL_SOURCE_ROLES - set(by_role), key=_role_sort_key)
    ready = not missing and not duplicates and not unresolved and not unsupported
    warnings: list[str] = []
    if optional_missing:
        warnings.append(
            "本次未提供：" + "、".join(SOURCE_ROLE_LABELS[role] for role in optional_missing)
        )
    return {
        "ready": ready,
        "files": [inspection.to_dict() for inspection in inspections],
        "missingRoles": [
            {"role": role, "roleLabel": SOURCE_ROLE_LABELS[role]}
            for role in missing
        ],
        "duplicateRoles": [
            {
                "role": role,
                "roleLabel": SOURCE_ROLE_LABELS.get(role, role),
                "filenames": [row.filename for row in rows],
            }
            for role, rows in sorted(duplicates.items(), key=lambda item: _role_sort_key(item[0]))
        ],
        "unresolvedFiles": [row.filename for row in unresolved],
        "unsupportedRoles": [
            {
                "role": EXTERNAL_SUPPLEMENT,
                "roleLabel": SOURCE_ROLE_LABELS[EXTERNAL_SUPPLEMENT],
                "filenames": [row.filename for row in unsupported],
                "reason": "尚未建立可验证的字段映射",
            }
        ]
        if unsupported
        else [],
        "optionalMissingRoles": [
            {"role": role, "roleLabel": SOURCE_ROLE_LABELS[role]}
            for role in optional_missing
        ],
        "warnings": warnings,
        "inspections": inspections,
    }


def build_recruitment_initial_data(
    *,
    target_month: int,
    package: dict[str, Any],
    output_dir: Path | str,
) -> dict[str, Any]:
    if not package.get("ready"):
        raise ValueError(source_package_error_message(package))
    inspections: list[SourceInspection] = package["inspections"]
    paths = {inspection.role: inspection.path for inspection in inspections}
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    rows, diagnostics = build_auto_import_rows(
        target_month=target_month,
        previous_workbook=paths[HISTORICAL_BASELINE],
        ehr_roster=paths[EHR_ROSTER],
        oehr_roster=paths[OEHR_ROSTER],
        domestic_offer=paths[DOMESTIC_OFFER],
        overseas_offer=paths[OVERSEAS_OFFER],
        ehr_resignations=paths.get(EHR_RESIGNATIONS),
        oehr_resignations=paths.get(OEHR_RESIGNATIONS),
        special_approvals=paths.get(SPECIAL_APPROVALS),
    )
    initial_path = write_standard_import_workbook(rows, output_path / "招聘奖金_整合初算数据.xlsx")
    report_path = write_exception_workbook(diagnostics, output_path / "招聘奖金_数据整合报告.xlsx")
    return {
        "rows": rows,
        "diagnostics": diagnostics,
        "initialDataPath": initial_path,
        "sourceReportPath": report_path,
        "baseline": next(row.to_dict() for row in inspections if row.role == HISTORICAL_BASELINE),
        "sourceFiles": [row.to_dict() for row in inspections],
    }


def source_package_error_message(package: dict[str, Any]) -> str:
    messages: list[str] = []
    missing = package.get("missingRoles") or []
    if missing:
        messages.append("缺少" + "、".join(row["roleLabel"] for row in missing))
    duplicates = package.get("duplicateRoles") or []
    if duplicates:
        messages.append("存在重复来源：" + "、".join(row["roleLabel"] for row in duplicates))
    unresolved = package.get("unresolvedFiles") or []
    if unresolved:
        messages.append("无法识别：" + "、".join(unresolved))
    unsupported = package.get("unsupportedRoles") or []
    if unsupported:
        messages.append(
            "暂不能处理："
            + "、".join(f'{row["roleLabel"]}（{row["reason"]}）' for row in unsupported)
        )
    return "；".join(messages) or "原始数据包未通过校验"


def _workbook_header_candidates(path: Path) -> list[tuple[int, list[str]]]:
    if path.suffix.lower() == ".xls":
        with tempfile.TemporaryDirectory() as tmpdir:
            converted = _convert_xls_to_xlsx(path, Path(tmpdir))
            return _workbook_header_candidates(converted)
    if path.suffix.lower() not in {".xlsx", ".xlsm"}:
        return []
    try:
        with zipfile.ZipFile(path) as archive:
            shared_strings = _read_shared_strings(archive)
            sheet_path = _first_worksheet_path(archive)
            candidates: list[tuple[int, list[str]]] = []
            with archive.open(sheet_path) as source:
                for _event, element in ET.iterparse(source, events=("end",)):
                    if _local_name(element.tag) != "row":
                        continue
                    row_number = int(element.attrib.get("r") or len(candidates) + 1)
                    parsed = _parse_xlsx_row(element, shared_strings)
                    element.clear()
                    headers = [_text(value) for _column, value in sorted(parsed.items()) if _text(value)]
                    if headers:
                        candidates.append((row_number, headers))
                    if row_number >= 15 or len(candidates) >= 15:
                        break
            return candidates
    except (OSError, KeyError, zipfile.BadZipFile, ET.ParseError):
        return []


def _filename_role_scores(filename: str) -> dict[str, int]:
    normalized = filename.lower().replace(" ", "")
    scores: dict[str, int] = {}
    for role, hints in _FILENAME_HINTS.items():
        if any(hint.lower().replace(" ", "") in normalized for hint in hints):
            scores[role] = 5
    if "oehr" in normalized:
        scores[EHR_ROSTER] = 0
        scores[EHR_RESIGNATIONS] = 0
    return scores


def _normalize_header(value: Any) -> str:
    return "".join(_text(value).lower().split())


def _role_sort_key(role: str) -> int:
    order = list(SOURCE_ROLE_LABELS)
    return order.index(role) if role in order else len(order)

from __future__ import annotations

import re
from typing import Any


COVERAGE_LABELS = {
    "social": "社保",
    "medical": "医保",
    "housing": "公积金",
}

STATUS_LABELS = {
    "ready": "可办理",
    "needs_review": "待确认",
    "supplement": "补缴确认",
    "scheduled": "跨月待办",
    "completed": "已完成",
    "excluded": "不办理",
    "deferred": "暂不处理",
}

_CITY_ROUTES: tuple[tuple[tuple[str, ...], dict[str, tuple[str, str, str]]], ...] = (
    (("深圳",), {
        "social": ("shenzhen-social-medical", "深圳社保医保合并模板", "template"),
        "medical": ("shenzhen-social-medical", "深圳社保医保合并模板", "template"),
    }),
    (("成都",), {
        "social": ("chengdu-social", "成都社保模板", "template"),
        "medical": ("chengdu-medical", "成都医保模板", "template"),
    }),
    (("杭州", "宁波", "义乌", "浙江"), {
        "social": ("zhejiang-social-medical", "浙江社保医保合并模板", "template"),
        "medical": ("zhejiang-social-medical", "浙江社保医保合并模板", "template"),
    }),
    (("广州",), {
        "social": ("guangzhou-social", "广州社保医保模板", "template"),
        "medical": ("guangzhou-social", "广州社保医保模板", "template"),
    }),
    (("东莞",), {
        "social": ("dongguan-social", "东莞社保医保模板", "template"),
        "medical": ("dongguan-social", "东莞社保医保模板", "template"),
    }),
    (("郑州",), {
        "medical": ("zhengzhou-medical", "郑州医保模板", "template"),
    }),
    (("武汉",), {
        "medical": ("wuhan-medical", "武汉医保模板", "template"),
    }),
)

_MANUAL_ROUTE = ("manual-offline", "线下办理（暂不生成模板）", "manual")


def _route_for(place: str, coverage: str) -> tuple[str, str, str]:
    normalized = str(place or "").strip()
    for markers, routes in _CITY_ROUTES:
        if any(marker in normalized for marker in markers):
            return routes.get(coverage, _MANUAL_ROUTE)
    return _MANUAL_ROUTE


def _place_for_routing(*values: Any) -> str:
    candidates = [str(value or "").strip() for value in values if str(value or "").strip()]
    for candidate in candidates:
        if not re.fullmatch(r"\d+(?:\.0+)?", candidate):
            return candidate
    return candidates[0] if candidates else ""


def _coverage_segment(status_text: str, coverage: str) -> str:
    text = str(status_text or "").strip()
    if not text:
        return ""
    markers = ("社保", "工伤") if coverage == "social" else ("医保", "医疗")
    clauses = [item.strip() for item in re.split(r"[，,；;]", text) if item.strip()]
    matched = [item for item in clauses if any(marker in item for marker in markers)]
    return "；".join(matched) if matched else text


def _extract_months(text: str) -> list[str]:
    matched = re.search(r"补缴([^；;,，]*)", text)
    if not matched:
        return []
    months: list[str] = []
    for value in re.findall(r"(?<!\d)(1[0-2]|[1-9])(?=\s*(?:月|、|,|，|和|及|至|到|$))", matched.group(1)):
        if value not in months:
            months.append(value)
    return months


def _future_action_month(text: str) -> str:
    matched = re.search(r"(?<!\d)(1[0-2]|[1-9])月[^；;,，]*(?:购买|增员|参保)", text)
    return matched.group(1) if matched else ""


def _inferred_status(
    *,
    coverage: str,
    status_text: str,
    employee_status: str,
    decision: str,
) -> tuple[str, str, list[str], str]:
    label = COVERAGE_LABELS[coverage]
    if decision == "exclude" or employee_status == "excluded":
        return "excluded", "", [], f"本批人员已排除，{label}不办理"

    segment = _coverage_segment(status_text, coverage)
    normalized = segment.lower().replace(" ", "")
    supplement_months = _extract_months(segment)
    if "补缴" in segment and "补缴ok" not in normalized:
        detail = "、".join(supplement_months) if supplement_months else "历史月份"
        return "supplement", "", supplement_months, f"线下源表标记{label}补缴{detail}"
    if any(marker in segment for marker in ("待审核", "待确认", "需确认", "未返回")):
        return "needs_review", "", [], f"线下源表标记{label}待审核"
    action_month = _future_action_month(segment)
    if action_month and "ok" not in normalized:
        return "scheduled", action_month, [], f"线下源表指定{action_month}月办理{label}"
    if any(marker in normalized for marker in ("ok", "已办理", "已完成", "完成")):
        return "completed", "", [], f"线下源表标记{label}已完成"
    if action_month:
        return "completed", action_month, [], f"线下源表标记{action_month}月{label}已完成"
    if employee_status == "needs_review":
        return "needs_review", "", [], f"{label}沿用人员字段校验结果，需人工确认"
    return "ready", "", [], f"{label}沿用现有字段校验结果"


def build_coverage_tasks(
    *,
    coverage_source: dict[str, Any] | None,
    source: dict[str, Any] | None,
    employee_status: str,
    decision: str,
) -> dict[str, dict[str, Any]]:
    safe_coverage_source = coverage_source if isinstance(coverage_source, dict) else {}
    safe_source = source if isinstance(source, dict) else {}
    place = _place_for_routing(
        safe_coverage_source.get("socialPlace"),
        safe_source.get("socialPlace"),
        safe_source.get("place"),
    )
    status_text = str(
        safe_coverage_source.get("socialMedicalStatus")
        or safe_source.get("socialMedicalStatus")
        or ""
    ).strip()
    tasks: dict[str, dict[str, Any]] = {}
    for coverage in ("social", "medical"):
        status, action_month, supplement_months, reason = _inferred_status(
            coverage=coverage,
            status_text=status_text,
            employee_status=employee_status,
            decision=decision,
        )
        route, route_label, handling = _route_for(place, coverage)
        tasks[coverage] = {
            "coverage": coverage,
            "label": COVERAGE_LABELS[coverage],
            "status": status,
            "statusLabel": STATUS_LABELS[status],
            "actionMonth": action_month,
            "supplementMonths": supplement_months,
            "route": route,
            "routeLabel": route_label,
            "handling": handling,
            "reason": reason,
        }

    tasks["housing"] = {
        "coverage": "housing",
        "label": COVERAGE_LABELS["housing"],
        "status": "deferred",
        "statusLabel": STATUS_LABELS["deferred"],
        "actionMonth": "",
        "supplementMonths": [],
        "route": "housing-deferred",
        "routeLabel": "本期暂不处理公积金模板",
        "handling": "deferred",
        "reason": "本期聚焦社保增员，公积金仅保留源状态",
    }
    return tasks


def coverage_summary(employees: list[dict[str, Any]]) -> dict[str, int]:
    active_tasks = [
        task
        for employee in employees
        if employee.get("decision") == "include"
        for key, task in (employee.get("coverageTasks") or {}).items()
        if key in {"social", "medical"} and isinstance(task, dict)
    ]
    return {
        "coverageReady": sum(task.get("status") in {"ready", "completed"} for task in active_tasks),
        "coverageNeedsReview": sum(task.get("status") in {"needs_review", "supplement"} for task in active_tasks),
        "coverageScheduled": sum(task.get("status") == "scheduled" for task in active_tasks),
        "manualHandling": sum(task.get("handling") == "manual" for task in active_tasks),
    }


def processing_plan(employees: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for employee in employees:
        if employee.get("decision") != "include":
            continue
        for coverage in ("social", "medical"):
            task = (employee.get("coverageTasks") or {}).get(coverage) or {}
            route = str(task.get("route") or "manual-offline")
            group = groups.setdefault(route, {
                "route": route,
                "routeLabel": str(task.get("routeLabel") or "线下办理（暂不生成模板）"),
                "handling": str(task.get("handling") or "manual"),
                "coverages": [],
                "employeeIds": set(),
            })
            if coverage not in group["coverages"]:
                group["coverages"].append(coverage)
            group["employeeIds"].add(str(employee.get("id") or ""))
    output = []
    for group in groups.values():
        output.append({
            **{key: value for key, value in group.items() if key != "employeeIds"},
            "employeeCount": len(group["employeeIds"]),
        })
    return sorted(output, key=lambda item: (item["handling"] != "template", item["routeLabel"]))

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

from .models import LaborLineItem
from .parsing import normalize_employee_name


def build_ocr_name_gate(
    candidate_rows: list[LaborLineItem],
    excel_rows: list[LaborLineItem],
    *,
    amount_tolerance: float = 0.10,
    hours_tolerance: float = 0.10,
) -> dict[str, Any]:
    candidates = _aggregate(candidate_rows)
    excel = _aggregate(excel_rows)
    matches: list[dict[str, Any]] = []
    used_excel: set[str] = set()
    pending: list[dict[str, Any]] = []

    for candidate_key, candidate in candidates.items():
        exact = excel.get(candidate_key)
        if (
            exact
            and len(candidate["rawNames"]) == 1
            and len(exact["rawNames"]) == 1
            and candidate_key not in used_excel
        ):
            matches.append(_match_payload(candidate, exact, "confirmed", 1.0, 1.0, amount_tolerance, hours_tolerance))
            used_excel.add(candidate_key)
            continue
        scored = sorted(
            (
                (_name_score(candidate["name"], item["name"]), excel_key, item)
                for excel_key, item in excel.items()
                if excel_key not in used_excel
            ),
            reverse=True,
            key=lambda value: value[0],
        )
        best_score, best_key, best = scored[0] if scored else (0.0, "", None)
        runner_up_score = scored[1][0] if len(scored) > 1 else 0.0
        pending.append(
            {
                "candidateKey": candidate_key,
                "candidate": candidate,
                "excelKey": best_key,
                "excel": best,
                "score": best_score,
                "runnerUpScore": runner_up_score,
            }
        )

    for item in sorted(pending, key=lambda value: value["score"], reverse=True):
        candidate = item["candidate"]
        excel_key = item["excelKey"]
        excel_item = item["excel"]
        if not excel_item or excel_key in used_excel:
            matches.append(_unmatched_payload(candidate))
            continue
        amount_supported = abs(candidate["amount"] - excel_item["amount"]) <= amount_tolerance
        hours_supported = abs(candidate["hours"] - excel_item["hours"]) <= hours_tolerance
        margin = round(item["score"] - item["runnerUpScore"], 4)
        reviewable = bool(
            (item["score"] >= 0.72 and margin >= 0.05)
            or (item["score"] >= 0.50 and amount_supported and hours_supported and margin >= 0.03)
        )
        if not reviewable:
            matches.append(_unmatched_payload(candidate, best=excel_item, score=item["score"], margin=margin))
            continue
        matches.append(
            _match_payload(
                candidate,
                excel_item,
                "review",
                item["score"],
                margin,
                amount_tolerance,
                hours_tolerance,
            )
        )
        used_excel.add(excel_key)

    status_counts = {
        status: sum(1 for item in matches if item["status"] == status)
        for status in ("confirmed", "review", "unmatched")
    }
    return {
        "source": "labor_ocr_name_gate",
        "formalFlowChanged": False,
        "summary": {
            "candidateEmployeeCount": len(candidates),
            "excelEmployeeCount": len(excel),
            "unlinkedExcel": len(excel) - len(used_excel),
            **status_counts,
            "autoConfirmRate": round(status_counts["confirmed"] / len(candidates), 4) if candidates else 0.0,
        },
        "matches": sorted(matches, key=lambda item: (item["status"], item["candidateName"])),
    }


def _aggregate(rows: list[LaborLineItem]) -> dict[str, dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = normalize_employee_name(row.employee_name_raw)
        if not key:
            continue
        group = groups.setdefault(
            key,
            {"key": key, "name": row.employee_name_raw, "rawNames": set(), "hours": 0.0, "amount": 0.0},
        )
        group["rawNames"].add(row.employee_name_raw)
        group["hours"] = round(group["hours"] + float(row.hours or 0), 3)
        group["amount"] = round(group["amount"] + float(row.amount or 0), 2)
    return groups


def _name_score(left: str, right: str) -> float:
    left_normalized = normalize_employee_name(left)
    right_normalized = normalize_employee_name(right)
    left_tokens = set(left_normalized.split())
    right_tokens = set(right_normalized.split())
    if not left_tokens or not right_tokens:
        return 0.0
    jaccard = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
    sequence = SequenceMatcher(None, left_normalized, right_normalized).ratio()
    return round(max(jaccard, sequence), 4)


def _match_payload(
    candidate: dict[str, Any],
    excel: dict[str, Any],
    status: str,
    score: float,
    margin: float,
    amount_tolerance: float,
    hours_tolerance: float,
) -> dict[str, Any]:
    amount_delta = round(candidate["amount"] - excel["amount"], 2)
    hours_delta = round(candidate["hours"] - excel["hours"], 3)
    return {
        "candidateName": candidate["name"],
        "excelName": excel["name"],
        "status": status,
        "nameScore": round(score, 4),
        "scoreMargin": round(margin, 4),
        "candidateHours": candidate["hours"],
        "excelHours": excel["hours"],
        "hoursDelta": hours_delta,
        "candidateAmount": candidate["amount"],
        "excelAmount": excel["amount"],
        "amountDelta": amount_delta,
        "amountSupported": abs(amount_delta) <= amount_tolerance,
        "hoursSupported": abs(hours_delta) <= hours_tolerance,
    }


def _unmatched_payload(
    candidate: dict[str, Any],
    *,
    best: dict[str, Any] | None = None,
    score: float = 0.0,
    margin: float = 0.0,
) -> dict[str, Any]:
    return {
        "candidateName": candidate["name"],
        "excelName": best["name"] if best else "",
        "status": "unmatched",
        "nameScore": round(score, 4),
        "scoreMargin": round(margin, 4),
        "candidateHours": candidate["hours"],
        "excelHours": best["hours"] if best else 0.0,
        "hoursDelta": round(candidate["hours"] - best["hours"], 3) if best else candidate["hours"],
        "candidateAmount": candidate["amount"],
        "excelAmount": best["amount"] if best else 0.0,
        "amountDelta": round(candidate["amount"] - best["amount"], 2) if best else candidate["amount"],
        "amountSupported": False,
        "hoursSupported": False,
    }

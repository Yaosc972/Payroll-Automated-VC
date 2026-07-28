from __future__ import annotations

import base64
from dataclasses import asdict, replace
from difflib import SequenceMatcher
import hashlib
from io import BytesIO
import json
import logging
import queue
import re
import socket
import threading
import unicodedata
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib import request

import httpx

logger = logging.getLogger("bonus_platform.labor.extract")

from .models import LaborLineItem, line_items_from_dicts
from .layout import InvoiceLayoutPlan, analyze_invoice_layout, extract_rows_from_layout_plan, layout_plan_from_dict
from .evidence import LaborPageEvidence, select_invoice_evidence
from .parsing import normalize_workbuddy_name, parse_number
from .profiles import SupplierExtractionProfile, resolve_supplier_profile


LINE_RE = re.compile(r"^(?P<name>.+?)\s+(?P<id>(?:[A-Z]{2,5})?\d{5,6})\s+(?P<rest>\d.*\$.*?)$")
NUMBER_RE = re.compile(r"-?\$|[-]?\d[\d,]*\.\d+\$?")
DATE_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")
HOUR_RE = re.compile(r"^\d+(?:\.\d+)?$")
PAY_CODE_RE = re.compile(r"^(?:Reg|OT|DT)$", re.IGNORECASE)
TYPE_RE = re.compile(r"^(?:REG|OT|DT)$", re.IGNORECASE)
MONEY_RE = re.compile(r"^\$?[\d,]+\.\d{2}\$?$")
AI_PAGE_CACHE_VERSION = "v15"
TOTALS_CACHE_VERSION = "v6"
ProgressCallback = Callable[[Dict[str, Any]], None]


class MiMoTimeoutException(Exception):
    """Raised when MiMo API request exceeds timeout."""
    pass


# ── HTTP client with strict outer timeout (wall-clock) ──
# urllib and httpx timeouts are phase/socket oriented, so a slow gateway can still
# keep a request alive. The daemon worker below lets the caller abandon a stuck request.
_MIMO_TIMEOUT = httpx.Timeout(60.0, connect=10.0, read=50.0, pool=5.0)
_MIMO_WALL_TIMEOUT_SECONDS = 60.0


def _http_post_json(
    url: str,
    headers: Dict[str, str],
    payload: dict,
    timeout: httpx.Timeout = _MIMO_TIMEOUT,
    wall_timeout_seconds: float = _MIMO_WALL_TIMEOUT_SECONDS,
) -> dict:
    """POST JSON with strict total timeout. Returns parsed JSON response.

    Raises MiMoTimeoutException on any timeout (connect, read, pool, or total).
    """
    logger.info(f"[D] [CRITICAL] POST → {url}, payload={len(json.dumps(payload))} bytes, timeout={wall_timeout_seconds}s total")
    result_queue: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)

    def _send() -> None:
        with httpx.Client(timeout=timeout, http2=False) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
        result_queue.put((True, (data, resp.status_code)))

    def _worker() -> None:
        try:
            _send()
        except Exception as exc:
            result_queue.put((False, exc))

    thread = threading.Thread(target=_worker, name="mimo-http-post", daemon=True)
    thread.start()
    thread.join(timeout=wall_timeout_seconds)
    if thread.is_alive():
        raise MiMoTimeoutException(f"MiMo API Gateway took over {wall_timeout_seconds:g}s to respond: {url}")
    try:
        ok, result = result_queue.get_nowait()
    except queue.Empty as exc:
        raise MiMoTimeoutException(f"MiMo API Gateway returned without a response payload: {url}") from exc

    if ok:
        data, status_code = result
        logger.info(f"[E] [CRITICAL] POST ← {url} responded in time, status={status_code}")
        return data
    exc = result
    try:
        raise exc
    except httpx.TimeoutException as exc:
        raise MiMoTimeoutException(f"MiMo API Gateway dropped connection or took over 30s to respond: {url}") from exc
    except httpx.HTTPStatusError as exc:
        response_text = exc.response.text[:1000]
        logger.error(f"[E] HTTP {exc.response.status_code}: {response_text[:300]}")
        message = f"{exc}. Response body: {response_text}" if response_text else str(exc)
        raise httpx.HTTPStatusError(message, request=exc.request, response=exc.response) from exc
    except Exception as exc:
        logger.error(f"[E] POST {url} failed: {exc}")
        raise


def _anthropic_messages_url(ai_config: Dict[str, Any]) -> str:
    base_url = str(ai_config["base_url"]).rstrip("/")
    if "token-plan-cn.xiaomimimo.com" in base_url and "/anthropic" not in base_url:
        if base_url.endswith("/v1"):
            base_url = base_url[: -len("/v1")]
        return f"{base_url}/anthropic/v1/messages"
    if base_url.endswith("/v1"):
        return f"{base_url}/messages"
    return f"{base_url}/v1/messages"


def _effective_render_scale(ai_config: Dict[str, Any]) -> float:
    scale = float(ai_config.get("render_scale") or 1.2)
    if _is_token_plan(ai_config):
        return min(scale, 0.75)
    return scale


def _effective_max_pages_per_request(ai_config: Dict[str, Any]) -> int:
    max_pages = max(int(ai_config.get("max_pages_per_request") or 5), 1)
    if _is_token_plan(ai_config):
        return 1
    return max_pages




# ── Fuzzy key matching for AI-extracted rows ──
_AMOUNT_KEYS = ("amount", "total", "charge", "cost", "price", "total_amount",
                "金额", "费用", "实际", "bill", "bill_amount", "invoice_amount",
                "amount_due", "balance", "net", "gross", "subtotal")
_HOURS_KEYS = ("hours", "hour", "hrs", "hr", "工时", "时长", "total_hours",
               "work_hours", "regular_hours", "ot_hours")
_NAME_KEYS = ("employee_name_raw", "employeeNameRaw", "employee_name",
              "employeeName", "name", "employee", "worker_name", "staff_name",
              "姓名", "员工", "worker")


def _fuzzy_get(row: Dict[str, Any], candidates: tuple, default: Any = None) -> Any:
    """Fuzzy key lookup: try exact match, then lowercase, then substring."""
    # Exact match
    for key in candidates:
        if key in row and row[key] is not None and row[key] != "":
            return row[key]
    # Lowercase match
    lower_map = {k.lower(): v for k, v in row.items()}
    for key in candidates:
        if key.lower() in lower_map and lower_map[key.lower()] is not None:
            return lower_map[key.lower()]
    # Substring match (key contains candidate)
    for key, val in row.items():
        if val is not None and val != "":
            key_lower = key.lower()
            for candidate in candidates:
                if candidate in key_lower or key_lower in candidate:
                    return val
    return default


def _fuzzy_get_amount(row: Dict[str, Any]) -> float:
    """Extract amount from row, trying all known key variations."""
    raw = _fuzzy_get(row, _AMOUNT_KEYS, 0)
    result = parse_number(raw)
    if result == 0:
        # Log raw data so we can see what AI actually returned
        non_null = {k: v for k, v in row.items() if v is not None and v != ""}
        if non_null:
            logger.warning(f"金额为0, 原始数据: {json.dumps(non_null, ensure_ascii=False)[:300]}")
    return result


def _fuzzy_get_hours(row: Dict[str, Any]) -> float:
    raw = _fuzzy_get(row, _HOURS_KEYS, 0)
    return parse_number(raw)


def _fuzzy_get_name(row: Dict[str, Any]) -> str:
    return str(_fuzzy_get(row, _NAME_KEYS, "")).strip()


def _warehouse_id_from_filename(source_file: str) -> str:
    """Extract warehouse number from PDF filename like DEPT_1, CHINA_EXPRESS__3, elog9-1."""
    name = Path(source_file).stem.split("_202")[0]
    m = re.search(r"(?<!\d)(\d{1,3})\s*号\s*仓", name)
    if m:
        return m.group(1)
    m = re.search(r"DEPT[_\-\s]*(\d+)", name, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r"\bNJ[_\-\s]*(\d{1,3})\b", name, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r"CHINA_EXPRESS__?(\d+)", name, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r"elog(\d+)-", name, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r"(?:^|[_\-\s])WH[_\-\s]*(\d{1,3})(?:$|[_\-\s])", name, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r"(?:^|[_\-\s])LOC(?:ATION)?[_\-\s]*(\d{1,3})(?:$|[_\-\s])", name, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r"\bCA[_\-\s]*#?\s*(\d{1,3})\b", name, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r"\(#?(\d{1,3})\)\s*$", name)
    if m:
        return m.group(1)
    m = re.search(r"#\s*(\d{1,3})(?:\D|$)", name)
    if m:
        return m.group(1)
    m = re.search(r"(?:___|__)(\d{1,3})\s*$", name)
    if m:
        return m.group(1)
    return ""


def _normalize_warehouse_id_candidate(value: Any) -> str:
    text = str(value or "").strip()
    match = re.fullmatch(r"(?:(?:dept|warehouse|wh|ca)\s*)?[:#-]?\s*(\d{1,3})", text, re.IGNORECASE)
    return match.group(1) if match else ""


def _warehouse_id_from_text(page_text: str) -> str:
    """从PDF内容中提取仓库号（如 CA#25 → 25）。

    支持格式：
    - CA#N（如 CA#25 Bloomington）
    - DEPT:N（如 DEPT:25）
    - N号仓（如 25号仓）
    """
    # 匹配 CA#N / CA(LA)- #N / (CA)LA#N 格式（US ELogistics/Fairway 发票）
    m = re.search(r"CA\s*\([^)]*\)\s*-?\s*#\s*(\d+)", page_text, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r"\(CA\)\s*LA\s*#\s*(\d+)", page_text, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r"CA\s*#\s*(\d+)", page_text, re.IGNORECASE)
    if m:
        return m.group(1)
    # 匹配 DEPT:N 格式
    m = re.search(r"\bDEPT\.?\s*[:#-]\s*(\d+)", page_text, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r"WAREHOUSE\s+LOC\.?\s*#\s*(\d+)", page_text, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r"\bWH(?:\s|[:#-])+\s*(\d+)", page_text, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r"\bLOC(?:ATION)?\.?\s*[:#-]\s*(\d+)", page_text, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r"\bLocation\s+NJ\s*(\d+)", page_text, re.IGNORECASE)
    if m:
        return m.group(1)
    # 匹配 N号仓 格式
    m = re.search(r"(\d+)号仓", page_text)
    if m:
        return m.group(1)
    return ""


def _warehouse_id_conflict(source_file: str, page_text: str) -> Dict[str, str]:
    filename_wh = _warehouse_id_from_filename(source_file)
    text_wh = _warehouse_id_from_text(page_text)
    if filename_wh and text_wh and filename_wh != text_wh:
        return {
            "source_file": source_file,
            "filename_warehouse_id": filename_wh,
            "text_warehouse_id": text_wh,
        }
    return {}


def _classify_pdf(source_file: str, pages_text: str) -> str:
    """按业务用途轻量分类 PDF，避免把支持材料/附件重复计入应付金额。"""
    non_payable_role = _non_payable_page_role(source_file, pages_text)
    if non_payable_role == "supporting_attachment":
        return "attachment"
    if non_payable_role:
        return "supporting"
    text = (pages_text or "").lower()
    if re.search(
        r"(?:invoice\s+total|total\s+due|amount\s+due|balance\s+due|grand\s+total|net\s+total|"
        r"total\s+neto|nettosumme|gesamt)",
        text,
    ) and re.search(r"\$?\s*[\d,]+\.\d{2}\$?", text):
        return "primary"
    return "unknown"


def _non_payable_page_role(source_file: str, page_text: str) -> str:
    """Return a non-payable role before considering totals or detail rows."""
    filename = re.sub(r"[_-]+", " ", Path(source_file).name.lower())
    text = str(page_text or "").lower()
    payable_invoice_signal = (
        bool(re.search(r"\b(?:invoice|factura|rechnung)\b", text))
        and bool(re.search(r"\b(?:amount|importe|betrag|bill\s+rate)\b", text))
        and bool(
            re.search(
                r"\b(?:total|net\s+total|total\s+neto|nettosumme|gesamt|amount\s+due|balance\s+due)\b",
                text,
            )
        )
        and bool(re.search(r"\$?\s*[\d,]+\.\d{2}\$?", text))
    )
    if payable_invoice_signal:
        return ""
    combined = f"{filename}\n{text}"
    if re.search(r"\b(?:w-?9|coi|certificate|insurance)\b", combined):
        return "supporting_attachment"
    # "Payment Terms" is a normal field on invoice headers. Treat it as a
    # supporting-document signal only when the file itself is named that way;
    # otherwise a valid payable invoice page can be excluded wholesale.
    if re.search(r"\bpayment\s+terms\b", filename):
        return "supporting_attachment"
    if re.search(r"(?:time\s*card|timecard|timesheet)", combined):
        return "timecard_summary"
    if re.search(r"(?:daily\s+log|daily\s+detail)", combined):
        return "daily_detail"
    if re.search(r"(?:supplement|supporting?|backup|appendix|attachment)", combined):
        return "supporting_attachment"
    return ""


def _has_invoice_signal(source_file: str, page_text: str) -> bool:
    return bool(
        re.search(r"\b(?:invoice|inv)\b", Path(source_file).stem, re.IGNORECASE)
        or re.search(r"\b(?:invoice|invoice\s+total|total\s+due|amount\s+due|balance\s+due|grand\s+total)\b", str(page_text or ""), re.IGNORECASE)
    )


def _has_employee_detail_signal(page_text: str) -> bool:
    """Detect employee-detail attachments that should not be counted as payable totals.

    Some payable invoices also contain employee tables. Those must stay in the
    payable total set. This signal is intentionally limited to backup/detail
    layouts such as ELGA where a separate summary invoice carries the payable
    amount.
    """
    normalized = " ".join(str(page_text or "").split())
    if not normalized:
        return False
    patterns = [
        r"Job Site/Warehouse\s+Name\s+Pay Type",
        r"\bName\s+Pay Type\s+Rate\s+Hours\b",
    ]
    if not any(re.search(pattern, normalized, re.IGNORECASE) for pattern in patterns):
        return False
    amount_signal = re.search(r"(?:Hourly-Reg|Overtime\s*\(Hourly\)|\bReg\.?\s*Time\b|\bO\.?T\.?\b)", normalized, re.IGNORECASE)
    return bool(amount_signal)


def _extract_invoice_total_from_text(page_text: str) -> float:
    """Extract an invoice total from text before asking AI.

    Fairway-style invoices expose the authoritative amount in either a
    "Totals" row or the "GRAND TOTAL" block. Prefer those deterministic
    signals over slower model extraction and over "pay after due date" amounts.
    """
    lines = [" ".join(line.split()) for line in (page_text or "").splitlines()]
    authoritative_totals: List[float] = []
    totals: List[float] = []

    for line in lines:
        if re.search(r"\bTOTAL\s+INVOICE\s+AMOUNT\b", line, re.IGNORECASE):
            amounts = re.findall(r"\$?\s*[\d,]+\.\d{2}\$?", line)
            if amounts:
                authoritative_totals.append(parse_number(amounts[-1]))
        if re.search(r"\bTotals\b", line, re.IGNORECASE):
            amounts = re.findall(r"\$?\s*[\d,]+\.\d{2}\$?", line)
            if amounts:
                totals.append(parse_number(amounts[-1]))
        if re.match(r"^\s*TOTAL\s*:", line, re.IGNORECASE):
            amounts = re.findall(r"\$?\s*[\d,]+\.\d{2}\$?", line)
            if amounts:
                totals.append(parse_number(amounts[-1]))
        if re.search(
            r"\b(?:total\s+due|invoice\s+total|amount\s+due|balance\s+due|net\s+total|"
            r"total\s+neto|nettosumme|gesamt)\b",
            line,
            re.IGNORECASE,
        ):
            amounts = re.findall(r"\$?\s*[\d,]+\.\d{2}\$?", line)
            if amounts:
                totals.append(parse_number(amounts[-1]))

    for idx, line in enumerate(lines[:60]):
        if "BILLABLE" not in line.upper() or "TOTAL" not in line.upper():
            continue
        for candidate in lines[idx + 1 : idx + 12]:
            amounts = re.findall(r"\$?\s*[\d,]+\.\d{2}\$?", candidate)
            if len(amounts) >= 2:
                totals.append(parse_number(amounts[-1]))
                break

    grand_totals: List[float] = []
    for idx, line in enumerate(lines):
        if "GRAND TOTAL" not in line.upper():
            continue
        window = " ".join(lines[idx : idx + 8])
        amounts = re.findall(r"\$?\s*[\d,]+\.\d{2}\$?", window)
        if amounts:
            grand_totals.append(parse_number(amounts[0]))

    # Some accounting PDFs place the labels in a fixed header column and the
    # corresponding values in a footer column. Text extraction preserves the
    # reading order but separates the labels from their values. Accept this
    # shape only when the footer contains a self-consistent Total/Balance pair.
    label_positions = {
        "total": next((index for index, line in enumerate(lines) if line.strip().lower() == "total"), None),
        "balance": next((index for index, line in enumerate(lines) if line.strip().lower() == "balance due"), None),
        "payments": next((index for index, line in enumerate(lines) if line.strip().lower().startswith("payments/credits")), None),
    }
    if all(position is not None for position in label_positions.values()):
        ordered_positions = [label_positions["total"], label_positions["balance"], label_positions["payments"]]
        if ordered_positions == sorted(ordered_positions) and ordered_positions[-1] - ordered_positions[0] <= 4:
            page_marker = max(
                (index for index, line in enumerate(lines) if re.fullmatch(r"Page\s+\d+", line, re.IGNORECASE)),
                default=-1,
            )
            footer_values = [
                parse_number(line)
                for line in lines[page_marker + 1 :]
                if re.fullmatch(r"\$?\s*[\d,]+\.\d{2}", line)
            ]
            if (
                len(footer_values) >= 3
                and footer_values[0] > 0
                and abs(footer_values[0] - footer_values[1]) <= 0.01
                and footer_values[2] <= footer_values[0]
            ):
                totals.append(footer_values[0])

    authoritative_candidates = [value for value in authoritative_totals if value > 0]
    if authoritative_candidates:
        return round(authoritative_candidates[-1], 2)

    candidates = [value for value in [*totals, *grand_totals] if value > 0]
    return round(candidates[-1], 2) if candidates else 0.0


def _candidate_target_amount_from_pages(pages: List[Dict[str, Any]]) -> float:
    pages_by_source: Dict[str, List[str]] = {}
    for page in pages:
        source = str(page.get("source_file") or "")
        pages_by_source.setdefault(source, []).append(str(page.get("text") or ""))

    source_totals: List[float] = []
    for page_texts in pages_by_source.values():
        total = _extract_invoice_total_from_text("\n".join(page_texts))
        if total > 0:
            source_totals.append(total)
    if source_totals:
        return round(sum(source_totals), 2)

    return _extract_invoice_total_from_text("\n".join(str(page.get("text") or "") for page in pages))


def _candidate_total_amount(rows: List[LaborLineItem]) -> float:
    return round(sum(float(row.amount or 0) for row in rows), 2)


def _candidate_average_confidence(rows: List[LaborLineItem]) -> float:
    if not rows:
        return 0.0
    return sum(float(row.confidence or 0) for row in rows) / len(rows)


def _candidate_employee_count(rows: List[LaborLineItem]) -> int:
    keys = {
        normalize_workbuddy_name(row.employee_name_raw or row.employee_id or "")
        for row in rows
        if (row.employee_name_raw or row.employee_id or "").strip()
    }
    return len({key for key in keys if key}) or len(rows)


def _expected_employee_count(expected_rows: List[Dict[str, Any]] | None) -> int:
    if not expected_rows:
        return 0
    keys = set()
    for row in expected_rows:
        name = (
            row.get("employee_name_raw")
            or row.get("employeeNameRaw")
            or row.get("employee_name")
            or row.get("employeeName")
            or row.get("name")
            or row.get("employee")
            or ""
        )
        key = normalize_workbuddy_name(str(name))
        if key:
            keys.add(key)
    return len(keys)


def _candidate_score(rows: List[LaborLineItem], pages: List[Dict[str, Any]], expected_rows: List[Dict[str, Any]] | None = None) -> float:
    if not rows:
        return float("-inf")
    target_amount = _candidate_target_amount_from_pages(pages)
    candidate_total = _candidate_total_amount(rows)
    employee_count = _candidate_employee_count(rows)
    avg_confidence = _candidate_average_confidence(rows)

    score = min(employee_count, 80) * 2.0 + avg_confidence * 30.0
    if target_amount > 0:
        delta = abs(candidate_total - target_amount)
        tolerance = max(0.10, round(target_amount * 0.00001, 2))
        if delta <= tolerance:
            score += 250.0
        else:
            relative_delta = delta / max(target_amount, 1.0)
            score += max(0.0, 120.0 - relative_delta * 600.0)
            score -= min(180.0, relative_delta * 180.0)

    expected_count = _expected_employee_count(expected_rows)
    if expected_count:
        coverage = min(employee_count / max(expected_count, 1), 1.0)
        score += coverage * 80.0
        if employee_count < max(1, int(expected_count * 0.5)):
            score -= 50.0
    return score


def _candidate_is_confident(rows: List[LaborLineItem], pages: List[Dict[str, Any]], expected_rows: List[Dict[str, Any]] | None = None) -> bool:
    if not rows:
        return False
    expected_count = _expected_employee_count(expected_rows)
    if expected_count:
        coverage = _candidate_employee_count(rows) / max(expected_count, 1)
        if coverage < 0.85:
            return False

    target_amount = _candidate_target_amount_from_pages(pages)
    if target_amount > 0:
        return abs(_candidate_total_amount(rows) - target_amount) <= max(0.10, round(target_amount * 0.00001, 2))

    if expected_count:
        return coverage >= 0.85 and _candidate_average_confidence(rows) >= 0.9

    return target_amount <= 0 and len(rows) >= 2 and _candidate_average_confidence(rows) >= 0.9


def _choose_best_extraction_candidate(
    candidates: List[tuple[str, List[LaborLineItem]]],
    pages: List[Dict[str, Any]],
    expected_rows: List[Dict[str, Any]] | None = None,
) -> List[LaborLineItem]:
    valid_candidates = [(label, rows) for label, rows in candidates if rows]
    if not valid_candidates:
        return []
    ranked = sorted(
        valid_candidates,
        key=lambda item: _candidate_score(item[1], pages, expected_rows=expected_rows),
        reverse=True,
    )
    chosen_label, chosen_rows = ranked[0]
    logger.info(
        "抽取候选选择: %s rows=%s amount=%.2f score=%.2f target=%.2f candidates=%s",
        chosen_label,
        len(chosen_rows),
        _candidate_total_amount(chosen_rows),
        _candidate_score(chosen_rows, pages, expected_rows=expected_rows),
        _candidate_target_amount_from_pages(pages),
        ", ".join(
            f"{label}:{len(rows)}/{_candidate_total_amount(rows):.2f}/{_candidate_score(rows, pages, expected_rows=expected_rows):.1f}"
            for label, rows in ranked
        ),
    )
    return chosen_rows


def extract_invoice_items(
    pdf_paths: List[Path],
    ai_config: Dict[str, Any],
    supplier: str = "",
    period_start: str = "",
    period_end: str = "",
    currency: str = "",
    expected_rows: List[Dict[str, Any]] | None = None,
    retry_mode: bool = False,
    target_names: list[str] | None = None,
    supplier_profile_override: Optional[SupplierExtractionProfile] = None,
    progress_callback: ProgressCallback | None = None,
    audit_collector: List[Dict[str, Any]] | None = None,
    allowed_pages_by_source: Dict[str, set[int]] | None = None,
) -> List[LaborLineItem]:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    supplier_profile = supplier_profile_override or resolve_supplier_profile(supplier, profiles_path=ai_config.get("supplier_profiles_path"))
    pages = _extract_pdf_pages(pdf_paths)
    if allowed_pages_by_source:
        pages = [
            page
            for page in pages
            if str(page.get("source_file") or "") not in allowed_pages_by_source
            or int(page.get("page") or 0) in allowed_pages_by_source[str(page.get("source_file") or "")]
        ]
    if progress_callback:
        progress_callback(
            {
                "event": "pdf_pages_loaded",
                "total_files": len(pdf_paths),
                "total_pages": len(pages),
                "processed_pages": 0,
            }
        )
    extraction_candidates: List[tuple[str, List[LaborLineItem]]] = []

    # 并行规则抽取
    parallel_enabled = ai_config.get("parallel_extraction_enabled", True)

    def _extract_rules_for_page(page: Dict[str, Any]) -> List[LaborLineItem]:
        """对单个页面尝试规则抽取"""
        rows = []
        voyage_rows = _extract_voyage_invoice_rows(
            page,
            supplier=supplier,
            period_start=period_start,
            period_end=period_end,
            currency=currency,
        )
        if voyage_rows:
            return voyage_rows
        layout_plan = analyze_invoice_layout([page])
        rows.extend(
            extract_rows_from_layout_plan(
                [page],
                layout_plan,
                supplier=supplier,
                period_start=period_start,
                period_end=period_end,
                currency=currency,
            )
        )
        description_rows = _extract_description_qty_rate_invoice_rows(
            page,
            supplier=supplier,
            period_start=period_start,
            period_end=period_end,
            currency=currency,
        )
        if description_rows:
            return description_rows
        rate_amount_rows = _extract_regular_rate_amount_invoice_rows(
            page,
            supplier=supplier,
            period_start=period_start,
            period_end=period_end,
            currency=currency,
        )
        if rate_amount_rows and len(rate_amount_rows) >= len(rows):
            return rate_amount_rows
        elga_rows = _extract_elga_invoice_detail_rows(
            page,
            supplier=supplier,
            period_start=period_start,
            period_end=period_end,
            currency=currency,
        )
        if elga_rows and len(elga_rows) >= len(rows):
            return elga_rows
        if rows:
            return rows
        rows.extend(_extract_wage_code_invoice_rows(page, supplier=supplier, period_start=period_start, period_end=period_end, currency=currency))
        rows.extend(_extract_bill_rate_invoice_rows(page, supplier=supplier, period_start=period_start, period_end=period_end, currency=currency))
        rows.extend(_extract_sss_employee_summary_rows(page, supplier=supplier, period_start=period_start, period_end=period_end, currency=currency))
        rows.extend(_extract_bill_rate_summary_invoice_rows(page, supplier=supplier, period_start=period_start, period_end=period_end, currency=currency))
        rows.extend(_extract_vertical_invoice_rows(page, supplier=supplier, period_start=period_start, period_end=period_end, currency=currency))
        rows.extend(_extract_tabular_invoice_rows(page, supplier=supplier, period_start=period_start, period_end=period_end, currency=currency))
        rows.extend(_extract_simple_invoice_rows(page, supplier=supplier, period_start=period_start, period_end=period_end, currency=currency))
        for line in (page.get("text") or "").splitlines():
            compact = " ".join(line.split())
            match = LINE_RE.match(compact)
            if not match:
                continue
            values = [parse_number(value) for value in NUMBER_RE.findall(match.group("rest"))]
            if len(values) < 10:
                if len(values) == 9:
                    rows.append(_line_item(page, match, hours=0.0, amount=values[-1], currency=currency, supplier=supplier, period_start=period_start, period_end=period_end, evidence_text=compact))
                continue
            hours_values = values[4:-4]
            hours = sum(hours_values)
            amount = values[-1]
            rows.append(_line_item(page, match, hours=hours, amount=amount, currency=currency, supplier=supplier, period_start=period_start, period_end=period_end, evidence_text=compact))
        return rows

    if parallel_enabled and len(pages) > 1:
        all_rule_items: List[LaborLineItem] = []
        max_workers = min(len(pages), int(ai_config.get("parallel_max_workers", 3)))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_page = {executor.submit(_extract_rules_for_page, page): page for page in pages}
            for future in as_completed(future_to_page):
                try:
                    items = future.result()
                    all_rule_items.extend(items)
                except Exception as exc:
                    logger.warning(f"规则抽取(并行)异常: {exc}")
    else:
        all_rule_items = []
        for page in pages:
            try:
                all_rule_items.extend(_extract_rules_for_page(page))
            except Exception as exc:
                logger.warning(f"规则抽取(顺序)异常: {exc}")

    if all_rule_items:
        logger.info(f"规则抽取成功: {len(all_rule_items)} 条记录")
        extraction_candidates.append(("rules", all_rule_items))
        if _candidate_is_confident(all_rule_items, pages, expected_rows=expected_rows):
            return all_rule_items
        parsed_sources = {item.source_file for item in all_rule_items}
        pages_by_source: Dict[str, List[Dict[str, Any]]] = {}
        for page in pages:
            pages_by_source.setdefault(str(page.get("source_file") or ""), []).append(page)
        unparsed_empty_sources = {
            source
            for source, source_pages in pages_by_source.items()
            if source and source not in parsed_sources and not any((page.get("text") or "").strip() for page in source_pages)
        }
        if unparsed_empty_sources and _ai_ready(ai_config):
            unparsed_paths = [path for path in pdf_paths if path.name in unparsed_empty_sources]
            try:
                render_workers = int(ai_config.get("parallel_image_render_workers", 1))
                image_pages = _render_pdf_pages_to_images(
                    unparsed_paths,
                    scale=_effective_render_scale(ai_config),
                    max_workers=render_workers,
                    allowed_pages_by_source=allowed_pages_by_source,
                )
                image_pages = _apply_image_page_policy(image_pages, supplier_profile)
                if image_pages:
                    rows = _extract_with_ai_images(
                        image_pages,
                        ai_config,
                        supplier=supplier,
                        period_start=period_start,
                        period_end=period_end,
                        currency=currency,
                        supplier_profile=supplier_profile,
                        expected_rows=expected_rows,
                        retry_mode=retry_mode,
                        target_names=target_names,
                        progress_callback=progress_callback,
                        audit_collector=audit_collector,
                    )
                    rows = _filter_ai_rows_by_page_text(rows, pages)
                    all_rule_items.extend(line_items_from_dicts(rows))
            except Exception as exc:
                logger.warning(f"规则抽取后补充扫描 PDF 失败，保留已抽取结果: {_safe_error_message(exc)}")
        extraction_candidates[-1] = ("rules", all_rule_items)
        if _candidate_is_confident(all_rule_items, pages, expected_rows=expected_rows):
            return all_rule_items

    layout_plan = analyze_invoice_layout(pages)
    has_text_for_layout = any((page.get("text") or "").strip() for page in pages)
    if layout_plan.recommended_parser == "ai_assisted" and has_text_for_layout and _ai_ready(ai_config):
        try:
            ai_layout_plan = _analyze_layout_with_ai(pages, ai_config, supplier=supplier, currency=currency)
            if ai_layout_plan.confidence >= 0.75 and ai_layout_plan.recommended_parser != "ai_assisted":
                layout_plan = ai_layout_plan
        except Exception as exc:
            logger.warning(f"AI 版式分析失败，继续原抽取流程: {_safe_error_message(exc)}")
    planned_rows = extract_rows_from_layout_plan(
        pages,
        layout_plan,
        supplier=supplier,
        period_start=period_start,
        period_end=period_end,
        currency=currency,
    )
    if planned_rows:
        logger.info(f"版式计划抽取成功: {layout_plan.layout_type}/{layout_plan.recommended_parser}, {len(planned_rows)} 条记录")
        extraction_candidates.append(("layout_plan", planned_rows))
        if _candidate_is_confident(planned_rows, pages, expected_rows=expected_rows):
            return _choose_best_extraction_candidate(extraction_candidates, pages, expected_rows=expected_rows)

    # 如果规则抽取没有通过自检，继续尝试 AI 抽取，让多个候选结果互相比对。
    if _ai_ready(ai_config):
        logger.info("规则抽取未通过完整性自检，进入 AI 抽取流程")
        errors: List[str] = []
        # 跳过文本 AI 抽取：当所有页面文本为空（图片 PDF）时，直接走图片路径
        has_text = any((page.get("text") or "").strip() for page in pages)
        if has_text:
            try:
                rows = _extract_with_ai_text(pages, ai_config, supplier=supplier, period_start=period_start, period_end=period_end, currency=currency, supplier_profile=supplier_profile, expected_rows=expected_rows, retry_mode=retry_mode, target_names=target_names)
                rows = _filter_ai_rows_by_page_text(rows, pages)
                items = line_items_from_dicts(rows)
                if items:
                    extraction_candidates.append(("ai_text", items))
                    return _choose_best_extraction_candidate(extraction_candidates, pages, expected_rows=expected_rows)
            except Exception as exc:
                errors.append(_safe_error_message(exc))
        try:
            render_workers = int(ai_config.get("parallel_image_render_workers", 1))
            logger.info(f"[C] 渲染 PDF 为图片: {len(pdf_paths)} 个 PDF, workers={render_workers}")
            if progress_callback:
                progress_callback(
                    {
                        "event": "rendering_images",
                        "total_files": len(pdf_paths),
                        "total_pages": len(pages),
                        "processed_pages": 0,
                    }
                )
            image_pages = _render_pdf_pages_to_images(
                pdf_paths,
                scale=_effective_render_scale(ai_config),
                max_workers=render_workers,
                allowed_pages_by_source=allowed_pages_by_source,
            )
            logger.info(f"[C] 渲染完成: {len(image_pages)} 张图片")
            image_pages = _apply_image_page_policy(image_pages, supplier_profile)
            logger.info(f"[C] 策略过滤后: {len(image_pages)} 张图片")
            if not image_pages:
                logger.error("[C] 图片为空！PDF 渲染失败或策略过滤掉所有页面")
                errors.append("PDF 渲染为图片后为空，无法进行 AI 抽取")
            else:
                rows = _extract_with_ai_images(
                    image_pages,
                    ai_config,
                    supplier=supplier,
                    period_start=period_start,
                    period_end=period_end,
                    currency=currency,
                    supplier_profile=supplier_profile,
                    expected_rows=expected_rows,
                    retry_mode=retry_mode,
                    target_names=target_names,
                    progress_callback=progress_callback,
                    audit_collector=audit_collector,
                )
                rows = _filter_ai_rows_by_page_text(rows, pages)
                items = line_items_from_dicts(rows)
                if items:
                    extraction_candidates.append(("ai_image", items))
                    return _choose_best_extraction_candidate(extraction_candidates, pages, expected_rows=expected_rows)
                errors.append("AI 图片抽取返回 0 条员工明细")
        except Exception as exc:
            logger.error(f"[C] 图片抽取异常: {exc}", exc_info=True)
            errors.append(_safe_error_message(exc))
        if extraction_candidates:
            return _choose_best_extraction_candidate(extraction_candidates, pages, expected_rows=expected_rows)
        if errors:
            raise ValueError("AI 抽取失败：" + "；".join(errors))
    if extraction_candidates:
        return _choose_best_extraction_candidate(extraction_candidates, pages, expected_rows=expected_rows)
    return []


def quick_extract_totals(
    pdf_paths: List[Path],
    ai_config: Dict[str, Any],
    supplier: str = "",
) -> List[Dict[str, Any]]:
    """Extract totals with page-level evidence while retaining legacy fields."""
    ai_ready = _ai_ready(ai_config)
    profile = resolve_supplier_profile(supplier, profiles_path=ai_config.get("supplier_profiles_path"))
    selector_profile = {"authoritative_total_method": profile.authoritative_total_methods}
    pages_by_path: Dict[Path, List[Dict[str, Any]]] = {path: [] for path in pdf_paths}
    paths_by_name: Dict[str, List[Path]] = {}
    for path in pdf_paths:
        paths_by_name.setdefault(path.name, []).append(path)
    for page in _extract_pdf_pages(pdf_paths):
        source_path = Path(str(page["source_path"])) if page.get("source_path") else None
        if source_path in pages_by_path:
            pages_by_path[source_path].append(page)
            continue
        matches = paths_by_name.get(str(page.get("source_file") or ""), [])
        if len(matches) == 1:
            pages_by_path[matches[0]].append(page)
    results: List[Dict[str, Any]] = []

    for source_path, raw_pages in pages_by_path.items():
        source_file = str(raw_pages[0].get("source_file") or source_path.name) if raw_pages else source_path.name
        cache_fingerprint = _totals_cache_fingerprint(source_path, ai_config, profile)
        cached = _load_totals_cache(source_path, ai_config, cache_fingerprint)
        if cached is not None:
            results.append(cached)
            continue

        pages = sorted(raw_pages, key=lambda page: int(page.get("page") or 1))
        file_text = "\n".join(str(page.get("text") or "") for page in pages)
        evidence_pages: List[LaborPageEvidence] = []
        consecutive_ai_failures = 0
        for page_index, page in enumerate(pages):
            page_number = int(page.get("page") or 1)
            page_text = str(page.get("text") or "")
            invoice_roles = {"invoice_primary", "invoice_continuation", "invoice_total"}
            prior_evidence = select_invoice_evidence(source_file, evidence_pages, profile=selector_profile)
            prior_authoritative_total = (
                prior_evidence.authoritative
                and prior_evidence.total_page is not None
                and page_number > prior_evidence.total_page
            )
            if page_text.strip():
                page_evidence = _text_page_evidence(page)
                closing_page = page_index >= max(len(pages) - 2, 0)
                text_invoice_hint = bool(
                    re.search(
                        r"\b(?:invoice|facture)\b|\btotal\s+h\.?\s*t\.?\b|"
                        r"\btotal\s+t\.?\s*t\.?\s*c\.?(?:\s+global)?\b",
                        page_text,
                        re.IGNORECASE,
                    )
                )
                retry_text_bottom_total_ocr = bool(
                    ai_ready
                    and page_evidence.total_amount is None
                    and page_evidence.net_amount is None
                    and not prior_authoritative_total
                    and closing_page
                    and text_invoice_hint
                )
                if retry_text_bottom_total_ocr:
                    image_page = _render_pdf_page_to_image(
                        source_path,
                        page_number,
                        _effective_render_scale(ai_config),
                    )
                    if image_page is not None:
                        try:
                            bottom_evidence = _extract_bottom_total_evidence_with_ai_ocr(image_page, ai_config)
                            if bottom_evidence is not None:
                                page_evidence = replace(
                                    bottom_evidence,
                                    warehouse_id=bottom_evidence.warehouse_id or page_evidence.warehouse_id,
                                )
                        except Exception as exc:
                            logger.warning(
                                "文本发票底部总额 OCR 兜底失败: %s p%s: %s",
                                source_file,
                                page_number,
                                exc,
                            )
                page_evidence = _apply_filename_non_payable_override(source_file, page_evidence)
            elif not ai_ready:
                page_evidence = LaborPageEvidence(source_file, page_number, "unknown", 0.0, extraction_method="ai_not_configured")
            else:
                image_page = _render_pdf_page_to_image(source_path, page_number, _effective_render_scale(ai_config))
                if image_page is None:
                    page_evidence = LaborPageEvidence(source_file, page_number, "unknown", 0.0, extraction_method="image_render_failed")
                else:
                    try:
                        page_evidence = _extract_page_evidence_with_ai_image(image_page, _page_evidence_prompt(), ai_config)
                    except Exception as exc:
                        logger.warning("发票总金额页面证据抽取失败: %s p%s: %s", source_file, page_number, exc)
                        page_evidence = LaborPageEvidence(source_file, page_number, "unknown", 0.0, extraction_method="ai_image_failed")
                    retry_missing_invoice_total = (
                        page_evidence.total_amount is None
                        and page_evidence.role in {"unknown", *invoice_roles}
                        and not prior_authoritative_total
                    )
                    retry_inconsistent_total_role = (
                        page_evidence.total_amount is not None
                        and page_evidence.role not in invoice_roles
                    )
                    if page_number <= 2 and (retry_missing_invoice_total or retry_inconsistent_total_role):
                        retry_config = dict(ai_config)
                        retry_config["page_evidence_max_tokens"] = 1024
                        try:
                            retry_evidence = _extract_page_evidence_with_ai_image(image_page, _page_evidence_prompt(), retry_config)
                            retry_is_invoice = retry_evidence.role in invoice_roles
                            current_is_invoice = page_evidence.role in invoice_roles
                            if (
                                retry_is_invoice
                                or (
                                    retry_evidence.role != "unknown"
                                    and not current_is_invoice
                                    and page_evidence.role == "unknown"
                                )
                            ):
                                page_evidence = retry_evidence
                        except Exception as exc:
                            logger.warning("发票总金额页面证据重试失败: %s p%s: %s", source_file, page_number, exc)
                    retry_gross_breakdown = bool(
                        page_evidence.total_amount is not None
                        and page_evidence.net_amount is None
                        and re.search(
                            r"(?:\bttc\b|gross|amount\s+due|balance\s+due)",
                            page_evidence.total_label,
                            re.IGNORECASE,
                        )
                    )
                    if retry_gross_breakdown:
                        retry_config = dict(ai_config)
                        retry_config["page_evidence_max_tokens"] = 1024
                        try:
                            retry_evidence = _extract_page_evidence_with_ai_image(
                                image_page,
                                _page_evidence_prompt(),
                                retry_config,
                            )
                            if retry_evidence.net_amount is not None:
                                page_evidence = retry_evidence
                        except Exception as exc:
                            logger.warning("发票净额/税额/含税额证据重试失败: %s p%s: %s", source_file, page_number, exc)
                    edge_page = page_index < 2 or page_index >= max(len(pages) - 2, 0)
                    retry_bottom_total_ocr = bool(
                        page_evidence.net_amount is None
                        and not prior_authoritative_total
                        and (
                            edge_page
                            or page_evidence.role in invoice_roles
                            or page_evidence.total_amount is not None
                        )
                    )
                    if retry_bottom_total_ocr:
                        try:
                            bottom_evidence = _extract_bottom_total_evidence_with_ai_ocr(image_page, ai_config)
                            if bottom_evidence is not None:
                                page_evidence = replace(
                                    bottom_evidence,
                                    warehouse_id=bottom_evidence.warehouse_id or page_evidence.warehouse_id,
                                )
                        except Exception as exc:
                            logger.warning("发票底部总额 OCR 兜底失败: %s p%s: %s", source_file, page_number, exc)
                page_evidence = _apply_filename_non_payable_override(source_file, page_evidence)

            evidence_pages.append(page_evidence)
            if page_evidence.extraction_method == "ai_image_failed":
                consecutive_ai_failures += 1
            else:
                consecutive_ai_failures = 0
            if consecutive_ai_failures >= 2:
                for remaining in pages[page_index + 1:]:
                    evidence_pages.append(
                        LaborPageEvidence(
                            source_file,
                            int(remaining.get("page") or 1),
                            "unknown",
                            0.0,
                            extraction_method="not_scanned_after_consecutive_ai_failures",
                        )
                    )
                break
            partial_evidence = select_invoice_evidence(source_file, evidence_pages, profile=selector_profile)
            if _should_stop_page_evidence_scan(partial_evidence, page_evidence):
                for remaining in pages[page_index + 1:]:
                    evidence_pages.append(
                        LaborPageEvidence(
                            source_file,
                            int(remaining.get("page") or 1),
                            "unknown",
                            0.0,
                            extraction_method="not_scanned_after_authoritative_total",
                        )
                    )
                break

        evidence = select_invoice_evidence(source_file, evidence_pages, profile=selector_profile)
        if (
            not evidence.authoritative
            and not any(page.total_amount for page in evidence_pages)
            and any(str(page.get("text") or "").strip() for page in pages)
        ):
            evidence = _select_rule_total_evidence(source_file, evidence_pages, pages, supplier, selector_profile)
        result = _invoice_evidence_result(evidence, source_file, file_text)
        if ai_ready:
            _save_totals_cache(source_path, ai_config, result, cache_fingerprint)
        results.append(result)
    return results


def _should_stop_page_evidence_scan(invoice_evidence, current_page: LaborPageEvidence) -> bool:
    if not invoice_evidence.authoritative or current_page.page < 2:
        return False
    if (
        invoice_evidence.total_page is not None
        and current_page.page > invoice_evidence.total_page
        and current_page.total_amount is None
    ):
        return True
    invoice_roles = {"invoice_primary", "invoice_continuation", "invoice_total"}
    return current_page.role not in invoice_roles or current_page.total_amount is not None


def _quick_extract_totals_legacy(
    pdf_paths: List[Path],
    ai_config: Dict[str, Any],
    supplier: str = "",
) -> List[Dict[str, Any]]:
    """轻量级提取：每个 PDF 只提取总金额和仓库号。

    提取策略（按优先级）：
    1. 明确的发票总计/Totals 行 — 用于仓库与总账结论
    2. 规则抽取 — 从文本行解析员工明细并求和（总计缺失时兜底）
    3. 缓存 — 读取 .ai_extract_cache/ 中的历史结果
    4. AI 抽取 — 调用 AI 模型提取总金额（最慢）

    返回 [{source_file, total_amount, warehouse_id}, ...] 列表。
    线程池并行处理，支持文本 PDF 和图片 PDF。
    """
    ai_ready = _ai_ready(ai_config)

    from concurrent.futures import ThreadPoolExecutor, as_completed

    logger.info(f"开始快速总金额抽取: {len(pdf_paths)} 个 PDF")
    # 规则抽取需要所有页面才能得到完整总额，AI 抽取只读首页
    all_pages = _extract_pdf_pages(pdf_paths)
    first_pages = [p for p in all_pages if int(p.get("page") or 1) == 1]

    # Map filename to full path for image rendering
    fname_to_path = {p.name: p for p in pdf_paths}

    # 按文件名分组所有页面，用于规则抽取
    pages_by_file: Dict[str, List[Dict[str, Any]]] = {}
    for page in all_pages:
        pages_by_file.setdefault(page["source_file"], []).append(page)

    # Pre-render images for PDFs with empty text (image-based PDFs)
    image_pages_map: Dict[str, Dict[str, Any]] = {}
    empty_text_pages = [p for p in first_pages if not p.get("text", "").strip()]
    if ai_ready and empty_text_pages:
        empty_pdf_paths = [fname_to_path[p["source_file"]] for p in empty_text_pages if p["source_file"] in fname_to_path]
        if empty_pdf_paths:
            try:
                image_pages = _render_pdf_pages_to_images(empty_pdf_paths, scale=_effective_render_scale(ai_config))
                for img in image_pages:
                    key = img.get("source_file", "")
                    if key not in image_pages_map:
                        image_pages_map[key] = img
            except Exception:
                pass  # Corrupt or unrenderable PDFs will fall through to 0.0

    prompt = (
        "From this invoice page, extract ONLY two values as strict JSON:\n"
        "1. total_amount: the invoice total/balance due (a number, no currency symbol)\n"
        "2. warehouse_id: the warehouse/dept number if visible (e.g. CA#3 → 3), else empty string\n\n"
        "Return format: {\"total_amount\": <actual_number>, \"warehouse_id\": \"<actual_id_or_empty>\"}\n"
        "Extract the REAL values from the invoice. Return only the JSON, no extra text."
    )

    def _extract_one(page: Dict[str, Any]) -> Dict[str, Any]:
        """提取单个 PDF 的总金额。优先规则抽取，其次缓存，最后 AI。"""
        source_file = page.get("source_file", "")
        page_text = page.get("text", "")
        filename_wh = _warehouse_id_from_filename(source_file)
        text_wh = _warehouse_id_from_text(page_text) if page_text else ""
        wh = filename_wh or text_wh
        conflict = _warehouse_id_conflict(source_file, page_text)
        file_pages = pages_by_file.get(source_file, [])
        file_text = "\n".join(p.get("text", "") for p in file_pages) or page_text
        pdf_type = _classify_pdf(source_file, file_text)
        has_employee_detail = _has_employee_detail_signal(file_text)

        def _result(total_amount: float, warehouse_id: str = "") -> Dict[str, Any]:
            payload = {
                "source_file": source_file,
                "total_amount": total_amount,
                "warehouse_id": warehouse_id or wh,
                "pdf_type": pdf_type,
            }
            if has_employee_detail:
                payload["has_employee_detail"] = True
            if conflict:
                # 文件名和正文仓库号冲突时不静默吞掉，交给仓库核对/质量诊断提示人工复核。
                payload["warehouse_conflict"] = conflict
            return payload

        # 1. 优先取发票明确写出的总计。部分供应商的员工行逐行四舍五入后
        # 会与底部发票总计相差几分钱，仓库/总账结论应以发票总计为准。
        if any(p.get("text", "").strip() for p in file_pages):
            text_total = _extract_invoice_total_from_text(file_text)
            if text_total > 0:
                return _result(text_total)

            # 2. 发票没有可识别总计时，再从所有页面解析员工明细并求和。
            rule_rows: List[LaborLineItem] = []
            for p in file_pages:
                rule_rows.extend(_extract_description_qty_rate_invoice_rows(p, supplier=supplier, period_start="", period_end="", currency=""))
                rule_rows.extend(_extract_wage_code_invoice_rows(p, supplier=supplier, period_start="", period_end="", currency=""))
                rule_rows.extend(_extract_bill_rate_invoice_rows(p, supplier=supplier, period_start="", period_end="", currency=""))
                rule_rows.extend(_extract_regular_rate_amount_invoice_rows(p, supplier=supplier, period_start="", period_end="", currency=""))
                rule_rows.extend(_extract_elga_invoice_detail_rows(p, supplier=supplier, period_start="", period_end="", currency=""))
                rule_rows.extend(_extract_bill_rate_summary_invoice_rows(p, supplier=supplier, period_start="", period_end="", currency=""))
                rule_rows.extend(_extract_vertical_invoice_rows(p, supplier=supplier, period_start="", period_end="", currency=""))
                if not rule_rows:
                    rule_rows.extend(_extract_tabular_invoice_rows(p, supplier=supplier, period_start="", period_end="", currency=""))
            if rule_rows:
                total = round(sum(r.amount for r in rule_rows), 2)
                return _result(total)

        # 3. 检查缓存
        source_path = fname_to_path.get(source_file)
        if source_path:
            cached = _load_totals_cache(source_path, ai_config)
            if cached is not None:
                return _result(cached["total_amount"], cached.get("warehouse_id", wh))

        # 4. AI 抽取（文本或图片）
        if not ai_ready:
            return _result(0.0)
        if not page_text.strip():
            img_data = image_pages_map.get(source_file)
            if img_data and img_data.get("base64"):
                try:
                    amount = _extract_total_with_ai_image(img_data, prompt, ai_config)
                    result = {"total_amount": amount, "warehouse_id": wh}
                    if source_path:
                        _save_totals_cache(source_path, ai_config, result)
                    return _result(amount, wh)
                except Exception:
                    pass
            return _result(0.0)
        try:
            amount = _extract_total_with_ai(page_text, prompt, ai_config)
            result = {"total_amount": amount, "warehouse_id": wh}
            if source_path:
                _save_totals_cache(source_path, ai_config, result)
            return _result(amount, wh)
        except Exception:
            return _result(0.0)

    results = [None] * len(first_pages)
    # AI 调用并发数降到 2，避免 MiMo 服务限流导致全部卡死
    max_workers = min(len(first_pages), int(ai_config.get("parallel_max_workers", 2)))
    logger.info(f"快速总金额抽取: {len(first_pages)} 个 PDF, 并发数={max_workers}")
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_idx = {executor.submit(_extract_one, page): i for i, page in enumerate(first_pages)}
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                results[idx] = future.result()
                logger.info(f"  PDF {idx+1}/{len(first_pages)} 完成: {results[idx].get('source_file','?')} -> {results[idx].get('total_amount', 0)}")
            except Exception as exc:
                logger.error(f"  PDF {idx+1}/{len(first_pages)} 失败: {exc}")
                results[idx] = {"source_file": first_pages[idx].get("source_file", ""), "total_amount": 0.0, "warehouse_id": ""}
    return results


def _page_evidence_prompt() -> str:
    return (
        "Return exactly one minified JSON object that classifies this page and extracts payable invoice-total evidence. "
        "page_role must be invoice_primary, invoice_continuation, invoice_total, email_cover, timecard_summary, "
        "daily_detail, supporting_attachment, or unknown. Invoice pages may contain employee payable charge rows with "
        "LAST NAME, FIRST NAME, REGULAR HRS, OVER TIME HRS, Bill Rate, AMOUNT, Invoice #, or a payable TOTAL; do not "
        "misclassify those rows as daily_detail. daily_detail/timecard pages instead show attendance dates, shifts, "
        "working hours, or overtime without payable Bill Rate and AMOUNT columns. On French invoices, distinguish "
        "TOTAL HT (pre-tax net total), TVA (tax), and TOTAL TTC (gross payable total); when employee line amounts are "
        "HT, return TOTAL HT as total_amount and preserve TOTAL HT as total_label. Also return separately visible "
        "net_amount (HT/pre-tax), tax_amount (TVA/tax), and gross_amount (TTC/amount due); never derive or calculate "
        "one from the others. Set total_amount only for a visible "
        "payable invoice TOTAL, Amount Due, Balance Due, or a visibly complete invoice line sum. Never copy schema "
        "placeholders or values from these instructions. Use null when evidence is absent. Required schema: "
        "{\"page_role\":null,\"role_confidence\":null,\"warehouse_id\":null,\"total_amount\":null,"
        "\"total_label\":null,\"net_amount\":null,\"tax_amount\":null,\"gross_amount\":null,"
        "\"evidence_text\":null}."
    )


def _extract_rule_total_rows_from_page(
    page: Dict[str, Any],
    *,
    supplier: str = "",
) -> List[LaborLineItem]:
    """Return deterministic payable rows used by total and page-evidence gates."""
    rows: List[LaborLineItem] = []
    for extractor in (
        _extract_description_qty_rate_invoice_rows,
        _extract_wage_code_invoice_rows,
        _extract_bill_rate_invoice_rows,
        _extract_regular_rate_amount_invoice_rows,
        _extract_elga_invoice_detail_rows,
        _extract_bill_rate_summary_invoice_rows,
        _extract_vertical_invoice_rows,
    ):
        rows.extend(
            extractor(
                page,
                supplier=supplier,
                period_start="",
                period_end="",
                currency="",
            )
        )
    return rows


def _has_deterministic_payable_rows(page: Dict[str, Any]) -> bool:
    if _extract_rule_total_rows_from_page(page):
        return True
    if _extract_voyage_invoice_rows(
        page,
        supplier="",
        period_start="",
        period_end="",
        currency="",
    ):
        return True
    return bool(
        _extract_tabular_invoice_rows(
            page,
            supplier="",
            period_start="",
            period_end="",
            currency="",
        )
    )


def _text_page_evidence(page: Dict[str, Any]) -> LaborPageEvidence:
    source_file = str(page.get("source_file") or "")
    page_number = int(page.get("page") or 1)
    text = str(page.get("text") or "")
    closed_french_total = _extract_closed_french_total_row(text)
    total_amount = (
        closed_french_total["net_amount"]
        if closed_french_total is not None
        else _extract_invoice_total_from_text(text)
    )
    non_payable_role = _non_payable_page_role(source_file, text)
    has_payable_rows = False if non_payable_role else _has_deterministic_payable_rows(page)
    if non_payable_role:
        role, confidence = non_payable_role, 0.98
        total_amount = 0.0
        closed_french_total = None
    elif total_amount > 0:
        role, confidence = "invoice_total", 0.98
    elif _has_invoice_signal(source_file, text) or has_payable_rows:
        role, confidence = ("invoice_primary" if page_number == 1 else "invoice_continuation"), 0.95
    else:
        role, confidence = "unknown", 0.5
    label_match = re.search(
        r"\b(amount\s+due|balance\s+due|grand\s+total|invoice\s+total|total\s+due|net\s+total|"
        r"total\s+neto|nettosumme|gesamt|totals?)\b",
        text,
        re.IGNORECASE,
    )
    return LaborPageEvidence(
        source_file=source_file,
        page=page_number,
        role=role,
        role_confidence=confidence,
        warehouse_id=_warehouse_id_from_filename(source_file) or _warehouse_id_from_text(text),
        total_amount=total_amount if total_amount > 0 else None,
        total_label=(
            "TOTAL HT"
            if closed_french_total is not None
            else label_match.group(1) if total_amount > 0 and label_match else ""
        ),
        net_amount=closed_french_total["net_amount"] if closed_french_total is not None else None,
        tax_amount=closed_french_total["tax_amount"] if closed_french_total is not None else None,
        gross_amount=closed_french_total["gross_amount"] if closed_french_total is not None else None,
        evidence_text=text[:500],
        extraction_method=(
            "text_closed_french_total_row"
            if closed_french_total is not None
            else "text_explicit_total"
            if total_amount > 0
            else "text_payable_line_rows"
            if has_payable_rows
            else "text_page_classification"
        ),
    )


def _apply_filename_non_payable_override(
    source_file: str,
    page_evidence: LaborPageEvidence,
) -> LaborPageEvidence:
    """Keep strong non-payable filename signals ahead of AI page classification."""
    role = _non_payable_page_role(source_file, "")
    if not role:
        return page_evidence
    return LaborPageEvidence(
        source_file=page_evidence.source_file or source_file,
        page=page_evidence.page,
        role=role,
        role_confidence=1.0,
        warehouse_id=page_evidence.warehouse_id,
        evidence_text=page_evidence.evidence_text,
        extraction_method=f"{page_evidence.extraction_method}:filename_non_payable_override",
    )


def _select_rule_total_evidence(
    source_file: str,
    evidence_pages: List[LaborPageEvidence],
    pages: List[Dict[str, Any]],
    supplier: str,
    profile: Dict[str, List[str]],
):
    invoice_page_numbers = {
        evidence.page
        for evidence in evidence_pages
        if evidence.role in {"invoice_primary", "invoice_continuation", "invoice_total"}
    }
    if not invoice_page_numbers:
        return select_invoice_evidence(source_file, evidence_pages, profile=profile)
    rule_rows: List[LaborLineItem] = []
    for page in pages:
        if int(page.get("page") or 1) not in invoice_page_numbers:
            continue
        rule_rows.extend(_extract_rule_total_rows_from_page(page, supplier=supplier))
        if not rule_rows:
            rule_rows.extend(_extract_tabular_invoice_rows(page, supplier=supplier, period_start="", period_end="", currency=""))
    invoice_pages = [page for page in evidence_pages if page.role in {"invoice_primary", "invoice_continuation", "invoice_total"}]
    if not rule_rows or not invoice_pages:
        return select_invoice_evidence(source_file, evidence_pages, profile=profile)
    target = invoice_pages[-1]
    replacement = LaborPageEvidence(
        source_file=target.source_file,
        page=target.page,
        role=target.role,
        role_confidence=target.role_confidence,
        warehouse_id=target.warehouse_id,
        total_amount=round(sum(row.amount for row in rule_rows), 2),
        evidence_text="Complete invoice line sum from deterministic extraction.",
        extraction_method="complete_invoice_line_sum",
    )
    return select_invoice_evidence(
        source_file,
        [replacement if page == target else page for page in evidence_pages],
        profile=profile,
    )


def _invoice_evidence_result(evidence, source_file: str, file_text: str) -> Dict[str, Any]:
    selected_page = next((page for page in evidence.page_evidence if page.page == evidence.total_page), None)
    result = {
        "source_file": source_file,
        "total_amount": round(float(evidence.total_amount or 0.0), 2),
        "warehouse_id": evidence.warehouse_id,
        "pdf_type": _classify_pdf(source_file, file_text),
        "authoritative": evidence.authoritative,
        "evidence_status": evidence.evidence_status,
        "total_page": evidence.total_page,
        "total_label": selected_page.total_label if selected_page else "",
        "page_evidence": [asdict(page) for page in evidence.page_evidence],
        "excluded_pages": list(evidence.excluded_pages),
    }
    if _has_employee_detail_signal(file_text):
        result["has_employee_detail"] = True
    conflict = _warehouse_id_conflict(source_file, file_text)
    if not conflict:
        filename_warehouse_id = _warehouse_id_from_filename(source_file)
        page_warehouse_ids = sorted({
            page.warehouse_id.strip()
            for page in evidence.page_evidence
            if page.warehouse_id.strip() and page.warehouse_id.strip() != filename_warehouse_id
        })
        if filename_warehouse_id and page_warehouse_ids:
            conflict = {
                "source_file": source_file,
                "filename_warehouse_id": filename_warehouse_id,
                "page_warehouse_ids": page_warehouse_ids,
            }
    if conflict:
        result.update(
            {
                "total_amount": 0.0,
                "authoritative": False,
                "evidence_status": "needs_review",
                "total_page": None,
                "total_label": "",
            }
        )
        result["warehouse_conflict"] = conflict
    return result


def _extract_total_with_ai(page_text: str, prompt: str, ai_config: Dict[str, Any]) -> float:
    """Call AI to extract total amount from a single page text."""
    provider = str(ai_config.get("provider") or "").lower()
    base_url = ai_config["base_url"].rstrip("/")

    if provider == "mimo" and "token-plan" in base_url:
        return _extract_total_anthropic(page_text, prompt, ai_config)

    payload = {
        "model": ai_config["model"],
        "messages": [
            {"role": "system", "content": "Extract invoice total as JSON only."},
            {"role": "user", "content": f"{prompt}\n\nInvoice text:\n{page_text[:3000]}"},
        ],
        "temperature": 0,
        "max_completion_tokens": 256,
    }
    _apply_provider_options(payload, ai_config)
    data = _http_post_json(f"{base_url}/chat/completions", _request_headers(ai_config), payload)
    return _parse_total_from_response(data["choices"][0]["message"]["content"])


def _extract_total_anthropic(page_text: str, prompt: str, ai_config: Dict[str, Any]) -> float:
    """Anthropic Messages API variant for total extraction."""
    headers = {
        "x-api-key": str(ai_config["api_key"]),
        "anthropic-version": "2023-06-01",
    }
    payload = {
        "model": ai_config["model"],
        "max_tokens": 4096,
        "system": "Respond ONLY with valid JSON. Do not think step by step. Extract invoice total as JSON only.",
        "messages": [{"role": "user", "content": f"{prompt}\n\nInvoice text:\n{page_text[:3000]}"}],
    }
    base_url = ai_config["base_url"].rstrip("/")
    data = _http_post_json(_anthropic_messages_url(ai_config), headers, payload)
    content = ""
    thinking = ""
    for block in data.get("content", []):
        if block.get("type") == "text":
            content += block["text"]
        elif block.get("type") == "thinking":
            thinking += block.get("thinking", "")
    if not content.strip() and thinking:
        content = thinking
    return _parse_total_from_response(content)


def _extract_total_with_ai_image(page: Dict[str, Any], prompt: str, ai_config: Dict[str, Any]) -> float:
    """Extract total amount from image-based PDF using vision API."""
    provider = str(ai_config.get("provider") or "").lower()
    base_url = ai_config["base_url"].rstrip("/")
    model = ai_config.get("model") or "mimo-v2.5"

    if provider == "mimo" and "token-plan" in base_url:
        # Anthropic Messages API with image
        headers = {
            "x-api-key": str(ai_config["api_key"]),
            "anthropic-version": "2023-06-01",
        }
        payload = {
            "model": model,
            "max_tokens": 4096,
            "system": "Respond ONLY with valid JSON. Do not think step by step. Extract invoice total as JSON only.",
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": f"{prompt}\n\nExtract the total amount from this invoice image. Return ONLY the JSON object."},
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": page.get("mime_type", "image/png"),
                            "data": page["base64"],
                        },
                    },
                ],
            }],
        }
        data = _http_post_json(_anthropic_messages_url(ai_config), headers, payload)
        content = ""
        thinking = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                content += block["text"]
            elif block.get("type") == "thinking":
                thinking += block.get("thinking", "")
        if not content.strip() and thinking:
            content = thinking
        return _parse_total_from_response(content)

    # OpenAI-compatible API with image
    payload = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": f"{prompt}\n\nExtract the total amount from this invoice image."},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{page.get('mime_type', 'image/png')};base64,{page['base64']}"},
                },
            ],
        }],
        "temperature": 0,
        "max_tokens": 256,
    }
    _apply_provider_options(payload, ai_config)
    data = _http_post_json(f"{base_url}/chat/completions", _request_headers(ai_config), payload)
    return _parse_total_from_response(data["choices"][0]["message"]["content"])


def _extract_page_evidence_with_ai_image(
    page: Dict[str, Any],
    prompt: str,
    ai_config: Dict[str, Any],
) -> LaborPageEvidence:
    """Extract the approved page-evidence contract from one rendered page."""
    provider = str(ai_config.get("provider") or "").lower()
    base_url = str(ai_config["base_url"]).rstrip("/")
    model = ai_config.get("model") or "mimo-v2.5"
    reasoning = ""
    if provider == "mimo" and "token-plan" in base_url:
        payload = {
            "model": model,
            "max_tokens": 4096,
            "system": "Respond ONLY with the requested valid JSON object.",
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image", "source": {"type": "base64", "media_type": page.get("mime_type", "image/png"), "data": page["base64"]}},
                ],
            }],
        }
        data = _http_post_json(
            _anthropic_messages_url(ai_config),
            {"x-api-key": str(ai_config["api_key"]), "anthropic-version": "2023-06-01"},
            payload,
        )
        content = "".join(str(block.get("text") or "") for block in data.get("content", []) if block.get("type") == "text")
        reasoning = "".join(str(block.get("thinking") or "") for block in data.get("content", []) if block.get("type") == "thinking")
    else:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "Return only the requested minified JSON object. Do not repeat the instructions."},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:{page.get('mime_type', 'image/png')};base64,{page['base64']}"}},
                    ],
                },
            ],
            "temperature": 0,
            "max_tokens": max(int(ai_config.get("page_evidence_max_tokens") or 256), 128),
        }
        _apply_provider_options(payload, ai_config)
        data = _http_post_json(f"{base_url}/chat/completions", _request_headers(ai_config), payload)
        message = data["choices"][0]["message"]
        content = str(message.get("content") or "")
        reasoning = str(message.get("reasoning_content") or "")

    parsed = _parse_page_evidence_object(content, reasoning)
    total_value = parsed.get("total_amount", parsed.get("totalAmount"))
    total_amount = _parse_page_evidence_amount(total_value) if total_value not in (None, "") else None
    evidence_text = str(parsed.get("evidence_text", parsed.get("evidenceText", "")) or "")
    total_label = str(parsed.get("total_label", parsed.get("totalLabel", "")) or "")
    if total_amount and not _evidence_text_supports_total(evidence_text, total_amount):
        total_amount = None
        total_label = ""
    supported_amounts: Dict[str, float | None] = {}
    for snake_name, camel_name in (
        ("net_amount", "netAmount"),
        ("tax_amount", "taxAmount"),
        ("gross_amount", "grossAmount"),
    ):
        raw_value = parsed.get(snake_name, parsed.get(camel_name))
        parsed_amount = _parse_page_evidence_amount(raw_value) if raw_value not in (None, "") else None
        supported_amounts[snake_name] = (
            parsed_amount
            if parsed_amount and parsed_amount > 0 and _evidence_text_contains_amount(evidence_text, parsed_amount)
            else None
        )
    confidence = _parse_role_confidence(parsed.get("role_confidence", parsed.get("roleConfidence", 0)))
    return LaborPageEvidence(
        source_file=str(page.get("source_file") or ""),
        page=int(page.get("page") or 1),
        role=str(parsed.get("page_role", parsed.get("pageRole", "unknown")) or "unknown"),
        role_confidence=confidence,
        warehouse_id=str(
            _normalize_warehouse_id_candidate(parsed.get("warehouse_id", parsed.get("warehouseId", "")))
            or _warehouse_id_from_filename(str(page.get("source_file") or ""))
            or ""
        ),
        total_amount=total_amount if total_amount and total_amount > 0 else None,
        total_label=total_label,
        net_amount=supported_amounts["net_amount"],
        tax_amount=supported_amounts["tax_amount"],
        gross_amount=supported_amounts["gross_amount"],
        evidence_text=evidence_text,
        extraction_method="ai_page_evidence",
    )


_BOTTOM_TOTAL_AMOUNT_RE = re.compile(
    r"(?:\d{1,3}(?:[ .\u00a0,]\d{3})+[.,]\d{2}|\d+[.,]\d{2})"
)


def _extract_closed_french_total_row(text: str, tolerance: float = 0.10) -> Dict[str, float] | None:
    """Read an HT/tax/TTC footer row from PDF text only when its arithmetic closes."""
    normalized = unicodedata.normalize("NFKC", str(text or "")).replace("\u00a0", " ")
    normalized_labels = re.sub(r"(?<=[A-Za-z])\.(?=[A-Za-z])", "", normalized)
    if not (
        re.search(r"\btotal\s+ht\b", normalized_labels, re.IGNORECASE)
        and re.search(r"\b(?:tva|vat|taxe)\b", normalized_labels, re.IGNORECASE)
        and re.search(r"\btotal\s+ttc\b", normalized_labels, re.IGNORECASE)
    ):
        return None

    closures: set[tuple[float, float, float]] = set()
    for line in normalized.splitlines():
        if not re.search(r"EUR\b", line, re.IGNORECASE):
            continue
        monetary_line = re.sub(r"\b\d{1,2}/\d{1,2}/\d{4}\b", "", line)
        amounts = [
            round(_parse_page_evidence_amount(token), 2)
            for token in _BOTTOM_TOTAL_AMOUNT_RE.findall(monetary_line)
        ]
        if len(amounts) < 3:
            continue
        gross_amount = amounts[-1]
        for net_index, net_amount in enumerate(amounts[:-2]):
            for tax_amount in amounts[net_index + 1:-1]:
                if net_amount > 0 and tax_amount > 0 and abs(net_amount + tax_amount - gross_amount) <= tolerance:
                    closures.add((net_amount, tax_amount, gross_amount))
    if len(closures) != 1:
        return None
    net_amount, tax_amount, gross_amount = next(iter(closures))
    return {
        "net_amount": net_amount,
        "tax_amount": tax_amount,
        "gross_amount": gross_amount,
    }


def _parse_bottom_total_ocr_text(text: str, tolerance: float = 0.10) -> Dict[str, float] | None:
    """Parse a visible HT/TVA/TTC block and accept it only when it closes."""
    normalized = unicodedata.normalize("NFKC", str(text or "")).replace("\u00a0", " ")
    normalized = re.sub(r"(?<=[A-Za-z])\.(?=[A-Za-z])", "", normalized)

    def _amount_candidates(label: str, next_label: str, *, reject_rate_label: bool = False) -> set[float]:
        values: set[float] = set()
        for match in re.finditer(
            rf"(?:{label})(?P<body>[^\n]*?)(?=(?:{next_label})|$)",
            normalized,
            re.IGNORECASE | re.MULTILINE,
        ):
            if reject_rate_label:
                prefix = normalized[max(0, match.start() - 12):match.start()]
                if re.search(r"taux\s*$", prefix, re.IGNORECASE):
                    continue
            tokens = _BOTTOM_TOTAL_AMOUNT_RE.findall(match.group("body"))
            if tokens:
                value = _parse_page_evidence_amount(tokens[-1])
                if value > 0:
                    values.add(round(value, 2))
        return values

    net_candidates = _amount_candidates(
        r"\btotal\s+h\.?\s*t\.?\b",
        r"\b(?:tva|vat|taxe)\b|\btotal\s+t\.?\s*t\.?\s*c\.?\b",
    )
    tax_candidates = _amount_candidates(
        r"\b(?:tva|vat|taxe)\b",
        r"\btotal\s+t\.?\s*t\.?\s*c\.?\b",
        reject_rate_label=True,
    )
    gross_candidates = _amount_candidates(
        r"\btotal\s+t\.?\s*t\.?\s*c\.?\b(?:\s+global)?",
        r"(?!)",
    )
    closures = {
        (net_amount, tax_amount, gross_amount)
        for net_amount in net_candidates
        for tax_amount in tax_candidates
        for gross_amount in gross_candidates
        if abs(net_amount + tax_amount - gross_amount) <= tolerance
    }
    if len(closures) != 1:
        return None
    net_amount, tax_amount, gross_amount = next(iter(closures))
    return {
        "net_amount": net_amount,
        "tax_amount": tax_amount,
        "gross_amount": gross_amount,
    }


def _bottom_total_crop(page: Dict[str, Any]) -> Dict[str, Any] | None:
    """Crop and enhance the bottom 32% of a rendered invoice page."""
    try:
        from PIL import Image, ImageEnhance, ImageOps

        image = Image.open(BytesIO(base64.b64decode(str(page.get("base64") or "")))).convert("RGB")
        width, height = image.size
        if width <= 0 or height <= 0:
            return None
        cropped = image.crop((0, int(height * 0.68), width, height))
        grayscale = ImageOps.grayscale(cropped)
        enhanced = ImageEnhance.Contrast(grayscale).enhance(1.4)
        buffer = BytesIO()
        enhanced.save(buffer, format="PNG")
    except Exception:
        return None
    return {
        **page,
        "mime_type": "image/png",
        "base64": base64.b64encode(buffer.getvalue()).decode("ascii"),
        "bottom_total_crop": True,
    }


def _extract_bottom_total_evidence_with_ai_ocr(
    page: Dict[str, Any],
    ai_config: Dict[str, Any],
) -> LaborPageEvidence | None:
    """Transcribe only the bottom total area, then validate it deterministically."""
    cropped_page = _bottom_total_crop(page)
    if cropped_page is None:
        return None
    prompt = (
        "OCR the visible invoice summary area exactly. Return plain text only. "
        "Preserve labels and numbers, especially TOTAL HT, TVA, and TOTAL TTC. "
        "Write each visible total label followed by its corresponding visible amount on the same line. "
        "Do not calculate, infer, explain, translate, or return JSON."
    )
    provider = str(ai_config.get("provider") or "").lower()
    base_url = str(ai_config["base_url"]).rstrip("/")
    model = ai_config.get("model") or "mimo-v2.5"
    if provider == "mimo" and "token-plan" in base_url:
        payload = {
            "model": model,
            "max_tokens": 1024,
            "system": "Return only exact OCR transcription from the supplied crop.",
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": cropped_page["mime_type"],
                            "data": cropped_page["base64"],
                        },
                    },
                ],
            }],
        }
        data = _http_post_json(
            _anthropic_messages_url(ai_config),
            {"x-api-key": str(ai_config["api_key"]), "anthropic-version": "2023-06-01"},
            payload,
        )
        content = "".join(
            str(block.get("text") or "")
            for block in data.get("content", [])
            if block.get("type") == "text"
        )
        if not content.strip():
            content = "".join(
                str(block.get("thinking") or "")
                for block in data.get("content", [])
                if block.get("type") == "thinking"
            )
    else:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "Return only exact OCR transcription from the supplied crop."},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{cropped_page['mime_type']};base64,{cropped_page['base64']}"
                            },
                        },
                    ],
                },
            ],
            "temperature": 0,
            "max_tokens": 512,
        }
        _apply_provider_options(payload, ai_config)
        data = _http_post_json(f"{base_url}/chat/completions", _request_headers(ai_config), payload)
        message = data["choices"][0]["message"]
        content = str(message.get("content") or message.get("reasoning_content") or "")
    closure = _parse_bottom_total_ocr_text(content)
    if closure is None:
        return None
    evidence_text = (
        f"TOTAL HT {closure['net_amount']:.2f}; "
        f"TVA {closure['tax_amount']:.2f}; "
        f"TOTAL TTC {closure['gross_amount']:.2f}"
    )
    return LaborPageEvidence(
        source_file=str(page.get("source_file") or ""),
        page=int(page.get("page") or 1),
        role="invoice_total",
        role_confidence=0.99,
        warehouse_id=_warehouse_id_from_filename(str(page.get("source_file") or "")) or "",
        total_amount=closure["net_amount"],
        total_label="TOTAL HT",
        net_amount=closure["net_amount"],
        tax_amount=closure["tax_amount"],
        gross_amount=closure["gross_amount"],
        evidence_text=evidence_text,
        extraction_method="bottom_total_ocr",
    )


def _parse_page_evidence_object(content: str, reasoning: str = "") -> Dict[str, Any]:
    parsed = _first_json_object(content)
    if parsed:
        return parsed

    stripped_reasoning = str(reasoning or "").strip()
    if stripped_reasoning:
        try:
            exact = json.loads(stripped_reasoning)
        except json.JSONDecodeError:
            exact = None
        if isinstance(exact, dict):
            return exact

    tail = stripped_reasoning[-1400:].lower()
    if not tail:
        return {}
    strong_invoice = (
        any(
            phrase in tail
            for phrase in (
                "clearly an invoice",
                "document is an invoice",
                "looks like an invoice",
                "invoice_primary",
                "complete invoice page",
            )
        )
        or all(signal in tail for signal in ("invoice", "bill rate", "amount"))
    )
    total_match = None
    if strong_invoice:
        total_match = _last_labeled_total_match(stripped_reasoning)

    if "not an invoice" in tail and ("timecard" in tail or "attendance summary" in tail):
        role = "timecard_summary"
    elif strong_invoice:
        role = "invoice_total" if "invoice_total" in tail or "invoice total page" in tail else "invoice_primary"
    elif "email" in tail and ("attachment" in tail or "attached" in tail):
        role = "email_cover"
    elif "supporting attachment" in tail or "supporting document" in tail:
        role = "supporting_attachment"
    elif "daily_detail" in tail or "daily attendance" in tail or "attendance date" in tail:
        role = "daily_detail"
    else:
        role = "unknown"
    result = {
        "page_role": role,
        "role_confidence": 0.95 if strong_invoice else (0.9 if role != "unknown" else 0.0),
        "evidence_text": total_match.group(0) if total_match is not None else "",
    }
    if total_match is not None:
        result["total_amount"] = parse_number(total_match.group(2))
        result["total_label"] = total_match.group(1)
    return result


def _labeled_total_matches(text: str) -> list[re.Match[str]]:
    return list(re.finditer(
        r"\b(grand\s+total|invoice\s+total|amount\s+due|balance\s+due|net\s+total|"
        r"total\s+ht|total\s+ttc|total\s+neto|nettosumme|gesamt|total(?:\s+due)?)\b"
        r"[^\d.,\n]{0,48}[€$]?\s*((?:\d{1,3}(?:[ ,.]\d{3})+[.,]\d{2}|\d+[.,]\d{2}))",
        str(text or ""),
        re.IGNORECASE,
    ))


def _last_labeled_total_match(text: str) -> re.Match[str] | None:
    matches = _labeled_total_matches(text)
    return matches[-1] if matches else None


def _evidence_text_supports_total(evidence_text: str, total_amount: float) -> bool:
    return any(
        abs(_parse_page_evidence_amount(match.group(2)) - total_amount) <= 0.005
        for match in _labeled_total_matches(evidence_text)
    )


def _evidence_text_contains_amount(evidence_text: str, amount: float) -> bool:
    tokens = re.findall(r"(?:\d{1,3}(?:[ ,.\u00a0]\d{3})+[.,]\d{2}|\d+[.,]\d{2})", str(evidence_text or ""))
    return any(abs(_parse_page_evidence_amount(token) - amount) <= 0.005 for token in tokens)


def _parse_page_evidence_amount(value: Any) -> float:
    text = str(value or "").strip().replace(" ", "")
    if "," in text and "." not in text and re.search(r",\d{2}$", text):
        text = text.replace(",", ".")
    elif "," in text and "." in text and text.rfind(",") > text.rfind("."):
        text = text.replace(".", "").replace(",", ".")
    return parse_number(text)


def _parse_role_confidence(value: Any) -> float:
    labels = {
        "very high": 0.98,
        "high": 0.95,
        "medium": 0.75,
        "low": 0.4,
    }
    normalized = str(value or "").strip().lower().replace("_", " ")
    if normalized in labels:
        return labels[normalized]
    try:
        return min(max(float(value or 0), 0.0), 1.0)
    except (TypeError, ValueError):
        return 0.0


def _first_json_object(content: str) -> Dict[str, Any]:
    text = str(content or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        return parsed

    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            candidate, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            return candidate
    return {}


def _parse_total_from_response(content: str) -> float:
    """Extract total_amount number from AI response."""
    if not content or not content.strip():
        return 0.0
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            return parse_number(parsed.get("total_amount"))
    except json.JSONDecodeError:
        match = re.search(r'"total_amount"\s*:\s*([\d,]+\.?\d*)', content)
        if match:
            return parse_number(match.group(1))
    return 0.0


def _ai_ready(ai_config: Dict[str, Any]) -> bool:
    return bool(
        ai_config.get("external_ai_enabled") is not False
        and ai_config.get("enabled")
        and ai_config.get("api_key")
        and ai_config.get("base_url")
        and ai_config.get("model")
    )


def _safe_error_message(exc: Exception) -> str:
    if isinstance(exc, HTTPError):
        body = exc.read().decode("utf-8", "ignore")
        if body:
            try:
                payload = json.loads(body)
                detail = payload.get("error", payload)
                if isinstance(detail, dict):
                    message = str(detail.get("message") or detail.get("detail") or body)
                else:
                    message = str(detail)
            except json.JSONDecodeError:
                message = body
            return f"HTTP {exc.code} {message}"[:300]
    message = str(exc)
    if len(message) > 300:
        message = message[:300] + "..."
    return message or exc.__class__.__name__


def _extract_pdf_pages(pdf_paths: List[Path], max_pages: int | None = None) -> List[Dict[str, Any]]:
    pages: List[Dict[str, Any]] = []
    try:
        from pypdf import PdfReader
    except Exception:
        PdfReader = None
    for path in pdf_paths:
        if PdfReader is None:
            pages.append({"source_file": path.name, "source_path": str(path), "page": 1, "text": ""})
            continue
        try:
            reader = PdfReader(str(path))
            page_count = len(reader.pages) if max_pages is None else min(len(reader.pages), max_pages)
            for index in range(page_count):
                pages.append({"source_file": path.name, "source_path": str(path), "page": index + 1, "text": reader.pages[index].extract_text() or ""})
        except Exception:
            pages.append({"source_file": path.name, "source_path": str(path), "page": 1, "text": ""})
    return pages


def _extract_with_ai_text(
    pages: List[Dict[str, Any]],
    ai_config: Dict[str, Any],
    supplier: str = "",
    period_start: str = "",
    period_end: str = "",
    currency: str = "",
    supplier_profile: SupplierExtractionProfile | None = None,
    expected_rows: List[Dict[str, Any]] | None = None,
    retry_mode: bool = False,
    target_names: list[str] | None = None,
) -> List[Dict[str, Any]]:
    prompt = {
        "instruction": _ai_instruction(supplier_profile, retry_mode=retry_mode, target_names=target_names),
        "supplier": supplier,
        "period_start": period_start,
        "period_end": period_end,
        "currency": currency,
        "pages": pages,
    }
    if expected_rows:
        prompt["expected_employees"] = expected_rows
    payload = {
        "model": ai_config["model"],
        "messages": [
            {"role": "system", "content": "You extract payroll invoice tables into JSON only."},
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ],
        "temperature": 0,
        "max_completion_tokens": int(ai_config.get("max_completion_tokens") or 8192),
    }
    _apply_provider_options(payload, ai_config)
    return _normalize_ai_rows(_ai_call_with_retry(payload, ai_config), supplier=supplier, period_start=period_start, period_end=period_end, currency=currency, default_confidence=float(ai_config.get("default_confidence", 0.7)))


def _analyze_layout_with_ai(
    pages: List[Dict[str, Any]],
    ai_config: Dict[str, Any],
    *,
    supplier: str = "",
    currency: str = "",
) -> InvoiceLayoutPlan:
    page_summaries = [
        {
            "source_file": page.get("source_file", ""),
            "page": page.get("page", ""),
            "text": (page.get("text") or "")[:5000],
        }
        for page in pages[:3]
    ]
    prompt = {
        "instruction": (
            "Analyze the labor invoice table layout. Return one JSON object inside an array. "
            "Do not extract employee rows. Choose recommended_parser only from: "
            "simple_invoice_table, line_item_text_table, ai_assisted. "
            "Return fields: layout_type, recommended_parser, confidence, "
            "employee_name_pattern, hours_columns, amount_column, total_label, "
            "warehouse_source, evidence."
            "Use line_item_text_table only when each text line contains one employee "
            "and the same line also contains hours and a payable amount."
        ),
        "supplier": supplier,
        "currency": currency,
        "pages": page_summaries,
    }
    payload = {
        "model": ai_config["model"],
        "messages": [
            {"role": "system", "content": "You classify invoice table layouts into parser plans."},
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ],
        "temperature": 0,
        "max_completion_tokens": min(int(ai_config.get("max_completion_tokens") or 2048), 2048),
    }
    _apply_provider_options(payload, ai_config)
    rows = _ai_call_with_retry(payload, ai_config)
    if not rows:
        return InvoiceLayoutPlan(layout_type="unknown", recommended_parser="ai_assisted", confidence=0.0)
    return layout_plan_from_dict(rows[0])


def _image_prompt_text(
    image_instruction: str,
    supplier: str,
    currency: str,
    expected_rows: List[Dict[str, Any]] | None,
) -> str:
    prompt_text = image_instruction
    if supplier:
        prompt_text += f"\nSupplier: {supplier}"
    if currency:
        prompt_text += f"\nCurrency: {currency}"
    if expected_rows:
        names = [r.get("employee_name", "") for r in expected_rows[:80] if r.get("employee_name")]
        prompt_text += (
            "\nExpected employees for this batch: " + ", ".join(names) +
            "\nReturn only employees visibly present in the invoice image and plausibly matching this list. "
            "If no listed employee is visible, return [] exactly. Do not invent placeholder names."
        )
    return prompt_text


def _image_chunk_payload(chunk: List[Dict[str, Any]], prompt_text: str, ai_config: Dict[str, Any]) -> Dict[str, Any]:
    content: List[Dict[str, Any]] = [_image_content_part(page, ai_config) for page in chunk]
    content.append({"type": "text", "text": prompt_text})
    payload = {
        "model": ai_config["model"],
        "messages": [
            {"role": "system", "content": "You extract employee data from invoice images as JSON arrays."},
            {"role": "user", "content": content},
        ],
        "temperature": 0,
        "max_completion_tokens": int(ai_config.get("max_completion_tokens") or 4096),
    }
    _apply_provider_options(payload, ai_config)
    return payload


def _preview_normalized_image_rows(
    rows: List[Dict[str, Any]],
    *,
    supplier: str,
    period_start: str,
    period_end: str,
    currency: str,
    ai_config: Dict[str, Any],
    expected_rows: List[Dict[str, Any]] | None,
) -> List[Dict[str, Any]]:
    normalized = _normalize_ai_rows(
        rows,
        supplier=supplier,
        period_start=period_start,
        period_end=period_end,
        currency=currency,
        default_confidence=float(ai_config.get("default_confidence", 0.7)),
    )
    if expected_rows:
        normalized = _filter_ai_rows_by_expected_employees(normalized, expected_rows)
    return normalized


def _record_image_page_audit(
    audit_collector: List[Dict[str, Any]] | None,
    chunk: List[Dict[str, Any]],
    status: str,
    normalized_rows: List[Dict[str, Any]],
    *,
    from_cache: bool = False,
    error: str = "",
) -> None:
    if audit_collector is None:
        return
    for page in chunk:
        source_file = str(page.get("source_file") or "")
        page_number = page.get("page")
        page_ref = f"p{page_number}"
        page_rows: List[Dict[str, Any]] = []
        for row in normalized_rows:
            row_source = str(row.get("source_file") or row.get("sourceFile") or "")
            row_page = str(row.get("source_page_or_row") or row.get("sourcePageOrRow") or "")
            if len(chunk) == 1:
                if (not row_source or row_source == source_file) and (not row_page or row_page == page_ref):
                    page_rows.append(row)
            elif row_source == source_file and row_page == page_ref:
                page_rows.append(row)
        entry: Dict[str, Any] = {
            "sourceFile": source_file,
            "page": page_number,
            "status": status,
            "rowCount": len(page_rows),
            "amountTotal": round(sum(_fuzzy_get_amount(row) for row in page_rows), 2),
            "renderScale": page.get("render_scale"),
            "fromCache": bool(from_cache),
            "highResolutionRetry": bool(page.get("high_resolution_retry")),
        }
        if error:
            entry["error"] = error[:300]
        audit_collector.append(entry)


def _high_resolution_retry_scale(page: Dict[str, Any], ai_config: Dict[str, Any]) -> float:
    current = float(page.get("render_scale") or _effective_render_scale(ai_config) or 1.0)
    configured = float(ai_config.get("high_resolution_retry_scale") or 2.4)
    max_scale = float(ai_config.get("high_resolution_retry_max_scale") or 3.0)
    return min(max(configured, current * 1.75), max_scale)


def _should_high_resolution_retry(
    chunk: List[Dict[str, Any]],
    normalized_rows: List[Dict[str, Any]],
    ai_config: Dict[str, Any],
) -> bool:
    if ai_config.get("high_resolution_retry_enabled") is False:
        return False
    if normalized_rows:
        return False
    if len(chunk) != 1:
        return False
    page = chunk[0]
    if page.get("high_resolution_retry"):
        return False
    return bool(page.get("source_path") and page.get("page"))


def _extract_with_ai_images(
    image_pages: List[Dict[str, Any]],
    ai_config: Dict[str, Any],
    supplier: str = "",
    period_start: str = "",
    period_end: str = "",
    currency: str = "",
    supplier_profile: SupplierExtractionProfile | None = None,
    expected_rows: List[Dict[str, Any]] | None = None,
    retry_mode: bool = False,
    target_names: list[str] | None = None,
    progress_callback: ProgressCallback | None = None,
    audit_collector: List[Dict[str, Any]] | None = None,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    max_pages = _effective_max_pages_per_request(ai_config)

    # 智能页面筛选：无 Profile 时 AI 判断有效页
    image_pages = _select_invoice_pages(image_pages, ai_config, supplier_profile)
    total_pages = len(image_pages)
    processed_pages = 0
    if progress_callback:
        progress_callback(
            {
                "event": "ai_image_start",
                "total_pages": total_pages,
                "processed_pages": processed_pages,
            }
        )

    # 图片抽取使用简化的 prompt，避免模型返回空结果
    image_instruction = _ai_instruction(supplier_profile, for_image=True, retry_mode=retry_mode, target_names=target_names)
    prompt_text = _image_prompt_text(image_instruction, supplier, currency, expected_rows)

    logger.info(f"[D] _extract_with_ai_images: {len(image_pages)} 张图片, max_pages={max_pages}")
    configured_retry_delays = ai_config.get("image_retry_delays")
    retry_delays = [5, 15, 30] if configured_retry_delays is None else list(configured_retry_delays)

    def _request_chunk(chunk_pages: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], Exception | None]:
        payload = _image_chunk_payload(chunk_pages, prompt_text, ai_config)
        last_exc = None
        for attempt in range(1 + len(retry_delays)):  # 首次 + 3次重试 = 最多4次
            try:
                extracted_rows = _post_chat_completion(payload, ai_config)
                from .runtime_metrics import record_labor_runtime_metric
                record_labor_runtime_metric("model_call", status="succeeded")
                return _annotate_image_rows(extracted_rows, chunk_pages), None
            except Exception as exc:  # A single provider/page failure must not abort the batch.
                from .runtime_metrics import record_labor_runtime_metric
                record_labor_runtime_metric("model_call", status="failed")
                last_exc = exc
                if attempt < len(retry_delays):
                    delay = retry_delays[attempt]
                    sources = ", ".join(f"{page.get('source_file')}#p{page.get('page')}" for page in chunk_pages)
                    logger.warning(f"AI 抽取失败，{delay}s 后重试 (attempt {attempt+1}/{1+len(retry_delays)}): {sources}; error={exc}")
                    if progress_callback:
                        current_page = chunk_pages[0] if chunk_pages else {}
                        progress_callback(
                            {
                                "event": "ai_image_page_retrying",
                                "total_pages": total_pages,
                                "processed_pages": processed_pages,
                                "current_file": current_page.get("source_file") or "",
                                "current_page": current_page.get("page"),
                                "retry_delay_seconds": delay,
                                "retry_attempt": attempt + 1,
                            }
                        )
                    import time as _time
                    _time.sleep(delay)
        return [], last_exc

    for start in range(0, len(image_pages), max_pages):
        chunk = image_pages[start : start + max_pages]
        logger.info(f"[D] 处理 chunk: {len(chunk)} 张图片 (index {start}-{start+len(chunk)-1})")
        current_page = chunk[0] if chunk else {}
        if progress_callback:
            progress_callback(
                {
                    "event": "ai_image_page_started",
                    "total_pages": total_pages,
                    "processed_pages": processed_pages,
                    "current_file": current_page.get("source_file") or "",
                    "current_page": current_page.get("page"),
                    "chunk_pages": len(chunk),
                }
            )
        cached = _load_ai_page_cache(chunk, ai_config)
        if cached is not None:
            extracted = _annotate_image_rows(cached, chunk)
            from_cache = True
            last_exc = None
        else:
            extracted, last_exc = _request_chunk(chunk)
            from_cache = False
        if last_exc is not None:
            sources = ", ".join(f"{page.get('source_file')}#p{page.get('page')}" for page in chunk)
            logger.warning(f"AI 图片抽取跳过超时/解析失败页面（已重试{len(retry_delays)}次）: {sources}; last={last_exc}")
            _record_image_page_audit(audit_collector, chunk, "failed", [], from_cache=False, error=_safe_error_message(last_exc))
            processed_pages = min(processed_pages + len(chunk), total_pages)
            if progress_callback:
                progress_callback(
                    {
                        "event": "ai_image_page_skipped",
                        "total_pages": total_pages,
                        "processed_pages": processed_pages,
                        "current_file": current_page.get("source_file") or "",
                        "current_page": current_page.get("page"),
                    }
                )
            continue
        if not from_cache:
            _save_ai_page_cache(chunk, ai_config, extracted)

        normalized_preview = _preview_normalized_image_rows(
            extracted,
            supplier=supplier,
            period_start=period_start,
            period_end=period_end,
            currency=currency,
            ai_config=ai_config,
            expected_rows=expected_rows,
        )
        _record_image_page_audit(
            audit_collector,
            chunk,
            "cache_hit" if from_cache else "completed",
            normalized_preview,
            from_cache=from_cache,
        )
        if _should_high_resolution_retry(chunk, normalized_preview, ai_config):
            page = chunk[0]
            retry_scale = _high_resolution_retry_scale(page, ai_config)
            if progress_callback:
                progress_callback(
                    {
                        "event": "ai_image_high_res_retrying",
                        "total_pages": total_pages,
                        "processed_pages": processed_pages,
                        "current_file": page.get("source_file") or "",
                        "current_page": page.get("page"),
                    }
                )
            retry_page = _render_pdf_page_to_image(Path(str(page.get("source_path"))), int(page.get("page") or 1), retry_scale)
            if retry_page:
                retry_extracted, retry_exc = _request_chunk([retry_page])
                retry_normalized = _preview_normalized_image_rows(
                    retry_extracted,
                    supplier=supplier,
                    period_start=period_start,
                    period_end=period_end,
                    currency=currency,
                    ai_config=ai_config,
                    expected_rows=expected_rows,
                )
                if retry_exc is None and retry_normalized:
                    extracted = retry_extracted
                    normalized_preview = retry_normalized
                    _save_ai_page_cache(chunk, ai_config, extracted)
                    _record_image_page_audit(audit_collector, [retry_page], "high_res_retry_applied", retry_normalized)
                    logger.info(
                        "AI 图片高清重试成功: %s#p%s, rows=%s",
                        page.get("source_file"),
                        page.get("page"),
                        len(retry_normalized),
                    )
                else:
                    _record_image_page_audit(
                        audit_collector,
                        [retry_page],
                        "high_res_retry_no_rows" if retry_exc is None else "high_res_retry_failed",
                        retry_normalized,
                        error=_safe_error_message(retry_exc) if retry_exc else "",
                    )
            else:
                _record_image_page_audit(audit_collector, chunk, "high_res_retry_render_failed", [], from_cache=False)

        rows.extend(extracted)
        processed_pages = min(processed_pages + len(chunk), total_pages)
        if progress_callback:
            progress_callback(
                {
                    "event": "ai_image_page_completed",
                    "total_pages": total_pages,
                    "processed_pages": processed_pages,
                    "current_file": current_page.get("source_file") or "",
                    "current_page": current_page.get("page"),
                    "from_cache": from_cache,
                }
            )
    normalized = _normalize_ai_rows(rows, supplier=supplier, period_start=period_start, period_end=period_end, currency=currency, default_confidence=float(ai_config.get("default_confidence", 0.7)))
    normalized = [
        row
        for row in normalized
        if str(row.get("source_file") or row.get("sourceFile") or "").strip()
    ]
    normalized = _drop_closed_employee_subtotals(normalized)
    if expected_rows:
        normalized = _filter_ai_rows_by_expected_employees(normalized, expected_rows)
    return normalized


def _annotate_image_rows(rows: List[Dict[str, Any]], chunk: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if len(chunk) != 1:
        return rows
    page = chunk[0]
    source_file = page.get("source_file") or ""
    source_page = f"p{page.get('page')}"
    annotated: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        current = dict(row)
        current["source_file"] = current.get("source_file") or current.get("sourceFile") or source_file
        current["source_page_or_row"] = current.get("source_page_or_row") or current.get("sourcePageOrRow") or source_page
        annotated.append(current)
    return annotated

_AI_RETRY_DELAYS = [5, 15, 30]  # 退避等待秒数
_AI_EXC_TYPES = (json.JSONDecodeError, TimeoutError, socket.timeout, URLError, MiMoTimeoutException, httpx.TimeoutException)


def _ai_call_with_retry(payload: Dict[str, Any], ai_config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """调用 AI API，失败时自动重试（最多 3 次退避重试）"""
    last_exc = None
    for attempt in range(1 + len(_AI_RETRY_DELAYS)):
        try:
            result = _post_chat_completion(payload, ai_config)
            from .runtime_metrics import record_labor_runtime_metric
            record_labor_runtime_metric("model_call", status="succeeded")
            return result
        except _AI_EXC_TYPES as exc:
            from .runtime_metrics import record_labor_runtime_metric
            record_labor_runtime_metric("model_call", status="failed")
            last_exc = exc
            if attempt < len(_AI_RETRY_DELAYS):
                delay = _AI_RETRY_DELAYS[attempt]
                logger.warning(f"AI 调用失败，{delay}s 后重试 (attempt {attempt+1}/{1+len(_AI_RETRY_DELAYS)}): {exc}")
                import time as _time
                _time.sleep(delay)
    raise last_exc  # type: ignore[misc]


def _post_chat_completion(payload: Dict[str, Any], ai_config: Dict[str, Any]) -> List[Dict[str, Any]]:
    provider = str(ai_config.get("provider") or "").lower()
    base_url = ai_config["base_url"].rstrip("/")

    if provider == "mimo" and "token-plan" in base_url:
        # MiMo token plan uses Anthropic Messages API format
        logger.info(f"[D] 发起 MiMo/Anthropic API 请求 (via _post_chat_completion)")
        return _post_anthropic_completion(payload, ai_config)

    # Standard OpenAI-compatible format
    data = _http_post_json(f"{base_url}/chat/completions", _request_headers(ai_config), payload)
    content = data["choices"][0]["message"]["content"]
    return _json_array(content)


class MiMoTimeoutException(Exception):
    """Raised when MiMo API request exceeds timeout."""
    pass


# (moved to top of file — see after imports)


def _post_anthropic_completion(payload: Dict[str, Any], ai_config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Call MiMo token plan using Anthropic Messages API format.

    Handles thinking blocks correctly and enforces strict 45s timeout.
    """
    # Convert OpenAI-style payload to Anthropic Messages format
    system_msg = ""
    messages = []
    for msg in payload.get("messages", []):
        if msg["role"] == "system":
            system_msg = msg["content"]
        elif msg["role"] == "user":
            content = msg["content"]
            if isinstance(content, str):
                messages.append({"role": "user", "content": content})
            elif isinstance(content, list):
                # Image+text multimodal content
                anthropic_content = []
                for part in content:
                    if part.get("type") == "text":
                        anthropic_content.append({"type": "text", "text": part["text"]})
                    elif part.get("type") == "image_url":
                        url = part["image_url"]["url"]
                        if url.startswith("data:"):
                            media_type, b64 = url.split(",", 1)
                            media_type = media_type.split(":")[1].split(";")[0]
                            anthropic_content.append({
                                "type": "image",
                                "source": {"type": "base64", "media_type": media_type, "data": b64},
                            })
                    elif part.get("type") == "image" and part.get("source"):
                        anthropic_content.append(part)
                messages.append({"role": "user", "content": anthropic_content})

    # Build Anthropic payload — NO thinking field (causes gateway deadlock)
    # Use max_tokens=4096 + strict system prompt to control output
    anthropic_payload = {
        "model": payload.get("model", "mimo-v2.5"),
        "max_tokens": 4096,
        "messages": messages,
    }
    if system_msg:
        anthropic_payload["system"] = system_msg + " Respond ONLY with valid JSON. Do not think step by step."
    else:
        anthropic_payload["system"] = "Respond ONLY with valid JSON. Do not think step by step."

    headers = {
        "x-api-key": str(ai_config["api_key"]),
        "anthropic-version": "2023-06-01",
    }
    base_url = ai_config["base_url"].rstrip("/")

    data = _http_post_json(_anthropic_messages_url(ai_config), headers, anthropic_payload)

    stop_reason = data.get("stop_reason", "?")
    usage = data.get("usage", {})
    logger.info(f"[E] Anthropic 响应: stop_reason={stop_reason}, in={usage.get('input_tokens',0)}, out={usage.get('output_tokens',0)}")

    # ── ROBUST CONTENT EXTRACTION: handle both text and thinking blocks ──
    content = ""
    thinking = ""
    for block in data.get("content", []):
        block_type = block.get("type", "")
        if block_type == "text":
            content += block.get("text", "")
        elif block_type == "thinking":
            thinking += block.get("thinking", "")
        else:
            logger.warning(f"[E] 未知 block 类型: {block_type}")

    # Fallback: if no text but thinking exists, try to extract JSON from thinking
    if not content.strip() and thinking:
        logger.warning(f"[E] 无 text 内容，尝试从 thinking 中提取 ({len(thinking)} 字符)")
        content = thinking

    if not content.strip():
        logger.warning(f"[E] Anthropic 响应完全为空, blocks={[b.get('type') for b in data.get('content',[])]}")
        return []
    return _json_array(content)


def _request_headers(ai_config: Dict[str, Any]) -> Dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if str(ai_config.get("provider") or "").lower() == "mimo":
        headers["api-key"] = str(ai_config["api_key"])
    else:
        headers["Authorization"] = f"Bearer {ai_config['api_key']}"
    return headers


def _apply_provider_options(payload: Dict[str, Any], ai_config: Dict[str, Any]) -> None:
    # Do NOT set thinking=disabled — it causes the MiMo gateway to deadlock
    # Instead, rely on max_tokens + system prompt constraints
    pass


def _is_token_plan(ai_config: Dict[str, Any]) -> bool:
    """Check if using MiMo token plan (no vision support)."""
    provider = str(ai_config.get("provider") or "").lower()
    base_url = str(ai_config.get("base_url") or "")
    return provider == "mimo" and "token-plan" in base_url


def _image_content_part(page: Dict[str, Any], ai_config: Dict[str, Any]) -> Dict[str, Any]:
    mime_type = page.get("mime_type", "image/png")
    b64_data = page["base64"]
    if _is_token_plan(ai_config):
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": mime_type,
                "data": b64_data,
            },
        }
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{mime_type};base64,{b64_data}"},
    }


def _ai_instruction(
    supplier_profile: SupplierExtractionProfile | None = None,
    for_image: bool = False,
    retry_mode: bool = False,
    target_names: list[str] | None = None,
) -> str:
    """生成 AI 抽取的 prompt 指令。

    Args:
        supplier_profile: 供应商专属 Profile，含 prompt_notes
        for_image: 是否为图片抽取模式（使用更简洁的 prompt）
        retry_mode: 是否为重试模式（针对低置信度行重新抽取）
        target_names: 重试模式下需要重点关注的员工姓名列表
    """
    if for_image:
        # 图片抽取使用更简洁的 prompt，避免模型返回空结果
        instruction = (
            "Extract all employee/associate rows from this invoice image as a JSON array. "
            "Each row must have these fields: employee_name_raw, description, item_type, quantity, unit, hours, amount, currency, confidence, evidence_text. "
            "Rules:\n"
            "- employee_name_raw: ONLY the person's full name (e.g. 'Lopez, Elizabeth'). "
            "Do NOT include job codes, candidate IDs, shift types, or any other text after the name. "
            "If the row shows 'Lopez, Elizabeth CUE1PK2 19905 8.00...', extract ONLY 'Lopez, Elizabeth'.\n"
            "- description: visible charge/service label from that row\n"
            "- item_type: worked_hours, meal_allowance, transport_allowance, bonus, allowance, expense, other, or unknown\n"
            "- quantity: visible billed quantity, which may be meals, days, kilometers, items, or hours\n"
            "- unit: visible quantity unit; use hour only when the quantity is actually worked time\n"
            "- hours: total worked hours only; meal counts, ticket counts, days, kilometers, and other quantities must be 0 here\n"
            "- amount: total billed amount in dollars\n"
            "- currency: USD or currency shown in invoice\n"
            "- confidence: 0.95 for clear rows, 0.85 for minor issues\n"
            "- evidence_text: the original text snippet with name and amount\n"
            "Ignore headers, footers, subtotals, summary rows (like 'Workforce Shift', 'Flexible Workforce Shift'), and non-employee rows. "
            "Return ONLY the JSON array, no explanations."
        )
    else:
        instruction = (
            "Extract labor invoice employee rows as a strict JSON array. "
            "Each row must include source_file, source_page_or_row, employee_id, employee_name_raw, description, item_type, quantity, unit, hours, amount, currency, confidence, evidence_text. "
            "Spatial calibration: first identify page orientation, table boundaries, column headers, and row alignment before extracting. "
            "Only extract rows spatially aligned under employee/name, hours, amount, and total/charge columns in the same table. "
            "Ignore handwriting, margin notes, barcodes, page numbers, headers, footers, subtotals, and timesheet-only pages. "
            "Return only employee charge rows, not invoice totals or headers. "
            "If a page has no clear employee charge rows, return [] exactly. "
            "employee_name_raw must be ONLY the person's visible name (e.g. 'Lopez, Elizabeth' or 'John Smith'). "
            "Do NOT include job codes (like CUE1PK2, B1), candidate IDs, shift types (Packer Shift, Forklift Shift), or any other non-name text. "
            "If the row shows 'Lopez, Elizabeth CUE1PK2 19905 8.00...', extract ONLY 'Lopez, Elizabeth'. "
            "Do NOT extract summary/category rows like 'Workforce Shift', 'Flexible Workforce Shift', 'Open, Open' as employee names. "
            "employee_id must be empty unless a separate visible employee ID column/value exists next to that person; never copy a name, barcode, invoice number, account number, or long numeric string into employee_id. "
            "If a premium/meal row has amount but no worked hours, use hours 0 and keep the amount. "
            "Keep visible non-time quantities in quantity/unit, never in hours. Use item_type worked_hours only for actual worked time; otherwise use meal_allowance, transport_allowance, bonus, allowance, expense, other, or unknown. "
            "If expected_employees is provided, use it only as a reconciliation candidate list: search the invoice for those visible employees, return only rows that are actually visible, preserve the visible PDF names, choose the row total billed amount, and return [] for candidates not found. "
            "Confidence scoring: use 0.95+ for clear, unambiguous rows; 0.85-0.94 for rows with minor OCR issues or formatting variations; 0.70-0.84 for rows requiring interpretation; below 0.70 only for highly uncertain extractions. "
            "Evidence text: include the original text snippet that supports the extraction, including dollar signs, amounts, and employee names. "
            "Currency: use the currency symbol or code visible in the invoice (USD, EUR, etc.); if not visible, use the provided currency parameter. "
            "Error handling: if you encounter unclear or ambiguous data, make your best interpretation and assign lower confidence; do not skip rows that are likely valid. "
            "Warehouse identification: if the page contains a warehouse/dept identifier (e.g. DEPT:CA#3, DEPT:CA-27, warehouse code), include it as warehouse_id field in each row. Extract only the numeric part (e.g. DEPT:CA#3 -> 3, DEPT:CA-27 -> 27). If no warehouse identifier is visible, set warehouse_id to empty string. "
            "Output format: return ONLY the JSON array, no additional text, explanations, or markdown formatting."
        )
    # 重试模式：追加重点关注员工名单
    if retry_mode and target_names:
        names_str = ", ".join(target_names[:20])  # 最多20个名字，避免 prompt 过长
        source_hint = "invoice image" if for_image else "invoice document"
        instruction += (
            f" RETRY MODE: Focus specifically on extracting data for these employees: {names_str}. "
            f"Re-examine the {source_hint} carefully for these names — they may have been missed or extracted with low confidence in a previous pass. "
            "Pay extra attention to name spelling, amount alignment, and row boundaries."
        )
    if supplier_profile and supplier_profile.prompt_notes:
        instruction += " Supplier-specific profile guidance: " + " ".join(supplier_profile.prompt_notes)
    if supplier_profile and supplier_profile.line_item_aliases:
        aliases = ", ".join(
            f"{label} => {item_type}"
            for label, item_type in sorted(supplier_profile.line_item_aliases.items())
        )
        instruction += f" Confirmed line-item label mappings: {aliases}."
    return instruction


# 清洗员工名：去掉 AI 误带的工号、岗位后缀等
# 匹配 "Last, First" 格式的姓名（最可靠的模式）
# Last: 字母+空格（如 "Palacios Villo", "St"）
# First: 字母（如 "Elizabeth", "Juan"）
# 遇到全大写token（工号如CUE1PK2）或纯数字（候选ID）就停止
_NAME_COMMA_RE = re.compile(r"^([A-Za-z][A-Za-z .'-]*,\s*[A-Za-z][a-z .'-]+)")
# 岗位关键词（用于过滤）
_SHIFT_KEYWORDS = re.compile(
    r"\b(?:Packer|Forklift|Loader|Loaders|Shipping|Receiving|Material\s*Handler|Workforce|Flexible|Shift|Bonus|Differential)\b",
    re.IGNORECASE,
)
# 非员工名的关键词
_NON_EMPLOYEE_NAMES = {
    "workforce shift", "flexible workforce shift", "open, open",
    "employee name", "name", "total", "totals", "subtotal",
    "office payroll", "supplemental payroll", "payroll capture",
}


def _clean_employee_name(raw_name: str) -> str:
    """清洗员工名，去掉工号、岗位后缀等非姓名内容。

    处理 AI 抽取时误带的工号（如 CUE1PK2）、候选人ID、岗位后缀等。
    """
    name = raw_name.strip()
    if not name:
        return name

    # 过滤明显的非员工名
    if name.lower().strip() in _NON_EMPLOYEE_NAMES:
        return ""

    # 优先提取 "Last, First" 格式
    m = _NAME_COMMA_RE.match(name)
    if m:
        result = m.group(1).strip()
        # 二次检查：提取后可能是非员工名（如 "Open, Open Open B Bonus Nov" → "Open, Open"）
        if result.lower() in _NON_EMPLOYEE_NAMES:
            return ""
        return result

    # 没有逗号的名字（如 "John Smith", "Antonio CUE LD"）
    # 先去掉岗位关键词
    name = _SHIFT_KEYWORDS.sub("", name).strip()
    # 再去掉尾部的大写 token（工号如 CUE, LD, FL, B1）
    parts = name.split()
    while len(parts) > 1:
        tail = parts[-1]
        if tail.isupper() and len(tail) <= 4:  # 短大写 token = 工号
            parts.pop()
            continue
        break
    return " ".join(parts).strip()


def _normalize_ai_rows(
    rows: List[Dict[str, Any]],
    supplier: str,
    period_start: str,
    period_end: str,
    currency: str,
    default_confidence: float = 0.7,
) -> List[Dict[str, Any]]:
    """标准化 AI 抽取结果。

    Args:
        default_confidence: AI 未返回 confidence 时的默认值，从 AI_CONFIG["default_confidence"] 读取
    """
    normalized = []
    for i, row in enumerate(rows):
        employee_name = _fuzzy_get_name(row)
        if not employee_name:
            logger.warning(f"行{i}: 无员工姓名, 原始数据: {json.dumps({k:v for k,v in row.items() if v}, ensure_ascii=False)[:200]}")
            continue
        # 清洗员工名：去掉工号、岗位后缀等
        cleaned_name = _clean_employee_name(employee_name)
        if not cleaned_name:
            continue
        employee_name = cleaned_name

        # 行级过滤：丢弃明显非员工行
        # 1. 名字过短（< 2字符）或过长（> 40字符）
        if len(employee_name) < 2 or len(employee_name) > 40:
            continue
        # 2. hours 和 amount 都为 0 的行（无效数据）
        hours_val = parse_number(row.get("hours"))
        amount_val = parse_number(row.get("amount"))
        if hours_val == 0 and amount_val == 0:
            continue

        if not _looks_like_employee_row(employee_name, row):
            continue
        current = dict(row)
        # Normalize key names to canonical form
        current["employee_name_raw"] = employee_name
        current["hours"] = _fuzzy_get_hours(row)
        current["amount"] = _fuzzy_get_amount(row)
        current["source_type"] = current.get("source_type") or current.get("sourceType") or "pdf_invoice"
        current["source_page_or_row"] = current.get("source_page_or_row") or current.get("sourcePageOrRow") or "p?"
        current["currency"] = current.get("currency") or currency
        current["supplier"] = current.get("supplier") or supplier
        current["period_start"] = current.get("period_start") or current.get("periodStart") or period_start
        current["period_end"] = current.get("period_end") or current.get("periodEnd") or period_end
        current["confidence"] = current.get("confidence") if current.get("confidence") is not None else default_confidence
        normalized.append(current)
    return normalized


_EMPLOYEE_SUBTOTAL_RE = re.compile(r"(?:\bs\s*/\s*total\b|\bsous[-\s]?total\b|\bsubtotal\b|小计)", re.IGNORECASE)


def _drop_closed_employee_subtotals(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Drop an employee subtotal only when nearby component rows close exactly.

    Image extraction can see charge lines at the bottom of one page and repeat
    the employee subtotal at the top of the next page. Keeping both doubles the
    same charge. The strong subtotal label plus amount/hour closure keeps this
    conservative for suppliers whose invoice contains legitimate repeated rows.
    """

    def _name_key(row: Dict[str, Any]) -> str:
        raw = str(
            row.get("employee_name_raw")
            or row.get("employeeNameRaw")
            or row.get("employee_name")
            or row.get("employeeName")
            or ""
        )
        normalized = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode("ascii")
        return re.sub(r"[^a-z0-9]+", "", normalized.lower())

    def _page_number(row: Dict[str, Any]) -> int | None:
        match = re.search(r"\bp\s*(\d+)\b", str(row.get("source_page_or_row") or row.get("sourcePageOrRow") or ""), re.IGNORECASE)
        return int(match.group(1)) if match else None

    def _is_subtotal(row: Dict[str, Any]) -> bool:
        text = " ".join(
            str(row.get(key) or "")
            for key in ("description", "evidence_text", "evidenceText")
        )
        return bool(_EMPLOYEE_SUBTOTAL_RE.search(text))

    drop_indexes: set[int] = set()
    for index, subtotal in enumerate(rows):
        if not _is_subtotal(subtotal):
            continue
        source = str(subtotal.get("source_file") or subtotal.get("sourceFile") or "").strip()
        name = _name_key(subtotal)
        subtotal_page = _page_number(subtotal)
        if not source or not name or subtotal_page is None:
            continue
        components = [
            row
            for candidate_index, row in enumerate(rows)
            if candidate_index != index
            and not _is_subtotal(row)
            and str(row.get("source_file") or row.get("sourceFile") or "").strip() == source
            and _name_key(row) == name
            and _page_number(row) in {subtotal_page - 1, subtotal_page}
        ]
        if len(components) < 2:
            continue
        subtotal_amount = parse_number(subtotal.get("amount"))
        component_amount = round(sum(parse_number(row.get("amount")) for row in components), 2)
        if subtotal_amount <= 0 or abs(subtotal_amount - component_amount) > 0.10:
            continue
        subtotal_hours = parse_number(subtotal.get("hours"))
        component_hours = round(sum(parse_number(row.get("hours")) for row in components), 3)
        if subtotal_hours > 0 and component_hours > 0 and abs(subtotal_hours - component_hours) > 0.05:
            continue
        drop_indexes.add(index)
        logger.info(
            "忽略跨页重复员工小计: %s %s#p%s amount=%.2f",
            subtotal.get("employee_name_raw") or subtotal.get("employeeNameRaw") or "",
            source,
            subtotal_page,
            subtotal_amount,
        )
    return [row for index, row in enumerate(rows) if index not in drop_indexes]


def _filter_ai_rows_by_page_text(rows: List[Dict[str, Any]], pages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Reject AI rows that have no name/evidence support in an extractable text layer."""
    text_pages = [page for page in pages if (page.get("text") or "").strip()]
    if not text_pages:
        return rows

    normalized_pages = [
        {
            "source_file": page.get("source_file") or "",
            "source_page_or_row": f"p{page.get('page')}",
            "text": _normalize_support_text(page.get("text") or ""),
        }
        for page in text_pages
    ]
    text_sources = {page["source_file"] for page in normalized_pages}
    filtered: List[Dict[str, Any]] = []
    for row in rows:
        name = str(row.get("employee_name_raw") or row.get("employeeNameRaw") or row.get("employee_name") or row.get("employeeName") or "")
        evidence = str(row.get("evidence_text") or row.get("evidenceText") or "")
        name_key = _normalize_support_text(name)
        evidence_key = _normalize_support_text(evidence)
        if not name_key:
            continue
        row_source = str(row.get("source_file") or row.get("sourceFile") or "")
        if row_source and row_source not in text_sources:
            filtered.append(dict(row))
            continue
        matched_page = None
        for page in normalized_pages:
            if row_source and page["source_file"] != row_source:
                continue
            page_text = page["text"]
            if (
                name_key in page_text
                or (evidence_key and evidence_key in page_text)
                or _fuzzy_name_supported_by_page_text(name_key, page_text)
            ):
                matched_page = page
                break
        if not matched_page:
            logger.warning(f"AI 抽取行缺少 PDF 文本证据，已丢弃: {name}")
            continue
        current = dict(row)
        current["source_file"] = current.get("source_file") or current.get("sourceFile") or matched_page["source_file"]
        current["source_page_or_row"] = current.get("source_page_or_row") or current.get("sourcePageOrRow") or matched_page["source_page_or_row"]
        filtered.append(current)
    return filtered


def _normalize_support_text(value: str) -> str:
    value = unicodedata.normalize("NFD", value)
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def _fuzzy_name_supported_by_page_text(name_key: str, page_text: str) -> bool:
    """Confirm a multi-token AI name against small OCR/text-layer typos."""
    name_tokens = [token for token in name_key.split() if len(token) >= 3]
    page_tokens = [token for token in page_text.split() if len(token) >= 3]
    if len(name_tokens) < 2 or not page_tokens:
        return False
    token_scores = [
        max(SequenceMatcher(None, name_token, page_token).ratio() for page_token in page_tokens)
        for name_token in name_tokens
    ]
    return min(token_scores) >= 0.84


def _filter_ai_rows_by_expected_employees(rows: List[Dict[str, Any]], expected_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """扫描件无文本证据时，用 Excel 候选名单拦截图片 AI 幻觉员工。"""
    expected_names = [str(row.get("employee_name") or "").strip() for row in expected_rows if row.get("employee_name")]
    if not expected_names:
        return rows
    filtered: List[Dict[str, Any]] = []
    for row in rows:
        name = _fuzzy_get_name(row)
        if any(_matches_expected_employee(name, expected) for expected in expected_names):
            filtered.append(row)
            continue
        logger.warning(f"AI 图片抽取员工不在本批 Excel 候选名单中，已丢弃: {name}")
    return filtered


def _matches_expected_employee(left: str, right: str) -> bool:
    left_norm = normalize_workbuddy_name(left)
    right_norm = normalize_workbuddy_name(right)
    left_tokens = set(left_norm.split())
    right_tokens = set(right_norm.split())
    if not left_tokens or not right_tokens:
        return False
    token_score = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
    char_score = SequenceMatcher(None, left_norm, right_norm).ratio()
    if token_score >= 0.30 or char_score >= 0.78:
        return True
    # Keep a visible invoice name when every Excel name token has a strong
    # spelling counterpart, even if the invoice includes an extra surname.
    # This covers OCR/vendor variants such as BANTSIMBA/BATSIMBA without
    # weakening the hallucination gate to unrelated names.
    if len(right_tokens) < 2:
        return False
    expected_token_scores = [
        max(SequenceMatcher(None, expected, candidate).ratio() for candidate in left_tokens)
        for expected in right_tokens
    ]
    return min(expected_token_scores) >= 0.88


def _looks_like_employee_row(employee_name: str, row: Dict[str, Any]) -> bool:
    amount = _fuzzy_get_amount(row)
    if amount == 0:
        return False
    # Accept if name has >= 3 alpha characters (covers CJK names too)
    letters = re.findall(r"[A-Za-z一-鿿À-ÖØ-öø-ÿ]", employee_name)
    if len(letters) < 2:
        return False
    # Reject obvious non-names (pure codes like "RG-40", "OT-0.42")
    if re.fullmatch(r"[A-Z]{1,4}[-\s]*\d+(?:\.\d+)?", employee_name.strip(), flags=re.IGNORECASE):
        return False
    return True


def _render_pdf_pages_to_images(
    pdf_paths: List[Path],
    scale: float = 1.2,
    max_workers: int = 4,
    allowed_pages_by_source: Dict[str, set[int]] | None = None,
) -> List[Dict[str, Any]]:
    """渲染 PDF 页面为图片。

    优化策略：
    - scale=1.2: 平衡清晰度和 token 消耗（约 690 tokens/页 vs scale=1.5 的 1073）
    - JPEG 格式: 比 PNG 小 ~70%，发票识别足够
    - 对比度增强: 提升扫描件识别率

    pypdfium2/libpdfium 在 macOS 上多线程渲染后再次渲染可能触发原生内存破坏，
    导致整个 Python 进程崩溃。这里故意串行渲染，避免后台抽取把 Web 服务带崩。
    """
    try:
        import pypdfium2 as pdfium
    except Exception as exc:
        raise RuntimeError("扫描版 PDF 需要安装 pypdfium2 才能渲染页面图片。") from exc

    from PIL import ImageEnhance

    def _render_single_pdf(path: Path) -> List[Dict[str, Any]]:
        """渲染单个 PDF 的所有页面"""
        try:
            document = pdfium.PdfDocument(str(path))
            pages = []
            try:
                for index in range(len(document)):
                    allowed_pages = (allowed_pages_by_source or {}).get(path.name)
                    if allowed_pages is not None and index + 1 not in allowed_pages:
                        continue
                    page = document[index]
                    try:
                        bitmap = page.render(scale=scale).to_pil()
                        # 图片预处理：增强对比度和锐度，提升扫描件识别率
                        bitmap = ImageEnhance.Contrast(bitmap).enhance(1.15)
                        bitmap = ImageEnhance.Sharpness(bitmap).enhance(1.1)

                        buffer = BytesIO()
                        # JPEG 格式，quality=85 平衡大小和质量
                        bitmap.save(buffer, format="JPEG", quality=85)
                        pages.append({
                            "source_file": path.name,
                            "source_path": str(path),
                            "page": index + 1,
                            "mime_type": "image/jpeg",
                            "base64": base64.b64encode(buffer.getvalue()).decode("ascii"),
                            "render_scale": scale,
                        })
                    finally:
                        page.close()
            finally:
                document.close()
            return pages
        except Exception as exc:
            logger.error(f"PDF 渲染失败: {path.name}: {exc}")
            return []

    all_image_pages: List[Dict[str, Any]] = []
    for path in pdf_paths:
        all_image_pages.extend(_render_single_pdf(path))

    return all_image_pages


def _render_pdf_page_to_image(path: Path, page_number: int, scale: float) -> Dict[str, Any] | None:
    try:
        import pypdfium2 as pdfium
    except Exception as exc:
        raise RuntimeError("扫描版 PDF 需要安装 pypdfium2 才能渲染页面图片。") from exc

    from PIL import ImageEnhance

    try:
        document = pdfium.PdfDocument(str(path))
        try:
            index = max(int(page_number) - 1, 0)
            if index >= len(document):
                return None
            page = document[index]
            try:
                bitmap = page.render(scale=scale).to_pil()
                bitmap = ImageEnhance.Contrast(bitmap).enhance(1.25)
                bitmap = ImageEnhance.Sharpness(bitmap).enhance(1.2)
                buffer = BytesIO()
                bitmap.save(buffer, format="JPEG", quality=90)
                return {
                    "source_file": path.name,
                    "source_path": str(path),
                    "page": page_number,
                    "mime_type": "image/jpeg",
                    "base64": base64.b64encode(buffer.getvalue()).decode("ascii"),
                    "render_scale": scale,
                    "high_resolution_retry": True,
                }
            finally:
                page.close()
        finally:
            document.close()
    except Exception as exc:
        logger.warning(f"PDF 单页高清渲染失败: {path.name} p{page_number}: {exc}")
        return None


def _apply_image_page_policy(image_pages: List[Dict[str, Any]], supplier_profile: SupplierExtractionProfile) -> List[Dict[str, Any]]:
    if supplier_profile.image_page_policy == "first_page_only":
        return [page for page in image_pages if int(page.get("page") or 1) == 1]
    return image_pages


def _check_profile_validity(
    supplier_profile: SupplierExtractionProfile,
    rule_rows: list,
    ai_config: dict,
) -> bool:
    """检查 Profile 是否仍然有效。

    当 Profile 存在（非 DEFAULT_PROFILE）但规则抽取返回 0 行时，
    说明供应商格式可能已变化，Profile 失效。

    Args:
        supplier_profile: 当前使用的供应商 Profile
        rule_rows: 规则抽取的结果行
        ai_config: AI 配置字典

    Returns:
        True 表示 Profile 有效，False 表示失效应回退 AI
    """
    # 无 Profile 或默认 Profile — 始终有效（无需检测）
    if not supplier_profile or supplier_profile.key == "default":
        return True

    # 规则抽取有结果 — Profile 有效
    if rule_rows:
        return True

    # Profile 存在但规则抽取 0 行 — 格式可能变化
    logger.warning(
        f"Profile '{supplier_profile.key}' 存在但规则抽取返回 0 行，"
        f"供应商格式可能已变化，回退到 AI 抽取"
    )
    return False


def _select_invoice_pages(image_pages: List[Dict[str, Any]], ai_config: Dict[str, Any], supplier_profile: SupplierExtractionProfile) -> List[Dict[str, Any]]:
    """智能页面筛选：无 Profile 时用 AI 判断哪些页面包含员工计费数据。

    仅当 supplier_profile 是 DEFAULT_PROFILE 且 image_page_policy=="all" 时触发。
    用轻量 AI 调用分析页面缩略图，返回有效页面列表。
    0 页时 fallback 返回全部页。
    """
    if not supplier_profile or supplier_profile.key != "default" or supplier_profile.image_page_policy != "all":
        return image_pages
    if not ai_config.get("smart_page_selection", True):
        return image_pages
    if not _ai_ready(ai_config):
        return image_pages
    if len(image_pages) <= 2:
        return image_pages  # 2 页以内不需要筛选

    logger.info(f"[D] 智能页面筛选: {len(image_pages)} 页待分析")
    try:
        # 构造轻量 payload：每页只发缩略图，让 AI 判断哪些页有计费表
        content: List[Dict[str, Any]] = []
        for i, page in enumerate(image_pages):
            content.append({"type": "text", "text": f"Page {i+1}:"})
            content.append(_image_content_part(page, ai_config))

        selection_prompt = (
            "You are analyzing a multi-page labor invoice PDF. "
            "For each page shown, determine if it contains an employee billing table with columns like: "
            "employee name, hours worked, and charge amounts. "
            "Return ONLY a JSON array of 1-based page numbers that contain billing data. "
            "Example: [1, 3] means pages 1 and 3 have billing tables. "
            "Ignore cover pages, summary pages, terms/conditions, and blank pages. "
            "Return ONLY the JSON array, no explanations."
        )

        payload = {
            "model": ai_config.get("model", ""),
            "messages": [{"role": "user", "content": content + [{"type": "text", "text": selection_prompt}]}],
            "max_tokens": 256,
            "temperature": 0,
        }
        result = _post_chat_completion(payload, ai_config)

        # 解析返回的页码列表
        raw_text = ""
        if isinstance(result, dict):
            choices = result.get("choices") or []
            if choices:
                msg = choices[0].get("message") or {}
                raw_text = msg.get("content") or ""

        # 提取 JSON 数组
        json_match = re.search(r'\[[\d\s,]*\]', raw_text)
        if json_match:
            page_numbers = json.loads(json_match.group())
            valid_pages = [image_pages[n - 1] for n in page_numbers if 1 <= n <= len(image_pages)]
            if valid_pages:
                logger.info(f"[D] 智能筛选结果: {len(valid_pages)}/{len(image_pages)} 页有效")
                return valid_pages

        logger.warning(f"[D] 智能筛选解析失败，回退全读。原始返回: {raw_text[:200]}")
    except Exception as exc:
        logger.warning(f"[D] 智能筛选异常，回退全读: {exc}")

    return image_pages


def _load_ai_page_cache(chunk: List[Dict[str, Any]], ai_config: Dict[str, Any]) -> List[Dict[str, Any]] | None:
    cache_path = _ai_page_cache_path(chunk, ai_config)
    if cache_path is None or not cache_path.exists():
        from .runtime_metrics import record_labor_runtime_metric
        record_labor_runtime_metric("ocr_cache", status="miss", summary={"cacheHit": False})
        return None
    try:
        rows = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(rows, list):
        return None
    if not rows and ai_config.get("retry_empty_page_cache"):
        from .runtime_metrics import record_labor_runtime_metric
        record_labor_runtime_metric("ocr_cache", status="miss", summary={"cacheHit": False})
        return None
    from .runtime_metrics import record_labor_runtime_metric
    record_labor_runtime_metric("ocr_cache", status="hit", summary={"cacheHit": True})
    return rows


def _save_ai_page_cache(chunk: List[Dict[str, Any]], ai_config: Dict[str, Any], rows: List[Dict[str, Any]]) -> None:
    cache_path = _ai_page_cache_path(chunk, ai_config)
    if cache_path is None:
        return
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        return


def _ai_page_cache_path(chunk: List[Dict[str, Any]], ai_config: Dict[str, Any]) -> Path | None:
    if len(chunk) != 1 or ai_config.get("cache_enabled") is False:
        return None
    page = chunk[0]
    source_path = page.get("source_path")
    if not source_path:
        return None
    path = Path(str(source_path))
    model = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(ai_config.get("model") or "model"))
    return path.parent / ".ai_extract_cache" / f"{path.stem}_p{page.get('page')}_{model}_{AI_PAGE_CACHE_VERSION}.json"


def _totals_cache_path(source_path: Path, ai_config: Dict[str, Any]) -> Path:
    model = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(ai_config.get("model") or "model"))
    return source_path.parent / ".ai_extract_cache" / f"{source_path.stem}_totals_{model}_{TOTALS_CACHE_VERSION}.json"


def _totals_cache_fingerprint(
    source_path: Path,
    ai_config: Dict[str, Any],
    profile: SupplierExtractionProfile,
) -> str:
    try:
        file_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
    except OSError:
        file_hash = ""
    payload = {
        "file_sha256": file_hash,
        "model": str(ai_config.get("model") or ""),
        "extraction_version": TOTALS_CACHE_VERSION,
        "profile": {
            "key": profile.key,
            "version": profile.version,
            "authoritative_total_methods": sorted(profile.authoritative_total_methods),
        },
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _load_totals_cache(
    source_path: Path,
    ai_config: Dict[str, Any],
    fingerprint: str | None = None,
) -> Dict[str, Any] | None:
    if ai_config.get("cache_enabled") is False:
        return None
    cache_path = _totals_cache_path(source_path, ai_config)
    if not cache_path.exists():
        return None
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    required_fields = {
        "authoritative", "evidence_status", "total_page", "total_label", "page_evidence", "excluded_pages", "cache_fingerprint",
    }
    if not isinstance(data, dict) or not required_fields.issubset(data):
        return None
    if not fingerprint or data.get("cache_fingerprint") != fingerprint:
        return None
    if data.get("authoritative") is not True or data.get("evidence_status") != "authoritative":
        return None
    return data


def _save_totals_cache(
    source_path: Path,
    ai_config: Dict[str, Any],
    result: Dict[str, Any],
    fingerprint: str | None = None,
) -> None:
    if (
        ai_config.get("cache_enabled") is False
        or not fingerprint
        or result.get("authoritative") is not True
        or result.get("evidence_status") != "authoritative"
    ):
        return
    cache_path = _totals_cache_path(source_path, ai_config)
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {**result, "cache_fingerprint": fingerprint}
        cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except OSError:
        return


def _json_array(content: str) -> List[Dict[str, Any]]:
    if not content or not content.strip():
        return []
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\[[\s\S]*\]", content)
        if not match:
            return []
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, list):
        return []
    return [row for row in parsed if isinstance(row, dict)]


def _extract_with_rules(pages: List[Dict[str, Any]], supplier: str, period_start: str, period_end: str, currency: str) -> List[LaborLineItem]:
    rows: List[LaborLineItem] = []
    for page in pages:
        voyage_rows = _extract_voyage_invoice_rows(
            page,
            supplier=supplier,
            period_start=period_start,
            period_end=period_end,
            currency=currency,
        )
        if voyage_rows:
            rows.extend(voyage_rows)
            continue
        layout_plan = analyze_invoice_layout([page])
        rows.extend(
            extract_rows_from_layout_plan(
                [page],
                layout_plan,
                supplier=supplier,
                period_start=period_start,
                period_end=period_end,
                currency=currency,
            )
        )
        description_rows = _extract_description_qty_rate_invoice_rows(
            page,
            supplier=supplier,
            period_start=period_start,
            period_end=period_end,
            currency=currency,
        )
        if description_rows:
            rows.extend(description_rows)
            continue
        rate_amount_rows = _extract_regular_rate_amount_invoice_rows(page, supplier=supplier, period_start=period_start, period_end=period_end, currency=currency)
        if rate_amount_rows:
            rows.extend(rate_amount_rows)
            continue
        elga_rows = _extract_elga_invoice_detail_rows(page, supplier=supplier, period_start=period_start, period_end=period_end, currency=currency)
        if elga_rows:
            rows.extend(elga_rows)
            continue
        if layout_plan.recommended_parser != "ai_assisted":
            continue
        rows.extend(_extract_wage_code_invoice_rows(page, supplier=supplier, period_start=period_start, period_end=period_end, currency=currency))
        rows.extend(_extract_bill_rate_invoice_rows(page, supplier=supplier, period_start=period_start, period_end=period_end, currency=currency))
        rows.extend(_extract_sss_employee_summary_rows(page, supplier=supplier, period_start=period_start, period_end=period_end, currency=currency))
        rows.extend(_extract_bill_rate_summary_invoice_rows(page, supplier=supplier, period_start=period_start, period_end=period_end, currency=currency))
        rows.extend(_extract_vertical_invoice_rows(page, supplier=supplier, period_start=period_start, period_end=period_end, currency=currency))
        rows.extend(_extract_tabular_invoice_rows(page, supplier=supplier, period_start=period_start, period_end=period_end, currency=currency))
        rows.extend(_extract_simple_invoice_rows(page, supplier=supplier, period_start=period_start, period_end=period_end, currency=currency))
        for line in (page.get("text") or "").splitlines():
            compact = " ".join(line.split())
            match = LINE_RE.match(compact)
            if not match:
                continue
            values = [parse_number(value) for value in NUMBER_RE.findall(match.group("rest"))]
            if len(values) < 10:
                if len(values) == 9:
                    rows.append(_line_item(page, match, hours=0.0, amount=values[-1], currency=currency, supplier=supplier, period_start=period_start, period_end=period_end, evidence_text=compact))
                continue
            hours_values = values[4:-4]
            hours = sum(hours_values)
            amount = values[-1]
            rows.append(_line_item(page, match, hours=hours, amount=amount, currency=currency, supplier=supplier, period_start=period_start, period_end=period_end, evidence_text=compact))
    return rows


def _extract_description_qty_rate_invoice_rows(
    page: Dict[str, Any],
    supplier: str,
    period_start: str,
    period_end: str,
    currency: str,
) -> List[LaborLineItem]:
    """Extract wrapped Description / Qty / Rate / Amount invoice rows."""
    text = str(page.get("text") or "")
    if not re.search(r"Description\s+Qty\s+Rate\s+Amount", text, re.IGNORECASE):
        return []

    compact_lines = [" ".join(line.split()) for line in text.splitlines()]
    compact_lines = [line for line in compact_lines if line]
    header_index = next(
        (
            index
            for index, line in enumerate(compact_lines)
            if re.search(r"Description\s+Qty\s+Rate\s+Amount", line, re.IGNORECASE)
        ),
        -1,
    )
    if header_index < 0:
        return []

    numeric_row = re.compile(
        r"^\$?\s*(?P<hours>\d[\d,]*(?:\.\d+)?)\s+"
        r"\$?\s*(?P<rate>\d[\d,]*(?:\.\d+)?)\s+"
        r"\$?\s*(?P<amount>\d[\d,]*\.\d{2})$"
    )
    inline_numeric_row = re.compile(
        r"^(?P<description>.+?)\s+"
        r"\$?\s*(?P<hours>\d[\d,]*(?:\.\d+)?)\s+"
        r"\$?\s*(?P<rate>\d[\d,]*(?:\.\d+)?)\s+"
        r"\$?\s*(?P<amount>\d[\d,]*\.\d{2})$"
    )
    period_prefix = re.compile(
        r"^Pay\s+Period\s*:\s*\d{1,2}[-/]\d{1,2}(?:[-/]\d{2,4})?\s+"
        r"through\s+\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\s*[-–]?\s*",
        re.IGNORECASE,
    )
    name_pattern = re.compile(
        r"^(?P<name>[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ.'-]+"
        r"(?:\s+[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ.'-]+){1,3}?)"
        r"(?=\s*(?:[-–]|U\.?\s*S\.?\b|E-?logistics\b|"
        r"(?:Inbound|Packing|Picking|After[- ]?Sales)\s+Team\b|Lumper\b|@?\$))",
        re.IGNORECASE,
    )
    rows: List[LaborLineItem] = []
    pending_description: List[str] = []
    warehouse_id = _warehouse_id_from_text(text) or _warehouse_id_from_filename(str(page.get("source_file") or ""))

    def append_row(description: str, match: re.Match[str], evidence_line: str) -> None:
        description_without_period = period_prefix.sub("", description).strip()
        name_match = name_pattern.match(description_without_period)
        if not name_match:
            return
        hours = parse_number(match.group("hours"))
        rate = parse_number(match.group("rate"))
        amount = parse_number(match.group("amount"))
        if hours <= 0 or rate <= 0 or amount <= 0:
            return
        if abs(round(hours * rate, 2) - round(amount, 2)) > max(0.05, round(amount * 0.0001, 2)):
            return
        employee_name = " ".join(name_match.group("name").split()).strip(" -")
        employee_name = re.sub(r"[-–]\s*U\.?\s*S\.?.*$", "", employee_name, flags=re.IGNORECASE).strip(" -")
        rows.append(
            LaborLineItem(
                source_type="pdf_invoice",
                source_file=str(page.get("source_file") or ""),
                source_page_or_row=f"p{page.get('page')}",
                employee_id="",
                employee_name_raw=employee_name,
                hours=round(hours, 2),
                amount=round(amount, 2),
                currency=currency,
                confidence=0.98,
                evidence_text=f"{description} | {evidence_line}",
                supplier=supplier,
                period_start=period_start,
                period_end=period_end,
                warehouse_id=warehouse_id,
            )
        )

    for line in compact_lines[header_index + 1 :]:
        if re.fullmatch(r"Page\s+\d+", line, re.IGNORECASE):
            pending_description = []
            continue
        match = numeric_row.fullmatch(line)
        if not match:
            inline_match = inline_numeric_row.fullmatch(line)
            if inline_match:
                pending_description = []
                append_row(inline_match.group("description"), inline_match, line)
                continue
            if not re.fullmatch(r"\$?\s*[\d,]+\.\d{2}", line):
                pending_description.append(line)
            continue

        description = " ".join(pending_description)
        pending_description = []
        append_row(description, match, line)
    return rows


def _extract_regular_rate_amount_invoice_rows(page: Dict[str, Any], supplier: str, period_start: str, period_end: str, currency: str) -> List[LaborLineItem]:
    """Extract rows shaped as NAME REGULAR HRS O/T HRS RATE AMOUNT."""
    text = page.get("text") or ""
    if not re.search(r"NAME\s+REGULAR\s+HRS\s+O/?T\s+HRS\s+RATE\s+AMOUNT", text, re.IGNORECASE):
        return []

    rows: List[LaborLineItem] = []
    for line in text.splitlines():
        compact = " ".join(line.split())
        if not compact:
            continue
        values = list(re.finditer(r"\d[\d,]*(?:\.\d+)?", compact))
        if len(values) < 3:
            continue
        amount_raw = values[-1].group()
        if not re.search(r"\.\d{2}$", amount_raw.replace(",", "")):
            continue
        name = compact[: values[0].start()].strip(" -:")
        name_upper = name.upper()
        if not name or name_upper in {"NAME", "TOTAL", "TOTALS", "BALANCE", "INVOICE"}:
            continue
        if any(token in name_upper for token in ["BILLING PERIOD", "PAYMENT", "DUE DATE", "BILL TO"]):
            continue

        hour_values = [parse_number(match.group()) for match in values[:-2]]
        hours = round(sum(hour_values), 2)
        amount = round(parse_number(amount_raw), 2)
        if hours <= 0 or amount <= 0:
            continue
        rows.append(
            LaborLineItem(
                source_type="pdf_invoice",
                source_file=page["source_file"],
                source_page_or_row=f"p{page['page']}",
                employee_id="",
                employee_name_raw=name,
                hours=hours,
                amount=amount,
                currency=currency,
                confidence=0.97,
                evidence_text=compact,
                supplier=supplier,
                period_start=period_start,
                period_end=period_end,
                warehouse_id=_warehouse_id_from_text(text),
            )
        )
    return rows


def _extract_elga_invoice_detail_rows(page: Dict[str, Any], supplier: str, period_start: str, period_end: str, currency: str) -> List[LaborLineItem]:
    """Extract ELGA-style detail rows where one employee spans Reg and OT lines."""
    text = page.get("text") or ""
    if "Hourly-Reg" not in text or "INVOICE DETAIL" not in text:
        return []

    rows: List[LaborLineItem] = []
    lines = [" ".join(line.split()) for line in text.splitlines()]
    in_table = False
    pending_parts: List[str] = []
    current: Dict[str, Any] | None = None

    def _clean_name(raw: str) -> str:
        value = " ".join(raw.split())
        value = re.sub(r"^\d+\s+", "", value)
        value = re.sub(r"^WH\s*\d+\s+", "", value, flags=re.IGNORECASE)
        value = re.sub(r"^WH\d+\s+", "", value, flags=re.IGNORECASE)
        ga_match = re.search(r"\bGA\b\s+(?P<name>.+)$", value, re.IGNORECASE)
        if ga_match:
            value = ga_match.group("name")
        value = re.sub(r"^(?:Fulton|The Bluffs|Austell|Atlanta|Ga)\s+", "", value, flags=re.IGNORECASE)
        return " ".join(value.split())

    def _warehouse(raw: str) -> str:
        match = re.search(r"^\s*(\d{1,3})\b", raw)
        if match:
            return match.group(1)
        match = re.search(r"\bWH\s*(\d{1,3})\b", raw, re.IGNORECASE)
        return match.group(1) if match else _warehouse_id_from_text(text)

    def _money_number_tokens(value: str) -> List[float]:
        return [parse_number(match.group()) for match in re.finditer(r"-?\d[\d,]*(?:\.\d+)?", value)]

    def _apply_pay_numbers(target: Dict[str, Any], numeric_text: str) -> None:
        values = _money_number_tokens(numeric_text)
        if len(values) < 3:
            return
        target["hours"] = round(float(target.get("hours") or 0) + values[1], 2)
        target["amount"] = round(float(target.get("amount") or 0) + values[2], 2)
        target["needs_numbers"] = False

    def _flush() -> None:
        nonlocal current
        if not current:
            return
        name = str(current.get("name") or "").strip()
        amount = round(float(current.get("amount") or 0), 2)
        hours = round(float(current.get("hours") or 0), 2)
        if name and amount > 0:
            rows.append(
                LaborLineItem(
                    source_type="pdf_invoice",
                    source_file=page["source_file"],
                    source_page_or_row=f"p{page['page']}",
                    employee_id="",
                    employee_name_raw=name,
                    hours=hours,
                    amount=amount,
                    currency=currency,
                    confidence=0.96,
                    evidence_text=" | ".join(current.get("evidence") or []),
                    supplier=supplier,
                    period_start=period_start,
                    period_end=period_end,
                    warehouse_id=str(current.get("warehouse_id") or ""),
                )
            )
        current = None

    for compact in lines:
        if not compact:
            continue
        if "Job Site/Warehouse" in compact and "Pay Type" in compact:
            in_table = True
            pending_parts = []
            continue
        if not in_table:
            continue
        if compact.startswith("Total "):
            _flush()
            pending_parts = []
            continue
        if "INVOICE DETAIL" in compact:
            _flush()
            break
        if compact in {"Paid Amount Paid", "Reg/OT", "Total", "combined", "Check Amount in Quickbooks"}:
            continue

        if "Hourly-Reg" in compact:
            _flush()
            before, after = compact.split("Hourly-Reg", 1)
            name_source = " ".join([*pending_parts, before])
            current = {
                "name": _clean_name(name_source),
                "hours": 0.0,
                "amount": 0.0,
                "warehouse_id": _warehouse(name_source),
                "evidence": [compact],
                "needs_numbers": True,
            }
            _apply_pay_numbers(current, after)
            pending_parts = []
            continue

        if "Overtime (Hourly)" in compact:
            if current:
                current.setdefault("evidence", []).append(compact)
                _, after = compact.split("Overtime (Hourly)", 1)
                _apply_pay_numbers(current, after)
            continue

        if current and current.get("needs_numbers"):
            values = _money_number_tokens(compact)
            if len(values) >= 3:
                current.setdefault("evidence", []).append(compact)
                _apply_pay_numbers(current, compact)
                continue

        if not re.fullmatch(r"[-\d.,$ ]+", compact):
            pending_parts.append(compact)

    _flush()
    return rows


_VOYAGE_NUMBER = r"(?:-\$|-?\$?\d[\d,]*(?:\.\d+)?\$?)"
_VOYAGE_ROW_RE = re.compile(
    rf"^(?P<row>\d+)\s+"
    rf"(?P<name>[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ\s.,'’()\-]*?)\s*"
    rf"(?P<values>{_VOYAGE_NUMBER}(?:\s+{_VOYAGE_NUMBER}){{10}})$"
)


def _extract_voyage_invoice_rows(
    page: Dict[str, Any],
    supplier: str,
    period_start: str,
    period_end: str,
    currency: str,
) -> List[LaborLineItem]:
    """Extract Voyage rows, including continuation pages without a repeated header."""
    rows: List[LaborLineItem] = []
    warehouse_id = _warehouse_id_from_filename(str(page.get("source_file") or "")) or _warehouse_id_from_text(
        str(page.get("text") or "")
    )
    for raw_line in (page.get("text") or "").splitlines():
        compact = " ".join(raw_line.split())
        match = _VOYAGE_ROW_RE.match(compact)
        if not match:
            continue
        values = [parse_number(value) for value in re.findall(_VOYAGE_NUMBER, match.group("values"))]
        if len(values) != 11:
            continue
        rows.append(
            LaborLineItem(
                source_type="pdf_invoice",
                source_file=str(page.get("source_file") or ""),
                source_page_or_row=f"p{page.get('page') or 1}",
                employee_id="",
                employee_name_raw=match.group("name").strip(),
                hours=round(values[1] + values[4] + values[7], 2),
                amount=round(values[10], 2),
                currency=currency,
                confidence=0.99,
                evidence_text=compact,
                supplier=supplier,
                period_start=period_start,
                period_end=period_end,
                warehouse_id=warehouse_id,
            )
        )
    return rows


def _extract_simple_invoice_rows(page: Dict[str, Any], supplier: str, period_start: str, period_end: str, currency: str) -> List[LaborLineItem]:
    """Extract simple rows like: "1 Name 40 2.5 $19.00 $28.50 $834.75"."""
    rows: List[LaborLineItem] = []
    for line in (page.get("text") or "").splitlines():
        compact = " ".join(line.split())
        match = re.match(r"^\d+\s+(?P<name>[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ\s.'-]*?)\s+(?P<rest>\d.*\$\d[\d,]*\.\d{2})$", compact)
        if not match:
            continue
        name = match.group("name").strip()
        values = [parse_number(value) for value in re.findall(r"-?\$?\d[\d,]*(?:\.\d+)?\$?", match.group("rest"))]
        if len(values) < 4:
            continue
        amount = values[-1]
        if not amount:
            continue
        hours = values[0]
        if len(values) >= 5:
            hours += values[1]
        rows.append(
            LaborLineItem(
                source_type="pdf_invoice",
                source_file=page["source_file"],
                source_page_or_row=f"p{page['page']}",
                employee_id="",
                employee_name_raw=name,
                hours=round(hours, 2),
                amount=round(amount, 2),
                currency=currency,
                confidence=0.95,
                evidence_text=compact,
                supplier=supplier,
                period_start=period_start,
                period_end=period_end,
                warehouse_id=_warehouse_id_from_text(page.get("text") or ""),
            )
        )
    return rows


def _extract_wage_code_invoice_rows(page: Dict[str, Any], supplier: str, period_start: str, period_end: str, currency: str) -> List[LaborLineItem]:
    """Extract invoice rows laid out as name / wage code / type / hours / rate / amount."""
    lines = [" ".join(line.split()) for line in (page.get("text") or "").splitlines()]
    lines = [line for line in lines if line]
    rows: List[LaborLineItem] = []
    index = 0
    while index + 5 < len(lines):
        step = 6
        name, wage_code, pay_type, hours_raw, rate_raw, amount_raw = lines[index : index + 6]
        if (
            index + 6 < len(lines)
            and not PAY_CODE_RE.match(wage_code)
            and "," in lines[index]
            and _looks_like_vertical_name(lines[index])
            and _looks_like_vertical_name(lines[index + 1])
            and PAY_CODE_RE.match(lines[index + 2])
            and TYPE_RE.match(lines[index + 3])
            and HOUR_RE.match(lines[index + 4])
            and HOUR_RE.match(lines[index + 5])
            and MONEY_RE.match(lines[index + 6])
        ):
            name = f"{lines[index]} {lines[index + 1]}"
            wage_code, pay_type, hours_raw, rate_raw, amount_raw = lines[index + 2 : index + 7]
            step = 7
        if not (
            _looks_like_vertical_name(name)
            and PAY_CODE_RE.match(wage_code)
            and TYPE_RE.match(pay_type)
            and HOUR_RE.match(hours_raw)
            and HOUR_RE.match(rate_raw)
            and MONEY_RE.match(amount_raw)
        ):
            index += 1
            continue

        hours = parse_number(hours_raw)
        amount = parse_number(amount_raw)
        if amount:
            rows.append(
                LaborLineItem(
                    source_type="pdf_invoice",
                    source_file=page["source_file"],
                    source_page_or_row=f"p{page['page']}",
                    employee_id="",
                    employee_name_raw=name,
                    hours=round(hours, 2),
                    amount=round(amount, 2),
                    currency=currency,
                    confidence=0.98,
                    evidence_text=" | ".join(lines[index : index + 6]),
                    supplier=supplier,
                    period_start=period_start,
                    period_end=period_end,
                    warehouse_id=_warehouse_id_from_text(page.get("text") or ""),
                )
            )
        index += step
    return rows


def _extract_bill_rate_invoice_rows(page: Dict[str, Any], supplier: str, period_start: str, period_end: str, currency: str) -> List[LaborLineItem]:
    """Extract rows like "$22.40 40.000 $896.00 5/17/2026 Name $17.500 Reg"."""
    text = page.get("text") or ""
    if not re.search(r"Hours\s+Amount\s+Bill\s+Rate\s+Date\s+Description\s+Pay\s+Rate", text, re.IGNORECASE):
        return []

    line_pattern = re.compile(
        r"^\$(?P<bill_rate>\d[\d,]*(?:\.\d+)?)\s+"
        r"(?P<hours>\d+(?:\.\d+)?)\s+"
        r"\$(?P<amount>\d[\d,]*(?:\.\d+)?)\s+"
        r"\d{1,2}/\d{1,2}/\d{4}\s+"
        r"(?P<name>.+?)\s+"
        r"\$(?P<pay_rate>\d[\d,]*(?:\.\d+)?)\s+"
        r"(?P<type>Reg|OT|Overtime|Regular|DT|Doubletime)$",
        re.IGNORECASE,
    )
    grouped: Dict[str, Dict[str, Any]] = {}
    for line in text.splitlines():
        compact = " ".join(line.split())
        match = line_pattern.match(compact)
        if not match:
            continue
        name = match.group("name").strip()
        if not _looks_like_vertical_name(name):
            continue
        current = grouped.setdefault(name, {"hours": 0.0, "amount": 0.0, "evidence": []})
        current["hours"] += parse_number(match.group("hours"))
        current["amount"] += parse_number(match.group("amount"))
        current["evidence"].append(compact)

    warehouse_id = _warehouse_id_from_text(text) or _warehouse_id_from_filename(str(page.get("source_file") or ""))
    rows: List[LaborLineItem] = []
    for name, data in grouped.items():
        amount = round(float(data["amount"]), 2)
        if not amount:
            continue
        rows.append(
            LaborLineItem(
                source_type="pdf_invoice",
                source_file=page["source_file"],
                source_page_or_row=f"p{page['page']}",
                employee_id="",
                employee_name_raw=name,
                hours=round(float(data["hours"]), 2),
                amount=amount,
                currency=currency,
                confidence=0.98,
                evidence_text=" | ".join(data["evidence"]),
                supplier=supplier,
                period_start=period_start,
                period_end=period_end,
                warehouse_id=warehouse_id,
            )
        )
    return rows


def _extract_bill_rate_summary_invoice_rows(page: Dict[str, Any], supplier: str, period_start: str, period_end: str, currency: str) -> List[LaborLineItem]:
    """Extract OSS-style summary rows with Base Rate/Bill Rate/Reg Time/OT/Total columns."""
    text = page.get("text") or ""
    if not re.search(r"Associate\s+Base\s+Rate\s+Bill\s+Rate\s+OT\s+Rate\s+Reg\.\s*Time", text, re.IGNORECASE):
        return []
    rows: List[LaborLineItem] = []
    warehouse_id = _warehouse_id_from_text(text) or _warehouse_id_from_filename(str(page.get("source_file") or ""))
    for line in text.splitlines():
        compact = " ".join(line.split())
        if not compact or compact.startswith(("Totals ", "If paid", "Pay period")):
            continue
        match = re.match(
            r"^(?P<name>[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ\s,.'-]*?)\s+"
            r"\$(?P<base>\d[\d,]*(?:\.\d+)?)\s+"
            r"(?P<bill>\d[\d,]*(?:\.\d+)?)\$\s+"
            r"(?P<ot_rate>\d[\d,]*(?:\.\d+)?)\$\s+"
            r"(?P<rest>.+?)\s+"
            r"(?P<total>\d[\d,]*\.\d{2})\$\s*$",
            compact,
        )
        if not match:
            continue
        name = match.group("name").strip()
        if not _looks_like_vertical_name(name):
            continue
        rest_numbers = [parse_number(value) for value in re.findall(r"\d[\d,]*(?:\.\d+)?", match.group("rest"))]
        if not rest_numbers:
            continue
        reg_hours = rest_numbers[0]
        ot_hours = rest_numbers[1] if len(rest_numbers) > 1 and rest_numbers[1] <= 24 else 0.0
        dt_hours = rest_numbers[2] if len(rest_numbers) > 2 and rest_numbers[2] <= 24 else 0.0
        amount = parse_number(match.group("total"))
        if not amount:
            continue
        rows.append(
            LaborLineItem(
                source_type="pdf_invoice",
                source_file=page["source_file"],
                source_page_or_row=f"p{page['page']}",
                employee_id="",
                employee_name_raw=name,
                hours=round(reg_hours + ot_hours + dt_hours, 2),
                amount=round(amount, 2),
                currency=currency,
                confidence=0.96,
                evidence_text=compact,
                supplier=supplier,
                period_start=period_start,
                period_end=period_end,
                warehouse_id=warehouse_id,
            )
        )
    return rows


def _extract_sss_employee_summary_rows(page: Dict[str, Any], supplier: str, period_start: str, period_end: str, currency: str) -> List[LaborLineItem]:
    text = page.get("text") or ""

    warehouse_id = _warehouse_id_from_text(text) or _warehouse_id_from_filename(str(page.get("source_file") or ""))
    rows_by_identity: Dict[tuple[str, str], Dict[str, Any]] = {}
    number_token = r"\(?\d[\d,]*(?:\.\d+)?\)?"
    money_token = rf"-|{number_token}"
    employee_row = re.compile(
        r"^(?:\d+\s+)?"
        r"(?P<name>[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ\s,.'-]*?)\s+"
        r"(?P<employee_id>\d{4,6})\s+"
        r"(?P<job_code>[A-Z]{2,}\d?[A-Z]{0,3}\d?)\s+"
        r"(?P<rest>.+)$",
        re.IGNORECASE,
    )
    rates_and_totals = re.compile(
        rf"\$\s*(?P<wage_rate>{number_token})\s+"
        rf"(?P<multiplier>{number_token})%\s+"
        rf"\$\s*(?P<bill_rate>{number_token})\s+"
        rf"(?P<standard_hours>{number_token})\s+"
        rf"(?P<overtime_hours>{number_token})\s+"
        rf"\$\s*(?P<regular_fee>{money_token})\s+"
        rf"\$\s*(?P<overtime_fee>{money_token})\s+"
        rf"\$\s*(?P<total_fee>{money_token})\s*$",
        re.IGNORECASE,
    )

    compact_lines = [" ".join(line.split()) for line in text.splitlines()]
    compact_lines = [line for line in compact_lines if line]
    seen_values: set[tuple[str, str, float, float, float]] = set()
    for index in range(len(compact_lines)):
        compact = ""
        match = None
        totals_match = None
        for end in range(index + 1, min(index + 5, len(compact_lines) + 1)):
            compact = " ".join(compact_lines[index:end])
            match = employee_row.match(compact)
            if not match:
                continue
            totals_match = rates_and_totals.search(match.group("rest"))
            if totals_match:
                break
        if not match or not totals_match:
            continue
        job_code = match.group("job_code").upper()
        if job_code == "DC":
            continue
        name = match.group("name").strip()
        if _is_non_employee_summary_name(name):
            continue
        amount = parse_number(totals_match.group("total_fee"))
        if not amount:
            continue
        standard_hours = parse_number(totals_match.group("standard_hours"))
        overtime_hours = parse_number(totals_match.group("overtime_hours"))
        if job_code == "SD":
            standard_hours = 0.0
            overtime_hours = 0.0
        identity = (match.group("employee_id"), job_code)
        value_identity = (
            match.group("employee_id"),
            job_code,
            round(standard_hours, 2),
            round(overtime_hours, 2),
            round(amount, 2),
        )
        if value_identity in seen_values:
            continue
        seen_values.add(value_identity)
        current = rows_by_identity.setdefault(
            identity,
            {
                "employee_id": match.group("employee_id"),
                "name": name,
                "hours": 0.0,
                "amount": 0.0,
                "evidence": [],
            },
        )
        current["hours"] += standard_hours + overtime_hours
        current["amount"] += amount
        current["evidence"].append(compact)

    rows: List[LaborLineItem] = []
    for data in rows_by_identity.values():
        amount = round(float(data["amount"]), 2)
        hours = round(float(data["hours"]), 2)
        if not amount:
            continue
        rows.append(
            LaborLineItem(
                source_type="pdf_invoice",
                source_file=page["source_file"],
                source_page_or_row=f"p{page['page']}",
                employee_id=data["employee_id"],
                employee_name_raw=data["name"],
                hours=hours,
                amount=amount,
                currency=currency,
                confidence=0.96,
                evidence_text=" | ".join(data["evidence"]),
                supplier=supplier,
                period_start=period_start,
                period_end=period_end,
                warehouse_id=warehouse_id,
            )
        )
    return rows


def _is_non_employee_summary_name(name: str) -> bool:
    normalized = " ".join(name.lower().split())
    return (
        normalized.startswith("open, open")
        or "workforce shift" in normalized
        or normalized in {"total", "totals", "supplemental sub total"}
    )


def _extract_vertical_invoice_rows(page: Dict[str, Any], supplier: str, period_start: str, period_end: str, currency: str) -> List[LaborLineItem]:
    lines = [" ".join(line.split()) for line in (page.get("text") or "").splitlines()]
    lines = [line for line in lines if line]
    rows: List[LaborLineItem] = []
    index = 0
    while index + 7 < len(lines):
        chunk = lines[index : index + 8]
        if not _is_vertical_invoice_chunk(chunk):
            index += 1
            continue
        name = _clean_vertical_employee_name(chunk[1])
        hours = parse_number(chunk[2])
        amount = parse_number(chunk[7])
        if name and amount:
            rows.append(
                LaborLineItem(
                    source_type="pdf_invoice",
                    source_file=page["source_file"],
                    source_page_or_row=f"p{page['page']}",
                    employee_id="",
                    employee_name_raw=name,
                    hours=round(hours, 2),
                    amount=round(amount, 2),
                    currency=currency,
                    confidence=0.98,
                    evidence_text=" | ".join(chunk),
                    supplier=supplier,
                    period_start=period_start,
                    period_end=period_end,
                )
            )
        index += 8
    return rows


def _extract_tabular_invoice_rows(page: Dict[str, Any], supplier: str, period_start: str, period_end: str, currency: str) -> List[LaborLineItem]:
    lines = [" ".join(line.split()) for line in (page.get("text") or "").splitlines()]
    lines = [line for line in lines if line]
    rows: List[LaborLineItem] = []

    # Look for tabular data with headers like "Employee Name", "Employee ID", "Hours", "Rate", "Amount"
    header_pattern = re.compile(r"(?:Employee\s+)?(?:Name|ID)\s+(?:Employee\s+)?(?:ID|Name)\s+Hours\s+Rate\s+Amount", re.IGNORECASE)
    data_pattern = re.compile(r"^([A-Za-z\s,.-]+?)\s+([A-Z0-9]+)\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)$")

    for i, line in enumerate(lines):
        if header_pattern.search(line):
            # Found header, extract data rows
            for j in range(i + 1, len(lines)):
                data_match = data_pattern.match(lines[j])
                if data_match:
                    name = data_match.group(1).strip()
                    employee_id = data_match.group(2).strip()
                    hours = parse_number(data_match.group(3))
                    amount = parse_number(data_match.group(5))
                    if name and amount:
                        rows.append(
                            LaborLineItem(
                                source_type="pdf_invoice",
                                source_file=page["source_file"],
                                source_page_or_row=f"p{page['page']}",
                                employee_id=employee_id,
                                employee_name_raw=name,
                                hours=round(hours, 2),
                                amount=round(amount, 2),
                                currency=currency,
                                confidence=0.95,
                                evidence_text=lines[j],
                                supplier=supplier,
                                period_start=period_start,
                                period_end=period_end,
                            )
                        )
                else:
                    # If we hit a non-data line, stop processing this table
                    break
            break

    return rows


def _is_vertical_invoice_chunk(chunk: List[str]) -> bool:
    return (
        bool(DATE_RE.match(chunk[0]))
        and _looks_like_vertical_name(chunk[1])
        and bool(HOUR_RE.match(chunk[2]))
        and _looks_like_pay_code(chunk[3])
        and bool(TYPE_RE.match(chunk[4]))
        and bool(MONEY_RE.match(chunk[5]))
        and bool(MONEY_RE.match(chunk[6]))
        and bool(MONEY_RE.match(chunk[7]))
    )


def _looks_like_pay_code(value: str) -> bool:
    value = " ".join(value.split())
    if not value or DATE_RE.match(value) or MONEY_RE.match(value) or HOUR_RE.match(value):
        return False
    letters = re.findall(r"[A-Za-z]", value)
    if len(letters) < 2:
        return False
    return len(value) <= 40


def _looks_like_vertical_name(value: str) -> bool:
    if DATE_RE.match(value) or MONEY_RE.match(value) or HOUR_RE.match(value):
        return False
    letters = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ]", value)
    return len(letters) >= 3


def _clean_vertical_employee_name(value: str) -> str:
    return re.sub(r"\s+,", ",", value).strip()


def _line_item(
    page: Dict[str, Any],
    match: re.Match[str],
    *,
    hours: float,
    amount: float,
    currency: str,
    supplier: str,
    period_start: str,
    period_end: str,
    evidence_text: str,
) -> LaborLineItem:
    return LaborLineItem(
        source_type="pdf_invoice",
        source_file=page["source_file"],
        source_page_or_row=f"p{page['page']}",
        employee_id=match.group("id"),
        employee_name_raw=match.group("name").strip(),
        hours=round(hours, 2),
        amount=round(amount, 2),
        currency=currency,
        confidence=0.9,
        evidence_text=evidence_text,
        supplier=supplier,
        period_start=period_start,
        period_end=period_end,
    )

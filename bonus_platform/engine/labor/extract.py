from __future__ import annotations

import base64
from io import BytesIO
import json
import re
from pathlib import Path
from typing import Any, Dict, List
from urllib.error import HTTPError
from urllib import request

from .models import LaborLineItem, line_items_from_dicts
from .parsing import parse_number
from .profiles import SupplierExtractionProfile, resolve_supplier_profile


LINE_RE = re.compile(r"^(?P<name>.+?)\s+(?P<id>(?:[A-Z]{2,5})?\d{5,6})\s+(?P<rest>\d.*\$.*?)$")
NUMBER_RE = re.compile(r"-?\$|[-]?\d[\d,]*\.\d+\$?")
DATE_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")
HOUR_RE = re.compile(r"^\d+(?:\.\d+)?$")
PAY_CODE_RE = re.compile(r"^(?:Reg|OT|DT)$", re.IGNORECASE)
TYPE_RE = re.compile(r"^(?:REG|OT|DT)$", re.IGNORECASE)
MONEY_RE = re.compile(r"^\$?[\d,]+\.\d{2}\$?$")
AI_PAGE_CACHE_VERSION = "v4"


def extract_invoice_items(pdf_paths: List[Path], ai_config: Dict[str, Any], supplier: str = "", period_start: str = "", period_end: str = "", currency: str = "") -> List[LaborLineItem]:
    supplier_profile = resolve_supplier_profile(supplier, profiles_path=ai_config.get("supplier_profiles_path"))
    pages = _extract_pdf_pages(pdf_paths)
    rule_items = _extract_with_rules(pages, supplier=supplier, period_start=period_start, period_end=period_end, currency=currency)
    if rule_items:
        return rule_items
    if _ai_ready(ai_config):
        errors: List[str] = []
        try:
            rows = _extract_with_ai_text(pages, ai_config, supplier=supplier, period_start=period_start, period_end=period_end, currency=currency, supplier_profile=supplier_profile)
            items = line_items_from_dicts(rows)
            if items:
                return items
        except Exception as exc:
            errors.append(_safe_error_message(exc))
        try:
            image_pages = _render_pdf_pages_to_images(pdf_paths, scale=float(ai_config.get("render_scale") or 1.5))
            image_pages = _apply_image_page_policy(image_pages, supplier_profile)
            rows = _extract_with_ai_images(image_pages, ai_config, supplier=supplier, period_start=period_start, period_end=period_end, currency=currency, supplier_profile=supplier_profile)
            items = line_items_from_dicts(rows)
            if items:
                return items
        except Exception as exc:
            errors.append(_safe_error_message(exc))
        if errors:
            raise ValueError("AI 抽取失败：" + "；".join(errors))
    return []


def _ai_ready(ai_config: Dict[str, Any]) -> bool:
    return bool(ai_config.get("enabled") and ai_config.get("api_key") and ai_config.get("base_url") and ai_config.get("model"))


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


def _extract_pdf_pages(pdf_paths: List[Path]) -> List[Dict[str, Any]]:
    pages: List[Dict[str, Any]] = []
    try:
        from pypdf import PdfReader
    except Exception:
        PdfReader = None
    for path in pdf_paths:
        if PdfReader is None:
            pages.append({"source_file": path.name, "page": 1, "text": ""})
            continue
        try:
            reader = PdfReader(str(path))
            for index, page in enumerate(reader.pages, start=1):
                pages.append({"source_file": path.name, "page": index, "text": page.extract_text() or ""})
        except Exception:
            pages.append({"source_file": path.name, "page": 1, "text": ""})
    return pages


def _extract_with_ai_text(
    pages: List[Dict[str, Any]],
    ai_config: Dict[str, Any],
    supplier: str = "",
    period_start: str = "",
    period_end: str = "",
    currency: str = "",
    supplier_profile: SupplierExtractionProfile | None = None,
) -> List[Dict[str, Any]]:
    prompt = {
        "instruction": _ai_instruction(supplier_profile),
        "supplier": supplier,
        "period_start": period_start,
        "period_end": period_end,
        "currency": currency,
        "pages": pages,
    }
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
    return _normalize_ai_rows(_post_chat_completion(payload, ai_config), supplier=supplier, period_start=period_start, period_end=period_end, currency=currency)


def _extract_with_ai_images(
    image_pages: List[Dict[str, Any]],
    ai_config: Dict[str, Any],
    supplier: str = "",
    period_start: str = "",
    period_end: str = "",
    currency: str = "",
    supplier_profile: SupplierExtractionProfile | None = None,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    max_pages = max(int(ai_config.get("max_pages_per_request") or 5), 1)
    for start in range(0, len(image_pages), max_pages):
        chunk = image_pages[start : start + max_pages]
        content: List[Dict[str, Any]] = []
        for page in chunk:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{page['mime_type']};base64,{page['base64']}"},
                }
            )
        content.append(
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "instruction": _ai_instruction(supplier_profile),
                        "supplier": supplier,
                        "period_start": period_start,
                        "period_end": period_end,
                        "currency": currency,
                        "pages": [{"source_file": page["source_file"], "page": page["page"]} for page in chunk],
                    },
                    ensure_ascii=False,
                ),
            }
        )
        payload = {
            "model": ai_config["model"],
            "messages": [
                {"role": "system", "content": "You extract payroll invoice table rows from images into JSON only."},
                {"role": "user", "content": content},
            ],
            "temperature": 0,
            "max_completion_tokens": int(ai_config.get("max_completion_tokens") or 8192),
        }
        _apply_provider_options(payload, ai_config)
        cached = _load_ai_page_cache(chunk, ai_config)
        if cached is not None:
            rows.extend(cached)
            continue
        try:
            extracted = _post_chat_completion(payload, ai_config)
            _save_ai_page_cache(chunk, ai_config, extracted)
            rows.extend(extracted)
        except json.JSONDecodeError:
            try:
                extracted = _post_chat_completion(payload, ai_config)
                _save_ai_page_cache(chunk, ai_config, extracted)
                rows.extend(extracted)
                continue
            except json.JSONDecodeError:
                pass
            if chunk and all(int(page.get("page") or 1) > 1 for page in chunk):
                continue
            raise
    return _normalize_ai_rows(rows, supplier=supplier, period_start=period_start, period_end=period_end, currency=currency)


def _post_chat_completion(payload: Dict[str, Any], ai_config: Dict[str, Any]) -> List[Dict[str, Any]]:
    req = request.Request(
        ai_config["base_url"].rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers=_request_headers(ai_config),
        method="POST",
    )
    with request.urlopen(req, timeout=int(ai_config.get("timeout_seconds", 90))) as response:
        data = json.loads(response.read().decode("utf-8"))
    content = data["choices"][0]["message"]["content"]
    return _json_array(content)


def _request_headers(ai_config: Dict[str, Any]) -> Dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if str(ai_config.get("provider") or "").lower() == "mimo":
        headers["api-key"] = str(ai_config["api_key"])
    else:
        headers["Authorization"] = f"Bearer {ai_config['api_key']}"
    return headers


def _apply_provider_options(payload: Dict[str, Any], ai_config: Dict[str, Any]) -> None:
    if str(ai_config.get("provider") or "").lower() == "mimo":
        payload["thinking"] = {"type": "disabled"}


def _ai_instruction(supplier_profile: SupplierExtractionProfile | None = None) -> str:
    instruction = (
        "Extract labor invoice employee rows as a strict JSON array. "
        "Each row must include source_file, source_page_or_row, employee_id, employee_name_raw, hours, amount, currency, confidence, evidence_text. "
        "Spatial calibration: first identify page orientation, table boundaries, column headers, and row alignment before extracting. "
        "Only extract rows spatially aligned under employee/name, hours, amount, and total/charge columns in the same table. "
        "Ignore handwriting, margin notes, barcodes, page numbers, headers, footers, subtotals, and timesheet-only pages. "
        "Return only employee charge rows, not invoice totals or headers. "
        "If a page has no clear employee charge rows, return [] exactly. "
        "employee_name_raw must be a visible person name from an Associate/Employee row, not a vendor, subtotal, invoice number, barcode, account number, or random numeric string. "
        "employee_id must be empty unless a separate visible employee ID column/value exists next to that person; never copy a name, barcode, invoice number, account number, or long numeric string into employee_id. "
        "If a premium/meal row has amount but no worked hours, use hours 0 and keep the amount."
    )
    if supplier_profile and supplier_profile.prompt_notes:
        instruction += " Supplier-specific profile guidance: " + " ".join(supplier_profile.prompt_notes)
    return instruction


def _normalize_ai_rows(rows: List[Dict[str, Any]], supplier: str, period_start: str, period_end: str, currency: str) -> List[Dict[str, Any]]:
    normalized = []
    for row in rows:
        employee_name = str(row.get("employee_name_raw") or row.get("employeeNameRaw") or row.get("employee_name") or row.get("employeeName") or "").strip()
        if not employee_name:
            continue
        if not _looks_like_employee_row(employee_name, row):
            continue
        current = dict(row)
        current["source_type"] = current.get("source_type") or current.get("sourceType") or "pdf_invoice"
        current["source_page_or_row"] = current.get("source_page_or_row") or current.get("sourcePageOrRow") or "p?"
        current["currency"] = current.get("currency") or currency
        current["supplier"] = current.get("supplier") or supplier
        current["period_start"] = current.get("period_start") or current.get("periodStart") or period_start
        current["period_end"] = current.get("period_end") or current.get("periodEnd") or period_end
        current["confidence"] = current.get("confidence") if current.get("confidence") is not None else 0.7
        normalized.append(current)
    return normalized


def _looks_like_employee_row(employee_name: str, row: Dict[str, Any]) -> bool:
    hours = parse_number(row.get("hours"))
    amount = parse_number(row.get("amount"))
    evidence = str(row.get("evidence_text") or row.get("evidenceText") or "").lower()
    if amount == 0:
        return False
    if amount > 0 and not any(marker in evidence for marker in ("$", "amount", "bill", "total", "charge", "invoice")):
        return False
    letters = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ]", employee_name)
    if len(letters) < 3:
        return False
    if re.fullmatch(r"[A-Z]{1,4}[-\s]*\d+(?:\.\d+)?", employee_name.strip(), flags=re.IGNORECASE):
        return False
    return True


def _render_pdf_pages_to_images(pdf_paths: List[Path], scale: float = 1.5) -> List[Dict[str, Any]]:
    try:
        import pypdfium2 as pdfium
    except Exception as exc:
        raise RuntimeError("扫描版 PDF 需要安装 pypdfium2 才能渲染页面图片。") from exc

    image_pages: List[Dict[str, Any]] = []
    for path in pdf_paths:
        document = pdfium.PdfDocument(str(path))
        try:
            for index in range(len(document)):
                page = document[index]
                try:
                    bitmap = page.render(scale=scale).to_pil()
                    if bitmap.height > bitmap.width:
                        bitmap = bitmap.rotate(90, expand=True)
                    buffer = BytesIO()
                    bitmap.save(buffer, format="PNG")
                    image_pages.append(
                        {
                            "source_file": path.name,
                            "source_path": str(path),
                            "page": index + 1,
                            "mime_type": "image/png",
                            "base64": base64.b64encode(buffer.getvalue()).decode("ascii"),
                        }
                    )
                finally:
                    page.close()
        finally:
            document.close()
    return image_pages


def _apply_image_page_policy(image_pages: List[Dict[str, Any]], supplier_profile: SupplierExtractionProfile) -> List[Dict[str, Any]]:
    if supplier_profile.image_page_policy == "first_page_only":
        return [page for page in image_pages if int(page.get("page") or 1) == 1]
    return image_pages


def _load_ai_page_cache(chunk: List[Dict[str, Any]], ai_config: Dict[str, Any]) -> List[Dict[str, Any]] | None:
    cache_path = _ai_page_cache_path(chunk, ai_config)
    if cache_path is None or not cache_path.exists():
        return None
    try:
        rows = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return rows if isinstance(rows, list) else None


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


def _json_array(content: str) -> List[Dict[str, Any]]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\[[\s\S]*\]", content)
        if not match:
            raise
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, list):
        raise ValueError("AI 返回结果不是员工明细数组。")
    return [row for row in parsed if isinstance(row, dict)]


def _extract_with_rules(pages: List[Dict[str, Any]], supplier: str, period_start: str, period_end: str, currency: str) -> List[LaborLineItem]:
    rows: List[LaborLineItem] = []
    for page in pages:
        rows.extend(_extract_vertical_invoice_rows(page, supplier=supplier, period_start=period_start, period_end=period_end, currency=currency))
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


def _is_vertical_invoice_chunk(chunk: List[str]) -> bool:
    return (
        bool(DATE_RE.match(chunk[0]))
        and _looks_like_vertical_name(chunk[1])
        and bool(HOUR_RE.match(chunk[2]))
        and bool(PAY_CODE_RE.match(chunk[3]))
        and bool(TYPE_RE.match(chunk[4]))
        and bool(MONEY_RE.match(chunk[5]))
        and bool(MONEY_RE.match(chunk[6]))
        and bool(MONEY_RE.match(chunk[7]))
    )


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

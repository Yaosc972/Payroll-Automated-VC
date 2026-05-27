from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List
from urllib import request

from .models import LaborLineItem, line_items_from_dicts
from .parsing import parse_number


LINE_RE = re.compile(r"^(?P<name>.+?)\s+(?P<id>(?:[A-Z]{2,5})?\d{5,6})\s+(?P<rest>\d.*\$.*?)$")
NUMBER_RE = re.compile(r"-?\$|[-]?\d[\d,]*\.\d+\$?")


def extract_invoice_items(pdf_paths: List[Path], ai_config: Dict[str, Any], supplier: str = "", period_start: str = "", period_end: str = "", currency: str = "") -> List[LaborLineItem]:
    pages = _extract_pdf_pages(pdf_paths)
    if ai_config.get("enabled") and ai_config.get("api_key") and ai_config.get("base_url") and ai_config.get("model"):
        try:
            rows = _extract_with_ai(pages, ai_config)
            items = line_items_from_dicts(rows)
            if items:
                return items
        except Exception:
            # Keep V1 usable during pilots when AI config is incomplete or temporarily unavailable.
            pass
    return _extract_with_rules(pages, supplier=supplier, period_start=period_start, period_end=period_end, currency=currency)


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
        reader = PdfReader(str(path))
        for index, page in enumerate(reader.pages, start=1):
            pages.append({"source_file": path.name, "page": index, "text": page.extract_text() or ""})
    return pages


def _extract_with_ai(pages: List[Dict[str, Any]], ai_config: Dict[str, Any]) -> List[Dict[str, Any]]:
    prompt = {
        "instruction": "Extract labor invoice employee rows as strict JSON array. Each row must include source_file, source_page_or_row, employee_id, employee_name_raw, hours, amount, currency, confidence, evidence_text.",
        "pages": pages,
    }
    payload = {
        "model": ai_config["model"],
        "messages": [
            {"role": "system", "content": "You extract payroll invoice tables into JSON only."},
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ],
        "temperature": 0,
    }
    req = request.Request(
        ai_config["base_url"].rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {ai_config['api_key']}"},
        method="POST",
    )
    with request.urlopen(req, timeout=int(ai_config.get("timeout_seconds", 90))) as response:
        data = json.loads(response.read().decode("utf-8"))
    content = data["choices"][0]["message"]["content"]
    return _json_array(content)


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
        for line in (page.get("text") or "").splitlines():
            compact = " ".join(line.split())
            match = LINE_RE.match(compact)
            if not match:
                continue
            values = [parse_number(value) for value in NUMBER_RE.findall(match.group("rest"))]
            if len(values) < 10:
                continue
            hours_values = values[4:-4]
            rows.append(
                LaborLineItem(
                    source_type="pdf_invoice",
                    source_file=page["source_file"],
                    source_page_or_row=f"p{page['page']}",
                    employee_id=match.group("id"),
                    employee_name_raw=match.group("name").strip(),
                    hours=round(sum(hours_values), 2),
                    amount=round(values[-1], 2),
                    currency=currency,
                    confidence=0.9,
                    evidence_text=compact,
                    supplier=supplier,
                    period_start=period_start,
                    period_end=period_end,
                )
            )
    return rows


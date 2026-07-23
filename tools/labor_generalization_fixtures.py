#!/usr/bin/env python3
"""Generate deterministic, privacy-safe invoice fixtures for labor regression."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
from typing import Any

import fitz
from openpyxl import Workbook
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter


LABELS = {
    "en": {"invoice": "INVOICE", "associate": "ASSOCIATE", "hours": "HOURS", "amount": "AMOUNT", "net": "NET TOTAL", "tax": "TAX", "fee": "SERVICE FEE", "gross": "AMOUNT DUE"},
    "es": {"invoice": "FACTURA", "associate": "EMPLEADO", "hours": "HORAS", "amount": "IMPORTE", "net": "TOTAL NETO", "tax": "IMPUESTO", "fee": "TARIFA", "gross": "TOTAL"},
    "de": {"invoice": "RECHNUNG", "associate": "MITARBEITER", "hours": "STUNDEN", "amount": "BETRAG", "net": "NETTOSUMME", "tax": "STEUER", "fee": "GEBUEHR", "gross": "GESAMT"},
}


def load_scenarios(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    scenarios = payload.get("scenarios") or []
    if not isinstance(scenarios, list):
        raise ValueError("scenarios must be a list")
    required = {"id", "family", "supplier", "language", "recognizable", "employees", "netAmount", "taxAmount", "feeAmount", "pages"}
    seen: set[str] = set()
    for scenario in scenarios:
        missing = required - set(scenario)
        if missing:
            raise ValueError(f"{scenario.get('id', '<unknown>')} missing fields: {sorted(missing)}")
        if scenario["id"] in seen:
            raise ValueError(f"duplicate scenario id: {scenario['id']}")
        seen.add(scenario["id"])
    return scenarios


def _money(value: float) -> float:
    return round(float(value), 2)


def _truth_case(scenario: dict[str, Any]) -> dict[str, Any]:
    employees = [
        {"name": str(name), "hours": float(hours), "amount": _money(amount)}
        for name, hours, amount in scenario["employees"]
    ]
    employee_subtotal = _money(sum(row["amount"] for row in employees))
    net = _money(scenario["netAmount"])
    tax = _money(scenario["taxAmount"])
    fee = _money(scenario["feeAmount"])
    gross = _money(net + tax + fee)
    amount_scope = str(scenario.get("amountScope") or "net")
    amount_column = "Amount (Net)" if amount_scope == "net" else "Amount (Gross)"
    expected_reconciliation = net if amount_scope == "net" else gross
    if employee_subtotal != expected_reconciliation:
        raise ValueError(
            f"{scenario['id']} employee subtotal {employee_subtotal:.2f} does not match {amount_scope} amount {expected_reconciliation:.2f}"
        )
    official_pages = [index for index, role in enumerate(scenario["pages"], start=1) if role == "invoice"]
    return {
        "id": scenario["id"],
        "family": scenario["family"],
        "supplier": scenario["supplier"],
        "language": scenario["language"],
        "recognizable": bool(scenario["recognizable"]),
        "reviewReason": str(scenario.get("reviewReason") or ""),
        "amountScope": amount_scope,
        "amountColumn": amount_column,
        "warehouseId": str(scenario["warehouseId"]),
        "currency": "USD",
        "employees": employees,
        "employeeSubtotal": employee_subtotal,
        "netAmount": net,
        "taxAmount": tax,
        "feeAmount": fee,
        "grossAmount": gross,
        "displayedTotal": _money(scenario.get("displayedTotal", expected_reconciliation)),
        "pages": list(scenario["pages"]),
        "officialInvoicePages": official_pages,
        "attachmentPages": [index for index, role in enumerate(scenario["pages"], start=1) if role != "invoice"],
        "truthSource": "scenario_definition",
        "expectedCanRelease": bool(scenario["recognizable"]),
        "expectedRequiresHumanReview": not bool(scenario["recognizable"]),
    }


def _invoice_lines(case: dict[str, Any], scenario: dict[str, Any]) -> list[str]:
    labels = LABELS[case["language"]]
    lines = [
        labels["invoice"],
        case["supplier"],
        f"Invoice ID: SYN-{case['id'].upper()}",
        "Billing period: 2026-06-01 to 2026-06-07",
        f"WAREHOUSE LOC # {case['warehouseId']}",
        "",
        f"{labels['associate']:<28} {labels['hours']:>10} {labels['amount']:>14}",
    ]
    for row in case["employees"]:
        lines.append(f"{row['name']:<28} {row['hours']:>10.2f} ${row['amount']:>12,.2f}")
    lines.append("")
    if not scenario.get("omitTotal"):
        lines.append(f"{labels['net']}: ${case['netAmount']:,.2f}")
        if case["taxAmount"]:
            lines.append(f"{labels['tax']}: ${case['taxAmount']:,.2f}")
        if case["feeAmount"]:
            lines.append(f"{labels['fee']}: ${case['feeAmount']:,.2f}")
        if case["amountScope"] == "gross":
            lines.append(f"{labels['gross']}: ${case['displayedTotal']:,.2f}")
        elif case["displayedTotal"] != case["netAmount"]:
            lines.append(f"TOTAL: ${case['displayedTotal']:,.2f}")
    return lines


def _draw_text_page(page: fitz.Page, lines: list[str], *, compact: bool = False) -> None:
    page.insert_text((54, 54), lines[0], fontsize=18, fontname="helv")
    y = 84
    for line in lines[1:]:
        page.insert_text((54, y), line, fontsize=8.5 if compact else 10, fontname="cour")
        y += 14 if compact else 18


def _raster_invoice(lines: list[str], degradation: str) -> bytes:
    width, height = (850, 1100)
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    y = 45
    for index, line in enumerate(lines):
        draw.text((45, y), line, fill="black")
        y += 30 if index else 45
    if degradation == "readable":
        image = image.resize((595, 770)).rotate(0.7, fillcolor="white")
        image = ImageEnhance.Contrast(image).enhance(0.82)
        image = image.filter(ImageFilter.GaussianBlur(radius=0.25))
        quality = 58
    else:
        image = image.resize((150, 194)).resize((595, 770))
        image = ImageEnhance.Contrast(image).enhance(0.18)
        image = image.filter(ImageFilter.GaussianBlur(radius=4.0))
        quality = 18
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality)
    return buffer.getvalue()


def _write_pdf(path: Path, scenario: dict[str, Any], case: dict[str, Any]) -> None:
    document = fitz.open()
    invoice_lines = _invoice_lines(case, scenario)
    for role in scenario["pages"]:
        page = document.new_page(width=842, height=595)
        if role == "invoice":
            degradation = str(scenario.get("degradation") or "")
            if degradation:
                image_bytes = _raster_invoice(invoice_lines, degradation)
                page.insert_image(page.rect, stream=image_bytes)
            else:
                _draw_text_page(page, invoice_lines, compact=scenario.get("layout") == "compact")
        elif role == "email_cover":
            _draw_text_page(page, ["PAYROLL SUBMISSION", "Synthetic cover message", "Please process the attached invoice."])
        elif role == "timecard":
            _draw_text_page(page, ["WEEKLY TIMECARD", "Synthetic non-payable attachment", "Daily hours only - no invoice amount"])
        else:
            raise ValueError(f"unsupported page role: {role}")
    document.set_metadata({"title": f"Synthetic fixture {case['id']}", "author": "Sigma regression generator"})
    document.save(path, garbage=4, deflate=True)
    document.close()


def _write_workbook(path: Path, case: dict[str, Any]) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Employee Billing"
    sheet.append(["Employee ID", "Name", "Hours", case["amountColumn"], "Currency", "Physical Warehouse"])
    for index, employee in enumerate(case["employees"], start=1):
        sheet.append(
            [
                f"SYN{index:04d}",
                employee["name"],
                employee["hours"],
                employee["amount"],
                case["currency"],
                case["warehouseId"],
            ]
        )
    workbook.save(path)


def generate_fixture_set(scenarios_path: Path, output_dir: Path) -> dict[str, Any]:
    scenarios = load_scenarios(scenarios_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    truth_cases: list[dict[str, Any]] = []
    files: list[str] = []
    for scenario_index, original_scenario in enumerate(scenarios, start=101):
        scenario = dict(original_scenario)
        scenario.setdefault("warehouseId", str(scenario_index))
        case = _truth_case(scenario)
        pdf_path = output_dir / f"{case['id']}.pdf"
        workbook_path = output_dir / f"{case['id']}.xlsx"
        _write_pdf(pdf_path, scenario, case)
        _write_workbook(workbook_path, case)
        case["pdfFile"] = pdf_path.name
        case["workbookFile"] = workbook_path.name
        truth_cases.append(case)
        files.extend([pdf_path.name, workbook_path.name])
    truth = {"schemaVersion": 1, "seed": 20260712, "cases": truth_cases}
    truth_text = json.dumps(truth, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    truth_path = output_dir / "truth.json"
    truth_path.write_text(truth_text, encoding="utf-8")
    files.append(truth_path.name)
    return {
        "scenarioCount": len(truth_cases),
        "truthPath": str(truth_path),
        "truthSha256": hashlib.sha256(truth_text.encode("utf-8")).hexdigest(),
        "files": sorted(files),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenarios", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(generate_fixture_set(args.scenarios, args.output_dir), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

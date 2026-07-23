import json
from pathlib import Path

from bonus_platform.engine.labor.opendataloader_adapter import (
    extract_invoice_total_from_opendataloader_markdown,
    extract_labor_rows_from_opendataloader_json,
)


def test_extract_labor_rows_from_opendataloader_json_handles_inline_and_table_rows(tmp_path):
    payload = {
        "file name": "US_ELogistics_Service_Corp__35361.pdf",
        "kids": [
            {
                "type": "paragraph",
                "page number": 1,
                "content": (
                    "Invoice Number: 35361 Invoice Date: 6/19/2026 "
                    "Customer Number: CA#25 Bloomington Invoice Amt: $50,174.35 "
                    "Date Description Hours Pay Code Type Pay Rate Bill Rate Amount "
                    "CA#25 Bloomington 6/14/2026 Alva, Patrick 40.00 Reg REG $20.00 26.00 $1,040.00 "
                    "6/14/2026 Alva, Patrick 2.38 OT OT $30.00 39.00 $92.82"
                ),
            },
            {
                "type": "table row",
                "cells": [
                    {
                        "type": "table cell",
                        "page number": 2,
                        "kids": [
                            {
                                "type": "paragraph",
                                "page number": 2,
                                "content": "6/14/2026 Gomez, Alejandra",
                            }
                        ],
                    },
                    {
                        "type": "table cell",
                        "page number": 2,
                        "kids": [
                            {
                                "type": "paragraph",
                                "page number": 2,
                                "content": "3.77 OT OT $26.25 34.13 $128.67",
                            }
                        ],
                    },
                ],
            },
        ],
    }
    json_path = tmp_path / "sample.json"
    json_path.write_text(json.dumps(payload), encoding="utf-8")

    rows = extract_labor_rows_from_opendataloader_json(
        json_path,
        supplier="OSI",
        period_start="2026-06-08",
        period_end="2026-06-14",
        currency="USD",
    )

    assert [(row.employee_name_raw, row.hours, row.amount) for row in rows] == [
        ("Alva, Patrick", 40.0, 1040.0),
        ("Alva, Patrick", 2.38, 92.82),
        ("Gomez, Alejandra", 3.77, 128.67),
    ]
    assert {row.warehouse_id for row in rows} == {"25"}
    assert {row.source_type for row in rows} == {"pdf_invoice"}


def test_extract_invoice_total_from_opendataloader_markdown_prefers_invoice_amount(tmp_path):
    markdown_path = tmp_path / "sample.md"
    markdown_path.write_text(
        "Invoice Number: 35361 Invoice Amt: $50,174.35\n\n"
        "| Totals | 480.29 | 15.72 | $50,174.34 |\n",
        encoding="utf-8",
    )

    assert extract_invoice_total_from_opendataloader_markdown(markdown_path) == 50174.35

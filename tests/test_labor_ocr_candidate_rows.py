from bonus_platform.engine.labor.ocr_candidate_rows import extract_rows_from_visual_pages


def _extract(text):
    return extract_rows_from_visual_pages(
        [{"source_file": "invoice.pdf", "page": 1, "visualText": text}],
        supplier="candidate",
        period_start="2026-05-11",
        period_end="2026-05-17",
        currency="USD",
    )


def test_extracts_name_hours_rate_amount_visual_rows():
    rows = _extract(
        "LAST NAME FIRST NAME REGULAR HRS OVERTIME HRS DT HRS BILL RATE AMOUNT\n"
        "REYES KAYLEE 40.00 22.58 903.20\n"
        "REYES KAYLEE 2.11 33.86 71.44\n"
        "TOTAL: $ 974.64"
    )

    assert [(row.employee_name_raw, row.hours, row.amount) for row in rows] == [
        ("REYES KAYLEE", 40.0, 903.2),
        ("REYES KAYLEE", 2.11, 71.44),
    ]


def test_repairs_embedded_name_digit_without_parsing_supporting_numeric_rows():
    rows = _extract(
        "LAST NAME FIRST NAME REGULAR HRS BILL RATE AMOUNT\n"
        "RODRIGUEZ LIT7Y 4.07 22.58 91.90\n"
        "Overtime pay for day shift 7.32 3.25 4.88 4.88 2.84 6.91 69.66 63.62"
    )

    assert [(row.employee_name_raw, row.hours, row.amount) for row in rows] == [
        ("RODRIGUEZ LITZY", 4.07, 91.90),
    ]


def test_extracts_date_led_pay_type_rows():
    rows = _extract(
        "Date Description Comment Type Pay Rate Hours Bill Rate Amount\n"
        "5/17/2026 Arellano Luna, Pablo OT $26.250 0.400 $33.60 $13.44\n"
        "5/17/2026 Arellano Luna, Pablo Reg $17.500 40.000 $22.40 $896.00"
    )

    assert [(row.employee_name_raw, row.hours, row.amount) for row in rows] == [
        ("Arellano Luna, Pablo", 0.4, 13.44),
        ("Arellano Luna, Pablo", 40.0, 896.0),
    ]


def test_extracts_rate_summary_rows_using_last_value_as_total():
    rows = _extract(
        "Associate Base Rate Bill Rate OT Rate Reg. Time Dbl. Time RT OT DT TOTAL\n"
        "Alvarez Minchaca, Rosa $17.50 $ 22.40 $ 33.60 30.90 0.29 $ 692.16 $ 9.74 $ $ 701.90\n"
        "Benavides, Jeymmy $17.50 $ 22.40 $ 33.60 22.68 $ 508.03 $ $ $ 508.03\n"
        "Totals 53.58 0.29 $1,200.19 $9.74 $1,209.93"
    )

    assert [(row.employee_name_raw, row.hours, row.amount) for row in rows] == [
        ("Alvarez Minchaca, Rosa", 31.19, 701.9),
        ("Benavides, Jeymmy", 22.68, 508.03),
    ]


def test_carries_table_layout_to_continuation_pages_of_same_file():
    rows = extract_rows_from_visual_pages(
        [
            {
                "source_file": "invoice.pdf",
                "page": 1,
                "visualText": "LAST NAME FIRST NAME REGULAR HRS BILL RATE AMOUNT\nREYES KAYLEE 40.00 22.58 903.20",
            },
            {
                "source_file": "invoice.pdf",
                "page": 2,
                "visualText": "RODRIGUEZ JENNIFER 39.90 22.58 900.94\nTOTAL: $1,804.14",
            },
        ],
        currency="USD",
    )

    assert [(row.source_page_or_row, row.employee_name_raw, row.amount) for row in rows] == [
        ("p1", "REYES KAYLEE", 903.2),
        ("p2", "RODRIGUEZ JENNIFER", 900.94),
    ]


def test_removes_week_date_annotation_embedded_in_employee_name():
    rows = _extract(
        "LAST NAME FIRST NAME REGULAR HRS BILL RATE AMOUNT\n"
        "CANALES-WK 5/24/2026 ERICK 15.27 23.87 364.49"
    )

    assert [(row.employee_name_raw, row.hours, row.amount) for row in rows] == [
        ("CANALES ERICK", 15.27, 364.49),
    ]


def test_recovers_truncated_cent_from_hours_and_rate():
    rows = _extract(
        "LAST NAME FIRST NAME REGULAR HRS BILL RATE AMOUNT\n"
        "HERNANDEZ KAROLINA 1.06 37.73 39.9"
    )

    assert rows[0].amount == 39.99


def test_rate_summary_tolerates_ocr_header_and_missing_currency_marker():
    rows = _extract(
        "Associate Base Rate BIII Rate OT Rate Reg. Time Dbl. Time RT 10 DT TOTAL\n"
        "Solorzano, Kevin $20.00 25.60 $ 38.40 39.43 2.33 $ 1,009.41 $ 89.47 $ $ 1,098.88"
    )

    assert [(row.employee_name_raw, row.hours, row.amount) for row in rows] == [
        ("Solorzano, Kevin", 41.76, 1098.88),
    ]


def test_rate_summary_does_not_parse_dates_or_identifier_noise():
    rows = _extract(
        "Associate Base Rate Bill Rate OT Rate Reg. Time TOTAL\n"
        "Pay period 05/11/2026 - 05/17/2026\n"
        "WUS045852 WUS045851 WUS045751 25045792 WU5045751 WU5045746"
    )

    assert rows == []


def test_extracts_french_named_employee_subtotals_without_treating_repeated_amount_as_hours():
    rows = extract_rows_from_visual_pages(
        [
            {
                "source_file": "adequat.pdf",
                "page": 1,
                "visualText": (
                    "Détail des prestations Quantité Taux Montant\n"
                    "S/Total Intérimaire : FOFANA DRAME Sekou 45,40 45,40\n"
                    "S/Total Intérimaire : GOMES Esteban 38,75 801,34"
                ),
            }
        ],
        currency="EUR",
    )

    assert [(row.employee_name_raw, row.hours, row.amount) for row in rows] == [
        ("FOFANA DRAME Sekou", 0.0, 45.4),
        ("GOMES Esteban", 38.75, 801.34),
    ]


def test_extracts_common_ocr_variants_of_french_subtotal_label():
    rows = _extract(
        "STotal Intérimaire : FOFANA DRAME Sekou 45,40 45,40\n"
        "STtal Intérimaire : GOMES Esteban 38,75 801,34"
    )

    assert [(row.employee_name_raw, row.hours, row.amount) for row in rows] == [
        ("FOFANA DRAME Sekou", 0.0, 45.4),
        ("GOMES Esteban", 38.75, 801.34),
    ]


def test_extracts_french_week_employee_subtotal_across_pages():
    rows = extract_rows_from_visual_pages(
        [
            {
                "source_file": "sovitrat.pdf",
                "page": 1,
                "visualText": "AHOKA CLOVIS Semaine 22 du 25/05/2026 au 31/05/2026",
            },
            {
                "source_file": "sovitrat.pdf",
                "page": 2,
                "visualText": "001 HEURES NORMALES 28,00 20,19 565,32\nS/Total 46,16 1071,49",
            },
        ],
        currency="EUR",
    )

    assert [(row.source_page_or_row, row.employee_name_raw, row.hours, row.amount) for row in rows] == [
        ("p2", "AHOKA CLOVIS", 46.16, 1071.49),
    ]


def test_extracts_ocr_variant_of_plain_french_subtotal():
    rows = extract_rows_from_visual_pages(
        [
            {
                "source_file": "sovitrat.pdf",
                "page": 1,
                "visualText": (
                    "AHOKA CLOVIS Semaine 22 du 25/05/2026 au 31/05/2026\n"
                    "STotal 46,16 1071,49"
                ),
            }
        ],
        currency="EUR",
    )

    assert [(row.employee_name_raw, row.hours, row.amount) for row in rows] == [
        ("AHOKA CLOVIS", 46.16, 1071.49),
    ]

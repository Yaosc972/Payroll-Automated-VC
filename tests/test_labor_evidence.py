from bonus_platform.engine.labor.evidence import LaborPageEvidence, select_invoice_evidence


def test_selects_explicit_total_from_second_invoice_page():
    pages = [
        LaborPageEvidence(
            source_file="warehouse-2.pdf",
            page=1,
            role="invoice_primary",
            role_confidence=0.99,
            warehouse_id="2",
        ),
        LaborPageEvidence(
            source_file="warehouse-2.pdf",
            page=2,
            role="invoice_total",
            role_confidence=0.98,
            warehouse_id="2",
            total_amount=4105.15,
            total_label="TOTAL",
            evidence_text="TOTAL $4,105.15",
        ),
    ]

    result = select_invoice_evidence("warehouse-2.pdf", pages)

    assert result.total_amount == 4105.15
    assert result.total_page == 2
    assert result.evidence_status == "authoritative"
    assert result.authoritative is True


def test_selects_plural_totals_label_from_invoice_page():
    pages = [
        LaborPageEvidence(
            source_file="In291943.pdf",
            page=1,
            role="invoice_total",
            role_confidence=0.98,
            warehouse_id="29",
            total_amount=13836.28,
            total_label="Totals",
            evidence_text="Totals $13,836.28",
            extraction_method="text_explicit_total",
        ),
        LaborPageEvidence(
            source_file="In291943.pdf",
            page=2,
            role="invoice_continuation",
            role_confidence=0.95,
            warehouse_id="29",
        ),
    ]

    result = select_invoice_evidence("In291943.pdf", pages)

    assert result.total_amount == 13836.28
    assert result.total_page == 1
    assert result.evidence_status == "authoritative"
    assert result.authoritative is True


def test_excludes_supporting_attachment_amounts():
    pages = [
        LaborPageEvidence(
            source_file="warehouse-5.pdf",
            page=1,
            role="invoice_total",
            role_confidence=0.99,
            warehouse_id="5",
            total_amount=4222.26,
            total_label="Invoice Total",
        ),
        LaborPageEvidence(
            source_file="warehouse-5.pdf",
            page=2,
            role="timecard_summary",
            role_confidence=0.99,
            total_amount=4222.26,
        ),
        LaborPageEvidence(
            source_file="warehouse-5.pdf",
            page=3,
            role="daily_detail",
            role_confidence=0.99,
            total_amount=4222.26,
        ),
        LaborPageEvidence(
            source_file="warehouse-5.pdf",
            page=4,
            role="supporting_attachment",
            role_confidence=0.99,
            total_amount=4222.26,
        ),
    ]

    result = select_invoice_evidence("warehouse-5.pdf", pages)

    assert result.total_amount == 4222.26
    assert result.total_page == 1
    assert result.excluded_pages == (2, 3, 4)


def test_non_invoice_boundary_excludes_later_adjustment_total():
    pages = [
        LaborPageEvidence(
            source_file="warehouse-9.pdf",
            page=1,
            role="invoice_primary",
            role_confidence=0.99,
            warehouse_id="9",
        ),
        LaborPageEvidence(
            source_file="warehouse-9.pdf",
            page=2,
            role="invoice_total",
            role_confidence=0.99,
            warehouse_id="9",
            total_amount=11837.79,
            total_label="TOTAL",
        ),
        LaborPageEvidence(
            source_file="warehouse-9.pdf",
            page=3,
            role="email_cover",
            role_confidence=0.99,
        ),
        LaborPageEvidence(
            source_file="warehouse-9.pdf",
            page=5,
            role="invoice_total",
            role_confidence=0.99,
            warehouse_id="9",
            total_amount=226.76,
            total_label="Total",
        ),
    ]

    result = select_invoice_evidence("warehouse-9.pdf", pages)

    assert result.total_amount == 11837.79
    assert result.total_page == 2
    assert result.authoritative is True
    assert result.excluded_pages == (3, 5)


def test_later_adjustment_total_cannot_replace_missing_invoice_total():
    pages = [
        LaborPageEvidence(
            source_file="warehouse-9.pdf",
            page=1,
            role="invoice_primary",
            role_confidence=0.99,
            warehouse_id="9",
        ),
        LaborPageEvidence(
            source_file="warehouse-9.pdf",
            page=2,
            role="invoice_total",
            role_confidence=0.99,
            warehouse_id="9",
        ),
        LaborPageEvidence(
            source_file="warehouse-9.pdf",
            page=3,
            role="email_cover",
            role_confidence=0.99,
        ),
        LaborPageEvidence(
            source_file="warehouse-9.pdf",
            page=5,
            role="invoice_total",
            role_confidence=0.99,
            warehouse_id="9",
            total_amount=226.76,
            total_label="Total",
        ),
    ]

    result = select_invoice_evidence("warehouse-9.pdf", pages)

    assert result.total_amount is None
    assert result.authoritative is False
    assert result.evidence_status == "needs_review"
    assert result.excluded_pages == (3, 5)


def test_conflicting_explicit_totals_require_review():
    pages = [
        LaborPageEvidence(
            source_file="warehouse-9.pdf",
            page=1,
            role="invoice_total",
            role_confidence=0.99,
            warehouse_id="9",
            total_amount=11837.79,
            total_label="TOTAL",
        ),
        LaborPageEvidence(
            source_file="warehouse-9.pdf",
            page=2,
            role="invoice_total",
            role_confidence=0.98,
            warehouse_id="9",
            total_amount=11611.03,
            total_label="Amount Due",
        ),
    ]

    result = select_invoice_evidence("warehouse-9.pdf", pages)

    assert result.total_amount is None
    assert result.total_page is None
    assert result.evidence_status == "needs_review"
    assert result.authoritative is False


def test_unknown_supplier_with_unique_high_confidence_total_is_authoritative():
    pages = [
        LaborPageEvidence(
            source_file="unknown-supplier.pdf",
            page=1,
            role="unknown",
            role_confidence=0.62,
            warehouse_id="17",
        ),
        LaborPageEvidence(
            source_file="unknown-supplier.pdf",
            page=2,
            role="invoice_total",
            role_confidence=0.97,
            warehouse_id="17",
            total_amount=1961.93,
            total_label="Balance Due",
            evidence_text="Balance Due $1,961.93",
        ),
    ]

    result = select_invoice_evidence("unknown-supplier.pdf", pages)

    assert result.total_amount == 1961.93
    assert result.total_page == 2
    assert result.evidence_status == "authoritative"
    assert result.authoritative is True


def test_unknown_supplier_with_ambiguous_total_requires_review():
    pages = [
        LaborPageEvidence(
            source_file="unknown-supplier.pdf",
            page=1,
            role="invoice_primary",
            role_confidence=0.91,
            warehouse_id="18",
            total_amount=184.03,
        ),
        LaborPageEvidence(
            source_file="unknown-supplier.pdf",
            page=2,
            role="invoice_continuation",
            role_confidence=0.92,
            warehouse_id="18",
            total_amount=200.03,
        ),
    ]

    result = select_invoice_evidence("unknown-supplier.pdf", pages)

    assert result.total_amount is None
    assert result.total_page is None
    assert result.evidence_status == "needs_review"
    assert result.authoritative is False


def test_unknown_supplier_explicit_total_can_be_authoritative_without_warehouse_id():
    pages = [
        LaborPageEvidence(
            source_file="unknown-layout.pdf",
            page=1,
            role="invoice_total",
            role_confidence=0.98,
            warehouse_id="",
            total_amount=2682.75,
            total_label="NET TOTAL",
            evidence_text="NET TOTAL: $2,682.75",
            extraction_method="text_explicit_total",
        )
    ]

    result = select_invoice_evidence("unknown-layout.pdf", pages)

    assert result.authoritative is True
    assert result.total_amount == 2682.75
    assert result.warehouse_id == ""


def test_explicit_total_conflicts_with_complete_invoice_line_sum():
    pages = [
        LaborPageEvidence(
            source_file="warehouse-1.pdf",
            page=1,
            role="invoice_total",
            role_confidence=0.99,
            warehouse_id="1",
            total_amount=100.00,
            total_label="TOTAL",
        ),
        LaborPageEvidence(
            source_file="warehouse-1.pdf",
            page=2,
            role="invoice_continuation",
            role_confidence=0.99,
            warehouse_id="1",
            total_amount=120.00,
            extraction_method="complete_invoice_line_sum",
        ),
    ]

    result = select_invoice_evidence("warehouse-1.pdf", pages)

    assert result.evidence_status == "needs_review"
    assert result.authoritative is False
    assert result.total_amount is None


def test_matching_explicit_total_and_complete_invoice_line_sum_selects_explicit_total():
    pages = [
        LaborPageEvidence(
            source_file="warehouse-1.pdf",
            page=1,
            role="invoice_total",
            role_confidence=0.99,
            warehouse_id="1",
            total_amount=100.00,
            total_label="TOTAL",
        ),
        LaborPageEvidence(
            source_file="warehouse-1.pdf",
            page=2,
            role="invoice_continuation",
            role_confidence=0.99,
            warehouse_id="1",
            total_amount=100.00,
            extraction_method="complete_invoice_line_sum",
        ),
    ]

    result = select_invoice_evidence("warehouse-1.pdf", pages)

    assert result.evidence_status == "authoritative"
    assert result.authoritative is True
    assert result.total_amount == 100.00
    assert result.total_page == 1


def test_explicitly_configured_profile_dict_method_is_used():
    pages = [
        LaborPageEvidence(
            source_file="profiled.pdf",
            page=1,
            role="invoice_total",
            role_confidence=0.99,
            warehouse_id="27",
            total_amount=8302.85,
            extraction_method="configured_invoice_field",
        ),
    ]

    result = select_invoice_evidence(
        "profiled.pdf",
        pages,
        profile={"authoritative_total_method": "configured_invoice_field"},
    )

    assert result.evidence_status == "authoritative"
    assert result.authoritative is True
    assert result.total_amount == 8302.85


def test_low_confidence_invoice_warehouse_id_cannot_authorize_total():
    pages = [
        LaborPageEvidence(
            source_file="warehouse-2.pdf",
            page=1,
            role="invoice_primary",
            role_confidence=0.89,
            warehouse_id="2",
        ),
        LaborPageEvidence(
            source_file="warehouse-2.pdf",
            page=2,
            role="invoice_total",
            role_confidence=0.99,
            total_amount=4105.15,
            total_label="TOTAL",
        ),
    ]

    result = select_invoice_evidence("warehouse-2.pdf", pages)

    assert result.evidence_status == "needs_review"
    assert result.authoritative is False
    assert result.total_amount is None


def test_mismatched_non_empty_page_source_file_requires_review():
    pages = [
        LaborPageEvidence(
            source_file="another-invoice.pdf",
            page=1,
            role="invoice_total",
            role_confidence=0.99,
            warehouse_id="5",
            total_amount=4222.26,
            total_label="TOTAL",
        ),
    ]

    result = select_invoice_evidence("warehouse-5.pdf", pages)

    assert result.evidence_status == "needs_review"
    assert result.authoritative is False
    assert result.total_amount is None

import json
from pathlib import Path


def _case(case_id, *, recognizable=True, subtotal=100.0, pages=None):
    return {
        "id": case_id,
        "recognizable": recognizable,
        "employeeSubtotal": subtotal,
        "officialInvoicePages": pages or [1],
        "expectedCanRelease": recognizable,
        "expectedRequiresHumanReview": not recognizable,
        "reviewReason": "" if recognizable else "evidence_failure",
    }


def _result(*, amount=100.0, rows=True, pages=None, can_release=True, review=False):
    return {
        "extractedRows": [{"amount": amount}] if rows else [],
        "selectedInvoicePages": pages or [1],
        "canRelease": can_release,
        "requiresHumanReview": review,
    }


def test_generalization_gate_enforces_coverage_and_closure_independently():
    from tools.labor_generalization_regression import evaluate_generalization

    truth = {"cases": [_case(f"case-{index}") for index in range(10)]}
    results = {f"case-{index}": _result(rows=index < 8, amount=100 if index != 8 else 90) for index in range(10)}

    evaluated = evaluate_generalization(truth, results)

    assert evaluated["recognizableCount"] == 10
    assert evaluated["detailCoverageRatio"] == 0.8
    assert evaluated["amountClosureRatio"] == 0.8
    assert evaluated["passed"] is False


def test_generalization_gate_blocks_any_unsafe_release():
    from tools.labor_generalization_regression import evaluate_generalization

    truth = {"cases": [_case("missing-total", recognizable=False)]}
    results = {"missing-total": _result(can_release=True, review=False)}

    evaluated = evaluate_generalization(truth, results)

    assert evaluated["unsafeReleaseCount"] == 1
    assert evaluated["safetyPassRatio"] == 0.0
    assert evaluated["passed"] is False
    assert evaluated["safetyFailures"][0]["scenarioId"] == "missing-total"


def test_generalization_gate_rejects_attachment_page_as_invoice_evidence():
    from tools.labor_generalization_regression import evaluate_generalization

    truth = {"cases": [_case("cover-invoice", pages=[2])]}
    results = {"cover-invoice": _result(pages=[1, 2])}

    evaluated = evaluate_generalization(truth, results)

    assert evaluated["pageRoleAccuracyRatio"] == 0.0
    assert evaluated["pageRoleFailures"][0]["expectedPages"] == [2]
    assert evaluated["passed"] is False


def test_generalization_gate_passes_complete_safe_result_and_builds_report():
    from tools.labor_generalization_regression import build_markdown, evaluate_generalization

    truth = {"cases": [_case("good"), _case("bad-evidence", recognizable=False)]}
    results = {
        "good": _result(),
        "bad-evidence": _result(rows=False, can_release=False, review=True),
    }

    evaluated = evaluate_generalization(truth, results)
    markdown = build_markdown(evaluated)

    assert evaluated["passed"] is True
    assert evaluated["unsafeReleaseCount"] == 0
    assert "未知供应商泛化回归门禁" in markdown
    assert "100%" in markdown


def test_generalization_cli_returns_nonzero_when_gate_fails(tmp_path):
    from tools.labor_generalization_regression import main

    truth_path = tmp_path / "truth.json"
    results_path = tmp_path / "results.json"
    truth_path.write_text(json.dumps({"cases": [_case("unsafe", recognizable=False)]}), encoding="utf-8")
    results_path.write_text(json.dumps({"unsafe": _result(can_release=True)}), encoding="utf-8")

    exit_code = main(
        [
            "--truth", str(truth_path),
            "--results", str(results_path),
            "--json-output", str(tmp_path / "gate.json"),
            "--markdown-output", str(tmp_path / "gate.md"),
        ]
    )

    assert exit_code == 1
    assert Path(tmp_path / "gate.json").exists()


class _FakeTransport:
    def __init__(self, terminal=None, fail_poll=False):
        self.calls = []
        self.terminal = terminal or {
            "id": "labor_synthetic",
            "status": "已生成差异报告",
            "pdfExtractedRows": [{"amount": 100, "source_page_or_row": "1"}],
            "comparisonSummary": {"canRelease": True},
            "requiresHumanReview": False,
        }
        self.fail_poll = fail_poll

    def post_json(self, path, payload):
        self.calls.append(("post_json", path, payload))
        if path == "/api/labor/runs":
            return {"id": "labor_synthetic"}
        if path.endswith("/extract-and-compare"):
            return {"status": "抽取中"}
        return {"status": "ok"}

    def post_files(self, path, pdf_path, workbook_path):
        self.calls.append(("post_files", path, pdf_path.name, workbook_path.name))
        return {"status": "已上传文件"}

    def get_json(self, path):
        self.calls.append(("get_json", path))
        if self.fail_poll:
            raise TimeoutError("poll timeout")
        return self.terminal


def _write_replay_fixture(tmp_path):
    (tmp_path / "case.pdf").write_bytes(b"%PDF-1.4\n")
    (tmp_path / "case.xlsx").write_bytes(b"xlsx")
    truth = {
        "cases": [
            {
                "id": "case",
                "pdfFile": "case.pdf",
                "workbookFile": "case.xlsx",
                "officialInvoicePages": [1],
                "recognizable": True,
            }
        ]
    }
    truth_path = tmp_path / "truth.json"
    truth_path.write_text(json.dumps(truth), encoding="utf-8")
    return truth_path


def test_replay_fixture_set_uses_formal_api_flow_and_extracts_result(tmp_path):
    from tools.labor_generalization_replay import replay_fixture_set

    truth_path = _write_replay_fixture(tmp_path)
    transport = _FakeTransport()
    result = replay_fixture_set(
        "http://example.test",
        tmp_path,
        truth_path,
        transport=transport,
        poll_interval=0,
        poll_timeout=1,
    )

    assert result["case"]["runId"] == "labor_synthetic"
    assert result["case"]["selectedInvoicePages"] == [1]
    assert result["case"]["canRelease"] is True
    assert [call[0] for call in transport.calls[:4]] == ["post_json", "post_files", "post_json", "post_json"]
    mapping_call = transport.calls[2]
    assert mapping_call[2]["mapping"]["amount"] == "Amount"
    assert transport.calls[0][2]["require_employee_detail"] is True


def test_replay_fixture_set_persists_run_id_and_resumes_polling_after_timeout(tmp_path):
    from tools.labor_generalization_replay import replay_fixture_set

    truth_path = _write_replay_fixture(tmp_path)
    results_path = tmp_path / "results.json"
    first = replay_fixture_set(
        "http://example.test",
        tmp_path,
        truth_path,
        results_path=results_path,
        transport=_FakeTransport(fail_poll=True),
        poll_interval=0,
        poll_timeout=0.01,
    )
    second_transport = _FakeTransport()
    second = replay_fixture_set(
        "http://example.test",
        tmp_path,
        truth_path,
        results_path=results_path,
        transport=second_transport,
        poll_interval=0,
        poll_timeout=1,
    )

    assert first["case"]["runId"] == "labor_synthetic"
    assert first["case"]["status"] == "poll_timeout"
    assert second["case"]["status"] == "已生成差异报告"
    assert all(call[0] == "get_json" for call in second_transport.calls)


def test_requests_transport_bypasses_environment_proxy_for_local_replay():
    from tools.labor_generalization_replay import RequestsTransport

    transport = RequestsTransport("http://127.0.0.1:8001")

    assert transport.session.trust_env is False


def test_requests_transport_sends_current_formal_client_contract(monkeypatch):
    from tools.labor_generalization_replay import RequestsTransport

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    captured = {}
    transport = RequestsTransport("http://127.0.0.1:8001")
    monkeypatch.setattr(
        transport.session,
        "get",
        lambda *_args, **_kwargs: Response(
            {"version": "0.5-uat", "apiContractVersion": 2, "buildId": "build-current"}
        ),
    )

    def fake_post(_url, *, json, headers, timeout):
        captured.update({"json": json, "headers": headers, "timeout": timeout})
        return Response({"id": "labor-probe"})

    monkeypatch.setattr(transport.session, "post", fake_post)

    result = transport.post_json("/api/labor/runs", {"supplier_name": "Synthetic"})

    assert result["id"] == "labor-probe"
    assert captured["headers"] == {
        "x-sigma-labor-api-contract": "2",
        "x-sigma-labor-ui-version": "0.5-uat",
        "x-sigma-labor-ui-build": "build-current",
    }

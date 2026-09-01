from __future__ import annotations

import base64
import hashlib
from types import SimpleNamespace

import pytest

from bonus_platform.engine.overseas_payroll import service
from bonus_platform.engine.overseas_payroll.router import FRONTEND_PATH, page_router, router


def test_lists_eight_handover_tools() -> None:
    tools = service.list_tools()

    assert len(tools) == 8
    assert {tool["id"] for tool in tools} == {
        "swedish_tax",
        "dutch_pension",
        "humana_details",
        "import_paie",
        "norway_payslip",
        "norway_payment",
        "italy_payslip",
        "dutch_payslip",
    }


def test_vendored_frontend_matches_handover_checksum() -> None:
    digest = hashlib.sha256(FRONTEND_PATH.read_bytes()).hexdigest()

    assert digest == "539bb0da81d9ca7c9a4d31a3416588b51f51b57ed2fbe32de2c58dc80de622bc"


def test_routers_expose_native_and_original_frontend_contracts() -> None:
    native_paths = {route.path for route in router.routes}
    compatibility_paths = {route.path for route in page_router.routes}

    assert "/api/overseas-payroll/tools" in native_paths
    assert "/api/overseas-payroll/tools/{tool_id}/process" in native_paths
    assert {"/overseas-payroll.html", "/api/tools", "/api/tool/{tool_id}/process"} <= compatibility_paths


def test_single_file_tool_returns_decoded_content(monkeypatch: pytest.MonkeyPatch) -> None:
    encoded = base64.b64encode(b"xlsx-result").decode("ascii")
    legacy = SimpleNamespace(process_swedish_tax=lambda filename, raw: ("result.xlsx", encoded, "2 名员工"))
    monkeypatch.setattr(service, "_legacy_module", lambda: legacy)

    result = service.process_files("swedish_tax", [("tax.pdf", b"pdf")])

    assert result.filename == "result.xlsx"
    assert result.content == b"xlsx-result"
    assert result.summary == "2 名员工"


def test_multi_file_tool_builds_legacy_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def process(payload):
        captured.update(payload)
        return "paie.zip", base64.b64encode(b"zip-result").decode("ascii"), "生成完成"

    monkeypatch.setattr(service, "_legacy_module", lambda: SimpleNamespace(process_import_paie_multi=process))

    result = service.process_files("import_paie", [("source.xlsx", b"source"), ("template.xlsx", b"template")])

    assert result.content == b"zip-result"
    assert [item["filename"] for item in captured["files"]] == ["source.xlsx", "template.xlsx"]


def test_rejects_wrong_extension_before_loading_parsers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "_legacy_module", lambda: pytest.fail("parser should not load"))

    with pytest.raises(ValueError, match="格式不支持"):
        service.process_files("swedish_tax", [("tax.xlsx", b"data")])


def test_rejects_multiple_files_for_single_file_tool() -> None:
    with pytest.raises(ValueError, match="只支持一个文件"):
        service.process_files("italy_payslip", [("a.pdf", b"a"), ("b.pdf", b"b")])

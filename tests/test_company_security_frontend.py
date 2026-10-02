from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bonus_platform.engine.overseas_payroll import router as payroll_router


ROOT = Path(__file__).resolve().parents[1]


def _run_browser_script(script: str, *, next_url: str = "/", status: int = 200, hostname: str = "hras.example", mock: bool = False, network_error: bool = False, malformed_me: bool = False, mock_click: bool = False) -> dict:
    if not shutil.which("node"):
        pytest.skip("Node is required to execute frontend security regression scenarios")
    options = json.dumps({"script": str(ROOT / "bonus_platform/static" / script), "next": next_url, "status": status, "hostname": hostname, "mock": mock, "networkError": network_error, "malformedMe": malformed_me, "mockClick": mock_click})
    harness = r"""
const vm = require('node:vm');
const fs = require('node:fs');
const options = JSON.parse(process.argv[1]);
const outcome = { redirected: '', blocked: '', finished: false, requests: [], stateWritten: false };
const store = () => ({ getItem: () => null, removeItem() {}, setItem() { outcome.stateWritten = true; } });
const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {
    classList: { add() {}, remove() {} },
    listeners: {}, setAttribute() {}, getAttribute: () => 'false', addEventListener(name, callback) { this.listeners[name] = callback; }, appendChild() {},
    textContent: '', hidden: true,
  });
  return elements.get(id);
}
const document = {
  documentElement: {
    dataset: { moduleId: 'domestic' },
    classList: { add() {}, remove() { outcome.finished = true; } },
  },
  body: { appendChild() {} }, head: { appendChild() {} },
  getElementById(id) {
    if (id === 'loginSmokeyCanvas' || id === 'permissionLoadingStyles') return null;
    return element(id);
  },
  querySelector: () => null, createElement: () => element('created'),
  addEventListener() {}, open() {}, close() {}, write(html) { outcome.blocked = html; },
};
const location = {
  protocol: 'https:', hostname: options.hostname, origin: 'https://' + options.hostname,
  pathname: '/domestic-labor.html', search: '?next=' + encodeURIComponent(options.next),
  replace(target) { outcome.redirected = target; },
};
const window = {
  location, setInterval: () => 1, clearInterval() {}, setTimeout: () => 1, clearTimeout() {}, stop() {},
};
const me = { user: { id: 'real-user', roleIds: ['domesticAdmin'] }, modules: [{ id: 'domestic', enabled: true, canEnter: true }], permissions: { rolePermissions: {}, moduleAccess: {} } };
const fetch = async (url) => {
  outcome.requests.push(url);
  if (url === '/api/auth/feishu/config') return { ok: true, status: 200, json: async () => ({ configured: false, mockLoginEnabled: options.mock }) };
  if (options.networkError) throw new Error('offline');
  return { ok: options.status >= 200 && options.status < 300, status: options.status, json: async () => options.malformedMe ? {} : me };
};
const context = vm.createContext({ document, window, location, fetch, sessionStorage: store(), localStorage: store(), URL, URLSearchParams, AbortController, HTMLCanvasElement: class {}, setTimeout, console });
(async () => {
  await vm.runInContext(fs.readFileSync(options.script, 'utf8'), context);
  await new Promise(resolve => setImmediate(resolve));
  await new Promise(resolve => setImmediate(resolve));
  if (options.mockClick) await element('loginUserList').listeners.click({ target: { closest: () => ({ dataset: { userId: 'payrollAdmin' } }) } });
  outcome.mockPanelHidden = element('mockLoginPanel').hidden;
  outcome.redirected ||= location.href || '';
  process.stdout.write(JSON.stringify(outcome));
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    result = subprocess.run(["node", "-e", harness, options], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


@pytest.mark.parametrize("next_url", [
    "//evil.example", "/\\evil.example", "https://evil.example", "javascript:alert(1)",
    "/%2fevil.example", "/%5cevil.example", "/%252fevil.example", "/%255cevil.example",
    "/\tevil.example", "/%0aevil.example", "login.html?next=//evil.example", "not-a-path",
])
def test_login_rejects_external_or_ambiguous_next(next_url: str) -> None:
    outcome = _run_browser_script("login.js", next_url=next_url)
    assert outcome["redirected"] == "/"


@pytest.mark.parametrize("next_url", ["/", "/domestic-labor.html#view=canbuBatches", "/social-insurance.html?subject=test#employees"])
def test_login_preserves_valid_module_location(next_url: str) -> None:
    assert _run_browser_script("login.js", next_url=next_url)["redirected"] == next_url


@pytest.mark.parametrize("status", [403, 404, 500, 503])
def test_permission_guard_never_grants_mock_admin_on_failed_response(status: int) -> None:
    outcome = _run_browser_script("permission-guard.js", status=status)
    assert not outcome["finished"]
    assert "权限校验失败" in outcome["blocked"]


def test_permission_guard_still_accepts_authorized_user() -> None:
    outcome = _run_browser_script("permission-guard.js")
    assert outcome["finished"]
    assert not outcome["blocked"]


@pytest.mark.parametrize("hostname", ["hras.example", "localhost"])
def test_permission_guard_network_failure_without_explicit_mock_is_closed(hostname: str) -> None:
    outcome = _run_browser_script("permission-guard.js", hostname=hostname, network_error=True)
    assert not outcome["finished"]
    assert "权限校验失败" in outcome["blocked"]


def test_permission_guard_explicit_local_mock_preview_stays_usable() -> None:
    outcome = _run_browser_script("permission-guard.js", hostname="localhost", network_error=True, mock=True)
    assert outcome["finished"]


def test_permission_guard_invalid_success_payload_cannot_restore_default_admin() -> None:
    outcome = _run_browser_script("permission-guard.js", malformed_me=True)
    assert not outcome["finished"]
    assert "权限校验失败" in outcome["blocked"]


def test_remote_login_never_enables_or_calls_mock_login() -> None:
    outcome = _run_browser_script("login.js", status=401, mock=True, mock_click=True)
    assert outcome["mockPanelHidden"]
    assert "/api/auth/mock-login" not in outcome["requests"]
    assert not outcome["redirected"]
    assert not outcome["stateWritten"]


def test_explicit_local_mock_login_retains_preview_fallback() -> None:
    outcome = _run_browser_script("login.js", hostname="localhost", status=401, mock=True, mock_click=True)
    assert not outcome["mockPanelHidden"]
    assert "/api/auth/mock-login" in outcome["requests"]
    assert outcome["redirected"] == "/"
    assert outcome["stateWritten"]


def test_served_tools_use_platform_login_without_legacy_lock_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(payroll_router, "_require_access", lambda _: "synthetic-owner")
    app = FastAPI()
    app.include_router(payroll_router.page_router)
    with TestClient(app) as client:
        response = client.get("/overseas-payroll.html")
    assert response.status_code == 200
    for obsolete in ["/api/unlock", "/api/change-passcode", "paie_sid", "PAIE_SID", "id=\"lockModal\"", "id=\"chgModal\"", "id=\"chgpassbtn\"", "function unlock(", "function changePasscode(", "sp.get('sid')"]:
        assert obsolete not in response.text
    assert "共享口令" not in response.text
    assert "const grid = document.getElementById('grid')" in response.text
    assert '<script src="/overseas-payroll-async.js?v=4"></script>' in response.text
    # Parse the real served inline JavaScript, not just an isolated replacement snippet.
    inline = re.search(r"<script>(.*?)</script>", response.text, re.S).group(1)
    if shutil.which("node"):
        subprocess.run(["node", "-e", "new (require('node:vm').Script)(process.argv[1])", inline], check=True, capture_output=True, text=True)


def test_handover_drift_cannot_serve_the_legacy_auth_page(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = payroll_router.FRONTEND_PATH.read_text(encoding="utf-8")
    source = source.replace("let PAIE_SID =", "let UNEXPECTED_SID =", 1)
    changed_frontend = tmp_path / "changed.html"
    changed_frontend.write_text(source, encoding="utf-8")
    monkeypatch.setattr(payroll_router, "FRONTEND_PATH", changed_frontend)
    monkeypatch.setattr(payroll_router, "_require_access", lambda _: "synthetic-owner")
    app = FastAPI()
    app.include_router(payroll_router.page_router)
    with TestClient(app) as client:
        response = client.get("/overseas-payroll.html")
    assert response.status_code == 503
    assert response.json() == {"detail": "海外薪资页面暂不可用，请联系维护人员。"}
    assert "/api/unlock" not in response.text
    assert str(tmp_path) not in response.text

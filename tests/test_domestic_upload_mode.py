from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import bonus_platform.app as app_module


ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.usefixtures("bypass_domestic_labor_access_gate")


@pytest.mark.parametrize(
    ("backend", "expected"),
    [("s3", "server"), ("obs", "server"), ("supabase", "direct")],
)
def test_domestic_upload_mode_follows_storage_backend(monkeypatch, backend, expected):
    monkeypatch.setenv("SIGMA_DOMESTIC_LABOR_STORAGE_BACKEND", backend)
    response = TestClient(app_module.app).get("/api/domestic-labor/upload-mode")
    assert response.status_code == 200
    assert response.json() == {"mode": expected}


def test_domestic_server_upload_mode_skips_signed_upload_plan():
    if not shutil.which("node"):
        pytest.skip("Node.js is not installed")
    source = (ROOT / "bonus_platform/static/domestic-labor.js").read_text(encoding="utf-8")
    mode_function = source[
        source.index("async function getDomesticUploadMode("):source.index("async function submitDomesticLaborRun(")
    ]
    upload_function = source[
        source.index("async function submitDomesticLaborRun("):source.index("async function submitDomesticLaborRunDirect(")
    ]
    harness = r"""
const vm = require('node:vm');
const assert = require('node:assert/strict');
const calls = [];
const context = {
  requestJson: async url => { calls.push(url); return { mode: 'server' }; },
  updateUploadProgress: () => {},
  submitDomesticLaborRunDirect: async () => { throw new Error('unexpected direct upload'); },
  submitDomesticLaborRunMultipart: async payload => { calls.push('multipart'); return payload.files.length; },
};
vm.createContext(context);
vm.runInContext(process.argv[1] + '\n' + process.argv[2] + '\nthis.submit = submitDomesticLaborRun;', context);
(async () => {
  const result = await context.submit({file: {name:'a.xlsx',size:42}, engines:['canbu']});
  assert.equal(result, 1);
  assert.deepEqual(calls, ['/api/domestic-labor/upload-mode', 'multipart']);
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    result = subprocess.run(
        ["node", "-e", harness, mode_function, upload_function],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

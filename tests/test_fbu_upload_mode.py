from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import bonus_platform.app as app_module


ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.usefixtures("bypass_fbu_access_gate")


@pytest.mark.parametrize(
    ("backend", "expected"),
    [("s3", "server"), ("obs", "server"), ("supabase", "direct")],
)
def test_fbu_upload_mode_follows_storage_backend(monkeypatch, backend, expected):
    monkeypatch.setenv("SIGMA_FBU_STORAGE_BACKEND", backend)
    response = TestClient(app_module.app).get("/api/fbu-performance/upload-mode")
    assert response.status_code == 200
    assert response.json() == {"mode": expected}


def test_fbu_server_upload_mode_skips_signed_upload_plan():
    if not shutil.which("node"):
        pytest.skip("Node.js is not installed")
    source = (ROOT / "bonus_platform/static/fbu-performance.js").read_text(encoding="utf-8")
    mode_function = source[
        source.index("async function getFbuUploadMode("):source.index("async function uploadWorkbenchFilesDirect(")
    ]
    upload_function = source[
        source.index("async function uploadWorkbenchFilesDirect("):source.index("async function uploadWorkbenchAttendanceFilesDirect(")
    ]
    harness = r"""
const vm = require('node:vm');
const assert = require('node:assert/strict');
const calls = [];
const context = {
  API_BASE: '/api/fbu-performance',
  state: { currentActivity: { run_id: 'run_1' } },
  apiJson: async url => { calls.push(url); return { mode: 'server' }; },
};
vm.createContext(context);
vm.runInContext(process.argv[1] + '\n' + process.argv[2] + '\nthis.uploadFiles = uploadWorkbenchFilesDirect;', context);
(async () => {
  let fallbackCalls = 0;
  const result = await context.uploadFiles([{kind:'attendance', type:'attendance', file:{name:'a.xlsx',size:42}}], {
    fallback: async () => { fallbackCalls++; return 'uploaded'; },
  });
  assert.equal(result, 'uploaded');
  assert.equal(fallbackCalls, 1);
  assert.deepEqual(calls, ['/api/fbu-performance/upload-mode']);
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    result = subprocess.run(
        ["node", "-e", harness, mode_function, upload_function],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

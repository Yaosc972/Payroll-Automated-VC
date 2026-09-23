"""The OBS signed PUT must receive the file bytes, not a Supabase form body."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("script_path", "function_name", "next_function"),
    [
        ("bonus_platform/static/fbu-performance.js", "uploadFbuFileToSignedUrl", "async function uploadWorkbenchFilesDirect"),
        ("bonus_platform/static/domestic-labor.js", "uploadDomesticFileToSignedUrl", "function submitDomesticLaborRunMultipart"),
    ],
)
def test_obs_uses_raw_body_and_supabase_retains_form_body(script_path, function_name, next_function):
    if not shutil.which("node"):
        pytest.skip("Node.js is not installed")
    source = (ROOT / script_path).read_text(encoding="utf-8")
    function = source[source.index(f"function {function_name}("):source.index(next_function)]
    harness = r"""
const vm = require('node:vm');
const assert = require('node:assert/strict');
let request;
class MockFormData { constructor() { this.entries = []; } append(...entry) { this.entries.push(entry); } }
class MockXHR {
  constructor() { this.upload = {}; this.status = 200; this.headers = {}; request = this; }
  open(method, url) { this.method = method; this.url = url; }
  setRequestHeader(name, value) { this.headers[name] = value; }
  send(body) { this.body = body; this.onload(); }
}
const context = { XMLHttpRequest: MockXHR, FormData: MockFormData, WorkbenchProgress: { abortError: () => new Error('aborted') } };
vm.createContext(context);
vm.runInContext(process.argv[1] + '\nthis.uploadFile = ' + process.argv[2] + ';', context);
(async () => {
  const file = { name: 'attendance.xlsx', size: 42 };
  await context.uploadFile({ signedUrl: 'https://obs.invalid/signed', headers: {}, bodyFormat: 'raw' }, file, () => {});
  assert.equal(request.method, 'PUT');
  assert.equal(request.body, file);
  await context.uploadFile({ signedUrl: 'https://supabase.invalid/signed' }, file, () => {});
  assert.ok(request.body instanceof MockFormData);
  assert.equal(request.headers['x-upsert'], 'true');
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    result = subprocess.run(
        ["node", "-e", harness, function, function_name],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"{script_path}: {result.stderr}"

const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { webcrypto } = require('node:crypto');
const calls = [];
const raw = new Uint8Array(5 * 1024 * 1024).fill(7);
let broken = false;
const sandbox = { window: {}, crypto: webcrypto, Uint8Array, Blob, AbortSignal,
  fetch: async (url, options = {}) => {
    calls.push({ url, options });
    if (url.endsWith('/config/upload')) return Response.json({ directUpload: true });
    if (url.endsWith('/uploads')) return Response.json({ files: [{ signedUrl: 'https://storage.example/upload', method: 'PUT', headers: { 'content-type': 'application/octet-stream' } }] });
    if (url.endsWith('/start')) return Response.json({ status: 'running', runId: 'accepted' });
    if (url === 'https://storage.example/upload') return new Response(null, { status: broken ? 402 : 200 });
    if (url === 'https://storage.example/export') return new Response(raw);
    throw Error(`Unexpected request ${url}`);
  }
};
vm.runInNewContext(fs.readFileSync('bonus_platform/static/payroll-files.js', 'utf8'), sandbox);
(async () => {
  const file = new Blob([raw]); Object.defineProperty(file, 'name', { value: '考勤.xlsx' });
  const result = await sandbox.window.PayrollFiles.upload('activity', [file]);
  assert.equal(result.runId, 'accepted');
  const signed = calls.find(call => call.url.endsWith('/uploads'));
  assert.equal(JSON.parse(signed.options.body).files[0].size, raw.byteLength);
  assert.equal(calls.find(call => call.url === 'https://storage.example/upload').options.body, file);
  assert.equal(calls.filter(call => call.url.startsWith('/')).some(call => call.options.body instanceof Blob), false);
  calls.length = 0; broken = true;
  await assert.rejects(sandbox.window.PayrollFiles.upload('activity', [file]), /上传失败/);
  assert.equal(calls.some(call => call.url.endsWith('/start')), false);
  const hash = Buffer.from(await webcrypto.subtle.digest('SHA-256', raw)).toString('hex');
  const manifest = { downloadUrl: 'https://storage.example/export', filename: '九月餐补.xlsx', size: raw.byteLength, sha256: hash };
  const download = await sandbox.window.PayrollFiles.download(Response.json(manifest));
  assert.equal(download.blob.size, raw.byteLength); assert.equal(download.filename, manifest.filename);
  await assert.rejects(sandbox.window.PayrollFiles.download(Response.json({ ...manifest, sha256: '0'.repeat(64) })), /校验失败/);
  console.log('PASS: >4.5 MB private direct upload; upload failure blocks start; export integrity and Chinese filename');
})().catch(error => { console.error(error); process.exitCode = 1; });

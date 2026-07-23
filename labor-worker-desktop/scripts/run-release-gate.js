const { spawnSync } = require("node:child_process");
const path = require("node:path");

const python = process.env.PYTHON || (process.platform === "win32" ? "python" : "python3");
const gate = path.resolve(__dirname, "..", "..", "tools", "labor_worker_release_gate.py");
const result = spawnSync(python, [gate], {
  cwd: path.resolve(__dirname, ".."),
  env: process.env,
  stdio: "inherit",
  shell: false,
});

if (result.error) {
  console.error(`无法启动发布门禁（${python}）：${result.error.message}`);
  process.exit(1);
}
process.exit(result.status ?? 1);

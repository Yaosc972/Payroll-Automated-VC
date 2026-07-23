const { spawnSync } = require("node:child_process");

const python = process.env.PYTHON || (process.platform === "win32" ? "python" : "python3");
const result = spawnSync(
  python,
  [
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--distpath", "worker-dist",
    "--workpath", "worker-build",
    "pyinstaller-worker.spec"
  ],
  { stdio: "inherit", shell: process.platform === "win32" }
);

if (result.error) {
  console.error(result.error);
  process.exit(1);
}
process.exit(result.status ?? 0);

const { spawnSync } = require("child_process");

const python = process.env.PYTHON || (process.platform === "win32" ? "python" : "python3");
const args = [
  "-m",
  "PyInstaller",
  "--noconfirm",
  "--clean",
  "--distpath",
  "backend-dist",
  "--workpath",
  "backend-build",
  "pyinstaller-backend.spec"
];

const result = spawnSync(python, args, {
  stdio: "inherit",
  shell: process.platform === "win32"
});

if (result.error) {
  console.error(result.error);
  process.exit(1);
}

process.exit(result.status ?? 0);

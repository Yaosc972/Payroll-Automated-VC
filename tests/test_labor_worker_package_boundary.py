import json
from pathlib import Path

from bonus_platform import app as app_module
from bonus_platform.app import OVERSEAS_LABOR_REQUIRED_WORKER_VERSION
from bonus_platform.engine.labor.worker_version import worker_version_at_least


ROOT = Path(__file__).resolve().parents[1]
WORKER_DESKTOP = ROOT / "labor-worker-desktop"


def test_worker_release_version_is_explicit_and_not_older_than_server_gate():
    package = json.loads((WORKER_DESKTOP / "package.json").read_text(encoding="utf-8"))
    lockfile = json.loads((WORKER_DESKTOP / "package-lock.json").read_text(encoding="utf-8"))

    assert package["version"] == "0.3.12"
    assert lockfile["version"] == package["version"]
    assert lockfile["packages"][""]["version"] == package["version"]
    assert worker_version_at_least(package["version"], OVERSEAS_LABOR_REQUIRED_WORKER_VERSION)


def test_worker_environment_version_can_raise_but_not_lower_release_gate(monkeypatch):
    monkeypatch.setenv("SIGMA_LABOR_REQUIRED_WORKER_VERSION", "0.3.1")
    assert app_module._labor_required_worker_version() == OVERSEAS_LABOR_REQUIRED_WORKER_VERSION

    monkeypatch.setenv("SIGMA_LABOR_REQUIRED_WORKER_VERSION", "0.4.0")
    assert app_module._labor_required_worker_version() == "0.4.0"

    monkeypatch.setenv("SIGMA_LABOR_REQUIRED_WORKER_VERSION", "not-a-version")
    assert app_module._labor_required_worker_version() == OVERSEAS_LABOR_REQUIRED_WORKER_VERSION


def test_worker_pyinstaller_spec_has_worker_only_entry_and_output():
    spec = (WORKER_DESKTOP / "pyinstaller-worker.spec").read_text(encoding="utf-8")

    assert "Analysis(" in spec
    assert '["worker_entry.py"]' in spec
    assert "DESKTOP_ROOT = Path(SPECPATH)" in spec
    assert "PROJECT_ROOT = DESKTOP_ROOT.parent" in spec
    assert 'name="sigma-labor-worker"' in spec
    assert "worker-static-placeholder" in spec
    assert '"bonus_platform/static"' in spec
    assert 'ROOT / "bonus_platform" / "static"' not in spec
    assert "seed-data" not in spec
    assert "backend_entry.py" not in spec


def test_worker_static_placeholder_contains_no_platform_page_assets():
    placeholder = WORKER_DESKTOP / "worker-static-placeholder"
    assert (placeholder / ".keep").exists()
    assert not [path for path in placeholder.rglob("*") if path.suffix.lower() in {".html", ".js", ".css"}]


def test_worker_entry_does_not_start_the_platform_backend():
    entry = (WORKER_DESKTOP / "worker_entry.py").read_text(encoding="utf-8")

    assert "bonus_platform.worker.personal" in entry
    assert "uvicorn" not in entry
    assert "bonus_platform.app" not in entry


def test_worker_package_resources_do_not_include_platform_assets():
    package = (WORKER_DESKTOP / "package.json").read_text(encoding="utf-8")

    assert '"to": "worker/sigma-labor-worker"' in package
    assert "seed-data" not in package
    assert "bonus_platform/static" not in package
    assert "desktop/assets" not in package


def test_worker_installer_requires_formal_legacy_invoice_release_gate():
    package = json.loads((WORKER_DESKTOP / "package.json").read_text(encoding="utf-8"))
    wrapper = (WORKER_DESKTOP / "scripts" / "run-release-gate.js").read_text(encoding="utf-8")

    assert package["scripts"]["release:gate"] == "node scripts/run-release-gate.js"
    assert "labor_worker_release_gate.py" in wrapper
    assert 'process.env.PYTHON || (process.platform === "win32" ? "python" : "python3")' in wrapper
    assert package["scripts"]["dist:mac"].startswith("npm run release:gate &&")
    assert package["scripts"]["dist:win"].startswith("npm run release:gate &&")


def test_windows_builder_is_codex_independent_and_keeps_release_gate():
    powershell = (WORKER_DESKTOP / "build-windows.ps1").read_text(encoding="utf-8")
    launcher = (WORKER_DESKTOP / "build-windows.cmd").read_text(encoding="utf-8")

    assert powershell.isascii(), "Windows PowerShell 5.1 misdecodes UTF-8 scripts without a BOM"
    assert launcher.isascii(), "cmd launcher must remain encoding-independent"
    assert '$BuildCacheRoot = Join-Path $env:LOCALAPPDATA "SigmaWorkerBuild"' in powershell
    assert '$VenvRoot = Join-Path $BuildCacheRoot "py311"' in powershell
    assert '$VenvRoot = Join-Path $DesktopRoot ".venv-windows-build-py311"' not in powershell
    assert '$BuildPip = Join-Path $VenvRoot "Scripts\\pip.exe"' in powershell
    assert 'return @{ Command = "py"; Prefix = @("-3.11") }' in powershell
    assert 'Prefix = @("-3")' not in powershell
    assert '(@($SystemPython.Prefix) + @("-m", "venv", "--clear", $VenvRoot))' in powershell
    assert 'Invoke-Checked $BuildPython @("-m", "ensurepip", "--upgrade")' in powershell
    assert "Codex" not in powershell
    assert 'Invoke-Checked "npm" @("run", "release:gate")' in powershell
    assert 'Invoke-Checked "npx" @("electron-builder", "--win", "nsis", "--x64")' in powershell
    assert "SIGMA_LABOR_GOLDEN_MATERIALS_ROOT" in powershell
    assert 'Join-Path $DesktopRoot "release-gate-materials"' in powershell
    assert "ExecutionPolicy Bypass" in launcher

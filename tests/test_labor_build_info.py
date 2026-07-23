import json
from pathlib import Path

import pytest

from bonus_platform.engine.labor.build_info import (
    DEFAULT_LABOR_BUILD_PATTERNS,
    DEFAULT_LABOR_BUILD_SENTINELS,
    LABOR_BUILD_ENV_KEYS,
    LaborBuildMonitor,
    _labor_revision,
    _labor_source_files,
)


def test_labor_build_monitor_detects_source_changes_without_exposing_local_paths(tmp_path):
    (tmp_path / "app.py").write_text("VERSION = 1\n", encoding="utf-8")
    labor_dir = tmp_path / "engine" / "labor"
    labor_dir.mkdir(parents=True)
    (labor_dir / "extract.py").write_text("def extract(): return 1\n", encoding="utf-8")
    monitor = LaborBuildMonitor(
        tmp_path,
        patterns=("app.py", "engine/labor/**/*.py"),
        required_files=("app.py", "engine/labor/extract.py"),
        env={},
    )

    current = monitor.snapshot(
        env={},
        module_version="0.5-uat",
        api_contract_version=2,
        required_worker_version="0.3.0",
    )

    assert current["status"] == "current"
    assert current["startupFingerprint"] == current["currentFingerprint"]
    assert current["revision"] == f"local-{current['startupFingerprint'][:12]}"
    assert current["revisionSource"] == "source_fingerprint"
    assert str(tmp_path) not in json.dumps(current)

    (labor_dir / "extract.py").write_text("def extract(): return 2\n", encoding="utf-8")
    stale = monitor.snapshot(
        env={},
        module_version="0.5-uat",
        api_contract_version=2,
        required_worker_version="0.3.0",
    )

    assert stale["status"] == "restart_required"
    assert stale["startupFingerprint"] != stale["currentFingerprint"]


def test_labor_build_monitor_prefers_explicit_deployment_revision(tmp_path):
    (tmp_path / "app.py").write_text("VERSION = 1\n", encoding="utf-8")
    monitor = LaborBuildMonitor(
        tmp_path,
        patterns=("app.py",),
        required_files=("app.py",),
        env={"SIGMA_LABOR_BUILD_ID": "release-abc123"},
    )

    snapshot = monitor.snapshot(
        env={
            "SIGMA_LABOR_BUILD_ID": "release-abc123",
            "SIGMA_LABOR_SOURCE_REF": "codex/overseas-labor-p0",
            "VERCEL": "1",
            "SIGMA_LABOR_BUILD_TIME": "2026-07-15T08:00:00Z",
        },
        module_version="0.5-uat",
        api_contract_version=2,
        required_worker_version="0.3.0",
    )

    assert snapshot["revision"] == "release-abc123"
    assert snapshot["revisionSource"] == "explicit"
    assert snapshot["sourceRef"] == "codex/overseas-labor-p0"
    assert snapshot["runtime"] == "vercel"
    assert snapshot["builtAt"] == "2026-07-15T08:00:00Z"
    assert snapshot["requiredWorkerVersion"] == "0.3.0"


def test_labor_build_monitor_is_unverified_when_watch_set_is_empty(tmp_path):
    monitor = LaborBuildMonitor(
        tmp_path,
        patterns=("missing/**/*.py",),
        required_files=("app.py",),
        env={},
    )

    snapshot = monitor.snapshot(
        env={},
        module_version="0.5-uat",
        api_contract_version=2,
        required_worker_version="0.3.0",
    )

    assert snapshot["status"] == "unverified"
    assert snapshot["fileCount"] == 0
    assert snapshot["missingSentinels"] == ["app.py"]


def test_labor_build_monitor_is_unverified_when_required_sentinel_is_missing(tmp_path):
    (tmp_path / "app.py").write_text("VERSION = 1\n", encoding="utf-8")
    monitor = LaborBuildMonitor(
        tmp_path,
        patterns=("app.py",),
        required_files=("app.py", "static/overseas-labor.js"),
        env={},
    )

    snapshot = monitor.snapshot(
        env={},
        module_version="0.5-uat",
        api_contract_version=2,
        required_worker_version="0.3.0",
    )

    assert snapshot["status"] == "unverified"
    assert snapshot["fileCount"] == 1
    assert snapshot["missingSentinels"] == ["static/overseas-labor.js"]


def test_vercel_runtime_does_not_require_worker_package_lock_but_local_release_check_does(tmp_path):
    for relative_path in DEFAULT_LABOR_BUILD_SENTINELS:
        if relative_path == "labor-worker-desktop/package-lock.json":
            continue
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("release source\n", encoding="utf-8")

    vercel_snapshot = LaborBuildMonitor(tmp_path, env={"VERCEL": "1"}).snapshot(
        env={"VERCEL": "1"},
        module_version="0.5-uat",
        api_contract_version=2,
        required_worker_version="0.3.0",
    )
    local_snapshot = LaborBuildMonitor(tmp_path, env={}).snapshot(
        env={},
        module_version="0.5-uat",
        api_contract_version=2,
        required_worker_version="0.3.0",
    )

    assert vercel_snapshot["status"] == "current"
    assert "labor-worker-desktop/package-lock.json" not in vercel_snapshot["missingSentinels"]
    assert local_snapshot["status"] == "unverified"
    assert "labor-worker-desktop/package-lock.json" in local_snapshot["missingSentinels"]


def test_labor_revision_uses_short_local_build_id_without_explicit_environment():
    source_fingerprint = "a" * 64

    revision, revision_source = _labor_revision({}, source_fingerprint)

    assert revision == "local-aaaaaaaaaaaa"
    assert revision_source == "source_fingerprint"
    assert source_fingerprint not in revision


def test_labor_access_without_explicit_build_environment_hides_full_source_fingerprint(monkeypatch, tmp_path):
    import bonus_platform.app as app_module
    from fastapi.testclient import TestClient

    for name in LABOR_BUILD_ENV_KEYS:
        monkeypatch.delenv(name, raising=False)
    (tmp_path / "app.py").write_text("VERSION = 1\n", encoding="utf-8")
    monitor = LaborBuildMonitor(
        tmp_path,
        patterns=("app.py",),
        required_files=("app.py",),
        env={},
    )
    monkeypatch.setattr(app_module, "_LABOR_BUILD_MONITOR", monitor)

    response = TestClient(app_module.app).get("/api/labor/access")

    assert response.status_code == 200
    body = response.json()
    assert body["buildId"] == f"local-{monitor.startup_fingerprint[:12]}"
    assert body["build"]["buildId"] == body["buildId"]
    assert monitor.startup_fingerprint not in json.dumps(body)


def test_default_labor_build_patterns_cover_runtime_sources_but_not_generated_worker_outputs(tmp_path):
    included = {
        "api/index.py",
        "bonus_platform/static/index.html",
        "data/supplier_profiles/active.json",
        "bonus_platform/static/styles.css",
        "bonus_platform/static/assets/bonus-logo-dark.png",
        "bonus_platform/static/assets/bonus-logo-header-blue.png",
        "bonus_platform/static/assets/workbench-logo-2026.png",
        "bonus_platform/static/assets/workbench-sigma-mark.png",
        "bonus_platform/static/labor-operations.html",
        "bonus_platform/static/labor-operations.css",
        "bonus_platform/static/labor-operations.js",
        "labor-worker-desktop/main.js",
        "labor-worker-desktop/preload.js",
        "labor-worker-desktop/worker_entry.py",
        "labor-worker-desktop/pyinstaller-worker.spec",
        "labor-worker-desktop/package.json",
        "labor-worker-desktop/package-lock.json",
        "labor-worker-desktop/lib/activation.js",
        "labor-worker-desktop/renderer/app.js",
        "labor-worker-desktop/renderer/index.html",
        "labor-worker-desktop/renderer/styles.css",
        "labor-worker-desktop/scripts/build-worker.js",
        "labor-worker-desktop/assets/overseas-labor-worker.png",
        "labor-worker-desktop/worker-static-placeholder/.keep",
    }
    generated = {
        "labor-worker-desktop/node_modules/package/index.js",
        "labor-worker-desktop/worker-build/generated.txt",
        "labor-worker-desktop/worker-dist/sigma-labor-worker/binary",
        "labor-worker-desktop/release/worker.dmg",
    }
    for relative in included | generated:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative, encoding="utf-8")

    selected = {
        path.relative_to(tmp_path).as_posix()
        for path in _labor_source_files(tmp_path, patterns=DEFAULT_LABOR_BUILD_PATTERNS)
    }

    assert included <= selected
    assert selected.isdisjoint(generated)


@pytest.mark.parametrize(
    "relative_path",
    [
        "data/supplier_profiles/active.json",
        "bonus_platform/static/styles.css",
        "api/index.py",
        "bonus_platform/static/index.html",
        "bonus_platform/static/assets/workbench-logo-2026.png",
        "bonus_platform/static/assets/bonus-logo-header-blue.png",
        "bonus_platform/static/labor-operations.js",
        "labor-worker-desktop/main.js",
        "labor-worker-desktop/package.json",
        "labor-worker-desktop/worker-static-placeholder/.keep",
    ],
)
def test_default_labor_build_monitor_detects_active_runtime_source_changes(tmp_path, relative_path):
    source = tmp_path / relative_path
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("version 1\n", encoding="utf-8")
    monitor = LaborBuildMonitor(tmp_path, required_files=(), env={})

    current = monitor.snapshot(
        env={},
        module_version="0.5-uat",
        api_contract_version=2,
        required_worker_version="0.3.0",
    )
    source.write_text("version 2\n", encoding="utf-8")
    stale = monitor.snapshot(
        env={},
        module_version="0.5-uat",
        api_contract_version=2,
        required_worker_version="0.3.0",
    )

    assert current["status"] == "current"
    assert stale["status"] == "restart_required"


def test_default_labor_build_monitor_rejects_incomplete_home_ops_and_worker_bundle(tmp_path):
    legacy_sentinels = (
        "api/index.py",
        "bonus_platform/app.py",
        "bonus_platform/engine/labor/build_info.py",
        "bonus_platform/static/overseas-labor.html",
        "bonus_platform/static/overseas-labor.js",
        "labor-worker-desktop/main.js",
        "labor-worker-desktop/package.json",
        "labor-worker-desktop/worker_entry.py",
        "labor-worker-desktop/worker-static-placeholder/.keep",
    )
    for relative_path in legacy_sentinels:
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("minimal bundle\n", encoding="utf-8")

    snapshot = LaborBuildMonitor(tmp_path, env={}).snapshot(
        env={},
        module_version="0.5-uat",
        api_contract_version=2,
        required_worker_version="0.3.0",
    )

    assert snapshot["status"] == "unverified"
    assert {
        "bonus_platform/config.py",
        "bonus_platform/static/index.html",
        "bonus_platform/static/styles.css",
        "bonus_platform/static/labor-operations.js",
        "bonus_platform/static/assets/workbench-logo-2026.png",
        "bonus_platform/worker/personal.py",
        "labor-worker-desktop/renderer/app.js",
        "labor-worker-desktop/scripts/ad-hoc-sign-mac.js",
        "labor-worker-desktop/assets/overseas-labor-worker.icns",
        "vercel.json",
    } <= set(snapshot["missingSentinels"])


def test_labor_build_snapshot_rejects_supplier_profile_path_outside_release_bundle(monkeypatch, tmp_path):
    import bonus_platform.app as app_module

    external_profiles = tmp_path / "external-profiles"
    external_profiles.mkdir()
    (external_profiles / "supplier.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.setitem(app_module.AI_CONFIG, "supplier_profiles_path", str(external_profiles))

    snapshot = app_module._labor_build_snapshot()

    assert snapshot["status"] == "unverified"
    assert "supplier_profile_release_bundle" in snapshot["missingSentinels"]
    assert str(external_profiles) not in json.dumps(snapshot)


def test_labor_build_snapshot_rejects_missing_supplier_profile_path_inside_release_bundle(monkeypatch):
    import bonus_platform.app as app_module

    missing_profile = app_module.PROJECT_ROOT / "data" / "supplier_profiles" / "missing-p0-profile.json"
    assert not missing_profile.exists()
    monkeypatch.setitem(app_module.AI_CONFIG, "supplier_profiles_path", str(missing_profile))

    snapshot = app_module._labor_build_snapshot()

    assert snapshot["status"] == "unverified"
    assert "supplier_profile_release_bundle" in snapshot["missingSentinels"]


def test_labor_surfaces_do_not_load_unpinned_third_party_runtime_assets():
    static_root = Path(__file__).resolve().parents[1] / "bonus_platform" / "static"
    surface_text = "\n".join(
        (static_root / relative).read_text(encoding="utf-8")
        for relative in (
            "index.html",
            "overseas-labor.html",
            "labor-operations.html",
            "labor-operations.js",
        )
    )

    assert "https://" not in surface_text
    assert "http://" not in surface_text
    assert "@latest" not in surface_text


def test_labor_ci_scope_includes_real_entry_test_bootstrap_and_home_asset():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github" / "workflows" / "overseas-labor-ci.yml").read_text(encoding="utf-8")

    for path in (
        "api/index.py",
        "tests/conftest.py",
        "bonus_platform/static/assets/workbench-logo-2026.png",
    ):
        assert f'      - "{path}"' in workflow
    assert "api/index\\.py" in workflow
    assert "tests/(conftest\\.py" in workflow
    assert "workbench-logo-2026" in workflow


def test_labor_ci_final_gate_cannot_succeed_without_scope_check():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github" / "workflows" / "overseas-labor-ci.yml").read_text(encoding="utf-8")

    assert "workflow_dispatch:" not in workflow
    assert "if: github.event_name == 'pull_request' || github.event_name == 'push'" not in workflow
    assert 'test "$SCOPE_RESULT" = "success"' in workflow
    assert 'test "$SCOPE_RESULT" = "skipped"' not in workflow


def test_labor_ci_rejects_raw_invoice_and_workbook_materials():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github" / "workflows" / "overseas-labor-ci.yml").read_text(encoding="utf-8")

    assert "printf '%s\\n' \"$changed_paths\" | python3 tools/labor_candidate_material_guard.py ." in workflow


def test_labor_candidate_material_guard_blocks_known_and_unknown_raw_binaries(tmp_path):
    from tools.labor_candidate_material_guard import find_raw_material_paths

    blocked_paths = (
        "bonus_platform/engine/labor/private-invoice.gif",
        "bonus_platform/engine/labor/private-invoice.avif",
        "bonus_platform/engine/labor/private-ledger.ods",
        "bonus_platform/engine/labor/private-document.rtf",
        "bonus_platform/worker/private-scan.heif",
        "docs/labor_private_invoice.svg",
        "bonus_platform/engine/labor/private-material.unknown",
    )
    for relative_path in blocked_paths[:-1]:
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic-looking but forbidden material", encoding="utf-8")
    unknown_binary = tmp_path / blocked_paths[-1]
    unknown_binary.parent.mkdir(parents=True, exist_ok=True)
    unknown_binary.write_bytes(b"private\x00binary")

    allowed_paths = (
        "bonus_platform/engine/labor/runtime.py",
        "bonus_platform/static/assets/workbench-sigma-mark.png",
        "labor-worker-desktop/assets/overseas-labor-worker.png",
        "labor-worker-desktop/assets/overseas-labor-worker.icns",
        "labor-worker-desktop/assets/overseas-labor-worker.ico",
        "docs/labor_deleted_fixture.pdf",
    )
    source = tmp_path / allowed_paths[0]
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("VALUE = 1\n", encoding="utf-8")
    for relative_path in allowed_paths[1:-1]:
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"approved\x00asset")

    violations = find_raw_material_paths((*blocked_paths, *allowed_paths), root=tmp_path)

    assert set(violations) == set(blocked_paths)


def test_labor_candidate_material_guard_rejects_approved_asset_symlink(tmp_path):
    from tools.labor_candidate_material_guard import find_raw_material_paths

    private_material = tmp_path / "private-invoice.pdf"
    private_material.write_bytes(b"private invoice")
    approved_relative = "bonus_platform/static/assets/workbench-logo-2026.png"
    approved_path = tmp_path / approved_relative
    approved_path.parent.mkdir(parents=True, exist_ok=True)
    approved_path.symlink_to(private_material)

    assert find_raw_material_paths([approved_relative], root=tmp_path) == [approved_relative]


def test_labor_candidate_material_guard_accepts_utf8_split_at_sample_boundary(tmp_path):
    from tools.labor_candidate_material_guard import find_raw_material_paths

    relative_path = "bonus_platform/engine/labor/utf8_boundary.py"
    source = tmp_path / relative_path
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes((b"#" * 8191) + "中\nVALUE = 1\n".encode("utf-8"))

    assert find_raw_material_paths([relative_path], root=tmp_path) == []


def test_vercel_bundle_keeps_worker_sources_but_excludes_generated_outputs():
    root = Path(__file__).resolve().parents[1]
    lines = {
        line.strip()
        for line in (root / ".vercelignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert "labor-worker-desktop" not in lines
    for generated in (
        "labor-worker-desktop/node_modules",
        "labor-worker-desktop/worker-build",
        "labor-worker-desktop/worker-dist",
        "labor-worker-desktop/release",
        "labor-worker-desktop/dist",
    ):
        assert generated in lines

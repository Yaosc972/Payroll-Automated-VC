from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Optional, Sequence


DEFAULT_LABOR_BUILD_PATTERNS = (
    "api/index.py",
    "bonus_platform/app.py",
    "bonus_platform/config.py",
    "bonus_platform/engine/labor/**/*.py",
    "bonus_platform/worker/**/*.py",
    "bonus_platform/static/overseas-labor.html",
    "bonus_platform/static/overseas-labor.js",
    "bonus_platform/static/index.html",
    "bonus_platform/static/styles.css",
    "bonus_platform/static/assets/bonus-logo-dark.png",
    "bonus_platform/static/assets/bonus-logo-header-blue.png",
    "bonus_platform/static/assets/workbench-logo-2026.png",
    "bonus_platform/static/assets/workbench-sigma-mark.png",
    "bonus_platform/static/labor-operations.*",
    "data/supplier_profiles/**/*.json",
    "labor-worker-desktop/main.js",
    "labor-worker-desktop/preload.js",
    "labor-worker-desktop/worker_entry.py",
    "labor-worker-desktop/pyinstaller-worker.spec",
    "labor-worker-desktop/package.json",
    "labor-worker-desktop/package-lock.json",
    "labor-worker-desktop/lib/**/*.js",
    "labor-worker-desktop/renderer/**/*",
    "labor-worker-desktop/scripts/**/*.js",
    "labor-worker-desktop/assets/*",
    "labor-worker-desktop/worker-static-placeholder/.keep",
    "requirements.txt",
    "vercel.json",
)

DEFAULT_LABOR_BUILD_SENTINELS = (
    "requirements.txt",
    "vercel.json",
    "api/index.py",
    "bonus_platform/app.py",
    "bonus_platform/config.py",
    "bonus_platform/engine/labor/build_info.py",
    "bonus_platform/worker/__init__.py",
    "bonus_platform/worker/personal.py",
    "bonus_platform/static/index.html",
    "bonus_platform/static/styles.css",
    "bonus_platform/static/overseas-labor.html",
    "bonus_platform/static/overseas-labor.js",
    "bonus_platform/static/labor-operations.html",
    "bonus_platform/static/labor-operations.css",
    "bonus_platform/static/labor-operations.js",
    "bonus_platform/static/assets/bonus-logo-dark.png",
    "bonus_platform/static/assets/bonus-logo-header-blue.png",
    "bonus_platform/static/assets/workbench-logo-2026.png",
    "bonus_platform/static/assets/workbench-sigma-mark.png",
    "data/supplier_profiles/invoice.json",
    "data/supplier_profiles/onesource.json",
    "labor-worker-desktop/main.js",
    "labor-worker-desktop/preload.js",
    "labor-worker-desktop/package.json",
    "labor-worker-desktop/package-lock.json",
    "labor-worker-desktop/worker_entry.py",
    "labor-worker-desktop/pyinstaller-worker.spec",
    "labor-worker-desktop/lib/activation.js",
    "labor-worker-desktop/lib/status.js",
    "labor-worker-desktop/lib/worker-command.js",
    "labor-worker-desktop/lib/worker-pid.js",
    "labor-worker-desktop/renderer/app.js",
    "labor-worker-desktop/renderer/index.html",
    "labor-worker-desktop/renderer/styles.css",
    "labor-worker-desktop/scripts/ad-hoc-sign-mac.js",
    "labor-worker-desktop/scripts/build-worker.js",
    "labor-worker-desktop/assets/overseas-labor-worker.icns",
    "labor-worker-desktop/assets/overseas-labor-worker.ico",
    "labor-worker-desktop/assets/overseas-labor-worker.png",
    "labor-worker-desktop/worker-static-placeholder/.keep",
)

# Vercel's Python function bundle omits nested npm lockfiles. The standalone
# Worker job still validates this lockfile with `npm ci`; it is not a server
# runtime artifact and must not make an otherwise complete Lambda look stale.
VERCEL_RUNTIME_OMITTED_SENTINELS = frozenset(
    {
        "labor-worker-desktop/package-lock.json",
    }
)

LABOR_BUILD_ENV_KEYS = (
    "SIGMA_LABOR_BUILD_ID",
    "SIGMA_LABOR_SOURCE_REF",
    "SIGMA_LABOR_BUILD_TIME",
    "VERCEL",
    "VERCEL_GIT_COMMIT_SHA",
    "VERCEL_GIT_COMMIT_REF",
    "GITHUB_SHA",
    "GITHUB_REF_NAME",
)


class LaborBuildMonitor:
    """Capture the source snapshot used by a running labor API process."""

    def __init__(
        self,
        project_root: Path,
        *,
        patterns: Sequence[str] = DEFAULT_LABOR_BUILD_PATTERNS,
        required_files: Optional[Sequence[str]] = None,
        env: Optional[Mapping[str, str]] = None,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.patterns = tuple(patterns)
        source_env = os.environ if env is None else env
        selected_required_files = (
            _default_runtime_sentinels(source_env)
            if required_files is None
            else required_files
        )
        self.required_files = tuple(
            str(path).replace("\\", "/") for path in selected_required_files
        )
        self.process_started_at = _utc_now_iso()
        startup_files = _labor_source_files(self.project_root, patterns=self.patterns)
        self.startup_fingerprint = _fingerprint_files(self.project_root, startup_files)
        self.startup_file_count = len(startup_files)
        self.startup_missing_sentinels = _missing_sentinels(self.project_root, self.required_files)
        self.startup_env = _selected_build_env(source_env)

    def snapshot(
        self,
        *,
        env: Optional[Mapping[str, str]],
        module_version: str,
        api_contract_version: int,
        required_worker_version: str,
    ) -> dict:
        active_env = dict(self.startup_env if env is None else _selected_build_env(env))
        current_files = _labor_source_files(self.project_root, patterns=self.patterns)
        current_fingerprint = _fingerprint_files(self.project_root, current_files)
        missing_sentinels = _missing_sentinels(self.project_root, self.required_files)
        revision, revision_source = _labor_revision(active_env, self.startup_fingerprint)
        verified = bool(
            self.startup_file_count
            and current_files
            and not self.startup_missing_sentinels
            and not missing_sentinels
        )
        status = (
            "unverified"
            if not verified
            else "current"
            if current_fingerprint == self.startup_fingerprint
            else "restart_required"
        )
        return {
            "schemaVersion": 1,
            "moduleVersion": str(module_version),
            "apiContractVersion": int(api_contract_version),
            "buildId": revision,
            "revision": revision,
            "revisionSource": revision_source,
            "sourceRef": _safe_source_ref(
                _first_value(
                    active_env,
                    "SIGMA_LABOR_SOURCE_REF",
                    "VERCEL_GIT_COMMIT_REF",
                    "GITHUB_REF_NAME",
                    fallback="local-worktree",
                )
            ),
            "runtime": "vercel" if _truthy(active_env.get("VERCEL")) else "local",
            "builtAt": _safe_text(_first_value(active_env, "SIGMA_LABOR_BUILD_TIME", fallback=""), max_length=40),
            "processStartedAt": self.process_started_at,
            "startupFingerprint": self.startup_fingerprint,
            "currentFingerprint": current_fingerprint,
            "status": status,
            "fileCount": len(current_files),
            "missingSentinels": sorted(set(self.startup_missing_sentinels) | set(missing_sentinels)),
            "requiredWorkerVersion": str(required_worker_version),
        }


def calculate_labor_source_fingerprint(
    project_root: Path,
    *,
    patterns: Sequence[str] = DEFAULT_LABOR_BUILD_PATTERNS,
) -> str:
    root = Path(project_root).resolve()
    return _fingerprint_files(root, _labor_source_files(root, patterns=patterns))


def _labor_source_files(root: Path, *, patterns: Sequence[str]) -> set[Path]:
    return {
        candidate
        for pattern in patterns
        for candidate in root.glob(pattern)
        if candidate.is_file() and "__pycache__" not in candidate.parts
    }


def _fingerprint_files(root: Path, files: set[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(files, key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _missing_sentinels(root: Path, required_files: Sequence[str]) -> list[str]:
    return [relative for relative in required_files if not (root / relative).is_file()]


def _default_runtime_sentinels(env: Mapping[str, str]) -> tuple[str, ...]:
    if not _truthy(env.get("VERCEL")):
        return DEFAULT_LABOR_BUILD_SENTINELS
    return tuple(
        path
        for path in DEFAULT_LABOR_BUILD_SENTINELS
        if path not in VERCEL_RUNTIME_OMITTED_SENTINELS
    )


def _selected_build_env(env: Mapping[str, str]) -> dict[str, str]:
    return {key: str(env.get(key) or "") for key in LABOR_BUILD_ENV_KEYS if env.get(key) is not None}


def _labor_revision(env: Mapping[str, str], source_fingerprint: str) -> tuple[str, str]:
    explicit = _safe_build_id(env.get("SIGMA_LABOR_BUILD_ID"))
    if explicit:
        return explicit, "explicit"
    vercel_revision = _safe_build_id(env.get("VERCEL_GIT_COMMIT_SHA"))
    if vercel_revision:
        return vercel_revision, "vercel_git"
    github_revision = _safe_build_id(env.get("GITHUB_SHA"))
    if github_revision:
        return github_revision, "github"
    return f"local-{source_fingerprint[:12]}", "source_fingerprint"


def _first_value(env: Mapping[str, str], *names: str, fallback: str) -> str:
    for name in names:
        value = str(env.get(name) or "").strip()
        if value:
            return value
    return fallback


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_build_id(value: object) -> str:
    candidate = str(value or "").strip()
    if not candidate or len(candidate) > 64 or not re.fullmatch(r"[A-Za-z0-9._-]+", candidate):
        return ""
    return candidate


def _safe_source_ref(value: object) -> str:
    candidate = _safe_text(value, max_length=120)
    return candidate if re.fullmatch(r"[A-Za-z0-9._/@-]+", candidate) else "local-worktree"


def _safe_text(value: object, *, max_length: int) -> str:
    candidate = str(value or "").strip()
    if any(character in candidate for character in ("\r", "\n", "\x00")):
        return ""
    return candidate[:max_length]

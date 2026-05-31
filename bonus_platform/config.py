from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_NAME = "SigmaWorkbench"


def _load_local_env() -> None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_local_env()


def resolve_data_root() -> Path:
    configured = os.environ.get("SIGMA_WORKBENCH_HOME")
    if configured:
        return Path(configured).expanduser()
    return PROJECT_ROOT / "outputs"


def resolve_seed_root() -> Path:
    configured = os.environ.get("SIGMA_WORKBENCH_SEED_DIR")
    if configured:
        return Path(configured).expanduser()
    return PROJECT_ROOT / "outputs"


OUTPUT_DIR = resolve_data_root()
BUNDLED_OUTPUT_DIR = resolve_seed_root()
DEFAULT_RULE_WORKBOOK = OUTPUT_DIR / "招聘奖金核算_规则库.xlsx"
DEFAULT_IMPORT_TEMPLATE = OUTPUT_DIR / "招聘奖金核算_月度导入模板.xlsx"
EXPORT_DIR = OUTPUT_DIR / "platform_exports"
RUNS_DIR = OUTPUT_DIR / "runs"
LABOR_RUNS_DIR = OUTPUT_DIR / "labor_runs"
DATABASE_PATH = OUTPUT_DIR / "sigma_workbench.db"

MAX_PREVIEW_ROWS = 50


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value in (None, ""):
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value in (None, ""):
        return default
    try:
        return int(value)
    except ValueError:
        return default


AI_CONFIG: dict[str, Any] = {
    "enabled": _env_bool("AI_ENABLED", False),
    "provider": os.environ.get("AI_PROVIDER", ""),
    "api_key": os.environ.get("AI_API_KEY", "") or os.environ.get("MIMO_API_KEY", ""),
    "base_url": os.environ.get("AI_BASE_URL", ""),
    "model": os.environ.get("AI_MODEL", ""),
    "timeout_seconds": _env_int("AI_TIMEOUT_SECONDS", 90),
    "confidence_threshold": _env_float("AI_CONFIDENCE_THRESHOLD", 0.85),
    "amount_tolerance": _env_float("AI_AMOUNT_TOLERANCE", 0.05),
    "hours_tolerance": _env_float("LABOR_HOURS_TOLERANCE", 0.1),
    "max_pages_per_request": _env_int("AI_MAX_PAGES_PER_REQUEST", 5),
    "max_completion_tokens": _env_int("AI_MAX_COMPLETION_TOKENS", 8192),
    "render_scale": _env_float("AI_RENDER_SCALE", 1.5),
    "document_toolchain": os.environ.get("AI_DOCUMENT_TOOLCHAIN", "pypdfium2,mimo"),
    "ocr_command": os.environ.get("AI_OCR_COMMAND", ""),
    "supplier_profiles_path": os.environ.get("LABOR_SUPPLIER_PROFILES_PATH", ""),
    # 并行化配置
    "parallel_extraction_enabled": _env_bool("PARALLEL_EXTRACTION_ENABLED", True),
    "parallel_max_workers": _env_int("PARALLEL_MAX_WORKERS", 2),
    "parallel_image_render_workers": _env_int("PARALLEL_IMAGE_RENDER_WORKERS", 2),
}

if AI_CONFIG["provider"].lower() == "mimo":
    AI_CONFIG["base_url"] = AI_CONFIG["base_url"] or "https://api.xiaomimimo.com/v1"
    AI_CONFIG["model"] = AI_CONFIG["model"] or "mimo-v2.5"


def ensure_data_files() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for filename in ("招聘奖金核算_规则库.xlsx", "招聘奖金核算_月度导入模板.xlsx"):
        target = OUTPUT_DIR / filename
        source = BUNDLED_OUTPUT_DIR / filename
        if not target.exists() and source.exists() and source.resolve() != target.resolve():
            shutil.copy2(source, target)

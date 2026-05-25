from __future__ import annotations

import os
import shutil
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_NAME = "SigmaWorkbench"


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
DATABASE_PATH = OUTPUT_DIR / "sigma_workbench.db"

MAX_PREVIEW_ROWS = 50


def ensure_data_files() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for filename in ("招聘奖金核算_规则库.xlsx", "招聘奖金核算_月度导入模板.xlsx"):
        target = OUTPUT_DIR / filename
        source = BUNDLED_OUTPUT_DIR / filename
        if not target.exists() and source.exists() and source.resolve() != target.resolve():
            shutil.copy2(source, target)

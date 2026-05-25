from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "outputs"
DEFAULT_RULE_WORKBOOK = OUTPUT_DIR / "招聘奖金核算_规则库.xlsx"
DEFAULT_IMPORT_TEMPLATE = OUTPUT_DIR / "招聘奖金核算_月度导入模板.xlsx"
EXPORT_DIR = OUTPUT_DIR / "platform_exports"
RUNS_DIR = OUTPUT_DIR / "runs"

MAX_PREVIEW_ROWS = 50

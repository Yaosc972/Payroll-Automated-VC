from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bonus_platform.engine.recruitment_import_validation import run_validation


def main() -> None:
    parser = argparse.ArgumentParser(description="验证招聘奖金源文件自动整合结果")
    parser.add_argument("--month", type=int, required=True, help="核算月份，例如 202605")
    parser.add_argument("--previous-workbook", required=True, help="上月线下核算表或历史台账")
    parser.add_argument("--ehr-roster", required=True, help="EHR 花名册")
    parser.add_argument("--oehr-roster", required=True, help="OEHR 花名册")
    parser.add_argument("--domestic-offer", required=True, help="国内 Offer 流程表")
    parser.add_argument("--overseas-offer", required=True, help="海外 Offer 流程表")
    parser.add_argument("--target-template", required=True, help="人工整理完成的标准导入模板")
    parser.add_argument("--ehr-resignations", default="", help="EHR 离职审批/离职中员工表")
    parser.add_argument("--oehr-resignations", default="", help="OEHR 离职流程表")
    parser.add_argument("--special-approvals", default="", help="其他特殊事项审批流程（HR）导出数据")
    parser.add_argument("--output-dir", default="", help="报告输出目录")
    args = parser.parse_args()

    output_dir = Path(args.output_dir) if args.output_dir else ROOT / "outputs" / "recruitment_import_validation" / f"{args.month}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    result = run_validation(
        target_month=args.month,
        previous_workbook=Path(args.previous_workbook),
        ehr_roster=Path(args.ehr_roster),
        oehr_roster=Path(args.oehr_roster),
        domestic_offer=Path(args.domestic_offer),
        overseas_offer=Path(args.overseas_offer),
        target_template=Path(args.target_template),
        output_dir=output_dir,
        ehr_resignations=Path(args.ehr_resignations) if args.ehr_resignations else None,
        oehr_resignations=Path(args.oehr_resignations) if args.oehr_resignations else None,
        special_approvals=Path(args.special_approvals) if args.special_approvals else None,
    )
    print("验证完成")
    print(f"自动导入模板: {result['autoImportPath']}")
    print(f"字段差异报告: {result['diffReportPath']}")
    print(f"异常清单: {result['exceptionPath']}")
    print(f"摘要: {result['summary']}")


if __name__ == "__main__":
    main()

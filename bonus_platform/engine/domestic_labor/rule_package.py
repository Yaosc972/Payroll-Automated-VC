"""Published rule metadata for verified domestic labor payroll subjects."""

from copy import deepcopy
from typing import Any, Dict


_RULE_PACKAGE: Dict[str, Any] = {
    "package_id": "DL-PAYROLL",
    "name": "国内劳务薪酬核算规则包",
    "version": "1.0.0",
    "display_version": "DL-PAYROLL.v1.0.0",
    "status": "已发布",
    "released_at": "2026-07-15",
    "effective_from": "2026-05",
    "scope_note": "仅收录已使用真实线下数据完成核算验证的科目。",
    "categories": [
        {
            "id": "allowance",
            "name": "补贴类",
            "description": "按地区、岗位、出勤及住宿条件核算的补贴科目。",
            "subject_ids": ["canbu", "waisu_butie"],
        }
    ],
    "subjects": [
        {
            "id": "canbu",
            "name": "餐补",
            "english_name": "Meal Allowance",
            "category_id": "allowance",
            "version": "DL-CANBU.v1.0.0",
            "status": "已验证",
            "effective_from": "2026-05",
            "summary": "按工作地区、部门、岗位及考勤数据核算；平台内置标准，不读取上传餐补标准。",
            "data_sources": [
                "月考勤：工号、姓名、工作地区、部门、岗位、排班及请假字段",
                "日考勤：工作地区、部门、岗位、正班时数、刷卡加班、异常原因",
            ],
            "common_rules": [
                "工作地区优先取员工日考勤中出现次数最多的地区，缺失时回退月考勤。",
                "岗位和部门按平台已验证的享有名单判断；未命中已配置规则时金额为0。",
                "上传文件中的餐补标准字段不参与资格或金额判断。",
            ],
            "regions": [
                {
                    "name": "东莞",
                    "rule": "部门需命中寮步区或莞深操作，且岗位在享有名单内。",
                    "formula": "min(逐日餐补合计, 500元)",
                    "details": [
                        "单日有效时数=max(正班时数, 刷卡加班)。",
                        "有效时数大于8小时按19元；0至8小时按19/8逐小时折算。",
                        "异常原因为旷工的日期不发放；月度封顶500元。",
                    ],
                },
                {
                    "name": "嘉善 / 义乌",
                    "rule": "岗位在嘉善/义乌享有名单内，按月考勤字段折算。",
                    "formula": "300/排班天数×(实际在职工作日天数-事假时数/8-旷工天数-病假时数/8×0.4)",
                    "details": [
                        "月标准300元，结果限制在0至300元。",
                        "排班天数缺失或为0时金额为0并提示复核。",
                    ],
                },
                {
                    "name": "晋江",
                    "rule": "当前已验证口径不享有餐补。",
                    "formula": "0元",
                    "details": ["工作地区为晋江时直接返回0。"],
                },
            ],
            "verification": [
                "东莞2026年5月操作考勤真实数据回算",
                "嘉善/义乌2026年5月华东费用真实数据回算",
                "平台API、结果明细及导出回归测试",
            ],
            "change_log": [
                {
                    "version": "DL-CANBU.v1.0.0",
                    "released_at": "2026-07-15",
                    "changes": "首次发布：内置地区、部门和岗位资格；发布东莞逐日折算及嘉善/义乌月度折算。",
                }
            ],
        },
        {
            "id": "waisu_butie",
            "name": "外宿补贴",
            "english_name": "Housing Allowance",
            "category_id": "allowance",
            "version": "DL-WAISU.v1.0.0",
            "status": "已验证",
            "effective_from": "2026-05",
            "summary": "按地区岗位资格、当月在职区间、实际住宿区间及地区缺勤口径核算，平台标准150元/月。",
            "data_sources": [
                "月考勤：工号、姓名、考勤月份、工作地区、岗位、入职日期、最后工作日及请假字段",
                "日考勤：工作地区、岗位及上下班打卡",
                "住宿名单：工号、入住时间、退宿时间",
            ],
            "common_rules": [
                "平台内置标准为150元/月，上传文件中的外宿补贴标准字段不参与资格或金额判断。",
                "当月在职天数按入职日期和最后工作日截取；全月无打卡且非当月入离职时金额为0。",
                "入住当天计为住宿；退宿当天开始享有外宿补贴，住宿扣除截至退宿前一日。",
                "外宿补贴天数=max(在职天数-住宿扣除天数, 0)。",
            ],
            "regions": [
                {
                    "name": "东莞",
                    "rule": "按东莞享有/不享有岗位名单判断，陈西莎、田盈按已确认特殊名单享有。",
                    "formula": "150/月自然日天数×有效补贴天数",
                    "details": [
                        "缺勤包含事假、排休请假、病假、旷工及入离职缺勤；不计休年假等有薪假。",
                        "全月在职缺勤达到56小时且仍在宿时为0；无住宿扣除时按缺勤小时折算。",
                    ],
                },
                {
                    "name": "嘉善 / 义乌",
                    "rule": "按嘉善/义乌享有岗位名单判断，并结合住宿和缺勤核算。",
                    "formula": "150/月自然日天数×有效补贴天数",
                    "details": [
                        "缺勤包含休年假、婚假、陪产假、工伤假等有薪假，以及事假、调休、旷工；病假按60%计入。",
                        "当月入离职人员同样执行缺勤折算；缺勤达到56小时且仍在宿时为0。",
                    ],
                },
                {
                    "name": "晋江",
                    "rule": "操作员、门禁员、操作组长、HRBP专员按月考勤扣减公式核算。",
                    "formula": "150-入离职扣减-请假扣减",
                    "details": [
                        "入离职扣减按未在职自然日折算。",
                        "请假旷工合计超过7天时，按天数折算请假扣减。",
                    ],
                },
            ],
            "verification": [
                "东莞2026年5月真实数据规则基线验证及退宿日边界确认",
                "嘉善/义乌2026年5月真实数据端到端及导出验证",
                "晋江2026年5月75人逐行一致验证，合计10,151.59元",
            ],
            "change_log": [
                {
                    "version": "DL-WAISU.v1.0.0",
                    "released_at": "2026-07-15",
                    "changes": "首次发布：统一150元平台标准，发布三地区岗位、在职、住宿、缺勤和退宿日边界规则。",
                }
            ],
        },
    ],
    "version_history": [
        {
            "version": "1.0.0",
            "display_version": "DL-PAYROLL.v1.0.0",
            "status": "当前版本",
            "released_at": "2026-07-15",
            "effective_from": "2026-05",
            "subject_ids": ["canbu", "waisu_butie"],
            "summary": "首次发布餐补与外宿补贴两个已验证科目。",
        }
    ],
}


_RULE_PACKAGE_VERSIONS = {
    _RULE_PACKAGE["version"]: _RULE_PACKAGE,
}


def get_rule_package(version: str = "") -> Dict[str, Any]:
    """Return an immutable published version, defaulting to the current package."""
    selected_version = version or _RULE_PACKAGE["version"]
    if selected_version not in _RULE_PACKAGE_VERSIONS:
        raise KeyError(selected_version)
    return deepcopy(_RULE_PACKAGE_VERSIONS[selected_version])

"""Published rule metadata for verified and validating domestic labor payroll subjects."""

from copy import deepcopy
from typing import Any, Dict


_RULE_PACKAGE_V1_0_0: Dict[str, Any] = {
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


_RULE_PACKAGE = deepcopy(_RULE_PACKAGE_V1_0_0)
_RULE_PACKAGE.update({
    "version": "1.1.0",
    "display_version": "DL-PAYROLL.v1.1.0",
    "effective_from": "2026-02",
})
_RULE_PACKAGE["categories"].append({
    "id": "bonus",
    "name": "奖金类",
    "description": "按地区、岗位、工龄及考勤条件核算的奖金科目。",
    "subject_ids": ["gonglingjiang"],
})
_RULE_PACKAGE["subjects"].append({
    "id": "gonglingjiang",
    "name": "工龄奖",
    "english_name": "Seniority Bonus",
    "category_id": "bonus",
    "version": "DL-GONGLING.v1.0.0",
    "status": "已验证",
    "effective_from": "2026-02",
    "summary": "按工作地区、部门岗位、月初司龄及缺勤口径核算；莞深区揽收人员需提供当月HRBP发放名单。",
    "data_sources": [
        "月考勤：工号、姓名、考勤月份、工作地区、部门、岗位、入职日期及排班出勤字段",
        "缺勤字段：事假时数、病假时数、旷工时数/天数、排休请假时数/天数",
        "业务参数：莞深区揽收人员当月HRBP发放工号名单",
    ],
    "common_rules": [
        "以考勤月份首日计算完整司龄；入职日不是当月1日时，对应周年当月尚未满整年，次月开始增加一年。",
        "基础应发=min(每年标准×完整司龄, 地区及部门上限)。",
        "事假、病假、旷工和排休请假合计达到56小时后按排班天数折算；旷工、排休请假优先读取小时字段，缺失时按天数×8。",
        "入离职缺勤按排班天数与实际在职工作日天数之差另行扣减；结果按Excel ROUND保留2位小数。",
        "正班出勤天数为0且存在事假时按线下工资表结果归零；其他场景不额外设置最低金额。",
    ],
    "regions": [
        {
            "name": "东莞",
            "rule": "中国操作部按已验证一线岗位发放；第四纵队揽收人员须命中当月HRBP名单；头程运营部按FBU标准发放。",
            "formula": "操作/揽收150元×司龄，封顶600元；FBU100元×司龄，封顶500元",
            "details": [
                "操作享有岗位：安检员、操作文员、操作员、叉车司机、查验员、监察员。",
                "保洁、组长、主管及未命中岗位不发放。",
                "揽收人员不在当月HRBP名单时按0处理；未提供名单时进入异常复核。",
            ],
        },
        {
            "name": "嘉善 / 义乌",
            "rule": "按已验证实际工资表，操作条线不发放工龄奖。",
            "formula": "0元",
            "details": ["工作地区为嘉善或义乌时直接返回0。"],
        },
        {
            "name": "晋江",
            "rule": "操作员、门禁员享有，其他操作岗位不发放。",
            "formula": "50元×司龄，封顶150元，再按缺勤和入离职折算",
            "details": [
                "工龄计算、56小时缺勤门槛和入离职扣减与通用规则一致。",
                "最终金额按Excel ROUND保留2位小数。",
            ],
        },
    ],
    "verification": [
        "2026年2月华西华东东南实际工资表287人逐行一致",
        "2026年3月华西华东东南实际工资表338人逐行一致",
        "2026年2月莞深广珠FBU实际工资表711人逐行一致",
        "2026年3月莞深广珠FBU实际工资表756人中755人一致，剩余1人为待确认的重新入职边界",
        "2026年5月东莞操作考勤798人按线下公式重算逐行一致",
    ],
    "pending_confirmations": [
        "待薪酬确认：员工自离后重新入职是否重置工龄，以及平台应从哪个字段识别。样例OWHN2187戚甲鹏，2026年3月线下工龄奖为0。",
    ],
    "change_log": [
        {
            "version": "DL-GONGLING.v1.0.0",
            "released_at": "2026-07-15",
            "changes": "首次发布：按实际工资表更新地区岗位、小时缺勤字段、56小时门槛、入离职扣减和Excel舍入口径。",
        }
    ],
})
_RULE_PACKAGE["version_history"] = [
    {
        "version": "1.1.0",
        "display_version": "DL-PAYROLL.v1.1.0",
        "status": "当前版本",
        "released_at": "2026-07-15",
        "effective_from": "2026-02",
        "subject_ids": ["canbu", "waisu_butie", "gonglingjiang"],
        "summary": "新增经跨月实际工资表验证的工龄奖科目，保留重新入职工龄边界待确认项。",
    },
    {
        **_RULE_PACKAGE_V1_0_0["version_history"][0],
        "status": "历史版本",
    },
]


_RULE_PACKAGE_V1_1_0 = deepcopy(_RULE_PACKAGE)
_RULE_PACKAGE = deepcopy(_RULE_PACKAGE_V1_1_0)
_RULE_PACKAGE.update({
    "version": "1.1.1",
    "display_version": "DL-PAYROLL.v1.1.1",
    "released_at": "2026-07-20",
    "effective_from": "2026-06",
})
_waisu_butie = next(subject for subject in _RULE_PACKAGE["subjects"] if subject["id"] == "waisu_butie")
_waisu_butie["version"] = "DL-WAISU.v1.0.1"
_waisu_butie["common_rules"].append(
    "最后工作日在核算月月末或之后时，该月仍按全月在职判断并执行对应缺勤折算。"
)
_waisu_butie["common_rules"].append(
    "所有地区正班出勤不超过1天且旷工天数达到1天时，外宿补贴为0；旷工不足1天不归零。"
)
for _region in _waisu_butie["regions"]:
    if _region["name"] == "嘉善 / 义乌":
        _region["rule"] = "按嘉善/义乌享有岗位名单判断，设备维养专员等已确认岗位享有，并结合住宿和缺勤核算。"
    elif _region["name"] == "晋江":
        _region["rule"] = "操作员、门禁员、操作组长、HRBP专员、安全员按月考勤扣减公式核算。"
_waisu_butie["change_log"].insert(0, {
    "version": "DL-WAISU.v1.0.1",
    "released_at": "2026-07-20",
    "changes": "修复跨月离职边界，补充享有岗位，并增加所有地区正班出勤不超过1天且旷工至少1天的归零规则。",
})
_RULE_PACKAGE["version_history"] = [
    {
        "version": "1.1.1",
        "display_version": "DL-PAYROLL.v1.1.1",
        "status": "当前版本",
        "released_at": "2026-07-20",
        "effective_from": "2026-06",
        "subject_ids": ["canbu", "waisu_butie", "gonglingjiang"],
        "summary": "修复外宿补贴跨月离职边界，补充享有岗位，并增加正班出勤不超过1天且旷工至少1天的归零规则。",
    },
    {
        **_RULE_PACKAGE_V1_1_0["version_history"][0],
        "status": "历史版本",
    },
    *_RULE_PACKAGE_V1_1_0["version_history"][1:],
]


_RULE_PACKAGE_V1_1_1 = deepcopy(_RULE_PACKAGE)
_RULE_PACKAGE = deepcopy(_RULE_PACKAGE_V1_1_1)
_RULE_PACKAGE.update({
    "version": "1.1.2",
    "display_version": "DL-PAYROLL.v1.1.2",
    "released_at": "2026-07-21",
    "effective_from": "2026-07",
})
_gonglingjiang = next(subject for subject in _RULE_PACKAGE["subjects"] if subject["id"] == "gonglingjiang")
_gonglingjiang.update({
    "version": "DL-GONGLING.v1.0.1",
    "effective_from": "2026-07",
    "summary": "仅核算操作线人员，按工作地区、操作岗位、月初司龄及缺勤口径计算。",
    "data_sources": [
        "月考勤：工号、姓名、考勤月份、工作地区、部门、岗位、入职日期及排班出勤字段",
        "缺勤字段：事假时数、病假时数、旷工时数/天数、排休请假时数/天数",
    ],
    "regions": [
        {
            "name": "东莞",
            "rule": "中国操作部按已验证一线操作岗位发放，非操作线不纳入当前平台工龄奖核算。",
            "formula": "150元×司龄，封顶600元，再按缺勤和入离职折算",
            "details": [
                "操作享有岗位：安检员、操作文员、操作员、叉车司机、查验员、监察员。",
                "保洁、组长、主管及未命中岗位不发放。",
            ],
        },
        {
            "name": "嘉善 / 义乌",
            "rule": "按已验证实际工资表，操作条线不发放工龄奖。",
            "formula": "0元",
            "details": ["工作地区为嘉善或义乌时直接返回0。"],
        },
        {
            "name": "晋江",
            "rule": "操作员、门禁员享有，其他操作岗位不发放。",
            "formula": "50元×司龄，封顶150元，再按缺勤和入离职折算",
            "details": [
                "工龄计算、56小时缺勤门槛和入离职扣减与通用规则一致。",
                "最终金额按Excel ROUND保留2位小数。",
            ],
        },
    ],
    "verification": [
        "2026年5月东莞操作考勤798人按线下公式重算逐行一致",
    ],
})
_gonglingjiang["common_rules"].insert(0, "当前平台仅开放东莞、嘉善/义乌、晋江操作线工龄奖；历史兼容口径不参与资格或金额判断。")
_gonglingjiang["change_log"].insert(0, {
    "version": "DL-GONGLING.v1.0.1",
    "released_at": "2026-07-21",
    "changes": "仅保留明确地区操作线规则，非操作线及历史兼容规则转为本地暂缓归档。",
})
_RULE_PACKAGE["version_history"] = [
    {
        "version": "1.1.2",
        "display_version": "DL-PAYROLL.v1.1.2",
        "status": "当前版本",
        "released_at": "2026-07-21",
        "effective_from": "2026-07",
        "subject_ids": ["canbu", "waisu_butie", "gonglingjiang"],
        "summary": "工龄奖仅保留明确地区操作线规则，其他历史兼容规则转为本地暂缓归档。",
    },
    {
        **_RULE_PACKAGE_V1_1_1["version_history"][0],
        "status": "历史版本",
    },
    *_RULE_PACKAGE_V1_1_1["version_history"][1:],
]

_RULE_PACKAGE_V1_1_2 = deepcopy(_RULE_PACKAGE)
_RULE_PACKAGE = deepcopy(_RULE_PACKAGE_V1_1_2)
_RULE_PACKAGE.update({
    "version": "1.1.3",
    "display_version": "DL-PAYROLL.v1.1.3",
    "released_at": "2026-07-22",
    "effective_from": "2026-02",
})
_gonglingjiang = next(subject for subject in _RULE_PACKAGE["subjects"] if subject["id"] == "gonglingjiang")
_gonglingjiang.update({
    "version": "DL-GONGLING.v1.0.2",
    "effective_from": "2026-02",
    "summary": "核算操作线、东莞第四纵队揽收、东莞头程运营部/FBU及华西/华东/东南兼容区域人员，按月初司龄和缺勤口径计算。",
    "data_sources": [
        "月考勤：工号、姓名、考勤月份、工作地区、部门、岗位、入职日期及排班出勤字段",
        "缺勤字段：事假时数、病假时数、旷工时数/天数、排休请假时数/天数",
        "业务参数：东莞第四纵队揽收人员当月HRBP发放工号名单",
    ],
    "regions": [
        {
            "name": "东莞操作",
            "rule": "中国操作部按已验证一线操作岗位发放。",
            "formula": "150元×司龄，封顶600元，再按缺勤和入离职折算",
            "details": [
                "操作享有岗位：安检员、操作文员、操作员、叉车司机、查验员、监察员。",
                "保洁、组长、主管及未命中岗位不发放。",
            ],
        },
        {
            "name": "东莞第四纵队揽收",
            "rule": "二级部门为第四纵队，工号命中当月HRBP发放名单，且岗位不包含组长。",
            "formula": "150元×司龄，封顶600元，再按缺勤和入离职折算",
            "details": [
                "未提供名单时进入异常复核。",
                "已提供名单但工号未命中，或岗位包含组长时按0处理。",
            ],
        },
        {
            "name": "东莞头程运营部/FBU",
            "rule": "工作地区为东莞且二级部门为头程运营部。",
            "formula": "100元×司龄，封顶500元，再按缺勤和入离职折算",
            "details": ["无需HRBP发放名单，命中部门后按FBU标准计算。"],
        },
        {
            "name": "嘉善 / 义乌",
            "rule": "按已验证实际工资表，操作条线不发放工龄奖。",
            "formula": "0元",
            "details": ["工作地区为嘉善或义乌时直接返回0。"],
        },
        {
            "name": "晋江",
            "rule": "操作员、门禁员享有，其他操作岗位不发放。",
            "formula": "50元×司龄，封顶150元，再按缺勤和入离职折算",
            "details": [
                "工龄计算、56小时缺勤门槛和入离职扣减与通用规则一致。",
                "最终金额按Excel ROUND保留2位小数。",
            ],
        },
        {
            "name": "华西 / 华东 / 东南兼容区域",
            "rule": "按华东枢纽、华东揽收组、东南枢纽、华西区操作部、闽赣揽收组、华东B2B枢纽的部门及岗位名单判断。",
            "formula": "50元×司龄，封顶150元，再按缺勤和入离职折算",
            "details": [
                "操作享有岗位：操作员、内勤专员、中转员、门禁员、安检员、操作文员。",
                "揽收享有岗位：揽收操作员、内勤专员。",
                "组长、主管、经理及HRBP专员等非一线岗位不发放。",
            ],
        },
    ],
    "verification": [
        "2026年2月莞深广珠FBU实际工资表711人逐行一致",
        "2026年3月莞深广珠FBU实际工资表756人中755人一致，剩余1人为待确认的重新入职边界",
        "2026年5月东莞操作考勤798人按线下公式重算逐行一致",
        "2026年2月华西华东东南实际工资表287人逐行一致",
        "2026年3月华西华东东南实际工资表338人逐行一致",
    ],
})
_gonglingjiang["common_rules"][0] = "当前平台开放操作线、东莞第四纵队揽收、东莞头程运营部/FBU及华西/华东/东南兼容区域工龄奖。"
_gonglingjiang["change_log"].insert(0, {
    "version": "DL-GONGLING.v1.0.2",
    "released_at": "2026-07-22",
    "changes": "恢复东莞第四纵队揽收、东莞头程运营部/FBU及华西/华东/东南兼容区域口径。",
})
_RULE_PACKAGE["version_history"] = [
    {
        "version": "1.1.3",
        "display_version": "DL-PAYROLL.v1.1.3",
        "status": "当前版本",
        "released_at": "2026-07-22",
        "effective_from": "2026-02",
        "subject_ids": ["canbu", "waisu_butie", "gonglingjiang"],
        "summary": "恢复东莞第四纵队揽收、头程运营部/FBU及华西/华东/东南兼容区域工龄奖。",
    },
    {
        **_RULE_PACKAGE_V1_1_2["version_history"][0],
        "status": "历史版本",
    },
    *_RULE_PACKAGE_V1_1_2["version_history"][1:],
]


_RULE_PACKAGE_V1_1_3 = deepcopy(_RULE_PACKAGE)
_RULE_PACKAGE = deepcopy(_RULE_PACKAGE_V1_1_3)
_RULE_PACKAGE.update({
    "version": "1.1.4",
    "display_version": "DL-PAYROLL.v1.1.4",
    "released_at": "2026-07-22",
    "effective_from": "2026-02",
})
_gonglingjiang = next(subject for subject in _RULE_PACKAGE["subjects"] if subject["id"] == "gonglingjiang")
_gonglingjiang["version"] = "DL-GONGLING.v1.0.3"
_gonglingjiang["summary"] = "按地区、部门岗位、月初司龄和缺勤口径核算；仅识别到东莞第四纵队时要求维护含工号、姓名的揽收线工龄奖名单。"
_gonglingjiang["data_sources"] = [
    item.replace("东莞第四纵队揽收人员当月HRBP发放工号名单", "东莞第四纵队揽收线工龄奖名单（工号、姓名）")
    for item in _gonglingjiang["data_sources"]
]
collection_region = next(region for region in _gonglingjiang["regions"] if region["name"] == "东莞第四纵队揽收")
collection_region["rule"] = "仅当月考勤识别到东莞第四纵队时要求维护揽收线工龄奖名单；工号命中名单且岗位不包含组长。"
collection_region["details"] = [
    "名单同时保存工号和姓名，工号参与计算、姓名用于人工复核。",
    "未识别到东莞第四纵队时无需维护名单；已识别但未维护完整名单时阻止提交。",
    "工号未命中名单或岗位包含组长时按0处理。",
]
dongguan_operation = next(region for region in _gonglingjiang["regions"] if region["name"] == "东莞操作")
dongguan_operation["details"] = [
    "操作享有岗位：安检员、操作文员、操作员、叉车司机、揽收充电司机、查验员、监察员、理货员。",
    "岗位资格不按职级判断；保洁、组长、主管及未命中岗位不发放。",
]
_gonglingjiang["verification"].insert(0, "2026年6月线下工龄奖复核确认东莞理货员享有，补齐后原8名理货员差异归零。")
_gonglingjiang["pending_confirmations"].append(
    "待薪酬确认：线下规则图列明东莞文员享有，但OWHN12121张春燕2026年6月已满1年且无折算缺勤，线下工龄奖仍为0；确认前平台暂不开放文员。"
)
_gonglingjiang["change_log"].insert(0, {
    "version": "DL-GONGLING.v1.0.3",
    "released_at": "2026-07-22",
    "changes": "补齐东莞操作享有岗位；揽收线工龄奖名单增加姓名，并改为仅识别到东莞第四纵队时要求维护。",
})
_RULE_PACKAGE["version_history"] = [
    {
        "version": "1.1.4",
        "display_version": "DL-PAYROLL.v1.1.4",
        "status": "当前版本",
        "released_at": "2026-07-22",
        "effective_from": "2026-02",
        "subject_ids": ["canbu", "waisu_butie", "gonglingjiang"],
        "summary": "补齐东莞操作岗位，并完善按部门触发、包含工号姓名的揽收线工龄奖名单管理。",
    },
    {
        **_RULE_PACKAGE_V1_1_3["version_history"][0],
        "status": "历史版本",
    },
    *_RULE_PACKAGE_V1_1_3["version_history"][1:],
]


_RULE_PACKAGE_V1_1_4 = deepcopy(_RULE_PACKAGE)
_RULE_PACKAGE = deepcopy(_RULE_PACKAGE_V1_1_4)
_RULE_PACKAGE.update({
    "version": "1.1.5",
    "display_version": "DL-PAYROLL.v1.1.5",
    "released_at": "2026-07-29",
    "effective_from": "2026-07",
})
_gonglingjiang = next(subject for subject in _RULE_PACKAGE["subjects"] if subject["id"] == "gonglingjiang")
_gonglingjiang["version"] = "DL-GONGLING.v1.0.4"
_gonglingjiang["summary"] = "按地区、部门岗位、月初司龄和缺勤口径核算；第四纵队和头程运营部按部门识别，不限制工作地区。"
_gonglingjiang["data_sources"] = [
    item.replace("东莞第四纵队揽收线工龄奖名单", "第四纵队揽收线工龄奖名单")
    for item in _gonglingjiang["data_sources"]
]
_gonglingjiang["common_rules"][0] = "当前平台开放操作线、第四纵队揽收、头程运营部/FBU及华西/华东/东南兼容区域工龄奖。"
collection_region = next(region for region in _gonglingjiang["regions"] if region["name"] == "东莞第四纵队揽收")
collection_region["name"] = "第四纵队揽收"
collection_region["rule"] = "二级部门为第四纵队时要求维护揽收线工龄奖名单，不限制工作地区；工号命中名单且岗位不包含组长。"
collection_region["details"] = [
    "名单同时保存工号和姓名，工号参与计算、姓名用于人工复核。",
    "未识别到第四纵队时无需维护名单；已识别但未维护完整名单时阻止提交。",
    "工号未命中名单或岗位包含组长时按0处理。",
]
fbu_region = next(region for region in _gonglingjiang["regions"] if region["name"] == "东莞头程运营部/FBU")
fbu_region["name"] = "头程运营部/FBU"
fbu_region["rule"] = "二级部门为头程运营部时按FBU标准计算，不限制工作地区。"
_gonglingjiang["verification"].insert(
    0,
    "2026年7月生产复核确认第四纵队深圳/惠州人员及头程运营部宁波/广州人员应按对应部门标准计算。",
)
_gonglingjiang["change_log"].insert(0, {
    "version": "DL-GONGLING.v1.0.4",
    "released_at": "2026-07-29",
    "changes": "移除第四纵队和头程运营部的工作地区限制；普通操作线地区规则保持不变。",
})
_RULE_PACKAGE["version_history"] = [
    {
        "version": "1.1.5",
        "display_version": "DL-PAYROLL.v1.1.5",
        "status": "当前版本",
        "released_at": "2026-07-29",
        "effective_from": "2026-07",
        "subject_ids": ["canbu", "waisu_butie", "gonglingjiang"],
        "summary": "第四纵队和头程运营部改为按部门识别，不再限制工作地区。",
    },
    {
        **_RULE_PACKAGE_V1_1_4["version_history"][0],
        "status": "历史版本",
    },
    *_RULE_PACKAGE_V1_1_4["version_history"][1:],
]


_RULE_PACKAGE_V1_1_5 = deepcopy(_RULE_PACKAGE)
_RULE_PACKAGE = deepcopy(_RULE_PACKAGE_V1_1_5)
_RULE_PACKAGE.update({
    "version": "1.1.6",
    "display_version": "DL-PAYROLL.v1.1.6",
    "released_at": "2026-07-30",
    "effective_from": "2026-02",
})
_gonglingjiang = next(subject for subject in _RULE_PACKAGE["subjects"] if subject["id"] == "gonglingjiang")
_gonglingjiang["version"] = "DL-GONGLING.v1.0.5"
_gonglingjiang["summary"] = "按地区、二级部门、岗位、月初司龄和缺勤口径核算；华东/华西四个指定二级部门直接返回0。"
_gonglingjiang["common_rules"][0] = (
    "当前平台开放操作线、第四纵队揽收、头程运营部/FBU及东南/闽赣兼容区域工龄奖；"
    "华东枢纽、华东揽收组、华东B2B枢纽、华西区操作部不发放。"
)
wes_region = next(region for region in _gonglingjiang["regions"] if region["name"] == "华西 / 华东 / 东南兼容区域")
wes_region["name"] = "东南 / 闽赣兼容区域"
wes_region["rule"] = "仅东南枢纽、闽赣揽收组按部门及岗位名单判断。"
wes_region["details"] = [
    "东南枢纽享有岗位：操作员、内勤专员、中转员、门禁员、安检员、操作文员。",
    "闽赣揽收组享有岗位：揽收操作员、内勤专员。",
    "组长、主管、经理及HRBP专员等非一线岗位不发放。",
]
_gonglingjiang["regions"].append({
    "name": "华东 / 华西不发放部门",
    "rule": "二级部门名称为华东枢纽、华东揽收组、华东B2B枢纽或华西区操作部时直接返回0。",
    "formula": "0元",
    "details": [
        "不再根据工作地区、岗位或司龄进入工龄奖金额计算。",
        "2026年2月、3月实际工资表中上述部门工龄奖均为0。",
    ],
})
_gonglingjiang["verification"].insert(
    0,
    "2026年2月系统薪资复核：华东枢纽229人、华东揽收组67人、华西区操作部55人工龄奖均为0。",
)
_gonglingjiang["verification"].insert(
    1,
    "2026年3月系统薪资复核：华东枢纽270人、华东揽收组72人、华东B2B枢纽8人、华西区操作部56人工龄奖均为0。",
)
_gonglingjiang["change_log"].insert(0, {
    "version": "DL-GONGLING.v1.0.5",
    "released_at": "2026-07-30",
    "changes": "华东枢纽、华东揽收组、华东B2B枢纽、华西区操作部改为按二级部门直接返回0；东南枢纽、闽赣揽收组保留原兼容口径。",
})
_RULE_PACKAGE["version_history"] = [
    {
        "version": "1.1.6",
        "display_version": "DL-PAYROLL.v1.1.6",
        "status": "当前版本",
        "released_at": "2026-07-30",
        "effective_from": "2026-02",
        "subject_ids": ["canbu", "waisu_butie", "gonglingjiang"],
        "summary": "按历史工资表纠正华东/华西工龄奖部门范围，保留东南/闽赣规则。",
    },
    {
        **_RULE_PACKAGE_V1_1_5["version_history"][0],
        "status": "历史版本",
    },
    *_RULE_PACKAGE_V1_1_5["version_history"][1:],
]


_RULE_PACKAGE_V1_1_6 = deepcopy(_RULE_PACKAGE)
_RULE_PACKAGE.update({
    "version": "1.1.7",
    "display_version": "DL-PAYROLL.v1.1.7",
    "released_at": "2026-08-04",
    "effective_from": "2026-02",
})
_gonglingjiang = next(subject for subject in _RULE_PACKAGE["subjects"] if subject["id"] == "gonglingjiang")
_gonglingjiang["version"] = "DL-GONGLING.v1.0.6"
_gonglingjiang["summary"] = "按地区、二级部门、岗位、月初司龄和缺勤口径核算；头程运营部/FBU使用独立缺勤折算公式。"
_gonglingjiang["common_rules"][3] = (
    "除FBU外，事假、病假、旷工和排休请假合计达到56小时后按排班天数折算；"
    "旷工、排休请假优先读取小时字段，缺失时按天数×8。"
)
_gonglingjiang["common_rules"][4] = (
    "FBU不设56小时门槛，入离职缺勤、事假、病假和旷工合并折算一次且不包含排休请假；"
    "其他范围的入离职缺勤按通用规则另行扣减。"
)
_gonglingjiang["common_rules"][5] = (
    "FBU不使用正班出勤为0的通用归零特例，始终按FBU独立公式计算；"
    "其他范围正班出勤天数为0且存在事假时按线下工资表结果归零。"
)
fbu_region = next(region for region in _gonglingjiang["regions"] if region["name"] == "头程运营部/FBU")
fbu_region["formula"] = (
    "工龄奖标准/排班天数×（排班天数-（入离职缺勤时数+事假时数+病假时数+旷工天数×8）/8）"
)
fbu_region["details"] = [
    "工龄奖标准为100元×完整司龄，封顶500元。",
    "FBU不设56小时门槛，发生公式内缺勤即按小时折算。",
    "FBU折算不包含排休请假，入离职缺勤与其他缺勤合并计算一次。",
    "最终结果按Excel ROUND保留2位小数。",
]
_gonglingjiang["verification"] = [
    item
    for item in _gonglingjiang["verification"]
    if "莞深广珠FBU实际工资表" not in item
]
_gonglingjiang["verification"].insert(
    0,
    "2026年2月头程运营部/FBU工龄奖计算表逐行一致；系统薪资12人中11人一致，雷一鸣计算表55元、系统薪资100元。",
)
_gonglingjiang["verification"].insert(
    1,
    "2026年3月头程运营部/FBU系统薪资12人逐行一致。",
)
_gonglingjiang["change_log"].insert(0, {
    "version": "DL-GONGLING.v1.0.6",
    "released_at": "2026-08-04",
    "changes": "FBU改用无56小时门槛的独立公式，不计排休请假，并将入离职缺勤与事假、病假、旷工合并折算一次。",
})
_RULE_PACKAGE["version_history"] = [
    {
        "version": "1.1.7",
        "display_version": "DL-PAYROLL.v1.1.7",
        "status": "当前版本",
        "released_at": "2026-08-04",
        "effective_from": "2026-02",
        "subject_ids": ["canbu", "waisu_butie", "gonglingjiang"],
        "summary": "FBU工龄奖改用独立缺勤折算公式，移除56小时门槛和排休请假。",
    },
    {
        **_RULE_PACKAGE_V1_1_6["version_history"][0],
        "status": "历史版本",
    },
    *_RULE_PACKAGE_V1_1_6["version_history"][1:],
]


_RULE_PACKAGE_V1_1_7 = deepcopy(_RULE_PACKAGE)
_RULE_PACKAGE = deepcopy(_RULE_PACKAGE_V1_1_7)
_RULE_PACKAGE.update({
    "version": "1.1.8",
    "display_version": "DL-PAYROLL.v1.1.8",
    "released_at": "2026-08-06",
    "effective_from": "2026-02",
})
_bonus_category = next(category for category in _RULE_PACKAGE["categories"] if category["id"] == "bonus")
_bonus_category["subject_ids"].insert(0, "quanqinjiang")
_RULE_PACKAGE["subjects"].append({
    "id": "quanqinjiang",
    "name": "全勤奖",
    "english_name": "Attendance Bonus",
    "category_id": "bonus",
    "version": "DL-QUANQIN.v1.0.0",
    "status": "已验证",
    "effective_from": "2026-02",
    "summary": "全区域固定标准100元，按入离职、缺勤、迟到早退和签卡条件判断是否发放。",
    "data_sources": [
        "月考勤：工号、姓名、考勤月份、入职日期、最后工作日及全勤判断字段",
        "日考勤：出勤日期、工作状态，用于判断月初至入职日前是否存在工作日",
    ],
    "common_rules": [
        "满足全部条件时发放100元，否则为0元。",
        "旷工天数、工伤假天数、事假时数、病假时数、入离职缺勤时数或迟到早退30分钟内扣款任一大于0时不发放。",
        "正班迟到次数与早退次数合计不超过3次；签卡次数不超过3次。",
        "休年假和排休请假不单独影响全勤奖。",
        "月初至入职日前存在工作日时不发放；有日考勤时按工作状态判断，缺失时按周一至周五判断。",
        "最后工作日为空或不早于月末时可发放；最后工作日早于月末时不发放。",
        "OWHN9535、OWHN9353、OWHX0190为长期特殊排除名单，固定不发放。",
    ],
    "regions": [
        {
            "name": "全区域",
            "rule": "各地区使用相同的固定金额和全勤判断条件。",
            "formula": "满足全部发放条件 ? 100元 : 0元",
            "details": [
                "不按地区、部门或岗位设置不同金额。",
                "特殊排除名单属于长期规则，不作为待处理异常。",
            ],
        }
    ],
    "verification": [
        "2026年2月莞深广珠FBU月报869人逐行一致。",
        "2026年3月莞深广珠FBU月报1,004人逐行一致。",
        "2026年2月华西华东东南月报439人逐行一致。",
        "2026年3月华西华东东南月报495人逐行一致。",
        "四份真实月报合计2,807人，平台金额与线下结果差异0人。",
    ],
    "pending_confirmations": [],
    "change_log": [
        {
            "version": "DL-QUANQIN.v1.0.0",
            "released_at": "2026-08-06",
            "changes": "首次发布：固定100元标准、缺勤与异常考勤门槛、入离职边界及长期特殊排除名单。",
        }
    ],
})
_RULE_PACKAGE["version_history"] = [
    {
        "version": "1.1.8",
        "display_version": "DL-PAYROLL.v1.1.8",
        "status": "当前版本",
        "released_at": "2026-08-06",
        "effective_from": "2026-02",
        "subject_ids": ["quanqinjiang", "canbu", "waisu_butie", "gonglingjiang"],
        "summary": "新增经四份真实月报2,807人逐行验证的全勤奖科目。",
    },
    {
        **_RULE_PACKAGE_V1_1_7["version_history"][0],
        "status": "历史版本",
    },
    *_RULE_PACKAGE_V1_1_7["version_history"][1:],
]


_RULE_PACKAGE_V1_1_8 = deepcopy(_RULE_PACKAGE)
_RULE_PACKAGE = deepcopy(_RULE_PACKAGE_V1_1_8)
_RULE_PACKAGE.update({
    "version": "1.1.9",
    "display_version": "DL-PAYROLL.v1.1.9",
    "released_at": "2026-08-07",
    "effective_from": "2026-02",
})
_gonglingjiang = next(subject for subject in _RULE_PACKAGE["subjects"] if subject["id"] == "gonglingjiang")
_gonglingjiang["version"] = "DL-GONGLING.v1.0.7"
_gonglingjiang["summary"] = (
    "按地区、二级部门、岗位、月初司龄和缺勤口径核算；B操作部与中国操作部使用相同规则，"
    "安检员岗位按名称包含匹配。"
)
dongguan_operation = next(region for region in _gonglingjiang["regions"] if region["name"] == "东莞操作")
dongguan_operation["rule"] = "中国操作部、B操作部按已验证一线操作岗位发放。"
dongguan_operation["details"][0] = (
    "操作享有岗位：安检员、操作文员、操作员、叉车司机、揽收充电司机、查验员、监察员、理货员；"
    "岗位名称包含“安检员”字样即按安检员判断。"
)
wes_region = next(region for region in _gonglingjiang["regions"] if region["name"] == "东南 / 闽赣兼容区域")
wes_region["details"][0] = (
    "东南枢纽享有岗位：操作员、内勤专员、中转员、门禁员、安检员、操作文员；"
    "岗位名称包含“安检员”字样即按安检员判断。"
)
_gonglingjiang["verification"].insert(
    0,
    "最新线下核算截图确认B操作部操作员按中国操作部规则发放，并存在内部初级、内部高级、民航中级安检员等岗位名称。",
)
_gonglingjiang["change_log"].insert(0, {
    "version": "DL-GONGLING.v1.0.7",
    "released_at": "2026-08-07",
    "changes": "B操作部新增为操作归属部门并沿用中国操作部规则；岗位名称包含安检员字样时按安检员资格判断。",
})
_RULE_PACKAGE["version_history"] = [
    {
        "version": "1.1.9",
        "display_version": "DL-PAYROLL.v1.1.9",
        "status": "当前版本",
        "released_at": "2026-08-07",
        "effective_from": "2026-02",
        "subject_ids": ["quanqinjiang", "canbu", "waisu_butie", "gonglingjiang"],
        "summary": "工龄奖增加B操作部，并支持安检员岗位名称包含匹配。",
    },
    {
        **_RULE_PACKAGE_V1_1_8["version_history"][0],
        "status": "历史版本",
    },
    *_RULE_PACKAGE_V1_1_8["version_history"][1:],
]


_RULE_PACKAGE_V1_1_9 = deepcopy(_RULE_PACKAGE)
_RULE_PACKAGE = deepcopy(_RULE_PACKAGE_V1_1_9)
_RULE_PACKAGE.update({
    "version": "1.2.0",
    "display_version": "DL-PAYROLL.v1.2.0",
    "released_at": "2026-08-12",
    "effective_from": "2026-05",
    "scope_note": "收录平台当前执行的核算规则；已通过线下回归的科目标为已验证，仍在核对差异和特殊口径的科目标为验证中。",
})
_allowance_category = next(
    category for category in _RULE_PACKAGE["categories"] if category["id"] == "allowance"
)
_allowance_category["subject_ids"].append("yeban_butie")
_RULE_PACKAGE["subjects"].append({
    "id": "yeban_butie",
    "name": "夜班补贴",
    "english_name": "Night Shift Allowance",
    "category_id": "allowance",
    "version": "DL-YEBAN.v0.9.0",
    "status": "验证中",
    "effective_from": "2026-05",
    "summary": "按日考勤打卡、夜班窗口和班次休息时间逐日核算；正常日直接计入，异常但有计算依据的日期暂算计入，缺少计算依据的日期不计金额并等待补充。",
    "data_sources": [
        "月考勤：工号、姓名、工作地区、部门和岗位，用于员工归属及地区规则判断。",
        "日考勤：出勤日期、班次编号、工作状态、班次时间段、上班一和下班一。",
        "平台班次休息基线：当前内置122个班次，可按核算月份保存调整。",
        "晋江不享有夜班补贴人员名单：仅维护线下确认的额外排除人员、生效日期和失效日期。",
    ],
    "common_rules": [
        "只计算22:00至次日08:00夜班窗口内的有效出勤时长。",
        "上班向后、下班向前取整到半小时；取整后没有有效时段或未覆盖夜班窗口时不发放。",
        "按实际出勤覆盖情况扣除对应班次休息时间；班次休息使用平台基线并支持保存当月调整。",
        "普通夜班按有效夜班时长×3元/小时计算，单日最高25元；月度汇总后按Excel口径保留2位小数。",
        "上下班时长超过16小时、只覆盖部分休息时段等异常日期仍按现有数据暂算，暂算金额已计入本月应发并标记确认。",
        "缺少上下班打卡、日期无效或休息时间配置错误等没有完整计算依据的日期不计金额，补充数据后重新核算。",
        "非工作日且排班时间未覆盖夜班窗口时，即使没有打卡也按无需补贴处理。",
    ],
    "regions": [
        {
            "name": "东莞 / 嘉善 / 义乌",
            "rule": "当前按通用夜班规则核算，不设置地区或岗位拦截。",
            "formula": "有效夜班时长×3元/小时，单日最高25元",
            "details": [
                "地区在东莞、嘉善或义乌时直接进入通用规则。",
                "班次休息时间未维护时仍按现有打卡暂算，但不扣休息并标记确认。",
            ],
        },
        {
            "name": "晋江",
            "rule": "通用夜班规则之外，固定排除计件岗位和门禁岗位，并按月应用晋江额外排除人员名单。",
            "formula": "符合资格时按通用规则；命中排除规则时0元",
            "details": [
                "晋江计件岗位和门禁岗位由系统自动排除，不要求用户上传地区岗位范围。",
                "轻松岗位等无法从考勤字段稳定识别的人员，通过晋江不享有夜班补贴人员名单维护。",
                "当月晋江名单尚未确认时，符合通用规则的金额先暂算计入，并标记待确认。",
            ],
        },
        {
            "name": "凌晨3点班（LB15）",
            "rule": "当前按取整后的出勤时长折算暂算金额，因早退口径尚未确认，所有结果均需复核。",
            "formula": "取整后出勤时长/8小时×25元，单日最高25元",
            "details": [
                "金额先计入本月应发，并在结果中列为暂算需确认日。",
                "确认线下早退折算口径后再决定是否转为正式规则。",
            ],
        },
        {
            "name": "其他地区",
            "rule": "不阻断核算；符合通用规则的金额先暂算计入并提示确认地区口径。",
            "formula": "按通用规则暂算",
            "details": ["确认地区是否适用夜班补贴后再固化为正式规则。"],
        },
    ],
    "verification": [
        "2026年5月东莞、华东和晋江真实数据合计20,067条线下已发日记录回归。",
        "自动覆盖19,120条，覆盖率95.28%；其中16,220条金额精确一致，自动计算内准确率84.83%。",
        "班次休息与平台规则一致的标准休息子集金额准确率99.99%。",
        "晋江已计算记录1,052条全部精确一致，金额差异0元。",
        "全量平台测试、夜班补贴结果页及Excel导出回归。",
    ],
    "pending_confirmations": [
        "班次休息表与线下历史人工扣减存在差异，是当前东莞、华东金额差异的主要来源；需要继续核对并按月维护真实班次休息。",
        "凌晨3点班（LB15）的早退折算口径尚未确认，当前金额按8小时标准暂算并计入。",
        "超过16小时的异常打卡、只覆盖部分休息时段和扣除休息后有效时长异常的日期，当前暂算计入并要求人工复核。",
        "缺卡日期不计金额；补充上下班打卡后需要重新核算。",
        "连班登记及其特殊扣减口径尚未接入，待补充线下口径和表后开发。",
    ],
    "change_log": [
        {
            "version": "DL-YEBAN.v0.9.0",
            "released_at": "2026-08-12",
            "changes": "首次纳入规则包并标记验证中：发布通用夜班窗口、半小时取整、班次休息、地区规则、晋江名单及暂算/待补卡处理方式。",
        }
    ],
})
_RULE_PACKAGE["version_history"] = [
    {
        "version": "1.2.0",
        "display_version": "DL-PAYROLL.v1.2.0",
        "status": "当前版本",
        "released_at": "2026-08-12",
        "effective_from": "2026-05",
        "subject_ids": ["quanqinjiang", "canbu", "waisu_butie", "gonglingjiang", "yeban_butie"],
        "summary": "新增夜班补贴验证中规则，记录当前计算口径、暂算机制、晋江排除规则和真实数据回归结果。",
    },
    {
        **_RULE_PACKAGE_V1_1_9["version_history"][0],
        "status": "历史版本",
    },
    *_RULE_PACKAGE_V1_1_9["version_history"][1:],
]


_RULE_PACKAGE_V1_2_0 = deepcopy(_RULE_PACKAGE)
_RULE_PACKAGE = deepcopy(_RULE_PACKAGE_V1_2_0)
_RULE_PACKAGE.update({
    "version": "1.2.1",
    "display_version": "DL-PAYROLL.v1.2.1",
    "released_at": "2026-08-12",
})
_yeban_butie = next(subject for subject in _RULE_PACKAGE["subjects"] if subject["id"] == "yeban_butie")
_yeban_butie["version"] = "DL-YEBAN.v0.9.1"
_yeban_butie["field_calculations"] = [
    {
        "field": "计薪上班",
        "definition": "用于核算的起始时间。",
        "formula": "上班打卡向后取整到最近的半小时。",
        "example": "17:53 → 18:00；18:00 → 18:00",
    },
    {
        "field": "计薪下班",
        "definition": "用于核算的结束时间；跨日时显示“次日”。",
        "formula": "下班打卡向前取整到最近的半小时；下班时间早于或等于上班时间时按次日处理。",
        "example": "07:13 → 次日07:00；07:45 → 次日07:30",
    },
    {
        "field": "夜班时长（小时）",
        "definition": "普通夜班的计薪时间落在22:00至次日08:00窗口内的时长。",
        "formula": "夜班窗口交集分钟 ÷ 60；交集起点取计薪上班与22:00的较晚值，终点取计薪下班与次日08:00的较早值。",
        "example": "18:00—次日07:00与夜班窗口重叠9小时",
    },
    {
        "field": "扣除休息（小时）",
        "definition": "普通夜班计薪出勤与该班次休息时段重叠的合计时长。",
        "formula": "各段休息与计薪出勤的重叠分钟之和 ÷ 60；没有重叠则为0。",
        "example": "休息02:00—03:00且出勤完整覆盖 → 扣除1小时",
    },
    {
        "field": "有效夜班时长（小时）",
        "definition": "普通夜班实际用于计算补贴的时长。",
        "formula": "max（夜班时长 − 扣除休息，0）。",
        "example": "9小时 − 1小时 = 8小时",
    },
    {
        "field": "当日夜班补贴",
        "definition": "普通夜班当天计入月度汇总的补贴金额。",
        "formula": "min（有效夜班时长 × 3元/小时，25元）。",
        "example": "min（8小时 × 3元，25元）= 24元；8.5小时 × 3元按25元封顶",
    },
    {
        "field": "凌晨3点班当日补贴（LB15）",
        "definition": "凌晨3点班当前使用的暂算金额，暂不套用普通夜班窗口及休息扣除。",
        "formula": "min（取整后出勤时长 ÷ 8小时 × 25元，25元）。",
        "example": "取整后出勤7小时 → 7 ÷ 8 × 25 = 21.875元；月度汇总后统一保留2位小数",
    },
    {
        "field": "本月应发夜班补贴",
        "definition": "员工本月最终展示和导出的夜班补贴金额。",
        "formula": "正常核算日金额合计 + 暂算需确认日金额合计；待补卡日不计金额，月度汇总后按Excel口径保留2位小数。",
        "example": "暂算需确认日已计入应发；补齐缺卡后重新核算并更新本月金额",
    },
]
_yeban_butie["change_log"].insert(0, {
    "version": "DL-YEBAN.v0.9.1",
    "released_at": "2026-08-12",
    "changes": "新增导出字段级计算定义、公式和示例，明确普通夜班、凌晨3点班及月度汇总口径；规则状态仍为验证中。",
})
_RULE_PACKAGE["version_history"] = [
    {
        "version": "1.2.1",
        "display_version": "DL-PAYROLL.v1.2.1",
        "status": "当前版本",
        "released_at": "2026-08-12",
        "effective_from": "2026-05",
        "subject_ids": ["quanqinjiang", "canbu", "waisu_butie", "gonglingjiang", "yeban_butie"],
        "summary": "夜班补贴增加字段级计算公式和真实样例，明确计薪时间、夜班时长、休息扣除、当日金额及月度汇总口径。",
    },
    {
        **_RULE_PACKAGE_V1_2_0["version_history"][0],
        "status": "历史版本",
    },
    *_RULE_PACKAGE_V1_2_0["version_history"][1:],
]


_RULE_PACKAGE_V1_2_1 = deepcopy(_RULE_PACKAGE)
_RULE_PACKAGE = deepcopy(_RULE_PACKAGE_V1_2_1)
_RULE_PACKAGE.update({
    "version": "1.2.2",
    "display_version": "DL-PAYROLL.v1.2.2",
    "released_at": "2026-08-12",
})
_yeban_butie = next(subject for subject in _RULE_PACKAGE["subjects"] if subject["id"] == "yeban_butie")
_yeban_butie["version"] = "DL-YEBAN.v0.9.2"
_yeban_butie["summary"] = (
    "按日考勤打卡、夜班窗口和班次休息时间逐日核算；正常日直接计入，异常但有计算依据的日期暂算计入，"
    "员工缺勤导致的考勤异常日不计金额。"
)
_yeban_butie["common_rules"][5] = (
    "员工缺勤导致的考勤异常，以及日期无效、休息时间配置错误等没有完整计算依据的日期不计金额。"
)
_yeban_butie["pending_confirmations"][3] = "员工缺勤导致的考勤异常日不计夜班补贴。"
_monthly_amount_field = next(
    item for item in _yeban_butie["field_calculations"] if item["field"] == "本月应发夜班补贴"
)
_monthly_amount_field["formula"] = (
    "正常核算日金额合计 + 暂算需确认日金额合计；考勤异常等未计金额日不计入，"
    "月度汇总后按Excel口径保留2位小数。"
)
_monthly_amount_field["example"] = "暂算需确认日已计入应发；员工缺勤导致的考勤异常日为0元"
_yeban_butie["change_log"].insert(0, {
    "version": "DL-YEBAN.v0.9.2",
    "released_at": "2026-08-12",
    "changes": "将员工缺勤统一展示为考勤异常，并明确考勤异常日不计夜班补贴。",
})
_legacy_night_shift_log = next(
    item for item in _yeban_butie["change_log"] if item["version"] == "DL-YEBAN.v0.9.0"
)
_legacy_night_shift_log["changes"] = (
    "首次纳入规则包并标记验证中：发布通用夜班窗口、半小时取整、班次休息、地区规则、"
    "晋江名单及考勤异常处理方式。"
)
_RULE_PACKAGE["version_history"] = [
    {
        "version": "1.2.2",
        "display_version": "DL-PAYROLL.v1.2.2",
        "status": "当前版本",
        "released_at": "2026-08-12",
        "effective_from": "2026-05",
        "subject_ids": ["quanqinjiang", "canbu", "waisu_butie", "gonglingjiang", "yeban_butie"],
        "summary": "夜班补贴将员工缺勤统一展示为考勤异常，并明确考勤异常日不计夜班补贴。",
    },
    {
        **_RULE_PACKAGE_V1_2_1["version_history"][0],
        "status": "历史版本",
    },
    *_RULE_PACKAGE_V1_2_1["version_history"][1:],
]


_RULE_PACKAGE_V1_2_2 = deepcopy(_RULE_PACKAGE)
_RULE_PACKAGE = deepcopy(_RULE_PACKAGE_V1_2_2)
_RULE_PACKAGE.update({
    "version": "1.2.3",
    "display_version": "DL-PAYROLL.v1.2.3",
    "released_at": "2026-08-12",
})
_security_inspector_rule = (
    "安检员岗位资格仅识别以下7个名称：安检员、民航初级安检员、民航中级安检员、民航高级安检员、"
    "内部初级安检员、内部中级安检员、内部高级安检员；其他仅包含‘安检员’字样的岗位不自动享有。"
)

_canbu = next(subject for subject in _RULE_PACKAGE["subjects"] if subject["id"] == "canbu")
_canbu["version"] = "DL-CANBU.v1.0.1"
_canbu["common_rules"].append(_security_inspector_rule)
_canbu["change_log"].insert(0, {
    "version": "DL-CANBU.v1.0.1",
    "released_at": "2026-08-12",
    "changes": "餐补岗位资格兼容旧称安检员及6个已确认的新岗位名称；未改变原有地区、部门和其他岗位范围。",
})

_waisu_butie = next(subject for subject in _RULE_PACKAGE["subjects"] if subject["id"] == "waisu_butie")
_waisu_butie["version"] = "DL-WAISU.v1.0.2"
_waisu_butie["common_rules"].append(_security_inspector_rule)
_waisu_butie["change_log"].insert(0, {
    "version": "DL-WAISU.v1.0.2",
    "released_at": "2026-08-12",
    "changes": "外宿补贴岗位资格兼容旧称安检员及6个已确认的新岗位名称；仅继承原本安检员适用的地区范围。",
})

_gonglingjiang = next(subject for subject in _RULE_PACKAGE["subjects"] if subject["id"] == "gonglingjiang")
_gonglingjiang["version"] = "DL-GONGLING.v1.0.8"
_gonglingjiang["common_rules"].append(_security_inspector_rule)
for _region in _gonglingjiang["regions"]:
    _region["details"] = [
        detail.replace(
            "岗位名称包含“安检员”字样即按安检员判断。",
            "安检员岗位按已确认的7个名称精确判断。",
        )
        for detail in _region.get("details", [])
    ]
_gonglingjiang["change_log"].insert(0, {
    "version": "DL-GONGLING.v1.0.8",
    "released_at": "2026-08-12",
    "changes": "工龄奖将安检员岗位由模糊包含匹配收紧为7个确认名称精确匹配，同时保留旧称安检员。",
})

_RULE_PACKAGE["version_history"] = [
    {
        "version": "1.2.3",
        "display_version": "DL-PAYROLL.v1.2.3",
        "status": "当前版本",
        "released_at": "2026-08-12",
        "effective_from": "2026-05",
        "subject_ids": ["quanqinjiang", "canbu", "waisu_butie", "gonglingjiang", "yeban_butie"],
        "summary": "餐补、外宿补贴和工龄奖兼容安检员旧称及6个确认的新岗位名称，并改为精确岗位匹配。",
    },
    {
        **_RULE_PACKAGE_V1_2_2["version_history"][0],
        "status": "历史版本",
    },
    *_RULE_PACKAGE_V1_2_2["version_history"][1:],
]


_RULE_PACKAGE_V1_2_3 = deepcopy(_RULE_PACKAGE)
_RULE_PACKAGE = deepcopy(_RULE_PACKAGE_V1_2_3)
_RULE_PACKAGE.update({
    "version": "1.2.4",
    "display_version": "DL-PAYROLL.v1.2.4",
    "released_at": "2026-08-12",
})
_yeban_butie = next(subject for subject in _RULE_PACKAGE["subjects"] if subject["id"] == "yeban_butie")
_yeban_butie["version"] = "DL-YEBAN.v0.9.3"
_yeban_butie["common_rules"][2] = (
    "按实际出勤覆盖情况分别扣除班次配置中的晚上休息、早上休息和其他休息；"
    "每段休息的分类由班次配置明确维护，不按是否跨零点自动判断。"
)
_rest_field_index = next(
    index for index, item in enumerate(_yeban_butie["field_calculations"])
    if item["field"] == "扣除休息（小时）"
)
_yeban_butie["field_calculations"][_rest_field_index:_rest_field_index + 1] = [
    {
        "field": "晚上休息扣除（小时）",
        "definition": "班次配置中标注为晚上休息，且与计薪出勤重叠的休息时长。",
        "formula": "各段‘晚上休息’与计薪出勤的重叠分钟之和 ÷ 60。",
        "example": "23:00—24:00标注为晚上休息且完整覆盖 → 扣除1小时；00:00—01:00仍可标注为晚上休息。",
    },
    {
        "field": "早上休息扣除（小时）",
        "definition": "班次配置中标注为早上休息，且与计薪出勤重叠的休息时长。",
        "formula": "各段‘早上休息’与计薪出勤的重叠分钟之和 ÷ 60。",
        "example": "次日06:00—06:30标注为早上休息且完整覆盖 → 扣除0.5小时。",
    },
    {
        "field": "休息扣除合计（小时）",
        "definition": "当日从夜班时长中扣除的全部班次休息时长。",
        "formula": "晚上休息扣除 + 早上休息扣除 + 其他休息扣除。",
        "example": "晚上休息1小时 + 早上休息0.5小时 = 合计扣除1.5小时。",
    },
]
_effective_field = next(
    item for item in _yeban_butie["field_calculations"]
    if item["field"] == "有效夜班时长（小时）"
)
_effective_field["formula"] = "max（夜班时长 − 休息扣除合计，0）。"
_effective_field["example"] = "9.5小时 − 晚上休息1小时 − 早上休息0.5小时 = 8小时"
_yeban_butie["change_log"].insert(0, {
    "version": "DL-YEBAN.v0.9.3",
    "released_at": "2026-08-12",
    "changes": "班次配置为每段休息增加业务分类，核算明细分别展示晚上休息、早上休息和休息扣除合计；计算总额口径不变。",
})
_RULE_PACKAGE["version_history"] = [
    {
        "version": "1.2.4",
        "display_version": "DL-PAYROLL.v1.2.4",
        "status": "当前版本",
        "released_at": "2026-08-12",
        "effective_from": "2026-05",
        "subject_ids": ["quanqinjiang", "canbu", "waisu_butie", "gonglingjiang", "yeban_butie"],
        "summary": "夜班补贴按班次配置拆分晚上休息、早上休息和休息扣除合计，页面与导出同步展示。",
    },
    {
        **_RULE_PACKAGE_V1_2_3["version_history"][0],
        "status": "历史版本",
    },
    *_RULE_PACKAGE_V1_2_3["version_history"][1:],
]


_RULE_PACKAGE_V1_2_4 = deepcopy(_RULE_PACKAGE)
_RULE_PACKAGE = deepcopy(_RULE_PACKAGE_V1_2_4)
_RULE_PACKAGE.update({
    "version": "1.2.5",
    "display_version": "DL-PAYROLL.v1.2.5",
    "released_at": "2026-08-12",
})
_canbu = next(subject for subject in _RULE_PACKAGE["subjects"] if subject["id"] == "canbu")
_canbu["version"] = "DL-CANBU.v1.0.2"
_dongguan_canbu = next(region for region in _canbu["regions"] if region["name"] == "东莞")
_dongguan_canbu["formula"] = "ROUND(min(Σ单日未舍入餐补, 500元), 2)"
_dongguan_canbu["details"].append(
    "单日折算金额保留原始精度，月底汇总后统一舍入2位小数，避免逐日舍入造成累计差异。"
)
_canbu["change_log"].insert(0, {
    "version": "DL-CANBU.v1.0.2",
    "released_at": "2026-08-12",
    "changes": "东莞餐补改为单日保留原始精度、月底汇总后统一按Excel口径舍入2位小数；岗位范围不变。",
})
_RULE_PACKAGE["version_history"] = [
    {
        "version": "1.2.5",
        "display_version": "DL-PAYROLL.v1.2.5",
        "status": "当前版本",
        "released_at": "2026-08-12",
        "effective_from": "2026-05",
        "subject_ids": ["quanqinjiang", "canbu", "waisu_butie", "gonglingjiang", "yeban_butie"],
        "summary": "餐补、外宿补贴和工龄奖保留安检员新旧岗位别名；东莞餐补改为月底汇总后统一舍入。",
    },
    {
        **_RULE_PACKAGE_V1_2_4["version_history"][0],
        "status": "历史版本",
    },
    *_RULE_PACKAGE_V1_2_4["version_history"][1:],
]


_RULE_PACKAGE_V1_2_5 = deepcopy(_RULE_PACKAGE)
_RULE_PACKAGE = deepcopy(_RULE_PACKAGE_V1_2_5)
_RULE_PACKAGE.update({
    "version": "1.2.6",
    "display_version": "DL-PAYROLL.v1.2.6",
    "released_at": "2026-08-12",
})
_canbu = next(subject for subject in _RULE_PACKAGE["subjects"] if subject["id"] == "canbu")
_canbu["version"] = "DL-CANBU.v1.0.3"
_jiashan_yiwu_canbu = next(
    region for region in _canbu["regions"] if region["name"] == "嘉善 / 义乌"
)
_jiashan_yiwu_canbu["rule"] = "岗位在嘉善/义乌享有名单内（新增查验员），按月考勤字段折算。"
_jiashan_yiwu_canbu["details"].append(
    "查验员按已确认资格纳入嘉善/义乌餐补范围；其他地区、岗位和计算公式不变。"
)
_canbu["change_log"].insert(0, {
    "version": "DL-CANBU.v1.0.3",
    "released_at": "2026-08-12",
    "changes": "嘉善/义乌餐补享有岗位新增查验员；地区范围和月度折算公式不变。",
})
_RULE_PACKAGE["version_history"] = [
    {
        "version": "1.2.6",
        "display_version": "DL-PAYROLL.v1.2.6",
        "status": "当前版本",
        "released_at": "2026-08-12",
        "effective_from": "2026-05",
        "subject_ids": ["quanqinjiang", "canbu", "waisu_butie", "gonglingjiang", "yeban_butie"],
        "summary": "嘉善/义乌餐补享有岗位新增查验员；其他规则不变。",
    },
    {
        **_RULE_PACKAGE_V1_2_5["version_history"][0],
        "status": "历史版本",
    },
    *_RULE_PACKAGE_V1_2_5["version_history"][1:],
]


_RULE_PACKAGE_V1_2_6 = deepcopy(_RULE_PACKAGE)
_RULE_PACKAGE = deepcopy(_RULE_PACKAGE_V1_2_6)
_RULE_PACKAGE.update({
    "version": "1.3.0",
    "display_version": "DL-PAYROLL.v1.3.0",
    "released_at": "2026-08-12",
    "effective_from": "2026-07",
})
_allowance_category = next(
    category for category in _RULE_PACKAGE["categories"] if category["id"] == "allowance"
)
_allowance_category["subject_ids"].append("gangwei_butie")
_RULE_PACKAGE["subjects"].append({
    "id": "gangwei_butie",
    "name": "岗位补贴",
    "english_name": "Position Allowance",
    "category_id": "allowance",
    "version": "DL-GANGWEI.v0.9.0",
    "status": "验证中",
    "effective_from": "2026-07",
    "summary": "按地区、岗位名称、排班天数和缺勤时数核算；忽略职级，女神假每1天按8小时计入56小时缺勤门槛。",
    "data_sources": [
        "月考勤：工号、姓名、工作地区、岗位名称和排班天数。",
        "缺勤字段：事假、排休请假、病假、旷工、休年假、女神假、其他带薪假、调休和入离职缺勤。",
        "特殊人员：东莞陈晓龙、晋江贾万按特殊安检组长资格识别。",
    ],
    "common_rules": [
        "岗位名称直接匹配资格和月度标准，职级字段不参与资格或金额计算。",
        "女神假时数=女神假天数×8；再与其余八类缺勤时数相加。",
        "缺勤合计未达到56小时时不扣减；达到56小时后，按全部缺勤时数÷8折算扣减天数。",
        "应发岗位补贴=岗位补贴标准÷排班天数×(排班天数−扣减天数)，按Excel ROUND保留2位小数，最低为0元。",
        "有资格但没有真实线下样本可确定标准的岗位不自行套档，金额暂为0并进入标准确认。",
    ],
    "field_calculations": [
        {
            "field": "岗位补贴标准",
            "definition": "按工作地区、岗位名称或特殊安检组长人员匹配月度标准；职级不参与。",
            "formula": "标准=岗位标准表[工作地区, 岗位名称]；特殊组长按人员名单匹配",
            "example": "东莞民航初级安检员=1,300元；内部中级安检员=450元；陈晓龙=800元。",
        },
        {
            "field": "女神假折算时数",
            "definition": "女神假源字段为天数，统一折算为小时后参与缺勤门槛。",
            "formula": "女神假折算时数=女神假天数×8",
            "example": "女神假7天×8=56小时。",
        },
        {
            "field": "缺勤合计时数",
            "definition": "九类缺勤按小时合计，用于判断是否达到56小时门槛。",
            "formula": "事假+排休请假+病假+旷工+休年假+女神假天数×8+其他带薪假+调休+入离职缺勤",
            "example": "22小时休年假+35.5小时调休+24小时入离职缺勤=81.5小时。",
        },
        {
            "field": "扣减天数",
            "definition": "未达到56小时不扣减；达到后把全部缺勤小时折算为天数。",
            "formula": "IF(缺勤合计时数>=56, 缺勤合计时数÷8, 0)",
            "example": "55.5小时扣0天；81.5小时扣10.1875天。",
        },
        {
            "field": "应发岗位补贴",
            "definition": "按月标准和排班天数折算，月底统一保留2位小数。",
            "formula": "ROUND(标准÷排班天数×MAX(排班天数−扣减天数,0),2)",
            "example": "陈晓龙：800÷25×(25−81.5÷8)=474.00元。",
        },
    ],
    "regions": [
        {
            "name": "东莞",
            "rule": "已验证的安检等级岗位、HRBP相关岗位、叉车司机及陈晓龙按岗位或人员标准核算。",
            "formula": "按通用56小时缺勤折算公式",
            "details": [
                "已验证标准：内部初/中/高300/450/650元，民航初/中级1300/1500元。",
                "HRBP专员、高级HRBP专员、高级招聘专员700元；叉车司机800元；陈晓龙800元。",
                "旧称安检员、民航高级安检员、揽收充电司机已有资格但标准待确认。",
            ],
        },
        {
            "name": "嘉善 / 义乌",
            "rule": "持证安检员按六类新岗位名称和旧称安检员识别；已知岗位标准按岗位名称核算。",
            "formula": "按通用56小时缺勤折算公式",
            "details": ["民航高级安检员和旧称安检员因没有可验证金额标准，当前进入标准确认。"],
        },
        {
            "name": "晋江",
            "rule": "贾万按特殊安检组长资格识别，当前按800元月标准暂算。",
            "formula": "按通用56小时缺勤折算公式",
            "details": ["800元来自已验证安检组长标准，需在生产测试中继续核对晋江线下结果。"],
        },
    ],
    "verification": [
        "《7月岗位补贴.xlsx》18名员工逐人回算一致，18/18金额精确一致。",
        "线下应发合计15,074.00元，平台回归合计15,074.00元，差异0元。",
        "已覆盖标准金额、56小时边界、女神假天数×8、特殊组长、无资格和标准待确认场景。",
        "平台API、结果页和岗位补贴专用Excel导出回归。",
    ],
    "pending_confirmations": [
        "旧称安检员、民航高级安检员和揽收充电司机的月度金额标准尚无真实样本，当前不自行套档。",
        "嘉善/义乌的岗位标准需要用生产线下结果继续验证。",
        "晋江贾万当前按特殊安检组长800元标准暂算，需要用生产线下结果确认。",
    ],
    "change_log": [{
        "version": "DL-GANGWEI.v0.9.0",
        "released_at": "2026-08-12",
        "changes": "首次接入岗位补贴：发布岗位标准、特殊安检组长、56小时缺勤门槛和女神假天数×8规则，并标记验证中。",
    }],
})
_RULE_PACKAGE["version_history"] = [
    {
        "version": "1.3.0",
        "display_version": "DL-PAYROLL.v1.3.0",
        "status": "当前版本",
        "released_at": "2026-08-12",
        "effective_from": "2026-07",
        "subject_ids": ["quanqinjiang", "canbu", "waisu_butie", "gonglingjiang", "yeban_butie", "gangwei_butie"],
        "summary": "新增岗位补贴验证版，接入岗位标准、特殊安检组长、56小时门槛和女神假天数×8规则。",
    },
    {
        **_RULE_PACKAGE_V1_2_6["version_history"][0],
        "status": "历史版本",
    },
    *_RULE_PACKAGE_V1_2_6["version_history"][1:],
]


_RULE_PACKAGE_V1_3_0 = deepcopy(_RULE_PACKAGE)
_RULE_PACKAGE = deepcopy(_RULE_PACKAGE_V1_3_0)
_RULE_PACKAGE.update({
    "version": "1.3.1",
    "display_version": "DL-PAYROLL.v1.3.1",
    "released_at": "2026-08-12",
    "effective_from": "2026-08",
})
_quanqin = next(subject for subject in _RULE_PACKAGE["subjects"] if subject["id"] == "quanqinjiang")
_quanqin.update({
    "version": "DL-QUANQIN.v1.1.0",
    "status": "已验证",
    "effective_from": "2026-08",
    "summary": "全区域固定标准100元；迟到豁免只能二选一：6分钟内最多3次，或6-20分钟最多1次，超限或混用均不发放。",
})
_quanqin["data_sources"] = [
    "月考勤：工号、姓名、考勤月份、入职日期、最后工作日及全勤判断字段。",
    "迟到分档：迟到6分钟内(次)、迟到6-20分钟内(次)、迟到20-30分钟内(次)。",
    "日考勤：出勤日期、工作状态，用于判断月初至入职日前是否存在工作日。",
]
_quanqin["common_rules"] = [
    "满足全部条件时发放100元，否则为0元。",
    "迟到豁免只能选择一档：6分钟内最多3次，或者6-20分钟内最多1次，两档不可叠加。",
    "两档迟到同时出现时，即使各自未超过次数，全勤奖也为0；例如6分钟内2次且6-20分钟内1次，结果为0元。",
    "6分钟内迟到超过3次、6-20分钟迟到超过1次，或存在20-30分钟迟到时，全勤奖为0。",
    "本规则必须读取三个迟到分档字段；字段缺失时停止核算，不能只凭迟到总次数推断。",
    "旷工天数、工伤假天数、事假时数、病假时数、入离职缺勤时数或迟到早退30分钟内扣款任一大于0时不发放。",
    "签卡次数不超过3次；休年假和排休请假不单独影响全勤奖。",
    "月初至入职日前存在工作日时不发放；最后工作日早于月末时不发放。",
    "OWHN9535、OWHN9353、OWHX0190为长期特殊排除名单，固定不发放。",
]
_quanqin["field_calculations"] = [
    {
        "field": "迟到豁免判断",
        "definition": "按整月迟到分档判断，两个豁免档位互斥，不能累加使用。",
        "formula": "允许=(6分钟内次数<=3 且 6-20分钟次数=0) OR (6分钟内次数=0 且 6-20分钟次数<=1)；20-30分钟次数必须为0",
        "example": "6分钟内2次+6-20分钟1次：两档混用，不符合豁免。",
    },
    {
        "field": "应发全勤奖",
        "definition": "迟到豁免及其他全勤条件全部满足时发放固定100元。",
        "formula": "IF(迟到豁免符合 AND 未命中其他排除项 AND 满足入离职边界, 100, 0)",
        "example": "仅6分钟内3次且无其他排除项=100元；仅6-20分钟1次且无其他排除项=100元；两档混用=0元。",
    },
]
_quanqin["verification"] = [
    "旧版规则曾使用四份真实月报2,807人逐行回归一致。",
    "分档迟到互斥规则已按薪酬组确认口径发布。",
    "已完成6分钟内0/1/3/4次、6-20分钟1/2次、两档混用及20-30分钟迟到自动化边界回归。",
]
_quanqin["pending_confirmations"] = []
_quanqin["change_log"].insert(0, {
    "version": "DL-QUANQIN.v1.1.0",
    "released_at": "2026-08-12",
    "changes": "迟到豁免改为互斥二选一：6分钟内最多3次，或6-20分钟内最多1次；超限、混用及20-30分钟迟到均不发放。",
})
_RULE_PACKAGE["version_history"] = [
    {
        "version": "1.3.1",
        "display_version": "DL-PAYROLL.v1.3.1",
        "status": "当前版本",
        "released_at": "2026-08-12",
        "effective_from": "2026-08",
        "subject_ids": ["quanqinjiang", "canbu", "waisu_butie", "gonglingjiang", "yeban_butie", "gangwei_butie"],
        "summary": "全勤奖新增互斥迟到豁免：6分钟内最多3次，或6-20分钟内最多1次，混用即为0元。",
    },
    {
        **_RULE_PACKAGE_V1_3_0["version_history"][0],
        "status": "历史版本",
    },
    *_RULE_PACKAGE_V1_3_0["version_history"][1:],
]


_RULE_PACKAGE_V1_3_1 = deepcopy(_RULE_PACKAGE)
_RULE_PACKAGE = deepcopy(_RULE_PACKAGE_V1_3_1)
_RULE_PACKAGE.update({
    "version": "1.3.2",
    "display_version": "DL-PAYROLL.v1.3.2",
    "released_at": "2026-08-13",
})
_gangwei = next(subject for subject in _RULE_PACKAGE["subjects"] if subject["id"] == "gangwei_butie")
_gangwei.update({
    "version": "DL-GANGWEI.v0.9.1",
    "summary": "按地区、岗位名称、排班天数和缺勤时数核算；入离职缺勤可按实际在职工作日自动计算，职级不参与。",
})
_gangwei["data_sources"][0] = "月考勤：工号、姓名、工作地区、岗位名称、排班天数和实际在职工作日天数。"
_gangwei["common_rules"].insert(
    1,
    "入离职缺勤时数已有非零值时直接使用；否则按MAX(排班天数−实际在职工作日天数,0)×8自动计算。实际在职工作日天数缺失时暂按0小时并提示确认，不阻止核算。",
)
_gangwei["field_calculations"].insert(2, {
    "field": "入离职缺勤时数",
    "definition": "优先保留月考勤已有非零值；未提供时按排班天数与实际在职工作日天数自动计算。",
    "formula": "IF(已有入离职缺勤时数>0, 已有值, MAX(排班天数−实际在职工作日天数,0)×8)",
    "example": "排班23天、实际在职20天，入离职缺勤=(23−20)×8=24小时。",
})
_gangwei["verification"].insert(
    -1,
    "已覆盖入离职缺勤已有值优先、按排班与实际在职工作日自动计算、缺字段只提示不阻断场景。",
)
_gangwei["change_log"].insert(0, {
    "version": "DL-GANGWEI.v0.9.1",
    "released_at": "2026-08-13",
    "changes": "入离职缺勤已有非零值优先；否则按排班天数与实际在职工作日天数自动计算，缺少实际在职工作日时只提示、不阻止核算。",
})
_RULE_PACKAGE["version_history"] = [
    {
        "version": "1.3.2",
        "display_version": "DL-PAYROLL.v1.3.2",
        "status": "当前版本",
        "released_at": "2026-08-13",
        "effective_from": "2026-07",
        "subject_ids": ["quanqinjiang", "canbu", "waisu_butie", "gonglingjiang", "yeban_butie", "gangwei_butie"],
        "summary": "岗位补贴接入入离职缺勤自动计算：已有值优先，否则按排班与实际在职工作日折算。",
    },
    {
        **_RULE_PACKAGE_V1_3_1["version_history"][0],
        "status": "历史版本",
    },
    *_RULE_PACKAGE_V1_3_1["version_history"][1:],
]


_RULE_PACKAGE_V1_3_2 = deepcopy(_RULE_PACKAGE)
_RULE_PACKAGE = deepcopy(_RULE_PACKAGE_V1_3_2)
_RULE_PACKAGE.update({
    "version": "1.4.0",
    "display_version": "DL-PAYROLL.v1.4.0",
    "released_at": "2026-08-13",
    "effective_from": "2026-06",
})
_allowance_category = next(
    category for category in _RULE_PACKAGE["categories"] if category["id"] == "allowance"
)
_allowance_category["subject_ids"].append("gaowen_butie")
_RULE_PACKAGE["subjects"].append({
    "id": "gaowen_butie",
    "name": "高温补贴",
    "english_name": "High-temperature Allowance",
    "category_id": "allowance",
    "version": "DL-GAOWEN.v0.9.0",
    "status": "验证中",
    "effective_from": "2026-06",
    "summary": "高温季按测温网点、出勤日期和白/夜班匹配温度，达到33℃后按实际出勤时长逐日折算；职级和领色不参与。",
    "data_sources": [
        "月考勤：工号、姓名、工作地区、岗位及各级组织字段，用于识别员工对应测温网点。",
        "日考勤：出勤日期、班次名称/时间段、正班时数、刷卡加班和实际上班时数。",
        "高温测温登记：班次日期、测温班次、测温网点和测温温度。",
        "地区固定排除：东莞、嘉善/义乌人员名单；晋江固定岗位范围和HRBP排除人员。",
    ],
    "common_rules": [
        "发放期间为每年6月1日至10月31日；5月及其他非高温月份不计发。",
        "测温区按同测温网点、同出勤日期、同白/夜班匹配最高温度；达到33℃才进入当日金额计算。",
        "实际高温出勤时长=MAX(正班时数,刷卡加班)；实际上班时数的0缓存不覆盖明确正班，仅正班为0且最多残留0.5小时刷卡时按无实际出勤处理。",
        "工作日、休息日和法定节假日只要有符合条件的实际出勤，均按同一逐日公式计算。",
        "职级和领色不参与高温补贴资格或金额计算。",
        "测温区没有同班次测温记录时按0元；测温文件缺失不阻止创建任务，但不能自动当作无测温区域全额发放。",
        "逐日金额保留原始精度求和，月度封顶后按Excel ROUND保留2位小数。",
    ],
    "field_calculations": [
        {
            "field": "对应测温网点",
            "definition": "根据工作地区及一级至六级组织归属识别员工实际作业仓库。",
            "formula": "测温网点=固定组织到物理仓库映射[工作地区, 各级组织名称]",
            "example": "中国仓安全组→中国仓组-东莞茶山仓；华南B2B枢纽组→华南B2B枢纽-清溪仓。",
        },
        {
            "field": "测温班次",
            "definition": "优先读取班次名称；无法直接识别时按班次时间段起始时间划分白班/夜班。",
            "formula": "起始时间≥18:00或<06:00→夜班；其余→白班",
            "example": "19:00-28:00识别为夜班；09:00-18:00识别为白班。",
        },
        {
            "field": "当班最高温度",
            "definition": "只取与员工同仓、同出勤日期、同白/夜班的测温记录最高值。",
            "formula": "MAXIFS(测温温度,测温网点=员工网点,班次日期=出勤日期,测温班次=员工班次)",
            "example": "同日白班34.2℃、夜班32.9℃；夜班员工按32.9℃，不借用白班温度。",
        },
        {
            "field": "实际高温出勤时长",
            "definition": "采用正班时数和刷卡加班中的较大值；实际上班时数只用于识别无正班且最多残留0.5小时刷卡的零出勤脏数据。",
            "formula": "IF(实际上班时数=0 AND 正班时数=0 AND 刷卡加班<=0.5,0,MAX(正班时数,刷卡加班))",
            "example": "正班8小时即使实际上班时数为0缓存仍计8小时；正班0、实际上班0且刷卡加班0.5小时则不计。",
        },
        {
            "field": "当日高温补贴",
            "definition": "当班温度达到33℃后，按地区小时单价和实际出勤时长折算。",
            "formula": "IF(当班最高温度>=33,MIN(实际高温出勤时长×小时单价,单日封顶),0)",
            "example": "东莞4小时×1.725元=6.90元；8小时及以上封顶13.80元。",
        },
        {
            "field": "本月应发高温补贴",
            "definition": "逐日原始金额求和，应用地区月度封顶后保留2位小数。",
            "formula": "ROUND(MIN(SUM(当日高温补贴),地区月度封顶),2)",
            "example": "广东逐日合计427.80元，月度按300.00元发放。",
        },
    ],
    "regions": [
        {
            "name": "广东（东莞）",
            "rule": "同仓同日同班次温度达到33℃后，按1.725元/小时核算。",
            "formula": "MIN(MAX(正班时数,刷卡加班)×1.725,13.8)，月度封顶300元",
            "details": [
                "寮步、凤岗、茶山、清溪按固定组织映射到测温网点。",
                "17名固定排除人员按线下规则名单处理。",
            ],
        },
        {
            "name": "浙江（嘉善 / 义乌）",
            "rule": "当前验证版沿用线下规则表13.8元/天口径，并按同仓同日同班次33℃门槛核算。",
            "formula": "MIN(MAX(正班时数,刷卡加班)×1.725,13.8)，月度封顶300元",
            "details": [
                "张青、盛菊英、周钰铉/周钰炫、叶玉、樊明雪固定排除。",
                "2026-06-08更新中的浙江室内9.2元/天、室外13.8元/天需要薪酬组确认岗位/场所映射后再分流。",
            ],
        },
        {
            "name": "福建（晋江）",
            "rule": "操作员、门禁员、操作组长按1.5元/小时核算；HRBP陈远远排除。",
            "formula": "MIN(MAX(正班时数,刷卡加班)×1.5,12)，月度封顶260元",
            "details": ["当前同样使用测温登记33℃门槛，需薪酬组用晋江生产结果继续验证。"],
        },
    ],
    "verification": [
        "华南2026年7月833名员工线下结果用于金额主回归；830人金额一致，人员准确率99.64%，剩余3人总绝对差124.20元。",
        "已覆盖33℃边界、白/夜班隔离、MAX(正班时数,刷卡加班)、实际上班时数为0、单日/月度封顶和高温季边界。",
        "华东2026年7月298名员工、8262条日考勤及274条测温记录完成可计算性验证；该表未提供线下高温应发金额，不计入金额准确率。",
        "平台API三文件上传、结果汇总、每日明细和专用Excel导出已建立自动化回归。",
    ],
    "pending_confirmations": [
        "浙江室内作业9.2元/天、室外作业13.8元/天的员工/岗位/场所映射尚未提供；当前沿用线下规则表13.8元/天验证。",
        "无测温区域及其他驻场人员按月全额发放，需要提供明确的区域/人员清单；测温文件漏传不能视为无测温区域。",
        "华南残余黄婷燕、晏鑫钰、陈妙玲3人共124.20元差异更像线下人员例外或漏算，未据此反推并硬编码全局规则。",
        "晋江是否同样严格执行同仓同日同班次33℃门槛，需要薪酬组用生产样本确认。",
    ],
    "change_log": [{
        "version": "DL-GAOWEN.v0.9.0",
        "released_at": "2026-08-13",
        "changes": "首次接入高温补贴验证版：支持测温登记、同仓同日同班次33℃门槛、逐日折算、地区上限和固定排除规则。",
    }],
})
_RULE_PACKAGE["version_history"] = [
    {
        "version": "1.4.0",
        "display_version": "DL-PAYROLL.v1.4.0",
        "status": "当前版本",
        "released_at": "2026-08-13",
        "effective_from": "2026-06",
        "subject_ids": [
            "quanqinjiang", "canbu", "waisu_butie", "gonglingjiang", "yeban_butie",
            "gangwei_butie", "gaowen_butie",
        ],
        "summary": "新增高温补贴验证版：接入测温登记、同仓同日同班次33℃门槛、逐日折算及地区封顶。",
    },
    {
        **_RULE_PACKAGE_V1_3_2["version_history"][0],
        "status": "历史版本",
    },
    *_RULE_PACKAGE_V1_3_2["version_history"][1:],
]


_RULE_PACKAGE_VERSIONS = {
    _RULE_PACKAGE_V1_0_0["version"]: _RULE_PACKAGE_V1_0_0,
    _RULE_PACKAGE_V1_1_0["version"]: _RULE_PACKAGE_V1_1_0,
    _RULE_PACKAGE_V1_1_1["version"]: _RULE_PACKAGE_V1_1_1,
    _RULE_PACKAGE_V1_1_2["version"]: _RULE_PACKAGE_V1_1_2,
    _RULE_PACKAGE_V1_1_3["version"]: _RULE_PACKAGE_V1_1_3,
    _RULE_PACKAGE_V1_1_4["version"]: _RULE_PACKAGE_V1_1_4,
    _RULE_PACKAGE_V1_1_5["version"]: _RULE_PACKAGE_V1_1_5,
    _RULE_PACKAGE_V1_1_6["version"]: _RULE_PACKAGE_V1_1_6,
    _RULE_PACKAGE_V1_1_7["version"]: _RULE_PACKAGE_V1_1_7,
    _RULE_PACKAGE_V1_1_8["version"]: _RULE_PACKAGE_V1_1_8,
    _RULE_PACKAGE_V1_1_9["version"]: _RULE_PACKAGE_V1_1_9,
    _RULE_PACKAGE_V1_2_0["version"]: _RULE_PACKAGE_V1_2_0,
    _RULE_PACKAGE_V1_2_1["version"]: _RULE_PACKAGE_V1_2_1,
    _RULE_PACKAGE_V1_2_2["version"]: _RULE_PACKAGE_V1_2_2,
    _RULE_PACKAGE_V1_2_3["version"]: _RULE_PACKAGE_V1_2_3,
    _RULE_PACKAGE_V1_2_4["version"]: _RULE_PACKAGE_V1_2_4,
    _RULE_PACKAGE_V1_2_5["version"]: _RULE_PACKAGE_V1_2_5,
    _RULE_PACKAGE_V1_2_6["version"]: _RULE_PACKAGE_V1_2_6,
    _RULE_PACKAGE_V1_3_0["version"]: _RULE_PACKAGE_V1_3_0,
    _RULE_PACKAGE_V1_3_1["version"]: _RULE_PACKAGE_V1_3_1,
    _RULE_PACKAGE_V1_3_2["version"]: _RULE_PACKAGE_V1_3_2,
    _RULE_PACKAGE["version"]: _RULE_PACKAGE,
}


def get_rule_package(version: str = "") -> Dict[str, Any]:
    """Return an immutable rule package version, defaulting to the current package."""
    selected_version = version or _RULE_PACKAGE["version"]
    if selected_version not in _RULE_PACKAGE_VERSIONS:
        raise KeyError(selected_version)
    package = deepcopy(_RULE_PACKAGE_VERSIONS[selected_version])
    package["available_versions"] = deepcopy(_RULE_PACKAGE["version_history"])
    return package

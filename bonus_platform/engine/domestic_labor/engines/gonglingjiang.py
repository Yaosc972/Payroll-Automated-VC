"""工龄奖计算引擎 (Seniority Bonus Engine)."""
from datetime import date, datetime
from typing import Any, Dict, List
from .base import BaseEngine, CalculationResult


# ==================== 莞深广珠区域 ====================
# 部门映射
DEPARTMENT_MAP_GSDG = {
    "中国操作部": "操作",
    "第四纵队": "揽收",
    "头程运营部": "FBU",
}

# 操作部岗位名单
OPERATION_POSITIONS_GSDG = {
    "内勤专员", "中转员", "门禁员", "操作员", "监察员",
    "安检员", "操作文员", "查验员", "叉车司机", "揽收充电司机",
}

# 工龄奖上限
SENIORITY_CAP_GSDG = {
    "操作": 600,
    "揽收": 600,
    "FBU": 500,
}

# 工龄奖标准（每年）
SENIORITY_RATE_GSDG = {
    "操作": 150,
    "揽收": 150,
    "FBU": 100,
}

# ==================== 华西华东东南区域 ====================
# 部门映射
DEPARTMENT_MAP_WES = {
    "华东枢纽": "操作",
    "华东揽收组": "揽收",
    "东南枢纽": "操作",
    "华西区操作部": "操作",
    "闽赣揽收组": "揽收",
    "华东B2B枢纽": "操作",
}

# 操作部岗位名单（华西华东东南）
OPERATION_POSITIONS_WES = {
    "操作员", "内勤专员", "中转员", "门禁员", "安检员", "操作文员",
}

# 揽收部岗位名单（华西华东东南）
COLLECTION_POSITIONS_WES = {
    "揽收操作员", "内勤专员",
}

# 无工龄奖的岗位（组长类、非一线）
NO_BONUS_POSITIONS_WES = {
    "操作组长", "见习组长", "HRBP专员", "揽收组长",
    "操作副主管", "操作主管", "操作经理",
}

# 工龄奖上限（华西华东东南统一）
SENIORITY_CAP_WES = 150

# 工龄奖标准（每年，华西华东东南统一）
SENIORITY_RATE_WES = 50

# ==================== 兼容旧代码（莞深广珠默认） ====================
DEPARTMENT_MAP = DEPARTMENT_MAP_GSDG
OPERATION_POSITIONS = OPERATION_POSITIONS_GSDG
SENIORITY_CAP = SENIORITY_CAP_GSDG
SENIORITY_RATE = SENIORITY_RATE_GSDG


class GongLingJiangEngine(BaseEngine):
    """工龄奖计算引擎"""

    def __init__(self):
        pass

    def calculate(
        self,
        employee_data: Dict[str, Any],
        hrbp_list: List[str] = None,
        region_cap: float = None,
        region: str = None,
    ) -> CalculationResult:
        """计算单个员工的工龄奖

        Args:
            employee_data: 月考勤数据
            hrbp_list: 揽收部HRBP发放名单（工号列表）
            region: 区域 ('gsdg'=莞深广珠, 'wes'=华西华东东南, None=自动检测)
        """
        employee_id = str(employee_data.get("工号", ""))
        employee_name = str(employee_data.get("姓名", ""))
        warnings = []

        # F1: 归属部门大类（自动检测区域或使用指定区域）
        department = str(employee_data.get("二级部门名称", ""))
        position = str(employee_data.get("岗位名称", ""))

        if region == "wes":
            # 华西华东东南区域
            dept_category = DEPARTMENT_MAP_WES.get(department, "其他")
            standard = 0
            cap = SENIORITY_CAP_WES

            if dept_category == "操作":
                if position in OPERATION_POSITIONS_WES:
                    standard = SENIORITY_RATE_WES
            elif dept_category == "揽收":
                if position in COLLECTION_POSITIONS_WES:
                    standard = SENIORITY_RATE_WES
            elif dept_category == "其他":
                # HRBP部、共享运营中心等无工龄奖
                pass

            # 检查是否为无工龄奖岗位
            if position in NO_BONUS_POSITIONS_WES:
                standard = 0
                if dept_category != "其他":
                    warnings.append(f"员工{employee_id}岗位{position}为组长/非一线，无工龄奖")

        else:
            # 莞深广珠区域（默认）
            dept_category = DEPARTMENT_MAP_GSDG.get(department, "其他")
            standard = 0

            if dept_category == "操作":
                if position in OPERATION_POSITIONS_GSDG:
                    standard = SENIORITY_RATE_GSDG["操作"]
            elif dept_category == "揽收":
                if hrbp_list and employee_id in hrbp_list and "组长" not in position:
                    standard = SENIORITY_RATE_GSDG["揽收"]
                else:
                    if not hrbp_list:
                        warnings.append(f"员工{employee_id}为揽收部人员，请提供本月HRBP发放名单")
            elif dept_category == "FBU":
                standard = SENIORITY_RATE_GSDG["FBU"]

            cap = region_cap if region_cap is not None else SENIORITY_CAP_GSDG.get(dept_category, 0)

        if dept_category == "其他":
            return CalculationResult(
                employee_id=employee_id,
                employee_name=employee_name,
                amount=0,
                details={"reason": "部门不在工龄奖范围", "department": department},
                warnings=[]
            )

        if standard == 0:
            return CalculationResult(
                employee_id=employee_id,
                employee_name=employee_name,
                amount=0,
                details={"reason": "不符合工龄奖标准", "department": dept_category, "position": position},
                warnings=warnings
            )

        # F2.5: 检查备注异常
        remark = str(employee_data.get("备注", "") or "")
        remark_keywords = ["事假未出勤", "全月事假", "事假全月", "未出勤"]
        if any(kw in remark for kw in remark_keywords):
            warnings.append(f"⚠️ 员工{employee_id}({employee_name})备注'{remark}'，需人工确认是否发放工龄奖")

        # F3: 工龄（司龄）
        hire_date = employee_data.get("入职日期")
        if not isinstance(hire_date, date):
            return CalculationResult(
                employee_id=employee_id,
                employee_name=employee_name,
                amount=0,
                details={"reason": "入职日期异常"},
                warnings=[f"员工{employee_id}入职日期异常"]
            )

        # 假设发放月为当月1日
        attendance_month = str(employee_data.get("考勤月份", ""))
        if len(attendance_month) == 6:
            year = int(attendance_month[:4])
            month = int(attendance_month[4:])
            ref_date = date(year, month, 1)
        else:
            ref_date = date.today().replace(day=1)

        years = ref_date.year - hire_date.year
        if (ref_date.month, ref_date.day) < (hire_date.month, hire_date.day):
            years -= 1
        years = max(years, 0)

        if years == 0:
            return CalculationResult(
                employee_id=employee_id,
                employee_name=employee_name,
                amount=0,
                details={"reason": "入职不足1年", "years": 0},
                warnings=[]
            )

        # F5: 应发工龄奖
        yingfa = min(standard * years, cap)

        # F6: 请假时数（事假+病假+旷工+排休，小时）— 对应月报"请假时数"列
        spk_hours = float(employee_data.get("请假时数", 0) or 0)
        # 如果没有请假时数字段，回退到单独计算
        if spk_hours == 0:
            spk_hours = (
                float(employee_data.get("事假时数", 0) or 0)
                + float(employee_data.get("病假时数", 0) or 0)
                + float(employee_data.get("旷工时数", 0) or 0)
                + float(employee_data.get("排休请假天数", 0) or 0)
            )

        # F7: 排班天数
        paiban = float(employee_data.get("排班天数", 0) or 0)
        if paiban == 0:
            return CalculationResult(
                employee_id=employee_id,
                employee_name=employee_name,
                amount=0,
                details={"reason": "排班天数为0"},
                warnings=[f"员工{employee_id}排班天数为0，无法折算"]
            )

        # F8: 入离职缺勤时数
        actual_days = float(employee_data.get("实际在职工作日天数", 0) or 0)
        ruli_hours = (paiban - actual_days) * 8

        # F9: 最终工龄奖
        day_rate = yingfa / paiban
        after_spk = day_rate * (paiban - spk_hours / 8) if spk_hours >= 56 else yingfa
        after_ruli = after_spk - day_rate * (ruli_hours / 8)
        # 允许负数（表示需从工资中扣除）
        final = round(min(after_ruli, cap), 2)

        return CalculationResult(
            employee_id=employee_id,
            employee_name=employee_name,
            amount=final,
            details={
                "部门类别": dept_category,
                "岗位": position,
                "工龄(年)": years,
                "标准": standard,
                "上限": cap,
                "应发": yingfa,
                "事病旷排休时数": spk_hours,
                "入离职缺勤时数": ruli_hours,
                "最终金额": final,
            },
            warnings=warnings
        )

    def calculate_batch(
        self,
        employees: List[Dict[str, Any]],
        hrbp_list: List[str] = None,
        region_cap: float = None,
        region: str = None,
    ) -> List[CalculationResult]:
        """批量计算工龄奖"""
        return [self.calculate(emp, hrbp_list, region_cap, region) for emp in employees]

    def verify(self, results: List[CalculationResult]) -> Dict[str, Any]:
        """验证计算结果"""
        total = len(results)
        has_bonus = sum(1 for r in results if r.amount > 0)
        total_amount = sum(r.amount for r in results)
        all_warnings = [w for r in results for w in r.warnings]

        return {
            "总人数": total,
            "有工龄奖人数": has_bonus,
            "工龄奖合计金额": total_amount,
            "警告": all_warnings,
        }

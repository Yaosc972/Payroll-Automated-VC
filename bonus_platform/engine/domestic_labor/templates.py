"""Excel模板生成器 - 为每个计算引擎生成带说明和示例的模板"""
from pathlib import Path
from typing import Dict, List, Any
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

# 样式定义
HEADER_FILL = PatternFill(start_color="1a1a2e", end_color="1a1a2e", fill_type="solid")
HEADER_FONT = Font(name="微软雅黑", size=11, bold=True, color="FFFFFF")
REQUIRED_FILL = PatternFill(start_color="FFF3E0", end_color="FFF3E0", fill_type="solid")
OPTIONAL_FILL = PatternFill(start_color="F5F5F5", end_color="F5F5F5", fill_type="solid")
DESC_FONT = Font(name="微软雅黑", size=10, color="888888", italic=True)
EXAMPLE_FONT = Font(name="微软雅黑", size=10, color="4CAF50")
NORMAL_FONT = Font(name="微软雅黑", size=10)
THIN_BORDER = Border(
    left=Side(style="thin", color="DDDDDD"),
    right=Side(style="thin", color="DDDDDD"),
    top=Side(style="thin", color="DDDDDD"),
    bottom=Side(style="thin", color="DDDDDD"),
)

# 引擎模板定义
ENGINE_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "quanqinjiang": {
        "name": "全勤奖计算模板",
        "description": "用于计算员工全勤奖（100元/人/月）",
        "columns": [
            {"name": "工号", "desc": "员工工号，如 OWHN2313", "required": True, "example": "OWHN2313"},
            {"name": "姓名", "desc": "员工姓名", "required": True, "example": "何俊伟"},
            {"name": "考勤月份", "desc": "格式YYYYMM，如202603", "required": True, "example": "202603"},
            {"name": "入职日期", "desc": "格式YYYY-MM-DD", "required": True, "example": "2023-05-15"},
            {"name": "最后工作日", "desc": "在职员工留空，离职员工填写日期", "required": False, "example": ""},
            {"name": "旷工天数", "desc": "默认0", "required": False, "example": "0"},
            {"name": "正班迟到次数", "desc": "默认0", "required": False, "example": "0"},
            {"name": "早退次数", "desc": "默认0", "required": False, "example": "0"},
            {"name": "签卡次数", "desc": "默认0", "required": False, "example": "0"},
            {"name": "工伤假天数", "desc": "默认0", "required": False, "example": "0"},
            {"name": "事假时数", "desc": "事假总时数（小时）", "required": False, "example": "0"},
            {"name": "病假时数", "desc": "病假总时数（小时）", "required": False, "example": "0"},
            {"name": "入离职缺勤时数", "desc": "因入离职导致的缺勤时数", "required": False, "example": "0"},
            {"name": "迟到早退30分钟内扣款", "desc": "有扣款>0则不享全勤奖", "required": False, "example": "0"},
        ],
        "example_extra": [
            {"工号": "OWHN0424", "姓名": "韩录阳", "考勤月份": "202603", "入职日期": "2021-08-10",
             "最后工作日": "", "旷工天数": "0", "正班迟到次数": "0", "早退次数": "0", "签卡次数": "0",
             "工伤假天数": "0", "事假时数": "0", "病假时数": "0", "入离职缺勤时数": "0", "迟到早退30分钟内扣款": "0"},
        ],
    },
    "canbu": {
        "name": "餐补计算模板",
        "description": "用于计算员工餐补（按工作地区、部门、岗位适用平台规则）",
        "columns": [
            {"name": "工号", "desc": "员工工号", "required": True, "example": "OWHN2313"},
            {"name": "姓名", "desc": "员工姓名", "required": True, "example": "何俊伟"},
            {"name": "工作地区", "desc": "东莞/嘉善/义乌/晋江；按地区适用平台规则", "required": True, "example": "东莞"},
            {"name": "一级部门名称", "desc": "东莞需命中寮步区或莞深操作", "required": True, "example": "莞深操作"},
            {"name": "岗位名称", "desc": "用于判断是否享有餐补", "required": True, "example": "操作员"},
            {"name": "餐补标准", "desc": "历史字段，当前不作为发放资格入口", "required": False, "example": ""},
            {"name": "出勤天数", "desc": "历史字段，东莞按日考勤工作状态和时数逐日计算", "required": False, "example": "22"},
            {"name": "正班时数合计", "desc": "历史字段，东莞按日考勤逐日计算", "required": False, "example": "176"},
            {"name": "排班天数", "desc": "嘉善/义乌餐补月报折算分母", "required": False, "example": "22"},
            {"name": "实际在职工作日天数", "desc": "嘉善/义乌餐补月报折算基础天数", "required": False, "example": "22"},
            {"name": "事假时数", "desc": "嘉善/义乌按事假时数/8折算扣减", "required": False, "example": "0"},
            {"name": "病假时数", "desc": "嘉善/义乌按病假时数/8后40%扣减", "required": False, "example": "0"},
            {"name": "旷工天数", "desc": "嘉善/义乌按旷工天数扣减", "required": False, "example": "0"},
        ],
        "example_extra": [
            {"工号": "OWHN0424", "姓名": "韩录阳", "工作地区": "东莞", "一级部门名称": "莞深操作",
             "岗位名称": "操作员", "餐补标准": "", "出勤天数": "22", "正班时数合计": "176"},
        ],
    },
    "waisu_butie": {
        "name": "外宿补贴计算模板",
        "description": "用于计算员工外宿/住宿补贴（150元/月）",
        "columns": [
            {"name": "工号", "desc": "员工工号", "required": True, "example": "OWHN2313"},
            {"name": "姓名", "desc": "员工姓名", "required": True, "example": "何俊伟"},
            {"name": "考勤月份", "desc": "格式YYYYMM", "required": True, "example": "202603"},
            {"name": "外宿补贴标准", "desc": "150或'/'(不享有)", "required": True, "example": "150"},
            {"name": "入职日期", "desc": "格式YYYY-MM-DD", "required": True, "example": "2023-05-15"},
            {"name": "最后工作日", "desc": "在职留空", "required": False, "example": ""},
            {"name": "事假时数", "desc": "小时", "required": False, "example": "0"},
            {"name": "病假时数", "desc": "小时", "required": False, "example": "0"},
            {"name": "旷工时数", "desc": "小时", "required": False, "example": "0"},
            {"name": "排休请假时数", "desc": "小时", "required": False, "example": "0"},
            {"name": "入离职缺勤时数", "desc": "小时", "required": False, "example": "0"},
        ],
        "example_extra": [
            {"工号": "OWHN0424", "姓名": "韩录阳", "考勤月份": "202603", "外宿补贴标准": "150",
             "入职日期": "2021-08-10", "最后工作日": "", "事假时数": "0", "病假时数": "0",
             "旷工时数": "0", "排休请假时数": "0", "入离职缺勤时数": "0"},
        ],
    },
    "gonglingjiang": {
        "name": "工龄奖计算模板",
        "description": "用于计算员工工龄奖（按工龄×标准，有上限）",
        "columns": [
            {"name": "工号", "desc": "员工工号", "required": True, "example": "OWHN2313"},
            {"name": "姓名", "desc": "员工姓名", "required": True, "example": "何俊伟"},
            {"name": "二级部门名称", "desc": "决定部门类别（操作/揽收/FBU）", "required": True, "example": "中国操作部"},
            {"name": "岗位名称", "desc": "决定是否有工龄奖资格", "required": True, "example": "操作员"},
            {"name": "入职日期", "desc": "格式YYYY-MM-DD", "required": True, "example": "2023-05-15"},
            {"name": "考勤月份", "desc": "格式YYYYMM", "required": True, "example": "202603"},
            {"name": "请假时数", "desc": "事假+病假+旷工+排休（小时）", "required": False, "example": "0"},
            {"name": "排班天数", "desc": "当月排班天数", "required": True, "example": "26"},
            {"name": "实际在职工作日天数", "desc": "用于折算入离职缺勤", "required": False, "example": "26"},
            {"name": "备注", "desc": "如有特殊备注（如全月事假）", "required": False, "example": ""},
        ],
        "example_extra": [
            {"工号": "OWHN0424", "姓名": "韩录阳", "二级部门名称": "中国操作部", "岗位名称": "操作员",
             "入职日期": "2021-08-10", "考勤月份": "202603", "请假时数": "0", "排班天数": "26",
             "实际在职工作日天数": "26", "备注": ""},
        ],
    },
}


def generate_template(engine_key: str) -> bytes:
    """生成指定引擎的Excel模板，返回文件字节流"""
    if engine_key not in ENGINE_TEMPLATES:
        raise ValueError(f"未知引擎: {engine_key}，可选: {list(ENGINE_TEMPLATES.keys())}")

    template = ENGINE_TEMPLATES[engine_key]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = template["name"]

    columns = template["columns"]

    # 第1行：表头
    for col_idx, col in enumerate(columns, 1):
        cell = ws.cell(row=1, column=col_idx, value=col["name"])
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = THIN_BORDER

    # 第2行：列说明
    for col_idx, col in enumerate(columns, 1):
        cell = ws.cell(row=2, column=col_idx, value=col["desc"])
        cell.font = DESC_FONT
        cell.fill = REQUIRED_FILL if col["required"] else OPTIONAL_FILL
        cell.alignment = Alignment(wrap_text=True, vertical="center")
        cell.border = THIN_BORDER

    # 第3行起：示例数据
    for row_idx, row_data in enumerate(template.get("example_extra", []), 3):
        for col_idx, col in enumerate(columns, 1):
            val = row_data.get(col["name"], "")
            cell = ws.cell(row=row_idx, column=col_idx, value=val)
            cell.font = EXAMPLE_FONT
            cell.border = THIN_BORDER

    # 列宽自适应
    for col_idx, col in enumerate(columns, 1):
        max_len = max(len(col["name"]), len(col["desc"]) // 2, 12)
        ws.column_dimensions[openpyxl.utils.get_column_letter(col_idx)].width = min(max_len + 4, 30)

    # 冻结表头
    ws.freeze_panes = "A3"

    # 保存到字节流
    from io import BytesIO
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return output.getvalue()


def get_template_info(engine_key: str) -> Dict[str, Any]:
    """获取模板信息（不生成文件）"""
    if engine_key not in ENGINE_TEMPLATES:
        raise ValueError(f"未知引擎: {engine_key}")
    template = ENGINE_TEMPLATES[engine_key]
    return {
        "engine": engine_key,
        "name": template["name"],
        "description": template["description"],
        "columns": [
            {"name": c["name"], "desc": c["desc"], "required": c["required"]}
            for c in template["columns"]
        ],
    }

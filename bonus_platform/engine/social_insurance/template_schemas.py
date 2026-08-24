from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy
from datetime import datetime
import re
from typing import Any


def _field(
    name: str,
    *,
    header: str | None = None,
    required: bool = False,
    control: str = "text",
    options: Iterable[str] = (),
    note: str = "",
) -> dict[str, Any]:
    return {
        "name": name,
        "label": name,
        "header": header or name,
        "required": required,
        "control": control,
        "options": tuple(options),
        "note": note,
    }


SHENZHEN_FIELDS = (
    _field("证件号码", required=True, note="北森证件号码"),
    _field("姓名", required=True, note="北森员工姓名"),
    _field("户籍", required=True, control="select", options=("深圳户籍", "广东省内非深户", "广东省外户籍"), note="按户籍所在地映射"),
    _field("入深户时间", control="date", note="深圳户籍人员按模板格式填写"),
    _field("民族", required=True, note="北森民族"),
    _field("手机号码", required=True, note="员工本人手机号"),
    _field("通讯地址", required=True, note="北森现居住地址"),
    _field("电脑号", note="已有深圳社保账户时填写"),
    _field("岗位类别", required=True, control="select", options=("工人岗位", "管理(技术)岗位"), note="按个人身份映射"),
    _field("个人身份", required=True, control="select", options=("干部", "工人"), note="按学历规则映射"),
    _field("用工形式", required=True, control="select", options=("全民工", "合同工", "劳务工", "临时工", "集体工"), note="按雇佣关系映射"),
    _field("学历", required=True, note="映射为政务模板学历"),
    _field("职称", required=True, note="没有职称时填无"),
    _field("国家职业资格或职业技能等级", required=True, note="没有职业资格时填无"),
    _field("医疗缴费档次", required=True, control="select", options=("职工一档", "职工二档"), note="按户籍规则生成"),
    _field("部门名称", note="模板允许为空"),
    _field("户籍地类别", required=True, control="select", options=("农业", "非农业", "居民户"), note="按户口类别映射"),
    _field("户口所在地行政区划代码", required=True, control="adminDivision", note="从模板区县字典选择"),
    _field("就业形式", required=True, control="select", options=("雇佣就业", "派遣就业"), note="按雇佣关系映射"),
    _field("就业前身份", required=True, note="未提供时需业务确认"),
)


GUANGDONG_SOCIAL_FIELDS = (
    _field("变动类型", required=True, control="select", options=("1|增员",), note="本流程固定为增员"),
    _field("变动原因", required=True, control="select", options=("11|新参保", "12|恢复缴费", "400|其它"), note="默认新参保，已有账户时确认是否恢复缴费"),
    _field("个人社保号", note="已有社保账户时填写"),
    _field("证件类型", header="证件类型", required=True, control="select", options=("201|居民身份证", "208|外国护照", "210|港澳居民来往内地通行证", "213|台湾居民来往大陆通行证")),
    _field("证件号码", required=True),
    _field("姓名", required=True),
    _field("性别", required=True, control="select", options=("1|男", "2|女")),
    _field("国籍（地区籍）", required=True, note="居民身份证默认中华人民共和国"),
    _field("工资薪金", required=True, note="取社保缴交基数"),
    _field("出生日期", required=True, control="date", note="居民身份证自动解析"),
    _field("人员类别", required=True, note="按个人身份映射"),
    _field("人员状态", required=True, note="在职人员默认在职"),
    _field("用工形式", required=True, note="按雇佣关系映射"),
    _field("户籍类型", required=True, note="按户籍地与城乡类别映射"),
    _field("实际参保年月", required=True, note="按本次参保日期生成"),
    _field("手机号码", required=True),
)


DONGGUAN_FIELDS = (*GUANGDONG_SOCIAL_FIELDS,
    _field("企业基本养老保险", required=True, control="select", options=("1|参保", "0|不参保")),
    _field("工伤保险", required=True, control="select", options=("1|参保", "0|不参保")),
    _field("失业保险", required=True, control="select", options=("1|参保", "0|不参保")),
    _field("S1-单建统筹职工医保（含生育）", required=True, control="select", options=("1|参保", "0|不参保")),
)


GUANGZHOU_FIELDS = (*GUANGDONG_SOCIAL_FIELDS,
    _field("基本养老保险", required=True, control="select", options=("1|参保", "0|不参保")),
    _field("工伤保险", required=True, control="select", options=("1|参保", "0|不参保")),
    _field("失业保险", required=True, control="select", options=("1|参保", "0|不参保")),
    _field("基本医疗保险（含生育）", required=True, control="select", options=("1|参保", "0|不参保")),
)


ZHEJIANG_FIELDS = (
    _field("证件号码", header="证件号码（必填）", required=True),
    _field("姓名", header="姓名（必填）", required=True),
    _field("手机号码", header="手机号码（必填）", required=True),
    _field("户籍性质", header="户籍性质（必填）", required=True, note="按户籍地与城乡类别映射"),
    _field("户籍地址", header="户籍地址（必填）", required=True),
    _field("民族", header="民族 "),
    _field("联系地址-社保", header="联系地址-社保（必填）", required=True),
    _field("本次参保日期-社保", header="本次参保日期-社保(yyyy-MM-dd)(yyyy-MM-dd)（必填）", required=True, control="date"),
    _field("参保身份-社保", header="参保身份-社保（必填）", required=True, note="内部员工默认企业职工"),
    _field("用工形式-社保", note="按雇佣关系映射"),
    _field("联系电话-社保"),
    _field("邮政编码-社保", note="北森缺失时人工补充"),
    _field("是否补缴-医保", header="是否补缴-医保（必填）", required=True, control="select", options=("否", "是")),
    _field("常量-医保"),
    _field("补缴开始年月-医保", header="补缴开始年月-医保(yyyy-MM-dd)(yyyy-MM-dd)", control="date"),
    _field("补缴结束年月-医保", header="补缴结束年月-医保(yyyy-MM-dd)(yyyy-MM-dd)", control="date"),
    _field("本次参保日期-医保", header="本次参保日期-医保(yyyy-MM-dd)(yyyy-MM-dd)（必填）", required=True, control="date"),
    _field("学历", header=" 学历（必填）", required=True),
    _field("申报工资", note="取社保缴交基数"),
    _field("职工证件类型", note="居民身份证自动识别"),
    _field("实际工作单位统一社会信用代码", note="劳务派遣人员必填"),
)


CHENGDU_SOCIAL_FIELDS = (
    _field("姓名", required=True),
    _field("身份证号码", required=True),
    _field("文化程度", required=True),
    _field("参保时间", required=True, control="date"),
    _field("移动电话", required=True),
    _field("民族", required=True),
    _field("岗位性质", header="岗位性质(可为空)"),
    _field("二级单位编号", header="二级单位编号(可为空)"),
    _field("实际工作单位名称", header="实际工作单位名称(非劳务派遣单位可为空)"),
    _field("实际工作单位统一社会信用代码", header="实际工作单位统一社会信用代码(非劳务派遣单位可为空)"),
    _field("毕业年度", header="毕业年度(格式为YYYY可为空)"),
    _field("毕业院校地域类别", header="毕业院校地域类别(可为空)"),
)


CHENGDU_MEDICAL_FIELDS = (
    _field("姓名", required=True), _field("别名"),
    _field("证件类型", required=True), _field("证件号码", required=True),
    _field("性别", required=True), _field("出生日期", required=True, control="date"),
    _field("手机号码", required=True), _field("民族", required=True),
    _field("首次参加工作日期", control="date", note="优先从北森补充；缺失时业务确认"),
    _field("户口地址", required=True), _field("居住地址", required=True),
    _field("人员类型", required=True), _field("电子邮箱"), _field("政治面貌"),
    _field("户口性质", required=True), _field("户口所在地邮编"), _field("居住地邮编"),
    _field("婚姻状况"), _field("备注"), _field("学历", required=True),
    _field("用工形式", required=True), _field("编制类型"),
)


ZHENGZHOU_MEDICAL_FIELDS = (
    _field("姓名", header="姓名（必填）", required=True),
    _field("证件类型", header="证件类型（必填）", required=True),
    _field("证件号码", header="证件号码（必填）", required=True),
    _field("民族", header="民族（必填）", required=True),
    _field("参加工作日期", header="参加工作日期(格式:yyyy-MM-dd)", control="date"),
    _field("联系移动电话", header="联系移动电话（必填）", required=True),
    _field("户口地址", header="户口地址（必填）", required=True),
    _field("居住地地址", header="居住地地址（必填）", required=True),
    _field("户口性质"), _field("常住地详址"),
    _field("户口所在地行政区", header="户口所在地行政区(如360402 庐山区)"),
    _field("居住地行政区", header="居住地行政区(如360402 庐山区)"),
    _field("联系固定电话", header="联系固定电话(格式:xxx-xxxxxxxx)"),
    _field("常住地邮政编码"), _field("所属下级单位"),
)


WUHAN_MEDICAL_FIELDS = (
    _field("证件类型", required=True), _field("证件号码", required=True),
    _field("姓名", required=True), _field("性别", required=True), _field("民族", required=True),
    _field("出生日期", required=True, control="date"), _field("国家地区代码", required=True),
    _field("编制类型", required=True), _field("本次参保日期", required=True, control="date"),
    _field("手机号码", required=True),
)


TEMPLATE_SCHEMAS: dict[str, dict[str, Any]] = {
    "shenzhen-social-medical": {
        "route": "shenzhen-social-medical", "label": "深圳社保医保合并模板", "city": "深圳",
        "sheet": "人员参保登记报盘模板", "headerRow": 2, "dataStartRow": 4, "fields": SHENZHEN_FIELDS,
    },
    "dongguan-social": {
        "route": "dongguan-social", "label": "东莞社保医保模板", "city": "东莞",
        "sheet": "Sheet1", "headerRow": 5, "dataStartRow": 6, "fields": DONGGUAN_FIELDS,
    },
    "guangzhou-social": {
        "route": "guangzhou-social", "label": "广州社保医保模板", "city": "广州",
        "sheet": "Sheet1", "headerRow": 5, "dataStartRow": 6, "fields": GUANGZHOU_FIELDS,
    },
    "zhejiang-social-medical": {
        "route": "zhejiang-social-medical", "label": "浙江社保医保合并模板", "city": "浙江",
        "sheet": "sheet1", "headerRow": 1, "dataStartRow": 3, "fields": ZHEJIANG_FIELDS,
    },
    "chengdu-social": {
        "route": "chengdu-social", "label": "成都社保模板", "city": "成都",
        "sheet": "Sheet1", "headerRow": 1, "dataStartRow": 2, "fields": CHENGDU_SOCIAL_FIELDS,
    },
    "chengdu-medical": {
        "route": "chengdu-medical", "label": "成都医保模板", "city": "成都",
        "sheet": "Sheet1", "headerRow": 1, "dataStartRow": 2, "fields": CHENGDU_MEDICAL_FIELDS,
    },
    "zhengzhou-medical": {
        "route": "zhengzhou-medical", "label": "郑州医保模板", "city": "郑州",
        "sheet": "sheet1", "headerRow": 1, "dataStartRow": 2, "fields": ZHENGZHOU_MEDICAL_FIELDS,
    },
    "wuhan-medical": {
        "route": "wuhan-medical", "label": "武汉医保模板", "city": "武汉",
        "sheet": "职工批量增员申报", "headerRow": 1, "dataStartRow": 2, "fields": WUHAN_MEDICAL_FIELDS,
    },
}


def public_template_schemas() -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for schema in TEMPLATE_SCHEMAS.values():
        public_fields = []
        for field in schema["fields"]:
            item = deepcopy(field)
            item["options"] = list(item.get("options") or ())
            public_fields.append(item)
        output.append({key: deepcopy(value) for key, value in schema.items() if key != "fields"} | {"fields": public_fields})
    return output


def schema_for_route(route: str) -> dict[str, Any] | None:
    return TEMPLATE_SCHEMAS.get(str(route or "").strip())


def employee_template_routes(employee: dict[str, Any]) -> list[str]:
    routes: list[str] = []
    tasks = employee.get("coverageTasks") if isinstance(employee.get("coverageTasks"), dict) else {}
    for coverage in ("social", "medical"):
        task = tasks.get(coverage) if isinstance(tasks.get(coverage), dict) else {}
        route = str(task.get("route") or "").strip()
        if task.get("handling") == "template" and route in TEMPLATE_SCHEMAS and route not in routes:
            routes.append(route)
    return routes


def _identity_facts(value: str) -> dict[str, str]:
    identity = re.sub(r"\s+", "", str(value or "")).upper()
    facts = {"type": "", "birthDate": "", "gender": "", "nationality": ""}
    if re.fullmatch(r"\d{17}[0-9X]", identity):
        try:
            birth = datetime.strptime(identity[6:14], "%Y%m%d")
        except ValueError:
            return facts
        facts.update({
            "type": "居民身份证",
            "birthDate": birth.strftime("%Y-%m-%d"),
            "gender": "男" if int(identity[16]) % 2 else "女",
            "nationality": "中华人民共和国",
        })
    return facts


def _education(value: str, route: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if "博士" in raw:
        return "11 博士研究生" if route == "chengdu-social" else "博士研究生"
    if "硕士" in raw:
        return "14 硕士研究生" if route == "chengdu-social" else "硕士研究生"
    if "本科" in raw or "学士" in raw:
        return "21 大学本科" if route == "chengdu-social" else "大学本科"
    if "专科" in raw or "副学士" in raw:
        return "31 大学专科" if route == "chengdu-social" else "大学专科"
    if "高中" in raw:
        return "61 高中" if route == "chengdu-social" else "高中"
    return raw


def _nation(value: str, route: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if route == "chengdu-social" and "汉" in raw:
        return "01 汉族"
    return raw


def _household_kind(employee: dict[str, Any], route: str) -> str:
    source = employee.get("source") if isinstance(employee.get("source"), dict) else {}
    report = employee.get("report") if isinstance(employee.get("report"), dict) else {}
    domicile = str(source.get("domicileType") or report.get("户籍地类别") or "").strip()
    household = str(report.get("户口具体地址") or source.get("birthplace") or "").strip()
    rural = any(marker in domicile for marker in ("农村", "农业"))
    if route == "zhejiang-social-medical":
        local = "浙江" in household
        return f"{'省内' if local else '省外'}{'农村' if rural else '居民'}户口"
    if route == "dongguan-social":
        if "东莞" in household:
            return "04|本地农业户口" if rural else "03|本地非农业户口"
        if "广东" in household:
            return "12|广东省内市外农业" if rural else "11|广东省内市外城镇"
        return "14|广东省外农业" if rural else "13|广东省外城镇"
    if route == "guangzhou-social":
        if "广州" in household:
            return "04|本地农业户口" if rural else "03|本地非农业户口"
        return "06|外地农业户口" if rural else "05|外地非农业户口"
    return domicile


def _supplement_task(employee: dict[str, Any]) -> dict[str, Any]:
    tasks = employee.get("coverageTasks") if isinstance(employee.get("coverageTasks"), dict) else {}
    medical = tasks.get("medical") if isinstance(tasks.get("medical"), dict) else {}
    return medical if medical.get("status") == "supplement" else {}


def _mapped_value(name: str, employee: dict[str, Any], run: dict[str, Any], route: str) -> tuple[str, str]:
    report = employee.get("report") if isinstance(employee.get("report"), dict) else {}
    source = employee.get("source") if isinstance(employee.get("source"), dict) else {}
    identity = str(report.get("证件号码") or "")
    facts = _identity_facts(identity)
    entry_date = str(employee.get("entryDate") or "").strip()
    social_base = str(report.get("社保缴交基数") or source.get("socialContributionBase") or "").strip()
    household_address = str(report.get("户口具体地址") or source.get("householdAddress") or source.get("birthplace") or "").strip()
    current_address = str(source.get("currentAddress") or report.get("通讯地址") or "").strip()
    mobile = str(report.get("手机号码") or source.get("mobile") or "").strip()
    gender = str(source.get("gender") or facts["gender"]).strip()
    mapped_gender = gender
    if route in {"dongguan-social", "guangzhou-social"}:
        mapped_gender = {"男": "1|男", "女": "2|女"}.get(gender, gender)
    nation = str(source.get("nation") or report.get("民族") or "").strip()
    education = str(source.get("education") or report.get("学历") or "").strip()
    supplement = _supplement_task(employee)

    if route == "shenzhen-social-medical" and name in report:
        origin = "北森/规则映射" if report.get(name) else "待补充"
        return str(report.get(name) or ""), origin
    direct: dict[str, tuple[str, str]] = {
        "姓名": (str(report.get("姓名") or ""), "北森"),
        "证件号码": (identity, "北森"), "身份证号码": (identity, "北森"),
        "手机号码": (mobile, "北森"), "移动电话": (mobile, "北森"), "联系移动电话": (mobile, "北森"),
        "户口地址": (household_address, "北森"), "户籍地址": (household_address, "北森"),
        "居住地址": (current_address, "北森"), "居住地地址": (current_address, "北森"),
        "联系地址-社保": (current_address, "北森"), "常住地详址": (current_address, "北森"),
        "电子邮箱": (str(source.get("email") or ""), "北森"),
        "民族": (_nation(nation, route), "北森/枚举映射"),
        "性别": (mapped_gender, "北森/枚举映射" if mapped_gender != gender else "北森"),
        "出生日期": (str(source.get("birthDate") or facts["birthDate"]), "北森" if source.get("birthDate") else "身份证解析"),
        "首次参加工作日期": (str(source.get("firstWorkDate") or ""), "北森" if source.get("firstWorkDate") else "待补充"),
        "参加工作日期": (str(source.get("firstWorkDate") or ""), "北森" if source.get("firstWorkDate") else "待补充"),
        "政治面貌": (str(source.get("politicalStatus") or ""), "北森" if source.get("politicalStatus") else "待补充"),
        "婚姻状况": (str(source.get("maritalStatus") or ""), "北森" if source.get("maritalStatus") else "待补充"),
        "编制类型": (str(source.get("establishmentType") or ""), "北森" if source.get("establishmentType") else "待补充"),
        "岗位性质": (str(source.get("jobNature") or ""), "北森" if source.get("jobNature") else "待补充"),
        "户口所在地邮编": (str(source.get("householdPostalCode") or ""), "北森" if source.get("householdPostalCode") else "待补充"),
        "居住地邮编": (str(source.get("residencePostalCode") or ""), "北森" if source.get("residencePostalCode") else "待补充"),
        "邮政编码-社保": (str(source.get("residencePostalCode") or ""), "北森" if source.get("residencePostalCode") else "待补充"),
        "实际工作单位名称": (str(source.get("actualEmployerName") or ""), "主体配置" if source.get("actualEmployerName") else "待补充"),
        "实际工作单位统一社会信用代码": (str(source.get("actualEmployerCreditCode") or ""), "主体配置" if source.get("actualEmployerCreditCode") else "待补充"),
        "个人社保号": (str(source.get("personalSocialNumber") or report.get("电脑号") or ""), "北森"),
        "工资薪金": (social_base, "北森"), "申报工资": (social_base, "北森"),
        "户口性质": (_household_kind(employee, route), "规则映射"),
        "户籍性质": (_household_kind(employee, route), "规则映射"),
        "户籍类型": (_household_kind(employee, route), "规则映射"),
        "学历": (_education(education, route), "北森/枚举映射"),
        "文化程度": (_education(education, route), "北森/枚举映射"),
        "用工形式": ("40|合同" if route in {"dongguan-social", "guangzhou-social"} else "合同工", "批次规则"),
        "用工形式-社保": ("合同工", "批次规则"),
        "人员类型": ("在职职工", "批次规则"),
        "人员类别": ("04|干部" if report.get("个人身份") == "干部" else "06|工人", "规则映射"),
        "人员状态": ("0|在职", "批次规则"),
        "参保身份-社保": ("企业职工", "批次规则"),
        "本次参保日期-社保": (entry_date, "批次规则"),
        "本次参保日期-医保": (entry_date, "批次规则"),
        "本次参保日期": (entry_date, "批次规则"),
        "参保时间": (entry_date, "批次规则"),
        "实际参保年月": (entry_date[:7].replace("-", ""), "批次规则"),
        "变动类型": ("1|增员", "模板常量"),
        "变动原因": ("11|新参保", "批次规则"),
        "证件类型": (
            ("201|居民身份证" if route in {"dongguan-social", "guangzhou-social"} else "居民身份证")
            if facts["type"] else "",
            "身份证解析" if facts["type"] else "待补充",
        ),
        "职工证件类型": (facts["type"], "身份证解析" if facts["type"] else "待补充"),
        "国籍（地区籍）": ("156|中华人民共和国" if facts["nationality"] else str(source.get("nationality") or ""), "身份证解析" if facts["nationality"] else "北森"),
        "国家地区代码": ("156|中华人民共和国" if facts["nationality"] else str(source.get("nationality") or ""), "身份证解析" if facts["nationality"] else "北森"),
        "是否补缴-医保": ("是" if supplement else "否", "办理规则"),
        "联系电话-社保": (mobile, "北森"),
        "企业基本养老保险": ("1|参保", "模板常量"), "基本养老保险": ("1|参保", "模板常量"),
        "工伤保险": ("1|参保", "模板常量"), "失业保险": ("1|参保", "模板常量"),
        "S1-单建统筹职工医保（含生育）": ("1|参保", "模板常量"),
        "基本医疗保险（含生育）": ("1|参保", "模板常量"),
    }
    value, origin = direct.get(name, ("", "待补充"))
    return str(value or ""), origin


def build_employee_template_reports(employee: dict[str, Any], run: dict[str, Any]) -> dict[str, dict[str, Any]]:
    overrides = employee.get("templateOverrides") if isinstance(employee.get("templateOverrides"), dict) else {}
    reports: dict[str, dict[str, Any]] = {}
    for route in employee_template_routes(employee):
        schema = TEMPLATE_SCHEMAS[route]
        route_overrides = overrides.get(route) if isinstance(overrides.get(route), dict) else {}
        values: dict[str, str] = {}
        origins: dict[str, str] = {}
        for field in schema["fields"]:
            name = field["name"]
            value, origin = _mapped_value(name, employee, run, route)
            if name in route_overrides:
                value = str(route_overrides.get(name) or "").strip()
                origin = "人工修改"
            values[name] = value
            origins[name] = origin
        missing = [field["name"] for field in schema["fields"] if field["required"] and not values.get(field["name"], "").strip()]
        reports[route] = {
            "route": route,
            "label": schema["label"],
            "city": schema["city"],
            "values": values,
            "origins": origins,
            "missingRequired": missing,
            "ready": not missing,
        }
    return reports


def hydrate_employee_template_reports(employee: dict[str, Any], run: dict[str, Any]) -> None:
    employee["templateReports"] = build_employee_template_reports(employee, run)


def validate_template_updates(route: str, updates: dict[str, Any]) -> dict[str, str]:
    schema = schema_for_route(route)
    if schema is None:
        raise ValueError("未知政务模板办理路径")
    definitions = {field["name"]: field for field in schema["fields"]}
    unknown = set(updates) - set(definitions)
    if unknown:
        raise ValueError(f"未知模板字段：{'、'.join(sorted(unknown))}")
    normalized: dict[str, str] = {}
    for name, raw in updates.items():
        value = str(raw or "").strip()
        options = definitions[name].get("options") or ()
        if value and options and value not in options:
            raise ValueError(f"{name}必须从当前模板枚举选择")
        if value and definitions[name].get("control") == "date":
            parsed = None
            for pattern in ("%Y-%m-%d", "%Y%m%d"):
                try:
                    parsed = datetime.strptime(value, pattern)
                    break
                except ValueError:
                    continue
            if parsed is None:
                raise ValueError(f"{name}必须为有效日期")
            value = parsed.strftime("%Y-%m-%d")
        normalized[name] = value
    return normalized

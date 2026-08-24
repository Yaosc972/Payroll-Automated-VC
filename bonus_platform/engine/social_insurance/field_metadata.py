from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any

from ... import config


class FieldMetadataError(ValueError):
    """政务模板字段元数据不可用。"""


ENUM_OPTIONS: dict[str, tuple[str, ...]] = {
    "户籍": ("深圳户籍", "广东省内非深户", "广东省外户籍"),
    "民族": (
        "汉族", "蒙古族", "回族", "藏族", "维吾尔族", "苗族", "彝族", "壮族", "布依族", "朝鲜族",
        "满族", "侗族", "瑶族", "白族", "土家族", "哈尼族", "哈萨克族", "傣族", "黎族", "傈僳族",
        "佤族", "畲族", "高山族", "拉祜族", "水族", "东乡族", "纳西族", "景颇族", "柯尔克孜族", "土族",
        "达斡尔族", "仫佬族", "羌族", "布朗族", "撒拉族", "毛南族", "仡佬族", "锡伯族", "阿昌族", "普米族",
        "塔吉克族", "怒族", "乌孜别克族", "俄罗斯族", "鄂温克族", "德昂族", "保安族", "裕固族", "京族", "塔塔尔族",
        "独龙族", "鄂伦春族", "赫哲族", "门巴族", "珞巴族", "基诺族", "其他",
    ),
    "岗位类别": ("工人岗位", "管理(技术)岗位"),
    "个人身份": ("干部", "工人"),
    "用工形式": ("全民工", "合同工", "劳务工", "临时工", "集体工"),
    "学历": (
        "博士研究生", "硕士研究生", "大学本科", "大学专科", "中等专科",
        "职业高中", "技工学校", "普通中学（高中）", "初级中学", "小学",
    ),
    "职称": ("无", "员级职称", "助理级职称", "中级职称", "高级职称", "正高级职称"),
    "国家职业资格或职业技能等级": ("无", "高级技师（一级）", "技师（二级）", "高级（三级）", "中级（四级）", "初级（五级）"),
    "医疗缴费档次": ("职工一档", "职工二档"),
    "户籍地类别": ("农业", "非农业", "居民户"),
    "就业形式": ("雇佣就业", "派遣就业"),
    "就业前身份": (
        "未升学初中毕业生", "未升学高中毕业生", "就业转失业人员", "应届高校毕业生",
        "中职（专）、技校应届毕业生", "退伍兵", "随军家属", "刑释解教人员", "农转居",
        "残疾人", "被征地农民", "水库移民", "三峡库区移民", "本地农村劳动力", "其他",
    ),
}

_REQUIRED_FIELDS = {
    "证件号码", "姓名", "户籍", "民族", "手机号码", "通讯地址", "个人身份", "用工形式", "学历",
    "职称", "国家职业资格或职业技能等级", "医疗缴费档次", "户籍地类别", "户口所在地行政区划代码",
    "就业形式", "就业前身份",
}

_FIELD_SPECS = (
    ("证件号码", "text", "居民身份证号码"),
    ("姓名", "text", "北森员工姓名"),
    ("户籍", "select", "政务模板枚举"),
    ("入深户时间", "date", "选填；模板格式 yyyyMMdd"),
    ("民族", "select", "政务模板民族枚举"),
    ("手机号码", "text", "须为员工本人手机号"),
    ("通讯地址", "text", "现居住地址"),
    ("电脑号", "text", "仍在其他单位正常参保时填写"),
    ("岗位类别", "select", "女性职工必填；按个人身份匹配"),
    ("个人身份", "select", "本科及以上为干部，本科以下为工人"),
    ("用工形式", "select", "当前规则默认合同工"),
    ("学历", "select", "政务模板学历枚举"),
    ("职称", "select", "当前规则默认无"),
    ("国家职业资格或职业技能等级", "select", "当前规则默认无"),
    ("医疗缴费档次", "select", "深圳户籍一档，其他有效户籍二档；户籍无法判断时转人工"),
    ("部门名称", "text", "模板指引为无需填写"),
    ("户籍地类别", "select", "深圳户籍为居民户，其他按户口类别"),
    ("户口所在地行政区划代码", "adminDivision", "从模板行政区划字典选择到6位区县"),
    ("就业形式", "select", "当前规则默认雇佣就业"),
    ("就业前身份", "select", "当前规则默认其他"),
    ("社保缴交基数", "text", "取北森 Offer；缺失时由业务复核"),
    ("公积金缴交基数", "text", "取北森 Offer；本期不生成公积金模板"),
    ("公积金号", "text", "已有账户则展示；深圳非深户新开户可为空"),
    ("户口具体地址", "text", "取北森户口地址，用于行政区划复核"),
)

FIELD_DEFINITIONS: tuple[dict[str, Any], ...] = tuple(
    {
        "name": name,
        "control": control,
        "required": name in _REQUIRED_FIELDS,
        "note": note,
        **({"options": ENUM_OPTIONS[name]} if name in ENUM_OPTIONS else {}),
    }
    for name, control, note in _FIELD_SPECS
)
FIELD_DEFINITION_BY_NAME = {item["name"]: item for item in FIELD_DEFINITIONS}

_ADMIN_DIVISION_CACHE: dict[str, Any] = {"key": None, "values": [], "choices": []}
_BUNDLED_ADMIN_DIVISIONS = Path(__file__).with_name("administrative_divisions.json")


def public_field_definitions() -> list[dict[str, Any]]:
    return [
        {**item, **({"options": list(item["options"])} if "options" in item else {})}
        for item in FIELD_DEFINITIONS
    ]


def validate_report_field_value(field: str, value: str) -> None:
    normalized = str(value or "").strip()
    options = ENUM_OPTIONS.get(field)
    if normalized and options and normalized not in options:
        raise FieldMetadataError(f"{field}必须从政务模板枚举选择")
    if field == "入深户时间" and normalized:
        try:
            datetime.strptime(normalized, "%Y%m%d")
        except ValueError as exc:
            raise FieldMetadataError("入深户时间必须为有效的 yyyyMMdd 日期") from exc
    if field == "户口所在地行政区划代码" and normalized:
        if (
            not re.fullmatch(r"\d{6}\.[^\s.]+", normalized)
            or normalized not in set(load_administrative_divisions())
        ):
            raise FieldMetadataError("户口所在地行政区划代码必须从政务模板区县字典选择")


def _engine_dir() -> Path:
    configured = os.environ.get("SIGMA_SOCIAL_INSURANCE_ENGINE_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return (config.PROJECT_ROOT / "outputs" / "social-insurance-beisen-mvp-20260814").resolve()


def _template_path() -> Path:
    configured = os.environ.get("SIGMA_SOCIAL_INSURANCE_TEMPLATE_FILE")
    if not configured:
        raise FieldMetadataError("政务模板字典未配置，请配置当前深圳模板")
    path = Path(configured).expanduser().resolve()
    if not path.is_file() or path.suffix.lower() not in {".xls", ".xlsx"}:
        raise FieldMetadataError("已配置的深圳政务模板不可读取")
    return path


def _node_binary() -> str:
    configured = os.environ.get("SIGMA_SOCIAL_INSURANCE_NODE")
    for candidate in (configured, shutil.which("node")):
        if candidate and Path(candidate).exists():
            return str(candidate)
    raise FieldMetadataError("未找到政务模板字典所需的 Node.js 运行时")


def _build_administrative_division_metadata(raw_values: list[Any]) -> tuple[list[str], list[dict[str, str]]]:
    provinces: dict[str, str] = {}
    cities: dict[str, str] = {}
    divisions: list[tuple[str, str]] = []
    seen = set()
    for raw in raw_values:
        normalized = str(raw or "").strip().replace("．", ".")
        match = re.fullmatch(r"(\d{2}|\d{4}|\d{6})\.([^\s.]+)", normalized)
        if not match:
            continue
        code, name = match.groups()
        if len(code) == 2:
            provinces[code] = name
        elif len(code) == 4:
            cities[code] = name
        elif normalized not in seen:
            seen.add(normalized)
            divisions.append((normalized, name))

    values: list[str] = []
    choices: list[dict[str, str]] = []
    for value, name in divisions:
        code = value[:6]
        hierarchy = [provinces.get(code[:2], ""), cities.get(code[:4], "")]
        context_parts = [part for part in hierarchy if part and part != name]
        context = " / ".join(context_parts)
        search_text = " ".join(part for part in [value, code, name, *hierarchy] if part)
        values.append(value)
        choices.append({"value": value, "context": context, "searchText": search_text})
    return values, choices


def _load_bundled_administrative_divisions() -> list[str]:
    try:
        raw_values = json.loads(_BUNDLED_ADMIN_DIVISIONS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FieldMetadataError("云端政务模板行政区划字典不可用") from exc
    if not isinstance(raw_values, list):
        raise FieldMetadataError("云端政务模板行政区划字典格式无效")
    cache_key = f"bundled:{_BUNDLED_ADMIN_DIVISIONS.stat().st_mtime_ns}"
    if _ADMIN_DIVISION_CACHE["key"] == cache_key:
        return list(_ADMIN_DIVISION_CACHE["values"])
    values, choices = _build_administrative_division_metadata(raw_values)
    if not values:
        raise FieldMetadataError("云端政务模板未包含6位区县行政区划字典")
    _ADMIN_DIVISION_CACHE.update({"key": cache_key, "values": values, "choices": choices})
    return list(values)


def load_administrative_divisions() -> list[str]:
    if os.environ.get("VERCEL"):
        return _load_bundled_administrative_divisions()
    engine_dir = _engine_dir()
    template_path = _template_path()
    bridge = Path(__file__).with_name("metadata_bridge.mjs")
    if not (engine_dir / "lib" / "spreadsheet-io.mjs").exists():
        raise FieldMetadataError("已验证的政务模板读取引擎未配置")
    cache_key = f"{template_path}:{template_path.stat().st_mtime_ns}"
    if _ADMIN_DIVISION_CACHE["key"] == cache_key:
        return list(_ADMIN_DIVISION_CACHE["values"])
    try:
        completed = subprocess.run(
            [_node_binary(), str(bridge), str(engine_dir), str(template_path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
            env={**os.environ, "NODE_TLS_REJECT_UNAUTHORIZED": "1"},
        )
    except subprocess.TimeoutExpired as exc:
        raise FieldMetadataError("政务模板行政区划字典加载超时") from exc
    if completed.returncode != 0:
        raise FieldMetadataError("政务模板行政区划字典加载失败")
    try:
        last_line = next(line for line in reversed(completed.stdout.splitlines()) if line.strip())
        raw_values = json.loads(last_line).get("administrativeDivisions")
    except (StopIteration, AttributeError, json.JSONDecodeError) as exc:
        raise FieldMetadataError("政务模板行政区划字典格式无效") from exc
    if not isinstance(raw_values, list):
        raise FieldMetadataError("政务模板行政区划字典格式无效")
    values, choices = _build_administrative_division_metadata(raw_values)
    if not values:
        raise FieldMetadataError("政务模板未包含6位区县行政区划字典")
    _ADMIN_DIVISION_CACHE.update({"key": cache_key, "values": values, "choices": choices})
    return list(values)


def load_administrative_division_choices() -> list[dict[str, str]]:
    load_administrative_divisions()
    return [dict(choice) for choice in _ADMIN_DIVISION_CACHE["choices"]]

from __future__ import annotations

import base64
import mimetypes
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Iterable


@dataclass(frozen=True)
class ToolSpec:
    id: str
    name: str
    country: str
    description: str
    accept: tuple[str, ...]
    multiple: bool = False
    preview: bool = False
    category: str = "海外核算"
    source: str = ""
    drop_hint: str = ""

    def public_dict(self) -> dict:
        value = asdict(self)
        value["accept"] = list(self.accept)
        return value


@dataclass(frozen=True)
class ProcessResult:
    filename: str
    content: bytes
    summary: str
    media_type: str


TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec("swedish_tax", "瑞典税务 PDF 提取", "瑞典", "提取税务申报人员明细并生成双表 Excel。", (".pdf",)),
    ToolSpec("dutch_pension", "荷兰养老金提取", "荷兰", "解析 Zwitserleven 养老金账单并执行金额验算。", (".pdf",)),
    ToolSpec("humana_details", "Humana 牙科/眼科", "美国", "提取 Humana Employee Detail 并生成员工及计划汇总。", (".pdf",)),
    ToolSpec(
        "import_paie", "法国 Payfit import 自动填写", "法国",
        "用出勤源表填写一份或多份 Payfit 空白模板。", (".xlsx",), multiple=True,
        category="工资核算", drop_hint="一次拖入：源表 + 空白 import 模板（可多份）",
    ),
    ToolSpec("norway_payslip", "挪威工资单 PDF 提取", "挪威", "提取员工、期间、实发金额与工资科目。", (".pdf",), preview=True),
    ToolSpec("norway_payment", "挪威付款清单 PDF 提取", "挪威", "提取收款人、KID、账号、SWIFT 与付款金额。", (".pdf",), preview=True),
    ToolSpec("italy_payslip", "意大利工资单 PDF 提取", "意大利", "提取工资科目、净薪、总应发与总扣。", (".pdf",)),
    ToolSpec("dutch_payslip", "荷兰工资单 PDF 提取", "荷兰", "提取工资明细及员工汇总。", (".pdf",), multiple=True),
    ToolSpec(
        "pl_pesel", "波兰 PESEL 信息提取", "波兰",
        "按标签、11 位数字及 OCR 易混字符定位 PESEL，并校验校验位。", (".pdf",), multiple=True,
        source="波兰工具箱", drop_hint="拖入波兰工资单/合同/表单 PDF（可多份，.pdf）",
    ),
    ToolSpec(
        "pl_payroll", "波兰工资单提取", "波兰",
        "提取员工基本工资、工时、假期、ZUS 及加班等明细。", (".pdf",), multiple=True,
        source="波兰工具箱", drop_hint="拖入波兰工资单 PDF（可多份，每份输出一个 Excel）",
    ),
    ToolSpec(
        "pl_attendance", "波兰考勤合并汇总", "波兰",
        "合并各站点考勤表，生成请假明细、月汇总、异常清单及可选 Report 汇总。",
        (".xlsx", ".xlsm", ".xls"), multiple=True, category="工资核算", source="波兰工具箱",
        drop_hint="一次拖入各站点考勤表（可多份；可再加文件名含“汇总字段/模板”的表头模板）",
    ),
    ToolSpec(
        "de_lohnjournal", "德国工资单提取（Lohnjournal）", "德国",
        "按绘制锚点定位 Lohnjournal 32 列并逐人提取。", (".pdf",), multiple=True,
        drop_hint="拖入德国 Lohnjournal 工资单 PDF（可多份，无需 import 模板）",
    ),
    ToolSpec(
        "ie_payslip", "爱尔兰工资单处理", "爱尔兰",
        "提取员工姓名与 PPS Number，按姓名重命名并用 PPS 加密。", (".pdf",), multiple=True,
        drop_hint="拖入爱尔兰工资单 PDF（可多份，输出按姓名命名的加密 PDF）",
    ),
    ToolSpec(
        "p45_process", "英国 P45 处理（重命名+加密）", "英国",
        "提取姓名、离职日期和 NI Number，重命名后用 NI Number 加密。", (".pdf",), multiple=True,
        drop_hint="拖入英国 P45 表格 PDF（可多份，输出重命名并加密的 PDF）",
    ),
    ToolSpec(
        "pension_rename", "英国养老金信函重命名", "英国",
        "提取 AE Eligible / Non-Eligible Job Holder Letter 收件人姓名并重命名。", (".pdf",), multiple=True,
        drop_hint="拖入 AE Eligible / Non-Eligible Job Holder Letter PDF（可多份）",
    ),
    ToolSpec(
        "pl_pdf_encrypt", "PDF/Excel 批量加密", "通用",
        "按密码表中的文件名和 PESEL/密码，批量加密 PDF 或 Excel。",
        (".pdf", ".xlsx", ".xls"), multiple=True, category="工具",
        drop_hint="一次拖入：密码表 xlsx + 要加密的 PDF/xlsx/xls（可多份）",
    ),
    ToolSpec(
        "pl_pdf_rename", "PDF 批量重命名（按工号）", "通用",
        "按映射表的文件名和工号，批量重命名 PDF。", (".pdf", ".xlsx", ".xls"), multiple=True, category="工具",
        drop_hint="一次拖入：映射表 xlsx/xls + 要改名的 PDF（可多份）",
    ),
    ToolSpec(
        "pl_pdf_sanitize", "PDF 隐私脱敏（PESEL 打码）", "波兰",
        "按默认或自定义关键词涂白敏感信息，并输出脱敏 PNG。", (".pdf", ".txt"), multiple=True, category="工具", source="波兰工具箱",
        drop_hint="拖入含 PESEL 等敏感信息的 PDF（可多份；可另加自定义关键词 .txt）",
    ),
)
_TOOL_INDEX = {tool.id: tool for tool in TOOLS}
_PROCESS_LOCK = Lock()


def list_tools() -> list[dict]:
    return [tool.public_dict() for tool in TOOLS]


@lru_cache(maxsize=1)
def _legacy_module():
    """Load the handed-over parsers once without starting their standalone server."""
    from .vendor import (
        dutch_payslip_parser,
        humana_details_extract,
        italy_payslip_parser,
        legacy_web_extractor,
        norway_pdf_parser,
        pension_pdf_to_excel,
        swedish_tax_pdf_extractor,
    )
    from .vendor.import_paie_autofill.scripts import auto_fill_import

    legacy_web_extractor.ext = swedish_tax_pdf_extractor
    legacy_web_extractor.pen = pension_pdf_to_excel
    legacy_web_extractor.hum = humana_details_extract
    legacy_web_extractor.npr = norway_pdf_parser
    legacy_web_extractor.ita = italy_payslip_parser
    legacy_web_extractor.dpa = dutch_payslip_parser
    legacy_web_extractor.paie = auto_fill_import
    return legacy_web_extractor


@lru_cache(maxsize=1)
def _poland_tools():
    """Load the new toolbox adapters without changing their handed-over cores."""
    from .vendor import poland_web_tools

    return {meta["id"]: meta["core"] for meta in poland_web_tools.PL_META}


def _validate_files(tool: ToolSpec, files: list[tuple[str, bytes]]) -> None:
    if not files:
        raise ValueError("请至少上传一个文件。")
    if not tool.multiple and len(files) != 1:
        raise ValueError(f"{tool.name}每次只支持一个文件。")
    for filename, content in files:
        suffix = Path(filename).suffix.lower()
        if suffix not in tool.accept:
            raise ValueError(f"{filename} 格式不支持，应上传 {'/'.join(tool.accept)} 文件。")
        if not content:
            raise ValueError(f"{filename} 是空文件。")


def _decode_result(result) -> ProcessResult:
    if not result or len(result) < 2 or not result[0] or not result[1]:
        summary = result[2] if result and len(result) > 2 else "未提取到有效数据，请确认文件版式和文本层。"
        raise ValueError(summary)
    filename, encoded = result[:2]
    summary = result[2] if len(result) > 2 else "处理完成"
    content = base64.b64decode(encoded)
    media_type = mimetypes.guess_type(str(filename))[0] or "application/octet-stream"
    return ProcessResult(str(filename), content, str(summary), media_type)


def process_files(tool_id: str, uploaded_files: Iterable[tuple[str, bytes]]) -> ProcessResult:
    tool = _TOOL_INDEX.get(tool_id)
    if tool is None:
        raise KeyError(f"未知海外薪资工具：{tool_id}")
    files = [(Path(name).name, content) for name, content in uploaded_files]
    _validate_files(tool, files)

    # Several handed-over parsers keep document state in module globals. Keep
    # execution serialized until those parsers are made request-scoped.
    with _PROCESS_LOCK:
        toolbox = _poland_tools()
        if tool.id in toolbox:
            return _decode_result(toolbox[tool.id](files, None))

        legacy = _legacy_module()
        if tool.multiple:
            payload = {
                "files": [
                    {"filename": name, "data": base64.b64encode(content).decode("ascii")}
                    for name, content in files
                ]
            }
            function = getattr(legacy, f"process_{tool_id}_multi")
            return _decode_result(function(payload))

        function = getattr(legacy, f"process_{tool_id}")
        return _decode_result(function(files[0][0], files[0][1]))

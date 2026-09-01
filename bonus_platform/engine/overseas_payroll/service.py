from __future__ import annotations

import base64
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
    ToolSpec("import_paie", "法国 Payfit import 自动填写", "法国", "用出勤源表填写一份或多份 Payfit 空白模板。", (".xlsx",), multiple=True),
    ToolSpec("norway_payslip", "挪威工资单 PDF 提取", "挪威", "提取员工、期间、实发金额与工资科目。", (".pdf",), preview=True),
    ToolSpec("norway_payment", "挪威付款清单 PDF 提取", "挪威", "提取收款人、KID、账号、SWIFT 与付款金额。", (".pdf",), preview=True),
    ToolSpec("italy_payslip", "意大利工资单 PDF 提取", "意大利", "提取工资科目、净薪、总应发与总扣。", (".pdf",)),
    ToolSpec("dutch_payslip", "荷兰工资单 PDF 提取", "荷兰", "提取工资明细及员工汇总。", (".pdf",), multiple=True),
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
    media_type = "application/zip" if str(filename).lower().endswith(".zip") else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return ProcessResult(str(filename), content, str(summary), media_type)


def process_files(tool_id: str, uploaded_files: Iterable[tuple[str, bytes]]) -> ProcessResult:
    tool = _TOOL_INDEX.get(tool_id)
    if tool is None:
        raise KeyError(f"未知海外薪资工具：{tool_id}")
    files = [(Path(name).name, content) for name, content in uploaded_files]
    _validate_files(tool, files)
    legacy = _legacy_module()

    # Several handed-over parsers keep document state in module globals. Keep
    # execution serialized until those parsers are made request-scoped.
    with _PROCESS_LOCK:
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

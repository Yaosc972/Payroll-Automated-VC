#!/usr/bin/env python3
"""
养老金 PDF 账单提取工具 (Pension PDF to Excel)
支持 Zwitslerleven 荷兰养老金 PDF 账单的表格提取。
"""

import sys
import os
import re
import argparse
from pathlib import Path

import pdfplumber
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill, numbers
from openpyxl.utils import get_column_letter


# ──────────────────────────────────────────────
# 列定义
# ──────────────────────────────────────────────
COLUMNS = [
    "Name / participation",
    "Total",
    "Pension\ncontribution",
    "Supplementary\npension",
    "Service\ncharges",
    "Risk premium\nsurvivor / occ. disability",
    "Risk premium\ndeath",
    "Risk premium\nocc. disability",
    "Risk premium dependants'\nbridging pension",
]

# 备用表头关键词（用于模糊匹配 PDF 中的列标题）
HEADER_KEYWORDS = [
    ["name", "naam", "participation", "deelneming"],                     # col 0
    ["total", "totaal"],                                                  # col 1
    ["pension contribution", "pensioenbijdrage", "pensioenpremie",
     "pensioen"],                                                         # col 2
    ["supplementary", "aanvullend", "suppl"],                             # col 3
    ["service", "servicekosten", "uitvoeringskosten", "charges"],         # col 4
    ["survivor", "nabestaanden", "dependent",                             # col 5 (has survivor)
     "nabestaandenpensioen"],                                             # col 5
    ["death", "overlijden", "overlijdensrisico"],                         # col 6
    ["wia", "ao-premie", "arbeidsongeschiktheidspensioen",
     "arbeidsongeschiktheid", "disability", "occ.", "occupational"],     # col 7 (NO survivor)
    ["dependants", "wezen", "bridging", "overbrugging", "bridge"],        # col 8
]

THIN_BORDER = Border(
    left=Side(style="thin"),
    right=Side(style="thin"),
    top=Side(style="thin"),
    bottom=Side(style="thin"),
)
HEADER_FILL = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
HEADER_FONT = Font(name="Calibri", bold=True, color="FFFFFF", size=10)
DATA_FONT = Font(name="Calibri", size=10)
WRAP_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)
NUM_ALIGN = Alignment(horizontal="right", vertical="center")


# ──────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────
def is_money_value(text):
    """判断文本是否为金额"""
    if not text:
        return False
    text = text.strip()
    # 匹配: €1,234.56 或 -€1,234.56 或 1,234.56 或 1234.56
    return bool(re.match(r'^-?[€\u20ac]?\s*\d[\d,.]*\d$', text))


def parse_money(text):
    """将金额字符串转为浮点数"""
    if not text:
        return None
    text = text.strip()
    text = text.replace('€', '').replace('\u20ac', '').replace(' ', '')
    # 处理负号位置: "- 1,234.56" -> "-1234.56"
    text = re.sub(r'^-\s*', '-', text)
    text = text.replace(',', '')
    try:
        return float(text)
    except ValueError:
        return None


def fuzzy_match_header(cell_text, col_index):
    """检查 cell_text 是否匹配第 col_index 列的标题"""
    if not cell_text:
        return False
    text = cell_text.lower().strip()
    for kw in HEADER_KEYWORDS[col_index]:
        if kw in text:
            return True
    return False


def find_data_rows(tables):
    """
    从 pdfplumber 提取的 tables 中识别数据行。
    返回 (head_offset, data_rows) — 第一行有标题信息的行比例，以及纯数据行列表。
    """
    data_rows = []
    for table in tables:
        for row in table:
            # 过滤空行
            cleaned = [str(c).strip() if c else "" for c in row]
            if all(not c for c in cleaned):
                continue
            data_rows.append(cleaned)
    return data_rows


def reassemble_rows(raw_rows, expected_cols=9):
    """
    当 PDF 行被换行拆分时，尝试按列数补齐。
    """
    assembled = []
    buf = []
    for row in raw_rows:
        buf.extend(row)
        # 足够列数时截断，溢出追加到下一行
        while len(buf) >= expected_cols:
            assembled.append(buf[:expected_cols])
            buf = buf[expected_cols:]
    if buf and len(buf) >= expected_cols - 2:  # 允许少几列
        # 补齐 None
        buf += [""] * (expected_cols - len(buf))
        assembled.append(buf)
    return assembled


def classify_rows(rows):
    """
    把行分成: header_rows (包含表头文本的行) 和 data_rows (纯数字/金额行)。
    """
    header_rows = []
    data_rows_out = []
    for row in rows:
        text_parts = [c for c in row if c and not is_money_value(c)]
        money_parts = [c for c in row if is_money_value(c)]
        # 如果文本列数 >= 3 且金额列少 -> 大概率是表头行
        if len(text_parts) >= 3 and len(money_parts) <= 2:
            header_rows.append(row)
        else:
            data_rows_out.append(row)
    return header_rows, data_rows_out


def normalize_header_candidates(header_rows):
    """
    尝试把截图中那种多行表头规整成一组。
    返回: merged_header (可能多行合并后的 column_name 列表)
    """
    if not header_rows:
        return None
    # 收集所有 header text
    merged = [""] * 9
    for row in header_rows:
        for i, cell in enumerate(row):
            if i >= 9:
                break
            cell = str(cell).strip()
            if cell and not is_money_value(cell):
                if merged[i]:
                    merged[i] += "\n" + cell
                else:
                    merged[i] = cell
    return merged


def map_columns(candidate_header):
    """
    尝试把提取出的表头映射到标准 COLUMNS 顺序。
    返回: mapping_dict {standard_col_index: extracted_col_index}
    """
    # 第一轮：所有候选匹配
    candidates = {}  # {std_idx: [(ext_idx, score)]}
    for std_idx in range(9):
        matches = []
        for ext_idx, cell_text in enumerate(candidate_header):
            tokens = re.split(r'[\n/]+', cell_text.lower())
            for token in tokens:
                token = token.strip()
                if not token:
                    continue
                for kw in HEADER_KEYWORDS[std_idx]:
                    if kw in token or token in kw:
                        matches.append((ext_idx, len(kw)))
        if matches:
            candidates[std_idx] = matches

    # 第二轮：解析冲突 — 优先独占到唯一列的关键词匹配
    mapping = {}
    assigned_ext = set()

    # 按候选数升序处理（唯一匹配的先确定）
    for std_idx in sorted(candidates, key=lambda k: len(candidates[k])):
        # 过滤已被占用的 ext_idx
        available = [(ext, score) for ext, score in candidates[std_idx]
                     if ext not in assigned_ext]
        if not available:
            continue
        # 选最高分
        best_ext, best_score = max(available, key=lambda x: x[1])
        mapping[std_idx] = best_ext
        assigned_ext.add(best_ext)

    return mapping


def _iter_amounts(amt_row):
    """把金额行解析成 ['€368.54', ...] 列表。

    真实 Zwitserleven 账单中 € 符号位置不固定：
      - 有时独立单元格: ['€', '368.54']
      - 有时与数值合并: ['€ 9.10']
    本函数统一处理两种写法，返回带 € 前缀的金额字符串列表。
    """
    amounts = []
    cells = [(c or "").strip() for c in amt_row]
    i = 0
    while i < len(cells):
        cell = cells[i]
        if not cell:
            i += 1
            continue
        # 已合并: "€ 9.10" / "€9.10"
        m = re.match(r"^[€\u20ac]\s*([\d.,]+)$", cell)
        if m:
            amounts.append("€" + m.group(1))
            i += 1
            continue
        # 独立 € + 下一个单元格是数字: ['€', '368.54']
        if cell in ("€", "\u20ac") and i + 1 < len(cells) and re.match(r"^[\d.,]+$", cells[i + 1].strip()):
            amounts.append("€" + cells[i + 1].strip())
            i += 2
            continue
        # 纯数字（无 € 前缀）
        if re.match(r"^[\d.,]+$", cell):
            amounts.append(cell)
            i += 1
            continue
        i += 1
    return amounts


def _classify_row(row):
    """对一行做分类，返回 (is_final, is_name, is_amount, amts, label)。

    - is_final: Final total 行（c0 含 total/totaal 且金额数 >= 6）
    - is_name: 参保人姓名行（c0 含逗号，或前4列含 'particip'，且前4列有 6 位以上数字）
    - is_amount: 金额行（解析出 >= 2 个金额）
    - label: 姓名行拼接出的 '姓名 / participation 号' 标签
    """
    c0 = (row[0] or "").strip() if row else ""
    head = " ".join((c or "") for c in row[:6])
    amts = _iter_amounts(row)

    # Final total: 首列含 total/totaal，且该行有 >= 6 个金额（排除普通表头/文字行）
    is_final = bool(c0 and ("total" in c0.lower() or "totaal" in c0.lower()) and len(amts) >= 6)

    # 姓名行：逗号 或 particip 字样，且数字片段拼接后 >= 6 位。
    # 注意：participation 号常被拆成多个片段（跨列如 '86022'+'4062'、跨行如 '85032905'+'6'），
    # 必须拼接全部数字再判断长度，不能匹配单个连续 6 位数字（否则 Verheijen 这类行会被漏掉）
    head_digits = "".join(re.findall(r"\d+", head))
    is_name = bool((("," in c0) or ("particip" in head.lower())) and len(head_digits) >= 6)

    label = ""
    if is_name:
        # 拼接前三列得到完整姓名文本（| 为 pdfplumber 单元格内换行符）
        name_text = " ".join((c or "").replace("|", " ").strip() for c in row[:3] if c).strip()
        nm = re.split(r"particip", name_text, flags=re.I)[0].strip()
        nm = re.sub(r"\s+", " ", nm).rstrip("/").strip()
        # participation 号：取 'particip' 之后的所有数字片段拼接（兼容跨列/跨行拆分）
        part_src = name_text
        mi = re.search(r"particip", name_text, flags=re.I)
        if mi:
            part_src = name_text[mi.end():]
        participation = "".join(re.findall(r"\d+", part_src))
        label = f"{nm} / participation {participation}" if (nm and participation) else (nm or name_text)

    return is_final, is_name, len(amts) >= 2, amts, label


def _extract_participant_layout(pdf_path):
    """提取 Zwitserleven 'Prolongatiefactuur specificatie' 参保人布局。

    特征（无显式边框线，需 text 策略提取表格）：
      - 每个参保人 = 姓名行（姓名+participation 号）+ 后续金额行（8 个金额）
      - 账单底部有 Final total 行：首列含 'final total'，其后 8 个金额 = 各列合计
    采用流式扫描：把各页行拼成一条流，按"姓名行 → 最近金额行"配对，
    天然支持跨页断裂（姓名在页尾、金额在下一页开头）和行间插入空行/注释行。
    返回 (data_rows, found, final_totals, warnings) ；
    warnings 记录疑似漏提取（有姓名无金额）等异常。
    """
    all_rows = []          # 跨页收集所有非空行（流式）
    found = False
    final_totals = None
    text_strat = {"vertical_strategy": "text", "horizontal_strategy": "text"}

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables(text_strat)
            if not tables:
                tables = page.extract_tables()  # 退化：默认/线条策略
            for table in tables:
                cleaned = [[(c or "").strip() if c else "" for c in row] for row in table]
                for row in cleaned:
                    if any(cell for cell in row):
                        all_rows.append(row)

    # 流式扫描：姓名行挂起，遇到金额行配对；Final total 单独识别
    data_rows = []
    warnings = []
    pending_label = None
    for row in all_rows:
        is_final, is_name, is_amount, amts, label = _classify_row(row)
        if is_final:
            vals = [v for v in (parse_money(a) for a in amts) if v is not None]
            if vals:
                final_totals = vals
                print(f"[INFO] 识别到 Final total 行: {vals}")
            continue
        if is_name:
            pending_label = label
            found = True
            continue
        if is_amount and pending_label:
            full = [pending_label] + list(amts)
            while len(full) < 9:
                full.append("")
            full = full[:9]
            data_rows.append(full)
            pending_label = None
            continue
        # 其他行（表头/说明文字）：不打断配对，pending 保留继续找金额行

    if pending_label:
        warnings.append(f"疑似漏提取: 姓名行 '{pending_label}' 后未找到金额行（可能跨页断裂或该参保人金额缺失）")
        print(f"[WARN] {warnings[-1]}")

    return data_rows, found, final_totals, warnings


def _extract_generic(pdf_path):
    """通用提取逻辑（逐表分类 + 列映射），适用于带表头的干净 9 列表格。"""
    all_data_rows = []
    all_header_rows = []

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            if not tables:
                print("[WARN] 本页 extract_tables 为空（可能是扫描件/无文字层，需 OCR）")
                continue
            for table in tables:
                cleaned = [[str(c).strip() if c else "" for c in row] for row in table]
                if all(all(not cell for cell in r) for r in cleaned):
                    continue
                h_rows, d_rows = classify_rows(cleaned)
                if h_rows:
                    all_header_rows.extend(h_rows)
                    candidate = normalize_header_candidates(h_rows)
                    mapping = map_columns(candidate) if candidate else {}
                    if mapping:
                        print(f"Column mapping: {mapping}")
                        for row in d_rows:
                            new_row = []
                            for std_idx in range(9):
                                ext_idx = mapping.get(std_idx)
                                if ext_idx is not None and ext_idx < len(row):
                                    new_row.append(row[ext_idx])
                                else:
                                    new_row.append("")
                            all_data_rows.append(new_row)
                    else:
                        all_data_rows.extend(d_rows)
                else:
                    all_data_rows.extend(d_rows)

    if not all_data_rows:
        return [], None

    for i, row in enumerate(all_data_rows):
        if len(row) < 9:
            all_data_rows[i] = row + [""] * (9 - len(row))
        elif len(row) > 9:
            all_data_rows[i] = row[:9]

    candidate = normalize_header_candidates(all_header_rows) if all_header_rows else None
    print(f"[INFO] 提取数据行: {len(all_data_rows)}")
    return all_data_rows, candidate


def _verify_rows(data_rows, final_totals, tolerance=0.01):
    """双重验算：提取数据 vs 账单 Final total。

    - col_sums: 提取结果各列（8 个金额列）求和
    - 逐列与 final_totals 比对（Final total 行的 8 个金额 = 各列合计）
    - verified: 是否真正执行了比对（final_totals 存在时才为 True）
    - issues: 差异/异常列表（空 = 全部通过）
    返回 (col_sums, issues, verified)
    """
    n_cols = 8
    col_sums = [0.0] * n_cols
    for row in data_rows:
        for i in range(n_cols):
            if i + 1 < len(row):
                v = parse_money(str(row[i + 1])) if row[i + 1] else None
                if v is not None:
                    col_sums[i] += v

    issues = []
    verified = bool(final_totals)
    if verified:
        for i in range(n_cols):
            bill = final_totals[i] if i < len(final_totals) else None
            if bill is None:
                issues.append(f"列{i + 1}({COLUMNS[i + 1].splitlines()[0]}): 账单 Final total 缺少该列金额，无法比对")
                continue
            diff = round(col_sums[i] - bill, 2)
            if abs(diff) > tolerance:
                issues.append(
                    f"列{i + 1}({COLUMNS[i + 1].splitlines()[0]}): 提取 {col_sums[i]:.2f} vs 账单 {bill:.2f} 差 {diff:+.2f}"
                )
    else:
        issues.append("未识别到账单 Final total 行，无法执行验算（需人工核对）")
    return col_sums, issues, verified


def extract_from_pdf(pdf_path):
    """核心提取逻辑。

    优先识别 Zwitserleven 参保人布局（无边框线，需 text 策略）；
    未匹配到则回退到带表头的通用表格逻辑。
    返回 (data_rows, candidate_header, verify_info)：
      verify_info = {'final_totals', 'col_sums', 'issues', 'grand_sum',
                     'verified', 'passed', 'warnings'}
      passed 仅在 verified=True 且无差异时为 True（不会"假通过"）。
    """
    all_data_rows, found, final_totals, warnings = _extract_participant_layout(pdf_path)
    if found and all_data_rows:
        print(f"[INFO] 识别到参保人布局，提取数据行: {len(all_data_rows)}")
        col_sums, issues, verified = _verify_rows(all_data_rows, final_totals)
        for w in warnings:
            issues.append(w)
        verify_info = {
            "final_totals": final_totals or [],
            "col_sums": col_sums,
            "issues": issues,
            "grand_sum": round(sum(col_sums), 2),
            "verified": verified,
            "passed": verified and len(issues) == 0,
            "warnings": warnings,
        }
        if issues:
            print("[WARN] 验算/提取异常:")
            for msg in issues:
                print(f"  - {msg}")
        else:
            print(f"[INFO] 验算通过: 各列合计与账单 Final total 一致, 总和 {verify_info['grand_sum']:.2f}")
        return all_data_rows, None, verify_info

    print("[INFO] 未识别到参保人布局，回退到通用表格逻辑")
    data_rows, candidate = _extract_generic(pdf_path)
    return data_rows, candidate, None


# ──────────────────────────────────────────────
# Excel 输出
# ──────────────────────────────────────────────
def format_header_cell(cell, text):
    """将多行表头写入单元格"""
    cell.value = text.replace('\n', '\n')
    cell.font = HEADER_FONT
    cell.fill = HEADER_FILL
    cell.alignment = WRAP_ALIGN
    cell.border = THIN_BORDER


def write_excel(data_rows, candidate_header, output_path, verify_info=None):
    wb = Workbook()
    ws = wb.active
    ws.title = "Pension Statement"

    # ── 表头写入 ──
    # 使用标准列名（优先），保持截图标头结构
    header_row_idx = 1

    for col_idx, header_text in enumerate(COLUMNS, start=1):
        cell = ws.cell(row=header_row_idx, column=col_idx)
        format_header_cell(cell, header_text)

    # 如果 PDF 中提取到了额外表头信息，写入第二行作为参考
    if candidate_header:
        for col_idx, text in enumerate(candidate_header, start=1):
            if text:
                cell = ws.cell(row=2, column=col_idx)
                cell.value = text
                cell.font = Font(name="Calibri", italic=True, size=9, color="666666")
                cell.alignment = WRAP_ALIGN
                cell.border = THIN_BORDER
        data_start_row = 3
    else:
        data_start_row = 2

    # ── 数据写入 ──
    for r, row in enumerate(data_rows):
        excel_row = r + data_start_row
        for c, val in enumerate(row):
            cell = ws.cell(row=excel_row, column=c + 1)

            # 尝试解析金额
            money = parse_money(str(val)) if val else None
            if money is not None:
                cell.value = money
                cell.number_format = '#,##0.00'
                cell.alignment = NUM_ALIGN
            else:
                cell.value = str(val).strip() if val else ""
                cell.alignment = Alignment(vertical="center", wrap_text=True)

            cell.font = DATA_FONT
            cell.border = THIN_BORDER

            # 负值标红
            if money is not None and money < 0:
                cell.font = Font(name="Calibri", size=10, color="FF0000")

    # ── 验算结果行：合计 + Final total（保留账单原值） ──
    # 样式：加粗 + 浅色填充，便于与数据区分；验算未通过时数值标红
    SUM_FILL = PatternFill(start_color="DDEBF7", end_color="DDEBF7", fill_type="solid")
    FT_FILL = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")
    SUM_FONT = Font(name="Calibri", bold=True, size=10)
    ALERT_FONT = Font(name="Calibri", bold=True, size=10, color="FF0000")

    if verify_info:
        col_sums = verify_info.get("col_sums") or []
        final_totals = verify_info.get("final_totals") or []
        passed = verify_info.get("passed", False)
        verified = verify_info.get("verified", False)

        # 行1: Total (extracted) —— 提取值的各列求和（与账单 Final total 并排便于比对）
        sum_row = data_start_row + len(data_rows)
        cell = ws.cell(row=sum_row, column=1)
        cell.value = "Total (extracted)"
        cell.font = SUM_FONT
        cell.fill = SUM_FILL
        cell.border = THIN_BORDER
        for i in range(8):
            if i < len(col_sums):
                c = ws.cell(row=sum_row, column=i + 2, value=round(col_sums[i], 2))
                c.number_format = '#,##0.00'
                c.alignment = NUM_ALIGN
                c.font = SUM_FONT
                c.fill = SUM_FILL
                c.border = THIN_BORDER

        # 行2: Final total (bill) —— 账单原文金额，原样保留不做计算
        ft_row = sum_row + 1
        cell = ws.cell(row=ft_row, column=1)
        cell.value = "Final total (bill)"
        cell.font = SUM_FONT
        cell.fill = FT_FILL
        cell.border = THIN_BORDER
        for i in range(8):
            if i < len(final_totals) and final_totals[i] is not None:
                c = ws.cell(row=ft_row, column=i + 2, value=final_totals[i])
                c.number_format = '#,##0.00'
                c.alignment = NUM_ALIGN
                c.font = SUM_FONT
                c.fill = FT_FILL
                c.border = THIN_BORDER

        # 验算未通过/未验证 → 两行合计整体标红，提示需人工核对
        if not passed:
            for r in (sum_row, ft_row):
                for cidx in range(1, 10):
                    cc = ws.cell(row=r, column=cidx)
                    if cc.value is not None and cc.value != "":
                        cc.font = ALERT_FONT

    # ── 列宽 ──
    col_widths = [22, 14, 16, 16, 14, 20, 16, 16, 20]
    for i, w in enumerate(col_widths):
        ws.column_dimensions[get_column_letter(i + 1)].width = w

    # ── 冻结首行 ──
    ws.freeze_panes = f"A{data_start_row}"

    # ── 自动筛选（只含数据区，不含合计行） ──
    ws.auto_filter.ref = f"A{header_row_idx}:{get_column_letter(9)}{data_start_row - 1 + len(data_rows)}"

    # ── 保存 ──
    wb.save(output_path)
    print(f"\n[OK] Excel saved: {output_path}")
    print(f"     Data rows: {len(data_rows)}")
    if verify_info:
        status = "验算通过" if verify_info.get("passed") else f"验算差异 {len(verify_info.get('issues', []))} 项"
        print(f"     验算: {status}, 提取总和 {verify_info.get('grand_sum')}")


# ──────────────────────────────────────────────
# 批量模式：支持预览（dry-run）
# ──────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="养老金 PDF 账单 → Excel 提取工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python pension_pdf_to_excel.py bill.pdf                    # 输出 bill.xlsx
  python pension_pdf_to_excel.py bill.pdf -o output.xlsx     # 指定输出路径
  python pension_pdf_to_excel.py bill.pdf --dry-run          # 仅预览，不生成文件
  python pension_pdf_to_excel.py *.pdf                       # 批量转换
        """,
    )
    parser.add_argument("pdf_files", nargs="+", help="一个或多个 PDF 文件路径")
    parser.add_argument("-o", "--output", help="输出 Excel 路径 (单文件模式)")
    parser.add_argument("--dry-run", action="store_true", help="仅预览提取内容，不保存")
    args = parser.parse_args()

    for pdf_path in args.pdf_files:
        if not os.path.exists(pdf_path):
            print(f"[ERROR] File not found: {pdf_path}")
            continue

        print(f"\n{'='*60}")
        print(f"Processing: {pdf_path}")
        print(f"{'='*60}")

        data_rows, candidate_header, verify_info = extract_from_pdf(pdf_path)

        if args.dry_run:
            print(f"\nPreview (first 10 rows):")
            print("-" * 100)
            for i, row in enumerate(data_rows[:10]):
                print(f"  [{i}] " + " | ".join(str(c).strip() for c in row))
            print(f"... total {len(data_rows)} data rows")
            if verify_info:
                if verify_info["issues"]:
                    print("\n[WARN] 验算发现差异:")
                    for msg in verify_info["issues"]:
                        print(f"  - {msg}")
                else:
                    print(f"\n[OK] 验算通过: 提取总和 {verify_info['grand_sum']:.2f} 与账单 Final total 一致")
            continue

        if not data_rows:
            print("[WARN] No data to output.")
            continue

        # 确定输出路径
        if args.output and len(args.pdf_files) == 1:
            out_path = args.output
        else:
            base = Path(pdf_path).stem
            out_path = str(Path(pdf_path).parent / f"{base}.xlsx")

        write_excel(data_rows, candidate_header, out_path, verify_info)

    print("\nDone!")


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""波兰考勤 report/raport 表汇总的共享模块。

供 merge_all.py（生成「Report汇总(指定表头)」工作表）与
build_report_summary.py（生成两种独立工作簿）以及 GUI 工具共用，
保证列映射规则只有一份实现。

两种输出格式：
  A. 指定表头（canonical）：按用户给的模板表头（16 列）对齐，全部文件堆叠到一张表。
  B. 原始字段（raw）：每个文件一张分表，保留各自原始表头，不做对齐。
"""
import os
import re
import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

# ---- 每个目标列的匹配模式（按优先级）----
# 单元格引用(n16/n20/n25/h35/i35/k36)用于区分重复列
MATCH = {
    0: ['id'],
    1: ['row labels'],
    2: ['norma'],
    3: ['wszystkie godziny'],
    4: ['przepracowane godziny'],
    5: ['n16', 'urlop wypoczynkowy'],
    6: ['urlop na żądanie'],
    7: ['n25', 'inne nieobecność usprawiedliwiona płatna', 'other paid leaves'],
    8: ['nn nieobecność'],
    9: ['no paid leave'],
    10: ['urlop okolicznościowy'],
    11: ['n20', 'zwolnienie lekarskie'],
    12: ['h35', 'godziny nocne'],
    13: ['i35', 'nadgodziny 50%'],
    14: ['k36', 'nadgodziny 100%'],
    15: ['suma nadgodzin'],
}

SKIP_LABELS = {'', 'blank', '(blank)', 'grand total', 'suma', 'total', 'razem', 'ogółem'}

HDR_FILL = PatternFill('solid', fgColor='4472C4')
HDR_FONT = Font(bold=True, color='FFFFFF')
HDR_ALIGN = Alignment(horizontal='center', vertical='center', wrap_text=True)
THIN = Side(style='thin', color='D0D0D0')
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def src_label(f):
    """由文件名得到站点标签。"""
    name = os.path.basename(f).replace('.xlsx', '').replace('.XLSX', '')
    name = re.sub(r'^OK - Tabelki ', '', name)
    name = re.sub(r'^Tabelki ', '', name)
    return name


def norm(s):
    return re.sub(r'\s+', ' ', str(s).strip().lower())


def r2(x):
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        if abs(x) < 1e-9:
            return 0
        return round(x, 2)
    return x


def clean_label(s):
    return re.sub(r'[^a-z0-9一-鿿 ]', '', norm(s))


def find_report_sheet(wb):
    for s in wb.sheetnames:
        if 'report' in s.lower() or 'raport' in s.lower():
            return s
    return None


def load_target_headers(template_file):
    """读取模板文件第一张表的第一行作为规范表头。"""
    twb = openpyxl.load_workbook(template_file, data_only=True)
    tws = twb[twb.sheetnames[0]]
    return [c.value for c in tws[1]]


def build_matched(header, n_target):
    """把源表列映射到目标列下标。"""
    matched = {}
    for ti in range(n_target):
        pats = MATCH.get(ti, [])
        found = None
        for pat in pats:
            for ci, h in enumerate(header):
                if h is None:
                    continue
                if pat in norm(h):
                    found = ci
                    break
            if found is not None:
                break
        matched[ti] = found
    return matched


def build_canonical_rows(files, template_file, verbose=False):
    """格式A：按模板表头对齐，返回 (target_headers, rows)。rows 首列为来源文件。"""
    target = load_target_headers(template_file)
    n = len(target)
    rows = []
    for f in files:
        src = src_label(f)
        wb = openpyxl.load_workbook(f, read_only=True, data_only=True)
        sname = find_report_sheet(wb)
        if sname is None:
            wb.close()
            if verbose:
                print(f"  [跳过] {src}：未找到 report/raport 表")
            continue
        ws = wb[sname]
        all_rows = list(ws.iter_rows(min_row=1, max_row=ws.max_row, values_only=True))
        wb.close()
        if not all_rows:
            continue
        header = list(all_rows[0])
        matched = build_matched(header, n)
        if verbose:
            print(f"--- {src} (sheet '{sname}')")
            for ti in range(n):
                ci = matched[ti]
                print(f"  [{ti}] {target[ti]!r} -> col{ci}: "
                      f"{norm(header[ci]) if ci is not None else 'NONE'!r}")
        for r in all_rows[1:]:
            rl = r[1] if len(r) > 1 else None
            if rl is None or clean_label(rl) in SKIP_LABELS:
                continue
            # 必须含核心数值（Norma/总工时/工作工时 任一非空），否则视为空行或错位行丢弃
            core = []
            for ti in (2, 3, 4):
                ci = matched[ti]
                if ci is not None and ci < len(r):
                    core.append(r[ci])
            if all(v in (None, '') for v in core):
                continue
            out = [src]
            for ti in range(n):
                ci = matched[ti]
                val = r[ci] if (ci is not None and ci < len(r)) else None
                out.append(r2(val))
            rows.append(out)
    return target, rows


def write_canonical_sheet(ws, target, rows):
    """把格式A数据写入已有工作表（用于并入合并汇总簿）。"""
    n = len(target)
    ws.append(['来源文件'] + target)
    for row in rows:
        ws.append(row)
    for c in range(1, n + 2):
        cell = ws.cell(1, c)
        cell.fill = HDR_FILL
        cell.font = HDR_FONT
        cell.alignment = HDR_ALIGN
        cell.border = BORDER
    ws.row_dimensions[1].height = 42
    ws.freeze_panes = 'A2'
    ws.auto_filter.ref = f"A1:{get_column_letter(n + 1)}{ws.max_row}"
    for i in range(1, n + 2):
        ws.column_dimensions[get_column_letter(i)].width = 16
    ws.column_dimensions['A'].width = 26
    ws.column_dimensions['B'].width = 22
    return ws


def build_canonical_workbook(files, template_file, out_path, verbose=False):
    """生成独立的「指定表头」工作簿。返回行数。"""
    target, rows = build_canonical_rows(files, template_file, verbose=verbose)
    owb = openpyxl.Workbook()
    ws = owb.active
    ws.title = 'Report汇总(指定表头)'
    write_canonical_sheet(ws, target, rows)
    owb.save(out_path)
    return len(rows)


def build_raw_workbook(files, out_path):
    """格式B：每个文件一张分表，保留原始表头。返回分表数。"""
    owb = openpyxl.Workbook()
    owb.remove(owb.active)
    used = {}
    for f in files:
        src = src_label(f)
        wb = openpyxl.load_workbook(f, read_only=True, data_only=True)
        sname = find_report_sheet(wb)
        if sname is None:
            wb.close()
            continue
        ws = wb[sname]
        rows = list(ws.iter_rows(min_row=1, max_row=ws.max_row, values_only=True))
        wb.close()
        if not rows:
            continue
        maxc = 0
        for r in rows:
            for i, v in enumerate(r):
                if v is not None:
                    maxc = max(maxc, i)
        base = src[:31]
        nm, k = base, 1
        while nm in used:
            k += 1
            nm = f"{base[:27]}_{k}"
        used[nm] = True
        sh = owb.create_sheet(title=nm)
        for r in rows:
            sh.append([r2(v) for v in r[:maxc + 1]])
        for c in range(1, maxc + 2):
            cell = sh.cell(1, c)
            cell.fill = HDR_FILL
            cell.font = HDR_FONT
            cell.alignment = HDR_ALIGN
            cell.border = BORDER
        sh.freeze_panes = 'A2'
    owb.save(out_path)
    return len(used)

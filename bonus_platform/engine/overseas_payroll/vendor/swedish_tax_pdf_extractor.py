#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
瑞典税务 PDF 提取工具 (Arbetsgivardeklaration / KU10 风格, 文字版 PDF)
-----------------------------------------------------------------------
功能:
  1. 遍历输入文件夹内的所有文字版 PDF。
  2. 按 "Ruta 表格上方第一行" 的抬头行切分每位员工。
  3. 提取每位员工的身份信息 + 每个 Ruta 行的 (Ruta / Namn / Värde)。
  4. 提取雇主税金额 (Beräknad arbetsgivaravgift)。
  5. 金额规范化: 去空格, 逗号转小数点, 保留负号。
  6. 输出 Excel, 含两个 Sheet:
       - "Ruta明细": 长表, 每人每个 Ruta 一行, 三列严格拆开。
       - "金额透视": 矩阵, 行=人, 列=Ruta 代码(标注 Namn), 格=Värde_raw。

用法:
  python swedish_tax_pdf_extractor.py --input <PDF文件夹> --output <结果.xlsx>
  python swedish_tax_pdf_extractor.py --selftest   # 生成样例 PDF 并自测
"""

import argparse
import os
import re
import sys
import tempfile

import pdfplumber
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side


# ---------------------------------------------------------------------------
# 配置区 (可按实际 PDF 微调)
# ---------------------------------------------------------------------------
HEADER_RE = re.compile(r"^\s*(\d{3,4})\s*[-–—]\s+(.+?)\s*$")              # 001 - Li Sun / 001 – Li Sun
HEADER_RE2 = re.compile(r"^\s*(?:KU10|Kontrolluppgift)\s*[\-:]\s*(.+?)\s*$")  # KU10 - Li Sun / KU10:Li Sun
PERSONNR_RE = re.compile(r"Person-?/?samordnings-?/?organisationsnummer\s*([\d\-]{12,13})", re.I)
SPEC_RE = re.compile(r"Specifikationsnummer\s*(\d+)", re.I)
FORNAMN_RE = re.compile(r"Förnamn\s+(\S+)", re.I)
EFTERNAMN_RE = re.compile(r"Efternamn\s+(\S+)", re.I)
RUTA_LINE_RE = re.compile(r"^(\d{3})\s+(.+?)\s+([\d\s,.\-]{3,})\s*$")     # 011  Kontant bruttolön m.m.  47 250
AMOUNT_RE = re.compile(r"^[\d\s,.\-]{3,}$")


# ---------------------------------------------------------------------------
# 金额规范化
# ---------------------------------------------------------------------------
def normalize_amount(raw: str):
    """瑞典语数字 -> 可计算数字。空格=千分位, 逗号=小数点。
    返回 (规范字符串, 浮点值 或 None)"""
    if raw is None:
        return None, None
    s = raw.strip()
    s = s.replace("\u00a0", "").replace(" ", "")          # 去所有空格/不间断空格
    if "," in s and "." in s:
        s = s.replace(".", "")                            # 同时存在则点为千分位
    s = s.replace(",", ".")
    s = s.strip()
    if s in ("", "-", "."):
        return raw.strip(), None
    try:
        val = float(s)
        return s, val
    except ValueError:
        return raw.strip(), None


def norm_display(raw):
    """透视表显示用: 仅当 raw 是瑞典格式金额(只含数字/空格/逗号/负号)时,
    返回规范字符串; 否则原样返回。
    例: '46 856' -> '46856', '36 805,70' -> '36805.70',
        '198708076727' -> '198708076727' (个人号原样),
        'SE4320...' / 'Brf Korpen' -> 原样 (非数字)。"""
    if raw is None:
        return ""
    s = str(raw)
    if re.match(r"^-?[\d\s,\u00a0]+$", s):
        return s.replace("\u00a0", "").replace(" ", "").replace(",", ".")
    return s


def extract_employer_tax(text):
    """在区块内定位 'Beräknad arbetsgivaravgift' 并取其后的金额。
    兼容两种换行: 同行 '... (inklusive ören) 36 805,70' 或
    拆行 '... (inklusive' / '25 136,00' / 'ören)'。"""
    idx = text.find("Beräknad arbetsgivaravgift")
    if idx == -1:
        return None
    tail = text[idx:]
    for m in re.finditer(r"[\d\s,.\-]{3,}", tail):
        s = m.group(0).strip()
        if not s:
            continue
        digits = re.sub(r"\D", "", s)
        # 金额特征: 含逗号小数点 / 含空格千分位 / 纯数字长度>=4
        if "," in s or " " in s or len(digits) >= 4:
            return s
    return None


# ---------------------------------------------------------------------------
# 单页解析
# ---------------------------------------------------------------------------
def parse_block(block_lines, source_file, page_no, form_code, header_id, full_name):
    """解析单个员工区块 (从抬头行到下一个抬头行之间的所有行)。"""
    block_text = "\n".join(block_lines)

    # 雇主税 (仅在本区块内搜索) -- 保留原始文本 + 规范值
    employer_raw = extract_employer_tax(block_text)
    employer_val = normalize_amount(employer_raw)[1] if employer_raw else None

    rec = {
        "source_file": source_file,
        "page": page_no,
        "form_code": form_code,
        "header_id": header_id,
        "full_name": full_name,
        "spec_no": None,
        "personnummer": None,
        "fornamn": None,
        "efternamn": None,
        "ruta_rows": [],
        "employer_tax_raw": employer_raw,
        "employer_tax": employer_val,
    }

    pm = PERSONNR_RE.search(block_text)
    if pm:
        rec["personnummer"] = re.sub(r"\D", "", pm.group(1))
    sm = SPEC_RE.search(block_text)
    if sm:
        rec["spec_no"] = sm.group(1)
    fm = FORNAMN_RE.search(block_text)
    if fm:
        rec["fornamn"] = fm.group(1)
    em = EFTERNAMN_RE.search(block_text)
    if em:
        rec["efternamn"] = em.group(1)

    # 逐行解析 Ruta 表
    i = 0
    n = len(block_lines)
    while i < n:
        line = block_lines[i]
        # 跳过员工抬头行本身 (如 "004 - 12345 Qianchen Ren")
        if HEADER_RE.match(line):
            i += 1
            continue
        # 跳过 Ruta 表自身的表头行 (如 "Ruta  Namn  Värde")
        if line.strip().startswith("Ruta") and "Namn" in line:
            i += 1
            continue

        rm = RUTA_LINE_RE.match(line)
        if rm:
            ruta = rm.group(1)
            namn = rm.group(2).strip()
            raw = rm.group(3).strip()          # 原始文本
            val = normalize_amount(raw)[1]     # 规范值
            rec["ruta_rows"].append((ruta, namn, raw, val))
            i += 1
            continue

        rm2 = re.match(r"^(\d{3})\s+(.+)$", line)
        if rm2:
            ruta = rm2.group(1)
            namn = rm2.group(2).strip()
            j = i + 1
            amount_raw = None
            while j < n:
                nxt = block_lines[j].strip()
                if nxt == "":
                    j += 1
                    continue
                if AMOUNT_RE.match(nxt):
                    amount_raw = nxt
                    break
                if re.match(r"^\d{3}\s+", nxt) or HEADER_RE.match(nxt):
                    break
                namn += " " + nxt
                j += 1
            raw = amount_raw.strip() if amount_raw else None
            val = normalize_amount(raw)[1] if raw else None
            rec["ruta_rows"].append((ruta, namn.strip(), raw, val))
            i = j + 1
            continue

        i += 1

    return rec


def _match_header_line(ln):
    """尝试多种抬头行格式，返回 (header_id, full_name) 或 None。"""
    m = HEADER_RE.match(ln)
    if m:
        return m.group(1), m.group(2).strip()
    m = HEADER_RE2.match(ln)
    if m:
        return "KU10", m.group(1).strip()
    return None


def parse_page(page, source_file, page_no):
    """按抬头行切分员工区块, 逐块解析。
    兼容真实 Arbetsgivardegklaration PDF 中抬头行不固定的情况：
    - 若匹配不到标准抬头行，但页面包含瑞典税务关键词，
      将整个页面作为一个员工块兜底解析。"""
    text = page.extract_text() or ""
    lines = text.split("\n")
    if not lines or all(not ln.strip() for ln in lines):
        return []

    # 找到所有抬头行索引（支持多种格式）
    header_idx = []
    for i, ln in enumerate(lines):
        if _match_header_line(ln):
            header_idx.append(i)

    # 兜底：没有任何抬头行，但页面明显是瑞典税务表
    if not header_idx:
        lowered = text.lower()
        swedish_markers = (
            "person-" in lowered or "samordnings" in lowered or
            "specifikationsnummer" in lowered or "arbetsgivaravgift" in lowered or
            "kontrolluppgift" in lowered or ("ruta" in lowered and "namn" in lowered)
        )
        if swedish_markers:
            try:
                rec = parse_block(lines, source_file, page_no,
                                  str(page_no), str(page_no), "")
                if rec["ruta_rows"] or rec.get("personnummer") or rec.get("spec_no"):
                    return [rec]
            except Exception as e:
                import traceback as _tb
                print(f"[WARN] 瑞典工具 第{page_no}页 兜底解析跳过: {e}")
                print(_tb.format_exc())
        return []

    records = []
    for k, idx in enumerate(header_idx):
        try:
            header_id, full_name = _match_header_line(lines[idx])
            start = idx
            end = header_idx[k + 1] if k + 1 < len(header_idx) else len(lines)
            block = lines[start:end]
            rec = parse_block(block, source_file, page_no,
                              header_id, header_id, full_name)
            records.append(rec)
        except Exception as e:
            import traceback as _tb
            print(f"[WARN] 瑞典工具 第{page_no}页 员工区块解析跳过: {e}")
            print(_tb.format_exc())
    return records



# ---------------------------------------------------------------------------
# 遍历 PDF 文件夹 / 单个 PDF 文件
# ---------------------------------------------------------------------------
def extract_from_folder(input_dir):
    all_records = []
    for fn in sorted(os.listdir(input_dir)):
        if not fn.lower().endswith(".pdf"):
            continue
        path = os.path.join(input_dir, fn)
        with pdfplumber.open(path) as pdf:
            for idx, page in enumerate(pdf.pages, start=1):
                recs = parse_page(page, fn, idx)
                all_records.extend(recs)
    return all_records


def extract_from_path(input_path):
    """input_path 可以是文件夹(处理其中所有 PDF) 或单个 .pdf 文件。"""
    if os.path.isfile(input_path):
        if not input_path.lower().endswith(".pdf"):
            sys.exit(f"输入不是 PDF 文件: {input_path}")
        recs = []
        try:
            with pdfplumber.open(input_path) as pdf:
                for idx, page in enumerate(pdf.pages, start=1):
                    try:
                        recs.extend(parse_page(page, os.path.basename(input_path), idx))
                    except Exception as e:
                        import traceback as _tb
                        print(f"[WARN] 瑞典工具 第{idx}页解析跳过: {e}")
                        print(_tb.format_exc())
        except Exception as e:
            import traceback as _tb
            print(f"[ERROR] 瑞典工具 无法打开 PDF（可能加密/损坏/非文本层）: {e}")
            print(_tb.format_exc())
        if not recs:
            print("[WARN] 瑞典工具 未能提取到任何员工记录（可能是扫描件图片型 PDF，或非瑞典税务表格式）")
        return recs
    if os.path.isdir(input_path):
        return extract_from_folder(input_path)
    sys.exit(f"输入路径不存在: {input_path}")


# ---------------------------------------------------------------------------
# 写出 Excel
# ---------------------------------------------------------------------------
def write_excel(records, output_path):
    wb = Workbook()

    # ---- Sheet 1: Ruta明细 (长表) ----
    ws1 = wb.active
    ws1.title = "Ruta明细"
    headers1 = ["source_file", "page", "form_code", "header_id", "full_name",
                "spec_no", "personnummer", "Ruta", "Namn", "Värde_raw", "Värde"]
    ws1.append(headers1)
    for rec in records:
        for (ruta, namn, raw, val) in rec["ruta_rows"]:
            ws1.append([
                rec["source_file"], rec["page"], rec["form_code"], rec["header_id"],
                rec["full_name"], rec["spec_no"] or "", rec["personnummer"] or "",
                ruta, namn, raw if raw is not None else "",
                val if val is not None else ""
            ])

    # ---- 收集所有 Ruta 代码, 用于透视表列 ----
    ruta_codes = set()
    ruta_namn = {}
    for rec in records:
        for (ruta, namn, raw, val) in rec["ruta_rows"]:
            ruta_codes.add(ruta)
            ruta_namn.setdefault(ruta, namn)
    ruta_codes = sorted(ruta_codes)

    # 以 (source_file, page, header_id, full_name) 为人员 key
    people = {}
    order = []
    for rec in records:
        key = (rec["source_file"], rec["page"], rec["header_id"], rec["full_name"])
        if key not in people:
            people[key] = {
                "source_file": rec["source_file"], "page": rec["page"],
                "header_id": rec["header_id"], "full_name": rec["full_name"],
                "ruta_map": {}, "employer_tax_raw": rec["employer_tax_raw"]
            }
            order.append(key)
        for (ruta, namn, raw, val) in rec["ruta_rows"]:
            if raw is not None:
                people[key]["ruta_map"][ruta] = raw

    # ---- Sheet 2: 金额透视 (矩阵) ----
    ws2 = wb.create_sheet("金额透视")
    headers2 = ["source_file", "page", "header_id", "full_name"]
    for rc in ruta_codes:
        headers2.append(f"Ruta {rc}\n({ruta_namn.get(rc, '')})")
    headers2.append("雇主税")
    ws2.append(headers2)
    for key in order:
        p = people[key]
        row = [p["source_file"], p["page"], p["header_id"], p["full_name"]]
        for rc in ruta_codes:
            row.append(norm_display(p["ruta_map"].get(rc, "")))
        row.append(norm_display(p["employer_tax_raw"]) or "")
        ws2.append(row)

    # ---- 简单样式 ----
    thin = Side(style="thin", color="D0D0D0")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    head_fill = PatternFill("solid", fgColor="F3F4F6")
    head_font = Font(bold=True, size=11)
    for ws in (ws1, ws2):
        for c in ws[1]:
            c.fill = head_fill
            c.font = head_font
            c.alignment = Alignment(vertical="center", wrap_text=True)
        for row in ws.iter_rows():
            for c in row:
                c.border = border
        ws.freeze_panes = "A2"

    wb.save(output_path)


# ---------------------------------------------------------------------------
# 自测: 生成模拟 PDF 并跑通流程
# ---------------------------------------------------------------------------
def selftest():
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4

    tmpdir = tempfile.mkdtemp(prefix="swetax_")
    pdf_path = os.path.join(tmpdir, "sample.pdf")
    c = canvas.Canvas(pdf_path, pagesize=A4)
    c.setFont("Helvetica", 10)

    y = 800
    def line(txt):
        nonlocal y
        c.drawString(50, y, txt)
        y -= 16

    # 员工 1
    line("004 - 12345 Qianchen Ren")
    line("Person-/samordnings-/organisationsnummer 199307148321")
    line("Specifikationsnummer 1")
    line("Förnamn Qianchen")
    line("Efternamn Ren")
    line("")
    line("Ruta  Namn                                           Värde")
    line("011   Kontant bruttolön m.m.                         47 250")
    line("001   Avdragen preliminärskatt                       10 844")
    line("012   Skattepliktig förmån                           2 000")
    line("")
    line("Full arbetsgivaraavgift för födda 1959 -")
    line("Beräknad arbetsgivaravgift (inklusive ören)         14 845,95")
    y -= 20
    # 员工 2
    line("004 - 12346 Anna Andersson")
    line("Person-/samordnings-/organisationsnummer 198512073214")
    line("Specifikationsnummer 2")
    line("Förnamn Anna")
    line("Efternamn Andersson")
    line("")
    line("Ruta  Namn                                           Värde")
    line("011   Kontant bruttolön m.m.                         38 000")
    line("001   Avdragen preliminärskatt                       8 920")
    line("")
    line("Full arbetsgivaraavgift för födda 1959 -")
    line("Beräknad arbetsgivaravgift (inklusive ören)         11 939,60")

    c.showPage()
    c.save()

    out_xlsx = os.path.join(tmpdir, "sample_output.xlsx")
    recs = extract_from_folder(tmpdir)
    write_excel(recs, out_xlsx)

    print(f"[SELFTEST] 生成样例 PDF: {pdf_path}")
    print(f"[SELFTEST] 解析到员工记录数: {len(recs)}")
    for r in recs:
        print(f"  - {r['full_name']} (id={r['header_id']}) Ruta行={len(r['ruta_rows'])} 雇主税={r['employer_tax_raw']}")

    # 打印 Excel 内容核对
    from openpyxl import load_workbook
    wb = load_workbook(out_xlsx)
    for ws in wb.worksheets:
        print(f"\n=== Sheet: {ws.title} ({ws.max_row} 行 x {ws.max_column} 列) ===")
        for ridx, row in enumerate(ws.iter_rows(values_only=True), start=1):
            if ridx > 8:
                print("  ... (截断)")
                break
            print("  ", [str(c)[:22] if c is not None else "" for c in row])

    print(f"[SELFTEST] 输出 Excel: {out_xlsx}")
    return out_xlsx


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="瑞典税务 PDF 提取工具")
    ap.add_argument("--input", help="PDF 文件夹路径")
    ap.add_argument("--output", help="输出 Excel 路径")
    ap.add_argument("--selftest", action="store_true", help="生成样例 PDF 并自测")
    args = ap.parse_args()

    if args.selftest:
        selftest()
        return

    if not args.input or not args.output:
        ap.error("请指定 --input 与 --output (或使用 --selftest)")

    records = extract_from_path(args.input)
    write_excel(records, args.output)
    print(f"完成: 共 {len(records)} 名员工记录, 结果已写入 {args.output}")


if __name__ == "__main__":
    main()

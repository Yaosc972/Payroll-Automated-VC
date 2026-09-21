#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
波兰工资单 PDF 提取工具
Polish Payroll PDF Extractor

Usage:
    双击运行 "启动.bat" 或 python pdf_payroll_extractor.py

Features:
    - 导入 PDF（文本型），自动提取 PRACOWNIK 列数据
    - 字段：姓名、基本工资、标准工时、总工时、Urlopy、ZUS、NN、Inne、Nadg.50、Nadg.100、Nocne
    - 输出到 Excel（同一目录下，文件名 <原名>_提取结果.xlsx）
"""

import os
import re
import sys
import threading
from datetime import datetime

import fitz  # PyMuPDF
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side


# ============== PDF 解析 ==============

# PRACOWNIK 列在 PDF 中的 x 坐标范围
PRACOWNIK_X_MAX = 140
# 视觉行 y 坐标容差（像素）
Y_TOLERANCE = 2.5
# 表头识别文本（出现这些文本的行视为表头，跳过）
HEADER_TEXTS = {
    "PRACOWNIK [AKRONIM]", "LP", "STAWKA **", "CZAS PRACY",
    "EL. WYPŁATY", "WARTOŚĆ", "SKŁADKI   ZUS", "SKŁADKI   PPK",
    "OPODAT.", "NIEOPOD.", "UBEZPIECZ.", "PŁATNIK",
    "ZAL. POD.", "ZDROW.", "KOSZTY", "ULGA POD.", "ZAN. POD.",
    "DO WYPŁATY",
}

# PDF 末尾摘要/页脚文本（触发停止解析，防止误匹配覆盖最后一人的数据）
STOP_TEXTS = {
    "PODSUMOWANIE", "Zasiłki", "Wynagrodzenia", "CZAS:",
    "Sprawdzono pod", "Zatwierdzono na", "Do wypłaty:",
    "Słownie", "Operator drukujący",
}


def _is_header_row(row):
    """判断一行是否为表头。"""
    text = row_text(row).strip()
    if text in HEADER_TEXTS:
        return True
    # 包含多个表头文本的行也视为表头
    hits = sum(1 for t in HEADER_TEXTS if t in text)
    return hits >= 2


def extract_pracownik_spans(page):
    """从单页 PDF 中提取 PRACOWNIK 列的 spans（含坐标），跳过表头。"""
    text_dict = page.get_text("dict")
    spans = []
    for block in text_dict.get("blocks", []):
        if "lines" not in block:
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                x, y, x1, y1 = span["bbox"]
                if x < PRACOWNIK_X_MAX and y > 80:
                    spans.append({
                        "x": x,
                        "y": y,
                        "x1": x1,
                        "text": span["text"],
                    })
    spans.sort(key=lambda s: (s["y"], s["x"]))

    # 跳过表头：把所有连续出现在页面顶部的表头 span 过滤掉
    # 策略：先用 group_into_rows 分组，找出连续表头行，丢弃其 y 以下（含）的 spans
    if not spans:
        return spans
    rows = group_into_rows(spans, tolerance=Y_TOLERANCE)
    cut_y = None
    for row in rows:
        if _is_header_row(row):
            cut_y = max(s["y1"] if "y1" in s else s["y"] for s in row)
        else:
            break
    if cut_y is not None:
        spans = [s for s in spans if s["y"] > cut_y + 1]
    return spans


def group_into_rows(spans, tolerance=Y_TOLERANCE):
    """将 spans 按 y 坐标聚合成视觉行。每行内按 x 排序。"""
    rows = []
    current_row = []
    current_y = None
    for span in spans:
        if current_y is None or abs(span["y"] - current_y) <= tolerance:
            current_row.append(span)
            if current_y is None:
                current_y = span["y"]
        else:
            current_row.sort(key=lambda s: s["x"])
            rows.append(current_row)
            current_row = [span]
            current_y = span["y"]
    if current_row:
        current_row.sort(key=lambda s: s["x"])
        rows.append(current_row)
    return rows


def row_text(row):
    """把一行内的所有 span 文本拼接起来（按 x 排序后）。"""
    return "".join(s["text"] for s in row)


def row_left_text(row, x_max=35):
    """一行内 x < x_max 的文本（用于识别 LP）。"""
    return "".join(s["text"] for s in row if s["x"] < x_max).strip()


def extract_value_from_row(row, x_min=70):
    """从一行中提取右侧的值（数字和斜杠），去除空格和多余斜杠。"""
    parts = [s["text"] for s in row if s["x"] >= x_min]
    text = "".join(parts)
    cleaned = re.sub(r"[^\d/]", "", text)
    cleaned = re.sub(r"/+", "/", cleaned)
    return cleaned


def extract_time_from_row(row, x_min=70):
    """从一行中提取右侧的时间字符串 (HH:MM)。"""
    parts = [s["text"] for s in row if s["x"] >= x_min]
    text = "".join(parts)
    m = re.search(r"\d{1,3}:\d{2}", text)
    return m.group(0) if m else ""


def row_has_bracket(row):
    """判断一行内是否包含 '['。"""
    return any("[" in s["text"] for s in row)


def row_text_after_bracket(row):
    """从一行中提取 ']' 之后的文本（即 first name，可能在下一行）。"""
    full = row_text(row)
    m = re.search(r"\]\s*(.+)$", full)
    return m.group(1).strip() if m else ""


def new_worker(lp):
    return {
        "lp": lp,
        "name": "",
        "salary": 0,
        "standard_hours": "",
        "total_hours": "",
        "urlopy": "",
        "zus": "",
        "nn": "",
        "inne": "",
        "nadg50": "",
        "nadg100": "",
        "nocne": "",
    }


def _normalize_pl(s):
    """去除波兰语变音符号，仅用于比较（ł → l, ą → a 等）。"""
    return s.translate(str.maketrans({
        "ą": "a", "ć": "c", "ę": "e", "ł": "l", "ń": "n",
        "ó": "o", "ś": "s", "ź": "z", "ż": "z",
        "Ą": "A", "Ć": "C", "Ę": "E", "Ł": "L", "Ń": "N",
        "Ó": "O", "Ś": "S", "Ź": "Z", "Ż": "Z",
    }))


def _merge_name_with_extra(name, extra, allow_prefix_extend=False):
    """把额外名字合并到 AKRONIM 名字里。

    allow_prefix_extend:
      - True 时（括号有 '_' 被截断的情况），允许 extra 替换 ak_word 的前缀-扩展版本
      - False 时（括号完整无 '_'），只去重 + 追加

    例：name='HEYDAR ALIYEV', extra='HEYDAR', allow_prefix_extend=False → 'HEYDAR ALIYEV'（去重）
        name='PRZYBYŁ RADOS', extra='RADOSŁAW', allow_prefix_extend=True → 'PRZYBYŁ RADOSŁAW'（前缀扩展）
        name='XIAO', extra='XI', allow_prefix_extend=False → 'XIAO XI'（直接追加）
        name='XIAO', extra='XI', allow_prefix_extend=True → 'XIAO'（错误合并）
    """
    name_words = name.split()
    existing_norms = {_normalize_pl(w.upper()) for w in name_words}
    for w in extra.split():
        w_n = _normalize_pl(w.upper())
        if w_n in existing_norms:
            continue
        replaced = False
        if allow_prefix_extend:
            for i, ak_w in enumerate(name_words):
                ak_n = _normalize_pl(ak_w.upper())
                if len(ak_n) < 2:
                    continue
                if w_n.startswith(ak_n) and w_n != ak_n:
                    name_words[i] = w
                    existing_norms.discard(ak_n)
                    existing_norms.add(w_n)
                    replaced = True
                    break
                if ak_n.startswith(w_n) and ak_n != w_n:
                    replaced = True
                    break
        if not replaced:
            name_words.append(w)
            existing_norms.add(w_n)
    return " ".join(name_words)


def extract_full_name(text, lp=""):
    """提取完整名字。

    PDF 格式观察：
      - 方括号 [...] 内是 AKRONIM，可能被截断
      - 当 [...] 有闭合 ']' 时，AKRONIM 是完整的
      - 当 [...] 没有 ']' 时，是被截断的（PRACOWNIK 列宽不够），
        此时 '[' 之前的部分（去掉 LP）是完整的姓氏
      - 截断的 AKRONIM 偶尔还有多词尾巴（如 ABATE_ MUSE MULU），
        提供了完整名字的其他部分
      - 偶有方括号内是独立片段（如 LP 10 的 [MOXIYILE]），与之前的
        'BRAK DANYCH' 不重叠，需要拼接

    算法：
      1) 拆出 before='[' 之前 与 after=方括号内（去掉首段重复）
      2) 若 after 与 before 是子集关系，取较长的那一边（用 after 的完整写法）
      3) 否则按序拼接并去重
    """
    body = text.strip()
    if lp:
        body = re.sub(r"^\s*\d+\s*", "", body).strip()

    if "[" not in body:
        # 没有方括号：整行作为名字
        return body

    before_raw = body.split("[", 1)[0].strip()
    # 判断方括号是否闭合、有 '_'
    m_close = re.search(r"\[([^\]]*)\]", text)
    if m_close:
        tail_raw = m_close.group(1).strip()
        tail_split = tail_raw.replace("_", " ").split()
        is_truncated = False
    else:
        m_open = re.search(r"\[([^\]]*)", text)
        if m_open and "_" in m_open.group(1):
            parts = m_open.group(1).strip().split("_", 1)
            tail_raw = parts[1].strip() if len(parts) == 2 else ""
            tail_split = tail_raw.replace("_", " ").split()
            is_truncated = True
        else:
            tail_split = []

    # 过滤掉 < 2 字符的碎片（如 M、NN 等被截断的字母）
    before_words = [w for w in before_raw.split() if len(w) >= 2]
    after_words = [w for w in tail_split if len(w) >= 2]

    if not after_words:
        # 括号内没可用内容，用 before
        return " ".join(before_words) if before_words else before_raw
    if not before_words:
        # before 没东西（如整名都在方括号里），用 after
        return " ".join(after_words)

    before_norms = {_normalize_pl(w.upper()) for w in before_words}
    after_norms = {_normalize_pl(w.upper()) for w in after_words}

    # 若 before ⊆ after：after 已包含姓氏，直接采用 after
    if before_norms.issubset(after_norms):
        # 即使截断也优先 after，因为里面有完整名字
        return " ".join(after_words)
    # 若 after ⊆ before：before 已包含所有信息
    if after_norms.issubset(before_norms):
        return " ".join(before_words)

    # 否则两边互补：拼接去重
    seen = set()
    result = []
    for w in before_words + after_words:
        n = _normalize_pl(w.upper())
        if n not in seen:
            seen.add(n)
            result.append(w)
    return " ".join(result)


def parse_workers_from_rows(rows):
    """从视觉行列表中解析出所有 worker 记录。"""
    if not rows:
        return []

    workers = []
    current = None
    i = 0
    n = len(rows)

    # 标记哪些行已经被消费（防止重复处理）
    consumed = [False] * n

    def consume(idx):
        if 0 <= idx < n:
            consumed[idx] = True

    def get_text(idx):
        if 0 <= idx < n and not consumed[idx]:
            return row_text(rows[idx])
        return ""

    def is_blank(idx):
        if 0 <= idx < n and not consumed[idx]:
            return row_text(rows[idx]).strip() == ""
        return True

    def next_nonblank(idx):
        """从 idx+1 起找下一个未被消费且非空白的行。"""
        j = idx + 1
        while j < n and (consumed[j] or row_text(rows[j]).strip() == ""):
            j += 1
        return j if j < n else -1

    while i < n:
        if consumed[i]:
            i += 1
            continue

        row = rows[i]
        text = row_text(row)
        left = row_left_text(row)

        # 跳过纯空白行
        if text.strip() == "":
            i += 1
            continue

        # 0) 检测页脚/摘要文本：停止解析，防止误匹配覆盖最后一人数据
        if any(t in text for t in STOP_TEXTS) and current is not None:
            if current["salary"] > 0:
                workers.append(current)
                current = None
            break

        # 1) LP 行：左侧是独立数字（可能同行右侧还有 Name）
        if re.fullmatch(r"\s*\d+\s*", left):
            if current is not None:
                workers.append(current)
            current = new_worker(left)
            consume(i)

            # 同行右侧出现 Name（"["）→ 从 AKRONIM 提取完整名字
            if row_has_bracket(row):
                bracket_text_match = re.search(r"\[([^\]]*)", text)
                bracket_had_underscore = bool(
                    bracket_text_match and "_" in bracket_text_match.group(1)
                )
                current["name"] = extract_full_name(text, current["lp"])
                consume(i)
                # 检查下一行：如果是补充名字（前缀扩展或新词），智能合并
                j = next_nonblank(i)
                if j != -1:
                    next_text = row_text(rows[j])
                    next_left = row_left_text(rows[j])
                    if ("PLN" not in next_text
                            and not re.fullmatch(r"\s*\d+\s*", next_left)
                            and "Czas pracy" not in next_text
                            and "Nieobecności" not in next_text
                            and "[" not in next_text
                            and not any(t in next_text for t in STOP_TEXTS)):
                        extra = next_text.strip()
                        if extra:
                            # 仅当括号原本就有 '_'（说明 AKRONIM 被截断）时，
                            # 才允许做前缀扩展替换；否则直接去重+追加
                            current["name"] = _merge_name_with_extra(
                                current["name"], extra,
                                allow_prefix_extend=bracket_had_underscore,
                            )
                        consume(j)
            else:
                # 无 "[" 的行（如 "43KAKKANATTU MURALEEDHA"），
                # 下一行可能是纯姓名（如 "KRISHNAKUMAR"）
                j = next_nonblank(i)
                if j != -1:
                    next_text = row_text(rows[j])
                    next_left = row_left_text(rows[j])
                    if ("PLN" not in next_text
                            and not re.fullmatch(r"\s*\d+\s*", next_left)
                            and "Czas pracy" not in next_text
                            and "Nieobecności" not in next_text
                            and "[" not in next_text
                            and not any(t in next_text for t in STOP_TEXTS)):
                        current["name"] = next_text.strip()
                        consume(j)
            i += 1
            continue

        if current is None:
            i += 1
            continue

        # 2) Name 行（无 LP）：含 "["
        if row_has_bracket(row) and not current["name"]:
            j = next_nonblank(i)
            if j != -1:
                next_text = row_text(rows[j])
                next_left = row_left_text(rows[j])
                if ("PLN" not in next_text
                        and not re.fullmatch(r"\s*\d+\s*", next_left)
                        and "Czas pracy" not in next_text
                        and "Nieobecności" not in next_text
                        and "[" not in next_text):
                    current["name"] = next_text.strip()
                    consume(j)
            i += 1
            continue

        # 3) Salary：含 "PLN"
        if "PLN" in text and current["salary"] == 0:
            m = re.search(r"([\d\s]+,\d{2})\s*PLN", text)
            if m:
                salary_str = m.group(1)
                salary_num = salary_str.replace(" ", "").replace(",", ".")
                current["salary"] = int(float(salary_num))
                i += 1
                continue

        # 4) Czas pracy：含 "Czas pracy"
        if "Czas pracy" in text:
            times = re.findall(r"\d{1,3}:\d{2}", text)
            if len(times) >= 2:
                current["standard_hours"] = times[0]
                current["total_hours"] = times[1]
            i += 1
            continue

        # 5) Nieobecności：跳过
        if "Nieobecności" in text:
            i += 1
            continue

        # 6) Urlopy / ZUS / NN / Inne（注意：标签后紧跟数字，无词边界）
        # 额外守卫：不匹配摘要/页脚文本
        if not any(t in text for t in STOP_TEXTS):
            matched = False
            for label, key in [("Urlopy", "urlopy"), ("ZUS", "zus"),
                               ("NN", "nn"), ("Inne", "inne")]:
                if label in text:
                    val = extract_value_from_row(row)
                    if not val and i > 0 and not consumed[i - 1]:
                        val = extract_value_from_row(rows[i - 1])
                    if not val and i + 1 < n:
                        val = extract_value_from_row(rows[i + 1])
                    current[key] = val.replace("//", "/")
                    matched = True
                    break
            if matched:
                i += 1
                continue

        # 7) Nadg / Nocne 区
        if "Nadgodziny" in text:
            i += 1
            continue
        if "Nadg.50" in text:
            t = extract_time_from_row(row)
            if not t and i + 1 < n:
                t = extract_time_from_row(rows[i + 1])
            current["nadg50"] = t
            i += 1
            continue
        if "Nadg.100" in text:
            t = extract_time_from_row(row)
            if not t and i > 0 and not consumed[i - 1]:
                t = extract_time_from_row(rows[i - 1])
            current["nadg100"] = t
            i += 1
            continue
        if "Nocne" in text:
            t = extract_time_from_row(row)
            if not t and i + 1 < n:
                t = extract_time_from_row(rows[i + 1])
            current["nocne"] = t
            i += 1
            continue

        i += 1

    if current is not None:
        workers.append(current)

    return workers


def extract_workers(pdf_path):
    """从 PDF 文件中提取所有 worker 数据。返回 list[dict]。"""
    doc = fitz.open(pdf_path)
    all_rows = []
    for page in doc:
        spans = extract_pracownik_spans(page)
        rows = group_into_rows(spans)
        all_rows.extend(rows)
    doc.close()
    return parse_workers_from_rows(all_rows)


# ============== Excel 输出 ==============

EXCEL_HEADERS = [
    "序号", "姓名", "基本工资",
    "标准工时", "总工时",
    "Urlopy", "ZUS", "NN", "Inne",
    "Nadg.50", "Nadg.100", "Nocne",
]


def write_to_excel(workers, output_path, pdf_name):
    """将 worker 数据写入 Excel 文件。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "工资单数据"

    ws["A1"] = f"波兰工资单数据提取 - {pdf_name}"
    ws["A1"].font = Font(bold=True, size=14)
    ws.merge_cells("A1:L1")
    ws["A1"].alignment = Alignment(horizontal="center", vertical="center")

    ws["A2"] = f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  共 {len(workers)} 条记录"
    ws.merge_cells("A2:L2")
    ws["A2"].alignment = Alignment(horizontal="center")
    ws["A2"].font = Font(italic=True, color="666666")

    header_row = 4
    thin = Side(border_style="thin", color="BFBFBF")
    border = Border(top=thin, bottom=thin, left=thin, right=thin)

    for col, header in enumerate(EXCEL_HEADERS, 1):
        cell = ws.cell(row=header_row, column=col, value=header)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border

    for idx, w in enumerate(workers, 1):
        row = header_row + idx
        values = [
            int(w["lp"]) if w["lp"] else idx,
            w["name"],
            w["salary"],
            w["standard_hours"],
            w["total_hours"],
            w["urlopy"],
            w["zus"],
            w["nn"],
            w["inne"],
            w["nadg50"],
            w["nadg100"],
            w["nocne"],
        ]
        for col, val in enumerate(values, 1):
            cell = ws.cell(row=row, column=col, value=val)
            cell.border = border
            if col == 3:
                cell.number_format = "#,##0"
                cell.alignment = Alignment(horizontal="right")
            else:
                cell.alignment = Alignment(horizontal="center")

    widths = [6, 18, 12, 11, 11, 9, 9, 9, 9, 10, 10, 10]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[chr(64 + i)].width = w

    ws.row_dimensions[1].height = 24
    ws.row_dimensions[header_row].height = 22
    ws.freeze_panes = "A5"

    wb.save(output_path)


# ============== GUI ==============

class App:
    def __init__(self, root):
        self.root = root
        self.root.title("波兰工资单 PDF 提取工具 v1.0")
        self.root.geometry("720x560")
        self.root.minsize(640, 480)

        self.pdf_path = tk.StringVar()
        self.output_path = tk.StringVar()
        self._build_ui()

    def _build_ui(self):
        frm_pdf = tk.Frame(self.root)
        frm_pdf.pack(fill="x", padx=12, pady=(12, 4))
        tk.Label(frm_pdf, text="PDF 文件:", width=10, anchor="w").pack(side="left")
        tk.Entry(frm_pdf, textvariable=self.pdf_path).pack(side="left", fill="x", expand=True, padx=4)
        tk.Button(frm_pdf, text="选择...", command=self._on_select_pdf, width=10).pack(side="left")

        frm_out = tk.Frame(self.root)
        frm_out.pack(fill="x", padx=12, pady=4)
        tk.Label(frm_out, text="输出 Excel:", width=10, anchor="w").pack(side="left")
        tk.Entry(frm_out, textvariable=self.output_path).pack(side="left", fill="x", expand=True, padx=4)
        tk.Button(frm_out, text="选择...", command=self._on_select_output, width=10).pack(side="left")

        frm_btn = tk.Frame(self.root)
        frm_btn.pack(fill="x", padx=12, pady=8)
        self.btn_run = tk.Button(
            frm_btn, text="开始提取", command=self._on_run,
            bg="#4CAF50", fg="white", font=("Microsoft YaHei", 11, "bold"),
            height=1, width=12,
        )
        self.btn_run.pack(side="left")
        tk.Button(frm_btn, text="清空日志", command=self._on_clear, width=10).pack(side="left", padx=8)

        self.progress = ttk.Progressbar(self.root, mode="determinate")
        self.progress.pack(fill="x", padx=12, pady=2)

        tk.Label(self.root, text="处理日志:", anchor="w").pack(fill="x", padx=12, pady=(8, 0))
        self.log = scrolledtext.ScrolledText(self.root, height=18, font=("Consolas", 9), wrap="word")
        self.log.pack(fill="both", expand=True, padx=12, pady=4)

        self.status = tk.StringVar(value="就绪")
        tk.Label(self.root, textvariable=self.status, bd=1, relief="sunken", anchor="w").pack(fill="x", side="bottom")

    def _on_select_pdf(self):
        path = filedialog.askopenfilename(
            title="选择波兰工资单 PDF",
            filetypes=[("PDF 文件", "*.pdf"), ("所有文件", "*.*")],
        )
        if not path:
            return
        self.pdf_path.set(path)
        if not self.output_path.get():
            base = os.path.splitext(os.path.basename(path))[0]
            out = os.path.join(os.path.dirname(path), f"{base}_提取结果.xlsx")
            self.output_path.set(out)

    def _on_select_output(self):
        path = filedialog.asksaveasfilename(
            title="保存 Excel 文件",
            defaultextension=".xlsx",
            filetypes=[("Excel 文件", "*.xlsx")],
            initialfile=os.path.basename(self.output_path.get()) if self.output_path.get() else "提取结果.xlsx",
        )
        if path:
            self.output_path.set(path)

    def _on_clear(self):
        self.log.delete("1.0", "end")

    def _on_run(self):
        pdf = self.pdf_path.get().strip()
        out = self.output_path.get().strip()
        if not pdf or not os.path.isfile(pdf):
            messagebox.showerror("错误", "请先选择有效的 PDF 文件")
            return
        if not out:
            messagebox.showerror("错误", "请指定输出 Excel 路径")
            return
        self.btn_run.config(state="disabled")
        threading.Thread(target=self._worker, args=(pdf, out), daemon=True).start()

    def _worker(self, pdf, out):
        try:
            self._log(f"开始处理：{pdf}")
            self.status.set("正在解析 PDF...")
            self.progress["value"] = 10

            workers = extract_workers(pdf)
            self._log(f"共识别到 {len(workers)} 条员工记录")
            self.progress["value"] = 60

            for w in workers[:3]:
                self._log(
                    f"  #{w['lp']} {w['name']:<15} 工资={w['salary']:<7} "
                    f"工时={w['standard_hours']}/{w['total_hours']:<6} "
                    f"Urlopy={w['urlopy']:<5} ZUS={w['zus']:<5} NN={w['nn']:<5} Inne={w['inne']:<5} "
                    f"N50={w['nadg50']:<6} N100={w['nadg100']:<6} Nocne={w['nocne']}"
                )
            if len(workers) > 3:
                self._log(f"  ... (其余 {len(workers) - 3} 条略)")

            self.status.set("正在写入 Excel...")
            write_to_excel(workers, out, os.path.basename(pdf))
            self.progress["value"] = 100
            self._log(f"✅ 已保存到：{out}")
            self.status.set(f"完成 - {len(workers)} 条记录")
            messagebox.showinfo("完成", f"提取完成！共 {len(workers)} 条记录\n\n文件已保存到：\n{out}")
        except Exception as e:
            self._log(f"❌ 错误：{e}")
            self.status.set("出错")
            messagebox.showerror("错误", str(e))
            import traceback
            traceback.print_exc()
        finally:
            self.btn_run.config(state="normal")
            self.progress["value"] = 0

    def _log(self, msg):
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.root.update_idletasks()


def main():
    try:
        root = tk.Tk()
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
        app = App(root)
        root.mainloop()
    except Exception as e:
        import traceback, os, sys
        err_log = os.path.join(os.path.dirname(os.path.abspath(__file__)), "error.log")
        with open(err_log, "w", encoding="utf-8") as f:
            f.write(f"启动失败: {e}\n\n")
            traceback.print_exc(file=f)
        # 如果 GUI 不可用，用控制台输出
        print(f"启动失败: {e}", file=sys.stderr)
        traceback.print_exc()
        input("按回车键退出...")


if __name__ == "__main__":
    main()

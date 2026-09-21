"""
lohnjournal_extractor.py
========================
DATEV Lohnjournal (Form LOA313) PDF → Excel 提取核心

# 安全策略 (File Safety Policy)
本工具只处理用户显式选择的 PDF 文件路径，**不扫描、不读取、不修改用户本地的
任何其他文件或目录**。所有操作限定在用户选定的 PDF 与显式指定的输出路径。

# 数字解析规则 (用户指定)
- 文本层中数字里的 "." 是千分位分隔符；去掉分隔符后，末两位是小数
  (PDF 视觉上的竖线 "|" 即小数点，文本层不包含该字符)
  例: "4.29337" → 4293.37；"59883" → 598.83；"8300" → 83.00
- 数字末尾的 "-" 表示负数: "65042-" → -650.42
- "Z" 是 PV-Beitragszuschlag(无子女附加保险费)标记，解析金额时忽略

# 表格结构 (每个员工 3 条文本线, 间距 9px; 金额右对齐到列锚点)
  锚点~220  Steuerbrutto 区    L2=Steuerbrutto, L3=Pausch. verst. Bezüge
            → 按用户要求该列仅取 L1 的姓名, 金额不导出
  锚点~298  Lohnsteuer 区      L2=Lohnsteuer, L3=Pausch. Lohnsteuer
  锚点~370  KiSt 区            L2=Kirchensteuer(Förderbetrag), L3=Pausch. KiSt
  锚点~442  SolZ 区            L2=SolZ, L3=Pausch. SolZ
  锚点~502  KV 区              L1=KV-Brutto, L2=KV-Beitrag AN, L3=KV-Beitrag AG
  锚点~562  RV 区              同上
  锚点~622  AV 区              同上
  锚点~682  PV 区              同上
  锚点~736  Umlage 区          L1=Umlage 1, L2=Umlage 2, L3=Umlage Insolv
  锚点~814  最右区             L1=Gesamtbrutto, L2=Nettobezüge/-abzüge, L3=Auszahlungsbetrag

  3 行子行含义: L1=缴费基数, L2=个人(AN), L3=公司(AG)
  Lohnsteuer/KiSt/SolZ 的 L1 恒为空(该区 L1 是姓名), 按空值导出。

# 鲁棒性 / 诊断 (2026-09-14 加固, 应对「提取失败」排查)
- 锚点来源按可靠性兜底: 严格竖线 → 含细长矩形边/分段线的宽松竖线 →
  仿射拟合到默认锚点(整页缩放/平移) → 金额右对齐位置聚类反推 → 默认锚点。
- Pers.-Nr 严格分区 (x∈[20,60)) 一行都没命中时, 整页退回「左侧最靠前的 4-6 位数字」。
- 单页异常不再拖垮整份文档; 加密 PDF / 空页给出明确中文原因。
- 安全网: 解析到员工行但金额列全空时**直接报错**(并附锚点来源与页面尺寸),
  绝不交出「有姓名、没金额」的空壳表; 填充率 < 60% 记告警。
- extract_from_pdf(path, diag) 的 diag 会填入 anchors_source / page_size /
  notes / page_errors / fill_rate, 供工作台把失败原因写给用户。
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import fitz  # PyMuPDF
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
# 垂直线 x + 11.45 = 金额右对齐锚点 (LOA313 表单实测偏移 11.35~11.6)
_ANCHOR_OFFSET = 11.45
_ANCHOR_TOL = 3.5          # 锚点匹配容差
_LINE_Y_TOL = 2.5          # 文本行聚类容差
_SUB_ROW_DY = (9.0, 18.0)  # 员工块内第 2/3 子行相对第 1 行的 y 偏移
_RUN_GAP = 5.0             # 字符间距 >= 5px 视为不同 run

# 找不到垂直线时的兜底锚点 (本表单实测值)
DEFAULT_ANCHORS = [220.0, 298.0, 370.1, 442.1, 502.1,
                   562.1, 622.1, 682.1, 736.1, 814.1]

# 金额 run 允许出现的字符 (Z/z 为 PV-Zuschlag 标记)
_AMT_CHARS = set("0123456789.,- Zz")

# 元数据 x 分区 (LOA313 实测)
_ZONE_PERS = (20.0, 60.0)    # Pers.-Nr.
_ZONE_STKL = (60.0, 72.0)    # St.Kl.
_ZONE_FAKTOR = (72.0, 100.0)  # Faktor
_ZONE_KIFRB = (100.0, 122.0)  # Ki.Frb.
_ZONE_KONF = (122.0, 145.0)   # Konfession (ev / rk)
_NAME_X_RANGE = (140.0, 460.0)  # 姓名起始 run 的 x 范围


# ---------------------------------------------------------------------------
# 数字解析
# ---------------------------------------------------------------------------
def parse_amount_float(raw: Optional[str]) -> Optional[float]:
    """把 PDF 文本层金额解析为浮点数 (单位: 元)。

    规则: 去掉空格与 Z 标记; 末尾 "-" 为负号; 去掉千分位 "." 和 ","
    后, 末两位是小数。无法解析返回 None。
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    s = s.replace(" ", "").replace("Z", "").replace("z", "")
    if not s:
        return None
    sign = 1.0
    if s.endswith("-"):
        sign = -1.0
        s = s[:-1]
    digits = s.replace(".", "").replace(",", "")
    if not digits or not digits.isdigit():
        return None
    return round(sign * (int(digits) / 100.0), 2)


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------
@dataclass
class Employee:
    """单个员工的解析结果。"""
    pers_nr: Optional[str] = None
    st_kl: Optional[str] = None
    faktor: Optional[str] = None
    ki_frb: Optional[str] = None
    konfession: Optional[str] = None
    name: Optional[str] = None
    # 3 行字段: [缴费基数, 个人(AN), 公司(AG)]
    lohnsteuer: list = field(default_factory=lambda: [None, None, None])
    foerderbetrag: list = field(default_factory=lambda: [None, None, None])
    solz: list = field(default_factory=lambda: [None, None, None])
    kv: list = field(default_factory=lambda: [None, None, None])
    rv: list = field(default_factory=lambda: [None, None, None])
    av: list = field(default_factory=lambda: [None, None, None])
    pv: list = field(default_factory=lambda: [None, None, None])
    # 单值字段
    umlage1: Optional[float] = None
    umlage2: Optional[float] = None
    umlage_insolv: Optional[float] = None
    gesamtbrutto: Optional[float] = None
    nettobezuege: Optional[float] = None
    auszahlungsbetrag: Optional[float] = None

    def row_values(self) -> list:
        """按 Excel 列顺序返回一行数据。"""
        return [
            self.pers_nr, self.st_kl, self.faktor, self.ki_frb,
            self.konfession, self.name,
            *self.lohnsteuer, *self.foerderbetrag, *self.solz,
            *self.kv, *self.rv, *self.av, *self.pv,
            self.umlage1, self.umlage2, self.umlage_insolv,
            self.gesamtbrutto, self.nettobezuege, self.auszahlungsbetrag,
        ]


# ---------------------------------------------------------------------------
# PDF 底层提取工具
# ---------------------------------------------------------------------------
def _extract_chars(page) -> list:
    """提取页面全部字符及其包围盒。"""
    raw = page.get_text("rawdict")
    chars = []
    for block in raw.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                for ch in span.get("chars", []):
                    chars.append({"text": ch.get("c", ""), "bbox": ch["bbox"]})
    return chars


def _cluster_lines(chars: list, tol: float = _LINE_Y_TOL) -> list:
    """按 y0 把字符聚类成文本行, 返回 [{'y': float, 'chars': [...]}]。"""
    chars = sorted(chars, key=lambda c: (c["bbox"][1], c["bbox"][0]))
    lines: List[dict] = []
    for c in chars:
        if lines and abs(c["bbox"][1] - lines[-1]["y"]) <= tol:
            lines[-1]["chars"].append(c)
        else:
            lines.append({"y": c["bbox"][1], "chars": [c]})
    return lines


def _runs_of(line_chars: list, gap: float = _RUN_GAP) -> list:
    """把一行字符按水平间距切成 run (视觉上分开的片段)。"""
    cs = sorted(line_chars, key=lambda c: c["bbox"][0])
    runs: List[list] = []
    for c in cs:
        if runs and c["bbox"][0] - runs[-1][-1]["bbox"][2] >= gap:
            runs.append([c])
        elif not runs:
            runs.append([c])
        else:
            runs[-1].append(c)
    return runs


def _run_text(run) -> str:
    return "".join(c["text"] for c in run)


def _run_x0(run) -> float:
    return run[0]["bbox"][0]


def _run_x1(run) -> float:
    return run[-1]["bbox"][2]


def _core_end(run) -> float:
    """金额 run 的有效右端: 跳过末尾的 '-'/空格/'Z', 取最后一个数字字符的 x1。

    负数的 '-' 和 'Z' 标记会伸到锚点右侧, 不能用整个 run 的右端匹配锚点。
    """
    for c in reversed(run):
        if c["text"] in "0123456789.,":
            return c["bbox"][2]
    return _run_x1(run)


def _is_amount_run(run) -> bool:
    """判断 run 是否是纯金额片段 (只含数字/./,/-/空格/Z 且至少一个数字)。

    姓名、'NB'、'Summen' 等含字母片段会被排除。
    """
    txt = _run_text(run)
    if not any(ch.isdigit() for ch in txt):
        return False
    return all(ch in _AMT_CHARS for ch in txt)


def _match_anchor(core_end: float, anchors: List[float]) -> int:
    """返回 core_end 匹配的锚点下标, 无匹配返回 -1。"""
    for i, a in enumerate(anchors):
        if abs(core_end - a) <= _ANCHOR_TOL:
            return i
    return -1


def _zone_text(line: dict, x_lo: float, x_hi: float) -> Optional[str]:
    """取文本行中 x0 ∈ [x_lo, x_hi) 的字符拼接 (用于元数据分区)。"""
    cs = sorted(line["chars"], key=lambda c: c["bbox"][0])
    txt = "".join(c["text"] for c in cs if x_lo <= c["bbox"][0] < x_hi).strip()
    return txt or None


def _pers_nr_of(line: dict) -> Optional[str]:
    """判断文本行是否是员工块首行 (x<60 区域是 4-6 位 Pers.-Nr 数字)。"""
    txt = _zone_text(line, *_ZONE_PERS)
    if txt and re.fullmatch(r"\d{4,6}", txt):
        return txt
    return None


def _name_of(l1: dict) -> Optional[str]:
    """从员工块首行取姓名: x ∈ [140, 460] 内第一个含字母的 run。"""
    for run in _runs_of(l1["chars"]):
        x0 = _run_x0(run)
        if _NAME_X_RANGE[0] <= x0 <= _NAME_X_RANGE[1]:
            txt = _run_text(run).strip()
            if txt and any(ch.isalpha() for ch in txt):
                return re.sub(r"\s+", " ", txt)
    return None


def _anchors_from_drawings(drawings) -> Optional[List[float]]:
    """严格路径: 从贯穿表格的普通垂直线推导 10 个金额列锚点; 失败返回 None。

    保持原实现不变 —— 真实 LOA313 报表走这条路，输出与历史版本逐格一致。
    更宽松的兜底（细长矩形边 / 缩放平移 / 文本右对齐）见 _resolve_anchors。
    """
    vxs = set()
    for d in drawings:
        for it in d.get("items", []):
            if it[0] != "l":
                continue
            (x0, y0), (x1, y1) = it[1], it[2]
            if abs(x0 - x1) < 0.5 and abs(y1 - y0) > 300:
                vxs.add(round(x0, 1))
    # 相邻 1px 内合并
    xs: List[float] = []
    for x in sorted(vxs):
        if not xs or x - xs[-1] > 1.0:
            xs.append(x)
    # 金额区垂直线 (x >= 200) 应恰好 10 根
    amount_xs = [x for x in xs if x >= 200.0]
    if len(amount_xs) != 10:
        return None
    return [round(x + _ANCHOR_OFFSET, 1) for x in amount_xs]


# ---------------------------------------------------------------------------
# 锚点兜底：不同来源的 PDF（打印缩放、另存、边线画法不同）表格几何会变
# ---------------------------------------------------------------------------
_AMOUNT_ZONE_X0 = 200.0     # 金额列垂直线最小 x
_LAST_LEN_FLOOR = 120.0     # 竖线长度下限（矮页面/续页按页高自适应）


def _note(diag, key, val) -> None:
    if isinstance(diag, dict):
        diag[key] = val


def _warn(diag, msg) -> None:
    if isinstance(diag, dict):
        diag.setdefault("notes", []).append(msg)


def _vline_xs(drawings, page_height: float) -> List[float]:
    """宽松路径: 收集竖直的表格边线 x。

    与严格路径的区别:
      * 细长矩形（re，宽 <= 2px）也算竖线 —— 有的导出把边线画成矩形；
      * 同 x 的短线段累加长度（边线被拆成多段时仍能识别）；
      * 长度下限按页高自适应 max(120, 25% 页高)，不再硬编码 300
        （矮页面 / 续页 / 被裁剪的页面原来会整体漏判）。
    """
    seg: dict = {}
    for d in drawings:
        for it in d.get("items", []):
            if it[0] == "l":
                (x0, y0), (x1, y1) = it[1], it[2]
                if abs(x0 - x1) < 0.5:
                    x = round(x0, 1)
                    seg[x] = seg.get(x, 0.0) + abs(y1 - y0)
            elif it[0] == "re":
                r = it[1]
                w, h = abs(r.x1 - r.x0), abs(r.y1 - r.y0)
                if h > 0 and w <= 2.0:
                    x = round(min(r.x0, r.x1), 1)
                    seg[x] = seg.get(x, 0.0) + h
    min_len = max(_LAST_LEN_FLOOR, page_height * 0.25)
    xs: List[float] = []
    for x in sorted(seg):
        if xs and x - xs[-1] <= 1.0:
            xs[-1] = x          # 同一条线，取靠右的代表值（长度已累加）
            continue
        xs.append(x)
    return [x for x in xs
            if sum(v for k, v in seg.items() if abs(k - x) <= 1.0) > min_len]


def _fit_to_default(observed: List[float], min_match: int = 7):
    """把观测到的列位置仿射拟合到 DEFAULT_ANCHORS: x' = a*x + b。

    应对「同一张 LOA313 报表被整体缩放/平移」（打印缩放、另存、页面裁剪）。
    返回 (10 个拟合锚点, 命中数)；拟合不成立返回 None。
    """
    obs = sorted({round(o, 1) for o in observed})
    if len(obs) < 2:
        return None
    base = DEFAULT_ANCHORS
    span_needed = 0.25 * (base[-1] - base[0])
    best_hit, best_fit = 0, None
    for p in range(len(base)):
        for q in range(p + 1, len(base)):
            if base[q] - base[p] < span_needed:      # 参照对跨度太小，比例估不准
                continue
            for oi in obs:
                for oj in obs:
                    if oj - oi < span_needed * 0.6:
                        continue
                    a = (oj - oi) / (base[q] - base[p])
                    if not (0.4 <= a <= 2.5):        # 离谱比例直接排除
                        continue
                    b = oi - a * base[p]
                    fit = [a * x + b for x in base]
                    tol = max(_ANCHOR_TOL, 0.3 * a)
                    hit = sum(1 for f in fit
                              if min(abs(f - o) for o in obs) <= tol)
                    if hit > best_hit:
                        best_hit, best_fit = hit, fit
                        if hit == len(base):
                            return (fit, hit)
    if best_fit is None or best_hit < min_match:
        return None
    return (best_fit, best_hit)


def _merge_observed(fit: List[float], observed: List[float]) -> List[float]:
    """拟合出的 10 个锚点里，凡是观测到真实列位置的都用观测值。"""
    out = []
    for f in fit:
        near = min(observed, key=lambda o: abs(o - f))
        out.append(round(near, 1) if abs(near - f) <= _ANCHOR_TOL else round(f, 1))
    return out


def _amount_core_ends(lines: List[dict]) -> List[float]:
    """页面里全部金额 run 的右对齐位置（x >= 200），用于无锚线时反推列位置。"""
    ends = []
    for ln in lines:
        for run in _runs_of(ln["chars"]):
            if _is_amount_run(run):
                e = _core_end(run)
                if e >= _AMOUNT_ZONE_X0:
                    ends.append(e)
    return ends


def _peaks_from_ends(ends: List[float], tol: float = 1.5,
                     min_members: int = 2) -> List[float]:
    """把右对齐位置聚成峰（同一列的金额右端会落在同一 x 附近）。"""
    peaks: List[List[float]] = []
    for e in sorted(ends):
        if peaks and e - peaks[-1][-1] <= tol:
            peaks[-1].append(e)
        else:
            peaks.append([e])
    return [sum(p) / len(p) for p in peaks if len(p) >= min_members]


def _resolve_anchors(page, lines: List[dict], page_height: float,
                     diag=None) -> List[float]:
    """确定 10 个金额锚点，按可靠性从高到低兜底。

    ① 严格竖线（历史路径，命中即与历史输出逐格一致）
    ② 宽松竖线（含细长矩形边、分段线累加、长度自适应）恰好 10 根
    ③ 竖线不足 10 根 → 仿射拟合到默认锚点（整页缩放/平移）
    ④ 无竖线 → 用金额右对齐位置聚类成峰再拟合
    ⑤ 都不成立 → 默认锚点（记告警；最终由「金额全空」安全网拦截）
    """
    drawings = page.get_drawings()
    legacy = _anchors_from_drawings(drawings)
    if legacy is not None:
        _note(diag, "anchors_source", "表格竖线（严格路径）")
        return legacy
    amt = [x + _ANCHOR_OFFSET
           for x in _vline_xs(drawings, page_height) if x >= _AMOUNT_ZONE_X0]
    if len(amt) == 10:
        _note(diag, "anchors_source", "表格竖线（含矩形边，10 根）")
        return [round(x, 1) for x in amt]
    if len(amt) >= 2:
        got = _fit_to_default(amt)
        if got:
            fit, hit = got
            _note(diag, "anchors_source", "表格竖线（仿射拟合 %d/10）" % hit)
            return _merge_observed(fit, amt)
    peaks = _peaks_from_ends(_amount_core_ends(lines))
    if len(peaks) >= 2:
        got = _fit_to_default(peaks, min_match=6)
        if got:
            fit, hit = got
            _note(diag, "anchors_source", "金额右对齐拟合 %d/10" % hit)
            return _merge_observed(fit, peaks)
    _note(diag, "anchors_source",
          "默认锚点（未识别到表格锚线；竖线 %d 根 / 右对齐峰 %d 个）" % (len(amt), len(peaks)))
    return list(DEFAULT_ANCHORS)


# ---------------------------------------------------------------------------
# 员工块解析
# ---------------------------------------------------------------------------
def _assign(emp: Employee, anchor_idx: int, sub: int, val: Optional[float]) -> None:
    """把 (锚点, 子行) 的金额赋到员工字段。"""
    if anchor_idx == 0:
        # Steuerbrutto / Pausch. verst. Bezüge —— 用户要求仅取姓名, 金额不导出
        return
    if anchor_idx in (1, 2, 3):
        # Lohnsteuer / KiSt / SolZ: L2=正税(个人), L3=Pauschal(公司), L1 恒空
        target = {1: emp.lohnsteuer, 2: emp.foerderbetrag, 3: emp.solz}[anchor_idx]
        if 0 <= sub <= 2:
            target[sub] = val
        return
    if anchor_idx in (4, 5, 6, 7):
        target = {4: emp.kv, 5: emp.rv, 6: emp.av, 7: emp.pv}[anchor_idx]
        if 0 <= sub <= 2:
            target[sub] = val
        return
    if anchor_idx == 8:
        if sub == 0:
            emp.umlage1 = val
        elif sub == 1:
            emp.umlage2 = val
        elif sub == 2:
            emp.umlage_insolv = val
        return
    if anchor_idx == 9:
        if sub == 0:
            emp.gesamtbrutto = val
        elif sub == 1:
            emp.nettobezuege = val
        elif sub == 2:
            emp.auszahlungsbetrag = val


def _parse_employee(sub_lines: List[Optional[dict]], anchors: List[float]) -> Employee:
    """sub_lines = [L1行, L2行, L3行] (缺失为 None)。"""
    emp = Employee()
    l1 = sub_lines[0]
    if l1 is not None:
        emp.pers_nr = _pers_nr_of(l1)
        emp.st_kl = _zone_text(l1, *_ZONE_STKL)
        emp.faktor = _zone_text(l1, *_ZONE_FAKTOR)
        emp.ki_frb = _zone_text(l1, *_ZONE_KIFRB)
        emp.konfession = _zone_text(l1, *_ZONE_KONF)
        emp.name = _name_of(l1)

    for sub, ln in enumerate(sub_lines):
        if ln is None:
            continue
        for run in _runs_of(ln["chars"]):
            if not _is_amount_run(run):
                continue
            a = _match_anchor(_core_end(run), anchors)
            if a < 0:
                continue
            val = parse_amount_float(_run_text(run))
            _assign(emp, a, sub, val)
    return emp


_LIST_FIELDS = ("lohnsteuer", "foerderbetrag", "solz", "kv", "rv", "av", "pv")
_SINGLE_FIELDS = ("umlage1", "umlage2", "umlage_insolv",
                  "gesamtbrutto", "nettobezuege", "auszahlungsbetrag")


def has_any_amount(emp: "Employee") -> bool:
    """该员工是否解析到任何金额（用于「金额全空」安全网与填充率统计）。"""
    if any(v is not None for f in _LIST_FIELDS for v in getattr(emp, f)):
        return True
    return any(getattr(emp, f) is not None for f in _SINGLE_FIELDS)


def _relaxed_pers_nr_of(line: dict) -> Optional[str]:
    """宽松版 Pers.-Nr: 行内最靠左的 4-6 位纯数字 run（须在姓名列左侧）。"""
    for run in _runs_of(line["chars"]):
        if _run_x0(run) >= _NAME_X_RANGE[0]:
            break
        txt = _run_text(run).strip()
        if re.fullmatch(r"\d{4,6}", txt):
            return txt
    return None


def _sub_lines_of(l1: dict, lines: List[dict]) -> List[Optional[dict]]:
    """取员工块的 3 条子行: L1 本人 + y+9 / y+18 两行（缺为 None）。"""
    sub: List[Optional[dict]] = [l1]
    for dy in _SUB_ROW_DY:
        target_y = l1["y"] + dy
        found = None
        for other in lines:
            if other is l1:
                continue
            if abs(other["y"] - target_y) <= 3.0:
                found = other
                break
        sub.append(found)
    return sub


def _extract_page(page, diag=None) -> List[Employee]:
    """提取单页的所有员工。"""
    if page.rotation:
        # 旋转页里文本与绘制可能落在不同坐标系，导致锚点与金额错位。
        # 归一化到 0° 让两者回到同一坐标系（正常页面 rotation=0，走不到这里）。
        _warn(diag, "存在页面旋转 %d°，已按 0° 归一化坐标解析" % page.rotation)
        page.set_rotation(0)
    lines = _cluster_lines(_extract_chars(page))
    anchors = _resolve_anchors(page, lines, page.rect.height, diag)

    employees: List[Employee] = []
    for ln in lines:
        if _pers_nr_of(ln) is None:
            continue
        employees.append(_parse_employee(_sub_lines_of(ln, lines), anchors))

    if employees:
        return employees

    # 严格分区 (x ∈ [20,60)) 一行都没命中时退一步：整页左侧找 4-6 位数字 run。
    # 仅在严格路径 0 命中的页面启用，不会影响正常报表的结果。
    for ln in lines:
        nr = _relaxed_pers_nr_of(ln)
        if nr is None:
            continue
        emp = _parse_employee(_sub_lines_of(ln, lines), anchors)
        if not emp.pers_nr:
            emp.pers_nr = nr
        if emp.name or has_any_amount(emp):
            employees.append(emp)
    if employees:
        _warn(diag, "已启用 Pers.-Nr 宽松定位（左侧分区未命中，共 %d 行）" % len(employees))
    return employees


def _diag_brief(diag) -> str:
    """把诊断信息压成一句话，供异常文案 / 工作台提示引用。"""
    if not isinstance(diag, dict):
        return ""
    bits = []
    if diag.get("anchors_source"):
        bits.append("锚点来源：%s" % diag["anchors_source"])
    if diag.get("page_size"):
        bits.append("页面尺寸：%s" % diag["page_size"])
    bits.extend(str(n) for n in (diag.get("notes") or []))
    bits.extend(str(n) for n in (diag.get("page_errors") or []))
    fr = diag.get("fill_rate")
    if fr is not None:
        bits.append("金额填充率：%.0f%%" % (fr * 100))
    return ("（" + "；".join(bits) + "）") if bits else ""


LAST_DIAG: dict = {}


def extract_from_pdf(pdf_path: str, diag: Optional[dict] = None) -> List[Employee]:
    """从用户显式选择的 PDF 文件提取全部员工数据 (支持多页)。

    diag: 可选 dict，会被填入本次解析的诊断（锚点来源 / 页面尺寸 / 告警 /
          每页异常 / 金额填充率），供调用方把「为什么 0 行 / 金额为什么空」
          写进给用户的提示里。
    """
    d = diag if isinstance(diag, dict) else {}
    d.clear()
    global LAST_DIAG
    LAST_DIAG = d

    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        raise RuntimeError("PDF 无法解析（可能加密、损坏或非标准格式）: %s" % e)
    try:
        if getattr(doc, "needs_pass", False):
            raise RuntimeError(
                "PDF 已加密（需要口令才能打开），无法读取内容。"
                "请先解密或另存为不加密的 PDF 再上传。")
        if doc.page_count <= 0:
            raise RuntimeError("PDF 内没有任何页面。")
        d["page_size"] = "%.0f×%.0f" % (doc[0].rect.width, doc[0].rect.height)

        employees: List[Employee] = []
        page_errs: List[str] = []
        for i, page in enumerate(doc, 1):
            try:
                employees.extend(_extract_page(page, d))
            except Exception as e:            # 单页异常不拖垮整份文档
                page_errs.append("第 %d 页解析异常: %s" % (i, e))
        if page_errs:
            d["page_errors"] = page_errs
            if not employees:
                raise RuntimeError("；".join(page_errs))

        if employees:
            filled = sum(1 for e in employees if has_any_amount(e))
            d["fill_rate"] = filled / float(len(employees))
            if filled == 0:
                # 最危险的静默错误：有姓名、金额全空。宁可失败并说清原因，
                # 也不交出看起来「成功」的空壳表。
                raise RuntimeError(
                    "已解析到 %d 行员工，但金额列全为空 —— 表格尺规与工具预期不符，"
                    "为避免交出「有姓名、没金额」的空壳表已中止。%s"
                    "请核对：① 是否为 DATEV Lohnjournal（LOA313）报表？"
                    "② PDF 是否被整体缩放/裁剪/旋转，或经另存/打印（表格锚线可能丢失）？"
                    "③ 是否上传了单张工资单而非 Lohnjournal 明细表？"
                    % (len(employees), _diag_brief(d)))
            if d["fill_rate"] < 0.6:
                _warn(d, "金额填充率偏低（%.0f%%）：部分行未对齐，请抽查结果"
                          % (d["fill_rate"] * 100))
        return employees
    finally:
        doc.close()


# ---------------------------------------------------------------------------
# Excel 输出
# ---------------------------------------------------------------------------
HEADER_ROW = [
    "Pers.-Nr.", "St.Kl.", "Faktor", "Ki.Frb.", "Konf./St.Tg.", "Name",
    "Lohnsteuer 缴费基数", "Lohnsteuer 个人", "Lohnsteuer 公司",
    "KiSt/Förderbetrag 缴费基数", "KiSt/Förderbetrag 个人", "KiSt/Förderbetrag 公司",
    "SolZ 缴费基数", "SolZ 个人", "SolZ 公司",
    "KV 缴费基数", "KV 个人", "KV 公司",
    "RV 缴费基数", "RV 个人", "RV 公司",
    "AV 缴费基数", "AV 个人", "AV 公司",
    "PV 缴费基数", "PV 个人", "PV 公司",
    "Umlage 1", "Umlage 2", "Umlage Insolv",
    "Gesamtbrutto", "Nettobezüge/-abzüge", "Auszahlungsbetrag",
]

_COL_WIDTHS = [9, 6, 7, 7, 11, 26] + [13] * 21 + [11, 11, 12, 13, 16, 16]


def write_excel(employees: List[Employee], out_path: str) -> None:
    """把员工数据写入 Excel 文件 (金额为数值, 空 = 空单元格)。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "Lohnjournal"

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="305496", end_color="305496",
                              fill_type="solid")
    for ci, h in enumerate(HEADER_ROW, 1):
        c = ws.cell(row=1, column=ci, value=h)
        c.font = header_font
        c.fill = header_fill
        c.alignment = Alignment(horizontal="center", vertical="center",
                                wrap_text=True)

    for ri, emp in enumerate(employees, 2):
        for ci, v in enumerate(emp.row_values(), 1):
            c = ws.cell(row=ri, column=ci)
            if v is None:
                c.value = None  # 空值
            elif isinstance(v, float):
                c.value = v
                c.number_format = "#,##0.00"
                c.alignment = Alignment(horizontal="right", vertical="center")
            else:
                c.value = v
                if ci == 1:  # Pers.-Nr 保持前导零
                    c.number_format = "@"
                c.alignment = Alignment(
                    horizontal="center" if ci <= 5 else "left",
                    vertical="center")

    for i, w in enumerate(_COL_WIDTHS, 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    ws.freeze_panes = "G2"  # 冻结表头 + 前 6 列元数据

    wb.save(out_path)


# ---------------------------------------------------------------------------
# CLI 入口 (用于测试/命令行)
# ---------------------------------------------------------------------------
def main() -> None:
    if len(sys.argv) < 2:
        print("用法: python lohnjournal_extractor.py <path-to-pdf>")
        sys.exit(1)
    pdf_path = sys.argv[1]
    out_path = str(Path(pdf_path).with_suffix(".xlsx"))
    diag: dict = {}
    try:
        employees = extract_from_pdf(pdf_path, diag)
    except RuntimeError as e:
        print("提取失败: %s" % e)
        sys.exit(2)
    print(f"提取到 {len(employees)} 名员工")
    for emp in employees:
        print(f"  {emp.pers_nr}  {emp.name}")
    brief = _diag_brief(diag)
    if brief:
        print("诊断: " + brief)
    write_excel(employees, out_path)
    print(f"已写入 Excel: {out_path}")


if __name__ == "__main__":
    main()

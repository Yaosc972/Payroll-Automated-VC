import openpyxl, re, os, sys, argparse, datetime
from collections import defaultdict, Counter
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

BASE = r"D:/区域工资/1.云途/3.FBU美洲&亚太&欧洲区/6、波兰/2026年/8月/4、考勤"

DEFAULT_FILES = [
    f"{BASE}/9.3/OK - Tabelki WH No.5 August 2026 Temu V2.xlsx",
    f"{BASE}/9.3/OK - Tabelki BP3 July 2026 Shein V2.xlsx",
    f"{BASE}/9.4/Tabelki Gliwice August 2026 V5.xlsx",
    f"{BASE}/9.3/OK - Tabelki Ilowa August 2026 Shein V1.xlsx",
    f"{BASE}/9.3/OK - Tabelki Office August 2026 V1.xlsx",
    f"{BASE}/9.3/OK - Tabelki Poznan August 2026 V2.xlsx",
    f"{BASE}/9.4/Tabelki Slubice August 2026 V4.xlsx",
    f"{BASE}/9.3/OK - Tabelki Sycow August 2026 Shein V2.xlsx",
    f"{BASE}/9.4/Tabelki Kutno August 2026 V2.xlsx",
    f"{BASE}/9.1/OK - Tabelki Bedzin August 2026.xlsx",
]
DEFAULT_OUT = f"{BASE}/9.3/波兰考勤合并汇总_2026年7-8月.xlsx"
DEFAULT_TEMPLATE = r"D:/其他/Documents/Desktop/波兰汇总字段.xlsx"


def parse_args():
    """支持被 GUI/命令行调用：--files/--filelist/--out/--template/--raw-out。
    不带任何参数时沿用内置默认（保持原有单文件批处理行为）。"""
    p = argparse.ArgumentParser(description='波兰考勤表合并汇总')
    p.add_argument('--files', nargs='*', default=None, help='考勤表 xlsx（可多个）')
    p.add_argument('--filelist', default=None, help='每行一个文件路径的文本文件')
    p.add_argument('--out', default=None, help='输出工作簿路径')
    p.add_argument('--template', default=None,
                   help='汇总字段模板 xlsx（用于生成 Report汇总(指定表头) 表）')
    p.add_argument('--raw-out', default=None, help='额外导出「Report原始字段」工作簿的路径')
    p.add_argument('--no-report', action='store_true', help='不生成 Report 汇总表')
    a, _unknown = p.parse_known_args()

    files = list(a.files) if a.files else None
    if a.filelist and os.path.exists(a.filelist):
        with open(a.filelist, encoding='utf-8') as fh:
            extra = [ln.strip() for ln in fh if ln.strip()]
        files = (files or []) + extra
    if not files:
        files = list(DEFAULT_FILES)
    out = a.out or DEFAULT_OUT
    return files, out, a.template, a.raw_out, a.no_report


FILES, OUT, TEMPLATE, RAW_OUT, NO_REPORT = parse_args()

# Chinese labels for the 请假明细 类型说明 column
LEAVE_LABELS = {'UW': '年假', 'NN': '无故缺勤', 'FML': '不可抗力假', 'L4': '病假',
                'MATERNITY': '产假', 'PARENTAL': '育儿假', 'PAID': '带薪假',
                'UNPAID': '无薪假', 'FUNERAL': '丧假', 'PERSONAL': '事假', 'M': 'M(待确认)'}

# numeric summary buckets
NUM_CODES = ['UW', 'FML', '其他带薪', 'NN', 'UNPAID', 'L4']

detail_headers = ['来源文件', '姓名', '工号', 'Shift/Office', 'Date', 'Stat', 'End', 'Shift',
                  'Work hours', 'Remarks', 'Night', 'Overtimes 50%', 'Overtimes 100% (night)',
                  'Overtimes 100% others', 'Late', '', 'nocna od', 'nocna do',
                  'Work hours(计算)', 'Work hours校验',
                  '夜班工时(计算)', '夜班校验',
                  'OT50%(计算)', 'OT50%校验', 'OT100%夜(计算)', 'OT100%夜校验',
                  'OT100%其他(计算)', 'OT100%其他校验']
month_headers = ['来源文件', '姓名', '工号', '考勤记录天数', '出勤天数(工时>0)', '总工时', '夜班工时',
                 '加班50%', '加班100%(夜)', '加班100%(其他)', '迟到次数', '原表合计工时']
leave_detail_headers = ['来源文件', '姓名', '工号', '日期', '类型', '类型说明', '请假时数',
                        '请假时段', 'Remarks原文', '时数来源']
leave_sum_headers = ['来源文件', '姓名', '工号',
                     'UW天数', 'UW时数', 'FML天数', 'FML时数',
                     'NN天数', 'NN时数', 'UNPAID天数', 'UNPAID时数',
                     'L4天数', 'L4时数',
                     '其他带薪天数', '其他带薪时数',
                     '请假总天数', '请假总时数',
                     'Holidays from- to/hours', 'Unpaid holidays', 'Sick leaves-from-to/days',
                     '待确认的其他假期']

detail_rows = []
month_rows = []
norma_headers = ['来源文件', '姓名', '工号', '考勤记录天数', '出勤天数(工时>0)', '出勤工时(work hours)',
                 '夜班工时汇总', '请假工时', 'OT工时合计', '加班50%', '加班100%(夜)',
                 '加班100%(其他)', '考勤表推算标准工时', '月度标准工时Norma', '差异(推算-Norma)', '备注']
leave_detail = []
person_leave = {}
person_events = defaultdict(lambda: defaultdict(list))
person_modal = {}
person_order = []
norma_rows = []

num_re = re.compile(r'(\d+[.,]\d+|\d+)')
code_re = re.compile(r'(uw|nn|fml|l4)', re.IGNORECASE)
range_re = re.compile(r'(\d{1,2})[-–](\d{1,2})')


def r2(x):
    return round(float(x), 2) if x is not None else None


def fmt_num(x):
    x = round(float(x), 2)
    return str(int(x)) if x == int(x) else str(x)


def _to_min(v):
    """将打卡时间(可能是 datetime.time / datetime / '15:00' 字符串)转为分钟数。"""
    if v is None:
        return None
    if isinstance(v, datetime.time):
        return v.hour * 60 + v.minute
    if isinstance(v, datetime.datetime):
        return v.hour * 60 + v.minute
    s = str(v).strip().replace('.', ':')
    if ':' in s:
        p = s.split(':')
        try:
            return int(p[0]) * 60 + int(p[1])
        except ValueError:
            return None
    return None


def night_overlap(ci_raw, co_raw):
    """根据上下班打卡时间计算夜班工时(小时)。

    夜班时段：22:00–06:00（次日）。员工实际工作区间与夜班时段取交集。
    返回 (夜班_2206, 夜班_2207)：前者按 22:00–06:00 口径，后者按 22:00–07:00 口径
    （用于吸收 06:00/07:00 边界，避免把仅差 0.5h 的边界班次误判为错误）。
    缺打卡时间返回 (None, None)。
    """
    ci = _to_min(ci_raw)
    co = _to_min(co_raw)
    if ci is None or co is None:
        return (None, None)
    if co <= ci:                       # 跨午夜
        works = [(ci, 1440), (0, co)]
    else:
        works = [(ci, co)]
    segs06 = [(1320, 1440), (0, 360)]   # 22:00–06:00
    segs07 = [(1320, 1440), (0, 420)]   # 22:00–07:00

    def calc(segs):
        tot = 0
        for a, b in works:
            for na, nb in segs:
                lo, hi = max(a, na), min(b, nb)
                if hi > lo:
                    tot += hi - lo
        return round(tot / 60.0, 2)

    return (calc(segs06), calc(segs07))


# ===== 加班(OT)字段校验辅助函数 =====
def is_dayoff(name):
    """班次/列A含 Wolne / Day off / 公休 → 视为公休全天。"""
    if name is None:
        return False
    n = str(name).lower()
    return ('wolne' in n) or ('day off' in n) or ('公休' in n)


def regular_len(name):
    """解析班次常规工时(小时)；无法解析返回 None。

    - '10.5小时早班' → 10.5
    - 'Night Shift10.5' → 10.5
    - 'Special 8-18' → 10；'Warehouse 9-17' → 8；'Night Shift 15-23' → 8；'Warehouse 17-1' → 8
    - 'Warehouse 8h' → 8；'flexible schedule 2.5' / '2.5h' / '6.5H' / '1h' → 2.5/2.5/6.5/1
    - 弹性班次/Office → 8（默认）
    """
    if name is None:
        return None
    n = str(name)
    nl = n.lower()
    m = re.search(r'(\d+(?:\.\d+)?)\s*小时', n)
    if m:
        return float(m.group(1))
    # 区间须先于 "ShiftX" 匹配，否则 'Night Shift 15-23' 会被取成 15
    m = range_re.search(n)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        diff = b - a
        if diff <= 0:
            diff += 24
        return float(diff)
    m = re.search(r'shift\s*(\d+(?:\.\d+)?)', nl)
    if m:
        return float(m.group(1))
    m = re.search(r'flexible schedule[ ]*(\d+(?:\.\d+)?)\s*[hH]?', nl)
    if m:
        return float(m.group(1))
    m = re.search(r'(\d+(?:\.\d+)?)\s*h', nl)
    if m:
        return float(m.group(1))
    # 仅 Office/弹性班次默认 8h；'flexible schedule' 无数字时不可臆断(交由按人推断)
    if ('弹性' in n) or ('office' in nl):
        return 8.0
    return None


def expected_ot(regular, stat_raw, end_raw, wh_raw, dayoff):
    """按时间模型推算期望的 (OT50, OT100夜, OT100其他)。

    规则（用户给定）：
    - 公休全天：全部工时 = OT100%(其他)。
    - 工作日：常规工作块 = [上班, 上班+常规工时]；其后为加班。
        · 班前/班后落在 22:00 之前的加班 → OT50。
        · 班后加班超过 22:00、落在 22:00–06:00 的部分 → OT100%(夜)。
    常规工时无法取得时返回 (None, None, None)。
    """
    if dayoff:
        return (0.0, 0.0, r2(wh_raw) or 0.0)
    if not wh_raw:
        # 当日无工时（休息/请假等）→ 不应有任何加班
        return (0.0, 0.0, 0.0)
    if regular is None:
        return (None, None, None)
    wh = wh_raw or 0
    ci = _to_min(stat_raw)
    co = _to_min(end_raw)
    if ci is None or co is None:
        # 缺打卡时间：退化为 WH - 常规工时（全记 OT50）
        ot = max(0.0, round(wh - regular, 2))
        return (ot, 0.0, 0.0)
    if co <= ci:                       # 跨午夜
        co += 1440
    reg_end = ci + int(round(regular * 60))
    if co <= reg_end:
        ot_total = 0.0
    else:
        ot_total = round((co - reg_end) / 60.0, 2)
    # 班后加班落在 22:00–06:00 的部分 = OT100%(夜)
    night_ot = 0.0
    for base in (0, 1440):
        for na, nb in ((1320, 1440), (0, 360)):
            lo, hi = max(reg_end, na + base), min(co, nb + base)
            if hi > lo:
                night_ot += hi - lo
    night_ot = round(night_ot / 60.0, 2)
    night_ot = min(night_ot, ot_total)
    ot50 = round(ot_total - night_ot, 2)
    return (ot50, night_ot, 0.0)


def ot_flag(exp, src):
    if exp is None:
        return '无法校验'
    d = abs((src or 0) - exp)
    if d <= 0.25:
        return '✓一致'
    if d < 0.5:
        return '⚠偏差'
    return '✗异常'


def src_label(f):
    name = os.path.basename(f).replace('.xlsx', '')
    name = re.sub(r'^OK - Tabelki ', '', name)
    name = re.sub(r'^Tabelki ', '', name)
    return name


def parse_dm(d):
    if d is None:
        return (None, None)
    if isinstance(d, (datetime.datetime, datetime.date)):
        return (d.day, d.month)
    s = str(d).strip()
    for sep in ('/', '-'):
        if sep in s:
            parts = s.split(sep)
            if len(parts) >= 3:
                try:
                    return (int(parts[2]), int(parts[1]))
                except ValueError:
                    return (None, None)
    return (None, None)


def build_runs(events):
    runs = []
    for day, month, hrs in sorted(events, key=lambda x: (x[1], x[0])):
        if runs and runs[-1]['end'] == day - 1 and runs[-1]['hrs'] == round(hrs, 2) \
                and runs[-1]['month'] == month:
            runs[-1]['end'] = day
        else:
            runs.append({'start': day, 'end': day, 'hrs': round(hrs, 2), 'month': month})
    return runs


def fmt_leave(events, prefix):
    if not events:
        return ''
    runs = build_runs(events)
    total = round(sum(h for _, _, h in events), 2)
    if len(events) == 1:
        day, m, hrs = events[0]
        return f"{prefix}{day}.{m}-{fmt_num(hrs)}godziny"
    hours_set = set(round(h, 2) for _, _, h in events)
    if len(hours_set) == 1:
        # 时数一致(same)：紧凑列出日期/区间，仅末项带月份 .M，末尾用 x{hrs} 标注时数
        hrs = list(hours_set)[0]
        out = []
        for r in runs:
            if r['start'] == r['end']:
                out.append(f"{r['start']}")
            else:
                out.append(f"{r['start']}-{r['end']}")
        m = runs[-1]['month']
        out[-1] = f"{out[-1]}.{m}"
        return f"{prefix}{','.join(out)}x{fmt_num(hrs)}，sum{fmt_num(total)}godziny"
    # 时数不一致：按"时数"分组；同组日期/区间用逗号合并，仅每组末段带「.月份x时数」
    # （单日末段用 .月份-时数godziny；区间末段用 .月份x时数godziny）。
    # 组与组之间用全角「，」分隔，符合审计规则的 diff 分支。
    by_h = {}
    order = []
    for r in runs:
        key = round(r['hrs'], 2)
        if key not in by_h:
            by_h[key] = []
            order.append(key)
        by_h[key].append(r)
    parts = []
    for key in order:
        grp = by_h[key]
        m = grp[-1]['month']
        txts = []
        for i, r in enumerate(grp):
            if r['start'] == r['end']:
                base = f"{r['start']}"
            else:
                base = f"{r['start']}-{r['end']}"
            if i == len(grp) - 1:
                if r['start'] == r['end']:
                    base = f"{base}.{m}-{fmt_num(key)}godziny"
                else:
                    base = f"{base}.{m}x{fmt_num(key)}godziny"
            txts.append(base)
        parts.append(','.join(txts))
    return f"{prefix}{'，'.join(parts)}，sum{fmt_num(total)}godziny"


def classify(code):
    if code in ('NN', 'UNPAID'):
        return 'unpaid'
    if code == 'L4':
        return 'sick'
    return 'paid'


def num_bucket(code):
    if code in ('UW', 'FML', 'NN', 'UNPAID', 'L4'):
        return code
    return '其他带薪'


def prefix_for(code):
    if code == 'UW':
        return ''
    if code == 'FML':
        return 'Siła wyższa：'
    return f"{code}："


def is_person_sheet(name):
    return isinstance(name, str) and any(c.isalpha() for c in name)


# AURORA 等辅助汇总表（如 Arkusz9 / 工作表8）不是个人考勤表：
# 其首行即表头、首数据行在第 2 行，E2 可能是班次名（如 'Morning Shift'）。
# 若不排除，会误被当作个人表抓取，产生 "Morning Shift" 之类假人员并污染汇总。
AUX_NAME_RE = re.compile(r'^(arkusz|工作表|sheet|tabel[ea]|ark)\b', re.IGNORECASE)
AUX_HDR_MARKERS = ('aurora', 'gender', 'position', 'arkusz', '工作表')


def is_aux_sheet(sname, rows):
    """判断是否为 AURORA/辅助汇总表，应在个人表循环里跳过。

    判定依据：
    ① 表名匹配辅助表命名（Arkusz* / 工作表* / Sheet* / Tabela* 等）；
    ② 首行表头含 aurora id / GENDER / POSITION 等 AURORA 标记。
    """
    if AUX_NAME_RE.match((sname or '').strip()):
        return True
    if rows and rows[0]:
        hdr = [str(x).lower() if x is not None else '' for x in rows[0]]
        if any(any(m in h for m in AUX_HDR_MARKERS) for h in hdr):
            return True
    return False


def parse_sched(a_val):
    """Extract shift length (hours) from column A text."""
    if a_val is None:
        return None
    s = str(a_val)
    m = re.search(r'(\d+[.,]?\d*)\s*小时', s)
    if m:
        return float(m.group(1).replace(',', '.'))
    m = re.search(r'(\d+)\s*hrs?\b', s, re.IGNORECASE)
    if m:
        return float(m.group(1))
    m = re.search(r'(\d+[.,]?\d*)\s*h\b', s, re.IGNORECASE)
    if m:
        return float(m.group(1).replace(',', '.'))
    m = range_re.search(s)
    if m:
        h1, h2 = int(m.group(1)), int(m.group(2))
        if 0 <= h1 <= 24 and 0 <= h2 <= 24 and h2 > h1:
            return h2 - h1
    # 'flexible schedule 5.5' —— 班次名里明确写了数字，直接取
    m = re.match(r'^\s*flexible schedule\s+(\d+[.,]?\d*)\s*$', s, re.IGNORECASE)
    if m:
        return float(m.group(1).replace(',', '.'))
    # 职能端弹性班次（Office）：班次名无数字，但已由全部 Office 人员的手工
    # 录入值(Annual/Sick/Other paid leaves)交叉验证 = 8h
    if re.search(r'弹性班次|Office', s, re.IGNORECASE):
        return 8.0
    # 裸 'flexible schedule' 等班次名无数字的情况：此处**不猜**，返回 None，
    # 交由上层按「标准工时 − 已知班次工时」倒推（见下方第二遍处理）。
    return None


def load_norma_map(wb):
    """从源文件的 report/raport 表读取每人「标准工时 Norma」。

    返回 (out, rev)：
      out: {ID或姓名(原序): norma}（主表，ID 优先）
      rev: {姓名反序(波兰名序↔西式名序): norma}（兜底，用于跨表名序不一致）
           例：源表 'Krogulewski Marcin' → 反序 'Marcin Krogulewski' 可匹配人员表。
    """
    out = {}
    rev = {}
    for sname in wb.sheetnames:
        if 'report' not in sname.lower() and 'raport' not in sname.lower():
            continue
        wsx = wb[sname]
        rr = list(wsx.iter_rows(min_row=1, max_row=wsx.max_row, max_col=8, values_only=True))
        if not rr:
            continue
        hh = rr[0]
        ic = iname = inorm = None
        for j, v in enumerate(hh):
            t = str(v).strip().lower() if v is not None else ''
            if t == 'id':
                ic = j
            elif 'row labels' in t:
                iname = j
            elif 'norma' in t:
                inorm = j
        if inorm is None:
            continue
        for row in rr[1:]:
            if inorm >= len(row):
                continue
            nv = row[inorm]
            if not isinstance(nv, (int, float)) or isinstance(nv, bool):
                continue
            if ic is not None and ic < len(row) and row[ic] not in (None, ''):
                out[str(row[ic]).strip()] = float(nv)
            if iname is not None and iname < len(row) and row[iname] not in (None, ''):
                nm = str(row[iname]).strip()
                # 去掉类似 '(UZL)' 的括号后缀后再取反序，避免污染
                base = re.sub(r'\s*\([^)]*\)\s*$', '', nm).strip()
                out[nm] = float(nv)
                parts = base.split()
                if len(parts) >= 2:
                    rk = ' '.join(reversed(parts))
                    if rk != nm:
                        rev[rk] = float(nv)
        break
    return out, rev


# ---- 预扫描：为「班次名无法解析常规工时」的人员，按其每日(工时-OT合计)推断常规工时 ----
person_regular = {}
for _f in FILES:
    _wb = openpyxl.load_workbook(_f, read_only=True, data_only=True)
    _src = src_label(_f)
    for _sname in _wb.sheetnames:
        _ws = _wb[_sname]
        _rows = list(_ws.iter_rows(min_row=1, max_row=_ws.max_row, max_col=15, values_only=True))
        if len(_rows) < 2:
            continue
        if is_aux_sheet(_sname, _rows):
            continue
        _r2 = _rows[1]
        _name = _r2[4] if len(_r2) > 4 else None
        if not is_person_sheet(_name):
            continue
        _key = (_src, _name.strip())
        for _r in _rows[3:]:
            if not _r or _r[1] is None:
                continue
            if regular_len(_r[0]) is not None or is_dayoff(_r[0]):
                continue
            _wh = _r[5] or 0
            _ot = (_r[8] or 0) + (_r[9] or 0) + (_r[10] or 0)
            _cand = round(_wh - _ot, 2)
            if 0 < _cand <= 16:
                person_regular.setdefault(_key, []).append(_cand)
    _wb.close()
person_regular = {k: Counter(v).most_common(1)[0][0]
                  for k, v in person_regular.items() if v}

for f in FILES:
    src = src_label(f)
    wb = openpyxl.load_workbook(f, read_only=True, data_only=True)
    norma_map, norma_rev = load_norma_map(wb)
    n_person = 0
    for sname in wb.sheetnames:
        ws = wb[sname]
        rows = list(ws.iter_rows(min_row=1, max_row=ws.max_row, max_col=15, values_only=True))
        if len(rows) < 2:
            continue
        if is_aux_sheet(sname, rows):
            continue
        r2info = rows[1]
        name = r2info[4] if len(r2info) > 4 else None
        if not is_person_sheet(name):
            continue
        emp_name = name.strip()
        emp_id = r2info[8] if len(r2info) > 8 else None
        key = (src, emp_name)
        if key not in person_leave:
            person_order.append(key)
            person_leave[key] = {c: [0, 0.0] for c in NUM_CODES}

        daily = [r for r in rows[3:] if r and r[1] is not None]
        # modal shift length from worked days (any remarks), fallback per site
        samples = []
        for r in daily:
            worked = r[5] or 0
            if worked > 0:
                samples.append(round(worked, 2))
        modal = Counter(samples).most_common(1)[0][0] if samples else None
        if modal is None:
            modal = 8.0 if 'Office' in src else 10.5
        person_modal[key] = modal

        rec_days = len(daily)
        present_days = sum(1 for r in daily if (r[5] or 0) > 0)
        total_wh = sum((r[5] or 0) for r in daily)
        night_h = sum((r[7] or 0) for r in daily)
        ot50 = sum((r[8] or 0) for r in daily)
        ot100n = sum((r[9] or 0) for r in daily)
        ot100o = sum((r[10] or 0) for r in daily)
        late_cnt = sum(1 for r in daily if r[11] not in (None, '', 0))
        orig_sum = None
        for r in rows:
            if r and r[4] == 'Sum:':
                orig_sum = r[5]
                break
        month_rows.append([src, emp_name, emp_id, rec_days, present_days, r2(total_wh),
                           r2(night_h), r2(ot50), r2(ot100n), r2(ot100o), late_cnt, r2(orig_sum)])
        n_person += 1

        # 该员工当月应出勤日数（非 Wolne 的天）与标准工时 Norma
        _src_i = len(month_rows) - 1
        sched_days = sum(1 for r in daily if 'wolne' not in str(r[0] or '').lower())
        emp_norma = None
        if emp_id is not None and str(emp_id).strip() in norma_map:
            emp_norma = norma_map[str(emp_id).strip()]
        elif emp_name in norma_map:
            emp_norma = norma_map[emp_name]
        elif emp_name in norma_rev:
            # 跨表名序不一致（如 'Krogulewski Marcin' ↔ 'Marcin Krogulewski'）兜底
            emp_norma = norma_rev[emp_name]

        # ---- 第一遍：逐日收集请假行；班次未标注工时的先挂起，稍后倒推 ----
        recs = []
        for r in daily:
            # 夜班工时校验：按 22:00-06:00 口径计算应得夜班工时，上限 8h，与源表 Night 列比对
            exp1, exp2 = night_overlap(r[2], r[3])
            night_src = r[7] or 0
            if exp1 is None:
                calc_val = None
                flag = '缺打卡时间' if night_src != 0 else '—'
            else:
                # 上限 8h：夜班工时最多 8 小时
                e1, e2 = min(exp1, 8.0), min(exp2, 8.0)
                # 取与源值更接近的窗（吸收 06:00/07:00 边界，避免把仅差0.5h的边界班次误判）
                if abs(night_src - e1) <= abs(night_src - e2):
                    calc_val, best = e1, abs(night_src - e1)
                else:
                    calc_val, best = e2, abs(night_src - e2)
                if best <= 0.25:
                    flag = '✓一致'
                elif best < 0.5:
                    flag = '⚠偏差'
                else:
                    flag = '✗异常'
            # Work hours 校验：由上下班打卡时间推算期望工时 = 下班 − 上班（跨午夜按 +24h 处理），
            # 与源表 Work hours 列比对。请假/休息日(WH≤0)或含请假代码的日期不判异常。
            _ci = _to_min(r[2]); _co = _to_min(r[3])
            wh_src = r[5] or 0
            if _ci is None or _co is None:
                wh_calc = None
                wh_flag = '缺打卡时间' if wh_src != 0 else '—'
            else:
                _span = (_co + 1440 - _ci) if _co <= _ci else (_co - _ci)
                wh_calc = round(_span / 60.0, 2)
                if wh_src <= 0:
                    wh_flag = '—'           # 非出勤日（请假/休息），无法以打卡时长衡量
                elif re.search(r'[A-Za-z]', str(r[6] or '')):
                    wh_flag = '—'           # 含请假代码的日期（部分出勤/请假），不纳入纯出勤校验
                else:
                    _d = abs(wh_calc - wh_src)
                    wh_flag = '✓一致' if _d <= 0.25 else ('⚠偏差' if _d < 0.5 else '✗异常')
            # OT 三项校验：OT50 / OT100%(夜) / OT100%(其他)
            _rlen = regular_len(r[0])
            if _rlen is None:
                _rlen = person_regular.get(key)
            _dayoff = is_dayoff(r[0])
            e_ot50, e_otn, e_oto = expected_ot(_rlen, r[2], r[3], r[5], _dayoff)
            f_ot50 = ot_flag(e_ot50, r[8])
            f_otn = ot_flag(e_otn, r[9])
            f_oto = ot_flag(e_oto, r[10])
            detail_rows.append([src, emp_name, emp_id] + list(r[0:15])
                               + [wh_calc, wh_flag, calc_val, flag,
                                  e_ot50, f_ot50, e_otn, f_otn, e_oto, f_oto])
            g = r[6]
            if g in (None, '', 0):
                continue
            gstr = str(g)
            cm = code_re.search(gstr)
            if cm:
                code = cm.group(1).upper()
                code_token = cm.group(0)
            else:
                tm = re.search(r'[A-Za-z]+', gstr)
                code = tm.group(0).upper() if tm else '其他'
                code_token = tm.group(0) if tm else ''
            sched = parse_sched(r[0])
            worked = r[5] or 0
            # strip the leave-code token (e.g. 'L4') before searching for an
            # explicit hours number, so digits inside the code are not misread
            rest = gstr.replace(code_token, ' ', 1) if code_token else gstr
            nm = num_re.search(rest)
            if nm:
                hours = float(nm.group(1).replace(',', '.'))
                hsource = 'Remarks数字'
            elif sched is not None:
                hours = round(sched - worked, 2)
                hsource = '班制推导(班制-工时)'
            else:
                hours = None          # 待倒推
                hsource = '标准工时倒推'
            clocked = (r[2] is not None) or (r[3] is not None)
            seg = '小时假' if clocked else '整日假'
            # skip non-leave artifact: labelled leave but fully worked (derived 0h, no explicit number)
            # 注：班次未标注的行保留（待倒推），保证请假日期不丢失
            if hours is not None and hours <= 0 and nm is None:
                continue
            recs.append({'row': r, 'code': code, 'gstr': gstr, 'seg': seg,
                         'hours': hours, 'hsource': hsource,
                         'marked': hours is not None})

        # ---- 第二遍：未标注班次的日子，按「标准工时 − 已知班次工时」倒推 ----
        for code in {x['code'] for x in recs}:
            grp = [x for x in recs if x['code'] == code]
            pend = [x for x in grp if not x['marked']]
            if not pend:
                continue
            known = round(sum(x['hours'] for x in grp if x['marked']), 2)
            # 该假别是否覆盖当月全部应出勤日 → 合计应等于标准工时
            if emp_norma and len(grp) == sched_days and sched_days > 0:
                residual = round(emp_norma - known, 2)
                if residual > 0:
                    each = round(residual / len(pend), 2)
                    for x in pend:
                        x['hours'] = each
                        x['hsource'] = f'标准工时倒推({emp_norma:g}-{known:g})/{len(pend)}'
                    continue
            # 其余情况：用源表实证值 2.5（flexible schedule 等未标注班次）
            for x in pend:
                x['hours'] = 2.5
                x['hsource'] = '未标注班次(实证2.5)'

        for x in recs:
            r, code, gstr, seg = x['row'], x['code'], x['gstr'], x['seg']
            hours, hsource = x['hours'], x['hsource']
            leave_detail.append([src, emp_name, emp_id, r[1], code, LEAVE_LABELS.get(code, '其他'),
                                 hours, seg, gstr, hsource])
            nb = num_bucket(code)
            person_leave[key][nb][0] += 1
            person_leave[key][nb][1] += hours
            dm = parse_dm(r[1])
            person_events[key][code].append((dm[0], dm[1], hours))

        # ---- 考勤表自身推算的标准工时 = 总工时(work hours) + 全部请假工时 − 全部 OT ----
        # 月度标准工时可能与之不一致；若不一致说明考勤表数据有误，需返回考勤专员修改。
        leave_total = round(sum(x['hours'] for x in recs), 2)
        ot_total = round(ot50 + ot100n + ot100o, 2)
        sheet_std = round(total_wh + leave_total - ot_total, 2)
        norma_rows.append([src, emp_name, emp_id, rec_days, present_days, r2(total_wh),
                           r2(night_h), leave_total, ot_total,
                           r2(ot50), r2(ot100n), r2(ot100o), sheet_std, emp_norma,
                           (round(sheet_std - emp_norma, 2) if emp_norma is not None else None)])
    print(f"  {src:32} persons={n_person}")

# build leave summary rows
paid_order = ['UW', 'FML']
leave_sum_rows = []
for key in person_order:
    src, name = key
    d = person_leave[key]
    uw = d['UW']; fml = d['FML']; oth = d['其他带薪']; nn = d['NN']; unp = d['UNPAID']; l4 = d['L4']
    tot_days = uw[0] + fml[0] + oth[0] + nn[0] + unp[0] + l4[0]
    tot_h = r2(uw[1] + fml[1] + oth[1] + nn[1] + unp[1] + l4[1])
    ev = person_events[key]
    codes_present = [c for c in ev.keys() if classify(c) == 'paid']
    ordered = [c for c in paid_order if c in codes_present] + \
              sorted([c for c in codes_present if c not in paid_order])
    # 归入「其他带薪」的假别（MATERNITY/PARENTAL/FUNERAL/PAID/PERSONAL/M 等）
    # 单独放进「待确认的其他假期」字段，不再混入 Holidays
    other_codes = [c for c in ordered if num_bucket(c) == '其他带薪']
    keep_codes = [c for c in ordered if num_bucket(c) != '其他带薪']
    paid_lines = [fmt_leave(ev[c], prefix_for(c)) for c in keep_codes]
    other_paid_str = "\n".join(fmt_leave(ev[c], prefix_for(c)) for c in other_codes)
    holidays_str = "\n".join(paid_lines)
    # NN（无故缺勤）登记时带波兰语说明前缀；UNPAID 保持无前缀
    nn_str = fmt_leave(ev.get('NN', []), 'Nieusprawiedliwiona nieobecność：')
    unp_str = fmt_leave(ev.get('UNPAID', []), '')
    unpaid_str = "\n".join([x for x in (nn_str, unp_str) if x])
    sick_str = fmt_leave(ev.get('L4', []), "")
    leave_sum_rows.append([src, name, None,
                           uw[0], r2(uw[1]), fml[0], r2(fml[1]),
                           nn[0], r2(nn[1]), unp[0], r2(unp[1]), l4[0], r2(l4[1]),
                           oth[0], r2(oth[1]),
                           tot_days, tot_h, holidays_str, unpaid_str, sick_str,
                           other_paid_str])
id_map = {(m[0], m[1]): m[2] for m in month_rows}
for row in leave_sum_rows:
    row[2] = id_map.get((row[0], row[1]))

print("Total persons:", len(month_rows))
print("Detail rows:", len(detail_rows))
print("Leave events:", len(leave_detail))
night_anom = sum(1 for row in detail_rows if len(row) >= 22 and row[21] == '✗异常')
night_warn = sum(1 for row in detail_rows if len(row) >= 22 and row[21] == '⚠偏差')
night_na = sum(1 for row in detail_rows if len(row) >= 22 and row[21] == '缺打卡时间')
wh_anom = sum(1 for row in detail_rows if len(row) >= 20 and row[19] == '✗异常')
wh_warn = sum(1 for row in detail_rows if len(row) >= 20 and row[19] == '⚠偏差')
wh_na = sum(1 for row in detail_rows if len(row) >= 20 and row[19] == '缺打卡时间')
ot_anom = sum(1 for row in detail_rows if len(row) >= 28 and (row[23] == '✗异常' or row[25] == '✗异常' or row[27] == '✗异常'))
ot_warn = sum(1 for row in detail_rows if len(row) >= 28 and (row[23] == '⚠偏差' or row[25] == '⚠偏差' or row[27] == '⚠偏差'))
ot_na = sum(1 for row in detail_rows if len(row) >= 28 and (row[23] == '无法校验' or row[25] == '无法校验' or row[27] == '无法校验'))
print(f"Work hours校验: 异常 {wh_anom} 行，偏差 {wh_warn} 行，缺打卡时间 {wh_na} 行")
print(f"夜班工时校验: 异常 {night_anom} 行，偏差 {night_warn} 行，缺打卡时间 {night_na} 行")
print(f"OT三项校验: 异常 {ot_anom} 行，偏差 {ot_warn} 行，无法校验 {ot_na} 行")

# ---- write output ----
owb = openpyxl.Workbook()
thin = Side(style='thin', color='D0D0D0')
border = Border(left=thin, right=thin, top=thin, bottom=thin)
hdr_fill = PatternFill('solid', fgColor='4472C4')
hdr_font = Font(bold=True, color='FFFFFF')
hdr_align = Alignment(horizontal='center', vertical='center', wrap_text=True)


def style_header(ws, ncols):
    for c in range(1, ncols + 1):
        cell = ws.cell(1, c)
        cell.fill = hdr_fill
        cell.font = hdr_font
        cell.alignment = hdr_align
        cell.border = border


dws = owb.active
dws.title = '考勤明细汇总'
dws.append(detail_headers)
for row in detail_rows:
    dws.append(row)
style_header(dws, len(detail_headers))
for r in range(2, dws.max_row + 1):
    for c in (6, 7):
        dws.cell(r, c).number_format = 'hh:mm'
dws.freeze_panes = 'A2'
dws.auto_filter.ref = f"A1:{get_column_letter(dws.max_column)}{dws.max_row}"
for i, w in enumerate([26, 20, 12, 26, 12, 9, 9, 16, 11, 10, 9, 12, 16, 18, 8, 6, 10, 10, 14, 12,
                      14, 12, 12, 11, 13, 11, 14, 11], 1):
    dws.column_dimensions[get_column_letter(i)].width = w
for r in range(2, dws.max_row + 1):
    dws.cell(r, 19).number_format = '0.00'      # Work hours(计算)
    dws.cell(r, 21).number_format = '0.00'      # 夜班工时(计算)
    dws.cell(r, 23).number_format = '0.00'      # OT50%(计算)
    dws.cell(r, 25).number_format = '0.00'      # OT100%夜(计算)
    dws.cell(r, 27).number_format = '0.00'      # OT100%其他(计算)
# 校验列着色：红=异常(✗)，黄=偏差(⚠)，蓝=无法校验
_nf_red = PatternFill('solid', fgColor='FFC7CE')
_nf_yel = PatternFill('solid', fgColor='FFF2CC')
_nf_blu = PatternFill('solid', fgColor='DDEBF7')
for r in range(2, dws.max_row + 1):
    for c in (22, 24, 26, 28, 30):
        fv = dws.cell(r, c).value
        if fv == '✗异常':
            dws.cell(r, c).fill = _nf_red
        elif fv == '⚠偏差':
            dws.cell(r, c).fill = _nf_yel
        elif fv == '无法校验':
            dws.cell(r, c).fill = _nf_blu

lws = owb.create_sheet('请假明细')
lws.append(leave_detail_headers)
for row in leave_detail:
    lws.append(row)
style_header(lws, len(leave_detail_headers))
lws.freeze_panes = 'A2'
for i, w in enumerate([26, 20, 12, 12, 10, 12, 10, 22, 24, 18], 1):
    lws.column_dimensions[get_column_letter(i)].width = w

sws = owb.create_sheet('请假统计(按人)')
sws.append(leave_sum_headers)
for row in leave_sum_rows:
    sws.append(row)
style_header(sws, len(leave_sum_headers))
sws.freeze_panes = 'A2'
for i, w in enumerate([26, 20, 12, 9, 9, 9, 9, 11, 11, 9, 9, 11, 11, 9, 9, 11, 11, 42, 30, 30, 42], 1):
    sws.column_dimensions[get_column_letter(i)].width = w
wrap_align = Alignment(horizontal='left', vertical='top', wrap_text=True)
for r in range(2, sws.max_row + 1):
    for c in (18, 19, 20, 21):
        sws.cell(r, c).alignment = wrap_align

nws = owb.create_sheet('标准工时校验')
nws.append(norma_headers)
for row in norma_rows:
    nws.append(row)
style_header(nws, len(norma_headers))
nws.freeze_panes = 'C2'
for i, w in enumerate([26, 22, 12, 13, 14, 12, 12, 12, 12, 10, 12, 12, 16, 14, 11, 30], 1):
    nws.column_dimensions[get_column_letter(i)].width = w
# 列宽/冻结/筛选
nws.auto_filter.ref = f"A1:P{nws.max_row}"
warn_fill = PatternFill('solid', fgColor='FFF2CC')   # 黄：小差异
bad_fill = PatternFill('solid', fgColor='FFC7CE')    # 红：标准工时严重不一致
miss_fill = PatternFill('solid', fgColor='DDEBF7')   # 蓝：月度标准工时缺失
for r in range(2, nws.max_row + 1):
    norma = nws.cell(r, 14).value
    diff = nws.cell(r, 15).value
    note = nws.cell(r, 16)
    if norma is None or norma == 0:
        # 月度标准工时在考勤表里为 0/空 → 无法核对，属报表数据缺失
        for c in range(1, 17):
            nws.cell(r, c).fill = miss_fill
        note.value = '月度标准工时缺失(为0/空)，需补录后核对'
    elif isinstance(diff, (int, float)):
        d = abs(diff)
        if d >= 8:
            for c in range(1, 17):
                nws.cell(r, c).fill = bad_fill
            note.value = '推算标准工时与月度不一致(≥8h)，需返回考勤专员核对'
        elif d >= 0.01:
            for c in range(1, 17):
                nws.cell(r, c).fill = warn_fill
            note.value = '推算标准工时与月度小幅不一致(<8h)'
        else:
            note.value = '一致'
    else:
        note.value = '未取到月度标准工时'
print(f"标准工时校验: 共 {len(norma_rows)} 人，"
      f"标准工时不一致≥8h {sum(1 for x in norma_rows if isinstance(x[13],(int,float)) and x[13]>0 and isinstance(x[14],(int,float)) and abs(x[14])>=8)} 人，"
      f"小幅不一致 {sum(1 for x in norma_rows if isinstance(x[13],(int,float)) and x[13]>0 and isinstance(x[14],(int,float)) and 0<abs(x[14])<8)} 人，"
      f"月度标准工时缺失 {sum(1 for x in norma_rows if not isinstance(x[13],(int,float)) or x[13]==0)} 人")

# ---- 异常清单：供返回考勤专员核对的异常人员（从标准工时校验结果提炼）----
# 仅收录「非一致」人员，按严重度排序：严重不一致(红) → 缺失Norma(蓝) → 小幅不一致(黄)
exc_headers = ['来源文件', '姓名', '工号', '考勤表推算标准工时', '月度标准工时Norma',
               '差异(推算-Norma)', '异常类型', '处理建议']
exc_rows = []
for row in norma_rows:
    src, name, eid = row[0], row[1], row[2]
    sheet_std, norma, diff = row[12], row[13], row[14]
    if norma is None or norma == 0:
        etype = '月度标准工时缺失(为0/空)'
        suggestion = '考勤表月度标准工时为0/空，退回考勤专员补录后核对'
        rank, fill = 1, miss_fill
    elif isinstance(diff, (int, float)):
        d = abs(diff)
        if d >= 8:
            etype = '标准工时严重不一致(≥8h)'
            suggestion = '考勤表数据与月度标准工时不符，退回考勤专员核对修正'
            rank, fill = 0, bad_fill
        elif d >= 0.01:
            etype = '标准工时小幅不一致(<8h)'
            suggestion = '差异较小，建议确认是否四舍五入或漏记所致'
            rank, fill = 2, warn_fill
        else:
            continue  # 一致，不进入异常清单
    else:
        continue
    exc_rows.append((rank, abs(diff) if isinstance(diff, (int, float)) else 0,
                     [src, name, eid, sheet_std, norma, diff, etype, suggestion], fill))
# 先按严重度 rank，再按差异绝对值降序
exc_rows.sort(key=lambda x: (x[0], -x[1]))
exc_data = [r[2] for r in exc_rows]
exc_fills = [r[3] for r in exc_rows]

ews = owb.create_sheet('异常清单')
ews.append(exc_headers)
for r in exc_data:
    ews.append(r)
style_header(ews, len(exc_headers))
for i, fill in enumerate(exc_fills, start=2):
    for c in range(1, len(exc_headers) + 1):
        ews.cell(i, c).fill = fill
for r in range(2, ews.max_row + 1):
    for c in (4, 5, 6):
        ews.cell(r, c).number_format = '0.00'
ews.freeze_panes = 'A2'
for i, w in enumerate([26, 22, 12, 16, 14, 14, 22, 38], 1):
    ews.column_dimensions[get_column_letter(i)].width = w
# 移到第一张，便于直接交给考勤专员核对修正
ews_pos = owb.sheetnames.index('异常清单')
owb.move_sheet('异常清单', -ews_pos)
n_bad = sum(1 for x in exc_rows if x[3] is bad_fill)
n_miss = sum(1 for x in exc_rows if x[3] is miss_fill)
n_warn = sum(1 for x in exc_rows if x[3] is warn_fill)
print(f"异常清单: 严重不一致 {n_bad} 人，缺失Norma {n_miss} 人，小幅不一致 {n_warn} 人，合计 {len(exc_rows)} 人")

# ---- 追加「Report汇总(指定表头)」表 ----
# 优先按「所选考勤表 + 汇总字段模板」现场生成（通用、可复用于任意文件组合）；
# 模板不可用时才回退读取已生成的指定表头工作簿（兼容旧批处理）。
REPORT_SUMMARY = f"{BASE}/9.3/波兰考勤Report汇总_指定表头_2026年7-8月.xlsx"
_tpl = TEMPLATE if TEMPLATE else (DEFAULT_TEMPLATE if os.path.exists(DEFAULT_TEMPLATE) else None)
if not NO_REPORT and _tpl and os.path.exists(_tpl):
    try:
        import report_summary as _rs
        _target, _rrows_data = _rs.build_canonical_rows(FILES, _tpl)
        if 'Report汇总(指定表头)' in owb.sheetnames:
            del owb['Report汇总(指定表头)']
        rws = owb.create_sheet('Report汇总(指定表头)')
        _rs.write_canonical_sheet(rws, _target, _rrows_data)
        print(f"Report汇总(指定表头): 已并入 {rws.max_row - 1} 行")
    except Exception as _e:
        print(f"Report汇总(指定表头): 生成失败（{_e}），回退读取已生成工作簿")
        _rrows_data = None
else:
    _rrows_data = None

# 安全保护：回退读取的预生成工作簿对应的是「默认 10 文件」，
# 若本次导入的是其它文件组合则绝不能并入（否则会串入无关站点数据）。
_is_default_batch = {os.path.normcase(os.path.abspath(p)) for p in FILES} == \
                    {os.path.normcase(os.path.abspath(p)) for p in DEFAULT_FILES}
if (not NO_REPORT and _rrows_data is None and _is_default_batch
        and os.path.exists(REPORT_SUMMARY)):
    rwb = openpyxl.load_workbook(REPORT_SUMMARY, data_only=True)
    rws_src = rwb.active
    rrows = [list(r) for r in rws_src.iter_rows(min_row=1, max_row=rws_src.max_row, values_only=True)]
    RN = len(rrows[0])
    if 'Report汇总(指定表头)' in owb.sheetnames:
        del owb['Report汇总(指定表头)']
    rws = owb.create_sheet('Report汇总(指定表头)')
    rtext_cols = {1, 2, 3}
    for c in range(1, RN + 1):
        cell = rws.cell(1, c, rrows[0][c - 1])
        cell.fill = hdr_fill; cell.font = hdr_font; cell.alignment = hdr_align; cell.border = border
    for ridx, row in enumerate(rrows[1:], start=2):
        for c in range(1, RN + 1):
            v = row[c - 1]
            cell = rws.cell(ridx, c, v)
            cell.border = border
            cell.alignment = Alignment(vertical='center', horizontal='left' if c in rtext_cols else 'right')
            if c not in rtext_cols and isinstance(v, (int, float)):
                cell.number_format = '0.00'
    rwidths = {1: 38, 2: 12, 3: 24, 4: 9}
    for c in range(1, RN + 1):
        rws.column_dimensions[get_column_letter(c)].width = rwidths.get(c, 16)
    rws.row_dimensions[1].height = 42
    rws.freeze_panes = 'A2'
    rws.auto_filter.ref = f"A1:{get_column_letter(RN)}{rws.max_row}"
    print(f"Report汇总(指定表头): 已并入 {rws.max_row - 1} 行")

# ---- 可选：额外导出「Report原始字段」工作簿（每文件一张分表，保留原始表头）----
if RAW_OUT:
    try:
        import report_summary as _rs2
        _d = os.path.dirname(RAW_OUT)
        if _d and not os.path.isdir(_d):
            os.makedirs(_d, exist_ok=True)
        _n = _rs2.build_raw_workbook(FILES, RAW_OUT)
        print(f"Report原始字段: 已导出 {_n} 个分表 -> {RAW_OUT}")
    except Exception as _e2:
        print(f"Report原始字段: 导出失败（{_e2}）")

_d = os.path.dirname(OUT)
if _d and not os.path.isdir(_d):
    os.makedirs(_d, exist_ok=True)
owb.save(OUT)
print("Saved ->", OUT)

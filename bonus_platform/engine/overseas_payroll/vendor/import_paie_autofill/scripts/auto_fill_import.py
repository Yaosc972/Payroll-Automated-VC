#!/usr/bin/env python3
"""
import_variables_paie 自动填写脚本 (改进版 v2)
基于每周工资计算表，自动填写 Gonesse/Nanteuil/SM 三个 import 模板。

改进点 (相对 v1):
  - 地点从「月工资合计」Sheet 的 A列(地点)+B列(姓名) 获取
    (部分月份周出勤 Sheet 无地点列)
  - 请假代码大小写/拼写容错: 支持 'Heure de repos' / 'HEURES REPOS' / 'CSS' / 'CP' / 'rtt'
  - CSS「Absence injustifiée」列头不含 'css' 关键词也能正确检测
  - 公休通用化: 识别 2026 全年法国法定节假日列 (5/1,5/8,5/14,7/14...),
    JF->不填 Fériés, 数字->填入 (本月均为 JF, 故 Fériés 为空)
  - HS 50% 封顶 = 周数 × 5 (5周=25h, 4周=20h)
  - 年月(ym)从模板目录名 (如 202605-) 或文件名推导, 兼容无"年"的文件名
  - 过滤月工资合计中的垃圾备注行 (含 '/' 或纯备注)

用法:
    python auto_fill_import.py <每周工资计算表路径> <模板目录>

输出:
    在模板目录(或每周表同目录)下生成三个 "(自动生成).xlsx" 文件。
"""

import os
import re
import sys
from datetime import datetime, date, timedelta
from collections import defaultdict

import openpyxl


# ============================================================
# 固定列位置
# ============================================================

WEEKLY_COLS = {
    'name': 1,        # A: 员工姓名
    'daily_start': 2, # B-H: 每日出勤 (2-8)
    'daily_end': 8,
    'hs_125': 16,     # P: HS 1.25
    'hs_150': 17,     # Q: HS 1.5 Payfit输入
}

MONTHLY_COLS = {
    'location': 1,    # A: 地点
    'name': 2,        # B: 员工姓名
    'rd_abs': 8,      # H: RD/ABS总计
}

# 2026 法国法定节假日 (用于 Fériés 通用识别)
FRENCH_HOLIDAYS_2026 = {
    date(2026, 1, 1), date(2026, 4, 6), date(2026, 5, 1), date(2026, 5, 8),
    date(2026, 5, 14), date(2026, 5, 25), date(2026, 7, 14), date(2026, 8, 15),
    date(2026, 11, 1), date(2026, 11, 11), date(2026, 12, 25),
}


def _to_date(val):
    """把表头日期单元格值统一转成 date。
    兼容两种来源: datetime 对象 或 字符串 '2026/06/25' (部分月份源表表头是字符串)。
    转不了返回 None。
    """
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    if isinstance(val, str):
        s = val.strip().replace('/', '-')
        for fmt in ('%Y-%m-%d', '%d-%m-%Y', '%Y/%m/%d', '%d/%m/%Y'):
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                continue
    return None


def classify_leave_code(raw):
    """把日列文本值归类为请假类型, 返回 'cp'/'css'/'repos'/'rtt' 或 None"""
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if not s:
        return None
    if s == 'cp':
        return 'cp'
    if 'css' in s:
        return 'css'
    if 'repos' in s:           # 'heure de repos' / 'heures repos' 等
        return 'repos'
    if 'rtt' in s:
        return 'rtt'
    return None                 # 'JF' / 'AM' / '其他带薪' 等不在此处处理


# ============================================================
# 动态检测 import 模板列位置
# ============================================================

def detect_columns(ws):
    cols = {}
    headers = {}
    for col in range(1, ws.max_column + 1):
        v = ws.cell(row=2, column=col).value
        if v is not None:
            headers[col] = str(v).strip().lower()

    def find_col(*keywords, exclude=None):
        for col, text in headers.items():
            if all(kw.lower() in text for kw in keywords):
                if exclude and exclude.lower() in text:
                    continue
                return col
        return None

    cols['cp_start'] = find_col('cp', 'début') or find_col('cp', 'debut')
    cols['cp_end'] = find_col('cp', 'fin')
    cols['cp_choix'] = find_col('cp', 'choix')

    cols['css_start'] = find_col('css', 'début') or find_col('css', 'debut')
    cols['css_end'] = find_col('css', 'fin')
    cols['css_choix'] = find_col('css', 'choix')
    # 注意: 「Absence injustifiée」列头不含 'css', 单独用 'absence'+'injustifiée' 检测
    cols['css_injustifiee'] = find_col('absence', 'injustifiée') or find_col('absence', 'injustifiee')

    cols['repos_start'] = find_col('repos', 'début') or find_col('repos', 'debut')
    cols['repos_end'] = find_col('repos', 'fin')
    cols['repos_choix'] = find_col('repos', 'choix')
    cols['repos_solde'] = find_col('repos', 'solde')
    cols['repos_heures'] = find_col('repos', 'décompter') or find_col('repos', 'decompter')

    cols['rtt_start'] = find_col('rtt', 'début') or find_col('rtt', 'debut')
    cols['rtt_end'] = find_col('rtt', 'fin')

    cols['hs_25'] = find_col('25%', exclude='50%') or find_col('supplémentaires', '25%')
    cols['hs_50'] = find_col('50%')

    cols['dim_hab'] = find_col('dimanche', 'habituel')
    cols['dim_exc'] = find_col('dimanche', 'exceptionnel')
    cols['dim_nb'] = find_col('nombre', 'dimanche')

    cols['feries'] = find_col('fériés', 'habituelles') or find_col('feries', 'habituelles')

    # Heures d'absence — 精确匹配, 不能只匹配 'absence'
    cols['heures_absence'] = None
    for col, text in headers.items():
        if "heures d'absence" in text or "heures d absence" in text or "heures absence" in text:
            cols['heures_absence'] = col
            break

    required = ['cp_start', 'cp_end', 'css_start', 'css_end',
                'repos_start', 'repos_end', 'hs_25', 'hs_50',
                'feries', 'heures_absence']
    missing = [k for k in required if cols.get(k) is None]
    if missing:
        print(f"  WARNING: 以下列未检测到: {missing}")
        print(f"  已检测到的列: {cols}")
    return cols


# ============================================================
# 数据结构
# ============================================================

class EmployeeWeeklyData:
    def __init__(self):
        self.location = None
        self.leave_segments = defaultdict(list)
        self.leave_days = defaultdict(int)
        self.hs_125_total = 0
        self.hs_150_total = 0
        self.holiday_hours = {}   # {date: number} 公休当日实际出勤工时
        self.monthly_absence = 0


# ============================================================
# 解析每周工资计算表 + 月工资合计
# ============================================================

def _is_junk_name(name):
    """月工资合计中的垃圾备注行过滤"""
    if not name:
        return True
    if '/' in name:
        return True
    if not re.search(r'[A-Za-z]', name):   # 纯中文/无拉丁字母的备注
        return True
    return False


def parse_weekly_file(filepath):
    wb = openpyxl.load_workbook(filepath, data_only=True)

    weekly_sheets = [s for s in wb.sheetnames if '出勤情况' in s]
    monthly_sheets = [s for s in wb.sheetnames if '工资合计' in s]

    if not weekly_sheets:
        raise ValueError("未找到包含'出勤情况'的Sheet")
    if not monthly_sheets:
        raise ValueError("未找到包含'工资合计'的Sheet")

    employees = defaultdict(EmployeeWeeklyData)

    # ---- 月工资合计: 地点 + 缺勤 ----
    monthly_map = {}   # norm_name -> (location, absence)
    ms = wb[monthly_sheets[0]]
    for row in range(2, ms.max_row + 1):
        name = ms.cell(row=row, column=MONTHLY_COLS['name']).value
        if not name:
            continue
        name = str(name).strip()
        if _is_junk_name(name):
            continue
        loc = ms.cell(row=row, column=MONTHLY_COLS['location']).value
        if not loc:
            continue
        h_val = ms.cell(row=row, column=MONTHLY_COLS['rd_abs']).value
        absence = abs(h_val) if (isinstance(h_val, (int, float)) and h_val < 0) else 0
        n = normalize_name(name)
        if n not in monthly_map:
            monthly_map[n] = (str(loc).strip().upper(), absence)

    # ---- 周出勤: 请假段 + 加班 + 公休 ----
    for sn in weekly_sheets:
        ws = wb[sn]
        sheet_dates = []
        for col in range(WEEKLY_COLS['daily_start'], WEEKLY_COLS['daily_end'] + 1):
            sheet_dates.append(ws.cell(row=1, column=col).value)

        # 公休列 (日期属于 2026 法定节假日)
        holiday_cols = []   # (col_index, date)
        for i, raw_d in enumerate(sheet_dates):
            d = _to_date(raw_d)
            if d and d in FRENCH_HOLIDAYS_2026:
                holiday_cols.append((WEEKLY_COLS['daily_start'] + i, d))

        for row in range(2, ws.max_row + 1):
            name = ws.cell(row=row, column=WEEKLY_COLS['name']).value
            if not name or not str(name).strip():
                continue
            name = str(name).strip()
            if _is_junk_name(name):
                continue
            if not re.search(r'[A-Za-z]', name):
                continue

            emp = employees[name]

            # 每日请假标记
            for i, col in enumerate(range(WEEKLY_COLS['daily_start'], WEEKLY_COLS['daily_end'] + 1)):
                v = ws.cell(row=row, column=col).value
                if v is None or not isinstance(v, str) or not v.strip():
                    continue
                code = classify_leave_code(v)
                if code:
                    dd = sheet_dates[i] if i < len(sheet_dates) else None
                    d = _to_date(dd)
                    if d:
                        emp.leave_days[code] += 1
                        emp.leave_segments[code].append(d)

            # 公休当日值
            for hcol, hd in holiday_cols:
                v = ws.cell(row=row, column=hcol).value
                if isinstance(v, (int, float)) and v > 0:
                    emp.holiday_hours[hd] = v
                # 'JF' 字符串: 不记录 (当日放假, Fériés 不填)

            # 加班
            p = ws.cell(row=row, column=WEEKLY_COLS['hs_125']).value
            if isinstance(p, (int, float)) and p:
                emp.hs_125_total += p
            q = ws.cell(row=row, column=WEEKLY_COLS['hs_150']).value
            if isinstance(q, (int, float)) and q:
                emp.hs_150_total += q

    # ---- 用月工资合计补全地点/缺勤 (含仅出现在月表、未出现在周表的员工) ----
    for mname_norm, (loc, absence) in monthly_map.items():
        # 找到对应的周表员工名
        wk_name = _find_key_by_norm(employees, mname_norm)
        if wk_name is None:
            # 该员工只在月表出现 (如纯缺勤), 新建一条
            emp = EmployeeWeeklyData()
            emp.location = loc
            emp.monthly_absence = absence
            employees[mname_norm] = emp   # 以 norm 名作 key, 后续匹配仍能命中
        else:
            emp = employees[wk_name]
            if not emp.location:
                emp.location = loc
            if absence and not emp.monthly_absence:
                emp.monthly_absence = absence

    return employees, len(weekly_sheets)


def normalize_name(name):
    return str(name).strip().lower().replace('  ', ' ')


def _find_key_by_norm(d, norm):
    for k in d:
        if normalize_name(k) == norm:
            return k
    return None


def merge_consecutive_dates(dates, holidays=None):
    if not dates:
        return []
    holidays = holidays or set()
    # 归一化: 源表日期常为 datetime, 节假日集合为 date, 统一成 date 才能正确比对
    def _d(x):
        return x.date() if isinstance(x, datetime) else x
    sd = sorted(set(_d(d) for d in dates))
    segments = []
    start = prev = sd[0]
    for d in sd[1:]:
        if d == prev + timedelta(days=1):
            prev = d
        elif d <= prev + timedelta(days=3):
            gap_days = (d - prev).days
            all_holi = True
            for gap in range(1, gap_days):
                mid = prev + timedelta(days=gap)
                if mid.weekday() < 5 and mid not in holidays:
                    all_holi = False
                    break
            if all_holi:
                prev = d
            else:
                segments.append((start, prev)); start = d; prev = d
        else:
            segments.append((start, prev)); start = d; prev = d
    segments.append((start, prev))
    return segments


# ============================================================
# 姓名匹配
# ============================================================

def name_tokens(name):
    return str(name).strip().lower().split()

def match_employee(weekly_name, template_names):
    weekly_norm = normalize_name(weekly_name)
    weekly_tokens = set(name_tokens(weekly_name))

    for tn in template_names:
        if normalize_name(tn) == weekly_norm:
            return tn
    for tn in template_names:
        tn_norm = normalize_name(tn)
        if weekly_norm in tn_norm or tn_norm in weekly_norm:
            return tn
    for tn in template_names:
        if set(name_tokens(tn)) == weekly_tokens:
            return tn
    for tn in template_names:
        tn_tokens = set(name_tokens(tn))
        common = tn_tokens & weekly_tokens
        if len(common) >= 2 and (len(common) == len(weekly_tokens) or len(common) == len(tn_tokens)):
            return tn
    return None


# ============================================================
# 填写 import 模板
# ============================================================

LOC_KEYS = {'Gonesse': 'GONESSE', 'Nanteuil': 'NANTEUIL', 'SM': 'SAINT-MARD'}

def fill_template(template_path, output_path, employees, location_key, holidays, n_weeks):
    wb = openpyxl.load_workbook(template_path)
    ws = wb['Page 1']
    cols = detect_columns(ws)
    print(f"  检测列: HS25%={cols.get('hs_25')}, HS50%={cols.get('hs_50')}, "
          f"Fériés={cols.get('feries')}, Absence={cols.get('heures_absence')}, "
          f"CSS injustifiée={cols.get('css_injustifiee')}")

    template_employees = {}
    for row in range(3, ws.max_row + 1):
        name = ws.cell(row=row, column=4).value
        if not name or not str(name).strip():
            continue
        name = str(name).strip()
        template_employees.setdefault(name, []).append(row)

    # 清空可填写列
    clearable = set()
    for key in ['cp_start', 'cp_choix', 'cp_end', 'css_start', 'css_choix', 'css_end',
                'css_injustifiee', 'repos_start', 'repos_choix', 'repos_end',
                'repos_solde', 'repos_heures', 'hs_25', 'hs_50',
                'dim_hab', 'dim_exc', 'dim_nb', 'feries', 'heures_absence']:
        if cols.get(key) is not None:
            clearable.add(cols[key])
    if cols.get('rtt_start') is not None:
        for c in range(cols['rtt_start'], (cols.get('rtt_end') or cols['rtt_start']) + 1):
            clearable.add(c)
    for col in range(1, ws.max_column + 1):
        v = ws.cell(row=2, column=col).value
        if v and ('titre' in str(v).lower() or 'restaurant' in str(v).lower()):
            clearable.add(col)
    for row in range(3, ws.max_row + 1):
        for col in clearable:
            ws.cell(row=row, column=col).value = None

    filled = 0
    unmatched = []
    cap = 5 * n_weeks
    for weekly_name, emp in employees.items():
        # 地点过滤 (地点已知时按地点; 地点未知但能匹配模板也填)
        if emp.location is not None and emp.location != LOC_KEYS[location_key]:
            continue
        matched = match_employee(weekly_name, list(template_employees.keys()))
        if not matched:
            if emp.location is None:
                unmatched.append(weekly_name)
            continue

        rows = template_employees[matched]
        first_row = rows[0]

        segments = []
        for lt in ['cp', 'css', 'repos', 'rtt']:
            if emp.leave_segments.get(lt):
                for seg in merge_consecutive_dates(emp.leave_segments[lt], holidays):
                    segments.append((lt, seg[0], seg[1]))
        segments.sort(key=lambda x: (x[0], x[1]))

        for i, (lt, sd, ed) in enumerate(segments):
            if i < len(rows):
                r = rows[i]
            else:
                r = ws.max_row + 1
                for cc in (1, 2, 3, 4):
                    ws.cell(row=r, column=cc).value = ws.cell(row=first_row, column=cc).value
            if lt == 'cp':
                if cols.get('cp_start'): ws.cell(row=r, column=cols['cp_start']).value = sd
                if cols.get('cp_choix'): ws.cell(row=r, column=cols['cp_choix']).value = 'Journée entière'
                if cols.get('cp_end'): ws.cell(row=r, column=cols['cp_end']).value = ed
            elif lt == 'css':
                if cols.get('css_start'): ws.cell(row=r, column=cols['css_start']).value = sd
                if cols.get('css_choix'): ws.cell(row=r, column=cols['css_choix']).value = 'Journée entière'
                if cols.get('css_end'): ws.cell(row=r, column=cols['css_end']).value = ed
                if cols.get('css_injustifiee'): ws.cell(row=r, column=cols['css_injustifiee']).value = 'Non'
            elif lt == 'repos':
                if cols.get('repos_start'): ws.cell(row=r, column=cols['repos_start']).value = sd
                if cols.get('repos_choix'): ws.cell(row=r, column=cols['repos_choix']).value = 'Journée entière'
                if cols.get('repos_end'): ws.cell(row=r, column=cols['repos_end']).value = ed
                if cols.get('repos_solde'): ws.cell(row=r, column=cols['repos_solde']).value = 'Contrepartie des heures supplémentaires'
                if cols.get('repos_heures'):
                    wd = 0
                    d = sd
                    while d <= ed:
                        if d.weekday() < 5:
                            wd += 1
                        d += timedelta(days=1)
                    ws.cell(row=r, column=cols['repos_heures']).value = wd * 7
            elif lt == 'rtt' and cols.get('rtt_start') is not None:
                ws.cell(row=r, column=cols['rtt_start']).value = sd
                if cols.get('rtt_end'): ws.cell(row=r, column=cols['rtt_end']).value = ed

        # 非请假字段只填第一行
        if emp.hs_125_total > 0 and cols.get('hs_25'):
            ws.cell(row=first_row, column=cols['hs_25']).value = round(emp.hs_125_total, 2)
        if emp.hs_150_total > 0 and cols.get('hs_50'):
            val = min(emp.hs_150_total, cap)
            ws.cell(row=first_row, column=cols['hs_50']).value = round(val, 2)
            if val < emp.hs_150_total:
                print(f"    [封顶] {weekly_name}: HS50% 原始 {emp.hs_150_total:.2f} -> 封顶 {val:.2f} (周数×5={cap})")
        if emp.holiday_hours and cols.get('feries'):
            total = sum(v for v in emp.holiday_hours.values() if isinstance(v, (int, float)))
            if total > 0:
                ws.cell(row=first_row, column=cols['feries']).value = round(total, 2)
        if emp.monthly_absence > 0 and cols.get('heures_absence'):
            ws.cell(row=first_row, column=cols['heures_absence']).value = round(emp.monthly_absence, 2)

        filled += 1

    wb.save(output_path)
    return filled, unmatched


def _auto_gen_name(tpl_path):
    """把上传的空白模板文件名改为 (自动生成) 版"""
    base = os.path.basename(tpl_path)
    if base.lower().endswith(".xlsx"):
        return base[:-5] + " (自动生成).xlsx"
    return base + " (自动生成)"


def fill_template_by_template(weekly_employees, template_path, output_path, holidays, n_weeks):
    """以 import 模板人员为基准填充 (Web 多文件模式专用)。

    weekly_employees: parse_weekly_file 返回的 dict (weekly_name -> EmployeeWeeklyData)
    返回 (filled, template_missing, source_extra):
      filled          模板中匹配到源表并填写的人数
      template_missing 模板中有姓名但源表无匹配的人 (保持空白, 不报错)
      source_extra    源表中所有姓名里, 不匹配任何模板的人 (供前端提示)
    """
    wb = openpyxl.load_workbook(template_path)
    ws = wb['Page 1']
    cols = detect_columns(ws)
    print(f"  检测列: HS25%={cols.get('hs_25')}, HS50%={cols.get('hs_50')}, "
          f"Fériés={cols.get('feries')}, Absence={cols.get('heures_absence')}, "
          f"CSS injustifiée={cols.get('css_injustifiee')}")

    template_employees = {}
    for row in range(3, ws.max_row + 1):
        name = ws.cell(row=row, column=4).value
        if not name or not str(name).strip():
            continue
        name = str(name).strip()
        template_employees.setdefault(name, []).append(row)

    # 清空可填写列
    clearable = set()
    for key in ['cp_start', 'cp_choix', 'cp_end', 'css_start', 'css_choix', 'css_end',
                'css_injustifiee', 'repos_start', 'repos_choix', 'repos_end',
                'repos_solde', 'repos_heures', 'hs_25', 'hs_50',
                'dim_hab', 'dim_exc', 'dim_nb', 'feries', 'heures_absence']:
        if cols.get(key) is not None:
            clearable.add(cols[key])
    if cols.get('rtt_start') is not None:
        for c in range(cols['rtt_start'], (cols.get('rtt_end') or cols['rtt_start']) + 1):
            clearable.add(c)
    for col in range(1, ws.max_column + 1):
        v = ws.cell(row=2, column=col).value
        if v and ('titre' in str(v).lower() or 'restaurant' in str(v).lower()):
            clearable.add(col)
    for row in range(3, ws.max_row + 1):
        for col in clearable:
            ws.cell(row=row, column=col).value = None

    filled = 0
    template_missing = []
    matched_source_names = set()
    cap = 5 * n_weeks
    weekly_names = list(weekly_employees.keys())

    for tpl_name, rows in template_employees.items():
        matched = match_employee(tpl_name, weekly_names)
        if not matched:
            # 模板里有这人, 但源表找不到 -> 保持空白, 记录
            template_missing.append(tpl_name)
            continue
        matched_source_names.add(matched)
        emp = weekly_employees[matched]
        first_row = rows[0]

        segments = []
        for lt in ['cp', 'css', 'repos', 'rtt']:
            if emp.leave_segments.get(lt):
                for seg in merge_consecutive_dates(emp.leave_segments[lt], holidays):
                    segments.append((lt, seg[0], seg[1]))
        segments.sort(key=lambda x: (x[0], x[1]))

        for i, (lt, sd, ed) in enumerate(segments):
            if i < len(rows):
                r = rows[i]
            else:
                r = ws.max_row + 1
                for cc in (1, 2, 3, 4):
                    ws.cell(row=r, column=cc).value = ws.cell(row=first_row, column=cc).value
            if lt == 'cp':
                if cols.get('cp_start'): ws.cell(row=r, column=cols['cp_start']).value = sd
                if cols.get('cp_choix'): ws.cell(row=r, column=cols['cp_choix']).value = 'Journée entière'
                if cols.get('cp_end'): ws.cell(row=r, column=cols['cp_end']).value = ed
            elif lt == 'css':
                if cols.get('css_start'): ws.cell(row=r, column=cols['css_start']).value = sd
                if cols.get('css_choix'): ws.cell(row=r, column=cols['css_choix']).value = 'Journée entière'
                if cols.get('css_end'): ws.cell(row=r, column=cols['css_end']).value = ed
                if cols.get('css_injustifiee'): ws.cell(row=r, column=cols['css_injustifiee']).value = 'Non'
            elif lt == 'repos':
                if cols.get('repos_start'): ws.cell(row=r, column=cols['repos_start']).value = sd
                if cols.get('repos_choix'): ws.cell(row=r, column=cols['repos_choix']).value = 'Journée entière'
                if cols.get('repos_end'): ws.cell(row=r, column=cols['repos_end']).value = ed
                if cols.get('repos_solde'): ws.cell(row=r, column=cols['repos_solde']).value = 'Contrepartie des heures supplémentaires'
                if cols.get('repos_heures'):
                    wd = 0
                    d = sd
                    while d <= ed:
                        if d.weekday() < 5:
                            wd += 1
                        d += timedelta(days=1)
                    ws.cell(row=r, column=cols['repos_heures']).value = wd * 7
            elif lt == 'rtt' and cols.get('rtt_start') is not None:
                ws.cell(row=r, column=cols['rtt_start']).value = sd
                if cols.get('rtt_end'): ws.cell(row=r, column=cols['rtt_end']).value = ed

        if emp.hs_125_total > 0 and cols.get('hs_25'):
            ws.cell(row=first_row, column=cols['hs_25']).value = round(emp.hs_125_total, 2)
        if emp.hs_150_total > 0 and cols.get('hs_50'):
            val = min(emp.hs_150_total, cap)
            ws.cell(row=first_row, column=cols['hs_50']).value = round(val, 2)
            if val < emp.hs_150_total:
                print(f"    [封顶] {tpl_name}: HS50% 原始 {emp.hs_150_total:.2f} -> 封顶 {val:.2f} (周数×5={cap})")
        if emp.holiday_hours and cols.get('feries'):
            total = sum(v for v in emp.holiday_hours.values() if isinstance(v, (int, float)))
            if total > 0:
                ws.cell(row=first_row, column=cols['feries']).value = round(total, 2)
        if emp.monthly_absence > 0 and cols.get('heures_absence'):
            ws.cell(row=first_row, column=cols['heures_absence']).value = round(emp.monthly_absence, 2)

        filled += 1

    wb.save(output_path)

    # 本模板匹配到的源表姓名 (供 run_fill_v2 跨模板汇总, 判定"源表有但任何模板都无")
    return filled, template_missing, sorted(matched_source_names)


def run_fill_v2(weekly_path, template_paths, output_dir=None):
    """Web 多文件模式: 模板由用户上传的空白 import 文件列表。
    以模板人员为基准填充; 源表有但模板无的人不填写, 仅记录提示。

    返回 (outputs:list, report:dict):
      report = {
        'filled':          {模板文件名: 已填人数},
        'template_missing': {模板文件名: [模板有但源表无]},
        'source_extra':    [源表有但任何模板都没有],
      }
    """
    if not os.path.exists(weekly_path):
        raise FileNotFoundError("每月工资计算表不存在: " + weekly_path)
    for p in template_paths:
        if not os.path.exists(p):
            raise FileNotFoundError("模板不存在: " + p)

    employees, n_weeks = parse_weekly_file(weekly_path)
    print(f"解析员工数: {len(employees)}  (周出勤Sheet数={n_weeks}, HS50%封顶={5*n_weeks}h)")

    holidays = FRENCH_HOLIDAYS_2026
    if output_dir is None:
        output_dir = os.path.dirname(os.path.abspath(template_paths[0]))

    outputs = []
    report = {'filled': {}, 'template_missing': {}, 'source_extra': []}
    global_matched = set()
    for tpl in template_paths:
        out_name = _auto_gen_name(tpl)
        out_path = os.path.join(output_dir, out_name)
        print(f"填写 {os.path.basename(tpl)} ...")
        cnt, t_missing, matched_list = fill_template_by_template(employees, tpl, out_path, holidays, n_weeks)
        print(f"  已填写 {cnt} 人 -> {out_path}")
        outputs.append(out_path)
        report['filled'][os.path.basename(tpl)] = cnt
        if t_missing:
            report['template_missing'][os.path.basename(tpl)] = t_missing
        global_matched.update(matched_list)
        print()

    weekly_names = list(employees.keys())
    report['source_extra'] = sorted(w for w in weekly_names if w not in global_matched)
    return outputs, report


# ============================================================
# 主函数
# ============================================================

def derive_ym(weekly_path, template_dir):
    """推导年月。优先取源表文件名中的年份/月份(最可靠)，模板目录提示仅作兜底。
    避免当 import_templates 下存在多月目录时，模板路径先命中而把源表月份覆盖。
    """
    # 1) 源表文件名优先
    fname = os.path.basename(weekly_path)
    m = re.search(r'(20\d{2}[0-1]\d)', fname)
    if m:
        return m.group(1)
    m = re.search(r'(\d{4})年(\d{1,2})月', fname)
    if m:
        return m.group(1) + m.group(2).zfill(2)
    m = re.search(r'(\d{1,2})月.*?(\d{4})年', fname)
    if m:
        return m.group(2) + m.group(1).zfill(2)
    # 2) 模板目录提示兜底(多月份目录时取最后一个，通常更接近当月)
    m = re.search(r'(20\d{2}[0-1]\d)', template_dir)
    if m:
        return m.group(1)
    return "UNKNOWN"


def run_fill(weekly_path, template_dir, output_dir=None):
    """供 web 平台复用：解析+填写, 返回 (output_paths:list, unmatched:dict)。

    output_dir: 生成文件输出目录, 默认与模板同目录。
    """
    if not os.path.exists(weekly_path):
        raise FileNotFoundError("每周工资计算表不存在: " + weekly_path)

    ym = derive_ym(weekly_path, template_dir)
    print(f"每周工资计算表: {weekly_path}")
    print(f"模板目录: {template_dir}")
    print(f"年月标识: {ym}\n")

    templates = {
        'Gonesse': os.path.join(template_dir, f'import_variables_paie-{ym} Gonesse.xlsx'),
        'Nanteuil': os.path.join(template_dir, f'import_variables_paie-{ym} Nanteuil.xlsx'),
        'SM': os.path.join(template_dir, f'import_variables_paie-{ym} SM.xlsx'),
    }
    for k, p in templates.items():
        if not os.path.exists(p):
            raise FileNotFoundError(f"模板不存在: {p}")

    print("解析每周工资计算表 + 月工资合计...")
    employees, n_weeks = parse_weekly_file(weekly_path)
    print(f"  解析员工数: {len(employees)}  (周出勤Sheet数={n_weeks}, HS50%封顶={5*n_weeks}h)\n")

    holidays = FRENCH_HOLIDAYS_2026
    if output_dir is None:
        output_dir = template_dir

    all_unmatched = {}
    outputs = []
    for key, tpl in templates.items():
        out_name = f"import_variables_paie-{ym} {key} (自动生成).xlsx"
        out_path = os.path.join(output_dir, out_name)
        print(f"填写 {key} ...")
        cnt, unmatched = fill_template(tpl, out_path, employees, key, holidays, n_weeks)
        print(f"  已填写 {cnt} 人 -> {out_path}")
        outputs.append(out_path)
        if unmatched:
            all_unmatched[key] = unmatched
        print()

    return outputs, all_unmatched


def main():
    if len(sys.argv) < 3:
        print("用法: python auto_fill_import.py <每周工资计算表路径> <模板目录>")
        sys.exit(1)

    weekly_path = sys.argv[1]
    template_dir = sys.argv[2]

    outputs, all_unmatched = run_fill(weekly_path, template_dir)

    if all_unmatched:
        print("=" * 64)
        print("⚠️ 以下员工在源数据中存在, 但未在对应模板找到匹配 (未手动添加):")
        for loc, names in all_unmatched.items():
            print(f"  - {loc}: {', '.join(names)}")
        print("请确认是否需要手动添加到模板。")
        print("=" * 64)
    else:
        print("所有员工均匹配, 无遗漏。")
    print("全部完成！生成文件:")
    for p in outputs:
        print("  " + p)


if __name__ == '__main__':
    main()

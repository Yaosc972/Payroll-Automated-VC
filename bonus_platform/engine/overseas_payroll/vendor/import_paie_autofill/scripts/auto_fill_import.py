#!/usr/bin/env python3
"""
import_variables_paie 自动填写脚本 (v3)

基于「每周工资计算表(出勤情况) + 月工资合计」自动填写 Gonesse/Nanteuil/SM 三个 import 模板,
生成与人工版(Payfit 导出)一致的报盘文件。

v3 相对 v2 的修改 (依据 2026-08 人工版逐列核对结论):
  1. 补齐「Fin CP/CSS/Repos (choix)」列: v2 只写了 Début 的 choix, Fin 留空, 与人工版不一致。
  2. 修正「Solde à débiter」检测: 表头为 "Solde à débiter"(不含 'repos'), v2 检测不到,
     导致 Repos 行的 "Contrepartie des heures supplémentaires" 从未写入。
  3. 新增「Type de rémunération」= 'Paiement des heures supplémentaires' (HS>0 时)。
     例外: 月工资合计「人员类型」= 实习生 的人, 人工版既不填 HS 也不填 Type de rémunération。
  4. 新增周日奖金行: Type de prime / nom = 'Prime de dimanche',
     Montant = 月工资合计 K列(周日奖金), Date de début de versement = 当月1日, Fréquence = 'une seule fois'。
     该行写在「第一行未被他人 prime 占用」的行; 已存在 'Prime sur objectif'(绩效, 来自考勤之外)的行不覆盖。
  5. 不再清空/填写「Titres restaurant」区块: 该区块由模板预置(少量人员 "Non" + 8€/4.32€/Automatique),
     v2 会先清空再不管, 直接把模板预置信息清没了。
  6. 不再填写「Heures à décompter」: 人工版三个主体该列全空。
  7. 员工区改为「第3行起连续 ObjectId 段」: v2 用 range(3, ws.max_row+1) 扫描,
     而 ws.max_row 被样式撑到 5000+, 会把历史工具残留行(及下拉列表区)当成员工;
     追加行也不再从 ws.max_row+1 开始(那会落到 5095 行), 改为员工区末尾游标。
     同时清理残留行(ObjectId 已在员工区出现的孤儿行)中的工具字段。
  8. 填写前清空所有「本工具负责」的列(含新补的 Fin choix / Type de rémunération),
     使 202607 这类带旧数据的模板不会把上月数据漏进本月; 他人 prime 行与费率/配置列一律保留。
  9. 周表无出勤记录、仅月表有的人: 加班工时回退取月工资合计 D/E 列(v2 会漏填)。
 10. 月工资合计新增读取: D(HS1.25) E(HS1.5) J(周日天数) K(周日奖金) L(补餐票) Q(人员类型) P(全名)。

v3.1 (2026-09 修正, 依据 202608 人工版逐行核对):
 11. 请假段行分配改为「槽位」模型。v3 把所有类型的段混在一起按 (类型, 开始日) 排序后
     每段占一行, 导致同一员工的 CP/CSS/Repos 被排到不同行, 且段数一多就额外追加行。
     人工版实际是: 第 i 行同时承载 CP 的第 i 段、CSS 的第 i 段、Repos 的第 i 段
     (各类型占用不同列, 互不冲突, 一行可以放多种假)。
     证据: Yu-Tzu Liao(源表 CP 08-03 / CSS 08-14) -> 人工版两段同在第20行;
           Sabil BARKATI(CP#0=07-30~08-04, CSS#0=08-05~08-07, CSS#1=08-14)
           -> 人工版第3行=CP#0+CSS#0, 第4行=CSS#1;
           Qiyu WANG(Repos 08-11) -> 人工版 Repos 与 CP#0 同在第25行。
     即: 槽位数 = max(各类型段数); 仅当某类型的段数超过该员工已有行数时才追加新行。
 12. run_fill / run_fill_v2 输出目录改为自动创建 (os.makedirs exist_ok)。
     旧版 output_dir 不存在时会在 wb.save 抛 FileNotFoundError, 报错位置离真正原因很远。

保持不变(经核对为正确设计):
  - HS 来源 = 周表 P(1.25)/Q(1.5) 累计; HS50% 封顶 = 周数 × 5; HS25% 不封顶。
  - 请假段由周表每日标记 'CP'/'CSS'/'Repos'/'RTT' 归并而成 (同类且中间只隔周末/节假日的
    连续日合并为一段), 一段写成一条 (Début, Fin) 区间。
  - 公休(Fériés): 仅当节假日当日有数字工时才填, 值为工时; 'JF' 字符串不填。
  - Heures d'absence = 月工资合计 H(RD/ABS总计) 的负值绝对值。
  - 费率类列(Taux de majoration 等)、交通列一律不动。

用法:
    python auto_fill_import.py <每周工资计算表路径> <模板目录>

输出:
    在模板目录(或指定输出目录)下生成三份 "(自动生成).xlsx"。
"""

import os
import re
import sys
from copy import copy
from datetime import datetime, date, timedelta
from collections import defaultdict, OrderedDict

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

# 月工资合计 (1-based)
MONTHLY_COLS = {
    'location': 1,        # A: 地点
    'name': 2,            # B: 员工姓名
    'full_name': 16,      # P: 全名 (匹配辅助)
    'person_type': 17,    # Q: 人员类型 (实习生 判定)
    'hs_125': 4,          # D: 加班工时 1.25
    'hs_150': 5,          # E: 加班工时 1.5 Payfit输入
    'rd_abs': 8,          # H: RD/ABS总计 (负值为缺勤)
    'sunday_days': 10,    # J: 周日天数
    'sunday_prime': 11,   # K: 周日奖金
    'meal_ticket': 12,    # L: 补餐票
}

# 2026 法国法定节假日 (用于 Fériés 通用识别)
FRENCH_HOLIDAYS_2026 = {
    date(2026, 1, 1), date(2026, 4, 6), date(2026, 5, 1), date(2026, 5, 8),
    date(2026, 5, 14), date(2026, 5, 25), date(2026, 7, 14), date(2026, 8, 15),
    date(2026, 11, 1), date(2026, 11, 11), date(2026, 12, 25),
}

OBJECTID_RE = re.compile(r'^[0-9a-f]{24}$')

# 固定文本 (与人工版/Payfit 下拉值逐字一致)
VAL_JOURNEE = 'Journée entière'
VAL_CONTREPARTIE = 'Contrepartie des heures supplémentaires'
VAL_TYPE_REMU_HS = 'Paiement des heures supplémentaires'
VAL_PRIME_DIMANCHE = 'Prime de dimanche'
VAL_FREQ_UNE_FOIS = 'une seule fois'
PERSON_TYPE_INTERN = '实习生'

# 本工具负责(可清空/可写入)的列
OWNED_COL_KEYS = [
    'cp_start', 'cp_start_choix', 'cp_end', 'cp_end_choix',
    'css_start', 'css_start_choix', 'css_end', 'css_end_choix', 'css_injustifiee',
    'repos_start', 'repos_start_choix', 'repos_end', 'repos_end_choix', 'repos_solde',
    'rtt_start', 'rtt_start_choix', 'rtt_end', 'rtt_end_choix',
    'hs_25', 'hs_50', 'type_remu', 'dim_hab', 'dim_exc', 'dim_nb',
    'feries', 'heures_absence',
]

# prime 区块 (只在本工具拥有的行上清空/写入; 他人 prime 行保留)
PRIME_COL_KEYS = ('prime_type', 'prime_name', 'prime_amount',
                  'prime_date', 'prime_freq', 'prime_end')

# 餐票/交通等由人工维护的列 (只统计保留数量, 不改动)
PRESERVE_COL_KEYS = ('titre_gerer', 'titre_valeur', 'titre_gestion',
                     'titre_nombre', 'titre_part')


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


def _to_number(val):
    """宽容地把单元格值转成 float; 转不了返回 0.0 ('不超时' 之类文本 -> 0)。"""
    if isinstance(val, bool) or val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        s = val.strip().replace(',', '.').replace(' ', '')
        if not s:
            return 0.0
        try:
            return float(s)
        except ValueError:
            return 0.0
    return 0.0


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


def month_start_from_ym(ym):
    """'202608' -> date(2026, 8, 1); 推导不出返回 None"""
    if not ym or not re.fullmatch(r'20\d{4}', str(ym)):
        return None
    y, m = int(str(ym)[:4]), int(str(ym)[4:6])
    if not 1 <= m <= 12:
        return None
    return date(y, m, 1)


# ============================================================
# 动态检测 import 模板列位置
# ============================================================

def detect_columns(ws):
    """模板第2行为字段名表头(第1行是分组带), 用表头文本检测列位置。

    绝不硬编码列号: 不同月份/主体的模板列数并不一致
    (例: 202605 空白 gonesse 比 202608 人工版多 2 列 "Heures complémentaires à 10%/25%")。
    """
    cols = {}
    headers = {}
    for col in range(1, ws.max_column + 1):
        v = ws.cell(row=2, column=col).value
        if v is not None:
            headers[col] = str(v).strip().lower()

    def find_col(*keywords, exclude=None):
        """返回同时包含全部关键词的最靠左列 (表头已按列号升序)"""
        for col, text in headers.items():
            if all(kw.lower() in text for kw in keywords):
                if exclude and exclude.lower() in text:
                    continue
                return col
        return None

    def find_col_startswith(prefix):
        for col, text in headers.items():
            if text.startswith(prefix):
                return col
        return None

    # ---- CP ----
    cols['cp_start'] = find_col('cp', 'début') or find_col('cp', 'debut')
    cols['cp_start_choix'] = find_col('cp', 'début', 'choix') or find_col('cp', 'debut', 'choix')
    cols['cp_end'] = find_col('cp', 'fin')
    cols['cp_end_choix'] = find_col('cp', 'fin', 'choix')

    # ---- CSS ----
    cols['css_start'] = find_col('css', 'début') or find_col('css', 'debut')
    cols['css_start_choix'] = find_col('css', 'début', 'choix') or find_col('css', 'debut', 'choix')
    cols['css_end'] = find_col('css', 'fin')
    cols['css_end_choix'] = find_col('css', 'fin', 'choix')
    # 注意: 「Absence injustifiée」列头不含 'css', 单独用 'absence'+'injustifiée' 检测
    cols['css_injustifiee'] = find_col('absence', 'injustifiée') or find_col('absence', 'injustifiee')

    # ---- Repos ----
    cols['repos_start'] = find_col('repos', 'début') or find_col('repos', 'debut')
    cols['repos_start_choix'] = find_col('repos', 'début', 'choix') or find_col('repos', 'debut', 'choix')
    cols['repos_end'] = find_col('repos', 'fin')
    cols['repos_end_choix'] = find_col('repos', 'fin', 'choix')
    # 「Solde à débiter」表头不含 'repos' 关键词
    cols['repos_solde'] = find_col('solde à débiter') or find_col('solde a debiter') or find_col('solde')

    # ---- RTT (仅部分主体有, 人工版留空, 保持通用处理) ----
    cols['rtt_start'] = find_col('rtt', 'début') or find_col('rtt', 'debut')
    cols['rtt_start_choix'] = find_col('rtt', 'début', 'choix') or find_col('rtt', 'debut', 'choix')
    cols['rtt_end'] = find_col('rtt', 'fin')
    cols['rtt_end_choix'] = find_col('rtt', 'fin', 'choix')

    # ---- 加班 ----
    cols['hs_25'] = find_col('25%', exclude='50%') or find_col('supplémentaires', '25%')
    cols['hs_50'] = find_col('50%')
    cols['type_remu'] = find_col('type de rémunération') or find_col('type de remuneration')

    # ---- 周日 / 公休 ----
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

    # ---- Prime 区块: 锚定 "Type de prime (conventionnelle ou non)" 后向其右侧找同组列 ----
    for k in PRIME_COL_KEYS:
        cols[k] = None
    anchor = find_col('type de prime')
    if anchor:
        cols['prime_type'] = anchor
        for col in range(anchor + 1, ws.max_column + 1):
            t = headers.get(col)
            if not t:
                continue
            if cols['prime_name'] is None and 'nom de la prime' in t:
                cols['prime_name'] = col
            elif cols['prime_amount'] is None and t.startswith('montant'):
                cols['prime_amount'] = col
            elif cols['prime_date'] is None and 'date de début de versement' in t:
                cols['prime_date'] = col
            elif cols['prime_freq'] is None and t.startswith('fréquence'):
                cols['prime_freq'] = col
            elif cols['prime_end'] is None and t.startswith('date de fin'):
                cols['prime_end'] = col

    # ---- 餐票 (仅统计保留, 不填写) ----
    cols['titre_gerer'] = find_col('gérer les titres') or find_col('gerer les titres')
    cols['titre_valeur'] = find_col('valeur du titre')
    cols['titre_gestion'] = find_col('gestion du nombre')
    cols['titre_nombre'] = find_col('nombre de titres')
    cols['titre_part'] = find_col('part payée par l') or find_col('part payee par l')

    required = ['cp_start', 'cp_end', 'css_start', 'css_end',
                'repos_start', 'repos_end', 'hs_25', 'hs_50',
                'feries', 'heures_absence', 'type_remu', 'repos_solde']
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
        # --- v3 新增 ---
        self.has_weekly_rows = False   # 周出勤表中是否出现
        self.monthly_hs_125 = 0        # 月表 D
        self.monthly_hs_150 = 0        # 月表 E
        self.sunday_days = 0           # 月表 J
        self.sunday_prime = 0          # 月表 K
        self.meal_ticket = 0           # 月表 L
        self.person_type = ''          # 月表 Q (实习生 判定)
        self.full_name = ''            # 月表 P


# ============================================================
# 姓名工具
# ============================================================

def normalize_name(name):
    return str(name).strip().lower().replace('  ', ' ')


def _find_key_by_norm(d, norm):
    for k in d:
        if normalize_name(k) == norm:
            return k
    return None


def _is_junk_name(name):
    """月工资合计中的垃圾备注行过滤"""
    if not name:
        return True
    if '/' in name:
        return True
    if not re.search(r'[A-Za-z]', name):   # 纯中文/无拉丁字母的备注
        return True
    return False


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
# 解析每周工资计算表 + 月工资合计
# ============================================================

def _monthly_row(ms, row):
    """读取月工资合计一行的关键字段"""
    name = ms.cell(row=row, column=MONTHLY_COLS['name']).value
    if not name:
        return None
    name = str(name).strip()
    if _is_junk_name(name):
        return None
    loc = ms.cell(row=row, column=MONTHLY_COLS['location']).value
    if not loc:
        return None

    def _v(key):
        return ms.cell(row=row, column=MONTHLY_COLS[key]).value

    h_val = _v('rd_abs')
    absence = abs(h_val) if (isinstance(h_val, (int, float)) and h_val < 0) else 0
    return {
        'name': name,
        'norm': normalize_name(name),
        'location': str(loc).strip().upper(),
        'absence': absence,
        'hs_125': _to_number(_v('hs_125')),
        'hs_150': _to_number(_v('hs_150')),
        'sunday_days': _to_number(_v('sunday_days')),
        'sunday_prime': _to_number(_v('sunday_prime')),
        'meal_ticket': _to_number(_v('meal_ticket')),
        'person_type': str(_v('person_type') or '').strip(),
        'full_name': str(_v('full_name') or '').strip(),
    }


def parse_weekly_file(filepath):
    wb = openpyxl.load_workbook(filepath, data_only=True)

    weekly_sheets = [s for s in wb.sheetnames if '出勤情况' in s]
    monthly_sheets = [s for s in wb.sheetnames if '工资合计' in s]

    if not weekly_sheets:
        raise ValueError("未找到包含'出勤情况'的Sheet")
    if not monthly_sheets:
        raise ValueError("未找到包含'工资合计'的Sheet")

    employees = defaultdict(EmployeeWeeklyData)

    # ---- 月工资合计: 地点 + 缺勤 + 加班 + 周日奖金 + 人员类型 ----
    monthly_map = {}   # norm_name -> dict
    ms = wb[monthly_sheets[0]]
    for row in range(2, ms.max_row + 1):
        m = _monthly_row(ms, row)
        if m is None:
            continue
        if m['norm'] not in monthly_map:
            monthly_map[m['norm']] = m

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
            emp.has_weekly_rows = True

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

    # ---- 用月工资合计补全 (含仅出现在月表、未出现在周表的员工) ----
    for mname_norm, m in monthly_map.items():
        wk_name = _find_key_by_norm(employees, mname_norm)
        if wk_name is None and m['full_name'] and not _is_junk_name(m['full_name']):
            wk_name = _find_key_by_norm(employees, normalize_name(m['full_name']))
        if wk_name is None:
            # 该员工只在月表出现 (如纯缺勤/纯加班), 新建一条
            emp = EmployeeWeeklyData()
            emp.location = m['location']
            emp.monthly_absence = m['absence']
            emp.has_weekly_rows = False
            employees[m['norm']] = emp   # 以 norm 名作 key, 后续匹配仍能命中
        else:
            emp = employees[wk_name]
            if not emp.location:
                emp.location = m['location']
            if m['absence'] and not emp.monthly_absence:
                emp.monthly_absence = m['absence']

        # 月表独有信息一律带上 (周表无这些字段)
        emp.monthly_hs_125 = m['hs_125']
        emp.monthly_hs_150 = m['hs_150']
        emp.sunday_days = m['sunday_days']
        emp.sunday_prime = m['sunday_prime']
        emp.meal_ticket = m['meal_ticket']
        emp.person_type = emp.person_type or m['person_type']
        emp.full_name = emp.full_name or m['full_name']
        if not emp.has_weekly_rows:
            # 周表没有此人 -> 加班取月表 D/E (两者经核对数值一致, 仅作回退)
            emp.hs_125_total = m['hs_125']
            emp.hs_150_total = m['hs_150']

    return employees, len(weekly_sheets)


# ============================================================
# 模板员工区
# ============================================================

def collect_template_employees(ws, gap_tolerance=3):
    """读取模板员工区: 第3行起连续的 ObjectId 段 (允许少量空行)。

    返回 (roster, last_row, stray_rows)
      roster     : OrderedDict  key=ObjectId(无则用姓名) -> {'name': str, 'rows': [行号...]}
      last_row   : 员工区最后一行 (追加行游标从这里开始)
      stray_rows : 员工区之外仍带 ObjectId 的残留行 (历史版本用 ws.max_row+1 追加造成)
    """
    roster = OrderedDict()
    last_row = 2
    gap = 0
    for row in range(3, ws.max_row + 1):
        idv = ws.cell(row=row, column=1).value
        nm = ws.cell(row=row, column=4).value
        key = str(idv).strip() if idv is not None else ''
        name = str(nm).strip() if nm is not None else ''

        if OBJECTID_RE.match(key):
            ent = roster.get(key)
            if ent is None:
                roster[key] = {'name': name, 'rows': [row], 'id': key}
            else:
                ent['rows'].append(row)
                if not ent['name'] and name:
                    ent['name'] = name
            last_row = row
            gap = 0
        elif name and last_row >= 2:
            # 有姓名无 ObjectId 的容错行
            k2 = 'name:' + name
            ent = roster.get(k2)
            if ent is None:
                roster[k2] = {'name': name, 'rows': [row], 'id': ''}
            else:
                ent['rows'].append(row)
            last_row = row
            gap = 0
        else:
            gap += 1
            if gap > gap_tolerance:
                break

    stray_rows = []
    for row in range(last_row + 1, ws.max_row + 1):
        v = ws.cell(row=row, column=1).value
        if v is not None and OBJECTID_RE.match(str(v).strip()):
            stray_rows.append(row)
    return roster, last_row, stray_rows


def _clear_owned_cells(ws, cols, roster_rows, stray_rows):
    """清空本工具负责的列 (roster 行)。

    prime 区块只在「本工具拥有的行」清空: 行上已有他人 prime(如 Prime sur objectif)则整块保留。
    费率/配置列、餐票/交通列一律不动。
    """
    owned = [cols[k] for k in OWNED_COL_KEYS if cols.get(k)]
    if cols.get('rtt_start') and cols.get('rtt_end'):
        owned.extend(range(cols['rtt_start'], cols['rtt_end'] + 1))
    owned = sorted(set(owned))

    prime_cols = [cols[k] for k in PRIME_COL_KEYS if cols.get(k)]
    ptype = cols.get('prime_type')

    def _clear_prime(r):
        if ptype:
            v = ws.cell(row=r, column=ptype).value
            t = str(v).strip() if v is not None else ''
            if t and t != VAL_PRIME_DIMANCHE:
                return          # 他人 prime 行, 保留
        for c in prime_cols:
            ws.cell(row=r, column=c).value = None

    for r in roster_rows:
        for c in owned:
            ws.cell(row=r, column=c).value = None
        _clear_prime(r)
    # 残留孤儿行: 只有其 ObjectId 已在员工区出现才清理 (避免误删真实数据)
    for r in stray_rows:
        for c in owned:
            ws.cell(row=r, column=c).value = None
        _clear_prime(r)


def _kept_prime_rows(ws, cols, rows):
    """该员工行中已被他人 prime 占用的行 (本工具不覆盖)"""
    ptype = cols.get('prime_type')
    if not ptype:
        return []
    out = []
    for r in rows:
        v = ws.cell(row=r, column=ptype).value
        t = str(v).strip() if v is not None else ''
        if t and t != VAL_PRIME_DIMANCHE:
            out.append(r)
    return out


def _append_row(ws, src_row, cursor):
    """在员工区末尾追加一行 (复制源行 A-D 与整行样式), 返回新行号。"""
    r = cursor[0]
    cursor[0] += 1
    maxc = min(ws.max_column, 120)
    for cc in range(1, maxc + 1):
        s = ws.cell(row=src_row, column=cc)
        d = ws.cell(row=r, column=cc)
        d.value = s.value if cc <= 4 else None
        try:
            d._style = copy(s._style)
        except Exception:
            pass
    return r


def _w(ws, cols, r, key, val):
    if val is not None and cols.get(key):
        ws.cell(row=r, column=cols[key]).value = val


def _write_segment(ws, cols, r, lt, sd, ed):
    """把一个请假段写到模板行 (含 Début/Fin 的 (choix) 列)"""
    if lt == 'cp':
        _w(ws, cols, r, 'cp_start', sd)
        _w(ws, cols, r, 'cp_start_choix', VAL_JOURNEE)
        _w(ws, cols, r, 'cp_end', ed)
        _w(ws, cols, r, 'cp_end_choix', VAL_JOURNEE)
    elif lt == 'css':
        _w(ws, cols, r, 'css_start', sd)
        _w(ws, cols, r, 'css_start_choix', VAL_JOURNEE)
        _w(ws, cols, r, 'css_end', ed)
        _w(ws, cols, r, 'css_end_choix', VAL_JOURNEE)
        _w(ws, cols, r, 'css_injustifiee', 'Non')
    elif lt == 'repos':
        _w(ws, cols, r, 'repos_start', sd)
        _w(ws, cols, r, 'repos_start_choix', VAL_JOURNEE)
        _w(ws, cols, r, 'repos_end', ed)
        _w(ws, cols, r, 'repos_end_choix', VAL_JOURNEE)
        _w(ws, cols, r, 'repos_solde', VAL_CONTREPARTIE)
        # 「Heures à décompter」人工版不填写, 故不写
    elif lt == 'rtt':
        _w(ws, cols, r, 'rtt_start', sd)
        _w(ws, cols, r, 'rtt_start_choix', VAL_JOURNEE)
        _w(ws, cols, r, 'rtt_end', ed)
        _w(ws, cols, r, 'rtt_end_choix', VAL_JOURNEE)


def _write_person(ws, cols, rows, emp, cap, cursor, month_start, holidays, warn, label):
    """把一名员工的考勤写入其模板行。

    行分配规则 (与人工版一致, 见文件头 v3.1 第 11 条):
      - 请假段按「槽位」写入: 各类型独立归并成段后, 第 i 行同时承载 CP#i / CSS#i /
        Repos#i / RTT#i。槽位数 = max(各类型段数), 超出已有行数时才追加新行。
      - 非请假字段(HS25/HS50/Type de rémunération/Fériés/Heures d'absence): 只写 rows[0]。
      - 周日奖金: 写在第一行未被他人 prime 占用的行; 若该员工所有行都被占, 追加新行。
    """
    first_row = rows[0]
    kept = _kept_prime_rows(ws, cols, rows)

    # ---- 请假段: 逐类型归并, 再按槽位合并写入 ----
    seg_by_type = {}
    for lt in ('cp', 'css', 'repos', 'rtt'):
        if emp.leave_segments.get(lt):
            seg_by_type[lt] = merge_consecutive_dates(emp.leave_segments[lt], holidays)

    n_slots = max((len(v) for v in seg_by_type.values()), default=0)
    used_rows = rows[:n_slots] + [_append_row(ws, first_row, cursor)
                                  for _ in range(max(0, n_slots - len(rows)))]
    for i in range(n_slots):
        for lt, segs in seg_by_type.items():
            if i < len(segs):
                sd, ed = segs[i]
                _write_segment(ws, cols, used_rows[i], lt, sd, ed)

    # ---- 非请假字段 ----
    hs25 = emp.hs_125_total or 0
    hs50 = emp.hs_150_total or 0
    if (emp.person_type or '').strip() == PERSON_TYPE_INTERN:
        if hs25 or hs50:
            warn.append(f"{label}: 实习生({emp.person_type}) 源表加班 "
                        f"{hs25:.2f}/{hs50:.2f}h, 按人工版规则不填 HS 与 Type de rémunération")
        hs25 = hs50 = 0

    if hs25 > 0 and cols.get('hs_25'):
        ws.cell(row=first_row, column=cols['hs_25']).value = round(hs25, 2)
    if hs50 > 0 and cols.get('hs_50'):
        val = min(hs50, cap)
        ws.cell(row=first_row, column=cols['hs_50']).value = round(val, 2)
        if val < hs50:
            print(f"    [封顶] {label}: HS50% 原始 {hs50:.2f} -> 封顶 {val:.2f} (周数×5={cap})")
    if (hs25 > 0 or hs50 > 0) and cols.get('type_remu'):
        ws.cell(row=first_row, column=cols['type_remu']).value = VAL_TYPE_REMU_HS

    if emp.holiday_hours and cols.get('feries'):
        total = sum(v for v in emp.holiday_hours.values() if isinstance(v, (int, float)))
        if total > 0:
            ws.cell(row=first_row, column=cols['feries']).value = round(total, 2)

    if emp.monthly_absence > 0 and cols.get('heures_absence'):
        ws.cell(row=first_row, column=cols['heures_absence']).value = round(emp.monthly_absence, 2)

    # ---- 周日奖金 ----
    if emp.sunday_prime and emp.sunday_prime > 0:
        if not cols.get('prime_type'):
            warn.append(f"{label}: 月表周日奖金 {emp.sunday_prime} 但模板无『Type de prime』列, 未填写")
        else:
            target = None
            for r in rows:
                if r not in kept:
                    target = r
                    break
            if target is None:
                target = _append_row(ws, first_row, cursor)
            ws.cell(row=target, column=cols['prime_type']).value = VAL_PRIME_DIMANCHE
            _w(ws, cols, target, 'prime_name', VAL_PRIME_DIMANCHE)
            _w(ws, cols, target, 'prime_amount', round(emp.sunday_prime, 2))
            _w(ws, cols, target, 'prime_date', month_start)
            _w(ws, cols, target, 'prime_freq', VAL_FREQ_UNE_FOIS)
            if emp.sunday_days and not cols.get('prime_amount'):
                warn.append(f"{label}: 周日天数 {emp.sunday_days} 天 / 奖金 {emp.sunday_prime} 未能写入模板")


# ============================================================
# 填写 import 模板
# ============================================================

LOC_KEYS = {'Gonesse': 'GONESSE', 'Nanteuil': 'NANTEUIL', 'SM': 'SAINT-MARD'}


def _open_template(template_path):
    wb = openpyxl.load_workbook(template_path)
    ws = wb['Page 1'] if 'Page 1' in wb.sheetnames else wb[wb.sheetnames[0]]
    return wb, ws


def _print_cols(cols):
    print(f"  检测列: HS25%={cols.get('hs_25')}, HS50%={cols.get('hs_50')}, "
          f"TypeRém={cols.get('type_remu')}, PrimeType={cols.get('prime_type')}, "
          f"PrimeMontant={cols.get('prime_amount')}, Fériés={cols.get('feries')}, "
          f"Absence={cols.get('heures_absence')}, CSS injustifiée={cols.get('css_injustifiee')}, "
          f"Solde={cols.get('repos_solde')}, FinChoix(CP/CSS/Repos)="
          f"{cols.get('cp_end_choix')}/{cols.get('css_end_choix')}/{cols.get('repos_end_choix')}")


def _count_preserved(ws, cols, roster_rows):
    n = 0
    for key in PRESERVE_COL_KEYS:
        c = cols.get(key)
        if not c:
            continue
        for r in roster_rows:
            v = ws.cell(row=r, column=c).value
            if v is not None and str(v).strip():
                n += 1
    return n


def _prepare_template(ws, cols, warn, tpl_label):
    """读取员工区 -> 清空工具列 -> 返回 (roster, cursor, 统计)"""
    roster, last_row, stray_rows = collect_template_employees(ws)
    all_rows = [r for ent in roster.values() for r in ent['rows']]

    kept_ids = set(ent['id'] for ent in roster.values() if ent['id'])
    stray_orphan = []
    for r in stray_rows:
        v = ws.cell(row=r, column=1).value
        if v is not None and str(v).strip() in kept_ids:
            stray_orphan.append(r)
        else:
            warn.append(f"{tpl_label}: 员工区外第 {r} 行有未知 ObjectId, 已保留未改动")
    if stray_orphan:
        warn.append(f"{tpl_label}: 清理员工区外残留行 {len(stray_orphan)} 行 "
                    f"(第 {stray_orphan[0]}~{stray_orphan[-1]} 行, 历史工具追加造成)")

    _clear_owned_cells(ws, cols, all_rows, stray_orphan)

    preserved = _count_preserved(ws, cols, all_rows)
    if preserved:
        print(f"  保留模板人工维护列(餐票等) {preserved} 个单元格未改动")

    dup = defaultdict(list)
    for key, ent in roster.items():
        dup[normalize_name(ent['name'])].append(key)
    for nm, keys in dup.items():
        if len(keys) > 1:
            warn.append(f"{tpl_label}: 模板中有 {len(keys)} 个同名员工 '{nm}', 按姓名匹配可能串行, 请人工确认")

    return roster, [last_row + 1], all_rows


def fill_template(template_path, output_path, employees, location_key,
                  holidays, n_weeks, month_start=None, warn=None):
    """按地点从源表员工出发填写模板 (单模板调用)。"""
    warn = warn if warn is not None else []
    wb, ws = _open_template(template_path)
    cols = detect_columns(ws)
    _print_cols(cols)

    roster, cursor, _ = _prepare_template(ws, cols, warn, os.path.basename(template_path))
    name_index = {}
    for key, ent in roster.items():
        name_index.setdefault(ent['name'], ent)

    filled = 0
    unmatched = []
    cap = 5 * n_weeks
    for weekly_name, emp in employees.items():
        # 地点过滤 (地点已知时按地点; 地点未知但能匹配模板也填)
        if emp.location is not None and emp.location != LOC_KEYS[location_key]:
            continue
        matched = match_employee(weekly_name, list(name_index.keys()))
        if not matched:
            if emp.location is None:
                unmatched.append(weekly_name)
            continue
        ent = name_index[matched]
        _write_person(ws, cols, ent['rows'], emp, cap, cursor,
                      month_start, holidays, warn, matched)
        filled += 1

    wb.save(output_path)
    return filled, unmatched


def _auto_gen_name(tpl_path):
    """把上传的空白模板文件名改为 (自动生成) 版"""
    base = os.path.basename(tpl_path)
    if base.lower().endswith(".xlsx"):
        return base[:-5] + " (自动生成).xlsx"
    return base + " (自动生成)"


def fill_template_by_template(weekly_employees, template_path, output_path, holidays, n_weeks,
                             month_start=None, warn=None):
    """以 import 模板人员为基准填充 (Web 多文件模式专用)。

    weekly_employees: parse_weekly_file 返回的 dict (weekly_name -> EmployeeWeeklyData)
    返回 (filled, template_missing, source_extra):
      filled           模板中匹配到源表并填写的人数
      template_missing 模板中有姓名但源表无匹配的人 (保持空白, 不报错)
      source_extra     源表中所有姓名里, 不匹配任何模板的人 (供前端提示)
    """
    warn = warn if warn is not None else []
    wb, ws = _open_template(template_path)
    cols = detect_columns(ws)
    _print_cols(cols)

    roster, cursor, _ = _prepare_template(ws, cols, warn, os.path.basename(template_path))

    filled = 0
    template_missing = []
    matched_source_names = set()
    cap = 5 * n_weeks
    weekly_names = list(weekly_employees.keys())

    for key, ent in roster.items():
        tpl_name = ent['name']
        matched = match_employee(tpl_name, weekly_names)
        if not matched:
            template_missing.append(tpl_name)
            continue
        matched_source_names.add(matched)
        emp = weekly_employees[matched]
        _write_person(ws, cols, ent['rows'], emp, cap, cursor,
                      month_start, holidays, warn, tpl_name)
        filled += 1

    wb.save(output_path)
    return filled, template_missing, sorted(matched_source_names)


def run_fill_v2(weekly_path, template_paths, output_dir=None):
    """Web 多文件模式: 模板由用户上传的空白 import 文件列表。
    以模板人员为基准填充; 源表有但模板无的人不填写, 仅记录提示。

    返回 (outputs:list, report:dict):
      report = {
        'filled':          {模板文件名: 已填人数},
        'template_missing': {模板文件名: [模板有但源表无]},
        'source_extra':    [源表有但任何模板都没有],
        'warnings':        [填写过程中的提示/需人工确认项],
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
    os.makedirs(output_dir, exist_ok=True)

    ym = derive_ym(weekly_path, os.path.dirname(os.path.abspath(template_paths[0])))
    month_start = month_start_from_ym(ym)
    print(f"年月标识: {ym} (prime 起始日={month_start})\n")

    outputs = []
    report = {'filled': {}, 'template_missing': {}, 'source_extra': [], 'warnings': []}
    warn = report['warnings']
    global_matched = set()
    for tpl in template_paths:
        out_name = _auto_gen_name(tpl)
        out_path = os.path.join(output_dir, out_name)
        print(f"填写 {os.path.basename(tpl)} ...")
        cnt, t_missing, matched_list = fill_template_by_template(
            employees, tpl, out_path, holidays, n_weeks,
            month_start=month_start, warn=warn)
        print(f"  已填写 {cnt} 人 -> {out_path}")
        outputs.append(out_path)
        report['filled'][os.path.basename(tpl)] = cnt
        if t_missing:
            report['template_missing'][os.path.basename(tpl)] = t_missing
        global_matched.update(matched_list)
        print()

    weekly_names = list(employees.keys())
    report['source_extra'] = sorted(w for w in weekly_names if w not in global_matched)
    if warn:
        print("提示 / 需人工确认:")
        for w in warn:
            print("  - " + w)
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
    month_start = month_start_from_ym(ym)
    print(f"每周工资计算表: {weekly_path}")
    print(f"模板目录: {template_dir}")
    print(f"年月标识: {ym}  (prime 起始日={month_start})\n")

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
    os.makedirs(output_dir, exist_ok=True)

    all_unmatched = {}
    outputs = []
    warn = []
    for key, tpl in templates.items():
        out_name = f"import_variables_paie-{ym} {key} (自动生成).xlsx"
        out_path = os.path.join(output_dir, out_name)
        print(f"填写 {key} ...")
        cnt, unmatched = fill_template(tpl, out_path, employees, key, holidays, n_weeks,
                                       month_start=month_start, warn=warn)
        print(f"  已填写 {cnt} 人 -> {out_path}")
        outputs.append(out_path)
        if unmatched:
            all_unmatched[key] = unmatched
        print()

    if warn:
        print("=" * 64)
        print("提示 / 需人工确认:")
        for w in warn:
            print("  - " + w)

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

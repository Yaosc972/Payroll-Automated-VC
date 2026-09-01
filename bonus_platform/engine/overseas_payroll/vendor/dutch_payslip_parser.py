# -*- coding: utf-8 -*-
"""荷兰工资单 PDF -> Excel 提取器 (CIRRO E-Commerce Europe B.V. / 此类 Loonstrook)
按 Salarisspecificatie 标记分组员工；主页按坐标提取明细表，附录页提取汇总；
生成 Sheet1 工资明细 + Sheet2 员工汇总（含成本合计）。小计/合计行不进入 Sheet1。
"""
import io
import re
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

import pdfplumber
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Border, Side, Alignment
from openpyxl.utils import get_column_letter

# ---------- 数值解析 ----------
def parse_num(s):
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    neg = s.startswith('-')
    s = s[1:] if neg else s
    s = s.replace('.', '').replace(',', '.')
    try:
        v = float(s)
    except Exception:
        return None
    return -v if neg else v


# ---------- 列坐标边界 (基于 dump 实测, 页宽 595) ----------
COL_BOUNDS = [
    (40, 66, 'code'),
    (66, 200, 'desc'),
    (200, 242, 'periode'),
    (242, 276, 'aantal'),
    (276, 316, 'waarde'),
    (316, 360, 'betaling'),
    (360, 416, 'inhouding'),
    (416, 468, 'tabel'),
    (468, 503, 'bt'),
    (503, 532, 'svw'),
    (532, 576, 'werkgever'),
]

# 动态边界: 每页从表头行读取各列真实 x0, 解决双期间等排版列偏移
CUR_BOUNDS = COL_BOUNDS
HEADER_NAME_MAP = {
    # 荷兰语 (R10)
    'Code': 'code', 'Omschrijving': 'desc', 'Periode': 'periode', 'Aantal': 'aantal',
    'Waarde': 'waarde', 'Betaling': 'betaling', 'Inhouding': 'inhouding', 'Tabel': 'tabel',
    'BT': 'bt', 'SVW': 'svw', 'Werkgever': 'werkgever',
    # 英语 (R12)
    'Description': 'desc', 'Period': 'periode', 'Qty': 'aantal', 'Value': 'waarde',
    'Payment': 'betaling', 'Retention': 'inhouding', 'Table': 'tabel',
    'Cumulative': 'werkgever',
}


def compute_bounds(header_line):
    """从表头行词提取各列 x0, 按 x 排序生成边界。无表头时退回固定边界。
    边界取相邻列表头 x0 的中点, 容错词在列内的轻微偏移。"""
    pts = []
    for w in header_line:
        for k, v in HEADER_NAME_MAP.items():
            if w['text'] == k or w['text'].startswith(k):
                pts.append((w['x0'], v))
                break
    if len(pts) < 5:
        return None
    pts.sort(key=lambda p: p[0])
    n = len(pts)
    bounds = []
    for i, (x0, name) in enumerate(pts):
        lo = (pts[i - 1][0] + x0) / 2 if i > 0 else 0
        hi = (x0 + pts[i + 1][0]) / 2 if i + 1 < n else 595
        bounds.append((lo, hi, name))
    return bounds

SECTION_LABELS = ['Bruto', 'Werknemer Verzekering', 'Zvw', 'Loonheffing',
                  'Netto', 'Totalen', 'Betalen', 'Overige',
                  # 英语 (R12)
                  'Gross', 'Tax', 'Net', 'Totals', 'Payment', 'Other']
# section 归一化：英语统一映射到荷兰语，方便 Sheet2 汇总
SECTION_NORM = {
    'Gross': 'Bruto', 'Tax': 'Loonheffing', 'Net': 'Netto',
    'Totals': 'Totalen', 'Payment': 'Betalen', 'Other': 'Overige',
}
# 附录汇总区块，不应进入 Sheet1 明细
APPENDIX_LABELS = ['Reservation', 'Reservering', 'Fiscal wage', 'Fiscaal loon',
                   'SVW wage', 'SVW loon']
MONEY_COLS = ('waarde', 'betaling', 'inhouding', 'tabel', 'bt', 'svw', 'werkgever')


def col_of(x):
    for lo, hi, name in CUR_BOUNDS:
        if lo <= x < hi:
            return name
    return None


def group_lines(words, tolerance=3.0):
    # 语义聚合: 相邻词 top 差 ≤ tolerance 视为同一视觉行(含基线抖动), 真实行距~11px 仍可分。
    # 用「相对首词 top」而非 round 取整, 避免 round 边界把相差 1px 的跨行金额(如 9900 Total net
    # 标签与金额 1003,44 差 1px)拆成两行, 导致 Total net 无金额被跳过、实发取 0。
    words = sorted(words, key=lambda w: (w['top'], w['x0']))
    lines, cur, cur_top = [], None, None
    for w in words:
        if cur is None or w['top'] - cur_top > tolerance:
            cur = []
            lines.append(cur)
            cur_top = w['top']
        cur.append(w)
    return lines


def line_text(line):
    return ' '.join(w['text'] for w in line)


def section_of(text):
    for lab in SECTION_LABELS:
        if lab in text:
            return SECTION_NORM.get(lab, lab)
    return ''


def is_appendix_section(text):
    for lab in APPENDIX_LABELS:
        if lab in text:
            return True
    return False


def clean_money(raw, prefer_negative=False):
    """同列出现多个数值时取最相关的一个: Inhouding 取负值, 其余取首个。返回字符串或 None"""
    if not raw:
        return None
    nums = []
    for t in raw.split():
        v = parse_num(t)
        if v is not None:
            nums.append((t, v))
    if not nums:
        return None
    if prefer_negative:
        negs = [t for t, v in nums if v < 0]
        return negs[0] if negs else nums[0][0]
    return nums[0][0]


def split_aantal_waarde(raw):
    """Aantal 列偶尔被 Waarde 值污染(如 '0,630 2922,18'), 拆成 (aantal, waarde)。
    规则: Aantal 通常是比率/系数(<100), Waarde 是工资金额(通常>=1000);
    单个大金额落入 Aantal 列时, 应归到 Waarde。"""
    if not raw:
        return '', ''
    parts = raw.strip().split()
    nums = [(p, parse_num(p)) for p in parts if parse_num(p) is not None]
    if len(nums) >= 2:
        v0, v1 = nums[0][1], nums[1][1]
        # 两个都是大金额 -> 第一个也判为 waarde 漂移
        if v0 >= 1000 and v1 >= 1000:
            return '', nums[0][0]
        return nums[0][0], nums[1][0]
    if len(nums) == 1:
        if nums[0][1] >= 1000:
            return '', nums[0][0]
        return nums[0][0], ''
    return raw.strip(), ''


def is_header_line(line):
    """识别主表表头行（支持 NL / EN）。"""
    txts = [w['text'] for w in line]
    txts_set = set(txts)
    # 荷兰语：Code + Omschrijving
    if 'Code' in txts and any(t.startswith('Omschrijving') for t in txts):
        return True
    # 英语 R12：Description + Value + Payment（注意 R12 无 Code 列）
    if 'Description' in txts and 'Value' in txts and 'Payment' in txts:
        return True
    return False


def parse_main_page(pg):
    """返回 (meta, detail_rows, kosten_total)"""
    text = pg.extract_text() or ''
    words = pg.extract_words()
    lines = group_lines(words)

    # 定位主表起始行 (含表头), 仅其下方为明细
    thr = None
    header_line = None
    has_code_col = False
    for line in lines:
        if is_header_line(line):
            thr = max(w['top'] for w in line) + 5
            header_line = line
            has_code_col = any(w['text'] == 'Code' for w in line)
            break
    if thr is None:
        thr = 388
    # 动态列边界: 用本页表头真实 x0 对齐, 解决双期间等排版列偏移错位
    global CUR_BOUNDS
    dyn = compute_bounds(header_line) if header_line else None
    CUR_BOUNDS = dyn if dyn else COL_BOUNDS

    meta = parse_meta(text, words)
    detail = []
    current_section = ''
    per_bank_netto = None
    for line in lines:
        top = line[0]['top']
        if top < thr:
            continue  # 表头以上(员工信息块)整体跳过, 避免邮编等误当 Code
        txt = line_text(line)
        left = line[0]
        left_col = col_of(left['x0'])
        # 遇到附录汇总区块（Reservation / Fiscal wage / SVW wage）即停止，后续不再进 Sheet1
        if is_appendix_section(txt):
            break
        # section 标题行：通常在最左列，无金额数值，且命中已知 section 关键字
        has_amount = any(col_of(w['x0']) in MONEY_COLS and re.search(r'\d', w['text']) for w in line)
        if left_col in ('code', 'desc') and not has_amount and not re.search(r'[\d.,-]{2,}', left['text']):
            sec = section_of(txt)
            if sec:
                current_section = sec
                continue
        # 明细行识别
        code_word = None
        if has_code_col:
            for w in line:
                if col_of(w['x0']) == 'code' and re.match(r'^\d{3,5}$', w['text'].strip()):
                    code_word = w
                    break
            if not code_word:
                continue  # 小计/合计行 或 非明细行 -> 跳过
        else:
            # 英语 R12：无 Code 列，用金额+section判断。
            has_money = any(col_of(w['x0']) in MONEY_COLS and re.search(r'\d', w['text'])
                             for w in line)
            if not has_money:
                continue
            # 跳过 section 标题、小计/合计、Per Bank 等支付说明行
            desc_words = [w for w in line if col_of(w['x0']) == 'desc']
            desc_txt = ' '.join(w['text'] for w in desc_words).strip()
            full_txt = line_text(line)
            if not desc_txt:
                continue
            # Per Bank 行：提取当月实发到 meta，但不进入 Sheet1 明细
            if re.search(r'\bPer\s+Bank\b', full_txt, re.I):
                for w in line:
                    if col_of(w['x0']) == 'betaling':
                        v = parse_num(clean_money(w['text']))
                        if v is not None and v > 0:
                            per_bank_netto = v
                            break
                continue
            # 保留 Total net（用于 Sheet2 Netto 实发），跳过其它合计/支付说明行
            if re.search(r'\bTotal\s+net\b', desc_txt, re.I):
                pass
            else:
                skip_re = r'\b(Total|Totals|Totaal|Totalen|Netto|Net|Payment|IBAN|BIC)\b'
                if re.search(skip_re, desc_txt, re.I):
                    continue
            # 用描述文本作为 code（R12 无数字编码）
            code_word = desc_words[0]
        # 必须有金额列数值, 过滤掉纯文本误匹配
        has_money = any(col_of(w['x0']) in MONEY_COLS and re.search(r'\d', w['text'])
                         for w in line)
        if not has_money:
            continue
        row = {c: '' for c in ['code', 'desc', 'periode', 'aantal', 'waarde',
                                'betaling', 'inhouding', 'tabel', 'bt', 'svw', 'werkgever']}
        row['code'] = code_word['text'].strip()
        row['section'] = current_section
        for w in line:
            c = col_of(w['x0'])
            if c == 'code':
                continue
            if c == 'desc':
                row['desc'] = (row['desc'] + ' ' + w['text']).strip()
            elif c:
                if row[c] == '':
                    row[c] = w['text'].strip()
                else:
                    row[c] = (row[c] + ' ' + w['text']).strip()
        detail.append(row)

    if per_bank_netto is not None:
        meta['per_bank_netto'] = per_bank_netto
    return meta, detail, ''


def extract_overige(emp_pages):
    """跨页提取 Overige 区块: 7711 Holiday allowance 当月发生额 + 其下成本合计。
    7711 可能在主表页(第1页末尾), 也可能被分页整体推到附录页顶部(S.Heinen/Y.Fu 等)。
    返回 (holiday_str, kosten_str), 取不到则为空串。"""
    holiday = ''
    kosten = ''
    n = len(emp_pages)
    for pi, pg in enumerate(emp_pages):
        words = pg.extract_words()
        for w in words:
            if w['text'].strip() == '7711' and col_of(w['x0']) == 'code':
                line = [x for x in words if abs(x['top'] - w['top']) < 5]
                if any('holiday' in x['text'].lower() for x in line):
                    if not holiday:
                        for x in line:
                            if col_of(x['x0']) == 'werkgever' and re.match(r'^[\d.,-]+$', x['text']):
                                holiday = x['text']
                                break
                    if not kosten:
                        # 同页 7711 之下、右侧列(Werkgever 位)的数字 = 成本合计
                        cands = [x for x in words
                                 if x['top'] > w['top'] + 3 and x['x0'] > 500
                                 and re.match(r'^[\d.,-]+$', x['text'].strip())]
                        cands.sort(key=lambda x: x['top'])
                        if cands:
                            kosten = cands[0]['text']
                        elif pi + 1 < n:
                            # 跨页: 成本合计被推到下一页顶部 (top<120, 右侧列)
                            nw = emp_pages[pi + 1].extract_words()
                            nc = [x for x in nw
                                  if x['top'] < 120 and x['x0'] > 500
                                  and re.match(r'^[\d.,-]+$', x['text'].strip())]
                            nc.sort(key=lambda x: x['top'])
                            if nc:
                                kosten = nc[0]['text']
    return holiday, kosten


def _extract_name(words):
    """从坐标词按行提取员工姓名：title 词(Mevrouw/Mr./Ms./Mrs. 单 token, 或 De heer 双 token)
    起的同行左块，以「公司名短语」起始 x0 为右界切掉右侧公司名(如 CIRRO/GOFO ... B.V.)，
    兼容多主体。注意 pdfplumber 把 "De heer" 拆成两词，需特殊处理。"""
    if not words:
        return ''
    titles_single = {'mevrouw', 'mr', 'ms', 'mrs'}
    title_w = None
    for i, w in enumerate(words):
        t = w['text'].rstrip('.').lower()
        if t in titles_single:
            title_w = w
            break
        # De heer 双 token：De 后紧跟 heer
        if t == 'de' and i + 1 < len(words) and words[i + 1]['text'].rstrip('.').lower() == 'heer':
            title_w = w
            break
    if title_w is None:
        return ''
    top0 = title_w['top']
    line_words = sorted([w for w in words if abs(w['top'] - top0) <= 6], key=lambda w: w['x0'])
    if not line_words:
        return ''
    x0_0 = title_w['x0']
    # 公司短语起点 comp_start：默认行尾（整行都算姓名）
    comp_start = len(line_words)
    bv_i = None
    for i, w in enumerate(line_words):
        t = w['text'].rstrip('.').upper()
        if t == 'B.V' or t.endswith('B.V.'):
            bv_i = i
            break
    if bv_i is not None:
        # 从 B.V. 向左走，相邻间隙 < 100 视为公司短语内部；遇大间隙即公司起点
        comp_start = bv_i
        j = bv_i - 1
        while j >= 0 and (line_words[j + 1]['x0'] - line_words[j]['x0']) < 100:
            comp_start = j
            j -= 1
    else:
        # 无 B.V.：用整行最大间隙作为姓名/公司分界
        max_gap = 0
        for i in range(1, len(line_words)):
            g = line_words[i]['x0'] - line_words[i - 1]['x0']
            if g > max_gap:
                max_gap = g
                comp_start = i
    name_words = [w for w in line_words[:comp_start] if w['x0'] >= x0_0]
    if not name_words:
        return ''
    full = ' '.join(w['text'] for w in name_words)
    full = re.sub(r'^(De heer|Mevrouw|Mr\.|Ms\.|Mrs\.)\s+', '', full, flags=re.I).strip()
    return full


def parse_meta(text, words=None):
    meta = {'name': '', 'pers_nr': '', 'period': '', 'stam': '', 'dagen': '', 'uren': '', 'in_dienst': ''}
    # 姓名：优先坐标法(左块姓名/右块公司, 兼容 CIRRO/GOFO 等多主体)；兜底用旧文本正则
    nm = _extract_name(words)
    if nm:
        meta['name'] = nm
    else:
        m = re.search(r'(De heer|Mevrouw|Mr\.|Ms\.|Mrs\.)\s+.*?\s+B\.V\.', text, re.I)
        if m:
            nm2 = re.sub(r'^(De heer|Mevrouw|Mr\.|Ms\.|Mrs\.)\s+', '', m.group(0).replace('B.V.', '').strip(), flags=re.I)
            meta['name'] = nm2.strip()
    m = re.search(r'Pers\.\s*nr\.:\s*(\S+)', text)
    if m:
        meta['pers_nr'] = m.group(1)
    # 期间：NL "Salaris periode"；EN "Salary period"
    m = re.search(r'(?:Salaris periode|Salary period)\s+([^\s/]+)', text, re.I)
    if m:
        meta['period'] = m.group(1)
    # 基本工资：NL "Stam salaris"；EN "Base salary"
    m = re.search(r'(?:Stam salaris|Base salary):\s*([\d.,]+)', text, re.I)
    if m:
        meta['stam'] = m.group(1)
    # 工作天数：NL "Dagen gewerkt"；EN "Days worked"
    m = re.search(r'(?:Dagen gewerkt|Days worked):\s*(\d+)', text, re.I)
    if m:
        meta['dagen'] = m.group(1)
    # 工作小时：NL "Verloonde uren"；EN "Hours worked"
    m = re.search(r'(?:Verloonde uren|Hours worked):\s*([\d.,]+)', text, re.I)
    if m:
        meta['uren'] = m.group(1)
    # R12 中 "Hours/week" 不要误当成 Hours worked，如果 uren 异常大则清空
    if meta.get('uren') and float(meta['uren'].replace('.', '').replace(',', '.')) > 500:
        meta['uren'] = ''
    # 入职日期：NL "In dienst"；EN "In service"
    m = re.search(r'(?:In dienst|In service):\s*([^\s]+)', text, re.I)
    if m:
        meta['in_dienst'] = m.group(1)
    return meta


def parse_appendix(pg):
    text = pg.extract_text() or ''
    s = {}
    # NL: Fiscaal loon ... Loonheffing ... Dagen gewerkt ... Verloonde uren
    # EN R12: Fiscal wage ... Tax ... Days worked ... Hours worked
    m = re.search(r'(?:Fiscaal loon|Fiscal wage)\s+([\d.,]+)\s+(?:Loonheffing|Tax)\s+([\d.,]+)\s+(?:Dagen gewerkt|Days worked)\s+(\d+)\s+(?:Verloonde uren|Hours worked)\s+(\d+)', text, re.I)
    if m:
        s['fiscaal_loon'] = m.group(1)
        s['loonheffing_cum'] = m.group(2)
        s['dagen'] = m.group(3)
        s['uren'] = m.group(4)
    # NL: SVW loon ... Arbeidskorting cum. ... Arbeidskorting d.p. ... Run nummer
    # EN R12: SVW wage ... Labour deduction cum. ... Labour deduction t.p. ... Run number
    m = re.search(r'(?:SVW loon|SVW wage)\s+([\d.,]+)\s+(?:Arbeidskorting cum\.|Labour deduction cum\.)\s+([\d.,]+)\s+(?:Arbeidskorting d\.p\.|Labour deduction t\.p\.)\s+([\d.,]+)\s+(?:Run nummer|Run number):?\s+(\d+)', text, re.I)
    if m:
        s['svw_loon'] = m.group(1)
        s['arb_cum'] = m.group(2)
        s['arb_dp'] = m.group(3)
        s['run'] = m.group(4)
    # Reservation Res Balance / Reservering Res Saldo
    # 注意：R12 主表 Bruto 段也含 "Holiday allowance"（4 个数字），必须只在
    # Reservation/Reservering 段之后匹配，否则会错误命中主表、污染 Res/Saldo。
    m_res = re.search(r'(?:Reservering|Reservation)\s+Res\s+(?:Saldo|Balance)', text, re.I)
    target = text[m_res.end():] if m_res else text
    m = re.search(r'(?:Holiday allowance|Vakantiegeld)\s+([\d.,]+)\s+([\d.,]+)', target, re.I)
    if m:
        s['res_res'] = m.group(1)
        s['res_saldo'] = m.group(2)
    return s


def is_salary_spec_page(text):
    if not text:
        return False
    return 'Salarisspecificatie' in text or 'Salary specification' in text


def run(pdf_path):
    with pdfplumber.open(pdf_path) as pdf:
        pages = pdf.pages
        starts = [i for i, p in enumerate(pages)
                  if is_salary_spec_page(p.extract_text() or '')]
        employees = []
        for idx, sp in enumerate(starts):
            ep = (starts[idx + 1] - 1) if idx + 1 < len(starts) else (len(pages) - 1)
            rng = list(range(sp, ep + 1))
            try:
                meta, detail, _ = parse_main_page(pages[sp])
                summary = {}
                for ap in rng:
                    summary.update(parse_appendix(pages[ap]))
                emp_pages = [pages[i] for i in rng]
                holiday_str, kosten_str = extract_overige(emp_pages)
                employees.append({'meta': meta, 'detail': detail,
                                  'kosten': kosten_str, 'holiday': holiday_str,
                                  'summary': summary, 'pages': rng})
            except Exception as e:
                print('[WARN] 员工页 %s 解析异常: %s' % (rng, e))

    print('[DUTCH] 员工 %d 名' % len(employees))
    for e in employees:
        print('  %s (nr%s) 明细%d行 页码%s' % (
            e['meta']['name'], e['meta']['pers_nr'], len(e['detail']), e['pages']))

    return _build_workbook(employees)


def _build_workbook(employees):
    """依据解析后的 employees 列表生成 Excel 工作簿（工资明细 + 双表头员工汇总）。
    Sheet2「员工汇总」为双行表头：第一行按 员工信息/应发Bruto/加班费明细/扣除/公司承担/
    实发/成本与基数 分组，第二行展开细项（补贴、奖金、加班倍率等逐项列示）。"""

    # ============ 生成 Excel ============
    wb = Workbook()
    ws1 = wb.active
    ws1.title = '工资明细'
    ws2 = wb.create_sheet('员工汇总')

    thin = Side(style='thin', color='D0D7DE')
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    head_fill = PatternFill('solid', fgColor='1F4E78')
    head_font = Font(bold=True, color='FFFFFF', size=10)
    center = Alignment(horizontal='center', vertical='center', wrap_text=True)
    money_fmt = '#.##0,00'

    # ---- Sheet1 ----
    h1 = ['姓名', '员工编号', '期间', 'Code', '科目描述', 'Periode', 'Aantal',
          'Waarde', 'Betaling', 'Inhouding', 'Tabel', 'BT', 'SVW', 'Werkgever', '页码']
    ws1.append(h1)
    for c in range(1, len(h1) + 1):
        cell = ws1.cell(row=1, column=c)
        cell.fill = head_fill
        cell.font = head_font
        cell.alignment = center
        cell.border = border
    r = 2
    for e in employees:
        for d in e['detail']:
            aantal_raw, waarde_from_aantal = split_aantal_waarde(d['aantal'])
            aantal_val = parse_num(aantal_raw) if aantal_raw else None
            waarde_val = parse_num(clean_money(d['waarde'])) if d['waarde'] else None
            if waarde_val is None and waarde_from_aantal:
                waarde_val = parse_num(waarde_from_aantal)
            bet = parse_num(clean_money(d['betaling']))
            inh = parse_num(clean_money(d['inhouding'], prefer_negative=True))
            tabel = parse_num(clean_money(d['tabel']))
            bt = parse_num(clean_money(d['bt']))
            svw = parse_num(clean_money(d['svw']))
            werk = parse_num(clean_money(d['werkgever']))
            vals = [e['meta']['name'], e['meta']['pers_nr'], e['meta']['period'],
                    d['code'], d['desc'], d['periode'], aantal_val, waarde_val, bet,
                    inh, tabel, bt, svw, werk, e['pages'][0] + 1]
            for c, v in enumerate(vals, 1):
                cell = ws1.cell(row=r, column=c, value=v if v is not None else '')
                cell.border = border
                cell.alignment = center
                if c in (7, 8, 9, 10, 11, 12, 13, 14) and v is not None:
                    cell.number_format = money_fmt
            r += 1
    widths1 = [16, 10, 12, 8, 26, 10, 9, 11, 11, 11, 9, 8, 9, 11, 7]
    for i, w in enumerate(widths1, 1):
        ws1.column_dimensions[get_column_letter(i)].width = w
    ws1.freeze_panes = 'A2'
    if r > 2:
        ws1.auto_filter.ref = 'A1:O%d' % (r - 1)

    # ---- Sheet2 双表头（员工汇总）----
    GROUPS = [
        ('员工信息', ['序号', '姓名', '员工编号', '期间']),
        ('应发 Bruto', ['应发合计', '基本工资', '电话补贴', '交通补助', '夜班补贴',
                       '假期补贴', '其他津贴', 'Bonus', '离职补偿金', '加班费合计', '其他应发']),
        ('加班费明细', ['100%时薪', '100%时长', '100%加班费',
                       '125%时薪', '125%时长', '125%加班费',
                       '150%时薪', '150%时长', '150%加班费',
                       'PH200%时薪', 'PH200%时长', 'PH200%加班费',
                       '200%时薪', '200%时长', '200%加班费',
                       '250%时薪', '250%时长', '250%加班费']),
        ('扣除', ['Pension扣', '工资税', '其他扣除']),
        ('实发', ['实发Netto']),
        ('公司承担', ['公司保险合计']),
        ('Holiday allowance', ['Res', 'Saldo']),
        ('成本与基数', ['成本合计', '应税工资', '社保基数', '工作天数', '已付工时', 'Run批次']),
    ]
    GROUP_FILL = {
        '员工信息': '0C447C', '应发 Bruto': 'BA7517', '加班费明细': 'C55A11',
        '扣除': 'A32D2D', '公司承担': '534AB7', '实发': '3B6D11',
        'Holiday allowance': '2E7D32', '成本与基数': '5F5E5A',
    }
    GROUP_FILL_LIGHT = {
        '员工信息': 'E6F1FB', '应发 Bruto': 'FAEEDA', '加班费明细': 'FCE9D6',
        '扣除': 'FCEBEB', '公司承担': 'EEEDFE', '实发': 'EAF3DE',
        'Holiday allowance': 'E3F2E1', '成本与基数': 'F1EFE8',
    }
    sub_headers = []
    for _g, _subs in GROUPS:
        for _s in _subs:
            sub_headers.append((_g, _s))
    ncols = len(sub_headers)

    # 第一行：分组（合并单元格）
    c = 1
    for _g, _subs in GROUPS:
        _span = len(_subs)
        ws2.merge_cells(start_row=1, start_column=c, end_row=1, end_column=c + _span - 1)
        _cell = ws2.cell(row=1, column=c)
        _cell.value = _g
        _cell.fill = PatternFill('solid', fgColor=GROUP_FILL[_g])
        _cell.font = Font(bold=True, color='FFFFFF', size=10)
        _cell.alignment = center
        _cell.border = border
        c += _span
    # 第二行：细项
    for i, (_g, _s) in enumerate(sub_headers, 1):
        _cell = ws2.cell(row=2, column=i)
        _cell.value = _s
        _cell.fill = PatternFill('solid', fgColor=GROUP_FILL_LIGHT[_g])
        _cell.font = Font(bold=True, color='333333', size=9)
        _cell.alignment = center
        _cell.border = border

    def bet_of(d):
        raw = d.get('betaling', '')
        if not raw:
            return None
        nums = [parse_num(t) for t in raw.split() if parse_num(t) is not None]
        if not nums:
            return None
        # betaling 列可能因列错位混入前导 0(如 '0 1003,44'), 取最后一个非零值(真实金额)
        for v in reversed(nums):
            if v != 0:
                return v
        return 0.0

    def inh_of(d):
        v = parse_num(clean_money(d.get('inhouding', ''), prefer_negative=True))
        return abs(v) if v is not None else None

    def sum_section_wg(det, sec):
        tot = 0.0
        for d in det:
            if d.get('section') == sec:
                v = parse_num(clean_money(d.get('werkgever', '')))
                if v is not None:
                    tot += v
        return tot

    OT_RATES = [100, 125, 150, 200, 250]
    r = 3
    for idx, e in enumerate(employees, 1):
        det = e['detail']
        s = e['summary']
        base_salary = tel = trans = night = holiday_alw = other_allow = None
        bonus = severance = ot_total = other_bruto = None
        ot = {rt: [None, None, None] for rt in OT_RATES}
        ph = [None, None, None]
        pension = wage_tax = other_ded = None
        for d in det:
            desc = d.get('desc', '') or ''
            sec = d.get('section', '') or ''
            b = bet_of(d)
            ih = inh_of(d)
            # 加班（含 100/125/150/200/250%），用 split_aantal_waarde 清洗 aantal 列污染
            if re.search(r'overtime|overwerk', desc, re.I):
                m = re.search(r'(\d+)\s*%', desc)
                rate = int(m.group(1)) if m else None
                a_clean, w_clean = split_aantal_waarde(d.get('aantal', ''))
                waarde_src = w_clean if w_clean else d.get('waarde', '')
                if rate in ot:
                    ot[rate][0] = parse_num(clean_money(waarde_src)) if waarde_src else None
                    ot[rate][1] = parse_num(a_clean) if a_clean else parse_num(d.get('aantal', ''))
                    ot[rate][2] = b
                    if b:
                        ot_total = (ot_total or 0) + b
                elif b:
                    ot_total = (ot_total or 0) + b
                continue
            # Public Holiday（节假日加班，倍率常标 200%，无 % 字样亦匹配）
            if re.search(r'public\s+holiday', desc, re.I):
                a_clean, w_clean = split_aantal_waarde(d.get('aantal', ''))
                waarde_src = w_clean if w_clean else d.get('waarde', '')
                ph[0] = parse_num(clean_money(waarde_src)) if waarde_src else None
                ph[1] = parse_num(a_clean) if a_clean else parse_num(d.get('aantal', ''))
                ph[2] = b
                if b:
                    ot_total = (ot_total or 0) + b
                continue
            # 30% ruling 外籍免税项：`30% Ruling (table)/(BT)` 是从应税基数减去的免税额度(非扣除)、
            # `30% ruling (untaxed)` 是免税发放(已含在 Total net 实发内)。两者互相抵消，均不计入应发/扣除，
            # 否则会污染「其他扣除」与「应发合计」。
            if re.search(r'30\s*%\s*ruling', desc, re.I):
                continue
            if re.search(r'\bsalary\b', desc, re.I):
                if b:
                    base_salary = (base_salary or 0) + b
                continue
            if re.search(r'mobile allowance', desc, re.I):
                if b:
                    tel = (tel or 0) + b
                continue
            if re.search(r'commuting allowance', desc, re.I):
                if b:
                    trans = (trans or 0) + b
                continue
            if re.search(r'(night|nacht).{0,20}allowance', desc, re.I) or re.search(r'allowance.{0,20}(night|nacht)', desc, re.I):
                if b:
                    night = (night or 0) + b
                continue
            if re.search(r'holiday allowance', desc, re.I) and sec == 'Bruto':
                if b:
                    holiday_alw = (holiday_alw or 0) + b
                continue
            if re.search(r'\b(bonus|commission)\b', desc, re.I):
                if b:
                    bonus = (bonus or 0) + b
                continue
            if re.search(r'severance', desc, re.I):
                if b:
                    severance = (severance or 0) + b
                continue
            if re.search(r'pension', desc, re.I):
                if ih:
                    pension = (pension or 0) + ih
                continue
            if re.search(r'wage tax', desc, re.I):
                if ih:
                    wage_tax = (wage_tax or 0) + ih
                continue
            if ih and sec != 'Netto':
                other_ded = (other_ded or 0) + ih
                continue
            if b and sec in ('Bruto', 'Netto'):
                if re.search(r'allowance|toeslag', desc, re.I):
                    other_allow = (other_allow or 0) + b
                else:
                    other_bruto = (other_bruto or 0) + b
                continue
        bruto_total = ((base_salary or 0) + (tel or 0) + (trans or 0) + (night or 0)
                       + (holiday_alw or 0) + (other_allow or 0) + (bonus or 0)
                       + (severance or 0) + (ot_total or 0) + (other_bruto or 0))
        werk_verz = sum_section_wg(det, 'Werknemer Verzekering')
        zvw = sum_section_wg(det, 'Zvw')
        company_ins = (werk_verz or 0) + (zvw or 0)
        netto = None
        for d in det:
            if re.search(r'\bTotal\s+net\b', d.get('desc', ''), re.I):
                netto = bet_of(d)
                break
        if netto is None and e['meta'].get('per_bank_netto'):
            netto = e['meta']['per_bank_netto']
        if netto is None:
            for d in det:
                if d.get('code') == '9880':
                    netto = bet_of(d)
                    break
        nz = lambda v: v if (isinstance(v, (int, float)) and v != 0) else ''

        vals = [
            idx, e['meta']['name'], e['meta']['pers_nr'], e['meta']['period'],
            bruto_total, nz(base_salary), nz(tel), nz(trans), nz(night), nz(holiday_alw), nz(other_allow),
            nz(bonus), nz(severance), nz(ot_total), nz(other_bruto),
            nz(ot[100][0]), nz(ot[100][1]), nz(ot[100][2]),
            nz(ot[125][0]), nz(ot[125][1]), nz(ot[125][2]),
            nz(ot[150][0]), nz(ot[150][1]), nz(ot[150][2]),
            nz(ph[0]), nz(ph[1]), nz(ph[2]),
            nz(ot[200][0]), nz(ot[200][1]), nz(ot[200][2]),
            nz(ot[250][0]), nz(ot[250][1]), nz(ot[250][2]),
            nz(pension), nz(wage_tax), nz(other_ded), nz(netto),
            nz(company_ins),
            nz(parse_num(s.get('res_res')) if s.get('res_res') else None),
            nz(parse_num(s.get('res_saldo')) if s.get('res_saldo') else None),
            nz(parse_num(e['kosten']) if e['kosten'] else None),
            nz(parse_num(s.get('fiscaal_loon')) if s.get('fiscaal_loon') else None),
            nz(parse_num(s.get('svw_loon')) if s.get('svw_loon') else None),
            s.get('dagen', ''), s.get('uren', ''), s.get('run', ''),
        ]
        for ci, v in enumerate(vals, 1):
            _cell = ws2.cell(row=r, column=ci, value=v)
            _cell.border = border
            _cell.alignment = center
            if ci >= 5 and isinstance(v, (int, float)):
                _cell.number_format = money_fmt
        r += 1

    widths2 = [9, 16, 11, 11, 12, 11, 10, 10, 10, 10, 10, 9, 11, 11, 10,
               9, 9, 10, 9, 9, 10, 9, 9, 10, 9, 9, 10, 9, 9, 10, 9, 9, 10,
               10, 10, 10, 12, 11, 11, 11, 11, 11, 11, 11, 10, 10, 9]
    for i, w in enumerate(widths2, 1):
        if i <= ncols:
            ws2.column_dimensions[get_column_letter(i)].width = w
    ws2.freeze_panes = 'E3'
    if r > 3:
        ws2.auto_filter.ref = 'A1:%s%d' % (get_column_letter(ncols), r - 1)

    buf = io.BytesIO()
    wb.save(buf)
    wb_bytes = buf.getvalue()
    return wb_bytes, {
        'num_employees': len(employees),
        'num_detail': sum(len(e['detail']) for e in employees),
    }


if __name__ == '__main__':
    import sys as _s
    if len(_s.argv) > 1:
        b, info = run(_s.argv[1])
        out = _s.argv[1].rsplit('.', 1)[0] + '_dutch.xlsx'
        with open(out, 'wb') as f:
            f.write(b)
        print('saved', out, info)

"""
美国 Humana 医疗/牙科眼科账单 Employee Detail 提取工具 (网页平台复用版)

取文本优先用 PyMuPDF(fitz) —— 部分月份的 Humana PDF（如 202607）pdfplumber 只能读出
2 页乱码、且文本整行逆序，fitz 可完整正常提取 8 页。单行式布局(pdfplumber 风格)
与竖排分行式布局(fitz 风格，MemberID/Plan/Name/Coverage/金额各占一行) 均兼容。

输出模型: 每行 = 员工 × 计划(Plan) × 月份(Period)，即
  MemberName | MemberID | Plan | Coverage | Period | Adjustment | Premium

关键结构 (以 202606 / 202607 Humana 账单为例):
  - "Employee Detail:" 起 (通常第 4 页), 后续页为 "(Continued)" 续页
  - 竖排分行布局: 每条计划记录 = [MemberID 行][Plan 行][Name 行(仅该员工首条有)][Coverage 行][$金额 行]
    块末以 "EmployeeTotal $X" 结束；同一员工可有多条计划(如 DTP + VIS)，第二条起 Name 行省略
  - 单行布局(旧 pdfplumber 风格): 一行内 "MemberID PlanType Coverage $金额"
  - 前缀行 PRICING ADJUSTMENT / NEW ENROLLMENT / TERMINATION 后跟 ": MM/DD/YYYY" 表示回溯月份
    (实际 PDF 文本 "NEW ENROLLMENT" 中间有空格、冒号后也有空格，解析已容错)；
    前缀行本身不含数据，仅标记其后记录的月份与调整类型，该行 Period 取前缀月份。
  - 无前缀的行归属账单当期(bill_month)；若连 bill_month 都无法取得则 Period 留空，绝不捏造月份。
  - 账单 "Group Summary" 页有 "Premiums by Plan Type" 表(竖排)，给出 DHP/DTP/VIS 的计划合计
    (仅当期无调整行计入，与账单同口径；回溯调整行 Adjustment 非空，不计入计划合计验算)

输出 Excel (write_excel, 3 个 sheet):
  - Details: 逐行明细 (MemberName/MemberID/Plan/Coverage/Period/Adjustment/Premium)
  - 员工合计: 按 (MemberName, 月份) 逐人×月展开，列 MemberName|月份|DHP+DTP|VIS|总计；
              同人每月一行，多人多行，月份不可识别留空。
  - 计划合计: DHP/DTP/VIS 当期提取小计 vs 账单计划合计 (差异标红)

对外暴露:
  extract_details(pdf_path) -> (rows, verify_info)
  write_excel(rows, output_path, verify_info=None) -> None
依赖: PyMuPDF(fitz, 优先) 或 pdfplumber(兜底), openpyxl
"""
import re
import os
import openpyxl
from openpyxl.utils import get_column_letter
from openpyxl.styles import Font

try:
    import fitz  # PyMuPDF
    _HAVE_FITZ = True
except Exception:
    fitz = None
    _HAVE_FITZ = False
try:
    import pdfplumber
    _HAVE_PDFPLUMBER = True
except Exception:
    pdfplumber = None
    _HAVE_PDFPLUMBER = False


def _get_pages(pdf_path):
    """返回 [[line, ...], ...] 每页的文本行列表。优先 fitz，失败回退 pdfplumber。"""
    if _HAVE_FITZ:
        try:
            doc = fitz.open(pdf_path)
            pages = [ (doc[i].get_text() or '').split('\n') for i in range(doc.page_count) ]
            doc.close()
            if pages:
                return pages
        except Exception:
            pass
    if _HAVE_PDFPLUMBER:
        try:
            with pdfplumber.open(pdf_path) as pdf:
                return [ (p.extract_text() or '').split('\n') for p in pdf.pages ]
        except Exception:
            pass
    return []

MONTHS = {
    'JANUARY': 1, 'FEBRUARY': 2, 'MARCH': 3, 'APRIL': 4, 'MAY': 5, 'JUNE': 6,
    'JULY': 7, 'AUGUST': 8, 'SEPTEMBER': 9, 'OCTOBER': 10, 'NOVEMBER': 11, 'DECEMBER': 12,
}


def parse_amount(s):
    """解析金额: $1,234.56 / -$123.45 / ($123.45)"""
    if not s:
        return 0.0
    s = s.replace(',', '').replace(' ', '')
    neg = False
    if s.startswith('(') and s.endswith(')'):
        neg = True
        s = s[1:-1]
    if s.startswith('-'):
        neg = True
        s = s[1:]
    s = s.replace('$', '')
    try:
        v = float(s)
        return -v if neg else v
    except Exception:
        return 0.0


def parse_data_line(text, employee, period, adj):
    """解析一行 plan 明细: MemberID PlanType Coverage $金额
    返回 dict 或 None。"""
    mid = re.search(r'(?<!\d)(\d{6,10})(?!\d)', text)
    plan = re.search(r'\b(DHP|DTP|VIS)\b', text)
    cov = re.search(r'\b(EMP|ESP|ECH|FAM)\b', text)
    ams = re.findall(r'(-?\$[\d,]+\.\d{2}|\(\$[\d,]+\.\d{2}\))', text)
    if not (mid and plan and ams):
        return None
    return {
        'MemberName': employee or '',
        'MemberID': mid.group(1),
        'Plan': plan.group(1),
        'Coverage': cov.group(1) if cov else '',
        'Period': period,
        'Adjustment': adj,
        'Premium': parse_amount(ams[-1]),
    }


def _classify(line):
    """竖排分词: 返回 (类别, 值)。类别: name/plan/cov/mid/amt/other。"""
    s = line.strip()
    m = re.match(r"^([A-Z][A-Z.'-]+),\s*([A-Z][A-Z.'-]+(?:\s+[A-Z][A-Z.'-]+)?)", s)
    if m:
        return ('name', f"{m.group(1)}, {m.group(2)}")
    if re.match(r"^(DHP|DTP|VIS)$", s):
        return ('plan', s)
    if re.match(r"^(EMP|ESP|ECH|FAM)$", s):
        return ('cov', s)
    if re.match(r"^\d{6,10}$", s):
        return ('mid', s)
    am = re.match(r"^(\(\$[\d,]+\.\d{2}\)|-?\$[\d,]+\.\d{2})$", s)
    if am:
        return ('amt', parse_amount(s))
    return ('other', s)


def _extract_plan_bills(all_lines):
    """从 Group Summary 的 'Premiums by Plan Type' 区块(竖排)提取 DHP/DTP/VIS 计划合计。
    每个计划头之后跟若干 $金额, 取最后一个作为该计划合计(=Total 列)。
    注意: 该区块开头有一行列标题 'Total', 须与结尾的汇总行 'Total' 区分——只在已进入
    计划数据(seen_plans)后才把 'Total' 当作区块结束符。"""
    start = None
    for i, ln in enumerate(all_lines):
        if 'premiums by plan type' in ln.lower():
            start = i
            break
    if start is None:
        return {}
    bills = {}
    cur_plan = None
    cur_amts = []
    seen_plans = False
    for ln in all_lines[start + 1:]:
        s = ln.strip()
        if re.match(r'^(DHP|DTP|VIS)$', s):
            if cur_plan is not None and cur_amts:
                bills[cur_plan] = cur_amts[-1]
            cur_plan = s
            cur_amts = []
            seen_plans = True
            continue
        if s.lower() == 'total':
            if seen_plans:
                if cur_plan is not None and cur_amts:
                    bills[cur_plan] = cur_amts[-1]
                break
            continue  # 列标题 'Total', 跳过
        am = re.match(r'^(\(\$[\d,]+\.\d{2}\)|-?\$[\d,]+\.\d{2})$', s)
        if am and cur_plan is not None:
            cur_amts.append(parse_amount(s))
    if cur_plan is not None and cur_amts and cur_plan not in bills:
        bills[cur_plan] = cur_amts[-1]
    return bills


def extract_details(pdf_path):
    """提取 Employee Detail 明细, 返回 (rows, verify_info)。

    rows: list[dict], 每行 = 员工×计划×月份 展开。
    verify_info: 逐员工(EmployeeTotal) + 计划级(Group Summary) 双验算结果。
    文本来源优先 PyMuPDF(fitz)，兼容竖排分行与单行两种布局。
    """
    rows = []
    employees = []          # 逐员工验算
    plan_bills = {}         # 账单 Group Summary 计划合计
    bill_month = ''

    pages = _get_pages(pdf_path)
    if not pages:
        return rows, {
            'bill_month': bill_month, 'employees': employees, 'plan_totals': {},
            'plan_total_found': False, 'n_rows': 0, 'issues': ['无法读取 PDF 页面'],
            'passed': False,
        }

    flat = [ln for pg in pages for ln in pg]

    # 账单月份 (封面 "For coverage in July 2026")
    for ln in flat:
        m = re.search(r'coverage in ([A-Za-z]+)\s+(\d{4})', ln, re.I)
        if m and MONTHS.get(m.group(1).upper()):
            bill_month = f"{m.group(2)}-{MONTHS[m.group(1).upper()]:02d}"
            break

    # 计划级合计 (Group Summary "Premiums by Plan Type", 竖排)
    plan_bills = _extract_plan_bills(flat)

    # ---- 明细流式解析 (跨页连续) ----
    current_employee = None
    current_block = []
    pending = {'mid': None, 'plan': None, 'cov': '', 'adj': '', 'period': bill_month}

    def add_row(d):
        if not d or not current_employee:
            return
        rows.append(d)
        current_block.append(d)

    def flush_pending(amount):
        if pending.get('mid') and pending.get('plan'):
            add_row({
                'MemberName': current_employee or '',
                'MemberID': pending['mid'],
                'Plan': pending['plan'],
                'Coverage': pending.get('cov', ''),
                'Period': pending.get('period', bill_month),
                'Adjustment': pending.get('adj', ''),
                'Premium': amount,
            })
        pending['mid'] = None
        pending['plan'] = None
        pending['cov'] = ''
        pending['adj'] = ''
        pending['period'] = bill_month

    in_detail = False
    et_pending = False  # "Employee Total" 已出现, 等待下一行金额

    def close_employee(amt_str):
        nonlocal current_employee, current_block
        if current_employee and current_block:
            s = sum(r['Premium'] for r in current_block)
            bill = amt_str if isinstance(amt_str, (int, float)) else parse_amount(amt_str)
            diff = round(s - bill, 2)
            employees.append({
                'name': current_employee,
                'extracted': round(s, 2),
                'bill': bill,
                'diff': diff,
                'ok': abs(diff) <= 0.01,
            })
        current_employee = None
        current_block = []

    for pg in pages:
        for raw in pg:
            line = raw.strip()
            if not line:
                continue
            low = line.lower()

            if not in_detail:
                if 'employee detail' in low:
                    in_detail = True
                continue

            # 跳过页眉/页脚/表头
            if any(k in low for k in ['membername', 'plantype', 'billingid', 'yunexpress',
                                      'questions about', "don't forget", 'employee detail']):
                continue
            if re.match(r'^Page\s+\d+\s+of\s+\d+', line):
                continue
            if low in ('premium', 'memberid total'):
                continue

            # 员工块结束: "Employee Total" [可选同行金额] (fitz 竖排时金额在下一行)
            m_et = re.match(r'Employee\s*Total\s*(?:(\$?-?[\d,]+\.\d{2}|\(\$[\d,]+\.\d{2}\)))?', line, re.I)
            if m_et:
                et_amt = m_et.group(1)
                if et_amt:
                    close_employee(et_amt)
                    flush_pending(0.0)
                else:
                    et_pending = True
                continue

            # 带月份前缀的标记行 (PRICING ADJUSTMENT / NEW ENROLLMENT / TERMINATION: MM/DD/YYYY)
            # 前缀行本身不含数据, 仅标记其后记录的回溯月份与调整类型。
            # 注意: 实际 PDF 文本 "NEW ENROLLMENT" 中间有空格、冒号后也有空格, 须容错。
            m_pre = re.match(r'(PRICING\s*ADJUSTMENT|NEW\s*ENROLLMENT|TERMINATION)\s*:\s*(\d{2})/(\d{2})/(\d{4})', line, re.I)
            if m_pre:
                pending['adj'] = m_pre.group(1).upper().replace(' ', '')
                pending['period'] = f"{m_pre.group(4)}-{m_pre.group(2)}"
                continue

            # 单行数据 (pdfplumber 风格): 同一行含 mid+plan+amt
            single = parse_data_line(line, current_employee, bill_month, '')
            if single:
                flush_pending(0.0)
                add_row(single)
                continue

            # 竖排分词装配
            cm = _classify(line)
            if cm[0] == 'name':
                current_employee = cm[1]
                current_block = []
                # 注意: 不清 pending, 该员工的 mid/plan 已在前面两行就位
                continue
            if cm[0] == 'plan':
                pending['plan'] = cm[1]
                continue
            if cm[0] == 'mid':
                pending['mid'] = cm[1]
                continue
            if cm[0] == 'cov':
                pending['cov'] = cm[1]
                continue
            if cm[0] == 'amt':
                if et_pending:
                    et_pending = False
                    close_employee(cm[1])
                    pending['mid'] = None
                    pending['plan'] = None
                    pending['cov'] = ''
                    pending['adj'] = ''
                    pending['period'] = bill_month
                    continue
                flush_pending(cm[1])
                continue
            # 其他(表头词等)忽略

    # ---- 计划级验算 (仅本期正常保费, 与 Group Summary 同口径; 回溯调整行不计入) ----
    current_plan = {}
    for r in rows:
        if r['Adjustment'] == '':
            current_plan[r['Plan']] = current_plan.get(r['Plan'], 0.0) + r['Premium']
    plan_totals = {}
    plan_total_found = len(plan_bills) > 0
    for plan, bill in plan_bills.items():
        s = current_plan.get(plan, 0.0)
        diff = round(s - bill, 2)
        plan_totals[plan] = {
            'extracted': round(s, 2), 'bill': bill,
            'diff': diff, 'ok': abs(diff) <= 0.01,
        }

    # ---- 组装验算信息 ----
    issues = []
    for e in employees:
        if not e['ok']:
            issues.append(f"员工 {e['name']}: 提取 {e['extracted']:.2f} vs 账单 {e['bill']:.2f} 差 {e['diff']:+.2f}")
    for p, d in plan_totals.items():
        if not d['ok']:
            issues.append(f"计划 {p}: 提取 {d['extracted']:.2f} vs 账单 {d['bill']:.2f} 差 {d['diff']:+.2f}")

    verify_info = {
        'bill_month': bill_month,
        'employees': employees,
        'plan_totals': plan_totals,
        'plan_total_found': plan_total_found,
        'n_rows': len(rows),
        'issues': issues,
        'passed': len(issues) == 0,
    }
    return rows, verify_info


def _norm_name(name):
    return (name or '').strip() or '(未命名)'


def build_employee_monthly(rows, verify_info=None):
    """按 (MemberName, 月份Period) 聚合, 供「员工合计」sheet 使用。

    返回 (monthly_rows, name_totals):
      monthly_rows: 按 name 分组、组内按 Period 升序(空月份排最后)的逐人×月行:
                    {MemberName, Period, DHP+DTP, VIS, 总计}
      name_totals:  {name: {dhpdtp, vis, total, bill, diff, ok}} 保留给需要员工级对账的调用方。

    规则:
      - 同一人同一月的多条计划(DHP/DTP/VIS)合并: DHP/DTP 保费入同一列, VIS 单列, 总计=两者之和
      - Period 为空(无法识别月份)时如实留空, 不捏造月份
    """
    agg = {}            # (name, period) -> {dhpdtp, vis}
    name_order = []
    period_order = {}   # name -> [period, ...] (保持出现顺序)

    for r in rows:
        name = _norm_name(r.get('MemberName'))
        period = (r.get('Period') or '').strip()
        key = (name, period)
        if name not in name_order:
            name_order.append(name)
        if key not in agg:
            agg[key] = {'dhpdtp': 0.0, 'vis': 0.0}
            period_order.setdefault(name, [])
            if period not in period_order[name]:
                period_order[name].append(period)
        plan = (r.get('Plan') or '').strip().upper()
        prem = r.get('Premium', 0.0) or 0.0
        if plan in ('DHP', 'DTP'):
            agg[key]['dhpdtp'] += prem
        elif plan == 'VIS':
            agg[key]['vis'] += prem

    def period_sort_key(p):
        # 空月份排最后, 非空按 'YYYY-MM' 字符串升序
        return ('',) if not p else (p,)

    monthly = []
    name_totals = {}
    for name in name_order:
        periods = sorted(period_order[name], key=period_sort_key)
        nt = {'dhpdtp': 0.0, 'vis': 0.0, 'total': 0.0, 'bill': None, 'diff': None, 'ok': True}
        for p in periods:
            d = agg[(name, p)]
            dhpdtp = round(d['dhpdtp'], 2)
            vis = round(d['vis'], 2)
            total = round(dhpdtp + vis, 2)
            monthly.append({'MemberName': name, 'Period': p,
                            'DHP+DTP': dhpdtp, 'VIS': vis, '总计': total})
            nt['dhpdtp'] += dhpdtp
            nt['vis'] += vis
            nt['total'] += total
        nt['dhpdtp'] = round(nt['dhpdtp'], 2)
        nt['vis'] = round(nt['vis'], 2)
        nt['total'] = round(nt['total'], 2)
        # 对齐账单 EmployeeTotal
        if verify_info:
            for e in verify_info.get('employees', []):
                if e['name'] == name:
                    nt['bill'] = e['bill']
                    nt['diff'] = round(nt['total'] - e['bill'], 2)
                    nt['ok'] = abs(nt['diff']) <= 0.01
                    break
        name_totals[name] = nt

    return monthly, name_totals


def write_excel(rows, output_path, verify_info=None):
    """写出明细 + (验算信息存在时) 员工合计/计划合计两个 sheet。"""
    if not rows:
        raise ValueError("无数据可写出")

    wb = openpyxl.Workbook()

    # ---- 主表: 明细 ----
    ws = wb.active
    ws.title = "Details"
    headers = ['MemberName', 'MemberID', 'Plan', 'Coverage', 'Period', 'Adjustment', 'Premium']
    ws.append(headers)
    for r in rows:
        ws.append([r.get(h, '') for h in headers])
    for ri in range(2, len(rows) + 2):
        c = ws[f'G{ri}']
        c.number_format = '#,##0.00;[Red]-#,##0.00'
        if isinstance(c.value, (int, float)) and c.value < 0:
            c.font = Font(color='FF0000')
    for i, w in enumerate([22, 12, 8, 10, 10, 18, 12], 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{len(rows) + 1}"

    # ---- 员工合计 sheet (按人×月展开，只保留 DHP+DTP/VIS/总计 三列金额) ----
    if rows:
        monthly, _ = build_employee_monthly(rows, verify_info)
        wse = wb.create_sheet("员工合计")
        wse.append(['MemberName', '月份', 'DHP+DTP', 'VIS', '总计'])
        for mr in monthly:
            wse.append([mr['MemberName'], mr['Period'], mr['DHP+DTP'], mr['VIS'], mr['总计']])
            rr = wse.max_row
            for col in ('C', 'D', 'E'):
                cell = wse[f'{col}{rr}']
                cell.number_format = '#,##0.00;[Red]-#,##0.00'
                if isinstance(cell.value, (int, float)) and cell.value < 0:
                    cell.font = Font(color='FF0000')
        for i, w in enumerate([22, 10, 14, 12, 14], 1):
            wse.column_dimensions[get_column_letter(i)].width = w
        wse.freeze_panes = "A2"

    # ---- 计划合计 sheet ----
    if verify_info and verify_info.get('plan_totals'):
        wsp = wb.create_sheet("计划合计")
        wsp.append(['Plan', '提取小计', '账单计划合计', '差异', '状态'])
        for plan, d in verify_info['plan_totals'].items():
            wsp.append([plan, d['extracted'], d['bill'], d['diff'], 'OK' if d['ok'] else '差异'])
            rr = wsp.max_row
            if not d['ok']:
                for col in ('C', 'D', 'E'):
                    wsp[f'{col}{rr}'].font = Font(color='FF0000')
        for i, w in enumerate([10, 14, 16, 12, 10], 1):
            wsp.column_dimensions[get_column_letter(i)].width = w
        for ri in range(2, wsp.max_row + 1):
            for col in ('B', 'C', 'D'):
                wsp[f'{col}{ri}'].number_format = '#,##0.00;[Red]-#,##0.00'

    # ---- 数据说明 sheet (动态: 依据本次验算结果 + 稳定口径说明, 避免硬编码过时文案) ----
    wsn = wb.create_sheet("数据说明")
    wsn.append(['Humana 医疗账单提取 · 数据说明'])
    wsn.append([''])
    wsn.append(['一、本次验算结果'])
    if verify_info and verify_info.get('issues'):
        wsn.append(['未通过：发现 %d 处差异，请逐项核对：' % len(verify_info['issues'])])
        for it in verify_info['issues']:
            wsn.append(['  - ' + it])
    elif verify_info:
        wsn.append(['全部通过（明细 %d 行，%d 名员工）' % (
            verify_info.get('n_rows', 0), len(verify_info.get('employees', [])))])
    else:
        wsn.append(['（无验算信息）'])
    wsn.append([''])
    wsn.append(['二、口径与已知边界'])
    _notes = [
        'DHP 与 DTP 合并计入「DHP+DTP」列；VIS 单列；总计 = DHP+DTP + VIS。',
        '回溯调整行（Adjustment 不为空）不计入计划合计验算，仅取当期正常保费。',
        '月份取自 PDF 内 NEW ENROLLMENT / TERMINATION / PRICING ADJUSTMENT 前缀行；无法识别时留空，绝不捏造。',
        'Premium 为负数（调整/退款）时按原值计入对应列。',
        '计划合计仅对比「当期无调整」提取小计与账单 Group Summary 的 Premiums by Plan Type；两者因回溯调整存在差异属预期，非数据错误。',
    ]
    for n in _notes:
        wsn.append(['  - ' + n])
    wsn.column_dimensions['A'].width = 90
    wsn['A1'].font = Font(bold=True)
    wsn['A3'].font = Font(bold=True)
    wsn['A6'].font = Font(bold=True)

    wb.save(output_path)


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print("用法: python humana_details_extract.py <PDF文件路径>")
        sys.exit(1)
    pdf_path = sys.argv[1]
    rows, verify_info = extract_details(pdf_path)
    if not rows:
        print("未提取到任何数据行")
        sys.exit(1)
    out_path = os.path.splitext(pdf_path)[0] + '_Details.xlsx'
    write_excel(rows, out_path, verify_info)
    print(f"已导出: {out_path}  ({len(rows)} 行)")
    print(f"账单月份: {verify_info['bill_month']}  验算: {'通过' if verify_info['passed'] else '差异' + str(verify_info['issues'])}")

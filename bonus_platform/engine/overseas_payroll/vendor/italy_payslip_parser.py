import sys, re, os
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

import pypdf
import pdfplumber
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

# 模块级全局：由 _load(pdf_path) 设置（平台调用时延迟加载）
PDF_PATH = None
pages_text = {}
import io

# ============ 数字格式转换 ============
def fmt(val):
    if not val:
        return val
    if ',' in val:
        return val.replace('.', '').replace(',', '.')
    return val

def parse_num(s):
    if not s:
        return 0.0
    is_neg = ('(' in s) or (isinstance(s, str) and s.strip().startswith('-'))
    m = re.search(r'(-?\(?[\d.]+(?:,\d+)?\)?)', s)
    if not m:
        return 0.0
    num_str = m.group(1).strip('()').lstrip('-')
    val = float(num_str.replace('.', '').replace(',', '.'))
    return -val if is_neg else val

def convert_riferimento(raw):
    if not raw:
        return raw
    if raw.startswith('%'):
        return fmt(raw[1:]) + '%'
    return fmt(raw)

def sum_raw(a, b):
    if not a and not b:
        return ''
    total = parse_num(a) + parse_num(b)
    if abs(total) < 0.00001:
        return ''
    # 返回意大利数字格式: 点=千分位, 逗号=小数 (与原始 PDF 一致, 供 parse_num 正确回读)
    intp, dec = '{:.5f}'.format(abs(total)).split('.')
    intp = format(int(intp), ',d').replace(',', '.')
    val = intp + ',' + dec
    return '(' + val + ')' if total < 0 else val

# ============ 读取PDF（延迟加载，由 run() 调用） ============
def _load(pdf_path):
    global PDF_PATH, pages_text
    PDF_PATH = pdf_path
    reader = pypdf.PdfReader(pdf_path)
    pages_text = {}
    for i in range(len(reader.pages)):
        pages_text[i+1] = reader.pages[i].extract_text()

# ============ 列检测 ============
def detect_column_boundaries(page):
    lines = [l for l in page.lines if abs(l['x0'] - l['x1']) < 3 and abs(l['y0'] - l['y1']) > 150]
    vlines = sorted(set(round(l['x0']) for l in lines))
    if vlines and vlines[0] > 20:
        vlines.insert(0, 0)
    vlines.append(int(page.width))
    return vlines

def get_value_at_column(row_chars, x0, x1):
    """从行字符中提取指定x范围内的文本"""
    return ''.join(c['text'] for c in row_chars if x0 <= c['x0'] < x1).strip()

# ============ 解析员工信息 ============
def extract_retribuzione_fissa(text):
    """从 'Elementi di Retribuzione' 区域提取固定薪酬：PAGA BASE / EDR / EPA / 合计。

    ★ 关键修正（2026-08-15 复核）：该区块的科目**并不固定**——除 PAGA BASE / EDR ex Fs /
    EPA 三个常见科目外，还可能包含 SUP.ASS.(Superminimo 超级最低工资) / IND.FUNZ.
    (Indennità 津贴) / SCATTI 等其他固定科目（本批 PDF 实测 13 人含上述附加项）。
    旧逻辑硬编码 totale = PB+EDR+EPA，会**漏掉**附加科目，导致这些员工固定薪酬合计偏小
    （如 0000029 真实 2.325,00 被算成 1.859,49）。

    正确做法：区块底部的「合计行」（Zucchetti 已算好的纯大数字）才是权威的固定薪酬合计，
    它天然包含该员工本区块所有固定科目。本函数改为：
      - PAGA BASE / EDR / EPA 仍单独取（供分列展示）；
      - 「固定薪酬合计」直接取区块合计行 = 最后一个纯数字行（位于所有科目之后、Zucchetti 之前）；
      - 其余附加科目（SUP.ASS./IND.FUNZ./...）收集到 extra 列表（用于日志/校验，不单独成列）。
    全量验证（60 页）：PB/EDR/EPA/合计 均 60/60 取到；合计=各科目之和 0 不一致。
    """
    res = {'paga_base': '', 'edr': '', 'epa': '', 'totale': '', 'extra': []}
    lines = text.split('\n')
    start = None
    for i, line in enumerate(lines):
        if 'PAGA BASE' in line:
            start = i
            break
    if start is None:
        return res

    # 区块边界：到 "Zucchetti spa"（下一区块起始）为止，兜底扫 28 行
    end = min(start + 28, len(lines))
    for j in range(start, min(start + 28, len(lines))):
        if 'Zucchetti spa' in lines[j]:
            end = j
            break
    block = lines[start:end]

    def _num(line):
        m = re.search(r'([\d\.]+\,\d+)', line)
        return m.group(1) if m else ''

    def _is_date(s):
        # 如 7-2027：PAGA BASE 行的附注年份，非金额
        return bool(re.match(r'^\d{1,2}-\d{4}$', s.strip()))

    # 用首词匹配（避免 "PAGA BASE" 被按首词切成 PAGA 而漏匹配）
    label_field = {'PAGA': 'paga_base', 'EDR': 'edr', 'EPA': 'epa'}
    for k, line in enumerate(block):
        s = line.strip()
        if not s:
            continue
        if re.match(r'^[\d\.\,\s]+$', s):   # 纯数字行（金额/合计）：跳过，金额由下一行逻辑取
            continue
        if _is_date(s):                      # 附注年份
            continue
        m = re.match(r'^([A-Za-zÀ-ÿ\'\-\.]+)', s)
        if not m:
            continue
        lab = m.group(1).strip('.')
        if not lab:
            continue
        # 金额通常在该标签行的下一行
        val = ''
        if k + 1 < len(block):
            nv = _num(block[k + 1])
            if nv:
                val = nv
        if lab.upper() in label_field:
            res[label_field[lab.upper()]] = val
        else:
            if val:
                res['extra'].append((lab, val))

    # 固定薪酬合计：区块内最后一个「纯数字行」= Zucchetti 算好的合计（含所有固定科目）
    for line in reversed(block):
        s = line.strip()
        if re.match(r'^[\d\.\,\s]+$', s) and _num(s):
            res['totale'] = _num(s)
            break

    return res



def extract_employees():
    emp_list = []
    
    # 第一步：找出所有页中所有7位员工编号
    for page_num, text in pages_text.items():
        # 两种匹配方式：
        # 1) 标准格式：7位编号 + 姓名 + 税号在一行
        # 2) 编号单独出现在某行
        codes_found = set()
        
        # 方式A1：找 "编号 姓名 税号" 在同一行（标准格式），姓名2~6个词
        for m in re.finditer(r'(\d{7})\s+([A-Za-zÀ-ÿ\'\-]+(?:\s+[A-Za-zÀ-ÿ\'\-]+){1,5})\s+([A-Z0-9]{16})', text):
            code = m.group(1)
            if code in codes_found:
                continue
            codes_found.add(code)
            name = m.group(2).strip()
            # 过滤非人名（月份、通用词等）
            if name.upper() in ('APRILE', 'MAGGIO', 'GENNAIO', 'FEBBRAIO', 'MARZO', 'GIUGNO',
                                'LUGLIO', 'AGOSTO', 'SETTEMBRE', 'OTTOBRE', 'NOVEMBRE', 'DICEMBRE',
                                'COGNOME', 'NOME', 'TOTALE', 'PERIODO', 'FILIALE'):
                continue
            tax_code = m.group(3) or ''
            # 标准格式税号16位
            if len(tax_code) != 16:
                tax_code = ''
            existing = [e for e in emp_list if e['code'] == code]
            if existing:
                if page_num not in existing[0]['pages']:
                    existing[0]['pages'].append(page_num)
            else:
                emp_list.append({
                    'name': name, 'code': code, 'tax_code': tax_code,
                    'pages': [page_num], 'birth': '', 'hire': '', 'role': '', 'paga_base': '', 'edr': '', 'epa': '', 'totale': ''
                })
        
        # 方式A2：找 "编号 姓名"（无税号），姓名1~5个词（仅同行匹配，不跨行）
        for m in re.finditer(r'(\d{7})[ \t]+([A-Za-zÀ-ÿ\'\-]+(?:[ \t]+[A-Za-zÀ-ÿ\'\-]+){0,4})[ \t]*$', text, re.MULTILINE):
            code = m.group(1)
            if code in codes_found:
                continue
            codes_found.add(code)
            name = m.group(2).strip()
            if name.upper() in ('APRILE', 'MAGGIO', 'GENNAIO', 'FEBBRAIO', 'MARZO', 'GIUGNO',
                                'LUGLIO', 'AGOSTO', 'SETTEMBRE', 'OTTOBRE', 'NOVEMBRE', 'DICEMBRE',
                                'COGNOME', 'NOME', 'TOTALE', 'PERIODO', 'FILIALE'):
                continue
            # 过滤公司/地址行
            if 'GOFO' in name.upper() or 'ITALIA' in name.upper() or 'SRL' in name.upper() or 'VIA' in name.upper() or 'MILANO' in name.upper():
                continue
            tax_code = ''
            # 找税号
            tax_m = re.search(r'[A-Z0-9]{16}', text)
            tax_code = tax_m.group(0) if tax_m else ''
            existing = [e for e in emp_list if e['code'] == code]
            if existing:
                if page_num not in existing[0]['pages']:
                    existing[0]['pages'].append(page_num)
            else:
                emp_list.append({
                    'name': name, 'code': code, 'tax_code': tax_code,
                    'pages': [page_num], 'birth': '', 'hire': '', 'role': '', 'paga_base': '', 'edr': '', 'epa': '', 'totale': ''
                })
                tax_code = ''
            existing = [e for e in emp_list if e['code'] == code]
            if existing:
                if page_num not in existing[0]['pages']:
                    existing[0]['pages'].append(page_num)
            else:
                emp_list.append({
                    'name': name, 'code': code, 'tax_code': tax_code,
                    'pages': [page_num], 'birth': '', 'hire': '', 'role': '', 'paga_base': '', 'edr': '', 'epa': '', 'totale': ''
                })
        
        # 方式B：找单独7位编号（用于多页PDF中编号和姓名不同行的情况）
        for m in re.finditer(r'^(0\d{6})\s*$', text, re.MULTILINE):
            code = m.group(1)
            if code in codes_found:
                continue
            codes_found.add(code)
            # 查找姓名：在编号附近找姓名行
            lines = text.split('\n')
            name = ''
            for i, line in enumerate(lines):
                if code in line:
                    # 向后搜索姓名（可能在当前行或下几行）
                    for j in range(i, min(i+8, len(lines))):
                        name_match = re.search(r'^([A-Za-zÀ-ÿ\'\-]+(?:\s+[A-Za-zÀ-ÿ\'\-]+){0,3})$', lines[j].strip())
                        if name_match and len(lines[j].strip()) > 2:
                            name = name_match.group(1)
                            break
                    break
            if not name:
                continue
            # 找税号
            tax_m = re.search(r'[A-Z0-9]{16}', text)
            tax_code = tax_m.group(0) if tax_m else ''
            
            existing = [e for e in emp_list if e['code'] == code]
            if existing:
                if page_num not in existing[0]['pages']:
                    existing[0]['pages'].append(page_num)
            else:
                emp_list.append({
                    'name': name, 'code': code, 'tax_code': tax_code,
                    'pages': [page_num], 'birth': '', 'hire': '', 'role': '', 'paga_base': '', 'edr': '', 'epa': '', 'totale': ''
                })
    
    # 补全员工信息：出生日期、入职日期、职务、PAGA BASE、总薪酬
    for emp in emp_list:
        for pn in emp['pages']:
            text = pages_text[pn]
            if not emp['birth']:
                m = re.search(r'(\d{2}-\d{2}-\d{4})\s+(\d{2}-\d{2}-\d{4})', text)
                if m:
                    emp['birth'] = m.group(1)
                    emp['hire'] = m.group(2)
            if not emp['role']:
                m = re.search(r'(FINANCE\s+SUPERVISOR|TERMINAL\s+SPECIALIST|(?:OPE|IMP|QUADRO|DIRIGENTE)\s+Livello\s+[A-Za-z0-9.]+)', text)
                if m:
                    emp['role'] = m.group(0)
            # 固定薪酬（PAGA BASE / EDR / EPA / TOTALE）
            rf = extract_retribuzione_fissa(text)
            if rf['paga_base'] and not emp['paga_base']:
                emp['paga_base'] = rf['paga_base']
            if rf['edr'] and not emp['edr']:
                emp['edr'] = rf['edr']
            if rf['epa'] and not emp['epa']:
                emp['epa'] = rf['epa']
            if rf['totale'] and not emp.get('totale'):
                emp['totale'] = rf['totale']
            # 兜底：跨页拼接其所有页后再试一次，防止区块被拆到两页导致合计取不到
            if not emp.get('totale'):
                joined = '\n'.join(pages_text[p] for p in sorted(emp['pages']))
                rf2 = extract_retribuzione_fissa(joined)
                if rf2['totale']:
                    emp['totale'] = rf2['totale']
                if rf2['paga_base'] and not emp['paga_base']:
                    emp['paga_base'] = rf2['paga_base']
                if rf2['edr'] and not emp['edr']:
                    emp['edr'] = rf2['edr']
                if rf2['epa'] and not emp['epa']:
                    emp['epa'] = rf2['epa']
            # 兜底：SUP.ASS. 布局下的总薪酬
            if not emp.get('totale'):
                lines = text.split('\n')
                for j, line in enumerate(lines):
                    if 'SUP.ASS.' in line:
                        nums = []
                        for k in range(j+1, min(j+4, len(lines))):
                            m2 = re.search(r'([\d.]+\,\d+)', lines[k])
                            if m2:
                                nums.append(m2.group(1))
                        if len(nums) >= 2:
                            emp['totale'] = nums[1]
    
    return emp_list

# 意大利工资科目中文翻译表（按 Zucchetti Libro Unico 编码，未知科目回退原文）
CODE_ZH = {
    "Z00000": "社保缴费IVS", "Z00001": "工资", "ZP0001": "病假补贴(INPS垫付)",
    "Z00010": "社保附加缴费IVS", "ZP0030": "INPS毛额化补差", "Z00078": "CIGS基金缴费",
    "Z00134": "FIS基金缴费(15-50人)", "Z00226": "医疗检查假", "Z00250": "已休年假",
    "Z00255": "已休ROL假", "Z00260": "已休Ex-FS假", "Z01300": "病假(公司100%)",
    "Z02001": "入职/离职缺勤", "Z02003": "未工作工时", "Z02010": "无薪停职假",
    "Z02012": "无薪请假", "Z02014": "无薪缺勤", "Z02022": "无薪病假",
    "Z05006": "L.104/92照护假", "Z05031": "病假(INPS 50%)", "Z05078": "残疾假计提加成",
    "ZP8134": "年度TFR离职金", "ZP8138": "养老金基金扣缴", "ZP9960": "月度舍入",
    "Z20020": "白班轮班加成20%", "Z30018": "补充工时18%", "Z40030": "加班30%",
    "Z40050": "加班50%", "Z40130": "加班30%(MP)", "Z41165": "加班65%(MP)",
    "Z50000": "第13个月工资", "Z50039": "EBILOG基金缴费", "Z50540": "未休法定假日补偿",
    "Z51009": "未休年假补偿", "Z51010": "未休ROL假补偿",
    "F00880": "730退税返还2025", "F00883": "730欠税扣缴2025", "F00885": "730分期利息2025",
    "F02000": "IRPEF应税基数", "F02010": "IRPEF毛额", "F02500": "雇员个税抵免",
    "F02701": "工资补贴(L.21/2020)", "F02703": "L.207/24津贴", "F02801": "L.207/24额外抵免",
    "F03020": "IRPEF预扣", "F03320": "续约应税基数L.199/25", "F03321": "加成/津贴应税基数",
    "F03325": "替代税L.199/25", "F03326": "替代税L.199/25(c10)", "F06000": "单独计税基数",
    "F06010": "单独计税IRPEF毛额", "F06020": "单独计税IRPEF预扣", "F06990": "参考收入",
    "F06992": "TFR应税基数(2)", "F07015": "TFR个税抵免(定期)", "F07017": "TFR个税抵免L.244/07",
    "F07530": "TFR税率", "F08080": "归国人员免税收入", "F09110": "大区附加税2025",
    "F09130": "市镇附加税2025", "F09140": "市镇附加税预缴2026", "F09150": "工资补贴分期2025",
    "F09156": "额外抵免分期2025", "F09443": "离职抵免参考收入", "F09500": "离职雇员抵免",
    "F09586": "离职结算L.207/24津贴", "F09600": "离职结算IRPEF净额", "F09610": "离职结算大区附加税",
    "000016": "补发前月工资", "000025": "电子餐券", "000070": "费用报销", "000100": "奖金",
}

# ============ 坐标定位提取 ============
CODE_RE = re.compile(r'((?:F|Z)\d{4,5}|Z\d[A-Z]\d{3,4}|ZP\d{3,4}|\d{6})\s*(.*)')
NUM_RE = re.compile(r'(-?\(?[\d.]+\,\d+\)?)')

def extract_voci_by_coords(pi, emp_name, emp_code, emp_pages=None):
    """基于坐标精确提取费用条目"""
    with pdfplumber.open(PDF_PATH) as pdf:
        page = pdf.pages[pi]
        boundaries = detect_column_boundaries(page)
        
        # 获取所有非旋转文字字符（size较大的horizontal文字）
        data_chars = [c for c in page.chars if c['size'] >= 4]
        
        # 按y分组（放宽分组间距到8px以适应行内微差）
        rows = {}
        for c in data_chars:
            y_key = round(c['top'] / 8) * 8
            if y_key not in rows:
                rows[y_key] = []
            rows[y_key].append(c)
        
        voci = []
        for y in sorted(rows.keys()):
            chars = rows[y]
            # 获取col1（名称列，跳过col0侧边栏旋转文字）
            name_text = get_value_at_column(chars, boundaries[1], boundaries[2])
            name_text = name_text.replace('*', '').strip()
            
            m = CODE_RE.search(name_text)
            if not m:
                continue
            
            codice = m.group(1)
            # 过滤垃圾行
            if codice.isdigit() and len(codice) == 6 and not codice.startswith('0'):
                continue
            
            # 获取名称
            rest = m.group(2).strip()
            nome = NUM_RE.sub('', rest).strip()
            nome = re.sub(r'\s+', ' ', nome).strip()
            if not nome or len(nome) < 2:
                continue
            # 过滤非费用条目
            # 过滤非费用条目(公司/地址行)，注意避开合法项目如"Trasferta Italia"
            if nome.upper().startswith('GOFO') or nome.upper().startswith('ZHANG') or nome.upper().startswith('GUO'):
                continue
            # 雇主承担部分(如 Contributo EBILOG C/Ditta)不计入员工本月应发
            if 'C/DIT' in nome.upper():
                continue
            if codice in ('000225',) or (codice == '000000'):
                continue
            
            # 只在员工数据页提取 (跳过汇总页的重复数据)
            if any(k in nome.upper() for k in ['Ferie ', 'Perm.Ex-Fs', 'Permessi ',
                                                'CONGUAGLIO', 'PROGRESSIVI',
                                                'IMPIONIBILE T.F.R.', 'REDDITO DI RIFERIMENTO',
                                                'COMUNICAZIONI']):
                continue
            # 离职清算(Liquidazione/TFR)专项科目：非月度应发，不计入总应发，跳过
            if codice not in ('F09586',) and any(k in nome.upper() for k in ['CN. LIC', 'ALIQUOTA T.F.R',
                                                'LIQUIDAZ', 'RIVALUTAZ', ' LIC.', 'DETR. D',
                                                'DETR.D', 'REDD.RIF', 'IRPEF NETTA LIC']):
                continue
            if any(k in name_text for k in ['COGNOME', 'PERIODO', 'VOCI', 'ALLESTIMENTO',
                                            'RETRIBUZIONE', 'TOTALE', 'Zucchetti']):
                continue
            if name_text in ['P', 'F', 'Giorni', 'Detrazioni', 'Nr.']:
                continue
            
            # 从各列提取数值
            # 列边界: boundaries = [0, 32, 233, 319, 431, 499, ~595]
            # col1=nome(32-233), col2=imp_base(233-319), col3=riferimento(319-431), col4=trattenute(431-499), col5=competenze(499+)
            col_defs = [
                (2, 233, 319, 'importo_base'),
                (3, 319, 431, 'riferimento'),
                (4, 431, 499, 'trattenute'),
                (5, 499, 9999, 'competenze'),
            ]
            
            entry = {'codice': codice, 'nome': nome, 'emp_name': emp_name, 'emp_code': emp_code,
                     'page': pi + 1,
                     'importo_base': '', 'riferimento': '', 'trattenute': '', 'competenze': '',
                     'importo_base_raw': '', 'riferimento_raw': '', 'trattenute_raw': '', 'competenze_raw': ''}
            
            for ci, x_low, x_high, field in col_defs:
                raw = get_value_at_column(chars, x_low, x_high)
                if raw:
                    nums = NUM_RE.findall(raw)
                    if nums:
                        val = nums[0]
                        if ci == 3:  # riferimento: 保留前缀文字
                            entry[f'{field}_raw'] = raw.strip()
                            entry[field] = convert_riferimento(raw.strip())
                        else:
                            entry[f'{field}_raw'] = val
                            entry[field] = fmt(val)
            
            if any(entry[f+'_raw'] for f in ['importo_base','riferimento','trattenute','competenze']):
                # 雇主承担部分(C/Ditta 标记常落在基数/说明列)不计入员工本月应发
                _cdit = (entry['nome'] + ' ' + (entry.get('riferimento_raw') or '') + ' ' + (entry.get('importo_base_raw') or '')).upper()
                if 'C/DIT' in _cdit:
                    continue
                # DETRAZ类项目强制放competenze(即使列位置在imp_base范围)
                nu_name = entry['nome'].upper()
                if any(k in nu_name for k in ['DETRAZ', 'TRATTAMENTO', 'INDENNIT']):
                    val = entry['importo_base']
                    val_raw = entry['importo_base_raw']
                    if val:
                        entry['competenze'] = val
                        entry['competenze_raw'] = val_raw
                        entry['importo_base'] = ''
                        entry['importo_base_raw'] = ''
                # Z50039 Contributo EBILOG：雇主承担份额(CP=3,50)不计入员工应发，仅保留员工自付(TR=0,50)
                if codice == 'Z50039' and entry['competenze_raw'] and not entry['trattenute_raw']:
                    entry['competenze'] = ''
                    entry['competenze_raw'] = ''
                voci.append(entry)
        
        # 兜底：仅在本员工自身的"明细页"(非汇总页)内补全遗漏，严禁扫描汇总页，
        # 避免汇总页重印值(如 F09110/F09130/F09150 在汇总页落在另一列)污染应发导致翻倍
        col_codes = {v['codice'] for v in voci if any(v[f+'_raw'] for f in ['importo_base','riferimento','trattenute','competenze'])}
        _detail_pages = []
        if emp_pages:
            for p in emp_pages:
                _s = extract_summary(pages_text.get(p, ''), emp_name, p - 1)
                if not (_s and _s.get('total_competenze')):
                    _detail_pages.append(p)
        if emp_pages:
            # 兜底只扫描「当前页」自身文本补全遗漏，严禁扫描同员工其它页
            # （避免双期间员工把另一期间的科目重复拉进本页，造成应发合计虚高）
            fallback_text = pages_text.get(pi + 1, '')
        else:
            fallback_text = pages_text.get(pi + 1, '')
        for line in fallback_text.split('\n'):
            line = line.strip()
            if not line or len(line) < 5:
                continue
            content = line.replace('*', '').strip()
            m = CODE_RE.search(content)
            if not m:
                continue
            cod = m.group(1)
            if cod.isdigit() and len(cod) == 6 and not cod.startswith('0'):
                continue
            if cod in col_codes:
                continue
            rest2 = m.group(2).strip()
            nome2 = NUM_RE.sub('', rest2).strip()
            nome2 = re.sub(r'\s+', ' ', nome2).strip()
            if not nome2 or len(nome2) < 2:
                continue
            # 与主提取循环保持一致的过滤（避免兜底把离职清算/TFR/汇总行重新灌入月度应发）
            if any(k in nome2.upper() for k in ['Ferie ', 'Perm.Ex-Fs', 'Permessi ',
                                                'CONGUAGLIO', 'PROGRESSIVI',
                                                'IMPIONIBILE T.F.R.', 'REDDITO DI RIFERIMENTO',
                                                'COMUNICAZIONI']):
                continue
            if cod not in ('F09586',) and any(k in nome2.upper() for k in ['CN. LIC', 'ALIQUOTA T.F.R',
                                                'LIQUIDAZ', 'RIVALUTAZ', ' LIC.', 'DETR. D',
                                                'DETR.D', 'REDD.RIF', 'IRPEF NETTA LIC']):
                continue
            if any(k in content for k in ['COGNOME', 'PERIODO', 'VOCI', 'ALLESTIMENTO',
                                          'RETRIBUZIONE', 'TOTALE', 'Zucchetti']):
                continue
            if nome2.upper().startswith('GOFO') or nome2.upper().startswith('ZHANG') or nome2.upper().startswith('GUO'):
                continue
            if 'C/DIT' in nome2.upper():
                continue
            if cod in ('000225',) or (cod == '000000'):
                continue
            nums = re.findall(r'(%?\(?[\d.]+\,\d+\)?)', rest2)
            if not nums:
                continue
            
            entry = {'codice': cod, 'nome': nome2, 'emp_name': emp_name, 'emp_code': emp_code,
                     'page': pi + 1,
                     'importo_base': '', 'riferimento': '', 'trattenute': '', 'competenze': '',
                     'importo_base_raw': '', 'riferimento_raw': '', 'trattenute_raw': '', 'competenze_raw': ''}
            nu = nome2.upper()
            
            if 'RITENUTE' in nu or 'IMPOSTA SOSTITUTIVA' in nu:
                entry['trattenute_raw'] = nums[0]
                entry['trattenute'] = fmt(nums[0])
            elif 'DETRAZ' in nu:
                entry['competenze_raw'] = nums[0]
                entry['competenze'] = fmt(nums[0])
            elif 'IMPONIBILE' in nu or 'IRPEF LORDA' in nu or 'LORDA' in nu:
                entry['importo_base_raw'] = nums[0]
                entry['importo_base'] = fmt(nums[0])
            elif 'CONTRIBUTO' in nu or 'CIGS' in nu or 'FIS' in nu:
                entry['trattenute_raw'] = nums[0]
                entry['trattenute'] = fmt(nums[0])
            elif 'TRATTAMENTO' in nu or 'INDENNIT' in nu:
                entry['competenze_raw'] = nums[0]
                entry['competenze'] = fmt(nums[0])
            elif 'ARROTOND' in nu:
                entry['trattenute_raw'] = nums[0]
                entry['trattenute'] = fmt(nums[0])
            else:
                entry['competenze_raw'] = nums[0]
                entry['competenze'] = fmt(nums[0])
            
            # 多数字时补充riferimento/IB
            if len(nums) >= 3:
                entry['importo_base_raw'] = nums[0]
                entry['importo_base'] = fmt(nums[0])
                entry['riferimento_raw'] = nums[1]
                entry['riferimento'] = convert_riferimento(nums[1])
                if any(k in nu for k in ['CONTRIBUTO', 'CIGS', 'FIS', 'RITENUTE']):
                    entry['trattenute_raw'] = nums[2]
                    entry['trattenute'] = fmt(nums[2])
                else:
                    entry['competenze_raw'] = nums[2]
                    entry['competenze'] = fmt(nums[2])
            
            # 雇主承担部分(C/Ditta 标记常落在基数/说明列)不计入员工本月应发
            _cdit2 = (nome2 + ' ' + (entry.get('riferimento_raw') or '') + ' ' + (entry.get('importo_base_raw') or '')).upper()
            if 'C/DIT' in _cdit2:
                continue
            # Z50039 Contributo EBILOG：雇主承担份额(CP)不计入员工应发
            if cod in ('Z50039',) and entry['competenze_raw'] and not entry['trattenute_raw']:
                entry['competenze'] = ''
                entry['competenze_raw'] = ''
            voci.append(entry)
    
    return voci

# ============ 后处理：括号补充 ============
def fix_brackets(voci):
    for v in voci:
        for pn, text in pages_text.items():
            if v['emp_code'] not in text or v['codice'] not in text:
                continue
            for line in text.split('\n'):
                if v['codice'] not in line:
                    continue
                line_flat = line.replace(' ', '')
                for field in ['competenze_raw', 'trattenute_raw']:
                    raw = v[field]
                    if not raw or raw.startswith('('):
                        continue
                    num = raw.strip('()')
                    if f'(){num}' in line_flat:
                        v[field] = f'({num})'
    return voci

# ============ 解析汇总 ============
def extract_summary_by_coords(pi):
    """坐标定位汇总值（适用于无'Residuo AP'文字的离职/入职员工页面）"""
    res = {}
    with pdfplumber.open(PDF_PATH) as pdf:
        page = pdf.pages[pi]
        chars = [c for c in page.chars if c['size'] >= 4]
        rows = {}
        for c in chars:
            y_key = round(c['top'] / 6) * 6
            if y_key not in rows:
                rows[y_key] = []
            rows[y_key].append(c)
        for y in sorted(rows.keys()):
            row_chars = sorted(rows[y], key=lambda c: c['x0'])
            cp_text = ''.join(c['text'] for c in row_chars if c['x0'] >= 499).strip()
            all_text = ''.join(c['text'] for c in row_chars).replace(' ', '').replace('*', '')
            if not cp_text:
                continue
            m = re.search(r'(\d[\d.]*\,\d+)', cp_text)
            if not m:
                continue
            val = m.group(1)
            # 按行内标签文字识别汇总字段
            if 'NETT' in all_text:
                res['netto_mese'] = val
            elif 'COMPETENZE' in all_text:
                res['total_competenze'] = val
            elif 'TRATTENUTE' in all_text:
                res['total_trattenute'] = val
            elif 'ROTONDAMENTO' in all_text:
                res['arrotondamento'] = val
    return res


def extract_summary(text, emp_name, page_num=None):
    summary = {'emp_name': emp_name}
    lines = text.split('\n')
    
    # 方式1：通过 'Residuo AP' 定位（正常员工）
    found_residuo = False
    for i, line in enumerate(lines):
        if 'Residuo AP' in line or 'Residuo AP' in line.replace(' ', ''):
            found_residuo = True
            if i > 0:
                prev = lines[i-1].strip()
                m = re.search(r'([\d.]+\,\d+)', prev)
                if m:
                    summary['total_trattenute'] = m.group(1)
            m = re.search(r'([\d.]+\,\d+)', line)
            if m:
                summary['total_competenze'] = m.group(1)
            break
    
    # netto_mese（两种格式通用）
    for line in lines:
        m = re.search(r'([\d.]+\,[\d]+)\s*[\u20ac\u20AC]', line)
        if m:
            summary['netto_mese'] = m.group(1)
            break
    
    # 方式2：无 Residuo AP（离职/入职员工），用坐标定位
    if not found_residuo and page_num is not None:
        coords_summary = extract_summary_by_coords(page_num)
        for k, v in coords_summary.items():
            if v and not summary.get(k):
                summary[k] = v
    
    # arrotondamento（净额上方小于1的值）
    netto_idx = None
    for i, line in enumerate(lines):
        if re.search(r'([\d.]+\,[\d]+)\s*[\u20ac\u20AC]', line):
            netto_idx = i
            break
    if not summary.get('arrotondamento') and netto_idx and netto_idx > 0:
        for i in range(netto_idx-1, max(netto_idx-5, -1), -1):
            line = lines[i].strip()
            ms = re.findall(r'([\d.]+\,\d+)', line)
            for val in ms:
                num = float(val.replace('.', '').replace(',', '.'))
                if num < 1.0:
                    summary['arrotondamento'] = val
                    break
            if 'arrotondamento' in summary:
                break
    return summary

def run(pdf_path):
    _load(pdf_path)
    # ============ 主流程 ============
    employees = extract_employees()
    print("=== 员工信息 ===")
    for e in employees:
        print(f"  {e['name']} - 页面:{e['pages']}")

    all_voci = []
    all_summaries = []

    for emp in employees:
        # 仅从"明细页"(本页提取不到 total_competenze 的页)提取 voci；
        # 汇总页(含 Totale Competenze 的页)上的科目大部分是重印，如果直接提取
        # 会因列漂移导致应发翻倍，因此主循环只走明细页。
        # 单页工资单(明细+汇总同页)则整页提取。
        # 终止/离职员工(含第三个日期=离职日)的工资单，清算页(含 F09586 等结算科目)与
        # 明细页是不同科目，需全部扫描，不能按"含总应发即跳过"的规则排除清算页。
        _terminated = any(re.search(r'\d{2}-\d{2}-\d{4}\s+\d{2}-\d{2}-\d{4}\s+\d{2}-\d{2}-\d{4}', pages_text.get(pn, ''))
                          for pn in emp['pages'])
        if _terminated:
            detail_pages = list(emp['pages'])
        else:
            detail_pages = [p for p in emp['pages']
                            if not (extract_summary(pages_text[p], emp['name'], p - 1) or {}).get('total_competenze')]
            if not detail_pages:
                detail_pages = list(emp['pages'])

        def _norm(v):
            for f in ('competenze_raw', 'trattenute_raw', 'importo_base_raw'):
                if v.get(f):
                    return (v['codice'], v[f])
            return (v['codice'], '')
        per_page_voci = {}
        for pn in detail_pages:
            per_page_voci[pn - 1] = extract_voci_by_coords(pn - 1, emp['name'], emp['code'], emp_pages=emp['pages'])
        seen_norm = set()
        for pn in detail_pages:
            pi = pn - 1
            norms = [_norm(v) for v in per_page_voci[pi]]
            if seen_norm and norms and all(nv in seen_norm for nv in norms):
                print("  [去重] %s 页%d 为工资单重印(纯重复)，跳过" % (emp['name'], pn))
                continue
            for nv in norms:
                seen_norm.add(nv)
            all_voci.extend(per_page_voci[pi])
        # 额外扫描被排除的汇总页，只保留 TR 有值且 CP 为空、且编码不在明细页中的科目。
        # 重印页的编码与明细页相同会被跳过（防止如 Contributo IVS 重印导致金额翻倍）；
        # 列漂移错灌到 CP 列的科目因 CP 非空而被排除，不会污染应发。
        detail_codes = {v['codice'] for pn in detail_pages for v in per_page_voci[pn - 1]}
        for pn in emp['pages']:
            if pn in detail_pages:
                continue
            voci = extract_voci_by_coords(pn - 1, emp['name'], emp['code'], emp_pages=emp['pages'])
            for v in voci:
                if v['trattenute_raw'] and not v['competenze_raw']:
                    if v['codice'] in detail_codes:
                        continue
                    all_voci.append(v)
        # 汇总取最后一个页面对应的 total_competenze/nettomese 等
        for pn in reversed(emp['pages']):
            s = extract_summary(pages_text[pn], emp['name'], pn - 1)
            if s:
                s['emp_code'] = emp['code']
                existing = [x for x in all_summaries if x.get('emp_code') == emp['code']]
                if existing:
                    existing[0].update({k: v for k, v in s.items() if v and k not in ('emp_name', 'emp_code')})
                else:
                    all_summaries.append(s)
                break

    # 后处理
    all_voci = fix_brackets(all_voci)

    # 清理imp_base中的括号残留
    for v in all_voci:
        raw = v.get('importo_base_raw', '')
        if raw and '(' in raw:
            v['importo_base_raw'] = ''
            v['importo_base'] = ''

    print(f"\n=== 提取费用 ({len(all_voci)}条) ===")
    for v in all_voci:
        print(f"  {v['emp_name']:15s} | {v['codice']:8s} | {v['nome']:30s} | IB:{v['importo_base_raw'] or '':>12s} | RF:{v['riferimento_raw'] or '':>20s} | TR:{v['trattenute_raw'] or '':>10s} | CP:{v['competenze_raw'] or '':>10s}")

    # 相同编码不合并，保留 PDF 中的每一行（例如两个奖金拆开展示）

    def sort_key_code(codice):
        first = codice[0]
        num = int(re.sub(r'\D', '', codice) or 0)
        if first == 'Z': return (0, num)
        elif first == 'F': return (1, num)
        else: return (2, num)

    # 按员工 + PDF 页码顺序排列，保持与原始 PDF 一致的科目先后顺序，便于逐行核对金额
    all_voci.sort(key=lambda x: (x['emp_code'], x.get('page', 0)))

    print(f"\n=== 排序后 ({len(all_voci)}条) ===")
    for v in all_voci:
        ib = fmt(v['importo_base_raw']) if v['importo_base_raw'] else ''
        rf = convert_riferimento(v['riferimento_raw']) if v['riferimento_raw'] else ''
        tr = fmt(v['trattenute_raw']) if v['trattenute_raw'] else ''
        cp = fmt(v['competenze_raw']) if v['competenze_raw'] else ''
        print(f"  {v['emp_name']:15s} | {v['codice']:8s} | {v['nome']:30s} | IB:{ib:>12s} | RF:{rf:>20s} | TR:{tr:>10s} | CP:{cp:>10s}")

    # ============ 生成Excel（2 张中文表） ============
    wb = Workbook()
    thin_border = Border(
        left=Side(style='thin'), right=Side(style='thin'),
        top=Side(style='thin'), bottom=Side(style='thin')
    )
    hdr_font = Font(bold=True, size=10, name='Arial', color='FFFFFF')
    hdr_fill = PatternFill('solid', fgColor='4472C4')
    hdr2_fill = PatternFill('solid', fgColor='ED7D31')
    sub_font = Font(size=10, name='Arial')
    center = Alignment(horizontal='center', vertical='center', wrap_text=True)
    left_al = Alignment(horizontal='left', vertical='center')

    # 科目名称规范化（同编码取最佳名称）
    canonical_name = {}
    for v in all_voci:
        c = v['codice']; n = v['nome']
        if c not in canonical_name:
            canonical_name[c] = n
        else:
            curr = canonical_name[c]
            n_has_digit = n[0].isdigit() if n else False
            c_has_digit = curr[0].isdigit() if curr else False
            if n_has_digit and not c_has_digit:
                continue
            elif not n_has_digit and c_has_digit:
                canonical_name[c] = n
            elif len(n) < len(curr):
                canonical_name[c] = n
    for v in all_voci:
        v['nome'] = canonical_name.get(v['codice'], v['nome'])

    seen_keys = sorted({(v['codice'], v['nome']) for v in all_voci}, key=lambda k: sort_key_code(k[0]))

    def _subj_label(codice, nome):
        zh = CODE_ZH.get(codice)
        if zh:
            return "%s(%s)" % (zh, nome)
        return nome

    # ---- Sheet 1: 工资科目明细（长表，每人每科目一行，可筛选） ----
    ws = wb.active
    ws.title = "工资科目明细"
    headers1 = ["员工", "编号", "科目编码", "科目名称", "原始科目名称(意大利文)", "应发", "扣款", "基数", "说明"]
    for j, h in enumerate(headers1, 1):
        cell = ws.cell(row=1, column=j, value=h)
        cell.font = hdr_font; cell.fill = hdr_fill
        cell.alignment = center; cell.border = thin_border
    r = 2
    def _amt(raw):
        # 括号负数(员工自付等)不计入应发/扣款合计
        if not raw or '(' in raw:
            return ''
        return parse_num(raw)

    for v in all_voci:
        nome = v['nome'] or ''
        nome_low = nome.lower()
        is_detraz = 'detraz' in nome_low
        is_progress = 'progress' in nome_low
        # 税收抵免(Detrazioni)与年度累计(PROGRESSIVI)不计入"本月应发"合计
        if is_detraz:
            note = '税收抵免，不计入应发'
        elif is_progress:
            note = '年度累计，不计入本月应发'
        else:
            note = convert_riferimento(v['riferimento_raw']) if v['riferimento_raw'] else ''
        comp_show = _amt(v['competenze_raw']) if (v['competenze_raw'] and not is_detraz and not is_progress) else ''
        vals = [
            v['emp_name'], v['emp_code'], v['codice'],
            _subj_label(v['codice'], nome),
            nome,
            comp_show,
            _amt(v['trattenute_raw']) if v['trattenute_raw'] else '',
            parse_num(v['importo_base_raw']) if v['importo_base_raw'] else '',
            note,
        ]
        for j, val in enumerate(vals, 1):
            cell = ws.cell(row=r, column=j, value=val)
            cell.font = sub_font; cell.border = thin_border
            cell.alignment = left_al if j in (1, 4, 5, 9) else center
            if j in (6, 7, 8) and isinstance(val, (int, float)):
                cell.number_format = '#.##0,00'
        r += 1
    widths1 = [18, 10, 10, 30, 38, 12, 12, 12, 28]
    for i, w in enumerate(widths1, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = 'A2'
    if r > 2:
        ws.auto_filter.ref = "A1:I%d" % (r - 1)

    # ---- Sheet 2: 员工汇总（一人一行，含员工信息 + 校验差） ----
    ws2 = wb.create_sheet("员工汇总")
    headers2 = ["姓名", "编号", "税号", "出生", "入职", "职务", "基本工资", "EDR",
                "EPA", "固定薪酬合计", "总应发", "税收抵免", "总扣", "舍入", "实发", "校验差(应发-总应发)"]
    for j, h in enumerate(headers2, 1):
        cell = ws2.cell(row=1, column=j, value=h)
        cell.font = hdr_font; cell.fill = hdr2_fill
        cell.alignment = center; cell.border = thin_border
    sum_by_code = {s.get('emp_code'): s for s in all_summaries}
    # 每员工税收抵免(Detrazioni)合计: competenze 列且名称含 detraz
    detraz_by_code = {}
    for v in all_voci:
        if 'detraz' in (v['nome'] or '').lower() and v['competenze_raw']:
            detraz_by_code[v['emp_code']] = detraz_by_code.get(v['emp_code'], 0.0) + parse_num(v['competenze_raw'])
    # 每员工"本月应发"合计 = 工资科目明细 competenze 之和(排除税收抵免/年度累计/括号负数/雇主EBILOG)
    # 用于 Sheet2 "校验差" 列与 PDF 权威总应发对账
    # 下列科目虽落在「应发」列，但不计入 Zucchetti 的 Totale Competenze
    # (F08080 归国人员免税额 / F09110·F09130·F09150 大区·市镇附加税)，属税/准税项，
    # 从"本月应发"合计中剔除，使校验差与 PDF 总应发口径一致。
    EXCLUDE_FROM_GROSS = {'F08080', 'F09110', 'F09130', 'F09150'}
    sheet1_total_by_code = {}
    for v in all_voci:
        nome = (v['nome'] or '').lower()
        if 'detraz' in nome or 'progress' in nome:
            continue
        if v['codice'] in EXCLUDE_FROM_GROSS:
            continue
        cp = parse_num(v['competenze_raw']) if v['competenze_raw'] and '(' not in v['competenze_raw'] else 0.0
        sheet1_total_by_code[v['emp_code']] = sheet1_total_by_code.get(v['emp_code'], 0.0) + cp
    red_font = Font(size=10, name='Arial', color='FF0000', bold=True)
    r = 2
    for emp in sorted(employees, key=lambda e: e['code']):
        s = sum_by_code.get(emp['code'], {})
        # Sheet2 "总应发" 取 PDF 权威 Totale Competenze(汇总页)，与真实工资单相一致；
        # 若汇总页缺失则回退到明细应发合计
        comp = parse_num(s['total_competenze']) if (s and s.get('total_competenze')) else sheet1_total_by_code.get(emp['code'], 0.0)
        tratt = parse_num(s.get('total_trattenute', ''))
        arrot = parse_num(s.get('arrotondamento', ''))
        netto = parse_num(s.get('netto_mese', ''))
        dz = detraz_by_code.get(emp['code'], 0.0)
        vals = [emp['name'], emp['code'], emp['tax_code'], emp['birth'], emp['hire'],
                emp['role'],
                parse_num(emp['paga_base']) if emp.get('paga_base') else '',
                parse_num(emp['edr']) if emp.get('edr') else '',
                parse_num(emp['epa']) if emp.get('epa') else '',
                parse_num(emp['totale']) if emp.get('totale') else '',
                comp,
                dz if dz else '',
                parse_num(s.get('total_trattenute', '')),
                parse_num(s.get('arrotondamento', '')), parse_num(s.get('netto_mese', ''))]
        for j, val in enumerate(vals, 1):
            cell = ws2.cell(row=r, column=j, value=val)
            cell.font = sub_font; cell.border = thin_border
            cell.alignment = center
            if j in (7, 8, 9, 10, 11, 12, 13, 14, 15) and isinstance(val, (int, float)):
                cell.number_format = '#.##0,00'
        dcell = ws2.cell(row=r, column=16)
        dcell.font = sub_font; dcell.border = thin_border; dcell.alignment = center
        # 校验差 = 工资科目明细"应发"合计 − PDF 权威总应发；≈0 表示提取精准，否则标红提示需核对原PDF
        diff = sheet1_total_by_code.get(emp['code'], 0.0) - comp
        if abs(diff) < 0.01:
            dcell.value = ""
        else:
            dcell.value = "%.2f" % diff
            dcell.font = red_font
        r += 1
    widths2 = [20, 10, 16, 12, 12, 20, 12, 12, 12, 12, 12, 12, 12, 10, 12, 14]
    for i, w in enumerate(widths2, 1):
        ws2.column_dimensions[get_column_letter(i)].width = w
    ws2.freeze_panes = 'A2'
    if r > 2:
        ws2.auto_filter.ref = "A1:P%d" % (r - 1)

    # 保存到内存（不落盘），返回字节与统计
    buf = io.BytesIO()
    wb.save(buf)
    wb_bytes = buf.getvalue()
    print(f"[ITALY] 员工 {len(employees)} 名 / 费用 {len(all_voci)} 条 / 编码 {len(seen_keys)} 个")
    return wb_bytes, {
        "num_employees": len(employees),
        "num_voci": len(all_voci),
        "num_codes": len(seen_keys),
    }

"""Turn local approval originals into reviewable changes, never automatic awards.

Extraction accepts explicit business phrases. Matching uses this activity's
original records, not applicant/signatory names or fuzzy name similarity.
Unknown wording, ambiguous employments and missing attachments stay visible.
Only the selected, revision-checked proposals can enter a normal undoable preview.
"""
from collections import defaultdict
from copy import deepcopy
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path
import re

from .recruitment_documents import extract_document, mentioned_attachments, unreadable_pages
from .recruitment_draft_sources import digest, text

STAFF = r'(?<![a-z0-9])(?:zt|z1|zl|21)\d{4,9}(?!\d)'
RECIPIENT_ID = r'(?:zt|z1|zl|21|gl)\d{4,9}'
FIELDS = {'ABC类别', '招聘渠道', '周期剔除天数', '周期剔除依据', '招聘启动日期',
          '入职日期', '候选人入职时间', '转正日期', '最后工作日', '职级',
          '招聘负责人姓名', '招聘负责人工号', '协助招聘人姓名', '协助招聘人工号',
          '推荐人姓名', '推荐人工号'}
LABELS = {'ABC类别': '岗位类别', '候选人入职时间': '录用入职日期'}
ROLES = {'推荐人': r'(?:推荐人|内推人)', '协助招聘人': r'(?:协助招聘人|招聘协助人)', '招聘负责人': r'招聘负责人'}


def compact(value):
    return re.sub(r'\s+', '', text(value)).casefold()


def staff(value):
    value = compact(value)
    return re.sub(r'^(?:z1|zl|21)(?=\d{4,9}$)', 'zt', value)


def dates(body):
    return {f'{int(y):04d}-{int(m):02d}-{int(d):02d}' for y, m, d in
            re.findall(r'(20\d{2})[年/.-](\d{1,2})[月/.-](\d{1,2})日?', body)}


def body_text(doc):
    # OA scans sometimes contain the same printout twice. Later copies are
    # retained as evidence, but repeated proposals are deduplicated below.
    return '\n'.join(p.get('text', '').replace('\u3000', ' ') for p in doc['pages'] if not p.get('blank'))


def business_wording(body):
    # Normalize wording for parsing only; original excerpts remain available.
    return body.translate(str.maketrans('關於編碼內薦誤資訊請該為補並員', '关于编码内荐误资讯请该为补并员'))


def printed_sections(full):
    """Separate flattened OA form sentences from operator columns and crop copies."""
    if not ('基本信息' in full and re.search(r'申请人工号\s*[*＊]', full)):
        return None
    body = []; opinions = []; continuing = False; days_next = False
    boundary = re.compile(r'^(?:节点名称|操作者|操作$|处理意见|审批记录|评论记录|附件$|打印日期|扫描二维码|'
                          r'起草|超草|直接上级|间隔上级|HSSC|海外HR|HRBP|CHO|结束节点|时间$|'
                          r'身份重复|提交文档|通过$|结束流程|抱歉|模板|基本信息|申请人|创建时间)')
    action = re.compile(r'入职的人员[（(]|员工.+由原定|已于\s*20\d{2}.+入职|'
                        r'o[f]+er\s*流程.*(?:编码|编号|编碼)|'
                        r'招聘渠道.{0,20}(?:修改|调整|更正|变更)|'
                        r'由.+(?:内推|推荐)|(?:申请|批准).*(?:剔除|扣除)\s*\d|'
                        r'特此申请.*(?:offer|录用).*变更|'
                        r'申请.*按\s*[ABC]\s*类|^\d+[.、]\s*在.*入职|'
                        r'(?:招聘启动日期|入职日期|转正日期|最后工作日|职级|ABC类别|岗位类别).{0,15}(?:修改|调整|更正|变更|改为)|'
                        r'(?:不发|取消|不予发放)(?:招聘|内推)奖金|无需调整|无需修改|维持原资料|保持现有资料|候选人[：:]|'
                        r'(?:取消|更正|补充|调整).*(?:推荐人|协助人|招聘负责人)', re.I)
    for original in full.splitlines():
        line = business_wording(original.strip())
        if not line: continue
        if re.match(r'^(?:同意|不同意|仅批准|只批准|不批准|不予|最终意见|最终审批意见|维持原|保持现有|另行核定)', line):
            opinions.append(line); continuing = False; continue
        if re.match(r'^剔除天数\s*[*＊：:，,]?\s*\d*(?:\.\d+)?$', line):
            body.append(line); days_next = not bool(re.search(r'\d', line)); continuing = False; continue
        if days_next:
            if re.fullmatch(r'\d+(?:\.\d+)?', line): body.append(line)
            days_next = False
        if boundary.search(line) or re.match(r'^[•●○O]|^20\d{2}-\d\d-\d\d|^ZTJT-', line) or re.search(r'\.(?:pdf|pdt|jpg|png)\b', line, re.I):
            continuing = False; continue
        if action.search(line) and '提交的' not in line:
            body.append(line); continuing = True
        elif continuing and (len(line) >= 18 or re.fullmatch(r'周期[。.]?', line)):
            body.append(line)
        else:
            continuing = False
    return '\n'.join(dict.fromkeys(body)), list(dict.fromkeys(opinions))


@lru_cache(maxsize=4)
def original_people(folder, sources):
    people = {}; offers = []
    for sid, filename in sources:
        path = Path(folder) / 'parsed' / (sid + '.json')
        if not path.is_file():
            continue
        for rec in json.loads(path.read_text()).get('records', []):
            v = rec.get('values', {}); name = text(v.get('姓名')); number = staff(v.get('工号'))
            if rec.get('role') in {'roster', 'ledger', 'supplement', 'domestic_offer', 'overseas_offer'} and name:
                if number or v.get('入职日期'):
                    key = (number, compact(name), text(v.get('入职日期')))
                    person = people.setdefault(key, {'name': name, 'employeeId': number,
                        'hireDate': text(v.get('入职日期')), 'offers': set()})
                    if v.get('海外offer流程编号'): person['offers'].add(text(v['海外offer流程编号']))
                if v.get('海外offer流程编号'):
                    offers.append((name, number, text(v['海外offer流程编号'])))
            # Recipient facts in an Offer can identify someone absent from the
            # roster. They do not prove a new recipient relationship.
            for prefix in ('招聘负责人', '协助招聘人', '推荐人'):
                rn = text(v.get(prefix+'姓名')); ri = staff(v.get(prefix+'工号'))
                if rn and ri:
                    people.setdefault((ri, compact(rn), ''), {'name':rn, 'employeeId':ri, 'hireDate':'', 'offers':set()})
    values = list(people.values())
    by_name = defaultdict(list)
    for p in values: by_name[compact(p['name'])].append(p)
    for name, number, offer in offers:
        found = [p for p in by_name[compact(name)] if not number or p['employeeId'] == number]
        identities = {p['employeeId'] for p in found}
        if len(identities) == 1:
            for p in found: p['offers'].add(offer)
    return values


class Directory:
    def __init__(self, folder, state):
        sources = tuple((s['id'], s['name']) for s in state['sources'] if s.get('active', True)
                        and not s.get('error') and not s.get('comparisonOnly') and not s.get('attachment'))
        self.people = deepcopy(original_people(str(folder), sources))
        self.rows = state['rows']
        by_identity = defaultdict(list)
        for p in self.people: by_identity[(p['employeeId'],p['hireDate'])].append(p)
        for r in self.rows:
            v = r['values']; number = staff(v.get('工号')); name = text(v.get('姓名')); hire = text(v.get('入职日期'))
            matches = by_identity.get((number,hire),[]) if number else []
            if not matches:
                matches = [{'name':name, 'employeeId':number, 'hireDate':hire, 'offers':set()}]
                self.people.extend(matches)
            for p in matches:
                p['rowId'] = r['id']
                if v.get('海外offer流程编号'): p['offers'].add(text(v['海外offer流程编号']))
        self.target_names = [(p, name, name.casefold()) for p in self.people
                             for name in [re.sub(r'\s+', '', p['name'])]]

    def recipient(self, raw):
        raw = raw.strip(' ：:，,。；;\n')
        numbers = list(dict.fromkeys(staff(s) for s in re.findall(RECIPIENT_ID, raw, re.I)))
        if len(numbers) == 1:
            found = [p for p in self.people if p['employeeId'] == numbers[0]]
            names = {p['name'] for p in found}
            if len(names) == 1: return {'name':next(iter(names)), 'employeeId':numbers[0]}
            if len(names) > 1: return {'name':'', 'employeeId':numbers[0]}
            name = re.sub(RECIPIENT_ID, '', raw, flags=re.I).strip(' ：:，,。；;\n')
            return {'name':name if 1 < len(name) < 60 else '', 'employeeId':numbers[0]}
        found = [p for p in self.people if compact(p['name']) == compact(raw)]
        ids = {p['employeeId'] for p in found if p['employeeId']}
        return {'name':raw, 'employeeId':next(iter(ids)) if len(ids) == 1 else ''}

    def target(self, body, applicant):
        body = business_wording(body)
        named = re.findall(r'入职的人员\s*[（(]([^）)]+)[）)]', body)
        if named:
            found = [p for p in self.people if compact(p['name']) in {compact(n) for n in named}]
            found.extend({'name': n, 'employeeId': '', 'hireDate': '', 'offers': set()}
                         for n in named if not any(compact(p['name']) == compact(n) for p in found))
        else:
            found = None
        explicit = re.findall(r'((?:zt|z1|zl|21)\d{4,9})\s*入职的\s*o[f]+er', body, re.I)
        if found is not None:
            pass
        elif explicit:
            ids = {staff(v) for v in explicit}
            found = [p for p in self.people if p['employeeId'] in ids]
            found.extend({'name': number, 'employeeId': number, 'hireDate': '', 'offers': set()} for number in ids if not any(p['employeeId'] == number for p in found))
        else:
            offer_ids = re.findall(r'(?:o[f]+er\s*(?:流程\s*[（(]?\s*(?:编码|编号)?|编码|编号)|录用流程(?:编号)?)\s*[：:]?\s*(20\d{10})(?!\d)', body, re.I)
            found = [p for p in self.people if p['offers'] & set(offer_ids)]
            if not found and offer_ids:
                return [], '录用流程 '+ '、'.join(dict.fromkeys(offer_ids))+' 未对应到人员，请补充对应的花名册或 Offer。'
            if not found:
                searchable = re.sub(r'\s+', '', body)
                folded = searchable.casefold()
                applicant_name = compact(applicant)
                names = []
                for p, name, folded_name in self.target_names:
                    if len(name) < 2: continue
                    if folded_name not in folded: continue
                    for m in re.finditer(re.escape(name), searchable, re.I):
                        before = searchable[max(0,m.start()-18):m.start()]
                        after = searchable[m.end():m.end()+45]
                        if folded_name == applicant_name and not re.match(r'(?:已于|于)20\d{2}.+入职|由原定', after): continue
                        if any(len(other)>len(folded_name) and any(
                                hit.start()<=m.start() and hit.end()>=m.end()
                                for hit in re.finditer(re.escape(other),folded))
                               for _,_,other in self.target_names if folded_name in other): continue
                        if re.search(r'[a-z]', name[-1], re.I) and m.end()<len(searchable) and re.match(r'[a-z]', searchable[m.end()], re.I): continue
                        if re.search(r'[a-z]', name[0], re.I) and m.start() and re.match(r'[a-z]', searchable[m.start()-1], re.I): continue
                        if after.startswith('内推') and re.search(r'由.*(?:员工|员T)$',before): continue
                        if re.search(r'(?:推荐人|内推人|协助招聘人|招聘协助人|招聘负责人|申请人|审批人)[：:为是]*$', before): continue
                        names.append(p); break
                found = names
                for listed in re.findall(r'(?:^|[。；;\n：:])\s*([^。；;\n：:]+、[^。；;\n：:]+?)\s*(?:均|共同)\s*(?:申请|获批|批准|需)', body):
                    for name in listed.split('、'):
                        name = name.strip()
                        if 2 <= len(name) <= 60 and not any(compact(p['name']) == compact(name) for p in found):
                            found.append({'name': name, 'employeeId': '', 'hireDate': '', 'offers': set()})
        # A known hire date disambiguates namesakes; absence of such a date
        # never selects an arbitrary employment.
        hire_dates = dates(body)
        dated = [p for p in found if p['hireDate'] in hire_dates]
        if dated and len({compact(p['name']) for p in found}) == 1: found = dated
        # A final explicitly postponed hire day can distinguish employments;
        # never infer its year or use the original planned date.
        final_days = {f'-{int(m):02d}-{int(d):02d}' for m,d in re.findall(
            r'推迟至\s*(\d{1,2})[月./-](\d{1,2})日?\s*入职',body)}
        dated = [p for p in found if any(p['hireDate'].endswith(day) for day in final_days)]
        if len(final_days)==1 and dated and len({compact(p['name']) for p in found})==1: found=dated
        distinct = {}
        for p in found:
            key = (p['employeeId'], compact(p['name']), p['hireDate'])
            if key not in distinct or p.get('rowId'): distinct[key] = p
        found = list(distinct.values())
        # A directory-only name/ID record is not another employment when a
        # dated record with that same identity exists.
        found = [p for p in found if p['hireDate'] or not any(
            q['hireDate'] and q['employeeId'] == p['employeeId'] and compact(q['name']) == compact(p['name']) for q in found)]
        if len(found) == 1: return found, ''
        if found: return found, '有多名同名人员或多次任职，请选择本次审批对应的人员。'
        label = '、'.join(dict.fromkeys(staff(v) for v in explicit))
        return [], (label+'：' if label else '')+'未找到对应人员，请补充花名册或选择核算明细中的人员。'


def role_pair(body, prefix, directory):
    structured = re.search(ROLES[prefix]+r'工号\s*[（(：:]\s*('+RECIPIENT_ID+r')\s*[）)]?\s*和姓[名各]\s*[（(：:]\s*([^）)\n]+)[）)]?', body, re.I)
    if structured:
        return {'name': structured[2].strip(), 'employeeId': staff(structured[1])}
    pattern = ROLES[prefix]+r'\s*(?:为|是|填写为|更改为|调整为)?\s*[：:]?\s*([^，,。；;\n]{2,65})'
    for match in re.finditer(pattern, body, re.I):
        raw = match.group(1).strip()
        raw = re.split(r'\s*(?:现申请|需申请|申请|改为|更改为|调整为|变更为|所以|为非|为hras)', raw, flags=re.I)[0]
        if raw.startswith(('和', '的', '范围', '人员范围', '信息', '奖金', '改为', '不', '需')) or not raw: continue
        # Role labels in a sentence about changing roles are not names.
        if re.search(r'招聘|内推|推荐|所以|填写|人员范围|岗位', raw): continue
        return directory.recipient(raw)
    return None


def extract_changes(body, directory):
    body = business_wording(body)
    body = re.sub(r'(?<=[\u4e00-\u9fff])\s*\n\s*(?=[\u4e00-\u9fff])', '', body)
    fields = {}; decisions = []; issues = []
    if re.search(r'(?:不要|无需|不应|不同意|不批准|不予批准).{0,20}(?:修改|更正|调整|改为|剔除|按\s*[ABC]\s*类)',body):
        issues.append('审批中存在否定的调整表述，请核对原件中的最终调整内容。')
    def put(field, value):
        if field in fields and fields[field] != value:
            issues.append(LABELS.get(field, field)+'识别到多个调整值，请核对原件。')
        fields[field] = value
    def pair(prefix, value):
        put(prefix+'姓名', value.get('name','')); put(prefix+'工号', value.get('employeeId',''))
        if not value.get('name'): issues.append('请补充'+prefix+'姓名。')
    moved = re.search(r'从\s*(招聘协助人|协助招聘人|内推人|推荐人)\s*(?:改为|更改为|调整为)\s*(内推人|推荐人|招聘协助人|协助招聘人)', body)
    if moved:
        before = '推荐人' if moved[1] in {'内推人','推荐人'} else '协助招聘人'
        after = '推荐人' if moved[2] in {'内推人','推荐人'} else '协助招聘人'
        who = re.search(r'因\s*('+STAFF+r')', body, re.I)
        person = directory.recipient(who[1]) if who else role_pair(body, before, directory)
        pair(after, person or {'name':'','employeeId':''}); pair(before, {'name':'','employeeId':''})
        issues = [i for i in issues if i != '请补充'+before+'姓名。']
        if after == '推荐人': put('招聘渠道', '内推')
    channels = re.findall(r'(?:招聘渠道\s*(?:需|需要)?\s*(?:(?:修改|调整|更正|变更|改)为|由[^，。；\n]{1,15}改为)|(?:修改|调整|更正|变更)招聘渠道为)\s*(内部推荐入职|内部推荐|外部推荐|内推|招聘网站|校招|猎头|二次入职|员工推荐)', body)
    if not channels and re.search(r'(?:为内推人选|内推人选).*?(?:需更正|需修改|需调整)', body, re.S): channels = ['内推']
    for value in channels: put('招聘渠道', '内推' if value in {'内部推荐','内部推荐入职','员工推荐'} else value)
    if '外部推荐' in channels and re.search(r'误填.{0,60}(?:内部推荐人|内推人).{0,60}(?:取消|删除)', body, re.S):
        pair('推荐人', {'name':'','employeeId':''})
        issues = [i for i in issues if i != '请补充推荐人姓名。']
    referred = re.search(r'由.{0,12}(?:员工|员T)\s*([A-Za-z\u4e00-\u9fff][A-Za-z\u4e00-\u9fff .·-]{1,59}?)\s*内推', body)
    if referred and re.search(r'(?:申请|更正|变更|调整).{0,12}(?:offer|录用|渠道|信息)', body, re.I):
        put('招聘渠道','内推'); pair('推荐人',directory.recipient(referred[1]))
    if not moved:
        for prefix in ROLES:
            value = role_pair(body, prefix, directory)
            if value and (prefix == '推荐人' and fields.get('招聘渠道') == '内推' or
                          re.search(r'忘记填写|(?:补充|补上|增加|补填|添加|改为|变更为|更正为)', body)):
                pair(prefix, value)
    for value in re.findall(r'按\s*([ABC])\s*类(?:岗位)?标准\s*(?:核算|计算)|(?:岗位类别|ABC类别)\s*(?:修改|调整|更正|变更|改)为\s*([ABC])', body, re.I):
        put('ABC类别', (value[0] or value[1]).upper())
    exclusions = re.findall(r'(?<!不)(?<!无需)(?:剔除|扣除)\s*(\d+(?:\.\d+)?)\s*天', body)
    exclusions += re.findall(r'剔除天数\s*[*＊：:，,]?\s*(\d+(?:\.\d+)?)\b', body)
    for days in exclusions:
        put('周期剔除天数', float(days))
    for field in ('招聘启动日期','入职日期','转正日期','最后工作日'):
        for m in re.finditer(field+r'\s*(?:修改|更正|调整|变更|改)为\s*(20\d{2})[年/.-](\d{1,2})[月/.-](\d{1,2})日?', body):
            put(field, f'{int(m[1]):04d}-{int(m[2]):02d}-{int(m[3]):02d}')
            if field == '入职日期': put('候选人入职时间', fields[field])
    for value in re.findall(r'职级\s*(?:修改|更正|调整|变更|改)为\s*([PM]\d-\d)', body, re.I): put('职级',value.upper())
    for word, kind in [('招聘','recruitment'),('内推','referral')]:
        if re.search(r'(?:不发|取消|不予发放)'+word+'奖金', body): decisions.append({'kind':kind,'action':'exclude'})
    return fields, decisions, list(dict.fromkeys(issues))


def same_value(field, left, right):
    if field == '招聘渠道':
        from .recruitment_import_validation import _normalize_offer_channel
        lvalue,lunknown = _normalize_offer_channel(text(left))
        rvalue,runknown = _normalize_offer_channel(text(right))
        if lvalue and rvalue and not lunknown and not runknown:
            return lvalue == rvalue
    if field == '周期剔除天数':
        try: return float(left or 0) == float(right or 0)
        except (ValueError,TypeError): return False
    return text(left) == text(right)


def resolve_item(item, rows, override=None):
    override = override or {}
    if not isinstance(override,dict) or set(override)-{'rowId','fields','decisions'}: raise ValueError('审批调整的补充内容无效')
    extra = override.get('fields',{})
    if not isinstance(extra,dict) or set(extra)-FIELDS or any(not isinstance(v,(str,int,float)) or isinstance(v,bool) for v in extra.values()):
        raise ValueError('请选择有效的调整字段并填写采用值')
    if 'decisions' in override:
        decisions = override['decisions']
        if not isinstance(decisions, list) or any(d not in ({'kind':'recruitment','action':'exclude'}, {'kind':'referral','action':'exclude'}) for d in decisions):
            raise ValueError('请选择有效的奖金处理决定')
        item['decisions'] = decisions
    rid = override.get('rowId',item['person'].get('rowId'))
    if 'rowId' in override and rid not in rows: raise ValueError('所选人员不在本月核算中')
    if 'rowId' in override and item.get('matches') and rid not in {p.get('rowId') for p in item['matches']} and compact(rows[rid]['values'].get('姓名')) not in {compact(p.get('name')) for p in item['matches']}:
        raise ValueError('所选人员不属于这一审批对象，请选择对应任职')
    row = rows.get(rid); fields = {f['field']:f['value'] for f in item['fields']}; fields.update(extra)
    issues = list(item.get('documentIssues',[]))
    for issue in item.get('extractionIssues',[]):
        if issue.startswith('请补充'): continue
        if ('调整内容未识别完整' in issue or '否定的调整表述' in issue) and (extra or 'decisions' in override): continue
        if '识别到多个调整值' in issue and any(issue.startswith(LABELS.get(f,f)) for f in extra): continue
        issues.append(issue)
    if not row: issues.append(item.get('matchIssue') or '请先将审批涉及人员加入本月核算，再选择对应人员。')
    if not fields and not item['decisions']: issues.append('请补充调整字段和采用值。')
    for prefix in ROLES:
        if prefix+'姓名' in fields and not fields[prefix+'姓名'] and fields.get(prefix+'工号'):
            issues.append('请补充'+prefix+'姓名。')
    if 'ABC类别' in fields and fields['ABC类别'] not in {'A','B','C'}:issues.append('请选择有效的岗位类别。')
    if '周期剔除天数' in fields:
        import math
        try:
            value=float(fields['周期剔除天数'])
            if not math.isfinite(value) or value<0:raise ValueError()
        except (TypeError,ValueError):issues.append('周期剔除天数须为不小于零的有效数字。')
    if '招聘渠道' in fields and not fields['招聘渠道']: issues.append('请补充实际招聘渠道。')
    if row:
        v = row['values']; merged = {**v,**fields}
        if any(f.startswith(('招聘负责人','协助招聘人')) for f in fields):
            lead = staff(merged.get('招聘负责人工号')); assistant = staff(merged.get('协助招聘人工号'))
            if lead and assistant and lead == assistant: issues.append('招聘负责人和协助招聘人不能为同一人。')
        item['person'] = {'rowId':row['id'],'name':v.get('姓名',''),'employeeId':v.get('工号',''),'hireDate':v.get('入职日期','')}
    else: v = {}
    item['fields'] = [{'field':f,'label':LABELS.get(f,f),'before':v.get(f,''),'value':value} for f,value in fields.items()]
    item['issues'] = list(dict.fromkeys(issues))
    item['canMarkNoChange'] = not item.get('documentIssues') and (bool(row) or not item.get('matches'))
    same = bool(row) and all(same_value(f,v.get(f),value) and f not in row.get('unresolvedFields',[]) for f,value in fields.items())
    same = same and all(any(d.get('kind')==a['kind'] and d.get('action')=='exclude' for d in row.get('awardDecisions',[])) for a in item['decisions'])
    item['status'] = 'blocked' if issues else 'consistent' if same else 'ready'
    return item


def approval_sections(full):
    printed = printed_sections(full)
    if printed is not None:
        return printed
    parts = re.split(r'节点名称', full)
    main = parts[0]
    finals = list(re.finditer(r'(?:最终审批意见|最终意见)\s*[：:]?\s*', full))
    explicit = finals[-1] if finals else None
    if explicit:
        opinion = full[explicit.end():].split('节点名称')[0]
        return main[:explicit.start()] if len(parts) == 1 else main, [opinion]
    nodes = []
    for part in parts[1:]:
        part = re.split(r'(?:申请说明|申请内容)\s*[*＊：:]', part)[0]
        if '操作者' in part and re.search(r'直接上级|HSSC', part):
            opinions = re.findall(r'(?:^|\n)((?:同意|不同意|仅批准|批准|不发|不予发放)[^\n]+)', part)
            if opinions: nodes.append('\n'.join(dict.fromkeys(opinions)))
            continue
        marker = re.search(r'(?:审批意见|处理意见|意见)\s*[：:]?\s*', part)
        opinion = part[marker.end():] if marker else part
        opinion = re.split(r'\n\s*(?:操作时间|处理时间|审批时间|签字|签名|打印时间|打印人)\s*[：:]', opinion)[0]
        if opinion.strip(): nodes.append(opinion.strip())
    return main, nodes


def subject_groups(matches):
    groups = defaultdict(list)
    for person in matches:
        groups[compact(person['name'])].append(person)
    return list(groups.values()) or [[]]


def scoped_text(body, group, all_matches):
    names = {compact(p['name']) for p in all_matches}
    if len(names) < 2: return body
    own = {compact(p['name']) for p in group}
    result = []; current = set()
    pattern = '|'.join(re.escape(p['name']) for p in all_matches)
    for clause in re.split(r'[；;。\n]|[，,](?=\s*(?:'+pattern+r'))', body):
        mentioned = {name for name in names if name in compact(clause)}
        if mentioned: current = mentioned
        if not current or own & current: result.append(clause)
    return '。'.join(result)


def effective_changes(body, opinions, directory):
    fields, decisions, issues = extract_changes(body, directory)
    requested = dict(fields)
    for opinion in opinions:
        current = re.sub(r'(?:撤销|取消|推翻|不再执行)[^，,。；;\n]*(?:不发|不予发放)[^，,。；;\n]*', '', opinion)
        current = re.sub(r'(?:此前|之前|先前|原)[^，,。；;\n]*(?:不发|不予发放)[^，,。；;\n]*(?:撤销|取消|推翻|不再执行)', '', current)
        if re.search(r'(?<!不)(?:仅|只)?(?:批准|同意)\s*(?:剔除|扣除)?\s*\d+(?:\.\d+)?\s*天', current):
            current = re.sub(r'(?:不同意|不批准|不予批准)[^，,。；;\n]*(?:剔除|扣除)\s*\d+(?:\.\d+)?\s*天', '', current)
        if re.search(r'无需调整|无需修改|维持原资料|保持现有资料', current):
            fields, decisions, issues = {}, [], []
            continue
        if '周期剔除天数' in requested:
            current = re.sub(r'((?:仅|只)?(?:批准|同意))\s*(\d+(?:\.\d+)?)\s*天', r'\1剔除\2天', current)
        changed, exclusions, problems = extract_changes(current, directory)
        acknowledged = bool(re.search(r'(?<!不)(?:同意|通过|批准|符合规则|按申请|维持原申请|发放招聘奖金|发招聘奖金|发放内推奖金|发内推奖金)', current))
        if changed or exclusions or acknowledged:
            issues = [issue for issue in issues if '最终调整内容未识别完整' not in issue and '否定的调整表述' not in issue]
        for word, kind in [('招聘', 'recruitment'), ('内推', 'referral')]:
            if re.search(r'(?<!不)(?<!予)(?:同意|允许|正常|恢复|可以)?\s*发(?:放)?'+word+'奖金', current):
                decisions = [d for d in decisions if d['kind'] != kind]
                if any(d['kind'] == kind for d in exclusions):
                    problems.append('最终调整内容未识别完整，请核对相互冲突的发放意见。')
        for decision in exclusions:
            decisions = [d for d in decisions if d['kind'] != decision['kind']] + [decision]
        fields.update(changed)
        issues = [issue for issue in issues if not any(issue.startswith(LABELS.get(f, f)) for f in changed)]
        issues.extend(problems)
        unresolved = re.search(r'另行核定|另议|待确认|待核定|不能按申请|按(?:已)?沟通|暂不确定|以.*另行', current)
        rejection = re.search(r'不同意|不批准|不予批准|驳回', current)
        if unresolved or rejection or not (changed or exclusions or acknowledged):
            issues.append('最终调整内容未识别完整，请核对最终意见并补充采用值。')
    return fields, decisions, list(dict.fromkeys(issues)), requested


def conclusion_signature(store, state, item, doc):
    row_ids = {item['person'].get('rowId')} - {None, ''}
    if not row_ids: row_ids.update(p.get('rowId') for p in item['matches'] if p.get('rowId'))
    related = [r for r in state['rows'] if not row_ids or r['id'] in row_ids]
    facts = [{'id': r['id'], 'values': {k: v for k, v in r['values'].items() if k != '核算月份' and v is not None and v != ''}, 'unresolvedFields': r.get('unresolvedFields'),
              'provenance': r.get('provenance'), 'awardDecisions': r.get('awardDecisions')} for r in related]
    wording = item.get('excerpt', '')+'\n'+'\n'.join(item.get('finalOpinions', []))
    period = state['month'] if re.search(r'(?:本月|当月|本期|当期|20\d{2}年\d{1,2}月)[^。；\n]{0,20}(?:无需|不需|核算|适用|有效)', wording) else None
    return digest(json.dumps([facts, doc['sourceSignature'], doc['items'], period], sort_keys=True, ensure_ascii=False, default=str))


def legacy_scope(store, state, source_id, document):
    if document['issues']: return {}, False, []
    active = {o['id'] for o in state.get('operations', []) if o.get('active')}
    records = [r for r in state.get('reviewEntries', []) if r.get('sourceId') == source_id
               and (not r.get('operationId') or r['operationId'] in active)]
    applied = [r for r in records if r.get('applied') and not r.get('adoptedItems') and r.get('status') == '已认可' and r.get('scopeChecked')]
    if not applied: return {}, False, []
    if records[-1].get('status') != '已认可' or not records[-1].get('scopeChecked'):
        document['issues'].append('最新审批核对结论为'+records[-1].get('status', '待核实')+'，请重新核对认可状态与适用范围。')
        return {}, False, []
    source_ids = {source_id, *(sid for r in applied for sid in r.get('attachmentIds', []))}
    sources = {source['id']: source for source in state['sources']}
    for sid in source_ids:
        source = sources.get(sid, {})
        if not source.get('active', True) or source.get('error') or source.get('comparisonOnly') or not source.get('storedName'):
            return {}, False, []
        path = store._folder(state['month']) / 'sources' / source['storedName']
        if not path.is_file() or sha256(path.read_bytes()).hexdigest() != sid:
            return {}, False, []
    by_row = {}
    for review in applied:
        for rid in review.get('rowIds', []):
            entry = by_row.setdefault(rid, {'fields': {}, 'decisions': []})
            entry['fields'].update({e['field']: e['value'] for e in state.get('edits', [])
                if e.get('operationId') == review.get('operationId') and e.get('active', True)
                and e.get('evidenceId') == source_id and e['rowId'] == rid})
            entry['decisions'].extend({k: d[k] for k in ('kind', 'action')} for d in state.get('awardDecisions', [])
                if d.get('operationId') == review.get('operationId') and d.get('sourceId') == source_id and d['rowId'] == rid)
    checked_scope = next((r['personScope'] for r in reversed(records) if r.get('personScope')), [])
    complete = bool(records[-1].get('scopeComplete') and by_row and all(v['fields'] or v['decisions'] for v in by_row.values()))
    return by_row, complete, checked_scope


def inherit_legacy_scope(items, saved, complete, checked_scope, rows, source, document):
    scoped_names = {compact(person['name']) for person in checked_scope}
    retained = []
    for item in items:
        rid = item['person'].get('rowId')
        matches = [p['rowId'] for p in item['matches'] if p.get('rowId') in saved]
        if not rid and len(matches) == 1: rid = matches[0]
        if rid in saved:
            fields = {f['field']: f['value'] for f in item['fields']}
            fields = {**saved[rid]['fields'], **fields}
            item['fields'] = [{'field': field, 'label': LABELS.get(field, field), 'value': value} for field, value in fields.items()]
            item['decisions'] = item['decisions'] or saved[rid]['decisions']
            item = resolve_item(item, rows, {'rowId': rid} if rid in rows else {})
            item['legacyApplied'] = True
            if item['status'] != 'consistent':
                item['requiresRecheck'] = True
                item['issues'].append('旧审批已采用的资料发生变化，请重新核对。')
        elif not item['fields'] and not item['decisions'] and not item['extractionIssues']:
            if complete or scoped_names and compact(item['person'].get('name')) not in scoped_names: continue
        retained.append(item)
    represented = {item['person'].get('rowId') for item in retained}
    for rid, previous in saved.items():
        if rid in represented: continue
        row = rows.get(rid, {})
        values = row.get('values', {})
        person = {'rowId':rid, 'name':values.get('姓名', ''), 'employeeId':values.get('工号', ''), 'hireDate':values.get('入职日期', '')}
        item = {'id':digest(source['id']+'|legacy|'+rid), 'sourceId':source['id'], 'sourceName':source['name'],
                'person':person, 'matches':[person], 'fields':[{'field':f, 'label':LABELS.get(f,f), 'value':v} for f,v in previous['fields'].items()],
                'decisions':previous['decisions'], 'documentIssues':document['issues'], 'extractionIssues':[],
                'matchIssue':'旧审批对应人员已不在本月核算中，请重新核对。', 'excerpt':'已采用的审批核对记录',
                'pageNumbers':document['pageNumbers'], 'legacyApplied':True, '_previous':{}}
        item = resolve_item(item, rows)
        if item['status'] != 'consistent':
            item['requiresRecheck'] = True
            item['issues'].append('旧审批已采用的资料发生变化，请重新核对。')
        retained.append(item)
    names = {compact(item['person'].get('name')) for item in retained}
    for person in checked_scope:
        if compact(person['name']) in names: continue
        identity = {'name':person['name'], 'rowId':person.get('rowId') or '', 'employeeId':'', 'hireDate':''}
        item = {'id':digest(source['id']+'|scope|'+compact(person['name'])), 'sourceId':source['id'], 'sourceName':source['name'],
                'person':identity, 'matches':[identity], 'fields':[], 'decisions':[], 'documentIssues':document['issues'], 'extractionIssues':[],
                'matchIssue':person['reason'], 'excerpt':person['reason'], 'pageNumbers':document['pageNumbers'], '_previous':{}}
        retained.append(resolve_item(item, rows))
    return retained


def proposals(store, state):
    folder = store._folder(state['month']); sources = [s for s in state['sources'] if s.get('attachment')
        and s.get('active',True) and not s.get('error') and not s.get('comparisonOnly')]
    if not sources: return {'revision':state['revision'],'documents':[],'items':[]}
    from . import recruitment_reference_facts as reference
    if 'referenceFacts' not in state:state=reference.project(folder,{**state})
    reference_by_row=state['referenceFacts']['byRowId']
    directory = Directory(folder, state); rows = {r['id']:r for r in state['rows']}; documents = []; items = []
    for source in sources:
        result = {'sourceId':source['id'],'name':source['name'],'items':[], 'issues':[], 'pageNumbers':[],
                  'status':'blocked','label':'需补充清晰原件','readyCount':0,'blockedCount':1,'consistentCount':0,'attachmentIds':[]}
        try:
            doc = extract_document(folder/'sources'/source['storedName'], folder/'documents'/source['id'])
        except (ValueError, OSError) as exc:
            result['issues'] = [str(exc)]; documents.append(result); continue
        full = body_text(doc)
        result['pageNumbers'] = [p['page'] for p in doc['pages'] if not p.get('blank')]
        result['blankPages'] = [p['page'] for p in doc['pages'] if p.get('blank')]
        result['unreadablePages'] = unreadable_pages(doc)
        result['mentionedAttachments'] = mentioned_attachments(doc)
        available = [s for s in state['sources'] if s.get('active', True) and not s.get('error') and not s.get('comparisonOnly')]
        result['referencedAttachments'] = []
        for name in mentioned_attachments(doc, include_pdf=True):
            required = not name.lower().endswith('.pdf')
            matches = [s['id'] for s in available if s['name'] == name
                       or not required and s['name'].casefold() == name.casefold()]
            result['referencedAttachments'].append({'name': name, 'sourceIds': matches,
                'status': 'available' if matches else 'reference_only', 'required': required})
        result['attachmentIds'] = list(dict.fromkeys(sid for ref in result['referencedAttachments'] for sid in ref['sourceIds']))
        missing = [ref['name'] for ref in result['referencedAttachments'] if ref['required'] and not ref['sourceIds']]
        if missing: result['issues'].append('缺少审批引用附件：'+'、'.join(missing))
        unavailable = [p['page'] for p in doc['pages'] if not p.get('blank') and p.get('ocrError')=='unavailable']
        if unavailable:
            result['issues'].append('第 '+'、'.join(map(str,unavailable))+' 页扫描件识别服务暂不可用，请联系管理员检查服务；原件已保留。')
        unread = [page for page in result['unreadablePages'] if page not in unavailable]
        if unread: result['issues'].append('第 '+ '、'.join(map(str,unread))+' 页内容未读清，请补充清晰原件。')
        if not full.strip() and not unavailable: result['issues'].append('审批文件没有可识别内容，请补充有内容的审批原件。')
        # Explicit overall status can block adoption; a historical rejection
        # inside an approval log is not treated as the final outcome.
        if re.search(r'(?:流程状态|审批状态|最终结果)\s*[：:]?\s*(?:未结束|审批中|已驳回|已撤回|已拒绝)',full):
            result['issues'].append('审批尚未通过，请补充已通过的审批原件。')
        main, opinions = approval_sections(full)
        evidence = []
        for evidence_source in state['sources']:
            if evidence_source['id'] not in {source['id'], *result['attachmentIds']}: continue
            path = folder / 'sources' / evidence_source['storedName']
            evidence.append([evidence_source['id'], evidence_source.get('active', True), digest(path.read_bytes()) if path.is_file() else None])
        result['sourceSignature'] = digest(json.dumps([full, evidence], ensure_ascii=False))
        chunks = re.split(r'(?=\n\s*\d+[.、]\s*在)', main)
        applicant = source['name'].split('提交')[0]
        active = {o['id'] for o in state.get('operations',[]) if o.get('active')}
        adopted = {a['id']:a for r in state.get('reviewEntries',[]) if r.get('sourceId')==source['id']
                   and r.get('applied') and (not r.get('operationId') or r['operationId'] in active)
                   for a in r.get('adoptedItems',[])}
        document_matches, _ = directory.target(main, applicant)
        main_names = {compact(person['name']) for person in document_matches}
        for opinion in opinions:
            final_matches, _ = directory.target(opinion, applicant)
            for person in final_matches:
                if person not in document_matches: document_matches.append(person)
            for name in re.findall(r'(?:^|[；;。\n])\s*([\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z .·-]{1,59}?)\s*(?:(?:批准|同意)(?:剔除|扣除)|维持原申请|(?:不发|不予发放|发放)(?:招聘|内推)奖金|(?:招聘渠道|岗位类别|ABC类别)(?:修改|调整|改)为)', opinion):
                name = name.strip()
                if re.match(r'撤销|取消|推翻|不再|此前|之前|先前|原|同意|不同意|仅|只|最终|不予', name): continue
                if not any(compact(person['name']) == compact(name) for person in document_matches):
                    document_matches.append({'name':name, 'employeeId':'', 'hireDate':'', 'offers':set()})
        scopes = [(body, *directory.target(body, applicant)) for body in chunks]
        for group in subject_groups(document_matches):
            if group and compact(group[0]['name']) not in main_names:
                scopes.append(('', group, '有多名同名人员或多次任职，请选择本次审批对应的人员。' if len(group) > 1 else ''))
        legacy, complete, checked_scope = legacy_scope(store, state, source['id'], result)
        recognised = []
        for body, matches, reason in scopes:
            initial_fields, initial_decisions, _ = extract_changes(body, directory)
            if len(chunks) > 1 and not matches and not initial_fields and not initial_decisions: continue
            for group in subject_groups(matches):
                scoped = scoped_text(body, group, matches)
                final = [scoped_text(opinion, group, document_matches) for opinion in opinions]
                fields, decisions, extraction_issues, requested = effective_changes(scoped, final, directory)
                dated = [p for p in group if p['hireDate'] in dates(scoped)]
                if dated: group = dated
                person = group[0] if len(group) == 1 else {}
                match_issue = '' if len(group) == 1 else reason
                row = rows.get(person.get('rowId')); v = row['values'] if row else {}
                if not row and len(group) == 1:
                    hire = person.get('hireDate','')
                    historical = hire and hire[:7].replace('-','') < str(state['month'])
                    match_issue = (person['name']+'（'+hire+'入职）未纳入本月核算，请先导入或承接上月核算表。') if historical else person['name']+'未纳入本月核算，请先补充人员。'
                if fields.get('周期剔除天数',0): fields['周期剔除依据'] = source['name']
                if fields.get('推荐人姓名') == '' and '协助招聘人姓名' in fields and v.get('招聘渠道') == '内推' and '招聘渠道' not in fields:
                    fields['招聘渠道'] = ''
                identity = compact(group[0]['name']) if group else 'manual'
                iid = digest(source['id']+'|'+identity+'|'+compact(body))
                if any(i['id'] == iid for i in recognised): continue
                legacy_identity = person.get('employeeId') or person.get('name') or body.strip()
                legacy_id = digest(source['id']+'|'+legacy_identity+'|'+json.dumps(fields,sort_keys=True,ensure_ascii=False)+'|'+json.dumps(decisions))
                item = {'id':iid, 'sourceId':source['id'], 'sourceName':source['name'],
                        'person':{k:person.get(k,'') for k in ('name','employeeId','hireDate','rowId')},
                        'matches':[{k:p.get(k,'') for k in ('name','employeeId','hireDate','rowId')} for p in group],
                        'fields':[{'field':f,'label':LABELS.get(f,f),'before':v.get(f,''),'value':value} for f,value in fields.items()],
                        'requestedFields':requested, 'finalOpinions':final, 'decisions':decisions,
                        'documentIssues':list(result['issues']),'extractionIssues':extraction_issues,'matchIssue':match_issue,
                        'excerpt':scoped.strip() or '\n'.join(final).strip(), 'pageNumbers':result['pageNumbers']}
                previous = adopted.get(iid) or adopted.get(legacy_id) or (adopted.get(digest(source['id']+'|manual')) if not matches else None) or {}
                if not previous and row:
                    # Cleaning OCR columns changes the text-derived item ID.
                    # Reuse a unique review for this exact source and employment,
                    # never a name-only match or another person's saved decision.
                    prior = [a for a in adopted.values() if a.get('rowId') == row['id']]
                    if len(prior) == 1: previous = prior[0]
                source_changed = previous.get('sourceSignature') and previous['sourceSignature'] != result['sourceSignature']
                prior_override={k:deepcopy(previous[k]) for k in ('rowId','fields','decisions') if k in previous and (k == 'rowId' or previous.get('outcome') != 'no_change') and not source_changed}
                referenced=set(previous.get('referenceFields',[]))
                for field in referenced:
                    prior_override.get('fields',{}).pop(field,None)
                valid_references={p['id']:p['signature'] for p in reference_by_row.get(previous.get('rowId',item['person'].get('rowId')),[])}
                reference_current=all(valid_references.get(s['proposalId'])==s['signature'] for s in previous.get('referenceSelections',[]))
                if reference_current:
                    for field in referenced:
                        if same_value(field,rows.get(previous.get('rowId'),{}).get('values',{}).get(field),previous.get('fields',{}).get(field)):
                            prior_override.setdefault('fields',{})[field]=previous['fields'][field]
                item = resolve_item(item, rows, prior_override)
                if previous.get('referenceSelections') and not reference_current:
                    item.update(status='blocked', issues=item['issues']+['参考来源或对应任职已变化，请重新核对。'])
                if source_changed and item['status'] == 'consistent':
                    item.update(status='blocked', issues=['审批原件或引用附件已变化，请重新核对。'])
                item['_previous'] = previous
                recognised.append(item)
        if legacy:
            recognised = inherit_legacy_scope(recognised, legacy, complete, checked_scope, rows, source, result)
        result['items'] = [i['id'] for i in recognised]
        for item in recognised:
            previous = item.pop('_previous')
            item['factSignature'] = conclusion_signature(store, state, item, result)
            if previous.get('outcome') == 'no_change' and previous.get('factSignature') == item['factSignature'] and not result['issues']:
                item.update(status='consistent', issues=[], outcome='no_change')
            elif previous and (item['status'] != 'consistent' or previous.get('outcome') == 'no_change'):
                if item['status'] == 'consistent': item['status'] = 'blocked'
                item['requiresRecheck'] = True
                item['issues'].append('采用后核算资料已变更，请核对是否仍需执行这项审批调整。')
        for item in recognised:
            item['referenceOptions']=[{'field':field,'value':proposal['values'][field],
                'label':str(proposal['values'][field])+' · '+'、'.join(ref['sourceName']+' '+ref['sheet']+'!'+ref['cell'] for ref in proposal['refs']),
                'sources':proposal['refs'],'referenceProposal':{'proposalId':proposal['id'],'signature':proposal['signature']}}
                for proposal in reference_by_row.get(item['person'].get('rowId'),[])
                for field in proposal['values']
                if any(f['field']==field and not text(f['value']) for f in item['fields'])]
        result['readyCount'] = sum(i['status']=='ready' for i in recognised)
        result['blockedCount'] = sum(i['status']=='blocked' for i in recognised)
        result['consistentCount'] = sum(i['status']=='consistent' for i in recognised)
        if result['issues'] and not recognised: result['blockedCount'] = 1
        result['status'] = 'blocked' if result['blockedCount'] else 'ready' if result['readyCount'] else 'consistent'
        result['detail']='；'.join(dict.fromkeys(result['issues']+[p for i in recognised for p in i['issues']])) or '；'.join(
            i['person'].get('name','待匹配人员')+'：'+'、'.join(f['label'] for f in i['fields'] if f['field']!='周期剔除依据') for i in recognised)
        result['label'] = ' · '.join(([f"{result['readyCount']} 项待采用"] if result['readyCount'] else [])+
                                   ([f"{result['blockedCount']} 项待补充"] if result['blockedCount'] else [])) or '已与核算一致'
        documents.append(result); items.extend(recognised)
    return {'revision':state['revision'],'documents':documents,'items':items}


def project(store, state):
    """Enrich read responses without rewriting draft data or adopting approvals."""
    data = proposals(store, state); docs = {d['sourceId']:d for d in data['documents']}
    if not docs: return state, data
    projected = {**state, 'sources':[{**s, 'approvalSummary':docs[s['id']]} if s['id'] in docs else s for s in state['sources']], 'todos':[]}
    seen=set()
    for task in state.get('todos',[]):
        if task['kind'] != 'attachment_review': projected['todos'].append(task); continue
        for sid in task.get('sourceIds',[]):
            doc = docs.get(sid)
            if not doc: projected['todos'].append(task); continue
            if doc.get('status') == 'consistent': continue
            seen.add(sid)
            matching = [i for i in data['items'] if i['sourceId']==sid]
            detail = '；'.join(dict.fromkeys(doc['issues']+[p for i in matching for p in i['issues']]))
            if not detail: detail = '；'.join(i['person']['name']+'：'+'、'.join(f['label'] for f in i['fields'] if f['field']!='周期剔除依据') for i in matching)
            projected['todos'].append({**task, 'sourceIds':[sid], 'title':'补充审批调整资料' if doc.get('blockedCount') else '核对并采用审批调整', 'detail':detail})
    for sid,doc in docs.items():
        if sid in seen or doc.get('status')=='consistent':continue
        projected['todos'].append({'id':digest('approval:'+sid),'kind':'attachment_review','rowIds':[],
            'sourceIds':[sid],'title':'补充审批调整资料' if doc.get('blockedCount') else '核对并采用审批调整',
            'detail':'；'.join(doc['issues']+[p for i in data['items'] if i['sourceId']==sid for p in i['issues']])})
    return projected, data


def preview(store, month, payload):
    from .recruitment_reviews import prepare_preview
    state = store.read(month); store._check(state,payload.get('revision'))
    data = proposals(store,state); items = {i['id']:i for i in data['items']}; docs = {d['sourceId']:d for d in data['documents']}
    selected = payload.get('itemIds')
    if not isinstance(selected,list) or not selected or len(selected)>500 or any(not isinstance(i,str) for i in selected): raise ValueError('请选择需要采用的审批调整')
    if len(set(selected)) != len(selected) or any(i not in items for i in selected): raise ValueError('审批调整已变化，请重新打开清单')
    overrides = payload.get('overrides',{})
    if not isinstance(overrides,dict) or set(overrides)-set(selected):raise ValueError('只能补充本次选中的审批调整')
    outcomes = payload.get('outcomes', {})
    if not isinstance(outcomes, dict) or set(outcomes)-set(selected) or any(v != 'no_change' for v in outcomes.values()):
        raise ValueError('审批核对结论无效')
    from . import recruitment_reference_facts as reference
    selections=payload.get('referenceSelections',[])
    if not isinstance(selections,list) or len(selections)>500:raise ValueError('参考事实选择格式无效')
    references=defaultdict(list)
    for selection in selections:
        if not isinstance(selection,dict) or set(selection)!={'itemId','proposalId','signature'} or selection['itemId'] not in selected:
            raise ValueError('参考事实只能用于本次选中的审批调整')
        references[selection['itemId']].append({k:selection[k] for k in ('proposalId','signature')})
    rows = {r['id']:r for r in state['rows']}
    confirmed_selections=[]
    edits = []; decisions = []; reviews = []; by_source = defaultdict(list)
    for iid in selected:
        change=deepcopy(overrides.get(iid) or {})
        resolved=reference.selection_edits(store._folder(month),state,references.get(iid,[]))
        reference_fields=[]
        known={f['field']:f['value'] for f in items[iid]['fields']}
        for edit in resolved:
            rid=change.get('rowId',items[iid]['person'].get('rowId'))
            field=edit['field']
            if edit['rowId']!=rid or field not in known or field in change.get('fields',{}):
                raise ValueError('参考事实只能补充该审批对象尚未明确的人员字段')
            if text(known[field]):
                if not same_value(field,known[field],edit['value']):
                    raise ValueError('参考人员事实与审批已明确的人员字段不一致')
                continue
            change.setdefault('fields',{})[field]=edit['value']
            reference_fields.append(field)
        item = resolve_item(deepcopy(items[iid]),rows,change)
        item['referenceSelections']=references.get(iid,[])
        item['referenceFields']=reference_fields
        confirmed_selections.extend(item['referenceSelections'])
        if outcomes.get(iid) == 'no_change':
            if item['documentIssues'] or not item.get('canMarkNoChange'):
                raise ValueError('请先处理：'+'；'.join(item['documentIssues'] or [item.get('matchIssue') or '请核对审批对应人员']))
            if references.get(iid) or overrides.get(iid, {}).get('fields') or 'decisions' in overrides.get(iid, {}):
                raise ValueError('无需调整不能同时提交采用值')
            item['outcome'] = 'no_change'
            item['factSignature'] = conclusion_signature(store, state, item, docs[item['sourceId']])
            by_source[item['sourceId']].append(item)
            continue
        if item['status'] != 'ready': raise ValueError('请先处理：'+'；'.join(item['issues'] or ['该项已与核算一致']))
        sid = item['sourceId']; rid = item['person']['rowId']; by_source[sid].append(item)
        edits.extend({'rowId':rid, 'field':f['field'], 'value':f['value'], 'evidenceId':sid,
                      'evidencePages':item['pageNumbers'], 'reason':'核对审批调整：'+item['sourceName']} for f in item['fields'] if f['field'] not in item['referenceFields'])
        decisions.extend({**d,'rowId':rid,'sourceId':sid,'pageNumbers':item['pageNumbers']} for d in item['decisions'])
    # Do not silently use upload order to settle conflicting approvals.
    cells = {}
    for edit in edits:
        key = (edit['rowId'],edit['field'])
        if key in cells and edit['field']=='周期剔除依据':
            cells[key]['value']+='；'+edit['value'];continue
        if key in cells and cells[key]['value'] != edit['value']: raise ValueError('所选审批对同一人员的'+LABELS.get(edit['field'],edit['field'])+'有不同调整值，请分开核对。')
        cells.setdefault(key,edit)
    for sid, selected_items in by_source.items():
        doc = docs[sid]
        remaining = [i for i in data['items'] if i['sourceId']==sid and i['id'] not in selected and i['status']!='consistent']
        reviews.append({'sourceId':sid,'pageNumbers':doc['pageNumbers'],'attachmentIds':doc['attachmentIds'],
                        'status':'已认可','scopeChecked':True,'scopeComplete':not remaining and not doc['issues'],'personScope':None,
                        'note':'已核对，无需调整。' if all(i.get('outcome') == 'no_change' for i in selected_items) else '已核对并采用识别的人员及调整内容。','itemIds':[i['id'] for i in selected_items],
                        'adoptedItems':[{'id':i['id'],'rowId':i['person'].get('rowId',''),'fields':{f['field']:f['value'] for f in i['fields']},
                                         'referenceFields':i.get('referenceFields',[]),'referenceSelections':i.get('referenceSelections',[]),'decisions':i['decisions'],'outcome':i.get('outcome','apply'),'factSignature':i['factSignature'],'sourceSignature':doc['sourceSignature']} for i in selected_items],
                        'rowIds':list(dict.fromkeys(i['person']['rowId'] for i in selected_items if i['person'].get('rowId')))})
    origin = '审批核对，无需调整' if len(outcomes) == len(selected) else '采用审批调整'
    return prepare_preview(store,month,state['revision'],list(cells.values()),origin=origin,
                           decisions=decisions,approval_reviews=reviews,reference_selections=confirmed_selections)

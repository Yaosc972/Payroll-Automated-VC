"""Content-based source reading for the persistent recruitment worksheet.

This reader preserves source locations and employment dates. It does not calculate
awards, apply approvals, or infer payment from a historical amount.
"""
from __future__ import annotations

from datetime import date, datetime
from io import BytesIO
from pathlib import Path, PurePosixPath
import hashlib
import posixpath
import re
import tempfile
from typing import Any
from xml.etree import ElementTree as ET
import zipfile

from .recruitment_import_validation import (
    STANDARD_IMPORT_HEADERS, _as_date, _convert_xls_to_xlsx, _local_name,
    _parse_xlsx_row, _read_shared_strings, _normalize_offer_channel, _referrer_from_other_channel, offer_validity,
)

ALIASES = {
    '姓名': ['parent_Name', 'Name'], '工号': ['JobNumber', 'LookupPrefix_LURecord_JobNumber'],
    '证件号': ['身份证', '证件号码', 'parent_IDNumber', 'IDNumber'],
    '入职日期': ['EntryDate'], '人员状态': ['EmployeeStatus'],
    '转正日期': ['实际转正日期', 'RegularizationDate'],
    '最后工作日': ['离职日期', 'LastWorkDate'],
    '工作地': ['办公地址', '工作地区'], '职级': ['OIdJobLevel', '录用职级'],
    '职位': ['OIdJobPosition_Name', '录用职位'],
    '录用岗位': ['ApplicantPosition'], '录用用工形式': ['EmploymentForm', '用工形式'],
    '直接上级姓名': [], '间接上级1姓名': [], '间接上级2姓名': [], '间接上级3姓名': [], '间接上级4姓名': [],
    '二级组织': ['二级部门', 'LookupPrefix_OIdDepartment_SecondLevelOrganization'],
    '三级组织': ['三级部门', 'LookupPrefix_OIdDepartment_ThirdLevelOrganization'],
    '四级组织': ['四级部门', 'LookupPrefix_OIdDepartment_FourthLevelOrganization'],
    '五级组织': ['五级部门', 'LookupPrefix_OIdDepartment_FifthLevelOrganization'],
    '直线经理': ['直接上级', 'POIdEmpAdmin-ExportName'],
    '直线经理工号': ['直接上级工号', 'POIdEmpAdmin-StaffCode'],
    '海外offer流程编号': ['offer流程编号', 'offer编码'],
    '海外招聘需求编号': ['招聘需求编码', 'LookupPrefix_RecruitmentRequirement_RequirementCode'],
    'ABC类别': ['编制ABC分类', 'LookupPrefix_RecruitmentRequirement_extzhiweifenlei_109025_933701443'],
    '招聘负责人工号': ['extzhuanyuan12_109025_1971095424-StaffCode', 'HrDutyUserId-StaffCode'],
    '招聘负责人姓名': ['招聘负责人', 'extzhuanyuan12_109025_1971095424-ExportName', 'HrDutyUserId-ExportName'],
    '协助招聘人工号': ['协助招聘负责人工号', 'extxiezhuzhaopinfuzerengonghao_109025_801104894'],
    '协助招聘人姓名': ['协助招聘负责人姓名', 'extxiezhuzhaopinfuzeren_109025_1163526586'],
    '招聘启动日期': ['LookupPrefix_RecruitmentRequirement_CreateDate'],
    '招聘渠道': ['extQ20210635_109025_2041445622'],
    '推荐人工号': ['内推人工号', 'extQ202106334_109025_847145517-StaffCode'],
    '推荐人姓名': ['内推人', '内推人姓名', 'extQ202106334_109025_847145517-ExportName'],
    '周期剔除天数': ['周期天数剔除'], '人工备注': ['备注'],
    '奖金地区类型': ['发达国家/发展中国家'], '标准币种': ['奖金对应币种'],
    '原计划入职日期': [], '计划入职日期': [], '上次离职日期': [],
    '是否虚拟员工': [], '人事入职日期': [], '是否二次入职': [], '人员来源': [], '体系外人员编号': [],
    '其他渠道': ['其他招聘渠道', '其他渠道说明', '其他渠道名称'],
    '招聘渠道说明': ['渠道说明', '招聘来源说明', '招聘说明', '说明'],
    '招聘渠道备注': ['招聘备注', '录用备注', 'Offer备注', '备注', '备注说明', 'Remarks', 'remarks', 'Remark', 'remark', 'Notes', 'notes'],
    '数据动作': [], '申请单编号': [], '审批状态': ['ApprovalStatus', '文档状态'],
    '是否作废': [], '状态': [],
    '应届校招': [], '延后入职原因': [], '管培生已批名单资格': [],
    '周期豁免依据': [], '管培生资格依据': [], '周期剔除依据': [],
    '二次入职专项口径依据': [], '旧特殊规则依据': [],
    '推荐人与候选人上下级关系': [], '推荐人是否直接/间接上级': [], '推荐人转正日期': [],
}
PARSER_VERSION = 18
DATE_FIELDS = {'入职日期','候选人入职时间','转正日期','最后工作日','招聘启动日期','原计划入职日期','计划入职日期','上次离职日期',
               '招聘负责人入职日期','招聘负责人最后工作日','协助招聘人入职日期','协助招聘人最后工作日','推荐人入职日期','推荐人最后工作日','推荐人转正日期'}
FIELDS = set(STANDARD_IMPORT_HEADERS) | set(ALIASES) | DATE_FIELDS
HEADER_NAMES = FIELDS | {s for values in ALIASES.values() for s in values} | {
    '验证唯一','事项分类','申请说明','招聘周期特殊剔除时间（天）','离职类型',
    'ChangeReason','TransitionTypeOID','ProbationStopDate','人员来源',
}
DEPRECATED_FIELDS={'职族','职类','职族分类','海外招聘需求编号'}


def text(value):
    return '' if value is None else str(value).strip()


def canonical_header(value):
    # Business explanations below a newline are not part of the column name.
    return text(value).split('\n')[0].strip()


def date_text(value):
    if isinstance(value, (date, datetime)):
        return value.strftime('%Y-%m-%d')
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10]).isoformat()
        except ValueError:
            pass
    parsed = _as_date(value)
    return parsed.strftime('%Y-%m-%d') if parsed else ''


def json_value(value):
    return value.isoformat() if isinstance(value, (datetime, date)) else value


def digest(value):
    return hashlib.sha256(text(value).encode('utf-8')).hexdigest()[:24]


def classify(headers, sheet_name):
    names = set(headers)
    if sheet_name == '附件一-招聘奖金核算明细' or '验证唯一' in names:
        return 'ledger'
    if sheet_name == '导入_月度数据':
        return 'supplement'
    if '事项分类' in names and ('申请说明' in names or '申请单编号' in names):
        return 'approval'
    if {'JobNumber', 'LastWorkDate'} <= names and ('ChangeReason' in names or 'TransitionTypeOID' in names):
        return 'resignation'
    if {'工号', '最后工作日'} <= names and '离职类型' in names:
        return 'resignation'
    if 'LookupPrefix_RecruitmentRequirement_extzhiweifenlei_109025_933701443' in names:
        return 'domestic_offer'
    if 'offer编码' in names and ('编制ABC分类' in names or '招聘需求编码' in names):
        return 'overseas_offer'
    if {'JobNumber', 'EntryDate'} <= names or ({'工号', '入职日期', '人员状态'} <= names and ('offer流程编号' in names or '二级部门' in names or '人员来源' in names)):
        return 'roster'
    if names & {'身份证','证件号','证件号码','parent_IDNumber','IDNumber'} and names & {'编制ABC分类','招聘负责人工号','招聘负责人'}:
        return 'domestic_offer'
    if '体系外人员编号' in names or sheet_name == '导入_月度数据':
        return 'supplement'
    return 'unknown'


def normalize(raw, columns, role):
    values, field_columns = {}, {}
    for field in FIELDS:
        for candidate in [field] + ALIASES.get(field, []):
            if candidate in raw and raw[candidate] not in ('', None):
                value = raw[candidate]
                values[field] = (date_text(value) or text(value)) if field in DATE_FIELDS else json_value(value)
                field_columns[field] = columns[candidate]
                break
    # In a selected opening ledger an empty optional relationship is a saved
    # relationship state, unlike a column missing from a partial import.
    if role == 'ledger':
        for field in ('协助招聘人工号','协助招聘人姓名','推荐人工号','推荐人姓名'):
            if field in values: continue
            header=next((h for h in [field]+ALIASES.get(field,[]) if h in raw),None)
            if header is not None:
                values[field]='';field_columns[field]=columns[header]
    if '工号' in values:
        # Domestic exports sometimes contain "name/zt123".
        match = re.search(r'(?i)\bzt\d+\b', text(values['工号']))
        if match: values['工号'] = match.group(0)
    if role == 'roster':
        # An exported empty monthly date is a real cell, not a missing column.
        # Preserve its location so a later month can clear a previously saved date.
        for field in ('转正日期','最后工作日'):
            if field in values: continue
            header=next((h for h in [field]+ALIASES.get(field,[]) if h in raw),None)
            if header is not None:
                values[field]='';field_columns[field]=columns[header]
        src = text(values.get('人员来源'))
        native_oehr = {'姓名','工号','offer流程编号','入职日期','人员状态','办公地址','二级部门'} <= set(raw)
        if src == 'OEHR入职' or (not src and native_oehr):
            values['人员来源']='OEHR入职'
            values['标签分类'] = '海外'
            if '转正日期' in values:values['转正日期']=''
        elif 'JobNumber' in raw or src == 'EHR入职':
            values['标签分类'] = '国内'
            values['工作地']='中国大陆'
        if values.get('入职日期'):
            values['候选人入职时间']=values['入职日期']
            field_columns['候选人入职时间']=field_columns['入职日期']
        # Migrated records retain source facts; scope is resolved from organization later.
    if role in {'domestic_offer','overseas_offer'}:
        values['录用有效性'] = offer_validity(values, role)
        values['原始ABC类别'] = values.get('ABC类别','')
        values['原始招聘渠道'] = values.get('招聘渠道','')
        if role == 'overseas_offer':
            channel, uncertain = _normalize_offer_channel(values.get('招聘渠道'), values.get('其他渠道'),
                [values.get('招聘渠道说明'), values.get('招聘渠道备注')])
            values['招聘渠道'] = channel
            values['渠道待核'] = uncertain
            raw_other = text(values.get('其他渠道'))
            inferred_no, inferred_name = _referrer_from_other_channel(values.get('原始招聘渠道'), raw_other)
            numbers = sorted(set(re.findall(r'(?i)(?<![a-z0-9])(?:zt|lg)\d+(?![a-z0-9])', raw_other.lower())))
            if inferred_no and channel=='内推' and not uncertain:
                explicit = text(values.get('推荐人工号')).lower()
                if len(numbers) > 1 or explicit and explicit != inferred_no:
                    values['推荐人说明冲突'] = {'values':list(dict.fromkeys(([explicit] if explicit else [])+numbers)), 'description':raw_other}
                elif not explicit:
                    values['推荐人工号']=inferred_no
                    field_columns['推荐人工号']=field_columns['其他渠道']
                    if inferred_name and not text(values.get('推荐人姓名')):
                        values['推荐人姓名']=inferred_name
                        field_columns['推荐人姓名']=field_columns['其他渠道']
    if text(values.get('ABC类别')) in {'A类','B类','C类'}:
        values['ABC类别']=text(values['ABC类别'])[0]
    return values, field_columns


def _sheets(archive):
    rels = ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))
    targets = {r.attrib['Id']: r.attrib.get('Target','') for r in rels}
    root = ET.fromstring(archive.read('xl/workbook.xml'))
    for sheet in root.iter():
        if _local_name(sheet.tag) != 'sheet': continue
        rid = sheet.attrib.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
        target = targets.get(rid,'')
        path = target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/'+target)
        yield sheet.attrib.get('name',''), path


def _sheet_records(archive, path, shared, name, source_id, *, personnel_only=False):
    buffered, records = [], []
    headers = None
    role = 'unknown'
    def consume(number, row):
        raw, columns, cells = {}, {}, []
        for col, header in headers.items():
            val = row.get(col,'')
            if header and header not in raw:
                raw[header] = val; columns[header] = col + 1
            if val not in ('',None):
                cells.append({'column': col+1, 'label': full_headers.get(col,header), 'value': json_value(val)})
        vals, locs = normalize(raw, columns, role)
        if not any(text(vals.get(f)) for f in ('姓名','工号','证件号','海外offer流程编号','体系外人员编号','申请单编号')): return
        if vals.get('姓名') in {'姓名','合计'} or vals.get('工号')=='工号': return
        available_fields=[f for f in FIELDS if any(h in raw for h in [f]+ALIASES.get(f,[]))]
        records.append({'values': vals, 'fieldColumns': locs, 'availableFields':available_fields,
                        'rawValues':{field:json_value(row.get(col-1,'')) for field,col in locs.items()}, 'ref': {'sourceId':source_id,'sheet':name,'row':number},
                        'role':role, 'historyCells':cells if role=='ledger' else [],
                        'sourceScope':('overseas' if vals.get('标签分类')=='海外' else 'domestic' if vals.get('标签分类')=='国内' else 'unknown') if role=='roster' else '',
                        'scopeBasis':('native_oehr_schema' if role=='roster' and not text(raw.get('人员来源')) and vals.get('人员来源')=='OEHR入职'
                                      else 'native_ehr_schema' if role=='roster' and 'JobNumber' in raw else '人员来源' if role=='roster' and text(raw.get('人员来源')) else '')})
    def prepare():
        nonlocal headers, role, full_headers
        if not buffered: headers={}; return
        index=max(range(len(buffered)),key=lambda i:sum(canonical_header(v) in HEADER_NAMES for v in buffered[i][1].values()))
        base=buffered[index][1]
        headers={col:canonical_header(v) for col,v in base.items() if text(v)}
        role=classify(headers.values(),name)
        if personnel_only:
            names=set(headers.values())
            identity_fields={'姓名','工号','证件号','体系外人员编号','海外offer流程编号'}
            person_headers={h for field in identity_fields for h in [field]+ALIASES.get(field,[])}
            role='cumulative' if names & person_headers else 'unknown'
        full_headers=dict(headers)
        start=index+1
        # The actual historical template has a second header row for award nodes.
        if role=='ledger' and start<len(buffered):
            sub=buffered[start][1]
            if any('发放' in text(v) for v in sub.values()) and not text(sub.get(1)):
                upper=buffered[index-1][1] if index else {}
                upper_group=''
                group=''
                for col in sorted(set(base)|set(sub)|set(upper)):
                    if text(upper.get(col)): upper_group=canonical_header(upper[col])
                    if text(base.get(col)): group=canonical_header(base[col])
                    if text(sub.get(col)):
                        # Repeated 姓名/工号 subheaders belong to different
                        # manager levels, not the candidate's identity columns.
                        if re.fullmatch(r'直接上级|间接上级[1-4]',upper_group) and text(sub[col]) in {'姓名','工号'}:
                            headers[col]=upper_group+text(sub[col]);full_headers[col]=headers[col]
                            continue
                        parent=upper_group if isinstance(sub[col],(int,float)) and 200001<=sub[col]<=209912 else group
                        full_headers[col]=f'{parent} / {text(sub[col])}'
                        if col not in headers: headers[col]=canonical_header(sub[col])
                    elif col not in headers and text(upper.get(col)) and upper_group not in {'公式','花名册','判断','offer报表','招聘需求报表'}:
                        headers[col]=upper_group;full_headers[col]=upper_group
                start+=1
        if role != 'unknown':
            for n,row in buffered[start:]: consume(n,row)
    full_headers={}
    with archive.open(path) as stream:
        for _,element in ET.iterparse(stream,events=('end',)):
            if _local_name(element.tag)!='row': continue
            number=int(element.attrib.get('r') or 0)
            parsed=_parse_xlsx_row(element,shared); element.clear()
            if headers is None:
                buffered.append((number,parsed))
                if len(buffered)==12: prepare(); buffered.clear()
            elif role!='unknown': consume(number,parsed)
    if headers is None: prepare()
    return {'name':name,'role':role,'recordCount':len(records)},records


def read_source(path: Path, source_id: str, *, content: bytes | None = None, personnel_only=False):
    if path.suffix.lower()=='.xls':
        with tempfile.TemporaryDirectory() as tmp:
            if content is not None:
                path=Path(tmp)/path.name
                path.write_bytes(content)
            return read_source(_convert_xls_to_xlsx(path,Path(tmp)),source_id,personnel_only=personnel_only)
    if path.suffix.lower() in {'.pdf','.png','.jpg','.jpeg'}:
        return {'sheets':[], 'records':[], 'attachment':True}
    result={'sheets':[],'records':[],'attachment':False}
    with zipfile.ZipFile(BytesIO(content) if content is not None else path) as archive:
        shared=_read_shared_strings(archive)
        for name,sheet_path in _sheets(archive):
            meta,records=_sheet_records(archive,sheet_path,shared,name,source_id,personnel_only=personnel_only)
            result['sheets'].append(meta); result['records'].extend(records)
    return result

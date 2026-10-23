"""Monthly, immutable overseas HR snapshots; queries never execute approvals."""
from copy import deepcopy
from datetime import datetime, date, timedelta
import hashlib
import json
import logging
from pathlib import Path
import re
import shutil
import subprocess
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from .recruitment_cancellation import PreparationCancelled, checkpoint
from .recruitment_draft_sources import PARSER_VERSION, date_text, normalize, text


ROSTER_FIELDS=('姓名','工号','证件号码','offer流程编号','入职日期','人员状态','离职日期','办公地址',
               '职级','职位','二级部门','三级部门','四级部门','五级部门','直接上级','直接上级工号',
               '人员来源','是否虚拟员工')
OFFER_FIELDS=('姓名','offer编码','状态','编制ABC分类','招聘负责人','招聘负责人工号',
              '协助招聘负责人姓名','协助招聘负责人工号','招聘渠道','其他渠道','招聘启动日期',
              '招聘需求编码','内推人姓名','内推人工号')
HISTORY_FIELDS=('empNo','employeeInfoId','infoId','recordId','startDate','endDate','entryDate','lastWorkDay',
                'employmentType','employmentStatus','employeeStatus','businessType','businessTypeName',
                'deptCode','deptName','positionCode','positionName','jobLevelCode','jobLevelName',
                'lineManagerNo','lineManagerName','workPlaceAreaId','workPlacePathName')


def _month(value):
    if type(value) is not int or not 200001<=value<=209912 or value%100 not in range(1,13):
        raise ValueError('核算月份格式无效')
    return f'{value//100}-{value%100:02d}'


def _numbers(values):
    return sorted({text(v).lower() for v in values if text(v) and text(v) not in {'-','无','N/A'}})


def scope(state):
    from .recruitment_drafts import ROLE_FIELDS, staff_id
    rows=[r for r in state.get('rows',[]) if not r.get('externalOnly') and r['values'].get('标签分类')=='海外']
    numbers={staff_id(r['values'].get('工号')) for r in rows}
    numbers.update(staff_id(r['values'].get(field)) for r in rows for field,_,_,_ in ROLE_FIELDS)
    period=_month(state['month'])
    def needs_offer(row):
        values=row['values']
        hire=date_text(values.get('入职日期') or values.get('候选人入职时间'))
        start=date_text(values.get('招聘启动日期'))
        return (not row.get('offerMatched') and hire.startswith(period)) or bool(hire and start and start>hire)
    codes={r['values'].get('海外offer流程编号') for r in rows if needs_offer(r)}
    return {'job_numbers':_numbers(numbers),'offer_codes':_numbers(codes)}


def validate_snapshot(payload, month):
    period=_month(month)
    if not isinstance(payload,dict) or payload.get('version')!=1 or payload.get('month')!=month:
        raise ValueError('海外快照与核算月份不一致')
    try:
        when=datetime.fromisoformat(payload['queriedAt'].replace('Z','+00:00'))
    except (ValueError,TypeError,KeyError,AttributeError):
        raise ValueError('海外快照缺少有效查询时间') from None
    result={'version':1,'month':month,'queriedAt':when.replace(tzinfo=ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds')
            if when.tzinfo is None else when.astimezone(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds'),
            'requestedJobNumbers':_numbers(payload.get('requestedJobNumbers',[])),
            'requestedOfferCodes':_numbers(payload.get('requestedOfferCodes',[])),
            'missingOfferCodes':_numbers(payload.get('missingOfferCodes',[])), 'roster':[],'offers':[]}
    if any(len(result[k])>5000 for k in ('requestedJobNumbers','requestedOfferCodes','missingOfferCodes')):
        raise ValueError('本次海外查询范围过大，请按核算月份查询')
    for field in ('roster','offers'):
        if not isinstance(payload.get(field),list) or len(payload[field])>20000:
            raise ValueError('海外接口返回的资料范围无效')
    seen=set()
    for record in payload['roster']:
        if not isinstance(record,dict) or record.get('scope') not in {'month','lookup'} or not isinstance(record.get('data'),dict):
            raise ValueError('海外花名册记录格式无效')
        raw={k:text(record['data'].get(k,'')) for k in ROSTER_FIELDS}
        raw['入职日期']=date_text(raw['入职日期'])
        if not raw['工号'] or not raw['入职日期']:
            raise ValueError('海外花名册缺少工号或本次入职日期')
        if raw['离职日期'] and not date_text(raw['离职日期']):raise ValueError('海外花名册离职日期无效')
        raw['离职日期']=date_text(raw['离职日期'])
        if record['scope']=='month' and (not raw['入职日期'].startswith(period) or raw['人员来源']!='OEHR入职'):
            raise ValueError('海外花名册返回了核算月份以外的新增人员')
        anchor=(raw['工号'].lower(),raw['入职日期'])
        if anchor in seen:raise ValueError('海外花名册任职记录不唯一，本次未保存快照')
        seen.add(anchor);result['roster'].append({'scope':record['scope'],'data':raw})
    required=set(result['requestedOfferCodes'])
    required.update(r['data']['offer流程编号'].lower() for r in result['roster'] if r['scope']=='month'
                    and r['data']['是否虚拟员工']!='是' and r['data']['offer流程编号'])
    found=set()
    for record in payload['offers']:
        if not isinstance(record,dict):raise ValueError('海外 Offer 记录格式无效')
        raw={k:text(record.get(k,'')) for k in OFFER_FIELDS};code=raw['offer编码'].lower()
        if not code or code not in required or code in found:raise ValueError('海外 Offer 未唯一对应本次查询编号')
        if raw['招聘启动日期'] and not date_text(raw['招聘启动日期']):raise ValueError('海外 Offer 招聘启动日期无效')
        raw['招聘启动日期']=date_text(raw['招聘启动日期']);found.add(code);result['offers'].append(raw)
    missing=set(result['missingOfferCodes'])
    if found&missing or found|missing!=required:raise ValueError('海外 Offer 查询未完整完成，本次未保存快照')
    allowed=set(result['requestedJobNumbers'])
    allowed.update(text(o.get(k)).lower() for o in result['offers']
                   for k in ('招聘负责人工号','协助招聘负责人工号','内推人工号') if text(o.get(k)))
    if any(r['scope']=='lookup' and r['data']['工号'].lower() not in allowed for r in result['roster']):
        raise ValueError('海外花名册定向补查返回了范围以外的人员')
    if 'employmentHistory' in payload:
        expected={r['data']['工号'].lower() for r in result['roster'] if r['data']['人员来源']=='OEHR入职'
                  and r['data']['是否虚拟员工']!='是' and (r['scope']=='lookup' or r['data']['offer流程编号'])}
        queries=payload['employmentHistory'];queried=set();result['employmentHistory']=[]
        if not isinstance(queries,list) or len(queries)>20000:raise ValueError('海外任职记录格式无效')
        for query in queries:
            if not isinstance(query,dict):raise ValueError('海外任职查询记录无效')
            number=text(query.get('empNo')).lower();histories=query.get('records')
            if number not in expected or number in queried or not isinstance(histories,list) or len(histories)>1000:
                raise ValueError('海外任职查询范围不完整或重复')
            queried.add(number);items=[]
            for h in histories:
                if not isinstance(h,dict) or text(h.get('empNo')).lower()!=number:raise ValueError('海外任职记录未对应查询人员')
                item={k:text(h.get(k,'')) for k in HISTORY_FIELDS};item['empNo']=number
                for key in ('startDate','endDate','entryDate','lastWorkDay'):
                    value=date_text(item[key])
                    if not value and item[key]:
                        raise ValueError('海外任职记录缺少有效日期')
                    item[key]=value
                if item['startDate'] and item['endDate'] and item['startDate']>item['endDate']:raise ValueError('海外任职记录生效区间无效')
                if item not in items:items.append(item)
            result['employmentHistory'].append({'empNo':number,'records':sorted(items,key=lambda h:(h['startDate'],h['endDate'],h['recordId']))})
        if queried!=expected:raise ValueError('海外任职记录未查询完整，本次未保存快照')
        result['employmentHistory'].sort(key=lambda h:h['empNo'])
    result['roster'].sort(key=lambda r:(r['data']['工号'].lower(),r['data']['入职日期']))
    result['offers'].sort(key=lambda r:r['offer编码'].lower())
    return result


def data_digest(payload):
    data={k:v for k,v in payload.items() if k not in {'queriedAt','requestedJobNumbers','requestedOfferCodes'}}
    return hashlib.sha256(json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def roster_as_of(payload):
    month=payload['month'];following=(month//100+1)*100+1 if month%100==12 else month+1
    return min(payload['queriedAt'][:10],(date.fromisoformat(_month(following)+'-01')-timedelta(days=1)).isoformat())


def _historical_roster(raw,payload):
    query=next((q for q in payload.get('employmentHistory',[]) if q['empNo']==raw['工号'].lower()),None)
    if query is None:return raw
    at=roster_as_of(payload)
    matches=[h for h in query['records'] if h['entryDate']==raw['入职日期'] and h['employmentType']=='0'
             and h['employmentStatus'] in {'0','1'} and h['startDate'] and h['endDate'] and h['startDate']<=at<=h['endDate']]
    def unique(key):
        values={h[key] for h in matches}
        return next(iter(values)) if len(values)==1 else ''
    result=dict(raw)
    for dest,key in [('职级','jobLevelName'),('职位','positionName'),('直接上级','lineManagerName'),
                     ('直接上级工号','lineManagerNo'),('离职日期','lastWorkDay')]:result[dest]=unique(key)
    result['人员状态']={'2':'试用','3':'正式','8':'已离职'}.get(unique('employeeStatus'),'')
    leaf=next((raw.get(f) for f in ('五级部门','四级部门','三级部门','二级部门') if raw.get(f)),'')
    same_department=bool(matches and unique('deptName') and unique('deptName')==leaf)
    workplace=unique('workPlacePathName')
    workplace_evidence=any(h['workPlacePathName'] for h in matches)
    if workplace:
        result['办公地址']=workplace
    elif not same_department or workplace_evidence:
        result['办公地址']=''
    if not same_department or workplace_evidence and (not workplace or workplace!=raw.get('办公地址')):
        for field in ('二级部门','三级部门','四级部门','五级部门'):result[field]=''
    return result


def parsed_snapshot(payload, source_id):
    payload=validate_snapshot(payload,payload['month']);records=[];sheets=[]
    for sheet,role,items,fields in [('OEHR花名册','roster',[r['data'] for r in payload['roster']],ROSTER_FIELDS),
                                  ('海外Offer','overseas_offer',payload['offers'],OFFER_FIELDS)]:
        columns={field:i+1 for i,field in enumerate(fields)}
        sheets.append({'name':sheet,'role':role,'recordCount':len(items)})
        for number,raw in enumerate(items,2):
            values,field_columns=normalize(_historical_roster(raw,payload) if role=='roster' else raw,columns,role)
            original,_=normalize(raw,columns,role)
            records.append({'role':role,'values':values,'rawValues':original,'fieldColumns':field_columns,
                'availableFields':list(values),'ref':{'sourceId':source_id,'sheet':sheet,'row':number},'historyCells':[],
                'sourceScope':values.get('标签分类','海外'),'scopeBasis':'海外接口月度快照',
                'lookupOnly':role=='roster' and payload['roster'][number-2]['scope']=='lookup',
                'apiEvidence':{'provider':'oehr' if role=='roster' else 'hrms','queriedAt':payload['queriedAt'],'month':payload['month'],
                               'asOf':roster_as_of(payload) if role=='roster' and 'employmentHistory' in payload else ''}})
    if 'employmentHistory' in payload:
        count=0
        for query in payload['employmentHistory']:
            for h in query['records'] or [{'empNo':query['empNo'],'historyUnavailable':True}]:
                count+=1
                values={'工号':query['empNo'],'入职日期':h.get('entryDate',''),'生效日期':h.get('startDate',''),
                        '失效日期':h.get('endDate',''),'业务类型':h.get('businessTypeName',''),
                        '任职状态':h.get('employmentStatus',''),'人员状态':h.get('employeeStatus',''),
                        '最后工作日':h.get('lastWorkDay',''),'部门':h.get('deptName',''),
                        '职位':h.get('positionName',''),'职级':h.get('jobLevelName',''),
                        '直线经理':h.get('lineManagerName',''),'直线经理工号':h.get('lineManagerNo','')}
                records.append({'role':'employment_history','values':values,'rawValues':deepcopy(values),
                    'fieldColumns':{},'ref':{'sourceId':source_id,'sheet':'海外任职记录','row':count+1},
                    'apiEvidence':{'provider':'oehr','queriedAt':payload['queriedAt'],'month':payload['month'],'history':h}})
        sheets.append({'name':'海外任职记录','role':'employment_history','recordCount':count})
    return {'records':records,'sheets':sheets,'attachment':False,'parserVersion':PARSER_VERSION}


def save_snapshot(store, month, revision, payload):
    payload=validate_snapshot(payload,month);fingerprint=data_digest(payload)
    with store._lock(month) as folder:
        checkpoint();state=store.read(month);store._check(state,revision)
        if any(s.get('kind')=='overseas_api' and s.get('forMonth')==month and s.get('dataDigest')==fingerprint
               and not s.get('error') for s in state['sources']):return state
        period=_month(month)
        previous=[s for s in state['sources'] if s.get('kind')=='overseas_api' and s.get('forMonth')==month]
        new_month=(not state['revision'] or state.get('parentMonth') and not any(
            str(r['values'].get('入职日期') or r['values'].get('候选人入职时间') or '').startswith(period) for r in state['rows']))
        current=[s for s in state['sources'] if s.get('active',True) and not s.get('comparisonOnly')]
        if current and all(s.get('monthlyRoster') and s.get('forMonth')==month for s in current) and not any(
                r['values'].get('标签分类')=='海外' for r in state['rows']):new_month=True
        snapshot_only=bool(previous or not (new_month or state.get('monthlyWorkflow')))
        content=json.dumps(payload,ensure_ascii=False,sort_keys=True).encode();sid=hashlib.sha256(content).hexdigest()
        source={'id':sid,'kind':'overseas_api','name':f'海外资料快照{month}.json','storedName':sid+'.json',
            'active':True,'bytes':len(content),'forMonth':month,'addedAt':payload['queriedAt'],'dataDigest':fingerprint,
            'snapshotOnly':snapshot_only,'comparisonOnly':snapshot_only,'snapshotVersion':len(previous)+1,
            'scope':'核算月海外新人及已有人员任职资料','rosterCount':len(payload['roster']),'offerCount':len(payload['offers']),
            'missingOfferCodes':payload['missingOfferCodes']}
        if 'employmentHistory' in payload:
            source.update(employmentPeople=len(payload['employmentHistory']),
                          employmentRecords=sum(len(h['records']) for h in payload['employmentHistory']),
                          rosterAsOf=roster_as_of(payload))
        checkpoint();store._write(folder/'sources'/source['storedName'],payload)
        (folder/'sources'/source['storedName']).chmod(0o600)
        try:
            store._parse_source(folder,source);checkpoint();state['sources'].append(source)
            return store._save(folder,state,recalculate=False) if snapshot_only else store._save(folder,store._rebuild(folder,state))
        except Exception:
            if not (folder/'draft.json').exists() or not any(s['id']==sid for s in json.loads((folder/'draft.json').read_text()).get('sources',[])):
                (folder/'sources'/source['storedName']).unlink(missing_ok=True)
                (folder/'parsed'/f'{sid}.json').unlink(missing_ok=True)
            raise


class BrowserClient:
    """Use the existing browser session; never copy credentials into Python."""
    def __init__(self, space_id=None, keep_space=False):
        self.space_id=space_id;self.keep_space=keep_space

    def fetch(self, month, job_numbers=(), offer_codes=(), progress=None):
        _month(month)
        executable=shutil.which('ego-browser')
        if not executable:raise ValueError('请先打开并登录海外人事系统，当前未找到 Ego 浏览器连接')
        module=Path(__file__).with_name('recruitment_overseas_browser.mjs').resolve()
        with TemporaryDirectory(prefix='recruitment-overseas-') as temporary:
            cancel=Path(temporary)/'cancel'
            progress_file=Path(temporary)/'progress'
            result_file=Path(temporary)/'result.json'
            options={'month':month,'jobNumbers':_numbers(job_numbers),'offerCodes':_numbers(offer_codes),'cancelFile':str(cancel),
                     'spaceId':self.space_id,'keepSpace':self.keep_space,'progressFile':str(progress_file),'resultFile':str(result_file)}
            program=f'const {{run}}=await import({json.dumps(module.as_uri())});await run({json.dumps(options,ensure_ascii=False)});'
            process=subprocess.Popen([executable,'nodejs'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            first=True;last_message=''
            try:
                while True:
                    checkpoint()
                    try:
                        stdout,stderr=process.communicate(input=program if first else None,timeout=1)
                        break
                    except subprocess.TimeoutExpired as exc:
                        first=False;partial=exc.output or b''
                        if isinstance(partial,bytes):partial=partial.decode('utf-8',errors='replace')
                        messages=[line.split('OVERSEAS_PROGRESS:',1)[1] for line in partial.splitlines() if line.startswith('OVERSEAS_PROGRESS:')]
                        if progress_file.is_file():messages.append(progress_file.read_text()[:180])
                        if progress and messages and messages[-1]!=last_message:
                            last_message=messages[-1];progress(last_message[:180])
            except PreparationCancelled:
                cancel.touch()
                try:process.communicate(timeout=25)
                except subprocess.TimeoutExpired:process.terminate();process.communicate(timeout=10)
                raise
            except BaseException:
                process.terminate();process.communicate(timeout=10);raise
            checkpoint()
            result_text=result_file.read_text() if result_file.is_file() and process.returncode==0 else None
        if process.returncode or result_text is None:
            errors=re.findall(r'OVERSEAS_ERROR:([A-Z_]+)',stdout+'\n'+stderr)
            code=errors[-1] if errors and re.fullmatch('[A-Z_]{1,64}',errors[-1]) else 'QUERY_FAILED'
            logging.getLogger(__name__).warning('Overseas query failed: code=%s returncode=%s result=%s',code,process.returncode,result_text is not None)
            message={'LOGIN_REQUIRED':'请在 Ego 浏览器登录 HRMS 和 OEHR 后重试，已有资料和待办保留',
                     'CONTROL_RELEASED':'海外取数已暂停，请完成浏览器操作后重试，已有资料保留',
                     'CANCELLED':'海外取数已停止，已有资料保留'}.get(errors[-1] if errors else '',
                         '海外接口未完整返回资料，请稍后重试；本次未保存新快照')
            raise ValueError(message)
        return json.loads(result_text)


def configured_client():
    from ..auth import production_runtime
    if production_runtime():
        from .recruitment_browser_queue import QueuedClient
        return QueuedClient()
    return BrowserClient()


def fetch(month, *, job_numbers=(), offer_codes=(), client=None, progress=None):
    checkpoint()
    payload=(client or configured_client()).fetch(month,job_numbers,offer_codes,progress)
    checkpoint()
    return validate_snapshot(payload,month)

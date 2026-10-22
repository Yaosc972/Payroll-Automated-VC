"""Discover domestic monthly hires through the existing read-only Beisen client."""
from copy import deepcopy
from datetime import date, datetime, timedelta
import hashlib
import json

from . import recruitment_beisen as beisen
from .recruitment_cancellation import checkpoint
from .recruitment_draft_sources import normalize, date_text
from .recruitment_overseas import _month

MONTHLY='/TenantBaseExternal/api/v5/Employee/GetListByTimeWindow'
ORGANIZATIONS='/TenantBaseExternal/api/v5/Organization/GetByIds'
VIRTUAL='extshifoushixuniyuangong_109025_1767668301'
OEHR='extshifouoehryuangong_109025_1587397968'
FIELDS=('姓名','工号','证件号码','入职日期','人员状态','转正日期','离职日期','职级','职位',
        '二级部门','三级部门','四级部门','五级部门','直接上级','直接上级工号','人员来源','是否虚拟员工')
LEVELS=('SecondLevelOrganization','ThirdLevelOrganization','FourthLevelOrganization','FifthLevelOrganization')
COLUMNS=['UserID','Name','JobNumber','IDNumber','EntryDate','StartDate','StopDate','PObjectDataID',
         'ApprovalStatus','EmployeeStatus','EmployType','ServiceType','LastWorkDate','RegularizationDate',
         'LUOffer','OIdDepartment','OIdJobLevel','OIdJobPosition','POIdEmpAdmin',VIRTUAL,OEHR]


def _true(value):return value is True or str(value).lower() in {'true','1','是'}


def _effective_record(records,anchor,at):
    matches=[h for h in records if date_text(h.get('entryDate'))==date_text(anchor.get('entryDate'))
             and str(h.get('jobNumber','')).lower()==str(anchor.get('jobNumber','')).lower()
             and str(h.get('approvalStatus'))=='4' and str(h.get('serviceType'))=='0'
             and date_text(h.get('startDate')) and date_text(h.get('stopDate'))
             and date_text(h['startDate'])<=at<=date_text(h['stopDate'])]
    # Keep only facts shared by all effective records. A missing or conflicting
    # grade, manager or status remains blank for the existing review workflow.
    result={}
    for key in {k for h in matches for k in h if k!='translateProperties'}:
        values=[h.get(key) for h in matches]
        if values and all(v==values[0] for v in values):result[key]=values[0]
    translated={}
    for key in {k for h in matches for k in h.get('translateProperties',{})}:
        values=[h.get('translateProperties',{}).get(key) for h in matches]
        if values and all(v==values[0] for v in values):translated[key]=values[0]
    result.update(jobNumber=anchor['jobNumber'],entryDate=anchor['entryDate'],userID=anchor.get('userID'),translateProperties=translated)
    return result


def scope(state):
    from .recruitment_drafts import ROLE_FIELDS, staff_id
    rows=[r for r in state.get('rows',[]) if not r.get('externalOnly')]
    return {'job_numbers':sorted({staff_id(r['values'].get('工号')) for r in rows
                                 if r['values'].get('标签分类')=='国内' and staff_id(r['values'].get('工号'))}),
            'recipient_numbers':sorted({staff_id(r['values'].get(field)) for r in rows for field,_,_,_ in ROLE_FIELDS
                                        if staff_id(r['values'].get(field)).startswith('zt')})}


def fetch(month,client=None,progress=None,job_numbers=(),recipient_numbers=()):
    period=_month(month);client=client or beisen.Client();progress=progress or (lambda message:None)
    following=(month//100+1)*100+1 if month%100==12 else month+1
    body={'empStatus':[1,2,3,4,5,6,7,8,12],'employType':[0,1,2],'serviceType':[0],
          'withDisabled':True,'isGetLatestRecord':True,'timeWindowQueryType':1,
          'startTime':'2000-01-01T00:00:00','stopTime':(date.today()+timedelta(days=1)).isoformat()+'T00:00:00',
          'capacity':300,'columns':COLUMNS,'isWithDeleted':False,'enableTranslate':True,'scrollId':'',
          'extQueries':[{'fieldName':'EntryDate','queryType':7,'values':[period+'-01',_month(following)+'-01'],
                         'includeLowerValue':True,'includeUpperValue':False}]}
    people=[];seen=set();total=None
    progress('正在读取核算月份的国内花名册')
    for _ in range(500):
        reply=beisen._post(client,MONTHLY,body);batch=reply.get('data')
        if not isinstance(batch,list) or type(reply.get('total')) is not int:raise ValueError('国内花名册响应不完整，本次未保存快照')
        if total is None:total=reply['total']
        if not 0<=total<=100000 or total!=reply['total']:raise ValueError('国内花名册取数范围发生变化，请重新同步')
        if not batch:break
        for item in batch:
            info=item.get('employeeInfo');histories=item.get('recordInfoList')
            if not isinstance(info,dict) or not isinstance(histories,list) or not info.get('userID') or info['userID'] in seen:
                raise ValueError('国内花名册分页重复或人员标识缺失，本次未保存快照')
            if any(not date_text(h.get('entryDate')).startswith(period) for h in histories):
                raise ValueError('国内花名册未按核算月份筛选，本次未保存快照')
            seen.add(info['userID']);people.append(item)
        if not reply.get('scrollId'):raise ValueError('国内花名册分页缺少游标，本次未保存快照')
        body['scrollId']=reply['scrollId'];progress(f'正在读取国内花名册：{len(people)}/{total} 人')
    else:raise ValueError('国内花名册分页未结束，本次未保存快照')
    if len(people)!=total:raise ValueError('国内花名册分页不完整，本次未保存快照')
    candidates=[]
    for item in people:
        info=item['employeeInfo'];custom=info.get('customProperties') or {}
        if _true(custom.get(VIRTUAL)) or _true(custom.get(OEHR)):continue
        for history in item['recordInfoList']:
            if str(history.get('approvalStatus'))!='4' or str(history.get('serviceType'))!='0':continue
            if str(history.get('employeeStatus'))=='1' or not str(history.get('jobNumber') or '').lower().startswith('zt'):continue
            candidates.append((info,history))
    anchors=[(h['jobNumber'].lower(),date_text(h['entryDate'])) for _,h in candidates]
    if len(anchors)!=len(set(anchors)):raise ValueError('国内花名册存在重复任职，请先核对')
    as_of=min(date.today().isoformat(),(date.fromisoformat(_month(following)+'-01')-timedelta(days=1)).isoformat())
    histories=[]
    for batch in beisen.batches((info['userID'] for info,_ in candidates),300):
        response=beisen._post(client,beisen.HISTORY,{'oIds':batch,'option':'None','empStatus':[],'employType':[],
            'serviceType':[0],'approvalStatus':[4],'isWithDeleted':False,'enableTranslate':True,'columns':COLUMNS})
        if not isinstance(response.get('data'),list):raise ValueError('国内生效任职记录未完整返回')
        for raw in response['data']:
            if raw.get('userID') not in batch:raise ValueError('国内任职记录未对应查询人员')
            item=beisen.pick(raw,COLUMNS)
            item['translateProperties']={k:v for k,v in (raw.get('translateProperties') or {}).items()
                if k in {'EmployeeStatusText','OIdDepartmentText','OIdJobLevelText','OIdJobPositionText','POIdEmpAdminText'}}
            histories.append(item)
    candidates=[(info,_effective_record([h for h in histories if h.get('userID')==info['userID']],anchor,as_of))
                for info,anchor in candidates]
    departments=sorted({h['oIdDepartment'] for _,h in candidates if h.get('oIdDepartment')})
    organizations={}
    for batch in beisen.batches(departments,300):
        result=beisen._post(client,ORGANIZATIONS,{'oIds':batch,'isWithDeleted':False,'enableTranslate':True,
                            'columns':['OId','Name',*LEVELS]})
        if not isinstance(result.get('data'),list):raise ValueError('国内组织信息未完整返回')
        organizations.update({o['oId']:o for o in result['data']})
    managers=sorted({h['pOIdEmpAdmin'] for _,h in candidates if h.get('pOIdEmpAdmin')})
    manager_numbers={}
    for batch in beisen.batches(managers,300):
        result=beisen._post(client,beisen.HISTORY,{'oIds':batch,'option':'None','empStatus':[],'employType':[],
            'serviceType':[0],'approvalStatus':[4],'isWithDeleted':False,'columns':['UserID','JobNumber','StartDate','StopDate']})
        if not isinstance(result.get('data'),list):raise ValueError('国内直线经理信息未完整返回')
        for h in result['data']:
            if beisen.day(h.get('startDate'))<=as_of<=beisen.day(h.get('stopDate')) and h.get('jobNumber'):
                manager_numbers.setdefault(h['userID'],set()).add(h['jobNumber'].lower())
    roster=[]
    for info,h in candidates:
        translated=h.get('translateProperties') or {};org=organizations.get(h.get('oIdDepartment'),{});labels=org.get('translateProperties') or {}
        manager=manager_numbers.get(h.get('pOIdEmpAdmin'),set())
        record={'姓名':info.get('name') or '','工号':h['jobNumber'].lower(),'证件号码':info.get('iDNumber') or '',
                '入职日期':beisen.day(h.get('entryDate')),'人员状态':translated.get('EmployeeStatusText') or {'2':'试用','3':'正式','8':'已离职'}.get(str(h.get('employeeStatus')),''),
                '转正日期':beisen.day(h.get('regularizationDate')),'离职日期':beisen.day(h.get('lastWorkDate')),
                '职级':translated.get('OIdJobLevelText') or '','职位':translated.get('OIdJobPositionText') or '',
                '直接上级':translated.get('POIdEmpAdminText') or '','直接上级工号':next(iter(manager)) if len(manager)==1 else '',
                '人员来源':'EHR入职','是否虚拟员工':'否'}
        record.update({field:labels.get(level+'Text') or '' for field,level in zip(FIELDS[9:13],LEVELS)})
        roster.append(record)
    progress(f'正在关联 {len(roster)} 名国内人员的 Offer 及任职资料')
    payload=beisen.fetch(sorted(set(job_numbers)|{r['工号'] for r in roster}),client=client,progress=progress,
                         recipient_numbers=recipient_numbers,candidate_histories=histories,newest_first=True,offer_month=month)
    payload.update(month=month,monthlyRoster=True,roster=roster,queryTotal=total,rosterAsOf=as_of)
    return payload


def validate_snapshot(payload,month):
    period=_month(month)
    if not isinstance(payload,dict) or payload.get('month')!=month or payload.get('monthlyRoster') is not True:
        raise ValueError('国内快照与核算月份不一致')
    if not isinstance(payload.get('roster'),list) or len(payload['roster'])>20000:raise ValueError('国内花名册格式无效')
    result=deepcopy({k:v for k,v in payload.items() if k in {'version','month','monthlyRoster','queriedAt','roster','queryTotal',
        'requestedJobNumbers','requestedRecipientJobNumbers','scopeJobNumbers','scopeRecipientJobNumbers',
        'employeeMappings','candidateHistories','recipientHistories','offers','requirements','forms','syncCoverage','rosterAsOf'}})
    try:datetime.fromisoformat(result['queriedAt'])
    except (ValueError,KeyError,TypeError):raise ValueError('国内快照缺少有效查询时间') from None
    seen=set()
    for raw in result['roster']:
        if not isinstance(raw,dict) or not date_text(raw.get('入职日期')).startswith(period) or raw.get('人员来源')!='EHR入职':
            raise ValueError('国内花名册与核算月份或数据源不一致')
        key=(str(raw.get('工号') or '').lower(),date_text(raw['入职日期']))
        if not key[0].startswith('zt') or key in seen or raw.get('是否虚拟员工')=='是':raise ValueError('国内花名册人员范围无效')
        seen.add(key)
    result['roster']=[{f:r.get(f,'') for f in FIELDS} for r in result['roster']]
    return result


def roster_records(payload,source_id):
    payload=validate_snapshot(payload,payload['month']);records=[];columns={f:i+1 for i,f in enumerate(FIELDS)}
    for number,raw in enumerate(payload['roster'],2):
        values,field_columns=normalize(raw,columns,'roster')
        records.append({'role':'roster','values':values,'rawValues':deepcopy(values),'fieldColumns':field_columns,
            'ref':{'sourceId':source_id,'sheet':'EHR花名册','row':number},'sourceScope':'国内','scopeBasis':'国内接口月度快照',
            'apiEvidence':{'provider':'beisen','month':payload['month'],'queriedAt':payload['queriedAt'],
                           'asOf':payload.get('rosterAsOf','')}})
    return records


def data_digest(payload):
    return hashlib.sha256(json.dumps({k:v for k,v in payload.items() if k!='queriedAt'},ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def save_snapshot(store,month,revision,payload):
    payload=validate_snapshot(payload,month);digest=data_digest(payload)
    with store._lock(month) as folder:
        checkpoint();state=store.read(month);store._check(state,revision)
        previous=[s for s in state['sources'] if s.get('monthlyRoster') and s.get('forMonth')==month]
        if any(s.get('dataDigest')==digest and not s.get('error') for s in previous):return state
        domestic=[r for r in state['rows'] if r['values'].get('标签分类')=='国内' and not r.get('externalOnly')]
        initial=not domestic or state.get('parentMonth') and not any(date_text(r['values'].get('入职日期')).startswith(_month(month)) for r in domestic)
        snapshot_only=bool(previous or not (initial or state.get('monthlyWorkflow')))
        content=json.dumps(payload,ensure_ascii=False,sort_keys=True).encode();sid=hashlib.sha256(content).hexdigest()
        source={'id':sid,'kind':'beisen','monthlyRoster':True,'name':f'国内资料快照{month}.json','storedName':sid+'.json',
            'forMonth':month,'addedAt':payload['queriedAt'],'active':True,'bytes':len(content),'dataDigest':digest,
            'snapshotOnly':snapshot_only,'comparisonOnly':snapshot_only,'snapshotVersion':len(previous)+1,
            'scope':'核算月份国内新人及关联录用资料','rosterCount':len(payload['roster']),'offerCount':len(payload['offers'])}
        if payload.get('rosterAsOf'):source['rosterAsOf']=payload['rosterAsOf']
        checkpoint();store._write(folder/'sources'/source['storedName'],payload);(folder/'sources'/source['storedName']).chmod(0o600)
        try:
            store._parse_source(folder,source);checkpoint();state['sources'].append(source)
            return store._save(folder,state,recalculate=False) if snapshot_only else store._save(folder,store._rebuild(folder,state))
        except Exception:
            if not (folder/'draft.json').exists() or not any(s['id']==sid for s in json.loads((folder/'draft.json').read_text()).get('sources',[])):
                (folder/'sources'/source['storedName']).unlink(missing_ok=True);(folder/'parsed'/f'{sid}.json').unlink(missing_ok=True)
            raise

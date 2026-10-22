"""Read-only Beisen intake for employees in the selected monthly batch."""
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
import json
import os
import urllib.request
import urllib.error

from .recruitment_cancellation import checkpoint

BASE='https://openapi.italent.cn'
IDS='/TenantBaseExternal/api/v5/Employee/GetUserIDsByJobNumbers'
HISTORY='/TenantBaseExternal/api/v5/Employee/GetServiceInfoByIds'
OFFERS='/TenantBaseExternal/api/v5/Offer/GetByTimeWindow'
REQUIREMENTS='/RecruitV6/api/v1/Requirement/GetRequirements'
FORMS='/TenantBaseExternal/api/v5/CommonMetaObject/GetByIds'
OWNER='extzhuanyuan12_109025_1971095424'
REFERRER='extQ202106334_109025_847145517'
CHANNEL='extQ20210635_109025_2041445622'
ABC='extzhiweifenlei_109025_933701443'
COOP_ID='extxiezhuzhaopinfuzerengonghao_109025_801104894'
COOP_NAME='extxiezhuzhaopinfuzeren_109025_1163526586'
# Tenant-specific mappings validated against the supplied original Offer export.
ABC_LABELS={'1':'A','2':'B','3':'C1','4':'C2','5':'C','6':'不占编'}
CHANNEL_LABELS=dict(zip(map(str,[1,2,3,4,5,6,7,8,9,10,12,13,14,15,16,17]),
 ['内推','猎头','猎聘','Boss直聘','前程无忧','拉勾网','领英','外部推荐','二次入职','其他','校招','智联招聘','体系外转体系内','外包转正式','人员调动','小红书']))
HISTORY_COLUMNS=['UserID','JobNumber','StartDate','StopDate','EntryDate','LastWorkDate','LUOffer','EmployType','RegularizationDate','ServiceType','ApprovalStatus']
RECIPIENT_HISTORY_COLUMNS=HISTORY_COLUMNS+['OIdJobLevel','OIdJobPosition']
OFFER_COLUMNS=['ObjectId','Name','UserID','EntryDate','RecruitmentRequirement','ApplicantPosition','ApprovalStatus','EmploymentForm','CreatedTime','ModifiedTime','StdIsDeleted','Remarks',OWNER,REFERRER,CHANNEL,COOP_ID,COOP_NAME]


def batches(items,size):
    items=list(dict.fromkeys(items))
    for i in range(0,len(items),size):yield items[i:i+size]


def _post(client,path,body):
    checkpoint()
    result=client.post(path,body)
    checkpoint()
    return result


def day(value):return str(value or '')[:10]


def pick(record,columns):
    allowed={x.lower() for x in columns}
    result={k:v for k,v in record.items() if k.lower() in allowed and not isinstance(v,(dict,list))}
    if isinstance(record.get('customProperties'),dict):
        result['customProperties']={k:v for k,v in record['customProperties'].items() if k.lower() in allowed}
    translated=record.get('translateProperties')
    translation_fields={'OIdJobLevelText':'oidjoblevel','OIdJobPositionText':'oidjobposition'}
    if isinstance(translated,dict):
        selected={k:v for k,v in translated.items() if translation_fields.get(k) in allowed and isinstance(v,str)}
        if selected:result['translateProperties']=selected
    return result


def sync_coverage(payload):
    from .recruitment_import_validation import offer_validity
    candidates=payload.get('candidateHistories',[])
    recipients=payload.get('recipientHistories',[])
    approved=lambda h:str(h.get('approvalStatus'))=='4' and bool(h.get('jobNumber'))
    candidate_numbers={str(h['jobNumber']).lower() for h in candidates if approved(h)}
    recipient_numbers={str(h['jobNumber']).lower() for h in candidates+recipients if approved(h)}
    requested={str(n).lower() for n in payload.get('requestedJobNumbers',payload.get('scopeJobNumbers',[])) if n}
    requested_recipients={str(n).lower() for n in payload.get('requestedRecipientJobNumbers',payload.get('scopeRecipientJobNumbers',[])) if n}
    mapped={str(m.get('jobNumber','')).lower() for m in payload.get('employeeMappings',[]) if m.get('userId') and str(m.get('code'))=='200'}
    mapped|=candidate_numbers|recipient_numbers
    offer_states={o.get('objectId'):offer_validity(o,'domestic_offer')['state'] for o in payload.get('offers',[])}
    valid_offers={oid for oid,state in offer_states.items() if state=='valid'}
    offer_numbers={str(h['jobNumber']).lower() for h in candidates if approved(h) and h.get('lUOffer') in valid_offers}
    def entries(numbers,returned,offer=False):
        return {n:{'requested':n in numbers,'mapped':n in mapped,'employment':n in returned,
                   'offer':n in offer_numbers if offer else False,
                   'offerState':('valid' if n in offer_numbers else next((offer_states[h.get('lUOffer')] for h in candidates if str(h.get('jobNumber','')).lower()==n and h.get('lUOffer') in offer_states),'absent')) if offer else 'absent',
                   'reason':('未返回员工映射' if n not in mapped else '未返回已批准任职资料' if n not in returned
                             else '未取得对应的有效录用资料' if offer and n not in offer_numbers else '')}
                for n in sorted(numbers|returned)}
    return {'version':1,'candidates':entries(requested,candidate_numbers,True),
            'recipients':entries(requested_recipients,recipient_numbers)}


def coverage_sets(sources):
    result={key:set() for key in ('candidateEmployment','candidateOffer','candidateOfferGap','recipientEmployment','requestedCandidate','requestedRecipient')}
    for source in sorted(sources,key=lambda s:s.get('addedAt','')):
        if not source.get('active',True) or source.get('error') or source.get('channelDetailsOnly') or source.get('comparisonOnly'):continue
        coverage=source.get('syncCoverage',{})
        for role,prefix in (('candidates','candidate'),('recipients','recipient')):
            for number,item in coverage.get(role,{}).items():
                if item.get('requested'):result['requestedCandidate' if role=='candidates' else 'requestedRecipient'].add(number)
                if item.get('employment'):result[prefix+'Employment'].add(number)
                if role=='candidates':
                    if item.get('offer'):result['candidateOffer'].add(number)
                    elif item.get('offerState') in {'invalid','unknown'}:result['candidateOffer'].discard(number)
                    if item.get('requested'):
                        if item.get('offer'):result['candidateOfferGap'].discard(number)
                        else:result['candidateOfferGap'].add(number)
    return result


def _with_coverage(payload):
    coverage=sync_coverage(payload)
    payload.update(syncCoverage=coverage,
                   scopeJobNumbers=sorted(n for n,c in coverage['candidates'].items() if c['employment']),
                   scopeRecipientJobNumbers=sorted(n for n,c in coverage['recipients'].items() if c['employment']))
    return payload


class Client:
    def __init__(self):
        from ..auth import production_runtime
        path=Path(__file__).resolve().parents[2]/'.env.beisen.local'
        config={}
        if not production_runtime() and path.is_file():
            for line in path.read_text().splitlines():
                if line.strip() and not line.lstrip().startswith('#') and '=' in line:
                    k,v=line.split('=',1);config[k.strip()]=v.strip().strip('\"\'')
        config.update({k:os.environ[k] for k in ('BEISEN_BASE_URL','BEISEN_APP_KEY','BEISEN_APP_SECRET') if k in os.environ})
        if config.get('BEISEN_BASE_URL',BASE).rstrip('/')!=BASE:raise ValueError('北森接口地址不匹配')
        if not all(config.get(k) for k in ('BEISEN_APP_KEY','BEISEN_APP_SECRET')):raise ValueError('请填写北森接口凭据')
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self,*args,**kwargs):return None
        self.opener=urllib.request.build_opener(NoRedirect);self.token=None
        auth=self.post('/token',{'grant_type':'client_credentials','app_key':config['BEISEN_APP_KEY'],'app_secret':config['BEISEN_APP_SECRET']})
        self.token=auth.get('access_token')
        if not self.token:raise ValueError('北森鉴权未返回令牌')

    def post(self,path,body):
        checkpoint()
        if path not in {'/token',IDS,HISTORY,OFFERS,REQUIREMENTS,FORMS,
                        '/TenantBaseExternal/api/v5/Employee/GetListByTimeWindow',
                        '/TenantBaseExternal/api/v5/Organization/GetByIds'}:raise ValueError('不支持的北森查询')
        headers={'Content-Type':'application/json'}
        if self.token:headers['Authorization']='Bearer '+self.token
        request=urllib.request.Request(BASE+path,data=json.dumps(body).encode(),headers=headers)
        try:
            with self.opener.open(request,timeout=45) as response:raw=response.read().decode('utf-8-sig')
            try:data=json.loads(raw)
            except json.JSONDecodeError as exc:
                if not exc.msg.startswith('Invalid control character'):raise
                data=json.loads(raw,strict=False)
        except urllib.error.HTTPError as exc:raise ValueError(f'北森查询失败（HTTP {exc.code}），本次未保存同步资料') from None
        except (urllib.error.URLError,TimeoutError,ValueError):raise ValueError('北森网络或响应异常，本次未保存同步资料') from None
        checkpoint()
        if path!='/token' and str(data.get('code'))!='200':raise ValueError('北森未成功返回查询结果，本次未保存同步资料')
        return data


def fetch_employment(job_numbers,client=None):
    """Targeted read-only gap repair: no full historical Offer scan."""
    client=client or Client();numbers=list(dict.fromkeys(str(n).lower() for n in job_numbers if n));mapped=[];records=[]
    for batch in batches(numbers,30):mapped.extend(_post(client,IDS,{'jobNumbers':batch}).get('data') or [])
    for batch in batches((m['userId'] for m in mapped if m.get('userId') and str(m.get('code'))=='200'),300):
        result=_post(client,HISTORY,{'option':'None','empStatus':[],'employType':[],'serviceType':[],'approvalStatus':[4],
            'oIds':batch,'isWithDeleted':False,'columns':RECIPIENT_HISTORY_COLUMNS,'enableTranslate':True})
        records.extend(pick(r,RECIPIENT_HISTORY_COLUMNS) for r in result.get('data') or [])
    return _with_coverage({'version':1,'employmentOnly':True,'queriedAt':datetime.now().isoformat(timespec='seconds'),
            'requestedJobNumbers':[],'requestedRecipientJobNumbers':numbers,'employeeMappings':[pick(m,['jobNumber','userId','code']) for m in mapped],
            'candidateHistories':[],'recipientHistories':records,'offers':[],'requirements':[],'forms':[]})


def fetch(job_numbers,client=None,recipient_numbers=(),candidate_histories=(),progress=None,newest_first=False,offer_month=None):
    """No stored credentials, no audit-cache dependencies, no result workbook input."""
    client=client or Client();job_numbers=list(dict.fromkeys(str(n).lower() for n in job_numbers if n));mapped=[]
    cached=[dict(h) for h in candidate_histories if str(h.get('jobNumber','')).lower() in job_numbers]
    cached_numbers={str(h['jobNumber']).lower() for h in cached if str(h.get('approvalStatus'))=='4'}
    for batch in batches((n for n in job_numbers if n not in cached_numbers),30):mapped.extend(_post(client,IDS,{'jobNumbers':batch}).get('data') or [])
    def histories(ids,recipient=False):
        result=[]
        columns=RECIPIENT_HISTORY_COLUMNS if recipient else HISTORY_COLUMNS
        for batch in batches(ids,300):
            data=_post(client,HISTORY,{'option':'None','empStatus':[],'employType':[],'serviceType':[],'approvalStatus':[4],
                'oIds':batch,'isWithDeleted':False,'columns':columns,**({'enableTranslate':True} if recipient else {})})
            result.extend(pick(r,columns) for r in data.get('data') or [])
        return result
    hs=cached+histories(m['userId'] for m in mapped if m.get('userId') and str(m.get('code'))=='200')
    period=f'{offer_month//100}-{offer_month%100:02d}' if offer_month is not None else ''
    linked={h['lUOffer'] for h in hs if h.get('lUOffer') and (not period or day(h.get('entryDate')).startswith(period))}
    offers={}
    # Query by modification time over full history: older Offers may have a
    # nullable UserID; LUOffer is the authoritative employee relationship.
    first=datetime(2000,1,1);end=datetime.combine(date.today()+timedelta(days=1),datetime.min.time())
    start=max(first,end-timedelta(days=90)) if newest_first else first
    while linked and start<end:
        stop=end if newest_first else min(start+timedelta(days=90),end);scroll=''
        if progress:progress(f'正在关联国内 Offer：核对 {start:%Y-%m} 至 {stop:%Y-%m} 的历史变动')
        while True:
            response=_post(client,OFFERS,{'startTime':start.isoformat(),'stopTime':stop.isoformat(),'timeWindowQueryType':1,
                'scrollId':scroll,'capacity':300,'isWithDeleted':True,'columns':OFFER_COLUMNS})
            data=response.get('data') or []
            for r in data:
                if r.get('objectId') in linked and (not newest_first or r['objectId'] not in offers):offers[r['objectId']]=pick(r,OFFER_COLUMNS)
            if not data:break
            next_scroll=response.get('scrollId')
            if not next_scroll or next_scroll==scroll:raise ValueError('北森分页未完整返回，本次未保存同步资料')
            scroll=next_scroll
        if newest_first:
            if linked<=offers.keys() or start==first:break
            end=start;start=max(first,end-timedelta(days=90))
        else:start=stop
    requirements=[]
    for batch in batches((r['recruitmentRequirement'] for r in offers.values() if r.get('recruitmentRequirement')),300):
        requirements.extend(pick(r,['requirementId','requirementCode','createDate',ABC]) for r in _post(client,REQUIREMENTS,batch).get('data') or [])
    forms=[]
    for batch in batches((r['employmentForm'] for r in offers.values() if r.get('employmentForm')),300):
        for r in _post(client,FORMS,{'metaObjectName':'EmploymentForm','ids':batch,'columns':['OId','Name','Code']}).get('data') or []:
            forms.append({'fields':{k:v for k,v in r.get('fields',{}).items() if k in {'OId','Name','Code'}}})
    recipient_ids=[r['customProperties'][f] for r in offers.values() for f in (OWNER,REFERRER) if r.get('customProperties',{}).get(f)]
    extra=list(recipient_numbers)+[r.get('customProperties',{}).get(COOP_ID) for r in offers.values()]
    for batch in batches((str(n).lower() for n in extra if n and str(n) not in {'-','无'}),30):
        response=_post(client,IDS,{'jobNumbers':batch}).get('data') or []
        mapped.extend(response)
        recipient_ids.extend(m['userId'] for m in response if m.get('userId') and str(m.get('code'))=='200')
    recipients=histories(recipient_ids,recipient=True)
    return _with_coverage({'version':1,'queriedAt':datetime.now().isoformat(timespec='seconds'),'requestedJobNumbers':list(job_numbers),
        'requestedRecipientJobNumbers':list(dict.fromkeys(str(n).lower() for n in extra if n)), 'employeeMappings':[pick(m,['jobNumber','userId','code']) for m in mapped],
        'candidateHistories':hs,'offers':list(offers.values()),'requirements':requirements,'forms':forms,'recipientHistories':recipients})


def fetch_channel_details(payload, checked_ids=(), client=None):
    """Upgrade saved Offers with notes only; never replace the batch snapshot.

    Search each known modification day first. If a linked Offer has changed
    since that snapshot, follow the remaining modification window to today.
    Discard every unrelated response and retain no extra personal fields.
    """
    checked=set(checked_ids)
    targets={o['objectId']:o for o in payload.get('offers',[]) if o.get('objectId') not in checked
             and str(o.get('customProperties',{}).get(CHANNEL))=='10' and 'remarks' not in o}
    if not targets:return None
    if any(not day(o.get('modifiedTime')) for o in targets.values()):
        raise ValueError('原录用记录缺少查询时间，请更新国内资料后重试')
    client=client or Client();found={}
    columns=['ObjectId','Remarks','EntryDate','ApprovalStatus','StdIsDeleted',CHANNEL]
    def query(start,stop):
        scroll=''
        while True:
            response=_post(client,OFFERS,{'startTime':start.isoformat(),'stopTime':stop.isoformat(),
                'timeWindowQueryType':1,'scrollId':scroll,'capacity':300,'isWithDeleted':True,'columns':columns})
            data=response.get('data') or []
            for record in data:
                oid=record.get('objectId')
                if oid in targets:found[oid]=pick(record,columns)
            if not data:break
            following=response.get('scrollId')
            if not following or following==scroll:raise ValueError('北森备注分页未完整返回，本次未保存补查资料')
            scroll=following
    days=sorted({day(o['modifiedTime']) for o in targets.values()})
    for value in days:
        start=datetime.fromisoformat(value);query(start,start+timedelta(days=1))
    if targets.keys()-found.keys():
        start=datetime.fromisoformat(min(day(targets[oid]['modifiedTime']) for oid in targets.keys()-found.keys()))
        end=datetime.combine(date.today()+timedelta(days=1),datetime.min.time())
        while start<end and targets.keys()-found.keys():
            stop=min(start+timedelta(days=90),end);query(start,stop);start=stop
    offers=[];checks=[]
    for oid,old in targets.items():
        live=found.get(oid)
        valid=bool(live and not live.get('stdIsDeleted') and str(live.get('approvalStatus'))=='2'
                   and day(live.get('entryDate'))==day(old.get('entryDate'))
                   and str(live.get('customProperties',{}).get(CHANNEL))=='10')
        status='已取得备注' if valid and live.get('remarks') else '备注为空' if valid else '录用记录已变更或未找到'
        checks.append({'offerId':oid,'status':status})
        if valid:offers.append({**{k:old.get(k) for k in ('objectId','entryDate','approvalStatus')},'remarks':live.get('remarks')})
    return {'version':1,'queriedAt':datetime.now().isoformat(timespec='seconds'),'channelDetailsOnly':True,
        'channelDetailsCheckedOfferIds':sorted(targets),'channelChecks':checks,'scopeJobNumbers':[],
        'candidateHistories':[h for h in payload['candidateHistories'] if h.get('lUOffer') in targets],
        'offers':offers,'forms':[],'requirements':[],'recipientHistories':[]}


def parsed_snapshot(payload,source_id):
    """Only proven same-employment links become normalized intake records."""
    forms={r['fields']['OId']:r['fields']['Name'] for r in payload['forms']}
    requirements={r['requirementId']:r for r in payload['requirements']}
    offers={r['objectId']:r for r in payload['offers']};histories=payload['candidateHistories']
    recipients=defaultdict(list)
    for h in payload['recipientHistories']:recipients[h['userID']].append(h)
    def recipient(uid,at):
        if not uid:return ''
        matches={str(h['jobNumber']).lower() for h in recipients.get(uid,[]) if day(h.get('startDate'))<=at<=day(h.get('stopDate'))}
        return next(iter(matches)) if len(matches)==1 else None
    records=[];seen=set();warnings=[]
    def add(role,values,proof):
        key=json.dumps([role,values,proof],ensure_ascii=False,sort_keys=True)
        if key in seen:return
        seen.add(key);records.append({'role':role,'values':values,'fieldColumns':{},'availableFields':list(values),
            'rawValues':dict(values),'ref':{'sourceId':source_id,'sheet':'北森同步','row':len(records)+1},'apiEvidence':{'queriedAt':payload.get('queriedAt',''),**proof}})
    from .recruitment_import_validation import offer_validity
    for h in histories:
        o=offers.get(h.get('lUOffer'))
        if not o:continue
        entry=day(o.get('entryDate'));number=str(h.get('jobNumber') or '').lower()
        if not entry or not number:continue
        validity=offer_validity(o,'domestic_offer')['state']
        if validity!='valid':
            if validity!='absent' and not payload.get('channelDetailsOnly'):
                add('domestic_offer',{'工号':number,'入职日期':entry,'审批状态':str(o.get('approvalStatus') or ''),
                                     '是否作废':'是' if o.get('stdIsDeleted') else ''},
                    {'offerId':o['objectId'],'userId':h['userID']})
            continue
        if payload.get('channelDetailsOnly'):
            if o.get('remarks'):
                add('domestic_offer',{'工号':number,'入职日期':entry,'招聘渠道备注':o['remarks']},
                    {'offerId':o['objectId'],'userId':h['userID'],'field':'remarks'})
            continue
        req=requirements.get(o.get('recruitmentRequirement'));custom=o.get('customProperties',{})
        values={'姓名':o.get('name',''),'工号':number,'入职日期':entry,'标签分类':'国内','录用岗位':o.get('applicantPosition',''),
            '录用用工形式':forms.get(o.get('employmentForm'),''),'招聘渠道':CHANNEL_LABELS.get(str(custom.get(CHANNEL)),''),
            '协助招聘人工号':custom.get(COOP_ID,''),'协助招聘人姓名':custom.get(COOP_NAME,'')}
        if o.get('remarks'):values['招聘渠道备注']=o['remarks']
        for field,mapping,code in [('招聘渠道',CHANNEL_LABELS,custom.get(CHANNEL)),('ABC类别',ABC_LABELS,req.get('customProperties',{}).get(ABC) if req else None)]:
            if code is not None and str(code) not in mapping:warnings.append({'employee':number,'field':field,'code':str(code)})
            elif code is not None:values[field]=mapping[str(code)]
        if req:values.update({'海外招聘需求编号':str(req['requirementCode']),'招聘启动日期':day(req.get('createDate'))})
        for dest,f in [('招聘负责人工号',OWNER),('推荐人工号',REFERRER)]:
            resolved=recipient(custom.get(f),entry)
            if resolved is not None:values[dest]=resolved
            else:warnings.append({'employee':number,'field':dest,'reason':'领取人任职未唯一对应'})
        proof={'offerId':o['objectId'],'userId':h['userID']}
        add('domestic_offer',values,proof)
    # Monthly Offer retrieval need not return an earlier internship Offer.
    # The approved native history can prove the exact same-employment bridge.
    from .recruitment_intern_continuity import intern_continuities
    bridges={}
    for key,evidence in ({} if payload.get('channelDetailsOnly') else intern_continuities(histories)).items():
        user,number,offer,formal=key;o=offers.get(offer)
        if o and (offer_validity(o,'domestic_offer')['state']!='valid'
                  or day(o.get('entryDate'))!=evidence['recruitmentEntryDate']):continue
        add('employment_link',{'工号':number,'入职日期':evidence['recruitmentEntryDate'],'人事入职日期':formal},
            {'offerId':offer,'userId':user,'continuity':evidence})
        bridges[key]={**evidence,'ref':records[-1]['ref']}
    bridged_histories={id(histories[i]):bridge for bridge in bridges.values() for i in bridge['formalHistoryIndexes']}
    # Preserve effective-dated facts independently of Offer/roster records.
    # They enrich existing recruitments only; never discover a new hire by name.
    for h in ([] if payload.get('channelDetailsOnly') else histories+payload.get('recipientHistories',[])):
        number=str(h.get('jobNumber') or '').lower()
        if not number or str(h.get('approvalStatus'))!='4':continue
        bridge=bridged_histories.get(id(h))
        history=({**h,'recruitmentEntryDate':bridge['recruitmentEntryDate'],
                  'continuityEvidence':bridge['ref']} if bridge else h)
        add('employment_history',{'工号':number}, {'history':history,'queriedAt':h.get('_queriedAt',payload.get('queriedAt',''))})
    sheets=[{'name':'北森同步'}]
    if payload.get('monthlyRoster'):
        from .recruitment_domestic import roster_records
        records=roster_records(payload,source_id)+records
        sheets.insert(0,{'name':'EHR花名册','role':'roster','recordCount':len(payload['roster'])})
    return {'records':records,'attachment':False,'sheets':sheets,'warnings':warnings}

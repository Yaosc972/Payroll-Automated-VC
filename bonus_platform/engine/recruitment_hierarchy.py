"""Resolve the existing five-level reporting rule at the candidate's hire date."""
from .recruitment_draft_sources import date_text, text


FIELDS=('直线经理工号','直接上级工号','间接上级1工号','间接上级2工号','间接上级3工号','间接上级4工号')


def evidence(row,index):
    from .recruitment_drafts import staff_id
    v=row['values'];hire=date_text(v.get('入职日期') or v.get('候选人入职时间'))
    ref=staff_id(v.get('推荐人工号'));number=staff_id(v.get('工号'))
    protected=set(FIELDS)|{'推荐人与候选人上下级关系','推荐人是否直接/间接上级'}
    if (row.get('frozenRecruitmentFacts') or not hire or not ref.startswith('zt') or not number.startswith('zt')
            or protected & {e['field'] for e in row.get('edits',[])}
            or (protected|{'推荐人工号','入职日期','候选人入职时间'}) & set(row.get('unresolvedFields',[]))):
        return None
    result={'at':hire,'chain':[],'sources':[],'complete':False,'related':False,'pending':None}
    provider='oehr' if v.get('标签分类')=='海外' else 'beisen'
    identity={'number':number,'provider':provider};visited=set()
    for depth in range(5):
        key=('beisen-user:'+str(identity['userId'])) if 'userId' in identity else identity['number']
        marker=(identity['provider'],key)
        if marker in visited:return result
        visited.add(marker);facts=index.get(key,[])
        if identity['provider']!='either':facts=[h for h in facts if h.get('provider','beisen')==identity['provider']]
        if not facts:
            if not depth and any(v.get(f) for f in FIELDS):return None
            result['pending']=identity;return result
        matches=[]
        for h in facts:
            overseas=h.get('provider')=='oehr'
            approved=(h.get('employmentType')=='0' and h.get('employmentStatus') in {'0','1'}) if overseas else (
                str(h.get('serviceType'))=='0' and str(h.get('approvalStatus'))=='4')
            end=date_text(h.get('endDate' if overseas else 'stopDate'))
            if (approved and date_text(h.get('startDate')) and end and date_text(h['startDate'])<=hire<=end
                    and hire<=h.get('queriedAt','')[:10] and (depth or date_text(h.get('entryDate'))==hire)):
                matches.append(h)
        if not matches:return result
        identities={(h.get('provider','beisen'),str(h.get('employeeInfoId') if h.get('provider')=='oehr' else h.get('userID')),
                     date_text(h.get('entryDate'))) for h in matches}
        if len(identities)!=1 or any(x[1] in {'','None'} for x in identities):return result
        provider=next(iter(identities))[0];field='lineManagerNo' if provider=='oehr' else 'pOIdEmpAdmin'
        if any(field not in h for h in matches):
            if not depth and any(v.get(f) for f in FIELDS):return None
            result['pending']=identity;return result
        choices={text(h.get(field)).lower() for h in matches}
        if len(choices)!=1:return result
        manager=choices.pop();result['sources'].extend(h['source'] for h in matches if h['source'] not in result['sources'])
        if provider=='oehr' and not manager and any(h.get('lineManagerProvided')!='1' for h in matches):
            result['pending']=identity;return result
        if not manager or manager=='0':result['complete']=True;return result
        if provider=='oehr':
            number=staff_id(manager)
            if not number.startswith('zt'):return result
            identity={'provider':'either','number':number}
        else:
            identity={'provider':'beisen','userId':manager}
            people=index.get('beisen-user:'+manager,[])
            numbers={staff_id(h.get('jobNumber')) for h in people if str(h.get('serviceType'))=='0'
                     and str(h.get('approvalStatus'))=='4' and date_text(h.get('startDate'))<=hire<=date_text(h.get('stopDate'))
                     and hire<=h.get('queriedAt','')[:10]}
            if len(numbers)!=1 or not next(iter(numbers),'').startswith('zt'):
                if not people:result['pending']=identity
                return result
            number=numbers.pop()
        if number in result['chain'] or number==staff_id(v.get('工号')):return result
        result['chain'].append(number)
        if number==ref:result.update(complete=True,related=True);return result
    result['complete']=True
    return result

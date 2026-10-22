from copy import deepcopy

import pytest

from bonus_platform.engine import recruitment_beisen as beisen
from bonus_platform.engine.recruitment_awards import award
from bonus_platform.engine.recruitment_drafts import ROLE_FIELDS
from bonus_platform.engine.recruitment_employment import enrich, index_histories
from test_recruitment_awards import person


def history(**values):
    value={'userID':99,'jobNumber':'zt25991','entryDate':'2020-01-01',
           'startDate':'2020-01-01','stopDate':'9999-12-31','approvalStatus':4,
           'serviceType':0,'regularizationDate':'2020-07-01','lastWorkDate':'',
           'oIdJobLevel':123,'oIdJobPosition':456,
           'translateProperties':{'OIdJobLevelText':'P2-1','OIdJobPositionText':'产品运营'}}
    value.update(values)
    return value


def payload(histories):
    return {'version':1,'employmentOnly':True,'queriedAt':'2026-10-22T19:00:00',
            'requestedJobNumbers':[],'requestedRecipientJobNumbers':['zt25991'],
            'candidateHistories':[],'recipientHistories':histories,
            'offers':[],'forms':[],'requirements':[]}


class HistoryClient:
    def __init__(self):self.calls=[]
    def post(self,path,body):
        self.calls.append((path,deepcopy(body)))
        if path==beisen.IDS:return {'data':[{'jobNumber':'zt25991','userId':99,'code':200}]}
        assert path==beisen.HISTORY
        return {'data':[history(translateProperties={'OIdJobLevelText':'P2-1',
                     'OIdJobPositionText':'产品运营','UnrequestedText':'discard'})]}


def test_targeted_employment_retains_only_requested_qualification_translations():
    client=HistoryClient()
    value=beisen.fetch_employment(['zt25991'],client=client)
    request=next(body for path,body in client.calls if path==beisen.HISTORY)
    assert {'OIdJobLevel','OIdJobPosition'}<=set(request['columns'])
    assert request['enableTranslate'] is True
    assert value['recipientHistories'][0]['translateProperties']=={
        'OIdJobLevelText':'P2-1','OIdJobPositionText':'产品运营'}
    parsed=beisen.parsed_snapshot(value,'api')
    assert index_histories(parsed['records'])['zt25991'][0]['translateProperties']['OIdJobPositionText']=='产品运营'


def test_monthly_recipient_query_also_requests_qualification_translations():
    client=HistoryClient()
    value=beisen.fetch([],client=client,recipient_numbers=['zt25991'])
    request=next(body for path,body in client.calls if path==beisen.HISTORY)
    assert {'OIdJobLevel','OIdJobPosition'}<=set(request['columns'])
    assert request['enableTranslate'] is True
    assert value['recipientHistories'][0]['translateProperties']['OIdJobLevelText']=='P2-1'


def test_prefixed_legacy_referrer_attaches_internal_timeline_and_qualifies_award():
    row=person(hire='2026-08-01',推荐人工号='海外-ZT25991',推荐人入职日期='',
               推荐人人员状态='',推荐人转正日期='')
    row.update(edits=[],sources=[],provenance={},conflicts=[])
    records=beisen.parsed_snapshot(payload([history()]),'api')['records']
    enrich(row,index_histories(records),ROLE_FIELDS)
    node=next(n for n in award(row,'referral',202608)['nodes'] if n['dueMonth']==202608)
    assert node['status']=='本月到期'
    assert not any('推荐人' in issue for issue in node['issues'])
    assert row['employmentTimelines']['推荐人'][0]['jobNumber']=='zt25991'


def qualification_row(histories,**values):
    row=person(hire='2026-08-01',推荐人工号='zt25991',推荐人职级='',推荐人职位='',**values)
    row.update(edits=[],sources=[],provenance={},conflicts=[])
    records=beisen.parsed_snapshot(payload(histories),'api')['records']
    enrich(row,index_histories(records),ROLE_FIELDS)
    return row


def duplicate_metadata_row(**changes):
    complete=history(lUOffer='recipient-offer',employType=0)
    slim={k:v for k,v in complete.items() if k not in {'oIdJobLevel','oIdJobPosition','translateProperties'}}
    slim.update(changes)
    data=payload([complete]);data['candidateHistories']=[slim]
    row=person(hire='2026-08-01',推荐人工号='zt25991',推荐人职级='',推荐人职位='',
               推荐人人员状态='',推荐人转正日期='')
    row.update(edits=[],sources=[],provenance={},conflicts=[])
    enrich(row,index_histories(beisen.parsed_snapshot(data,'api')['records']),ROLE_FIELDS)
    return row


def test_slim_candidate_history_cannot_hide_complete_same_segment_recipient_qualification():
    row=duplicate_metadata_row()
    before=deepcopy(row)
    result=award(row,'referral',202608)
    node=next(n for n in result['nodes'] if n['dueMonth']==202608)
    assert node['status']=='本月到期'
    assert node['issues']==[]
    assert result['referrerQualificationBasis'][0]['values']=={'推荐人职级':'P2-1','推荐人职位':'产品运营'}
    assert len(result['referrerQualificationBasis'][0]['sources'])==2
    assert row==before


@pytest.mark.parametrize('missing',['OIdJobLevelText','OIdJobPositionText'])
def test_only_absent_translation_key_can_be_completed_from_same_segment(missing):
    translated=dict(history()['translateProperties']);translated.pop(missing)
    row=duplicate_metadata_row(translateProperties=translated)
    result=award(row,'referral',202608)
    assert next(n for n in result['nodes'] if n['dueMonth']==202608)['status']=='本月到期'


@pytest.mark.parametrize('changes',[{}, {'oIdJobPosition':456},
                                  {'oIdJobPosition':456,'translateProperties':{'OIdJobPositionText':'产品运营'}}])
def test_conflicting_raw_metadata_in_same_segment_donors_cannot_be_silenced(changes):
    row=duplicate_metadata_row(**changes)
    complete=next(h for h in row['employmentTimelines']['推荐人'] if 'translateProperties' in h)
    row['employmentTimelines']['推荐人'].append({**complete,'oIdJobPosition':999})
    result=award(row,'referral',202608)
    assert '推荐人岗位与职级待核' in result['issues']
    assert not result.get('referrerQualificationBasis')


def test_duplicate_metadata_completion_keeps_manual_clear_protected():
    row=duplicate_metadata_row()
    row['edits']=[{'field':'推荐人职位','value':''}]
    result=award(row,'referral',202608)
    assert '推荐人岗位与职级待核' in result['issues']
    assert not result.get('referrerQualificationBasis')


def test_metadata_completion_never_supplies_a_missing_regularization_date():
    row=duplicate_metadata_row(regularizationDate=None)
    for h in row['employmentTimelines']['推荐人']:h['regularizationDate']=None
    result=award(row,'referral',202608)
    node=next(n for n in result['nodes'] if n['dueMonth']==202608)
    assert node['status']=='待核对'
    assert '推荐人岗位与职级待核' not in node['issues']
    assert '推荐人：转正日期待核对' in node['issues']


@pytest.mark.parametrize('change',[
    {'translateProperties':{'OIdJobLevelText':'P2-1','OIdJobPositionText':''}},
    {'translateProperties':{'OIdJobLevelText':'P2-1','OIdJobPositionText':None}},
    {'translateProperties':{'OIdJobLevelText':'M4-1','OIdJobPositionText':'HRBP'}},
    {'translateProperties':None},
    {'oIdJobPosition':None},
    {'oIdJobPosition':999},
])
def test_explicit_unknown_or_conflicting_duplicate_metadata_stays_pending(change):
    result=award(duplicate_metadata_row(**change),'referral',202608)
    node=next(n for n in result['nodes'] if n['dueMonth']==202608)
    assert node['status']=='待核对'
    assert '推荐人岗位与职级待核' in node['issues']
    assert not result.get('referrerQualificationBasis')


@pytest.mark.parametrize('field,value',[
    ('userID',100),('jobNumber','zt-other'),('entryDate','2020-02-01'),
    ('startDate','2020-02-01'),('stopDate','2026-09-01'),('serviceType',1),
    ('approvalStatus',2),('lUOffer','different-offer'),('employType',1),
    ('queriedAt','2026-10-21T19:00:00'),('provider','oehr'),
])
def test_missing_translation_never_borrows_a_different_segment_or_capture(field,value):
    row=duplicate_metadata_row()
    slim=next(h for h in row['employmentTimelines']['推荐人'] if 'translateProperties' not in h)
    slim[field]=value
    if field=='entryDate':row['values']['推荐人入职日期']=''
    result=award(row,'referral',202608)
    assert '推荐人岗位与职级待核' in result['issues']
    assert not result.get('referrerQualificationBasis')


def test_missing_referrer_qualification_uses_month_end_history_instead_of_current_role():
    old=history(stopDate='2026-08-31')
    now=history(startDate='2026-09-01',translateProperties={'OIdJobLevelText':'M4-1','OIdJobPositionText':'HRBP'})
    row=qualification_row([old,now])
    result=award(row,'referral',202608)
    assert result['nodes'][0]['status']=='本月到期'
    assert '推荐人岗位与职级待核' not in result['issues']
    assert result['referrerQualificationBasis'][0]['at']=='2026-08-31'
    assert result['referrerQualificationBasis'][0]['values']['推荐人职级']=='P2-1'
    assert result['referrerQualificationBasis'][0]['sources'][0]['sourceId']=='api'
    assert row['values']['推荐人职级']==row['values']['推荐人职位']==''


def test_explicit_referral_cutoff_selects_that_date_for_missing_qualification():
    old=history(stopDate='2026-08-31')
    now=history(startDate='2026-09-01',translateProperties={'OIdJobLevelText':'M4-1','OIdJobPositionText':'HRBP'})
    result=award(qualification_row([old,now]),'referral',202608,
                 cutoff_policy={'mode':'date','date':'2026-09-15'})
    assert result['total']==0
    assert '推荐人岗位或职级不符合资格' in result['reasons']


def test_distinct_due_date_roles_stay_unknown_instead_of_globally_excluding():
    old=history(stopDate='2026-06-30')
    later=history(startDate='2026-07-01',translateProperties={'OIdJobLevelText':'M4-1','OIdJobPositionText':'HRBP'})
    row=qualification_row([old,later],ABC类别='A',职级='P4-1')
    row['values']['入职日期']=row['values']['候选人入职时间']='2026-05-01'
    row['rule']['version']='legacy'
    result=award(row,'referral',202608,cutoff_policy={'mode':'due'})
    assert '推荐人岗位与职级待核' in result['issues']
    assert all(n['status']=='待核对' for n in result['nodes'] if n['dueMonth']<=202608)
    assert '推荐人岗位或职级不符合资格' not in result['reasons']


def test_same_qualification_across_due_dates_supplies_one_traceable_fact_per_date():
    row=qualification_row([history(stopDate='2026-06-30'),history(startDate='2026-07-01')],
                          ABC类别='A',职级='P4-1')
    row['values']['入职日期']=row['values']['候选人入职时间']='2026-05-01'
    row['rule']['version']='legacy'
    before=deepcopy(row)
    result=award(row,'referral',202608,cutoff_policy={'mode':'due'})
    assert '推荐人岗位与职级待核' not in result['issues']
    assert [b['at'] for b in result['referrerQualificationBasis']]==['2026-05-31','2026-07-31']
    assert row==before


def test_partial_historical_qualification_can_only_fill_matching_missing_fact():
    row=qualification_row([history()])
    row['values']['推荐人职级']='P2-1'
    assert '推荐人岗位与职级待核' not in award(row,'referral',202608)['issues']
    row['values']['推荐人职级']='P1-1'
    assert '推荐人岗位与职级待核' in award(row,'referral',202608)['issues']


@pytest.mark.parametrize('placeholder',['n/a',' N/a ','--','none','None','null','NULL'])
def test_placeholder_history_position_never_proves_referrer_qualification(placeholder):
    row=qualification_row([history(translateProperties={
        'OIdJobLevelText':'P2-1','OIdJobPositionText':placeholder})])
    result=award(row,'referral',202608)
    node=next(n for n in result['nodes'] if n['dueMonth']==202608)
    assert node['status']=='待核对'
    assert '推荐人岗位与职级待核' in node['issues']
    assert not result.get('referrerQualificationBasis')


@pytest.mark.parametrize('field,placeholder',[
    ('推荐人职级','n/a'),('推荐人职级','None'),('推荐人职位',' N/a '),('推荐人职位','--')])
def test_static_placeholder_can_only_be_replaced_by_complete_history(field,placeholder):
    row=qualification_row([history()])
    row['values'][field]=placeholder
    result=award(row,'referral',202608)
    assert '推荐人岗位与职级待核' not in result['issues']
    assert result['referrerQualificationBasis'][0]['values']=={
        '推荐人职级':'P2-1','推荐人职位':'产品运营'}
    assert row['values'][field]==placeholder


@pytest.mark.parametrize('placeholder',['n/a','--','none','NULL'])
def test_complete_static_grade_with_placeholder_position_stays_pending_without_history(placeholder):
    row=qualification_row([])
    row['values'].update(推荐人职级='P2-1',推荐人职位=placeholder)
    before=deepcopy(row['values'])
    result=award(row,'referral',202608)
    node=next(n for n in result['nodes'] if n['dueMonth']==202608)
    assert node['status']=='待核对'
    assert '推荐人岗位与职级待核' in node['issues']
    assert row['values']==before


def test_proven_offline_referrer_keeps_missing_qualification_exception():
    row=qualification_row([])
    identifier='体系外海外-Synthetic'
    row['values'].update(推荐人工号=identifier,推荐人职级='N/A',推荐人职位='none',
                        推荐人入职日期='',推荐人人员状态='',推荐人转正日期='')
    row['provenance']['推荐人工号']=[{'sourceId':'offline','role':'supplement','value':identifier}]
    before=deepcopy(row['values'])
    result=award(row,'referral',202608)
    node=next(n for n in result['nodes'] if n['dueMonth']==202608)
    assert node['status']=='本月到期'
    assert not node['issues']
    assert node['employmentBasis']['sourceId']=='offline'
    assert row['values']==before


@pytest.mark.parametrize('change',['overseas-route','overseas-provider','secondary-service','unapproved',
                                   'unknown-entry','conflicting-identity','missing-query','missing-source',
                                   'unknown-grade','placeholder-grade','placeholder-position'])
def test_non_authoritative_recipient_history_cannot_supply_qualification(change):
    row=qualification_row([history()])
    fact=row['employmentTimelines']['推荐人'][0]
    if change=='overseas-route':row['recipientSourceRegions']={'推荐人':'海外'}
    elif change=='overseas-provider':fact['provider']='oehr'
    elif change=='secondary-service':fact['serviceType']=1
    elif change=='unapproved':fact['approvalStatus']=2
    elif change=='unknown-entry':fact['entryDate']=''
    elif change=='conflicting-identity':row['unresolvedFields']=['推荐人工号']
    elif change=='missing-query':fact['queriedAt']=''
    elif change=='missing-source':fact['source']={}
    elif change=='unknown-grade':fact['translateProperties']['OIdJobLevelText']='unknown'
    elif change=='placeholder-grade':fact['translateProperties']['OIdJobLevelText']='无'
    elif change=='placeholder-position':fact['translateProperties']['OIdJobPositionText']='-'
    result=award(row,'referral',202608)
    assert '推荐人岗位与职级待核' in result['issues']
    assert not result.get('referrerQualificationBasis')


@pytest.mark.parametrize('change',['manual-empty','existing-history','conflict','overlap','unknown-field','future-query','different-employment'])
def test_incomplete_or_protected_referrer_facts_are_not_filled(change):
    facts=[history()]
    row=qualification_row(facts)
    if change=='manual-empty':row['edits']=[{'field':'推荐人职位','value':''}]
    elif change=='existing-history':row['values'].update(推荐人职级='P1-1',推荐人职位='旧核对岗位')
    elif change=='conflict':row['conflicts']=[{'field':'推荐人职位','values':['旧岗位','新岗位']}]
    elif change=='overlap':
        row['employmentTimelines']['推荐人'].append({**row['employmentTimelines']['推荐人'][0],
            'translateProperties':{'OIdJobLevelText':'M4-1','OIdJobPositionText':'HRBP'}})
    elif change=='unknown-field':row['employmentTimelines']['推荐人'][0]['translateProperties'].pop('OIdJobPositionText')
    elif change=='future-query':row['employmentTimelines']['推荐人'][0]['queriedAt']='2026-08-15'
    elif change=='different-employment':row['values']['推荐人入职日期']='2021-01-01'
    result=award(row,'referral',202608)
    if change=='existing-history':
        assert result.get('referrerQualificationBasis',[])==[]
        assert row['values']['推荐人职位']=='旧核对岗位'
    else:
        assert '推荐人岗位与职级待核' in result['issues']

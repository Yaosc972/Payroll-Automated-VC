from copy import deepcopy
from datetime import datetime
import time

import pytest

from bonus_platform.engine import recruitment_beisen as beisen, recruitment_overseas as overseas, recruitment_prepare as jobs
from bonus_platform.engine.recruitment_awards import award
from bonus_platform.engine.recruitment_drafts import DraftStore
from bonus_platform.engine.recruitment_employment import referrer_qualification
from test_recruitment_awards import person
from test_recruitment_dated_referrer_facts import qualification_row, history
from test_recruitment_overseas import snapshot


def foreign_fact(**changes):
    return {'provider':'oehr','empNo':'zt3','employeeInfoId':'person-3','entryDate':'2020-01-01',
            'startDate':'2020-01-01','endDate':'9999-12-31','employmentType':'0','employmentStatus':'0',
            'employeeStatus':'3','jobLevelName':'P2-1','positionName':'产品运营','queriedAt':'2026-10-26T12:00:00',
            'source':{'sourceId':'oehr','sheet':'海外任职记录','row':2},**changes}


def foreign_row(facts):
    row=person('2026-08-01',推荐人工号='zt3',推荐人入职日期='',推荐人职级='',推荐人职位='')
    row.update(edits=[],sources=[],provenance={},conflicts=[],
               recipientSourceRegions={'推荐人':'海外'},employmentTimelines={'推荐人':facts})
    return row


def test_overseas_qualification_uses_the_hire_date_primary_role_before_a_later_promotion():
    row=foreign_row([foreign_fact(endDate='2026-08-31'),
                     foreign_fact(startDate='2026-09-01',jobLevelName='M4-1',positionName='HRBP'),
                     foreign_fact(employmentType='1',jobLevelName='M4-1',positionName='HRBP(兼)')])
    before=deepcopy(row);result=award(row,'referral',202608)
    assert '推荐人岗位与职级待核' not in result['issues']
    assert result['total']>0
    assert result['referrerQualificationBasis'][0]['at']=='2026-08-01'
    assert result['referrerQualificationBasis'][0]['values']=={'推荐人职级':'P2-1','推荐人职位':'产品运营'}
    assert row==before


@pytest.mark.parametrize('change',['missing-grade','missing-position','overlap','wrong-employee','missing-person','unapproved',
                                   'missing-date','future-query','missing-source','manual-clear','conflicting-field'])
def test_unknown_or_competing_overseas_qualification_is_not_guessed(change):
    h=foreign_fact();row=foreign_row([h])
    if change=='missing-grade':h['jobLevelName']=''
    elif change=='missing-position':h['positionName']='-'
    elif change=='overlap':row['employmentTimelines']['推荐人'].append(foreign_fact(jobLevelName='M4-1'))
    elif change=='wrong-employee':h['empNo']='zt-other'
    elif change=='missing-person':h['employeeInfoId']=''
    elif change=='unapproved':h['employmentStatus']='unknown'
    elif change=='missing-date':h['startDate']=''
    elif change=='future-query':h['queriedAt']='2026-07-31'
    elif change=='missing-source':h['source']={}
    elif change=='manual-clear':row['edits']=[{'field':'推荐人职位','value':''}]
    elif change=='conflicting-field':row['conflicts']=[{'field':'推荐人职级','values':['P2-1','M4-1']}]
    assert not referrer_qualification(row,[datetime(2026,8,1)])


def test_domestic_primary_qualification_is_not_hidden_by_an_extra_assignment():
    row=qualification_row([history(),history(serviceType=1,translateProperties={'OIdJobLevelText':'M4-1','OIdJobPositionText':'HRBP(兼)'})])
    result=award(row,'referral',202608)
    assert result['total']>0 and '推荐人岗位与职级待核' not in result['issues']


def test_migrated_employment_scope_keeps_legacy_captures_readable_and_new_queries_complete():
    value={'version':1,'month':202609,'queriedAt':'2026-10-26T12:00:00','employmentOnly':True,
           'requestedJobNumbers':['zt3'],'requestedOfferCodes':[],'missingOfferCodes':[],
           'roster':[{'scope':'lookup','data':{'工号':'zt3','入职日期':'2020-01-01','人员来源':'人员迁移','是否虚拟员工':'否'}}],
           'offers':[],'employmentHistory':[]}
    assert overseas.validate_snapshot(value,202609)['employmentHistory']==[]
    value['employmentHistoryScope']='oehr_and_migrated'
    with pytest.raises(ValueError):overseas.validate_snapshot(value,202609)
    value['employmentHistory']=[{'empNo':'zt3','records':[foreign_fact()]}]
    assert overseas.validate_snapshot(value,202609)['employmentHistory'][0]['empNo']=='zt3'


def test_prepare_repairs_future_referrers_through_both_interfaces_without_reloading_offers(tmp_path,monkeypatch):
    store=DraftStore(tmp_path);month=202609;p=snapshot(month)
    p['roster'][0]['data']['入职日期']='2026-09-02'
    p['offers'][0].update(招聘渠道='内推',其他渠道='',内推人姓名='推荐人',内推人工号='zt3')
    before=store.save_overseas_snapshot(month,0,p);calls=[]
    def domestic(numbers,**kwargs):
        calls.append(('domestic',numbers))
        return beisen._with_coverage({'version':1,'employmentOnly':True,'queriedAt':'2026-10-26T12:00:00',
            'requestedJobNumbers':[],'requestedRecipientJobNumbers':numbers,'candidateHistories':[],
            'recipientHistories':[],'offers':[],'requirements':[],'forms':[]})
    def foreign(period,job_numbers,**kwargs):
        calls.append(('overseas',job_numbers))
        return {'version':1,'month':period,'queriedAt':'2026-10-26T12:00:00','employmentOnly':True,
                'requestedJobNumbers':job_numbers,'requestedOfferCodes':[],'missingOfferCodes':[],
                'roster':[{'scope':'lookup','data':{'工号':'zt3','入职日期':'2020-01-01','人员来源':'OEHR入职',
                          '人员状态':'正式','是否虚拟员工':'否'}}],'offers':[],
                'employmentHistory':[{'empNo':'zt3','records':[foreign_fact()]}]}
    monkeypatch.setattr(beisen,'fetch_employment',domestic);monkeypatch.setattr(overseas,'fetch_employment',foreign)
    monkeypatch.setattr(beisen,'fetch',lambda *a,**k:pytest.fail('Qualification repair must not reload candidate Offers'))
    jobs.start(store,month,before['revision'])
    for _ in range(500):
        result=jobs.read(store,month)
        if result['status'] not in {'running','cancelling'}:break
        time.sleep(.01)
    assert result['status']=='complete',result
    assert calls==[('domestic',['zt3']),('overseas',['zt3'])]
    after=store.read(month)
    assert len(after['rows'])==1 and after.get('edits',[])==before.get('edits',[])
    assert '推荐人岗位与职级待核' not in after['rows'][0]['calculation']['referral']['issues']

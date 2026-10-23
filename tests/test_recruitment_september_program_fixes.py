"""Confirmed September defects, with unresolved business facts left intact."""
from copy import deepcopy

import pytest

from bonus_platform.engine.recruitment_awards import award, calculate_draft, country_currency
from bonus_platform.engine.recruitment_attention import needed
from bonus_platform.engine.recruitment_import_validation import _normalize_offer_channel, _classify_overseas_country
from bonus_platform.engine.recruitment_reconcile import monthly_comparison
from test_recruitment_awards import person


@pytest.mark.parametrize('selected', ['前程无忧', '前程無憂', '51job'])
def test_selected_website_channel_is_calculable(selected):
    row=person(招聘渠道=selected)
    assert _normalize_offer_channel(selected, '')[0]=='招聘网站'
    assert award(row,'recruitment',202607)['total']==award(person(),'recruitment',202607)['total']
    row['values'].update(招聘渠道='其他',其他渠道=selected,招聘渠道备注=selected)
    assert award(row,'recruitment',202607)['total']==0


@pytest.mark.parametrize('prefix,kind', [('招聘负责人','recruitment'),('协助招聘人','recruitment'),('推荐人','referral')])
def test_employed_status_alternatives_do_not_block_recipient(prefix,kind):
    row=person(**{prefix+'工号':'zt-recipient',prefix+'姓名':'领取人',prefix+'人员状态':'试用'})
    field=prefix+'人员状态'
    row.update(unresolvedFields=[field],conflicts=[{'field':field,'values':['试用','正式']}])
    before=deepcopy(row)
    result=award(row,kind,202607)
    nodes=[n for n in result['nodes'] if n['role']==prefix]
    assert nodes and all('领取人资料冲突' not in n['issues'] for n in nodes)
    assert row==before
    row['calculation']={k:award(row,k,202607) for k in ('recruitment','referral')}
    assert needed(row,field,202607)==[]


@pytest.mark.parametrize('alternative', ['离职','待入职','未入职','未知',''])
def test_departed_or_unknown_status_choices_stay_pending(alternative):
    row=person()
    field='招聘负责人人员状态'
    row.update(unresolvedFields=[field],conflicts=[{'field':field,'values':['正式',alternative]}])
    assert '领取人资料冲突' in award(row,'recruitment',202607)['nodes'][0]['issues']
    row['calculation']={k:award(row,k,202607) for k in ('recruitment','referral')}
    assert needed(row,field,202607)==['recruitment']


@pytest.mark.parametrize('field', ['招聘负责人工号','招聘负责人最后工作日'])
def test_employed_status_equivalence_does_not_hide_other_recipient_conflicts(field):
    row=person()
    row.update(unresolvedFields=['招聘负责人人员状态',field],
               conflicts=[{'field':'招聘负责人人员状态','values':['试用','正式']}])
    assert '领取人资料冲突' in award(row,'recruitment',202607)['nodes'][0]['issues']


def test_actual_departure_still_prevents_payment_with_equivalent_statuses():
    row=person(招聘负责人最后工作日='2026-07-20')
    row.update(unresolvedFields=['招聘负责人人员状态'],
               conflicts=[{'field':'招聘负责人人员状态','values':['试用','正式']}])
    node=award(row,'recruitment',202607)['nodes'][0]
    assert node['status']=='按规则不发'
    assert node['eligibilityReasons']==['招聘负责人：适用日期已不在职']


@pytest.mark.parametrize('org', ['UK销售组','FBU-UK','uk Sales','United Kingdom','England'])
def test_uk_organization_uses_european_standard_currency(org):
    values=person(二级组织=org,工作地='非中国/英国/英格兰/伯明翰')['values']
    currency,basis=country_currency(values)
    assert currency=='欧元' and basis.strip()==org
    assert _classify_overseas_country(org)=='海外发达国家'


@pytest.mark.parametrize('org,location', [('Phuket','Thailand/Phuket'),('Ukraine','Ukraine')])
def test_uk_alias_is_not_an_arbitrary_substring(org,location):
    assert _classify_overseas_country(org)!='海外发达国家'
    assert country_currency(person(二级组织=org,工作地=location)['values'])[0]=='美元'


def compare_special(row):
    state={'month':202609,'revision':1,'sources':[],'rows':[row],'todos':[],'summary':{}}
    calculate_draft(state)
    reference={'values':{**row['values'],'标准币种':'捷克克朗'},'ref':{'sheet':'核对表','row':2},'historyCells':[
        {'column':1,'label':'内推奖金 / 入职6个月 / 发放奖金','value':8000},
        {'column':2,'label':'发放周期','value':202609}]}
    return monthly_comparison(state,[reference],{'id':'reference','name':'核对表'})


def czech_row():
    row=person('2026-03-16',职级='P1-3',二级组织='捷克',工作地='捷克')
    row['rule']['specialScope']='FBU捷克'
    return row


def test_special_rule_explanation_is_not_a_qualification_failure():
    row=czech_row()
    result=compare_special(row)
    assert row['calculation']['referral']['reasons']==['按入职日期及部门适用FBU捷克旧内推规则']
    assert result['summary'].get('qualificationDifferenceNodes',0)==0
    assert row['calculation']['referral']['total']==8000
    assert not [d for d in result['differences'] if d['kind']=='内推奖金']


@pytest.mark.parametrize('case', ['role','approval','departure','missing-status'])
def test_genuine_qualification_failures_remain_in_comparison(case):
    row=czech_row()
    if case=='role':row['values']['推荐人职级']='M4-1'
    elif case=='approval':row['awardDecisions']=[{'kind':'referral','action':'exclude','basisType':'approval'}]
    elif case=='departure':row['values']['推荐人最后工作日']='2026-07-01'
    else:row['values']['推荐人人员状态']=''
    result=compare_special(row)
    assert result['summary']['qualificationDifferenceNodes']>0
    assert any(d['dimensions']['eligibility']['status']=='blocked' for d in result['differences'] if d['kind']=='内推奖金')

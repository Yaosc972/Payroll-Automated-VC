from copy import deepcopy
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
import runpy

import pytest
from openpyxl import load_workbook

from bonus_platform.engine.recruitment_awards import award, material_conflicts
from bonus_platform.engine.recruitment_monthly import recipient_summaries, export
from test_recruitment_awards import person

_helpers = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'docs/recruitment-audit-20261019/calculation-repro.py'))
fixture, checked, conflict, raw, confirm = (_helpers[k] for k in ('fixture', 'checked', 'conflict', 'raw', 'confirm'))


def test_mixed_currency_rows_and_export_totals_keep_actual_units():
    nodes = [dict(rowId='a', kind=kind, scope='current', role='招聘负责人' if kind=='recruitment' else '推荐人',
                  recipientId='zt1', recipientName='甲', currency=currency, label='入职满一个月',
                  amount=amount, review=False, reasons=[])
             for kind, currency, amount in [('recruitment','欧元',5),('recruitment','美元',8),('referral','人民币',300),('referral','欧元',200)]]
    state = {'month':202607, 'rows':[]}
    summaries = recipient_summaries(state,nodes)
    for kind, expected in [('recruitment',{'欧元':5,'美元':8}),('referral',{'人民币':300,'欧元':200})]:
        assert {r['currency']:r['confirmed'] for r in summaries[kind]['rows']} == expected
        assert {r['currency']:r['confirmed'] for r in summaries[kind]['totals']} == expected
    workbook = load_workbook(BytesIO(export(state, {'nodes':nodes,'recipientSummaries':summaries,
        'worksheet':{'columns':[{'key':'name','label':'姓名','group':'人员资料','type':'text'}],'rows':[]}})), data_only=True)
    for sheet, expected in [(workbook.worksheets[1],{'欧元':5,'美元':8}),(workbook.worksheets[2],{'人民币':300,'欧元':200})]:
        rows=list(sheet.values); headers=list(rows[1]); currency=headers.index('币种'); name=headers.index('姓名' if sheet==workbook.worksheets[1] else '内推人员姓名')
        amount=headers.index('合计发放' if sheet==workbook.worksheets[1] else '本月发放')
        assert {r[currency]:r[amount] for r in rows[2:] if r[name]=='合计'} == expected


def test_country_conflict_blocks_month_confirmation():
    with fixture() as (client, store, activity, base, state, values):
        state=conflict(client,base,state,{**values,'二级组织':'美国','工作地':'美国'})
        assert state['monthly']['cases']
        assert raw(store,activity)['rows'][0]['calculation']['recruitment']['total'] is None
        assert confirm(client,base,state) == 400


def test_zero_adopted_referrer_grade_does_not_hide_eligibility_conflict():
    with fixture(推荐人工号='zt-ref',推荐人姓名='推荐人',推荐人职级='P4-1') as (client,store,activity,base,state,values):
        state=conflict(client,base,state,{**values,'推荐人职级':'P2-1'})
        assert raw(store,activity)['rows'][0]['calculation']['referral']['total'] is None
        assert state['monthly']['cases']
        assert confirm(client,base,state) == 400


def test_irrelevant_domestic_organization_conflict_does_not_block():
    row=person(标签分类='国内',奖金地区类型='国内发展中国家')
    row.update(unresolvedFields=['二级组织'],conflicts=[{'field':'二级组织','values':['中国','美国']}])
    assert '二级组织' not in material_conflicts(row,'recruitment')
    assert award(row,'recruitment',202607)['total'] is not None


def test_confirmed_parent_installment_keeps_amount_and_reprices_only_remainder():
    with fixture() as (client,store,activity,base,state,values):
        assert confirm(client,base,state)==200
        prior=state['monthly']['nodes'][0]
        child=checked(client.post('/api/recruitment/activities',json={'month':202608,'opening':{'activityId':activity['id'],'revision':state['revision']}}))
        child_base=f"/api/recruitment/activities/{child['id']}/api/recruitment/drafts/202608"
        carried=checked(client.get(child_base))
        historical=next(n for n in carried['monthly']['nodes'] if n['id']==prior['id'])
        assert (historical['amount'],historical['month'],historical['openingLocked']) == (27.5,202607,True)
        changed=checked(client.post(child_base+'/changes',json={'revision':carried['revision'],'edits':[{'rowId':carried['rows'][0]['id'],'field':'招聘启动日期','value':'2026-06-27'}]}))
        future=next(n for n in changed['monthly']['nodes'] if n['label']=='入职满三个月')
        assert future['amount']==44
        assert all(n['paidAmount'] is None and n['paymentStatus']=='未核实' for n in changed['monthly']['nodes'])


@pytest.mark.parametrize('field,value', [('ABC类别','B'),('招聘渠道','猎头')])
def test_invalid_eligibility_exception_remains_actionable_even_without_node(field,value):
    with fixture(招聘负责人最后工作日='2026-01-01') as (client,store,activity,base,state,values):
        node=state['monthly']['nodes'][0]
        preview=checked(client.post(base+'/special/preview',json={'revision':state['revision'],'basisType':'manual','type':'exception',
            'rowId':node['rowId'],'nodeId':node['id'],'kind':'recruitment','month':202607,'conditions':['recipient_not_employed']}))
        applied=checked(client.post(base+'/special/previews/'+preview['id']+'/apply',json={'revision':state['revision']}))
        changed=checked(client.post(base+'/changes',json={'revision':applied['revision'],'edits':[{'rowId':node['rowId'],'field':field,'value':value}]}))
        assert changed['monthly']['cases']
        assert any('资格例外' in reason for p in changed['ruleValidation']['problems'] for reason in p['reasons'])
        assert confirm(client,base,changed)==400


def confirmed_state():
    from bonus_platform.engine.recruitment_awards import calculate_row
    from bonus_platform.engine.recruitment_settlement import capture_confirmed_installments
    row=person(推荐人工号='',推荐人姓名='')
    parent={'month':202607,'revision':1,'rows':[row],'sources':[],'operations':[], 'settlement':{'baselineId':None}}
    row['calculation']=calculate_row(parent,row)
    child=deepcopy(parent);child['month']=202608
    child['confirmedInstallments']=capture_confirmed_installments(parent)
    return child,child['rows'][0]


def test_confirmed_history_excludes_future_and_deduplicates_overlapping_excel():
    from bonus_platform.engine.recruitment_awards import calculate_row
    from bonus_platform.engine.recruitment_settlement import capture_confirmed_installments
    state,row=confirmed_state()
    assert len(state['confirmedInstallments'])==1
    assert state['confirmedInstallments'][0]['amount']==27.5
    state['settlement']['baselineId']='ledger'
    row['history']=[{'ref':{'sourceId':'ledger'},'cells':[{'column':c,'value':v} for c,v in
        [(39,27.5),(40,202607),(22,'zt-owner'),(23,'招聘负责人'),(56,'欧元')]]}]
    row['values']['招聘启动日期']='2026-06-27'
    row['calculation']=calculate_row(state,row)
    nodes=row['calculation']['recruitment']['nodes']
    assert [n['amount'] for n in nodes]==[27.5,44]
    assert not row['calculation']['recruitment']['recoveries']
    carried=capture_confirmed_installments(state)
    assert len(carried)==1
    assert carried[0]['confirmedMonth']==202607


@pytest.mark.parametrize('change,issue', [({'招聘负责人工号':'zt-new'},'领取人'),
    ({'二级组织':'美国','工作地':'美国'},'币种'),({'招聘渠道':'猎头'},'不再形成')])
def test_changed_entitlement_preserves_confirmed_fact_and_requires_recheck(change,issue):
    from bonus_platform.engine.recruitment_awards import calculate_row
    state,row=confirmed_state();row['values'].update(change)
    result=calculate_row(state,row)['recruitment']
    prior=next(n for n in result['nodes'] if n.get('openingLocked'))
    assert (prior['recipientId'],prior['currency'],prior['amount'],prior['scheduledMonth'])==('zt-owner','欧元',27.5,202607)
    assert any(issue in r['reason'] for r in result['accountingIssues'])
    assert all(n['paidAmount'] is None and n['paymentStatus']=='未核实' for n in result['nodes'])
    if issue=='币种':
        assert next(n for n in result['nodes'] if not n.get('openingLocked'))['amount']==55
        assert result['scheduledTotal'] is None


def test_conflicting_excel_history_is_visible_without_double_deduction():
    from bonus_platform.engine.recruitment_awards import calculate_row
    state,row=confirmed_state();state['settlement']['baselineId']='ledger'
    row['history']=[{'ref':{'sourceId':'ledger'},'cells':[{'column':c,'value':v} for c,v in
        [(39,30),(40,202607),(22,'zt-owner'),(23,'招聘负责人'),(56,'欧元')]]}]
    result=calculate_row(state,row)['recruitment']
    assert [n['amount'] for n in result['nodes']]==[27.5,27.5]
    assert any('台账不一致' in r['reason'] for r in result['accountingIssues'])


@pytest.mark.parametrize('adjustment_amount',[10,-10])
def test_confirmed_adjustment_is_retained_independently_of_rule_remainder(adjustment_amount):
    from bonus_platform.engine.recruitment_awards import calculate_row
    state,row=confirmed_state()
    state['confirmedInstallments'].append({**state['confirmedInstallments'][0],'originKey':'adjustment-origin',
        'nodeId':'adjustment','adjustmentId':'adjustment','label':'补发' if adjustment_amount>0 else '扣回','amount':adjustment_amount})
    row['values']['招聘启动日期']='2026-06-27'
    result=calculate_row(state,row)['recruitment']
    assert next(n for n in result['nodes'] if n['label']=='入职满三个月')['amount']==44
    supplement=next(n for n in result['nodes'] if n.get('adjustmentId'))
    assert supplement['amount']==adjustment_amount and supplement['scheduledMonth']==202607
    assert len(result['nodes'])==3
    from bonus_platform.engine.recruitment_settlement import capture_confirmed_installments
    row['calculation']={'recruitment':result,'referral':calculate_row(state,row)['referral']}
    history=capture_confirmed_installments(state)
    assert len(history)==2
    assert capture_confirmed_installments({**state,'confirmedInstallments':history})==history


def test_confirmed_arrangements_accumulate_without_locking_future_or_payment():
    from bonus_platform.engine.recruitment_awards import calculate_row
    from bonus_platform.engine.recruitment_settlement import capture_confirmed_installments
    state,row=confirmed_state()
    state['month']=202609
    row['calculation']=calculate_row(state,row)
    state['confirmedInstallments']=capture_confirmed_installments(state)
    assert sorted(r['confirmedMonth'] for r in state['confirmedInstallments'])==[202607,202609]
    assert capture_confirmed_installments(state)==state['confirmedInstallments']
    state['month']=202610;state.pop('settlement')
    row['calculation']=calculate_row(state,row)
    assert all(n['openingLocked'] for n in row['calculation']['recruitment']['nodes'])
    assert row['calculation']['recruitment']['currentAmount']==0
    assert not row['calculation']['recruitment']['accountingIssues']


def test_repriced_award_after_all_installments_confirmed_keeps_difference_actionable():
    from bonus_platform.engine.recruitment_awards import calculate_row, calculate_draft
    from bonus_platform.engine.recruitment_settlement import capture_confirmed_installments
    from bonus_platform.engine.recruitment_attention import project
    state,row=confirmed_state()
    state['month']=202609
    row['calculation']=calculate_row(state,row)
    state['confirmedInstallments']=capture_confirmed_installments(state)
    state['month']=202610
    row['values']['招聘启动日期']='2026-06-27'
    state.update(todos=[],summary={})
    calculate_draft(state)
    result=row['calculation']['recruitment']
    assert result['total']==71.5 and result['scheduledTotal']==55
    assert [n['amount'] for n in result['nodes']]==[27.5,27.5]
    assert any(r['amount']==16.5 for r in result['recoveries'])
    assert any(i['accountingMonth']==202610 for i in result['accountingIssues'])
    assert project(state)['current']


@pytest.mark.parametrize('field,values', [('二级组织',['德国','法国']),('工作地',['德国','美国'])])
def test_country_choices_with_proven_same_currency_do_not_add_todos(field,values):
    row=person();row.update(unresolvedFields=[field],conflicts=[{'field':field,'values':values}])
    assert field not in material_conflicts(row,'recruitment')


@pytest.mark.parametrize('grades,expected',[(['P1-1','P2-1'],400),(['P4-1','P5-1'],0)])
def test_equivalent_referral_eligibility_conflicts_keep_rule_result(grades,expected):
    row=person(推荐人职级=grades[0]);row.update(unresolvedFields=['推荐人职级'],conflicts=[{'field':'推荐人职级','values':grades}])
    assert '推荐人职级' not in material_conflicts(row,'referral')
    assert award(row,'referral',202607)['total']==expected



@pytest.mark.parametrize('kind,field,choices,values',[
    ('referral','推荐人职级',['P4-1','P5-1',''],{'推荐人职级':'P4-1'}),
    ('recruitment','二级组织',['德国','法国',''],{'工作地':'美国'}),
])
def test_empty_conflicting_fact_is_not_discarded_when_proving_equivalence(kind,field,choices,values):
    row=person(**values)
    row.update(unresolvedFields=[field],conflicts=[{'field':field,'values':choices}])
    assert field in material_conflicts(row,kind)
    assert award(row,kind,202607)['total'] is None


@contextmanager
def completed_installment_activity():
    from test_recruitment_drafts import book
    with fixture() as (client,store,activity,base,state,values):
        def refresh_roster(base,state):
            return checked(client.post(base+'/sources',data={'revision':state['revision'],'periodConfirmed':'true'},
                files=[('files',('本月花名册.xlsx',book(['姓名','工号','入职日期','人员状态','人员来源'],
                    [[values['姓名'],values['工号'],values['入职日期'],'正式','OEHR入职']])))]))
        assert confirm(client,base,state)==200
        for month in (202608,202609,202610):
            activity=checked(client.post('/api/recruitment/activities',json={'month':month,
                'opening':{'activityId':activity['id'],'revision':state['revision']}}))
            base=f"/api/recruitment/activities/{activity['id']}/api/recruitment/drafts/{month}"
            state=refresh_roster(base,checked(client.get(base)))
            if month<202610:assert confirm(client,base,state)==200
        yield client,store,activity,base,state,refresh_roster


def test_completed_installment_reprice_can_be_settled_revoked_and_carried_by_existing_adjustment_api():
    with completed_installment_activity() as (client,store,activity,base,state,refresh_roster):
        row=state['rows'][0]
        state=checked(client.post(base+'/changes',json={'revision':state['revision'],'edits':[
            {'rowId':row['id'],'field':'招聘启动日期','value':'2026-06-27'}]}))
        assert state['monthly']['cases'] and confirm(client,base,state)==400
        node=state['monthly']['nodes'][0]
        payload={'basisType':'manual','type':'adjustment','rowId':row['id'],'nodeId':node['id'],
                 'kind':'recruitment','month':202610,'role':'招聘负责人','currency':'欧元','amount':16.5,
                 'recipientId':node['recipientId'],'recipientName':node['recipientName']}
        preview=checked(client.post(base+'/special/preview',json={**payload,'revision':state['revision']}))
        applied=checked(client.post(base+'/special/previews/'+preview['id']+'/apply',json={'revision':state['revision']}))
        assert not applied['monthly']['cases']
        assert confirm(client,base,applied)==200
        supplement=next(n for n in applied['monthly']['nodes'] if n.get('adjustmentId'))
        assert supplement['amount']==16.5 and supplement['paymentStatus']=='未核实'
        revoked_preview=checked(client.post(base+'/special/preview',json={'revision':applied['revision'],
            'type':'revoke','recordId':supplement['adjustmentId']}))
        revoked=checked(client.post(base+'/special/previews/'+revoked_preview['id']+'/apply',json={'revision':applied['revision']}))
        assert revoked['monthly']['cases'] and confirm(client,base,revoked)==400
        preview=checked(client.post(base+'/special/preview',json={**payload,'revision':revoked['revision']}))
        reapplied=checked(client.post(base+'/special/previews/'+preview['id']+'/apply',json={'revision':revoked['revision']}))
        assert not reapplied['monthly']['cases'] and confirm(client,base,reapplied)==200
        child=checked(client.post('/api/recruitment/activities',json={'month':202611,
            'opening':{'activityId':activity['id'],'revision':reapplied['revision']}}))
        next_base=f"/api/recruitment/activities/{child['id']}/api/recruitment/drafts/202611"
        carried=refresh_roster(next_base,checked(client.get(next_base)))
        assert not carried['monthly']['cases'] and confirm(client,next_base,carried)==200
        assert [n['amount'] for n in carried['monthly']['nodes']]==[27.5,27.5,16.5]
        assert all(n['scope']=='history' and n['paidAmount'] is None for n in carried['monthly']['nodes'])


@pytest.mark.parametrize('override',[{'recipientId':'zt-unrelated'},{'role':'协助招聘人'}, {'amount':10}, {'month':202611}])
def test_unrelated_or_future_adjustment_cannot_close_unallocated_difference(override):
    with completed_installment_activity() as (client,store,activity,base,state,refresh_roster):
        rid=state['rows'][0]['id']
        state=checked(client.post(base+'/changes',json={'revision':state['revision'],'edits':[
            {'rowId':rid,'field':'招聘启动日期','value':'2026-06-27'}]}))
        node=state['monthly']['nodes'][0]
        preview=checked(client.post(base+'/special/preview',json={'revision':state['revision'],'basisType':'manual',
            'type':'adjustment','rowId':rid,'nodeId':node['id'],'kind':'recruitment','month':202610,
            'role':'招聘负责人','currency':'欧元','amount':16.5,'recipientId':node['recipientId'],
            'recipientName':node['recipientName'],**override}))
        applied=checked(client.post(base+'/special/previews/'+preview['id']+'/apply',json={'revision':state['revision']}))
        assert applied['monthly']['cases'] and confirm(client,base,applied)==400
        assert any(r['amount']==16.5 for r in applied['rows'][0]['calculation']['recruitment']['recoveries'])


def test_changed_fingerprint_reopens_previously_settled_difference():
    with completed_installment_activity() as (client,store,activity,base,state,refresh_roster):
        rid=state['rows'][0]['id']
        state=checked(client.post(base+'/changes',json={'revision':state['revision'],'edits':[
            {'rowId':rid,'field':'招聘启动日期','value':'2026-06-27'}]}))
        node=state['monthly']['nodes'][0]
        preview=checked(client.post(base+'/special/preview',json={'revision':state['revision'],'basisType':'manual',
            'type':'adjustment','rowId':rid,'nodeId':node['id'],'kind':'recruitment','month':202610,
            'role':'招聘负责人','currency':'欧元','amount':16.5,'recipientId':node['recipientId'],'recipientName':node['recipientName']}))
        applied=checked(client.post(base+'/special/previews/'+preview['id']+'/apply',json={'revision':state['revision']}))
        assert not applied['monthly']['cases']
        changed=checked(client.post(base+'/changes',json={'revision':applied['revision'],'edits':[
            {'rowId':rid,'field':'职级','value':'P2-1'}]}))
        assert changed['monthly']['cases'] and confirm(client,base,changed)==400
        assert any(n.get('adjustmentId') and n['issues'] for n in changed['monthly']['nodes'])


def test_removed_role_history_has_one_actionable_recovery_for_same_amount():
    from bonus_platform.engine.recruitment_awards import calculate_row
    state,row=confirmed_state()
    row['values']['招聘渠道']='猎头'
    result=calculate_row(state,row)['recruitment']
    assert len(result['recoveries'])==1
    assert result['recoveries'][0]['amount']==27.5
    assert '不再形成' in result['recoveries'][0]['reason']
    assert len(result['accountingIssues'])==1

from copy import deepcopy
from io import BytesIO

import pytest
from openpyxl import Workbook

from bonus_platform.engine import recruitment_external_results as external
from bonus_platform.engine.recruitment_attention import project as attention, recipient_requirements
from bonus_platform.engine.recruitment_drafts import DraftStore, DraftConflict
from bonus_platform.engine.recruitment_monthly import project as monthly
from test_recruitment_awards import person
from test_recruitment_drafts import book
from test_recruitment_external_results import upload, adopt


def setup_people(tmp_path, people):
    store=DraftStore(tmp_path)
    fields=list(dict.fromkeys(field for values in people for field in values))
    headers=['体系外人员编号']+fields
    state=store.ingest(202608,[('人员资料.xlsx',book(headers,[[v['工号']]+[v.get(f,'') for f in fields] for v in people]))],0)
    return store,state


def candidate_scope(row):
    return {'target':'candidate','rowId':row['id']}


def recipient_scope(number='zt-outside'):
    return {'target':'recipient','recipientId':number,'recipientName':'体系外负责人','kind':'recruitment','role':'招聘负责人'}


def scoped_person(name='候选人',number='zt-candidate',hire='2026-07-02',**values):
    return person(hire,姓名=name,工号=number,推荐人工号='',推荐人姓名='',招聘负责人工号='zt-outside',
                  招聘负责人姓名='体系外负责人',招聘负责人入职日期='',招聘负责人人员状态='',**values)['values']


def test_candidate_scope_routes_missing_internal_facts_to_one_external_action(tmp_path):
    values=scoped_person(hire='2026-08-01')
    for field in ('ABC类别','招聘渠道','招聘启动日期','招聘负责人工号','招聘负责人姓名'):
        values[field]=''
    store,state=setup_people(tmp_path,[values])
    state=external.apply_scope(store,202608,state['revision'],[candidate_scope(state['rows'][0])])
    row=state['rows'][0]
    assert not external.automatic_roles(row,'recruitment')
    assert not external.automatic_roles(row,'referral')
    assert row['calculation']['recruitment']['currentAmount'] is None
    assert row['calculation']['referral']['currentAmount'] is None
    assert {r['project'] for r in external.context(store,state)['expected']}=={'招聘负责人奖金','内推奖金'}
    items=monthly(state,attention(state))['workItems']
    assert len([w for w in items if w['key']=='external_results'])==1
    assert not [w for w in items if row['id'] in w.get('rowIds',[]) and w['key'].startswith(('intake','recipient'))]
    assert not any(n.get('amount') is not None for n in row['calculation']['recruitment']['nodes'] if n.get('externalResultId'))


def test_recipient_scope_owns_only_that_role_and_only_current_due_slots(tmp_path):
    due=scoped_person(协助招聘人工号='zt-assistant',协助招聘人姓名='内部协助人',协助招聘人入职日期='2020-01-01',协助招聘人人员状态='正式')
    future=scoped_person(name='下月入职满月',number='zt-future',hire='2026-08-02')
    old=scoped_person(name='旧工号',number='zt-old-candidate')
    old['招聘负责人工号']='zt-old-outside'
    store,state=setup_people(tmp_path,[due,future,old])
    before=deepcopy(state)
    state=external.apply_scope(store,202608,state['revision'],[recipient_scope()])
    expected=external.context(store,state)['expected']
    assert len(expected)==1 and expected[0]['candidateName']=='候选人'
    row=next(r for r in state['rows'] if r['values']['姓名']=='候选人')
    assert external.automatic_roles(row,'recruitment')=={'协助招聘人'}
    assert recipient_requirements(state,202608)['currentRecipients']=={'zt-assistant','zt-old-outside'}
    fields=('role','amount','currency','dueDate','dueMonth','scheduledMonth')
    def other_nodes(rows):
        r=next(r for r in rows if r['values']['姓名']=='候选人')
        return [{f:n.get(f) for f in fields} for n in r['calculation']['recruitment']['nodes'] if n['role']=='协助招聘人']
    assert other_nodes(state['rows'])==other_nodes(before['rows'])
    assert next(r for r in state['rows'] if r['values']['姓名']=='旧工号')['calculation']==next(r for r in before['rows'] if r['values']['姓名']=='旧工号')['calculation']
    assert row['calculation']['referral']==next(r for r in before['rows'] if r['id']==row['id'])['calculation']['referral']


def test_scope_retries_undo_and_redo_keep_one_operation(tmp_path):
    store,state=setup_people(tmp_path,[scoped_person()])
    original=deepcopy(state['rows'][0]['calculation'])
    scopes=[recipient_scope()]
    state=external.apply_scope(store,202608,state['revision'],scopes)
    revision=state['revision'];operations=len(state['operations'])
    repeated=external.apply_scope(store,202608,revision,scopes)
    assert repeated['revision']==revision and len(repeated['operations'])==operations
    undone=store.history_action(202608,revision,'undo')
    assert not external.context(store,undone)['expected']
    assert undone['rows'][0]['calculation']==original
    redone=store.history_action(202608,undone['revision'],'redo')
    assert len(external.context(store,redone)['expected'])==1


def test_scope_is_carried_but_never_reuses_monthly_amount(tmp_path):
    store,state=setup_people(tmp_path,[scoped_person(),scoped_person(name='后月到期',number='zt-future',hire='2026-08-02')])
    state=external.apply_scope(store,202608,state['revision'],[recipient_scope()])
    preview=upload(store,[['候选人','招聘负责人奖金','体系外负责人',32,'EUR','zt-candidate','','zt-outside']],state['revision'])
    state=adopt(store,preview)
    assert not external.context(store,state)['expected']
    carried=store.carry_forward(202609,202608,0)
    assert len(carried.get('externalScopes',[]))==1
    assert {r['candidateName'] for r in external.context(store,carried)['expected']}=={'后月到期'}
    assert not any(n.get('externalResultId') and n.get('scheduledMonth')==202609 and n.get('amount') for r in carried['rows'] for n in r['calculation']['recruitment']['nodes'])


def test_scope_invalid_inputs_stale_revision_and_confirmed_month_do_not_write(tmp_path):
    store,state=setup_people(tmp_path,[scoped_person()])
    path=store._folder(202608)/'draft.json';original=path.read_bytes()
    with pytest.raises(ValueError):
        external.apply_scope(store,202608,state['revision'],[candidate_scope(state['rows'][0]),{'target':'candidate','rowId':'missing'}])
    assert path.read_bytes()==original
    with pytest.raises(DraftConflict):external.apply_scope(store,202608,0,[recipient_scope()])
    assert path.read_bytes()==original
    store._write(store._folder(202608)/'accepted.json',{'revision':state['revision'],'state':state})
    with pytest.raises(ValueError,match='确认'):external.apply_scope(store,202608,state['revision'],[recipient_scope()])
    assert path.read_bytes()==original


def test_original_ledger_accepts_declared_normal_id_without_importing_unrelated_people(tmp_path):
    store,state=setup_people(tmp_path,[scoped_person()])
    state=external.apply_scope(store,202608,state['revision'],[recipient_scope()])
    wb=Workbook();ws=wb.active;ws.title='附件一-招聘奖金核算明细'
    for index,recipient in enumerate(('zt-outside','zt-old-outside','zt-unrelated'),1):
        cells=[None]*69
        for column,value in {1:index,2:'候选人' if index==1 else '其他'+str(index),3:'zt-candidate' if index==1 else 'zt-'+str(index),5:'2026-07-02',22:recipient,23:'体系外负责人',39:32,40:202608,56:'EUR'}.items():cells[column-1]=value
        ws.append(cells)
    content=BytesIO();wb.save(content)
    preview=external.prepare_import(store,202608,state['revision'],[('全球招聘奖金核算明细表202608.xlsx',content.getvalue())])
    assert len(preview['rows'])==1 and preview['rows'][0]['recipientId']=='zt-outside'
    assert preview['readyCount']==1


def test_scoped_recipient_with_cancelled_current_installment_does_not_need_result(tmp_path):
    values=scoped_person(招聘负责人最后工作日='2026-07-20')
    store,state=setup_people(tmp_path,[values])
    assert any(n['dueMonth']==202608 and n['scheduledMonth'] is None for n in state['rows'][0]['calculation']['recruitment']['nodes'])
    state=external.apply_scope(store,202608,state['revision'],[recipient_scope()])
    assert not external.context(store,state)['expected']


def test_scopes_do_not_classify_other_virtual_employees_or_a_different_id(tmp_path):
    first=scoped_person(name='待归类人员',number='zt-one')
    other=scoped_person(name='其他虚拟员工',number='zt-two')
    other['是否虚拟员工']='是'
    store,state=setup_people(tmp_path,[first,other])
    target=next(r for r in state['rows'] if r['values']['工号']=='zt-one')
    state=external.apply_scope(store,202608,state['revision'],[candidate_scope(target)])
    untouched=next(r for r in state['rows'] if r['values']['工号']=='zt-two')
    assert external.automatic_roles(untouched,'recruitment')=={'招聘负责人'}
    assert not any(r['rowId']==untouched['id'] for r in external.context(store,state)['expected'])


def test_unknown_rule_amount_keeps_a_current_external_result_entry(tmp_path):
    store,state=setup_people(tmp_path,[scoped_person(ABC类别='')])
    assert state['rows'][0]['calculation']['recruitment']['total'] is None
    state=external.apply_scope(store,202608,state['revision'],[recipient_scope()])
    assert len(external.context(store,state)['expected'])==1
    assert any(w['key']=='external_results' and w.get('current',True) for w in monthly(state,attention(state))['workItems'])
    assert state['rows'][0]['calculation']['recruitment']['currentAmount'] is None


def test_unknown_referral_stays_actionable_after_recruitment_result_is_adopted(tmp_path):
    values=scoped_person(ABC类别='',招聘渠道='')
    store,state=setup_people(tmp_path,[values])
    state=external.apply_scope(store,202608,state['revision'],[candidate_scope(state['rows'][0])])
    state=adopt(store,upload(store,[['候选人','招聘负责人奖金','体系外负责人',32,'EUR','zt-candidate','','zt-outside']],state['revision']))
    assert [r['project'] for r in external.context(store,state)['expected']]==['内推奖金']
    assert state['rows'][0]['calculation']['referral']['currentAmount'] is None
    assert any(w['key']=='external_results' for w in monthly(state,attention(state))['workItems'])
    state=adopt(store,upload(store,[['候选人','内推奖金','',0,'EUR','zt-candidate']],state['revision']))
    assert not external.context(store,state)['expected']
    assert state['rows'][0]['calculation']['referral']['currentAmount']==0


def test_known_non_referral_channel_does_not_require_an_extra_zero_result(tmp_path):
    store,state=setup_people(tmp_path,[scoped_person()])
    state=external.apply_scope(store,202608,state['revision'],[candidate_scope(state['rows'][0])])
    assert [r['project'] for r in external.context(store,state)['expected']]==['招聘负责人奖金']
    assert state['rows'][0]['calculation']['referral']['currentAmount']==0


def test_existing_preview_is_pending_adoption_and_not_a_duplicate_missing_material(tmp_path):
    store,state=setup_people(tmp_path,[scoped_person(),scoped_person(name='确缺结果',number='zt-missing',hire='2026-08-02')])
    missing=next(r for r in state['rows'] if r['values']['姓名']=='确缺结果')
    state=external.apply_scope(store,202608,state['revision'],[recipient_scope(),candidate_scope(missing)])
    preview=upload(store,[['候选人','招聘负责人奖金','体系外负责人',32,'EUR','zt-candidate','','zt-outside']],state['revision'])
    state=store.read(202608)
    missing_tasks=[t for t in attention(state)['current'] if t['kind']=='external_results_missing']
    assert len(missing_tasks)==1 and set(missing_tasks[0]['rowIds'])=={missing['id']}
    assert preview['readyCount']==1
    assert any(t['kind']=='external_results_pending' for t in attention(state)['current'])
    row=next(r for r in state['rows'] if r['values']['姓名']=='候选人')
    assert row['calculation']['recruitment']['currentAmount'] is None

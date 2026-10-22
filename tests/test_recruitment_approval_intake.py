from copy import deepcopy
from pathlib import Path
import json

import pytest
from PIL import Image

from bonus_platform.engine import recruitment_approval_intake as intake
from bonus_platform.engine import recruitment_documents as documents
from bonus_platform.engine import recruitment_reviews as reviews
from bonus_platform.engine.recruitment_drafts import DraftStore, DraftConflict
from test_recruitment_drafts import book
from test_recruitment_awards import person


def setup(tmp_path, monkeypatch, bodies, people=None):
    people = people or [dict(姓名='候选甲',工号='zt12345',海外offer流程编号='202608170020',招聘渠道='招聘网站',推荐人姓名='',推荐人工号='')]
    values = [person(**p)['values'] for p in people]
    for i,v in enumerate(values):v['体系外人员编号']='approval-fixture-'+str(i)
    keys = list(dict.fromkeys(k for v in values for k in v))
    store = DraftStore(tmp_path)
    state = store.ingest(202607,[('原始资料.xlsx',book(keys,[[v.get(k,'') for k in keys] for v in values]))],0)
    def extract(path, folder):
        raw = bodies[path.read_text()]
        return {'pages':[{'page':1,'text':raw,'blank':False}], 'pageCount':1,'version':documents.DOCUMENT_VERSION}
    monkeypatch.setattr(intake,'extract_document',extract)
    monkeypatch.setattr(reviews,'extract_document',extract)
    monkeypatch.setattr(documents,'extract_document',extract)
    state = store.ingest(202607,[(name+'.pdf',name.encode()) for name in bodies],state['revision'])
    return store,state


def test_upload_recognizes_explicit_fields_and_never_adopts(tmp_path,monkeypatch):
    store,state=setup(tmp_path,monkeypatch,{'周期':'候选人：候选甲。申请剔除10天签证办理时间。'})
    before=deepcopy(state);data=intake.proposals(store,state)
    item=data['items'][0]
    assert item['person']['rowId']==state['rows'][0]['id']
    assert item['status']=='ready'
    assert next(f['value'] for f in item['fields'] if f['field']=='周期剔除天数')==10
    assert store.read(202607)==before


def test_batch_apply_keeps_each_original_and_supports_retry_undo_redo(tmp_path,monkeypatch):
    store,state=setup(tmp_path,monkeypatch,{'周期':'候选人：候选甲。申请剔除10天签证办理时间。',
        '岗位':'候选甲招聘奖金申请按B类岗位标准核算。'})
    data=intake.proposals(store,state);ids=[i['id'] for i in data['items']]
    preview=intake.preview(store,202607,{'revision':state['revision'],'itemIds':ids})
    assert store.read(202607)==state
    saved=reviews.apply_preview(store,202607,state['revision'],preview['id'])
    assert len(saved['reviewEntries'])==2
    assert len({e['evidenceId'] for e in saved['edits']})==2
    assert all(e['evidencePages']==[1] for e in saved['edits'])
    assert reviews.apply_preview(store,202607,state['revision'],preview['id'])==saved
    assert all(i['status']=='consistent' for i in intake.proposals(store,saved)['items'])
    undone=store.history_action(202607,saved['revision'],'undo')
    assert all(i['status']=='ready' for i in intake.proposals(store,undone)['items'])
    redone=store.history_action(202607,undone['revision'],'redo')
    assert all(i['status']=='consistent' for i in intake.proposals(store,redone)['items'])


def test_recipient_role_transfer_retains_both_people_and_requires_channel(tmp_path,monkeypatch):
    store,state=setup(tmp_path,monkeypatch,{'更正':
        '申请说明：\n1.在zt12345入职的offer流程中，因zt67890为非HRAS线员工，申请从招聘协助人改为内推人。\n'
        '2.在zt12346入职的offer流程中，因zt67890为HRAS线员工，申请从内推人改为招\n聘协助人。'},[
        dict(姓名='候选甲',工号='zt12345',协助招聘人姓名='领取甲',协助招聘人工号='zt67890',推荐人姓名='',推荐人工号='',招聘渠道='招聘网站'),
        dict(姓名='候选乙',工号='zt12346',推荐人姓名='领取甲',推荐人工号='zt67890',招聘渠道='内推')])
    data=intake.proposals(store,state)
    assert len(data['items'])==2
    second=data['items'][1]
    assert second['status']=='blocked' and '实际招聘渠道' in str(second['issues'])
    with pytest.raises(ValueError,match='渠道'):intake.preview(store,202607,{'revision':state['revision'],'itemIds':[second['id']]})
    preview=intake.preview(store,202607,{'revision':state['revision'],'itemIds':[i['id'] for i in data['items']],
        'overrides':{second['id']:{'fields':{'招聘渠道':'招聘网站'}}}})
    saved=reviews.apply_preview(store,202607,state['revision'],preview['id'])
    assert all(i['status']=='consistent' for i in intake.proposals(store,saved)['items'])
    row=next(r for r in saved['rows'] if r['values']['姓名']=='候选乙')
    assert row['values']['推荐人工号']=='' and row['values']['协助招聘人工号']=='zt67890'


def test_same_name_or_multiple_employments_require_selection(tmp_path,monkeypatch):
    store,state=setup(tmp_path,monkeypatch,{'审批':'候选甲申请剔除10天。'},[
        dict(姓名='候选甲',工号='zt12345'),dict(姓名='候选甲',工号='zt12346')])
    item=intake.proposals(store,state)['items'][0]
    assert item['status']=='blocked' and len(item['matches'])==2
    with pytest.raises(ValueError):intake.preview(store,202607,{'revision':state['revision'],'itemIds':[item['id']]})
    preview=intake.preview(store,202607,{'revision':state['revision'],'itemIds':[item['id']],
        'overrides':{item['id']:{'rowId':state['rows'][0]['id']}}})
    assert preview['people']==1


def test_date_disambiguates_namesakes_and_missing_history_is_specific(tmp_path,monkeypatch):
    store,state=setup(tmp_path,monkeypatch,{'审批':'候选甲于2026年5月1日入职，申请按B类岗位标准核算。'},[
        dict(姓名='候选甲',工号='zt12345'),dict(姓名='候选甲',工号='zt12346')])
    # Original roster contains an earlier employment not yet carried forward.
    sid=state['sources'][0]['id'];path=store._folder(202607)/'parsed'/f'{sid}.json'
    parsed=json.loads(path.read_text())
    parsed['records'].append({'role':'roster','values':{'姓名':'候选甲','工号':'zt12347','入职日期':'2026-05-01'}})
    store._write(path,parsed);intake.original_people.cache_clear()
    item=intake.proposals(store,state)['items'][0]
    assert item['person']['employeeId']=='zt12347' and item['status']=='blocked'
    assert '上月核算表' in str(item['issues'])


def test_unknown_wording_can_be_completed_without_review_metadata(tmp_path,monkeypatch):
    store,state=setup(tmp_path,monkeypatch,{'审批':'录用信息请按已沟通方案修订。'})
    item=intake.proposals(store,state)['items'][0]
    assert item['status']=='blocked'
    preview=intake.preview(store,202607,{'revision':state['revision'],'itemIds':[item['id']],
        'overrides':{item['id']:{'rowId':state['rows'][0]['id'],'fields':{'ABC类别':'B'}}}})
    saved=reviews.apply_preview(store,202607,state['revision'],preview['id'])
    assert intake.proposals(store,saved)['items'][0]['status']=='consistent'


def test_missing_attachment_is_automatic_when_supplied_and_never_ignored(tmp_path,monkeypatch):
    store,state=setup(tmp_path,monkeypatch,{'审批':'候选甲申请剔除10天。附件：名单.xlsx'})
    item=intake.proposals(store,state)['items'][0]
    assert item['status']=='blocked' and '名单.xlsx' in str(item['issues'])
    with pytest.raises(ValueError,match='名单.xlsx'):intake.preview(store,202607,{'revision':state['revision'],'itemIds':[item['id']]})
    state=store.ingest(202607,[('名单.xlsx',book(['姓名','工号'],[['候选甲','zt12345']]))],state['revision'])
    item=intake.proposals(store,state)['items'][0]
    preview=intake.preview(store,202607,{'revision':state['revision'],'itemIds':[item['id']]})
    assert preview['approvalReviews'][0]['attachmentIds']


def test_conflicting_approvals_and_stale_revisions_cannot_apply(tmp_path,monkeypatch):
    store,state=setup(tmp_path,monkeypatch,{'一':'候选甲申请剔除10天。','二':'候选甲申请剔除15天。'})
    ids=[i['id'] for i in intake.proposals(store,state)['items']]
    with pytest.raises(ValueError,match='不同调整值'):intake.preview(store,202607,{'revision':state['revision'],'itemIds':ids})
    with pytest.raises(DraftConflict):intake.preview(store,202607,{'revision':0,'itemIds':ids[:1]})
    with pytest.raises(ValueError):intake.preview(store,202607,{'revision':state['revision'],'itemIds':ids[:1],'overrides':{ids[0]:{'rowId':'foreign'}}})
    assert store.read(202607)==state


def test_applicant_and_offer_prefix_are_not_used_as_target(tmp_path,monkeypatch):
    store,state=setup(tmp_path,monkeypatch,{'候选甲提交':'offer流程2026081700201申请剔除10天。'})
    item=intake.proposals(store,state)['items'][0]
    assert item['status']=='blocked' and not item['person']['rowId']


def test_source_disabled_and_unapproved_status_are_not_actionable(tmp_path,monkeypatch):
    store,state=setup(tmp_path,monkeypatch,{'审批':'候选甲申请剔除10天。审批状态：已撤回'})
    item=intake.proposals(store,state)['items'][0]
    assert item['status']=='blocked' and '尚未通过' in str(item['issues'])
    state['sources'][-1]['active']=False
    assert intake.proposals(store,state)['items']==[]


def test_blank_page_is_ignored_but_unreadable_printed_page_is_not(tmp_path):
    Image.new('RGB',(100,100),'white').save(tmp_path/'page-1.png')
    image=Image.new('RGB',(100,100),'white');image.putpixel((20,20),(0,0,0));image.save(tmp_path/'page-2.png')
    data={'pages':[{'page':1,'text':'','notice':'OCR不可用'}, {'page':2,'text':'','notice':'OCR不可用'}]}
    documents.mark_blank_pages(data,tmp_path)
    assert data['pages'][0]['blank'] and not data['pages'][1]['blank']
    assert documents.unreadable_pages(data)==[2]


def test_blank_legacy_cache_upgrades_without_rerendering(tmp_path,monkeypatch):
    Image.new('RGB',(100,100),'white').save(tmp_path/'page-1.png')
    (tmp_path/'document.json').write_text(json.dumps({'version':3,'pageCount':1,'pages':[{'page':1,'text':''}]}))
    data=documents.extract_document(tmp_path/'not-needed.pdf',tmp_path)
    assert data['version']==documents.DOCUMENT_VERSION and data['pages'][0]['blank']


def test_historical_or_negated_channel_is_not_an_approved_new_value(tmp_path,monkeypatch):
    store,state=setup(tmp_path,monkeypatch,{'审批':'候选甲原招聘渠道为内推。不要将招聘渠道修改为校招。'})
    item=intake.proposals(store,state)['items'][0]
    assert item['status']=='blocked' and '否定' in str(item['issues'])


def test_changed_fact_reopens_action_without_preselecting_old_approval(tmp_path,monkeypatch):
    store,state=setup(tmp_path,monkeypatch,{'审批':'候选甲申请剔除10天。'})
    item=intake.proposals(store,state)['items'][0]
    preview=intake.preview(store,202607,{'revision':state['revision'],'itemIds':[item['id']]})
    saved=reviews.apply_preview(store,202607,state['revision'],preview['id'])
    changed=store.change(202607,saved['revision'],{'edits':[{'rowId':saved['rows'][0]['id'],'field':'周期剔除天数','value':12}]})
    projected,data=intake.project(store,changed)
    assert data['items'][0]['requiresRecheck']
    assert any(t['kind']=='attachment_review' for t in projected['todos'])


def test_explicit_exclusion_and_referral_have_separate_original_provenance(tmp_path,monkeypatch):
    store,state=setup(tmp_path,monkeypatch,{'审批':'offer流程202608170020招聘渠道需修改为内部推荐，推荐人为：领取甲zt67890。\n节点名称\n同意，不发招聘奖金，发内推奖金。'})
    item=intake.proposals(store,state)['items'][0]
    assert item['decisions']==[{'kind':'recruitment','action':'exclude'}]
    preview=intake.preview(store,202607,{'revision':state['revision'],'itemIds':[item['id']]})
    saved=reviews.apply_preview(store,202607,state['revision'],preview['id'])
    assert saved['awardDecisions'][0]['sourceId']==item['sourceId']
    assert saved['rows'][0]['values']['推荐人工号']=='zt67890'
    assert intake.proposals(store,saved)['items'][0]['status']=='consistent'

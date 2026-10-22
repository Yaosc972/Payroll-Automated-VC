from copy import deepcopy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bonus_platform.engine import recruitment_assignments as assignments
from bonus_platform.engine.recruitment_drafts import DraftStore, DraftConflict
from bonus_platform.engine.recruitment_reviews import apply_preview
from bonus_platform.engine.recruitment_attention import project as attention
from bonus_platform.engine.recruitment_work_items import project as work_items
from test_recruitment_awards import person
from test_recruitment_drafts import book


def setup(tmp_path):
    store = DraftStore(tmp_path)
    values = [person(姓名=name, 工号='zt'+str(i), 标签分类='国内', 工作地='中国大陆', 二级组织='中国大陆',
                     招聘渠道='校招', 管培生已批名单资格='是', 周期豁免依据='已确认名单',
                     招聘负责人姓名='原负责人', 招聘负责人工号='zt-old', 推荐人姓名='', 推荐人工号='')['values']
              for i, name in enumerate(['甲', '乙'])]
    for i, value in enumerate(values): value['体系外人员编号'] = f'test-{i}'
    state = store.ingest(202607, [('原始录用.xlsx', book(list(values[0]), [list(v.values()) for v in values]))], 0)
    state['strictInputs'] = True
    store._write(store._folder(202607)/'draft.json', state)
    return store, state


def request(state):
    return {'revision':state['revision'], 'sourceId':state['sources'][0]['id'], 'reason':'依据原件核对招聘分工',
            'assignments':[{'rowId':r['id'], 'recruiter':{'name':'新负责人','employeeId':'zt-new'},
                            'assistant':{'name':'协助人','employeeId':'zt-assist'}} for r in state['rows']]}


def test_batch_preview_apply_undo_without_answer_table(tmp_path):
    store, state = setup(tmp_path)
    p = assignments.preview(store, 202607, request(state))
    assert p['people'] == 2 and p['nodeImpact']
    assert store.read(202607) == state
    saved = apply_preview(store, 202607, state['revision'], p['id'])
    for row in saved['rows']:
        assert row['values']['招聘负责人姓名'] == '新负责人'
        assert row['values']['招聘负责人工号'] == 'zt-new'
        assert row['values']['协助招聘人姓名'] == '协助人'
        assert {n['role'] for n in row['calculation']['recruitment']['nodes']} == {'招聘负责人','协助招聘人'}
    undone = store.history_action(202607, saved['revision'], 'undo')
    assert all(r['values']['招聘负责人姓名']=='原负责人' for r in undone['rows'])


def test_partial_edit_preserves_untouched_role_and_explicit_clear_clears_pair(tmp_path):
    store, state = setup(tmp_path)
    payload = request(state)
    for item in payload['assignments']: item.pop('recruiter')
    p = assignments.preview(store, 202607, payload)
    assert not any(e['field'].startswith('招聘负责人') for e in p['edits'])
    saved = apply_preview(store, 202607, state['revision'], p['id'])
    payload.update(revision=saved['revision'], assignments=[{'rowId':saved['rows'][0]['id'], 'assistant':None}])
    cleared = assignments.preview(store, 202607, payload)
    assert {e['field'] for e in cleared['edits']} == {'协助招聘人姓名','协助招聘人工号'}
    assert all(e['value']=='' for e in cleared['edits'])


@pytest.mark.parametrize('change,error', [
    ('duplicate','重复'), ('same_roles','不能为同一人'), ('no_name','姓名'),
    ('no_source','依据'), ('foreign','不在本活动'), ('unknown_field','分工'),
])
def test_invalid_assignment_never_writes_draft(tmp_path,change,error):
    store, state = setup(tmp_path);payload=request(state)
    if change=='duplicate': payload['assignments'].append(deepcopy(payload['assignments'][0]))
    if change=='same_roles': payload['assignments'][0]['assistant']=payload['assignments'][0]['recruiter']
    if change=='no_name': payload['assignments'][0]['recruiter']['name']=''
    if change=='no_source': payload['sourceId']=''
    if change=='foreign': payload['assignments'][0]['rowId']='another-activity'
    if change=='unknown_field': payload['assignments'][0]['amount']=99
    with pytest.raises(ValueError,match=error): assignments.preview(store,202607,payload)
    assert store.read(202607)==state


def test_answer_table_inactive_source_and_stale_version_cannot_authorize(tmp_path):
    store,state=setup(tmp_path)
    with pytest.raises(DraftConflict): assignments.preview(store,202607,{**request(state),'revision':0})
    for flag,value in [('comparisonOnly',True),('active',False)]:
        source=deepcopy(state);source['sources'][0][flag]=value;store._write(store._folder(202607)/'draft.json',source)
        with pytest.raises(ValueError,match='依据'): assignments.preview(store,202607,request(state))


def test_proposals_use_only_matching_original_source_and_keep_ambiguity(tmp_path):
    store,state=setup(tmp_path);rid=state['rows'][0]['id'];sid=state['sources'][0]['id']
    context=assignments.context(store,202607,state['revision'],[rid],sid)
    assert context['people'][0]['proposal']['recruiter']['name']=='原负责人'
    state['rows'][0]['provenance']['招聘负责人姓名'].append({'sourceId':sid,'value':'另一个名字'})
    store._write(store._folder(202607)/'draft.json',state)
    context=assignments.context(store,202607,state['revision'],[rid],sid)
    assert 'recruiter' not in context['people'][0]['proposal']
    assert context['people'][0]['warnings']


def test_missing_approval_attachment_is_visible_and_blocks_assignment(tmp_path,monkeypatch):
    store,state=setup(tmp_path)
    state['sources'][0].update(attachment=True,mentionedAttachments=['分工更正.xlsx'])
    store._write(store._folder(202607)/'draft.json',state)
    context=assignments.context(store,202607,state['revision'],[state['rows'][0]['id']],state['sources'][0]['id'])
    assert context['missingAttachments']==['分工更正.xlsx']
    with pytest.raises(ValueError,match='分工更正.xlsx'):assignments.preview(store,202607,request(state))


def test_recruiter_and_assistant_conflicts_are_one_user_action(tmp_path):
    store,state=setup(tmp_path)
    row=state['rows'][0]
    for field in ['招聘负责人工号','协助招聘人工号']:
        row['unresolvedFields'].append(field)
        row['conflicts'].append({'field':field,'sourceId':state['sources'][0]['id']})
        state['todos'].append({'id':field,'kind':'source_conflict','title':'核对不同来源的'+field,
                              'rowIds':[row['id']],'sourceIds':[state['sources'][0]['id']]})
    items=[i for i in work_items(state,attention(state)) if i['mode']=='assignments']
    assert len(items)==1 and items[0]['rowIds']==[row['id']]


def test_api_preview_has_revision_guard_and_uses_normal_apply(tmp_path,monkeypatch):
    from bonus_platform import recruitment_draft_api as api
    store,state=setup(tmp_path);monkeypatch.setattr(api,'store',store)
    app=FastAPI();app.include_router(api.router);client=TestClient(app)
    url='/api/recruitment/drafts/202607/assignments'
    assert client.post(url+'/context',json={'revision':state['revision'],'rowIds':[state['rows'][0]['id']]}).status_code==200
    response=client.post(url+'/preview',json=request(state))
    assert response.status_code==200 and response.json()['people']==2
    assert client.post(url+'/preview',json={**request(state),'revision':0}).status_code==409


def test_id_change_keeps_explicit_same_name_and_clears_old_employment(tmp_path):
    store,state=setup(tmp_path)
    payload=request(state);payload['assignments']=[{'rowId':state['rows'][0]['id'],'recruiter':{'name':'原负责人','employeeId':'zt-new'}}]
    p=assignments.preview(store,202607,payload)
    saved=apply_preview(store,202607,state['revision'],p['id'])
    assert saved['rows'][0]['values']['招聘负责人姓名']=='原负责人'
    assert saved['rows'][0]['values']['招聘负责人工号']=='zt-new'


def test_choose_current_value_resolves_real_source_conflict(tmp_path):
    store,state=setup(tmp_path)
    value={k:deepcopy(v) for k,v in state['rows'][0]['values'].items() if not k.startswith('_')};value['招聘负责人姓名']='另一负责人';value['招聘负责人工号']='zt-other'
    state=store.ingest(202607,[('分工更正.xlsx',book(list(value),[list(value.values())]))],state['revision'])
    row=state['rows'][0]
    assert '招聘负责人工号' in row['unresolvedFields']
    payload=request(state);payload['assignments']=[{'rowId':row['id'],'recruiter':{'name':row['values']['招聘负责人姓名'],'employeeId':row['values']['招聘负责人工号']}}]
    p=assignments.preview(store,202607,payload)
    saved=apply_preview(store,202607,state['revision'],p['id'])
    assert '招聘负责人工号' not in saved['rows'][0]['unresolvedFields']


def test_import_approval_detects_attachment_without_answer_table(tmp_path,monkeypatch):
    from bonus_platform.engine import recruitment_documents as documents
    monkeypatch.setattr(documents,'extract_document',lambda *_:{'pages':[{'text':'附件 全部Offer_20260803.xISx\n全部Offer_20260803.xlsx'}]})
    store,state=setup(tmp_path)
    state=store.ingest(202607,[('OA2.pdf',b'%PDF-test')],state['revision'])
    source=state['sources'][-1]
    assert source['mentionedAttachments']==['全部Offer_20260803.xlsx']
    task=next(t for t in state['todos'] if t['sourceIds']==[source['id']])
    assert '全部Offer_20260803.xlsx' in task['detail']
    item=next(i for i in work_items(state,attention(state)) if i['key']=='attachment_review')
    assert '全部Offer_20260803.xlsx' in item['detail']
    state=store.ingest(202607,[('全部Offer_20260803.xlsx',book(['姓名','工号'],[['目录人员','zt-dir']]))],state['revision'])
    assert not assignments.missing_attachments(state,source)
    assert not state.get('reviewEntries')  # supplying a file is not approval


def test_failed_document_inspection_keeps_original_and_does_not_claim_complete(tmp_path,monkeypatch):
    from bonus_platform.engine import recruitment_documents as documents
    def fail(*_):raise ValueError('unreadable')
    monkeypatch.setattr(documents,'extract_document',fail)
    store,state=setup(tmp_path)
    state=store.ingest(202607,[('扫描件.pdf',b'%PDF-test')],state['revision'])
    source=state['sources'][-1]
    assert not source.get('error') and source.get('documentInspectionError')
    assert 'mentionedAttachments' not in source


def test_preview_does_not_describe_unknown_amount_as_unchanged(tmp_path):
    store,state=setup(tmp_path)
    value={k:deepcopy(v) for k,v in state['rows'][0]['values'].items() if not k.startswith('_')};value['奖金地区类型']='海外发展中国家'
    state=store.ingest(202607,[('待核对录用.xlsx',book(list(value),[list(value.values())]))],state['revision'])
    p=assignments.preview(store,202607,request(state))
    assert p['unresolvedAmounts']
    assert any('奖金地区类型' in '；'.join(r['reasons']) for r in p['remainingIssues'])

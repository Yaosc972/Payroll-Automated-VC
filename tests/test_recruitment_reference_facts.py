from copy import deepcopy
import json
from io import BytesIO
import os
import re
import zipfile

import pytest

from bonus_platform.engine import recruitment_reference_facts as facts
from bonus_platform.engine import recruitment_reviews as reviews
from bonus_platform.engine import recruitment_approval_intake as approvals
from bonus_platform.engine.recruitment_drafts import DraftStore
from test_recruitment_drafts import book
from test_recruitment_awards import person
from test_recruitment_approval_intake import setup as approval_setup


def fixture(tmp_path, reference=None, origin=None):
    store = DraftStore(tmp_path)
    original = person(姓名='候选甲',工号='zt12345',体系外人员编号='candidate',ABC类别='',招聘渠道='',招聘启动日期='',招聘负责人姓名='',招聘负责人工号='')['values']
    original.update(origin or {})
    state = store.ingest(202607, [('人员资料.xlsx', book(list(original), [list(original.values())]))], 0)
    reference = {**original, 'ABC类别':'B', '招聘渠道':'招聘网站', '招聘启动日期':'2026-05-20',
                 '招聘负责人姓名':'负责人甲', '招聘负责人工号':'zt56789', '周期剔除天数':99,
                 '管培生已批名单资格':'是', '核算月份':202608, **(reference or {})}
    content = book(list(reference), [list(reference.values())], '附件一-招聘奖金核算明细')
    state = store.ingest(202607, [('招聘奖金核算明细202607.xlsx', content)], state['revision'], comparison_only=True)
    return store, state, state['rows'][0]['id']


def selections(store, state):
    return [{'proposalId':p['id'], 'signature':p['signature']} for p in facts.proposals(store._folder(state['month']), state)]


def adopt(store, state):
    preview = reviews.prepare_preview(store,state['month'],state['revision'],[],reference_selections=selections(store,state))
    return reviews.apply_preview(store,state['month'],state['revision'],preview['id'])


def stored_workbook(content, replace=None):
    data=BytesIO()
    with zipfile.ZipFile(BytesIO(content)) as original,zipfile.ZipFile(data,'w') as updated:
        for name in original.namelist():
            value=original.read(name)
            if replace and name=='xl/worksheets/sheet1.xml':
                value=value.replace(*replace)
            updated.writestr(name,value,compress_type=zipfile.ZIP_STORED)
    return data.getvalue()


def test_unchanged_reference_parses_once_and_parser_version_invalidates(tmp_path,monkeypatch):
    store,state,_=fixture(tmp_path)
    facts._cached_source_records.cache_clear()
    read_source=facts.read_source;calls=[]
    def counted(path,source_id,**kwargs):
        calls.append(source_id)
        return read_source(path,source_id,**kwargs)
    monkeypatch.setattr(facts,'read_source',counted)
    first=facts.proposals(store._folder(202607),state)
    assert facts.proposals(store._folder(202607),state)==first
    assert len(calls)==1
    monkeypatch.setattr(facts,'PARSER_VERSION',facts.PARSER_VERSION+1)
    refreshed=facts.proposals(store._folder(202607),state)
    assert len(calls)==2
    assert refreshed[0]['signature']!=first[0]['signature']


def test_reference_content_change_invalidates_with_same_length_and_mtime(tmp_path):
    store,state,_=fixture(tmp_path)
    source=state['sources'][-1];path=store._folder(202607)/'sources'/source['storedName']
    original=stored_workbook(path.read_bytes())
    changed=stored_workbook(original,(b'<t>B</t>',b'<t>C</t>'))
    assert len(original)==len(changed) and original!=changed
    path.write_bytes(original);before=path.stat()
    first=facts.proposals(store._folder(202607),state)
    assert next(p['values']['ABC类别'] for p in first if 'ABC类别' in p['values'])=='B'
    path.write_bytes(changed);os.utime(path,ns=(before.st_atime_ns,before.st_mtime_ns))
    assert path.stat().st_mtime_ns==before.st_mtime_ns
    updated=facts.proposals(store._folder(202607),state)
    assert next(p['values']['ABC类别'] for p in updated if 'ABC类别' in p['values'])=='C'
    assert updated[0]['proof']['contentDigest']!=first[0]['proof']['contentDigest']
    path.unlink()
    assert facts.proposals(store._folder(202607),state)==[]


def test_reference_values_and_literal_proof_use_one_content_snapshot(tmp_path,monkeypatch):
    store,state,_=fixture(tmp_path)
    source=state['sources'][-1];folder=store._folder(202607);path=folder/'sources'/source['storedName']
    original=stored_workbook(path.read_bytes())
    changed=stored_workbook(original,(b'<t>B</t>',b'<t>C</t>'))
    path.write_bytes(original);facts._cached_source_records.cache_clear()
    read_source=facts.read_source
    def replace_during_read(filename,source_id,**kwargs):
        path.write_bytes(changed)
        return read_source(filename,source_id,**kwargs)
    monkeypatch.setattr(facts,'read_source',replace_during_read)
    first=facts.proposals(folder,state)
    assert next(p['values']['ABC类别'] for p in first if 'ABC类别' in p['values'])=='B'
    monkeypatch.setattr(facts,'read_source',read_source)
    updated=facts.proposals(folder,state)
    assert next(p['values']['ABC类别'] for p in updated if 'ABC类别' in p['values'])=='C'
    assert first[0]['proof']['contentDigest']!=updated[0]['proof']['contentDigest']


def test_replacing_cached_literal_with_formula_does_not_propose_cached_value(tmp_path):
    store,state,_=fixture(tmp_path)
    source=state['sources'][-1];folder=store._folder(202607);path=folder/'sources'/source['storedName']
    assert any('ABC类别' in p['values'] for p in facts.proposals(folder,state))
    data=BytesIO()
    with zipfile.ZipFile(path) as original,zipfile.ZipFile(data,'w') as updated:
        for name in original.namelist():
            content=original.read(name)
            if name=='xl/worksheets/sheet1.xml':
                content,count=re.subn(rb'<c r="([^"]+)"[^>]*><is><t>B</t></is></c>',
                    lambda match:b'<c r="'+match[1]+b'"><f>"B"</f><v>B</v></c>',content)
                assert count==1
            updated.writestr(name,content)
    path.write_bytes(data.getvalue())
    proposals=facts.proposals(folder,state)
    assert len(proposals)==3 and not any('ABC类别' in p['values'] for p in proposals)


def test_only_literal_facts_and_paired_recruiter_are_offered(tmp_path):
    store,state,rid=fixture(tmp_path)
    proposals=facts.proposals(store._folder(202607),state)
    assert len(proposals)==4
    assert {f for p in proposals for f in p['values']}==facts.FIELDS
    assert all(p['rowId']==rid and all(r['literal'] and r['cell'] for r in p['refs']) for p in proposals)
    detail={'rowIds':[rid],'fields':[{'field':'招聘负责人工号','targets':[rid],'options':[]}],'currentFields':[]}
    facts.enrich_detail(store._folder(202607),state,detail)
    assert len(detail['fields'][0]['options'])==1
    assert detail['fields'][0]['options'][0]['value']=='zt56789'
    assert '负责人甲' in detail['fields'][0]['options'][0]['label']


def test_formula_cache_blank_and_incomplete_pair_never_propose(tmp_path):
    store,state,_=fixture(tmp_path,{'ABC类别':'="B"','招聘启动日期':'','招聘负责人姓名':''})
    source=state['sources'][-1];path=store._folder(202607)/'sources'/source['storedName']
    data=BytesIO()
    with zipfile.ZipFile(path) as original,zipfile.ZipFile(data,'w') as updated:
        for name in original.namelist():
            content=original.read(name)
            if name=='xl/worksheets/sheet1.xml':content=content.replace(b'<f>"B"</f><v></v>',b'<f>"B"</f><v>B</v>')
            updated.writestr(name,content)
    path.write_bytes(data.getvalue())
    assert [list(p['values']) for p in facts.proposals(store._folder(202607),state)]==[['招聘渠道']]


def test_generic_edits_cannot_forge_proof_or_use_comparison_evidence(tmp_path):
    store,state,rid=fixture(tmp_path)
    sid=state['sources'][-1]['id']
    for edit in ({'rowId':rid,'field':'ABC类别','value':'B','evidenceId':sid},
                 {'rowId':rid,'field':'ABC类别','value':'B','referenceFact':{}},
                 {'rowId':rid,'field':'ABC类别','value':'B','employmentBasis':{}},
                 {'rowId':rid,'field':'ABC类别','value':'B','referenceBasis':{}}):
        with pytest.raises(ValueError):reviews.prepare_preview(store,202607,state['revision'],[edit])
        with pytest.raises(ValueError):store.change(202607,state['revision'],{'edits':[edit]})
    forged=selections(store,state)[0]|{'field':'核算月份','value':202608}
    with pytest.raises(ValueError):reviews.prepare_preview(store,202607,state['revision'],[],reference_selections=[forged])


def test_adoption_audit_undo_redo_manual_clear_and_carry(tmp_path):
    store,state,rid=fixture(tmp_path)
    saved=adopt(store,state)
    assert saved['rows'][0]['values']['ABC类别']=='B'
    assert saved['rows'][0]['values']['招聘负责人姓名']=='负责人甲'
    assert saved['rows'][0]['offerMatched'] is False
    assert len(saved['edits'])==5 and all(e['referenceFact'] and e['evidenceRefs'] for e in saved['edits'])
    assert saved['operations'][-1]['referenceFacts']
    raw=json.loads((store._folder(202607)/'draft.json').read_text())
    assert 'referenceFacts' not in raw
    undone=store.history_action(202607,saved['revision'],'undo')
    assert not undone['rows'][0]['values'].get('ABC类别')
    redone=store.history_action(202607,undone['revision'],'redo')
    assert redone['rows'][0]['values']['ABC类别']=='B'
    cleared=store.change(202607,redone['revision'],{'edits':[{'rowId':rid,'field':'招聘渠道','value':''}]})
    assert cleared['rows'][0]['values']['招聘渠道']==''
    assert len(cleared['edits'])==6
    carry=store.carry_forward(202608,202607,0)
    assert carry['rows'][0]['values']['ABC类别']=='B' and carry['rows'][0]['values']['招聘渠道']==''
    source=carry['sources'][-1]
    removed=store.change(202608,carry['revision'],{'source':{'id':source['id'],'active':False}})
    assert not removed['rows'][0]['values'].get('ABC类别')
    assert len(removed['edits'])==6 and removed['referenceFacts']['staleEdits']


def test_changed_missing_deactivated_or_replaced_source_cannot_remain_valid(tmp_path):
    store,state,rid=fixture(tmp_path)
    selection=selections(store,state)
    preview=reviews.prepare_preview(store,202607,state['revision'],[],reference_selections=selection)
    source=state['sources'][-1];path=store._folder(202607)/'sources'/source['storedName']
    original=path.read_bytes();path.write_bytes(original+b'changed')
    with pytest.raises(ValueError):reviews.prepare_preview(store,202607,state['revision'],[],reference_selections=selection)
    with pytest.raises(ValueError):reviews.apply_preview(store,202607,state['revision'],preview['id'])
    path.write_bytes(original)
    saved=adopt(store,state);revision=saved['revision'];snapshot=(store._folder(202607)/'draft.json').read_bytes()
    path.unlink()
    stale=store.read(202607)
    assert stale['revision']==revision and not stale['rows'][0]['values'].get('ABC类别')
    assert stale['referenceFacts']['staleEdits'] and (store._folder(202607)/'draft.json').read_bytes()==snapshot
    path.write_bytes(original)
    inactive=store.change(202607,revision,{'source':{'id':source['id'],'active':False}})
    assert not inactive['rows'][0]['values'].get('ABC类别')
    restored=store.change(202607,inactive['revision'],{'source':{'id':source['id'],'active':True}})
    assert restored['rows'][0]['values']['ABC类别']=='B'
    assert any(p.get('restored') for p in restored['referenceFacts']['byRowId'][rid])
    replaced=store.ingest(202607,[('招聘奖金核算明细202607替换.xlsx',original+b'new')],restored['revision'],comparison_only=True)
    assert not replaced['rows'][0]['values'].get('ABC类别')


def test_identity_change_and_many_to_one_reference_are_not_adoptable(tmp_path):
    store,state,rid=fixture(tmp_path)
    signed=selections(store,state)
    with pytest.raises(ValueError):reviews.prepare_preview(store,202607,state['revision'],[{'rowId':rid,'field':'工号','value':'zt99999'}],reference_selections=signed)
    saved=adopt(store,state)
    changed=store.change(202607,saved['revision'],{'edits':[{'rowId':rid,'field':'工号','value':'zt99999'}]})
    assert not changed['rows'][0]['values'].get('ABC类别')
    assert changed['referenceFacts']['staleEdits']
    duplicated=deepcopy(state);duplicated['rows'].append({**deepcopy(state['rows'][0]),'id':'another'})
    assert facts.proposals(store._folder(202607),duplicated)==[]


def test_unidentified_match_never_uses_adopted_start_date_as_identity(tmp_path):
    store,state,_=fixture(tmp_path,origin={'工号':'','二级组织':'','工作地':'','职位':'Engineer','招聘启动日期':'2026-05-20'})
    assert facts.proposals(store._folder(202607),state)==[]


def test_approval_channel_adoption_preserves_separate_original_proofs(tmp_path,monkeypatch):
    store,state=approval_setup(tmp_path,monkeypatch,{'更正':
        '在zt12345入职的offer流程中，因zt67890为HRAS线员工，申请从内推人改为招聘协助人。'},[
        dict(姓名='候选甲',工号='zt12345',推荐人姓名='领取甲',推荐人工号='zt67890',招聘渠道='内推')])
    values={**{k:v for k,v in state['rows'][0]['values'].items() if isinstance(v,(str,int,float))},'招聘渠道':'招聘网站'}
    state=store.ingest(202607,[('招聘奖金核算明细202607.xlsx',book(list(values),[list(values.values())],'附件一-招聘奖金核算明细'))],state['revision'],comparison_only=True)
    item=approvals.proposals(store,state)['items'][0]
    assert item['status']=='blocked' and item['referenceOptions']
    option=next(o for o in item['referenceOptions'] if o['field']=='招聘渠道')
    preview=approvals.preview(store,202607,{'revision':state['revision'],'itemIds':[item['id']],
        'referenceSelections':[{'itemId':item['id'],**option['referenceProposal']}]})
    saved=reviews.apply_preview(store,202607,state['revision'],preview['id'])
    row=saved['rows'][0]
    assert row['values']['招聘渠道']=='招聘网站' and row['values']['推荐人工号']=='' and row['values']['协助招聘人工号']=='zt67890'
    edits={e['field']:e for e in saved['edits']}
    assert edits['招聘渠道']['referenceFact'] and edits['招聘渠道']['evidenceId']!=edits['协助招聘人工号']['evidenceId']
    assert 'referenceFact' not in edits['协助招聘人工号']
    assert approvals.proposals(store,saved)['items'][0]['status']=='consistent'
    disabled=store.change(202607,saved['revision'],{'source':{'id':edits['招聘渠道']['evidenceId'],'active':False}})
    stale=approvals.proposals(store,disabled)['items'][0]
    assert stale['status']=='blocked'
    assert next(f['value'] for f in stale['fields'] if f['field']=='招聘渠道')==''
    assert stale['referenceOptions']==[]


def test_original_identity_content_change_invalidates_adopted_reference(tmp_path):
    store,state,rid=fixture(tmp_path)
    saved=adopt(store,state)
    original=saved['sources'][0]
    path=store._folder(202607)/'sources'/original['storedName']
    values={**state['rows'][0]['original'],'工号':'zt00000'}
    values={k:v for k,v in values.items() if isinstance(v,(str,int,float))}
    path.write_bytes(book(list(values),[list(values.values())]))
    changed=store.read(202607)
    assert changed['revision']==saved['revision']
    assert changed['rows'][0]['values']['工号']=='zt00000'
    assert not changed['rows'][0]['values'].get('ABC类别')
    assert changed['referenceFacts']['staleEdits']

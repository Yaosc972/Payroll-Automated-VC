from pathlib import Path
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bonus_platform.engine.recruitment_trials import ScopedDraftStore
from test_recruitment_awards import person
from test_recruitment_drafts import book


def snapshot(folder):
    return {str(p.relative_to(folder)):p.read_bytes() for p in folder.rglob('*') if p.is_file()}


def fill_month(client,base,month,name):
    hire=f'{month//100}-{month%100:02d}-01'
    start=f'{month//100}-{month%100-2:02d}-20'
    v=person(hire,姓名=name,工号='ext1',体系外人员编号='outside1',招聘启动日期=start,推荐人工号='',推荐人姓名='')['values']
    payload=client.post(base+'/sources',data={'revision':0,'periodConfirmed':'true'},files=[
        ('files',('原始资料.xlsx',book(list(v),[list(v.values())],'导入_月度数据'))),
        ('files',('花名册.xlsx',book(['姓名','工号','入职日期','人员状态','人员来源'],[[name,'ext1',hire,'正式','OEHR入职']]))),
    ])
    assert payload.status_code==200,payload.text
    opened=client.post(base+'/opening-empty',json={'revision':payload.json()['revision'],'confirmed':True})
    assert opened.status_code==200,opened.text
    assert not opened.json()['monthly']['cases']
    return opened.json()


@pytest.fixture
def calculation(tmp_path,monkeypatch):
    import bonus_platform.recruitment_draft_api as api
    store=ScopedDraftStore(tmp_path/'drafts');monkeypatch.setattr(api,'store',store)
    app=FastAPI();app.include_router(api.router);app.include_router(api.trials_router);app.include_router(api.trial_drafts_router)
    client=TestClient(app)
    target_base='/api/recruitment/drafts/202607'
    item=client.post('/api/recruitment/trials',json={'month':202607,'name':'七月重新核算'}).json()
    source_base=f"/api/recruitment/trials/{item['id']}"+target_base
    target=fill_month(client,target_base,202607,'原核算人员')
    accepted=client.post(target_base+'/confirm-month',json={'revision':target['revision'],'coverageConfirmed':True})
    assert accepted.status_code==200,accepted.text
    source=fill_month(client,source_base,202607,'重新核算人员')
    return {'store':store,'client':client,'item':item,'source':source,'target':target,
            'sourceBase':source_base,'targetBase':target_base,
            'sourceFolder':store.trial_root/item['id']/'drafts'/'202607','targetFolder':store._folder(202607)}


def adopt(case,**changes):
    payload={'sourceRevision':case['source']['revision'],'targetRevision':case['target']['revision'],'coverageConfirmed':True,**changes}
    return case['client'].post(case['sourceBase']+'/adopt-month',json=payload)


def test_preview_reads_both_versions_without_writing(calculation):
    c=calculation;before=snapshot(c['store'].default_root.parent)
    response=c['client'].get(c['sourceBase']+f"/adoption-preview?sourceRevision={c['source']['revision']}")
    assert response.status_code==200,response.text
    data=response.json()
    assert data['canAdopt'] and data['blockers']==[]
    assert data['sourceRevision']==c['source']['revision'] and data['targetRevision']==c['target']['revision']
    assert data['source']['name']=='七月重新核算' and data['source']['people']==1
    assert data['target']['confirmedRevision']==c['target']['revision'] and data['target']['confirmedAt']
    assert '?month=2026-07' in data['returnUrl'] and 'trial=' not in data['returnUrl']
    assert snapshot(c['store'].default_root.parent)==before


def test_adoption_archives_original_and_next_month_uses_new_confirmed_state(calculation):
    c=calculation;target_before=snapshot(c['targetFolder']);source_before=snapshot(c['sourceFolder'])
    response=adopt(c);assert response.status_code==200,response.text
    data=response.json();revision=c['target']['revision']+1
    assert data['revision']==revision and data['name']=='七月重新核算' and 'trial=' not in data['url']
    archived=c['store'].trial_root/data['archive']['id']/'drafts'/'202607'
    assert snapshot(archived)==target_before
    assert snapshot(c['sourceFolder'])==source_before
    listed=c['client'].get('/api/recruitment/trials').json()
    assert {t['id'] for t in listed}=={c['item']['id'],data['archive']['id']}
    archive_base=f"/api/recruitment/trials/{data['archive']['id']}"+c['targetBase']
    original=c['client'].get(archive_base).json()
    assert original['rows'][0]['values']['姓名']=='原核算人员'
    assert original['trial']['id']==data['archive']['id']
    current=c['client'].get(c['targetBase']).json()
    assert current['revision']==current['confirmation']['revision']==revision
    assert current['rows'][0]['values']['姓名']=='重新核算人员'
    assert not current['isTrial'] and not current['paymentReady']
    accepted=json.loads((c['targetFolder']/'accepted.json').read_text())
    assert accepted['revision']==revision and accepted['state']['adoptedFrom']['id']==c['item']['id']
    assert (c['targetFolder']/'accepted'/f"{c['target']['revision']}.json").read_bytes()==target_before[f"accepted/{c['target']['revision']}.json"]
    for relative,content in target_before.items():
        if relative.startswith('sources/'):
            assert (c['targetFolder']/relative).read_bytes()==content
    child=c['store'].carry_forward(202608,202607,0)
    assert child['parentMonth']==202607 and child['parentRevision']==revision
    assert 'trial' not in child and 'adoptedFrom' not in child
    assert child['rows'][0]['values']['姓名']=='重新核算人员'
    assert child['sources']==accepted['state']['sources']
    for source in child['sources']:
        assert (c['store']._folder(202608)/'sources'/source['storedName']).is_file()


@pytest.mark.parametrize('field',['sourceRevision','targetRevision'])
def test_adoption_rejects_either_stale_version(calculation,field):
    c=calculation;before=snapshot(c['store'].default_root.parent)
    response=adopt(c,**{field:0})
    assert response.status_code==409,response.text
    assert snapshot(c['store'].default_root.parent)==before


@pytest.mark.parametrize('confirmed',[False,None,'true',1])
def test_adoption_requires_explicit_coverage_confirmation(calculation,confirmed):
    c=calculation;before=snapshot(c['targetFolder'])
    response=adopt(c,coverageConfirmed=confirmed)
    assert response.status_code==400,response.text
    assert snapshot(c['targetFolder'])==before


def test_adoption_rejects_unresolved_source_data(calculation):
    c=calculation;path=c['sourceFolder']/'draft.json'
    state=json.loads(path.read_text());state['sources'][0]['error']='原始资料未能读取'
    c['store']._write(path,state);before=snapshot(c['targetFolder'])
    preview=c['client'].get(c['sourceBase']+f"/adoption-preview?sourceRevision={state['revision']}").json()
    assert not preview['canAdopt'] and preview['blockers']
    response=adopt(c)
    assert response.status_code==400,response.text
    assert snapshot(c['targetFolder'])==before


@pytest.mark.parametrize('folder',['sourceFolder','targetFolder'])
def test_adoption_rejects_running_preparation(calculation,monkeypatch,folder):
    from bonus_platform.engine import recruitment_prepare as jobs
    c=calculation;key=str(c[folder]/'prepare.json');monkeypatch.setitem(jobs.RUNNING,key,'running-test')
    c['store']._write(Path(key),{'status':'running','id':'running-test'})
    before=snapshot(c['targetFolder']);response=adopt(c)
    assert response.status_code==409 and '正在整理' in response.json()['detail']
    assert snapshot(c['targetFolder'])==before


def test_adoption_rejects_persisted_unfinished_preparation(calculation):
    c=calculation;c['store']._write(c['sourceFolder']/'prepare.json',{'status':'running','id':'another-worker'})
    before=snapshot(c['targetFolder']);response=adopt(c)
    assert response.status_code==409
    assert snapshot(c['targetFolder'])==before


@pytest.mark.parametrize('registered',[True,False])
def test_month_confirmation_rejects_running_preparation(calculation,monkeypatch,registered):
    from bonus_platform.engine import recruitment_prepare as jobs
    c=calculation;key=str(c['targetFolder']/'prepare.json')
    c['store']._write(Path(key),{'id':'preparing','status':'running'})
    if registered:monkeypatch.setitem(jobs.RUNNING,key,'preparing')
    before=snapshot(c['targetFolder'])
    result=c['client'].post(c['targetBase']+'/confirm-month',json={'revision':c['target']['revision'],'coverageConfirmed':True})
    assert result.status_code==409 and '资料正在整理' in result.json()['detail']
    assert snapshot(c['targetFolder'])==before


def test_adoption_replaces_stale_preparation_status_with_the_adopted_revision(calculation):
    c=calculation
    c['store']._write(c['targetFolder']/'prepare.json',{'id':'old-job','status':'failed','revision':0,'message':'旧资料准备失败'})
    result=adopt(c);assert result.status_code==200,result.text
    status=c['client'].get(c['targetBase']+'/prepare').json()
    assert status['status']=='complete' and status['revision']==result.json()['revision']
    archived=c['store'].trial_root/result.json()['archive']['id']/'drafts'/'202607'/'prepare.json'
    assert json.loads(archived.read_text())['status']=='failed'


def test_material_copy_failure_preserves_original_without_publishing_archive(calculation,monkeypatch):
    from bonus_platform.engine import recruitment_trials as module
    c=calculation;before=snapshot(c['targetFolder']);copy=module.shutil.copytree
    def fail(source,destination,*args,**kwargs):
        if Path(source)==c['sourceFolder']/'sources':raise OSError('copy failed')
        return copy(source,destination,*args,**kwargs)
    monkeypatch.setattr(module.shutil,'copytree',fail)
    response=adopt(c)
    assert response.status_code==400 and '原月度结果' in response.json()['detail']
    assert snapshot(c['targetFolder'])==before
    assert [t['id'] for t in c['client'].get('/api/recruitment/trials').json()]==[c['item']['id']]
    assert not list(c['store'].default_root.parent.glob('.recruitment-adopt-*'))


def test_commit_failure_rolls_back_draft_and_confirmation(calculation,monkeypatch):
    from bonus_platform.engine import recruitment_trials as module
    c=calculation;before=snapshot(c['targetFolder']);replace=module.os.replace;failed=False
    def fail(source,destination):
        nonlocal failed
        if not failed and Path(destination)==c['targetFolder']/'accepted-status.json':
            failed=True;raise OSError('commit failed')
        return replace(source,destination)
    monkeypatch.setattr(module.os,'replace',fail)
    response=adopt(c)
    assert response.status_code==400,response.text
    assert failed and snapshot(c['targetFolder'])==before
    archives=[t for t in c['client'].get('/api/recruitment/trials').json() if t.get('kind')=='monthly-archive']
    assert len(archives)==1
    assert snapshot(c['store'].trial_root/archives[0]['id']/'drafts'/'202607')==before


def test_repeated_adoption_cannot_replace_the_month_again(calculation):
    c=calculation;first=adopt(c);assert first.status_code==200,first.text
    before=snapshot(c['store'].default_root.parent)
    second=adopt(c)
    assert second.status_code==409
    assert snapshot(c['store'].default_root.parent)==before


@pytest.fixture
def updated_previous(calculation):
    c=calculation;client=c['client'];store=c['store'];base='/api/recruitment/drafts/202610'
    state=fill_month(client,base,202610,'十月人员')
    def change(month,state,note):
        return store.change(month,state['revision'],{'edits':[{'rowId':state['rows'][0]['id'],'field':'人工备注','value':note,'reason':'核对原始资料'}]})
    state=change(202610,state,'十月原确认依据')
    assert state['revision']==3
    assert client.post(base+'/confirm-month',json={'revision':3,'coverageConfirmed':True}).status_code==200
    november=store.carry_forward(202611,202610,0)
    assert november['revision']==1 and november['parentRevision']==3
    state=change(202610,state,'十月新确认依据')
    assert state['revision']==4
    assert client.post(base+'/confirm-month',json={'revision':4,'coverageConfirmed':True}).status_code==200
    change(202610,state,'十月尚未确认的后续更正')
    return {**c,'november':november,'change':change}


def test_existing_month_reports_updated_parent_and_new_record_uses_frozen_accepted(updated_previous):
    c=updated_previous;store=c['store'];client=c['client'];before=snapshot(store._folder(202611))
    current=client.get('/api/recruitment/drafts/202611').json()
    assert current['revision']==1 and current['parentRevision']==3 and current['parentOutdated']
    assert current['previousConfirmed']['month']==202610 and current['previousConfirmed']['revision']==4
    response=client.post('/api/recruitment/trials',json={'month':202611,'name':'按最新上月重算','opening':{'month':202610,'revision':4}})
    assert response.status_code==200,response.text
    item=response.json();assert item['parentMonth']==202610 and item['parentRevision']==4
    fresh=client.get(f"/api/recruitment/trials/{item['id']}/api/recruitment/drafts/202611").json()
    assert fresh['revision']==1 and fresh['parentRevision']==4 and not fresh['parentOutdated']
    assert fresh['previousConfirmed']['revision']==4  # official root, not a private sibling month
    assert fresh['rows'][0]['values']['人工备注']=='十月新确认依据'
    assert fresh['trial']['id']==item['id'] and fresh['trial']['name']=='按最新上月重算'
    assert snapshot(store._folder(202611))==before
    assert not (store.trial_root/item['id']/'drafts'/'202611'/'accepted.json').exists()


def test_restarted_month_does_not_copy_old_current_month_edits(updated_previous):
    c=updated_previous;store=c['store'];client=c['client']
    old=c['change'](202611,c['november'],'旧十一月人工更正')
    before=snapshot(store._folder(202611))
    result=client.post('/api/recruitment/trials',json={'month':202611,'opening':{'month':202610,'revision':4}})
    assert result.status_code==200,result.text
    fresh=client.get(f"/api/recruitment/trials/{result.json()['id']}/api/recruitment/drafts/202611").json()
    assert fresh['rows'][0]['values']['人工备注']=='十月新确认依据'
    assert old['rows'][0]['values']['人工备注']=='旧十一月人工更正'
    assert snapshot(store._folder(202611))==before


def test_start_from_previous_rejects_changed_confirmation_version(updated_previous):
    c=updated_previous;before=snapshot(c['store'].default_root.parent)
    response=c['client'].post('/api/recruitment/trials',json={'month':202611,'opening':{'month':202610,'revision':3}})
    assert response.status_code==409,response.text
    assert snapshot(c['store'].default_root.parent)==before


def test_start_from_previous_rejects_missing_original_without_partial_record(updated_previous):
    c=updated_previous;store=c['store'];source=store.read(202610)['sources'][0]
    raw=store._folder(202610)/'sources'/source['storedName'];raw.rename(raw.with_suffix('.unavailable'))
    before=snapshot(store.default_root.parent)
    response=c['client'].post('/api/recruitment/trials',json={'month':202611,'opening':{'month':202610,'revision':4}})
    assert response.status_code==409,response.text
    assert snapshot(store.default_root.parent)==before
    assert not list(store.default_root.parent.glob('.recruitment-create-*'))


def test_start_from_previous_requires_an_accepted_immediately_preceding_month(calculation):
    c=calculation;client=c['client'];before=c['store'].list_trials()
    wrong=client.post('/api/recruitment/trials',json={'month':202609,'opening':{'month':202607,'revision':2}})
    assert wrong.status_code==400
    missing=client.post('/api/recruitment/trials',json={'month':202611,'opening':{'month':202610,'revision':4}})
    assert missing.status_code==400 and '尚未确认' in missing.json()['detail']
    assert c['store'].list_trials()==before


def test_adoption_warns_about_existing_next_month_without_modifying_it(calculation):
    c=calculation;store=c['store'];client=c['client']
    following=store.carry_forward(202608,202607,0);before=snapshot(store._folder(202608))
    preview=client.get(c['sourceBase']+f"/adoption-preview?sourceRevision={c['source']['revision']}").json()
    assert preview['nextMonth']=={'month':202608,'exists':True,'parentMonth':202607,
                                  'parentRevision':following['parentRevision'],'willNeedRecalculation':True,'confirmedRevision':None}
    applied=adopt(c);assert applied.status_code==200,applied.text
    result=applied.json()
    assert result['nextMonth']['willNeedRecalculation'] and '8月仍引用原结果' in result['message']
    assert snapshot(store._folder(202608))==before
    next_state=client.get('/api/recruitment/drafts/202608').json()
    assert next_state['parentOutdated'] and next_state['previousConfirmed']['revision']==result['revision']


def test_outdated_parent_prevents_month_confirmation_but_allows_workbook_export(updated_previous):
    c=updated_previous;client=c['client'];current=add_november_roster(client,'/api/recruitment/drafts/202611',1)
    assert current['parentOutdated'] and not current['monthly']['cases']
    before=snapshot(c['store']._folder(202611))
    refused=client.post('/api/recruitment/drafts/202611/confirm-month',json={'revision':current['revision'],'coverageConfirmed':True})
    assert refused.status_code==400 and '上月已确认结果已更新' in refused.json()['detail']
    assert snapshot(c['store']._folder(202611))==before
    exported=client.get(f"/api/recruitment/drafts/202611/monthly/export?revision={current['revision']}")
    assert exported.status_code==200,exported.text


def test_new_parent_confirmation_invalidates_recalculation_before_adoption(updated_previous):
    c=updated_previous;client=c['client'];store=c['store']
    made=client.post('/api/recruitment/trials',json={'month':202611,'opening':{'month':202610,'revision':4}})
    assert made.status_code==200,made.text
    base=f"/api/recruitment/trials/{made.json()['id']}/api/recruitment/drafts/202611"
    fresh=add_november_roster(client,base,1);target=store.read(202611)
    before=client.get(base+f"/adoption-preview?sourceRevision={fresh['revision']}").json()
    assert before['canAdopt']
    # Neither of the reviewed current-month versions changed; their shared
    # upstream accepted version changed between preview and adoption instead.
    newer=client.post('/api/recruitment/drafts/202610/confirm-month',json={'revision':5,'coverageConfirmed':True})
    assert newer.status_code==200,newer.text
    assert client.get(base).json()['parentOutdated']
    preview=client.get(base+f"/adoption-preview?sourceRevision={fresh['revision']}").json()
    assert not preview['canAdopt'] and any('上月已确认结果已更新' in x for x in preview['blockers'])
    original=snapshot(store._folder(202611))
    refused=client.post(base+'/adopt-month',json={'sourceRevision':fresh['revision'],'targetRevision':target['revision'],'coverageConfirmed':True})
    assert refused.status_code==400 and '上月已确认结果已更新' in refused.json()['detail']
    assert snapshot(store._folder(202611))==original


def add_november_roster(client,base,revision):
    content=book(['姓名','工号','入职日期','人员状态','人员来源','资料月份'],
                 [['十月人员','ext1','2026-10-01','正式','OEHR入职','2026年11月']])
    response=client.post(base+'/sources',data={'revision':revision,'periodConfirmed':'true'},
                         files={'files':('十一月花名册.xlsx',content)})
    assert response.status_code==200,response.text
    return response.json()

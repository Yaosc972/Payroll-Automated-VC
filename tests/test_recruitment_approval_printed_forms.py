import pytest

from bonus_platform.engine import recruitment_approval_intake as intake
from bonus_platform.engine import recruitment_documents as documents
from bonus_platform.engine import recruitment_reviews as reviews
from test_recruitment_approval_intake import setup


def printed(body, opinion='同意'):
    return ('基本信息\n申请人姓名*\n申请人工号*\nzt90000\n申请说明*\n'+body+
            '\n节点名称\n直接上级审核\nHSSC负责人审核\n操作者\n审批甲\n审批乙\n'
            '操作\n通过\n处理意见\n'+opinion+'\n扫描二维码查看详情')


def test_printed_operator_columns_and_name_substrings_are_not_subjects(tmp_path, monkeypatch):
    people=[{'姓名':'候选甲','工号':'zt12345'}, {'姓名':'审批甲','工号':'zt90001'},
            {'姓名':'审批乙','工号':'zt90002'}, {'姓名':'选甲','工号':'zt90003'}]
    body=printed('剔除天数*\n28\n因业务调整需要，员工候选甲由原定的入职时间5.1推迟至6.1入职。')
    store,state=setup(tmp_path,monkeypatch,{'审批':body},people)
    items=intake.proposals(store,state)['items']
    assert len(items)==1 and items[0]['person']['name']=='候选甲'
    assert items[0]['status']=='ready'
    assert next(f['value'] for f in items[0]['fields'] if f['field']=='周期剔除天数')==28


def test_printed_offer_code_and_traditional_cancellation(tmp_path, monkeypatch):
    body=printed('關於 Offer 流程（編碼：202608170020），先前誤填內部推薦人Sally資訊。\n'
                 '請補正取消該資訊並更正招聘渠道為外部推薦。')
    store,state=setup(tmp_path,monkeypatch,{'审批':body},[{'姓名':'候选甲','工号':'zt12345',
        '海外offer流程编号':'202608170020','招聘渠道':'内推','推荐人姓名':'Sally','推荐人工号':'zt67890'}])
    item=intake.proposals(store,state)['items'][0]
    assert item['person']['name']=='候选甲' and item['status']=='ready'
    fields={f['field']:f['value'] for f in item['fields']}
    assert fields=={'招聘渠道':'外部推荐','推荐人姓名':'','推荐人工号':''}
    preview=intake.preview(store,202607,{'revision':state['revision'],'itemIds':[item['id']]})
    saved=reviews.apply_preview(store,202607,state['revision'],preview['id'])
    assert saved['rows'][0]['values']['招聘渠道']=='招聘网站'
    assert intake.proposals(store,saved)['items'][0]['status']=='consistent'


def test_applicant_can_be_explicit_hired_subject(tmp_path, monkeypatch):
    body=printed('剔除天数*\n90\n法国区高级主管候选甲已于2026年6月1日入职，故申请剔除90天招聘周期。')
    store,state=setup(tmp_path,monkeypatch,{'候选甲提交':body})
    item=intake.proposals(store,state)['items'][0]
    assert item['person']['name']=='候选甲' and item['status']=='ready'


def test_structured_recipient_pairs_do_not_leak_between_candidates(tmp_path, monkeypatch):
    body=printed('1、候选甲因为内推人为GF需要申请\n'
        '1.1入职的人员（候选甲）招聘渠道修改为内推，内推人工号（GL000419）和姓名（Eva Huang）\n'
        '1.2入职的人员（候选乙）招聘渠道修改为内推，内推人工号（zt27571）和姓名（领取乙）')
    people=[{'姓名':'候选甲','工号':'zt12345'}, {'姓名':'候选乙','工号':'zt12346'},
            {'姓名':'领取乙','工号':'zt27571'}]
    store,state=setup(tmp_path,monkeypatch,{'审批':body},people)
    items=intake.proposals(store,state)['items']
    assert len(items)==2 and all(i['status']=='ready' for i in items)
    values={i['person']['name']:{f['field']:f['value'] for f in i['fields']} for i in items}
    assert values['候选甲']['推荐人工号']=='gl000419'
    assert values['候选甲']['推荐人姓名']=='Eva Huang'
    assert values['候选乙']['推荐人工号']=='zt27571'
    preview=intake.preview(store,202607,{'revision':state['revision'],'itemIds':[i['id'] for i in items]})
    saved=reviews.apply_preview(store,202607,state['revision'],preview['id'])
    assert all(i['status']=='consistent' for i in intake.proposals(store,saved)['items'])
    undone=store.history_action(202607,saved['revision'],'undo')
    assert all(i['status']=='ready' for i in intake.proposals(store,undone)['items'])


def test_english_referrer_sentence_keeps_recipient_out_of_subjects(tmp_path, monkeypatch):
    body=printed('Candidate Yang 由英国员TQi Guo内推\n特此申请offer信息变更')
    store,state=setup(tmp_path,monkeypatch,{'审批':body},[
        {'姓名':'Candidate Yang','工号':'zt12345'}, {'姓名':'Qi Guo','工号':'zt22334'}])
    items=intake.proposals(store,state)['items']
    assert len(items)==1 and items[0]['person']['name']=='Candidate Yang'
    fields={f['field']:f['value'] for f in items[0]['fields']}
    assert fields['招聘渠道']=='内推' and fields['推荐人工号']=='zt22334'


def test_postponed_day_only_selects_unique_employment(tmp_path, monkeypatch):
    body=printed('剔除天数，\n24\n因业务调整需要，员工Chen Zhang由原定的入职时间8.17推迟至9.10入职。')
    store,state=setup(tmp_path,monkeypatch,{'审批':body},[
        {'姓名':'Chen Zhang','工号':'zt12345','入职日期':'2026-09-10'},
        {'姓名':'Chen Zhang','工号':'zt12346','入职日期':'2025-02-03'}])
    item=intake.proposals(store,state)['items'][0]
    assert item['person']['employeeId']=='zt12345' and item['status']=='ready'
    # No guessed year when the same day matches two different employments.
    state['rows'][1]['values']['入职日期']='2025-09-10'
    directory=intake.Directory(store._folder(202607),state)
    matches,reason=directory.target(intake.approval_sections(body)[0],'申请人')
    assert len(matches)==2 and reason


@pytest.mark.parametrize('opinion',['不同意剔除28天。','最终意见：另行核定，不能按申请执行。'])
def test_printed_final_rejection_or_unknown_opinion_stays_blocked(tmp_path,monkeypatch,opinion):
    store,state=setup(tmp_path,monkeypatch,{'审批':printed('剔除天数*\n28\n因业务需要，员工候选甲由原定5.1推迟至6.1入职。',opinion)})
    assert intake.proposals(store,state)['items'][0]['status']=='blocked'


def test_conflicting_days_and_missing_image_are_not_silently_adopted(tmp_path,monkeypatch):
    body=printed('剔除天数*\n28\n候选甲已于2026年6月1日入职，申请剔除24天。')+'\n证明文件\n延期证明.jpg'
    store,state=setup(tmp_path,monkeypatch,{'审批':body})
    item=intake.proposals(store,state)['items'][0]
    assert item['status']=='blocked'
    assert '多个调整值' in str(item['issues']) and '延期证明.jpg' in str(item['issues'])
    assert documents.mentioned_attachments({'pages':[{'text':'证明文件\n延期证明.jpg'}]})==['延期证明.jpg']


def test_cleaned_item_id_preserves_unique_previously_reviewed_override(tmp_path,monkeypatch):
    store,state=setup(tmp_path,monkeypatch,{'审批':printed('候选甲已于2026年6月1日入职，申请剔除28天。')})
    item=intake.proposals(store,state)['items'][0]
    preview=intake.preview(store,202607,{'revision':state['revision'],'itemIds':[item['id']],
        'overrides':{item['id']:{'fields':{'周期剔除天数':24}}}})
    saved=reviews.apply_preview(store,202607,state['revision'],preview['id'])
    saved['reviewEntries'][-1]['adoptedItems'][0]['id']='old-ocr-body-id'
    again=intake.proposals(store,saved)['items'][0]
    assert again['status']=='consistent'
    assert next(f['value'] for f in again['fields'] if f['field']=='周期剔除天数')==24


def test_printed_form_retains_existing_date_grade_and_exclusion_changes(tmp_path,monkeypatch):
    body=printed('候选人：候选甲。入职日期更正为2026-06-02，职级调整为P2-3，ABC类别改为B。\n不发内推奖金。')
    store,state=setup(tmp_path,monkeypatch,{'审批':body})
    item=intake.proposals(store,state)['items'][0]
    fields={f['field']:f['value'] for f in item['fields']}
    assert item['status']=='ready' and item['person']['name']=='候选甲'
    assert fields['入职日期']=='2026-06-02' and fields['职级']=='P2-3' and fields['ABC类别']=='B'
    assert item['decisions']==[{'kind':'referral','action':'exclude'}]

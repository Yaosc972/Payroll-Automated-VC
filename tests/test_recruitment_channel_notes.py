from copy import deepcopy

import pytest

from bonus_platform.engine.recruitment_awards import channel
from bonus_platform.engine.recruitment_drafts import DraftStore
from bonus_platform.engine.recruitment_import_validation import _normalize_offer_channel
from bonus_platform.engine.recruitment_beisen import parsed_snapshot, CHANNEL
from test_recruitment_drafts import book, ROSTER, OFFER
from test_recruitment_beisen import snapshot


@pytest.mark.parametrize('note,expected', [
    ('招聘渠道：Boss直聘', '招聘网站'),
    ('实际渠道：小红书；入职日期已核对', '招聘网站'),
    ('pracuj.pl', '招聘网站'),
    ('渠道：劳务工转正', '外包转正式'),
    ('非内推；招聘渠道：招聘会', '招聘网站'),
    ('招聘渠道：内推', '内推'),
    ('通过Boss直聘招聘', '招聘网站'),
    ('渠道说明：招聘会', '招聘网站'),
    ('Channel: Facebook', '招聘网站'),
])
def test_other_channel_ignores_notes_for_award_eligibility(note, expected):
    assert _normalize_offer_channel('其他', '', note) == ('其他', False)
    factor, issues, value = channel({'招聘渠道': '其他', '招聘渠道备注': note}, 'legacy')
    assert value == '其他' and not issues
    assert factor == 0


@pytest.mark.parametrize('note', ['推荐人尚未转正', '内推奖金待发', '不是内推', '渠道待确认：Boss或内推',
                               '招聘渠道：Boss；实际渠道：内推', '可能来自招聘网站'])
def test_unrelated_negated_or_conflicting_notes_stay_unresolved(note):
    assert _normalize_offer_channel('其他', '', note) == ('其他', False)


def test_main_channel_and_conflicting_details_are_not_silently_replaced():
    assert _normalize_offer_channel('内推', '', '招聘渠道：Boss') == ('内推', False)
    assert _normalize_offer_channel('其他', '招聘会', '招聘渠道：内推') == ('其他', False)


def test_overseas_offer_note_resolves_and_retains_source(tmp_path):
    state = DraftStore(tmp_path).ingest(202607, [
        ('roster.xlsx', book(ROSTER, [['甲', 'ov1', 'OF1', '2026-07-01', '正式', '', '', 'OEHR入职', '德国', '德国']])),
        ('offer.xlsx', book(OFFER + ['备注'], [['OF1', 'R1', 'C', 'zt1', '其他', '', '已归档', '招聘渠道：招聘会']])),
    ], 0)
    row = state['rows'][0]
    assert row['values']['招聘渠道'] == '其他'
    assert row['values']['原始招聘渠道'] == '其他'
    assert row['values']['招聘渠道备注'] == '招聘渠道：招聘会'
    assert row['provenance']['招聘渠道备注'][0]['column'] == 8
    assert not any(t['kind'] == 'channel' for t in state['todos'])


def test_supplement_note_resolves_without_changing_original_channel(tmp_path):
    store = DraftStore(tmp_path)
    state = store.ingest(202607, [('data.xlsx', book(
        ['姓名', '工号', '入职日期', '招聘渠道', '备注'],
        [['甲', 'zt1', '2026-07-01', '其他', '实际渠道：猎聘']], title='导入_月度数据'))], 0)
    row = state['rows'][0]
    assert row['values']['招聘渠道'] == '其他'
    assert row['original']['招聘渠道'] == '其他'
    assert row['channelResolution']['sources'][0]['row'] == 2


def test_beisen_remarks_are_preserved_as_recruitment_evidence():
    p = snapshot()
    p['offers'][0].update(remarks='招聘渠道：Boss直聘')
    p['offers'][0]['customProperties'][CHANNEL] = '10'
    record = next(r for r in parsed_snapshot(p, 'api')['records'] if r['role'] == 'domestic_offer')
    assert record['values']['招聘渠道备注'] == '招聘渠道：Boss直聘'
    assert record['apiEvidence']['offerId'] == 'offer1'


def test_note_only_snapshot_keeps_main_snapshot_and_user_edits(tmp_path):
    store = DraftStore(tmp_path)
    state = store.save_beisen_snapshot(202607, 0, snapshot())
    patch = deepcopy(snapshot())
    patch.update(channelDetailsOnly=True, channelDetailsCheckedOfferIds=['offer1'])
    patch['offers'][0]['remarks'] = '招聘渠道：招聘会'
    result = store.save_beisen_snapshot(202607, state['revision'], patch)
    assert all(s['active'] for s in result['sources'])
    assert result['sources'][-1]['channelDetailsOnly'] is True
    records = parsed_snapshot(patch, 'notes')['records']
    assert len(records) == 1
    assert set(records[0]['values']) == {'工号', '入职日期', '招聘渠道备注'}


def test_conflicting_source_notes_never_produce_a_channel_factor(tmp_path):
    store = DraftStore(tmp_path)
    headers = ['姓名','工号','入职日期','招聘渠道','备注']
    state = store.ingest(202607, [(name, book(headers, [['甲','zt1','2026-07-01','其他',note]], title='导入_月度数据'))
        for name,note in [('a.xlsx','招聘渠道：Boss'), ('b.xlsx','实际渠道：内推')]], 0)
    row = state['rows'][0]
    assert row['values']['招聘渠道'] == '其他'
    assert channel(row['values'], 'legacy')[0] == 0
    assert row['channelResolution']['resolved'] is True


def test_channel_note_fetch_is_scoped_and_reusable():
    from bonus_platform.engine.recruitment_beisen import fetch_channel_details
    p = snapshot();p['offers'][0].update(modifiedTime='2026-07-01T10:00:00')
    p['offers'][0]['customProperties'][CHANNEL]='10'
    class Client:
        def __init__(self):self.calls=[]
        def post(self,path,body):
            self.calls.append(body)
            return {'data':[] if body['scrollId'] else [
                {**p['offers'][0], 'remarks':'渠道：招聘会', 'salaryAmount0':12345},
                {**p['offers'][0], 'objectId':'someone-else', 'remarks':'招聘渠道：内推'}], 'scrollId':'next'}
    c=Client();extra=fetch_channel_details(p,client=c)
    assert extra['channelDetailsCheckedOfferIds']==['offer1']
    assert len(extra['offers'])==1 and extra['offers'][0]['remarks']=='渠道：招聘会'
    assert 'salaryAmount0' not in extra['offers'][0]
    assert fetch_channel_details(p,extra['channelDetailsCheckedOfferIds'],client=c) is None
    assert len(c.calls)==2


def test_channel_note_fetch_rejects_changed_employment():
    from bonus_platform.engine.recruitment_beisen import fetch_channel_details
    p=snapshot();p['offers'][0].update(modifiedTime='2026-07-01T10:00:00')
    p['offers'][0]['customProperties'][CHANNEL]='10'
    class Client:
        def post(self,path,body):
            return {'data':[] if body['scrollId'] else [
                {**p['offers'][0], 'entryDate':'2026-08-01', 'remarks':'招聘渠道：招聘会'}], 'scrollId':'next'}
    extra=fetch_channel_details(p,client=Client())
    assert extra['offers']==[] and extra['channelChecks'][0]['status']=='录用记录已变更或未找到'


def test_prepare_does_not_fetch_notes_to_reinterpret_other_channel(tmp_path, monkeypatch):
    from bonus_platform.engine import recruitment_prepare as jobs, recruitment_beisen as adapter
    store=DraftStore(tmp_path)
    p=snapshot();p['offers'][0]['customProperties'][CHANNEL]='10'
    state=store.save_beisen_snapshot(202607,0,p)
    calls=[]
    extra={**deepcopy(p),'channelDetailsOnly':True,'channelDetailsCheckedOfferIds':['offer1']}
    extra['offers'][0]['remarks']='招聘渠道：招聘会'
    monkeypatch.setattr(adapter,'fetch_channel_details',lambda payload,checked:calls.append('notes') or extra)
    monkeypatch.setattr(adapter,'fetch',lambda *args,**kw:pytest.fail('No full sync needed'))
    for _ in range(2):
        state=store.read(202607)
        jobs.run(store,202607,{'revision':state['revision'],'status':'running'},False,jobs.key_for(store,202607))
        assert jobs.read(store,202607)['status']=='complete'
    assert calls==[]
    assert len([s for s in store.read(202607)['sources'] if s['active']])==1


@pytest.mark.parametrize('detail', ['非内推', 'Boss或内推', '渠道待确认'])
def test_uncertain_dedicated_details_are_not_positive_channel_evidence(detail):
    assert _normalize_offer_channel('其他',detail)==('其他',False)


@pytest.mark.parametrize('detail,expected', [('新欧洲','招聘网站'),('西华网','招聘网站'),
    ('facebook','招聘网站'),('中介工转正','外包转正式')])
def test_existing_overseas_materials_use_existing_channel_categories(detail,expected):
    assert _normalize_offer_channel('其他',detail)==('其他',False)


@pytest.mark.parametrize('detail', ['国内','中介公司','人才市场'])
def test_location_or_ambiguous_agency_description_does_not_invent_channel(detail):
    assert _normalize_offer_channel('其他',detail)==('其他',False)


def test_successful_empty_note_query_is_not_an_unrecognized_upload(tmp_path):
    store=DraftStore(tmp_path)
    p=snapshot();state=store.save_beisen_snapshot(202607,0,p)
    p.update(channelDetailsOnly=True,channelDetailsCheckedOfferIds=['offer1'])
    p['offers'][0]['remarks']=None
    state=store.save_beisen_snapshot(202607,state['revision'],p)
    assert not any(t['kind']=='source_unrecognized' for t in state['todos'])


@pytest.mark.parametrize('remarks,status', [(None,'备注为空'),('招聘渠道：Boss','已取得备注')])
def test_full_sync_retains_the_result_of_checking_channel_remarks(tmp_path,remarks,status):
    p=snapshot();p['offers'][0].update(remarks=remarks)
    p['offers'][0]['customProperties'][CHANNEL]='10'
    state=DraftStore(tmp_path).save_beisen_snapshot(202607,0,p)
    assert state['sources'][0]['channelChecks']==[{'offerId':'offer1','status':status}]
    assert state['sources'][0]['channelDetailsCheckedOfferIds']==['offer1']

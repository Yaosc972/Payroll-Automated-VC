"""Regression checks for 招聘奖金字段取数逻辑.xlsx, not award standards."""
from copy import deepcopy

import pytest

from bonus_platform.engine.recruitment_drafts import DraftStore, assemble
from tests.test_recruitment_drafts import book, ROSTER


def test_roster_adds_only_current_ehr_zt_and_oehr_with_offer(tmp_path):
    store = DraftStore(tmp_path)
    state = store.ingest(202607, [('本月花名册.xlsx', book(ROSTER, [
        ['国内新增', 'zt100', '', '2026-07-01', '正式', '', '', 'EHR入职', '深圳', '中国'],
        ['国内非zt', 'gl100', '', '2026-07-01', '正式', '', '', 'EHR入职', '深圳', '中国'],
        ['海外新增', 'gl200', 'OF200', '2026-07-02', '正式', '', '', 'OEHR入职', '德国', '德国'],
        ['海外无编号', 'zt200', '', '2026-07-02', '正式', '', '', 'OEHR入职', '德国', '德国'],
        ['上月国内', 'zt300', '', '2026-06-01', '正式', '', '', 'EHR入职', '深圳', '中国'],
        ['下月海外', 'gl300', 'OF300', '2026-08-01', '正式', '', '', 'OEHR入职', '德国', '德国'],
    ]))], 0)
    assert {r['values']['工号'] for r in state['rows']} == {'zt100', 'gl200'}
    assert not any(set(t['rowIds']) - {r['id'] for r in state['rows']} for t in state['todos'])
    assert state['intakeSummary']['excludedByReason'] == {'ehrNonZt': 1, 'oehrMissingOffer': 1}


def test_intake_filter_does_not_filter_ledger_or_explicit_supplements(tmp_path):
    state = DraftStore(tmp_path).ingest(202607, [
        ('上月台账.xlsx', book(['姓名', '工号', '入职日期'],
                            [['历史人员', 'gl100', '2026-06-01']], title='附件一-招聘奖金核算明细')),
        ('补充人员.xlsx', book(['姓名', '工号', '入职日期'],
                            [['人工补充', 'gl200', '2026-07-01']], title='导入_月度数据')),
        ('本月花名册.xlsx', book(ROSTER, [
            ['历史人员', 'gl100', '', '2026-06-01', '离职', '', '2026-07-10', 'OEHR入职', '德国', '德国'],
            ['人工补充', 'gl200', '', '2026-07-01', '正式', '', '', 'OEHR入职', '德国', '德国'],
        ])),
    ], 0)
    assert {r['values']['工号'] for r in state['rows']} == {'gl100', 'gl200'}
    assert next(r for r in state['rows'] if r['values']['工号'] == 'gl100')['values']['最后工作日'] == '2026-07-10'


@pytest.mark.parametrize('protected', ['none', 'edit', 'history', 'supplement', 'decision', 'installment'])
def test_upgrade_removes_only_unreviewed_auto_rows_outside_intake_contract(tmp_path, protected):
    store = DraftStore(tmp_path)
    state = store.ingest(202607, [('花名册.xlsx', book(ROSTER, [
        ['原自动新增', 'gl200', 'OF200', '2026-07-01', '正式', '', '', 'OEHR入职', '德国', '德国'],
    ]))], 0)
    row = state['rows'][0]
    row['original']['海外offer流程编号'] = row['values']['海外offer流程编号'] = ''
    ref = row['sources'][0]
    records = [{'role': 'roster', 'values': deepcopy(row['original']), 'fieldColumns': {}, 'ref': ref}]
    if protected == 'edit':
        state['edits'] = [{'rowId': row['id'], 'field': '人工备注', 'value': '已人工核对', 'active': True}]
    elif protected == 'history':
        row['history'] = [{'ref': ref, 'cells': [], 'isBaseline': False}]
        row['originKinds'].append('ledger')
    elif protected == 'supplement':
        row['originKinds'].append('supplement')
    elif protected in {'decision', 'installment'}:
        state['operations'] = [{'id': 'approved', 'active': True}]
        key = 'awardDecisions' if protected == 'decision' else 'installmentPlans'
        state[key] = [{'rowId': row['id'], 'operationId': 'approved'}]
    result = assemble(202607, records, state)
    assert len(result['rows']) == (0 if protected == 'none' else 1)
    if protected != 'none':
        assert result['rows'][0]['id'] == row['id']


def test_historical_fields_are_frozen_but_monthly_dates_refresh(tmp_path):
    headers = ['姓名', '工号', '入职日期', '候选人入职时间', '人员状态', '职级', '直线经理',
               '直线经理工号', '标签分类', '工作地', 'ABC类别', '招聘负责人姓名', '招聘负责人工号',
               '招聘渠道', '招聘启动日期', '转正日期', '最后工作日', '推荐人姓名', '推荐人工号']
    opening = ['历史姓名', 'zt100', '2026-06-01', '2026-06-01', '试用', 'P2', '原经理', 'zt1',
               '国内', '中国大陆', 'C', '原招聘人', 'zt2', '招聘网站', '2026-05-01', '', '', '', '']
    store = DraftStore(tmp_path)
    state = store.ingest(202607, [
        ('上月核算表.xlsx', book(headers, [opening], title='附件一-招聘奖金核算明细')),
        ('本月花名册.xlsx', book(ROSTER + ['职级', '直线经理', '直线经理工号'], [
            ['新姓名', 'zt100', '', '2026-06-01', '离职', '2026-07-01', '2026-07-15', 'EHR入职', '广州', '中国', 'P5', '新经理', 'zt3'],
            ['新招聘人姓名', 'zt2', '', '2020-01-01', '正式', '', '', 'EHR入职', '广州', '中国', 'P2', '', ''],
        ])),
        ('新Offer.xlsx', book(['工号', '身份证', '编制ABC分类', '招聘负责人', '招聘负责人工号', '招聘渠道', '招聘启动日期',
                              'LookupPrefix_RecruitmentRequirement_extzhiweifenlei_109025_933701443'],
                             [['zt100', '', 'A', '新招聘人', 'zt4', '内推', '2026-05-10', 'A']])),
    ], 0)
    row = state['rows'][0]
    for field, value in zip(headers, opening):
        if field not in {'转正日期', '最后工作日'}:
            assert row['values'].get(field, '') == value, field
    assert row['values']['转正日期'] == '2026-07-01'
    assert row['values']['最后工作日'] == '2026-07-15'
    assert not set(row['unresolvedFields']) & set(headers)


@pytest.mark.parametrize('roster_offer',['same-offer','another-offer',''])
def test_same_offshore_offer_preserves_historical_recruitment_date(tmp_path,roster_offer):
    store=DraftStore(tmp_path)
    headers=['姓名','工号','入职日期','候选人入职时间','标签分类','海外offer流程编号','招聘渠道','ABC类别','招聘启动日期']
    state=store.ingest(202607,[
        ('招聘奖金核算明细202606.xlsx',book(headers,[['历史员工','zt200','2026-04-13','2026-04-13','海外','same-offer','招聘网站','B','2026-03-27']],title='附件一-招聘奖金核算明细')),
        ('本月花名册.xlsx',book(ROSTER,[['历史员工','zt200',roster_offer,'2026-04-29','试用','','','OEHR入职','美国','美国']])),
    ],0)
    row=state['rows'][0]
    assert row['values']['入职日期']=='2026-04-13'
    conflicts=[t for t in state['todos'] if t['kind']=='employment_conflict' and row['id'] in t['rowIds']]
    assert bool(conflicts)==(roster_offer!='same-offer')


def test_historical_direct_manager_alias_is_also_frozen(tmp_path):
    state = DraftStore(tmp_path).ingest(202607, [
        ('历史表.xlsx', book(['姓名', '工号', '入职日期', '直接上级工号'],
                         [['历史人员', 'zt100', '2026-06-01', 'zt-old']], title='附件一-招聘奖金核算明细')),
        ('本月花名册.xlsx', book(ROSTER + ['直接上级工号'], [
            ['历史人员', 'zt100', '', '2026-06-01', '正式', '', '', 'EHR入职', '中国', '中国', 'zt-new'],
        ])),
    ], 0)
    assert state['rows'][0]['values']['直线经理工号'] == 'zt-old'
    assert state['rows'][0]['values']['直接上级工号'] == 'zt-old'


def test_carried_new_hire_becomes_frozen_in_next_month(tmp_path):
    store = DraftStore(tmp_path)
    july = store.ingest(202607, [('7月花名册.xlsx', book(ROSTER + ['直线经理工号'], [
        ['原姓名', 'zt100', '', '2026-07-01', '试用', '', '', 'EHR入职', '中国大陆', '中国', 'zt1'],
    ]))], 0)
    august = store.carry_forward(202608, 202607, 0)
    august = store.ingest(202608, [('8月花名册.xlsx', book(ROSTER + ['直线经理工号'], [
        ['更新姓名', 'zt100', '', '2026-07-01', '正式', '2026-08-01', '', 'EHR入职', '深圳', '中国', 'zt2'],
    ]))], august['revision'])
    row = august['rows'][0]
    assert row['id'] == july['rows'][0]['id']
    assert row['values']['姓名'] == '原姓名'
    assert row['values']['人员状态'] == '试用'
    assert row['values']['直线经理工号'] == 'zt1'
    assert row['values']['转正日期'] == '2026-08-01'
    assert not set(row['unresolvedFields']) & {'姓名', '人员状态', '直线经理工号'}


def test_partial_history_is_not_silently_filled_from_current_offer(tmp_path):
    state = DraftStore(tmp_path).ingest(202607, [
        ('历史表.xlsx', book(['姓名', '工号', '入职日期', '海外offer流程编号'],
                         [['历史人员', 'gl100', '2026-06-01', 'OF100']], title='附件一-招聘奖金核算明细')),
        ('Offer.xlsx', book(['offer编码', '编制ABC分类', '招聘负责人', '招聘渠道'],
                           [['OF100', 'A', '本月招聘人', '内推']])),
    ], 0)
    assert not state['rows'][0]['values'].get('ABC类别')
    assert not state['rows'][0]['values'].get('招聘负责人姓名')


@pytest.mark.parametrize('with_columns', [True, False])
def test_monthly_date_empty_cell_clears_old_date_but_missing_column_does_not(tmp_path, with_columns):
    store = DraftStore(tmp_path)
    state = store.ingest(202607, [('上月表.xlsx', book(
        ['姓名', '工号', '入职日期', '标签分类', '转正日期', '最后工作日'],
        [['历史人员', 'zt100', '2026-06-01', '国内', '2026-06-20', '2026-06-30']],
        title='附件一-招聘奖金核算明细'))], 0)
    fields = ['姓名', 'JobNumber', 'EntryDate', 'EmployeeStatus']
    values = ['历史人员', 'zt100', '2026-06-01', '正式']
    if with_columns:
        fields += ['RegularizationDate', 'LastWorkDate']
        values += ['', '']
    state = store.ingest(202607, [('本月花名册.xlsx', book(fields, [values]))], state['revision'])
    row = state['rows'][0]
    assert row['values'].get('转正日期', '') == ('' if with_columns else '2026-06-20')
    assert row['values'].get('最后工作日', '') == ('' if with_columns else '2026-06-30')


def test_latest_month_roster_replaces_previous_month_dates_without_false_conflict(tmp_path):
    store = DraftStore(tmp_path)
    july = store.ingest(202607, [('7月花名册.xlsx', book(ROSTER, [
        ['国内人员', 'zt100', '', '2026-07-01', '正式', '2026-07-20', '2026-07-30', 'EHR入职', '中国', '中国'],
    ]))], 0)
    august = store.carry_forward(202608, 202607, 0)
    august = store.ingest(202608, [('8月花名册.xlsx', book(ROSTER, [
        ['国内人员', 'zt100', '', '2026-07-01', '正式', '2026-08-01', '', 'EHR入职', '中国', '中国'],
    ]))], august['revision'])
    row = august['rows'][0]
    assert row['id'] == july['rows'][0]['id']
    assert row['values']['转正日期'] == '2026-08-01'
    assert row['values'].get('最后工作日', '') == ''
    assert not set(row['unresolvedFields']) & {'转正日期', '最后工作日'}


def test_overseas_probation_is_blank_in_worksheet_not_a_monthly_input(tmp_path):
    state = DraftStore(tmp_path).ingest(202607, [('花名册.xlsx', book(ROSTER, [
        ['海外新增', 'gl100', 'OF100', '2026-07-01', '正式', '2026-07-20', '', 'OEHR入职', '德国', '德国'],
    ]))], 0)
    assert not state['rows'][0]['values'].get('转正日期')
    assert state['rows'][0]['provenance']['转正日期'][0]['rawValue'] == '2026-07-20'


def test_competing_current_month_dates_need_review_even_if_one_is_blank(tmp_path):
    state = DraftStore(tmp_path).ingest(202607, [
        ('上月表.xlsx', book(['姓名', '工号', '入职日期', '标签分类'],
                         [['历史人员', 'zt100', '2026-06-01', '国内']], title='附件一-招聘奖金核算明细')),
        ('本月花名册A.xlsx', book(ROSTER, [
            ['历史人员', 'zt100', '', '2026-06-01', '正式', '', '', 'EHR入职', '中国', '中国'],
        ])),
        ('本月花名册B.xlsx', book(ROSTER, [
            ['历史人员', 'zt100', '', '2026-06-01', '正式', '2026-07-10', '', 'EHR入职', '中国', '中国'],
        ])),
    ], 0)
    assert '转正日期' in state['rows'][0]['unresolvedFields']


def test_new_roster_fills_candidate_hire_and_uses_source_region_and_workplace(tmp_path):
    state = DraftStore(tmp_path).ingest(202607, [('花名册.xlsx', book(ROSTER, [
        ['国内人员', 'zt100', '', '2026-07-01', '正式', '', '', 'EHR入职', '深圳', '德国业务部门'],
        ['海外人员', 'gl100', 'OF100', '2026-07-02', '正式', '', '', 'OEHR入职', '德国柏林', '中国业务部门'],
    ]))], 0)
    rows = {r['values']['工号']: r for r in state['rows']}
    assert rows['zt100']['values']['工作地'] == '中国大陆'
    assert rows['zt100']['values']['标签分类'] == '国内'
    assert rows['gl100']['values']['工作地'] == '德国柏林'
    assert rows['gl100']['values']['标签分类'] == '海外'
    for row in rows.values():
        assert row['values']['候选人入职时间'] == row['values']['入职日期']
        assert row['provenance']['候选人入职时间'][0]['column'] == 4


def test_domestic_offer_joins_by_id_card_before_employee_number_and_maps_referrer(tmp_path):
    state = DraftStore(tmp_path).ingest(202607, [
        ('花名册.xlsx', book(ROSTER + ['身份证', '职级'], [
            ['国内人员', 'zt100', '', '2026-07-01', '正式', '', '', 'EHR入职', '深圳', '中国', 'ID100', 'P2'],
        ])),
        ('国内Offer.xlsx', book(['姓名', '工号', '身份证', '编制ABC分类', '招聘负责人工号', '招聘负责人',
                               '招聘渠道', '招聘启动日期', '内推人', '内推人工号', '职级', '二级组织'], [
            ['其他人员', 'zt100', 'OTHER-ID', 'A', 'zt-wrong', '错误负责人', '招聘网站', '2026-05-01', '', '', 'P8', '其他组织'],
            ['国内人员', 'zt999', 'ID100', 'C', 'zt-right', '正确负责人', '内推', '2026-06-01', '推荐甲', 'zt-ref', 'P5', '其他组织'],
        ])),
    ], 0)
    row = state['rows'][0]
    assert row['offerMatched']
    assert row['values']['招聘负责人工号'] == 'zt-right'
    assert row['values']['招聘负责人姓名'] == '正确负责人'
    assert row['values']['推荐人姓名'] == '推荐甲'
    assert row['values']['推荐人工号'] == 'zt-ref'
    assert row['values']['职级'] == 'P2'
    assert row['values']['二级组织'] == '中国'
    assert not set(row['unresolvedFields']) & {'职级', '二级组织', '招聘负责人工号'}


def test_overseas_offer_joins_flow_number_not_employee_number(tmp_path):
    state = DraftStore(tmp_path).ingest(202607, [
        ('花名册.xlsx', book(ROSTER, [
            ['海外人员', 'gl100', 'OF100', '2026-07-01', '正式', '', '', 'OEHR入职', '德国', '德国'],
        ])),
        ('海外Offer.xlsx', book(['offer编码', '工号', '编制ABC分类', '招聘负责人工号', '招聘渠道'],
                             [['OFOTHER', 'gl100', 'A', 'zt-wrong', '招聘网站']])),
    ], 0)
    row = state['rows'][0]
    assert not row['offerMatched']
    assert not row['values'].get('招聘负责人工号')


def test_domestic_id_only_offer_row_is_readable(tmp_path):
    state = DraftStore(tmp_path).ingest(202607, [
        ('花名册.xlsx', book(ROSTER + ['身份证'], [
            ['国内人员', 'zt100', '', '2026-07-01', '正式', '', '', 'EHR入职', '深圳', '中国', 'ID100'],
        ])),
        ('国内Offer.xlsx', book(['身份证', '编制ABC分类', '招聘负责人工号', '招聘渠道'],
                             [['ID100', 'C', 'zt-right', '招聘网站']])),
    ], 0)
    assert state['rows'][0]['offerMatched']
    assert state['rows'][0]['values']['招聘负责人工号'] == 'zt-right'


def test_business_worksheet_uses_active_contract_fields_not_deprecated_columns():
    from bonus_platform.engine.recruitment_drafts import EDITABLE_FIELDS
    from bonus_platform.engine.recruitment_worksheet import columns
    deprecated = {'职族', '职类', '职族分类', '海外招聘需求编号'}
    keys = {c['key'] for c in columns()}
    assert not keys & deprecated
    assert not EDITABLE_FIELDS & deprecated
    assert {'证件号', '直线经理', '直线经理工号', '候选人入职时间', '推荐人姓名', '推荐人工号'} <= keys
    assert next(c['title'] for c in columns() if c['key'] == 'ABC类别') == 'ABC类别'


@pytest.mark.parametrize('region', ['国内', '海外'])
def test_all_nine_offer_fields_use_documented_aliases_for_new_hires(tmp_path, region):
    roster = ['新入职', 'zt100', 'OF100' if region == '海外' else '', '2026-07-01', '正式', '', '',
              'OEHR入职' if region == '海外' else 'EHR入职', '德国' if region == '海外' else '深圳',
              '德国' if region == '海外' else '中国', 'ID100']
    aliases = ['编制ABC分类', '招聘负责人工号', '招聘负责人', '协助招聘负责人工号', '协助招聘负责人姓名',
               '招聘渠道', '招聘启动日期', '内推人', '内推人工号']
    offer = ['C', 'zt-owner', '招聘人甲', 'zt-assistant', '协助人乙', '内推', '2026-06-01', '推荐人丙', 'zt-referrer']
    anchors = ['offer编码'] if region == '海外' else ['身份证']
    state = DraftStore(tmp_path).ingest(202607, [
        ('花名册.xlsx', book(ROSTER + ['身份证'], [roster])),
        ('Offer.xlsx', book(anchors + aliases, [['OF100' if region == '海外' else 'ID100'] + offer])),
    ], 0)
    fields = ['ABC类别', '招聘负责人工号', '招聘负责人姓名', '协助招聘人工号', '协助招聘人姓名',
              '招聘渠道', '招聘启动日期', '推荐人姓名', '推荐人工号']
    for field, expected in zip(fields, offer):
        assert state['rows'][0]['values'][field] == expected, field


def test_explicit_domestic_id_mismatch_is_not_backfilled_by_same_employee_number(tmp_path):
    state = DraftStore(tmp_path).ingest(202607, [
        ('花名册.xlsx', book(ROSTER + ['身份证'], [
            ['甲', 'zt100', '', '2026-07-01', '正式', '', '', 'EHR入职', '深圳', '中国', 'ID100'],
        ])),
        ('国内Offer.xlsx', book(['姓名', '工号', '身份证', '编制ABC分类', '招聘负责人工号'],
                             [['乙', 'zt100', 'OTHER-ID', 'A', 'zt-wrong']])),
    ], 0)
    assert not state['rows'][0]['offerMatched']
    assert not state['rows'][0]['values'].get('招聘负责人工号')


def test_recipient_roster_does_not_replace_offer_relationship_names(tmp_path):
    state = DraftStore(tmp_path).ingest(202607, [
        ('花名册.xlsx', book(ROSTER, [
            ['海外新人', 'gl100', 'OF100', '2026-07-01', '正式', '', '', 'OEHR入职', '德国', '德国'],
            ['招聘人改名', 'zt200', '', '2020-01-01', '正式', '', '', 'EHR入职', '深圳', '中国'],
            ['推荐人改名', 'zt300', '', '2020-01-01', '正式', '', '', 'EHR入职', '深圳', '中国'],
        ])),
        ('海外Offer.xlsx', book(['offer编码', '编制ABC分类', '招聘负责人工号', '招聘负责人', '招聘渠道', '内推人', '内推人工号'],
                             [['OF100', 'C', 'zt200', 'Offer招聘姓名', '内推', 'Offer推荐姓名', 'zt300']])),
    ], 0)
    row = state['rows'][0]
    assert row['values']['招聘负责人姓名'] == 'Offer招聘姓名'
    assert row['values']['推荐人姓名'] == 'Offer推荐姓名'
    assert row['values']['招聘负责人入职日期'] == '2020-01-01'


@pytest.mark.parametrize('proven', [False, True])
def test_duplicate_domestic_id_uses_proven_current_requirement_not_an_old_offer(proven):
    def record(role, source, values, proof=None):
        return {'role': role, 'values': values, 'fieldColumns': {}, 'ref': {'sourceId': source, 'sheet': '资料', 'row': 2},
                **({'apiEvidence': proof} if proof else {})}
    records = [
        record('roster', 'roster', {'姓名': '再次入职', '工号': 'zt100', '证件号': 'ID100', '入职日期': '2026-07-01', '人员来源': 'EHR入职', '标签分类': '国内'}),
        record('domestic_offer', 'file', {'姓名': '再次入职', '证件号': 'ID100', '海外招聘需求编号': 11, '招聘负责人工号': 'zt-old', 'ABC类别': 'A'}),
        record('domestic_offer', 'file', {'姓名': '再次入职', '证件号': 'ID100', '海外招聘需求编号': 22, '招聘负责人工号': 'zt-new', 'ABC类别': 'C'}),
    ]
    if proven:
        records.append(record('domestic_offer', 'api', {'工号': 'zt100', '入职日期': '2026-07-01', '海外招聘需求编号': '22',
                                                       '招聘负责人工号': 'zt-new', 'ABC类别': 'C'}, {'offerId': 'O22', 'userId': 100}))
    state = {'sources': [{'id': r['ref']['sourceId'], 'forMonth': 202607, 'active': True, 'recordCount': 1} for r in records],
             'rows': [], 'edits': [], 'baseline': ''}
    row = assemble(202607, records, state)['rows'][0]
    if proven:
        assert row['values']['招聘负责人工号'] == 'zt-new'
        assert row['values']['ABC类别'] == 'C'
        assert not set(row['unresolvedFields']) & {'招聘负责人工号', 'ABC类别'}
        assert row['offerMatchBasis']['sources'][0]['sourceId'] == 'api'
    else:
        assert '招聘负责人工号' in row['unresolvedFields']

"""Business choices and source-backed evidence for recruitment fact editors."""
from .recruitment_draft_sources import text


CHOICES = {
    '二次入职执行口径': ('不发招聘奖金', '按40%核算'),
    '推荐人与候选人上下级关系': ('是', '否'),
    '推荐人是否直接/间接上级': ('是', '否'),
    '应届校招': ('是', '否'),
    '管培生已批名单资格': ('是', '否'),
    '是否二次入职': ('是', '否'),
    '延后入职原因': ('毕业离校', '公司集训', '其他'),
    '任职说明': ('新增任职：本次为独立招聘', '任职延续：人员迁移，本段不新增奖金'),
}
FACT_CHOICES = {'核算范围': ('纳入核算', '不纳入核算'),
                '二次入职间隔结论': ('超过十二个月', '不超过十二个月')}
LABELS = {
    '二次入职执行口径': '离职间隔不超过12个月，招聘奖金怎么核算',
    '推荐人与候选人上下级关系': '推荐人是否为候选人的直接或间接上级',
    '推荐人是否直接/间接上级': '推荐人是否为候选人的直接或间接上级',
    '管培生已批名单资格': '是否在已批准的管培生名单内',
    '任职说明': '本次任职关系',
    '周期剔除依据': '剔除天数来源',
    '周期豁免依据': '免周期资格来源',
    '管培生资格依据': '管培生资格来源',
}
PROOF_FIELDS = {'周期剔除依据': ('周期剔除天数',),
                '周期豁免依据': ('管培生已批名单资格', '原计划入职日期'),
                '管培生资格依据': ('管培生已批名单资格', '原计划入职日期')}
SYSTEM_FIELDS = {'二次入职执行口径', '二次入职专项口径依据', '旧特殊规则依据', '负周期确认依据',
                 '负周期确认启动日期', '负周期确认入职日期', '负周期确认剔除天数'}


def definitions():
    return {**{field:{'label':LABELS[field],'choices':[], 'missingMessage':'缺少剔除天数的原始记录或审批' if field=='周期剔除依据' else '缺少免周期资格名单或审批'} for field in PROOF_FIELDS},
            **{field: {'label': LABELS.get(field, field),
                    'choices': [{'value': value, 'label': ('本次为独立招聘' if value.startswith('新增任职：') else '沿用原任职，本段不新增奖金') if field=='任职说明' else value} for value in values]}
            for field, values in {**FACT_CHOICES, **CHOICES}.items()}}


def controls(state, row, *, matching_values=False):
    result = definitions()
    sources = {s['id']: s for s in state.get('sources', []) if s.get('active', True)
               and not s.get('error') and not s.get('comparisonOnly')}
    for field, related in PROOF_FIELDS.items():
        def relevant(f, ref):
            value = text(ref.get('value'))
            if not value or ref.get('sourceId') not in sources:
                return False
            if f == '管培生已批名单资格':
                return value == '是' and (not matching_values or row['values'].get(f) == '是')
            if f in related:
                if f == '周期剔除天数':
                    from decimal import Decimal, InvalidOperation
                    try:
                        return Decimal(value) > 0 and (not matching_values or Decimal(value) == Decimal(text(row['values'].get(f))))
                    except InvalidOperation:
                        return False
                return (not matching_values or value == text(row['values'].get(f))) and value not in {'0', '0.0'}
            return True
        refs = [ref for f in (field, *related) for ref in row.get('provenance', {}).get(f, []) if relevant(f, ref)]
        if matching_values and field == '周期剔除依据':
            counts = row.get('provenance', {}).get('周期剔除天数', [])
            refs = [ref for ref in refs if not any(c.get('sourceId') == ref['sourceId'] for c in counts)
                    or any(c.get('sourceId') == ref['sourceId'] and relevant('周期剔除天数', c) for c in counts)]
        choices = [{'value': 'source:' + sid, 'label': sources[sid]['name']}
                   for sid in dict.fromkeys(ref['sourceId'] for ref in refs)]
        result[field] = {'label': LABELS[field], 'choices': choices,
                         'missingMessage': '缺少剔除天数的原始记录或审批' if field == '周期剔除依据' else '缺少免周期资格名单或审批'}
        if not choices:
            award = row.get('calculation', {}).get('recruitment')
            issues = award.get('issues', []) if award else []
            required = (('周期剔除依据待核' in issues or field in row.get('unresolvedFields', [])) if award
                        else bool(row['values'].get('周期剔除天数')))
            if field != '周期剔除依据':
                required = '管培生免周期资格待核' in issues or row['values'].get('管培生已批名单资格') == '是'
            if not required:
                result[field].update(missingMessage='当前没有需要关联的剔除资料' if field == '周期剔除依据' else '当前未申请免周期资格', upload=False)
    return result


def shared_controls(state, rows):
    result = definitions()
    for field in PROOF_FIELDS:
        per_person = [controls(state, row)[field] for row in rows]
        common = [choice for choice in per_person[0]['choices'] if all(choice in d['choices'] for d in per_person[1:])] if per_person else []
        result[field] = {'label': LABELS[field], 'choices': common,
                         'missingMessage': '按人员关联已有资料', 'field': field,
                         'people': [{'id': row['id'], 'name': row['values'].get('姓名') or row['id'],
                                     'label': ' · '.join(str(row['values'].get(f)) for f in ('姓名', '工号', '入职日期') if row['values'].get(f))}
                                    for row in rows]}
    return result


def source_basis(state, row, field, token):
    if field not in PROOF_FIELDS or not str(token).startswith('source:'):
        return None
    source = next(s for s in state['sources'] if s['id'] == token[7:])
    fields = (*PROOF_FIELDS[field], '入职日期', '候选人入职时间', '招聘启动日期')
    return {'sourceId': source['id'], 'digest': source.get('contentDigest', ''),
            'facts': {f: text(row['values'].get(f)) for f in fields}}


def invalidate_source_choices(state, row):
    latest = {edit['field']: edit for edit in row.get('edits', [])}
    sources = {s['id']: s for s in state.get('sources', [])}
    for field, edit in latest.items():
        proof = edit.get('fieldSourceBasis')
        if not proof:
            continue
        source = sources.get(proof['sourceId'], {})
        valid = (bool(source) and source.get('active', True) and not source.get('error') and not source.get('comparisonOnly')
                 and source.get('contentDigest', '') == proof['digest']
                 and all(text(row['values'].get(f)) == value for f, value in proof['facts'].items()))
        if not valid:
            row['values'][field] = ''
            row['unresolvedFields'] = sorted(set(row['unresolvedFields']) | {field})


def expand_choices(edits):
    result = list(edits)
    notes = set(CHOICES['任职说明'])
    for edit in edits:
        if not isinstance(edit, dict) or edit.get('field') != '任职说明' or edit.get('value') not in notes:
            continue
        scope = '不纳入核算' if edit['value'].startswith('任职延续') else '纳入核算'
        existing = [e for e in edits if isinstance(e, dict) and e.get('rowId') == edit.get('rowId') and e.get('field') == '核算范围']
        if existing and any(e.get('value') != scope for e in existing):
            raise ValueError('任职关系与核算范围不一致，请重新选择')
        if not existing:
            result.append({'rowId': edit.get('rowId'), 'field': '核算范围', 'value': scope, 'reason': '选择本次任职关系'})
    return result


def normalize_edit(state, row, field, value, evidence):
    if field in CHOICES and field!='任职说明' and value and value not in CHOICES[field]:
        raise ValueError('请选择有效的' + LABELS.get(field, field))
    if field in PROOF_FIELDS and str(value).startswith('source:'):
        choices = controls(state, row, matching_values=True)[field]['choices']
        selected = next((c for c in choices if c['value'] == value), None)
        if not selected:
            raise ValueError('所选资料已变化，请重新选择' + LABELS[field])
        return '采用已导入资料《' + selected['label'] + '》', value[7:]
    return value, evidence

"""Explicit, reviewed personnel facts from comparison workbooks."""
from collections import Counter, defaultdict
from copy import deepcopy
from functools import lru_cache
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
from xml.etree import ElementTree as ET
import zipfile

from openpyxl.utils import get_column_letter

from .recruitment_draft_sources import PARSER_VERSION, _sheets, date_text, read_source, text

FACTS = (('ABC类别',), ('招聘渠道',), ('招聘启动日期',), ('招聘负责人姓名', '招聘负责人工号'))
FIELDS = frozenset(field for fact in FACTS for field in fact)
TRUSTED_KEYS = frozenset({'fieldSourceBasis', 'referenceFact', 'referenceBasis', 'employmentBasis', 'trusted', 'referenceProposal', 'referenceSelection'})
VERSION = 1


def signature(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _anchor(row):
    from .recruitment_drafts import staff_id
    values = row['values']
    return {'rowId': row['id'], 'name': text(values.get('姓名')).casefold(),
            'employeeId': staff_id(values.get('工号')), 'hireDate': date_text(values.get('入职日期') or values.get('候选人入职时间')),
            'facts': {field: text(values.get(field)) for field in ('证件号', '体系外人员编号', '职位', '二级组织', '三级组织', '工作地', '海外offer流程编号')}}


def _named_month(source):
    from .recruitment_attention import named_month
    periods=set(re.findall(r'(?<!\d)(20\d{2})[年._-]?(0?[1-9]|1[0-2])月?(?!\d)',source['name']))
    return named_month([source['name']]) if len(periods)==1 else None


@lru_cache(maxsize=2)
def _cached_source_records(path, source_id, content_digest, parser_version, content):
    # Parse values and formula locations from one snapshot; cached records stay read-only.
    parsed = read_source(Path(path), source_id, content=content)
    literal = {}
    with zipfile.ZipFile(BytesIO(content)) as archive:
        for sheet, location in _sheets(archive):
            for cell in ET.fromstring(archive.read(location)).iter():
                if cell.tag.rsplit('}', 1)[-1] != 'c':
                    continue
                literal[(sheet, cell.attrib.get('r'))] = not any(c.tag.rsplit('}', 1)[-1] == 'f' for c in cell)
    return content_digest, parsed['records'], literal


def _source_records(folder, source):
    path = Path(folder) / 'sources' / source.get('storedName', '')
    if path.suffix.lower() not in {'.xlsx', '.xlsm'} or not path.is_file():
        return None
    try:
        content = path.read_bytes()
        content_digest = hashlib.sha256(content).hexdigest()
        return _cached_source_records(str(path.resolve()), source['id'], content_digest, PARSER_VERSION, content)
    except (OSError, ValueError, KeyError, ET.ParseError, zipfile.BadZipFile):
        return None


def _catalog(folder, state, include_carried=False):
    from .recruitment_reconcile import match_reference,identity
    sources = [s for s in state.get('sources', []) if s.get('comparisonOnly') and s.get('active', True)
               and not s.get('error') and 'ledger' in s.get('roles', [])
               and _named_month(s) == s.get('forMonth')
               and (s.get('forMonth') == state['month'] or include_carried and s.get('forMonth', state['month']) < state['month'])]
    # Recruitment start is itself adoptable and cannot establish its own identity.
    targets = [{**row, 'values': {f: v for f, v in row['values'].items() if f != '招聘启动日期'}} for row in state['rows']]
    by_identity=defaultdict(list);by_name_date=defaultdict(list)
    for row in targets:
        by_identity[identity(row['values'])].append(row)
        by_name_date[(text(row['values'].get('姓名')).casefold(),date_text(row['values'].get('入职日期')))].append(row)
    matches = []
    for source in sources:
        result = _source_records(folder, source)
        if not result:
            continue
        content_digest, records, literal = result
        for record in records:
            if record.get('role') != 'ledger':
                continue
            values = {f: v for f, v in record['values'].items() if f != '招聘启动日期'}
            if not date_text(values.get('入职日期') or values.get('候选人入职时间')):
                continue
            key=identity(values)
            candidates=by_identity.get(key,[]) if key else by_name_date.get((text(values.get('姓名')).casefold(),date_text(values.get('入职日期'))),[])
            row = match_reference(values, candidates)
            if row and not row.get('identityConflict'):
                matches.append((source, content_digest, record, literal, row))
    counts = Counter(row['id'] for *_, row in matches)
    result = []
    for source, content_digest, record, literal, row in matches:
        if counts[row['id']] != 1:
            continue
        for fields in FACTS:
            values = {}; refs = []
            for field in fields:
                column = record.get('fieldColumns', {}).get(field)
                value = record['values'].get(field)
                raw = record.get('rawValues', {}).get(field)
                cell = f'{get_column_letter(column)}{record["ref"]["row"]}' if column else ''
                if not column or not literal.get((record['ref']['sheet'], cell)) or text(raw) in {'', '-', '无', 'N/A'}:
                    break
                if field == 'ABC类别':
                    value = text(value).replace('类', '').replace('C1', 'C')
                    if value not in {'A', 'B', 'C'}:
                        break
                elif field == '招聘启动日期':
                    value = date_text(value)
                    if not value:
                        break
                else:
                    value = text(value)
                if not value or str(raw).startswith('='):
                    break
                values[field] = value
                refs.append({**record['ref'], 'sourceName': source['name'], 'column': column, 'cell': cell,
                             'field': field, 'value': value, 'rawValue': raw, 'literal': True})
            if len(values) != len(fields):
                continue
            proof = {'version': VERSION, 'sourceId': source['id'], 'sourceMonth': source['forMonth'],
                     'contentDigest': content_digest, 'parserVersion': PARSER_VERSION,
                     'target': _anchor(row), 'values': values, 'refs': refs}
            pid = signature({'sourceId': source['id'], 'sheet': record['ref']['sheet'], 'row': record['ref']['row'],
                             'rowId': row['id'], 'fields': fields})
            result.append({'id': pid, 'signature': signature(proof), 'rowId': row['id'], 'values': values, 'refs': refs, 'proof': proof})
    return result


def proposals(folder, state):
    return _catalog(folder, state)


def selection_edits(folder, state, selections, *, retained_edits=None):
    if not isinstance(selections, list) or len(selections) > 5000:
        raise ValueError('参考事实选择格式无效')
    if not selections:
        return []
    from .recruitment_reconcile import comparable
    catalog = {p['id']: p for p in proposals(folder, state)}
    retained = {(e['rowId'], e['field']): e['value'] for e in retained_edits or []}
    edits = []; seen = set()
    for selection in selections:
        if not isinstance(selection, dict) or set(selection) != {'proposalId', 'signature'}:
            raise ValueError('只能提交参考事实标识和签名')
        proposal = catalog.get(selection['proposalId'])
        if not proposal or proposal['signature'] != selection['signature'] or proposal['id'] in seen:
            raise ValueError('参考事实或对应任职已变化，请重新选择并预览')
        seen.add(proposal['id'])
        preserved = {field: retained[(proposal['rowId'], field)] for field in proposal['values']
                     if (proposal['rowId'], field) in retained}
        if any(comparable(field, value) != comparable(field, proposal['values'][field]) for field, value in preserved.items()):
            raise ValueError('参考人员事实与审批已明确的人员字段不一致')
        for field, value in proposal['values'].items():
            if field in preserved:
                continue
            edits.append({'rowId': proposal['rowId'], 'field': field, 'value': value,
                          'reason': '核对并采用参考表人员事实', 'evidenceId': proposal['proof']['sourceId'],
                          'referenceFact': {**deepcopy(proposal), 'proposalId': proposal['id'],
                                            **({'retainedFields': preserved} if preserved else {})}})
    return edits


def effective_edits(folder, state, catalog=None, *, proposed_edits=None):
    if not any(e.get('referenceFact') and e.get('active',True) for e in state.get('edits',[])):
        return list(state.get('edits',[])),[]
    from .recruitment_reconcile import comparable
    rows = {row['id']: row for row in state['rows']}
    pending = {(e['rowId'],e['field']):e['value'] for e in proposed_edits or [] if not e.get('referenceFact')}
    catalog = {p['id']: p for p in (_catalog(folder, state, True) if catalog is None else catalog)}
    effective = []; stale = []
    for edit in state.get('edits', []):
        proof = edit.get('referenceFact')
        if not proof or not edit.get('active', True):
            effective.append(edit)
            continue
        actual = catalog.get(proof.get('proposalId'))
        valid = bool(actual and actual['signature'] == proof.get('signature') and actual['proof'] == proof.get('proof')
                     and actual['rowId'] == edit.get('rowId') and edit.get('field') in actual['values']
                     and actual['values'][edit['field']] == edit.get('value')
                     and all(field in actual['values']
                             and comparable(field,value)==comparable(field,actual['values'][field])
                             and comparable(field,value)==comparable(field,pending.get((actual['rowId'],field),rows[actual['rowId']]['values'].get(field)))
                             and field not in rows[actual['rowId']].get('unresolvedFields',[])
                             for field,value in proof.get('retainedFields',{}).items()))
        if valid:
            effective.append(edit)
        else:
            stale.append({'rowId': edit.get('rowId'), 'field': edit.get('field'), 'proposalId': proof.get('proposalId'),
                          'reason': '参考来源或对应任职已变化，请重新核对'})
    return effective, stale


def strip_generated_values(state):
    """Remove inherited generated facts before rebuilding original source facts."""
    before = {}
    for edit in state.get('edits', []):
        if edit.get('referenceFact') or edit.get('employmentBasis'):
            before.setdefault((edit['rowId'], edit['field']), edit.get('before', ''))
    for row in state['rows']:
        for (rid, field), value in before.items():
            if rid == row['id']:
                row['values'][field] = value
                row.get('original', {})[field] = value
    return state


def project(folder, state, catalog=None, stale=None):
    from .recruitment_reconcile import comparable
    catalog = proposals(folder, state) if catalog is None else catalog
    by_row = defaultdict(list)
    active = {(e['rowId'], e['field']): e for e in state.get('edits', []) if e.get('active', True)}
    rows={row['id']:row for row in state['rows']}
    for proposal in catalog:
        row=rows[proposal['rowId']]
        if all(comparable(field,row['values'].get(field))==comparable(field,value) and field not in row.get('unresolvedFields',[]) for field,value in proposal['values'].items()) and not any(active.get((proposal['rowId'],field),{}).get('referenceFact') for field in proposal['values']):
            continue
        statuses = [active.get((proposal['rowId'], field), {}) for field in proposal['values']]
        preserved = {field for e in statuses if e.get('referenceFact',{}).get('signature')==proposal['signature']
                     for field,value in e['referenceFact'].get('retainedFields',{}).items()
                     if comparable(field,row['values'].get(field))==comparable(field,value)}
        adopted = all(active.get((proposal['rowId'],field),{}).get('referenceFact',{}).get('signature')==proposal['signature']
                      or field in preserved for field in proposal['values'])
        status = 'adopted' if adopted else 'superseded' if any(statuses) else 'available'
        by_row[proposal['rowId']].append({k: deepcopy(v) for k, v in proposal.items() if k != 'proof'} | {
            'fields': list(proposal['values']), 'canAdopt': True, 'status': status})
    state['referenceFacts'] = {'contractVersion': VERSION, 'byRowId': dict(by_row),
                               'staleEdits': stale if stale is not None else state.get('referenceFacts', {}).get('staleEdits', [])}
    return state


def enrich_detail(folder, state, data):
    if 'referenceFacts' not in state:
        project(folder, state)
    by_row = state['referenceFacts']['byRowId']
    fields = data.get('fields', []) + data.get('currentFields', [])
    for field in fields:
        name = field['field']
        if name not in FIELDS:
            continue
        row_ids = {t if isinstance(t,str) else t['rowId'] for t in field.get('targets', [])}
        row_ids.update(t['rowId'] for t in field.get('bindings', []) if t.get('rowId'))
        if not row_ids:
            row_ids = set(data.get('rowIds', []))
            if data.get('rowId'):
                row_ids.add(data['rowId'])
        for rid in row_ids:
            for proposal in by_row.get(rid, []):
                if name not in proposal['values']:
                    continue
                choice={'proposalId':proposal['id'],'signature':proposal['signature']}
                if any(option.get('referenceProposal')==choice for option in field.get('options',[])):
                    continue
                if name == '招聘负责人姓名' and any(f['field']=='招聘负责人工号' and rid in f.get('targets',[]) for f in fields):
                    continue
                refs = proposal['refs']; value = proposal['values'][name]
                label = ' / '.join(str(v) for v in proposal['values'].values())
                label += ' · ' + '、'.join(f'{ref["sourceName"]} {ref["sheet"]}!{ref["cell"]}' for ref in refs)
                field.setdefault('options', []).append({'value': value, 'label': label, 'sources': refs,
                    'referenceProposal':choice,'referenceStatus':proposal['status']})
    data['referenceFacts'] = state['referenceFacts']
    return data

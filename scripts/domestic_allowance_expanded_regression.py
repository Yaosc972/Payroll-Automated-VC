"""Read-only real-material regression; outputs contain source rows, not employee identities."""
from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bonus_platform.engine.domestic_labor.parser import MultiFilePayrollDataLoader, ExcelParser
from bonus_platform.engine.domestic_labor.engines.gaowen_butie import GaoWenBuTieEngine
from bonus_platform.engine.domestic_labor.engines.yeban_butie import YeBanBuTieEngine
from bonus_platform.engine.domestic_labor.night_shift_config import load_night_shift_config
from scripts.domestic_labor_night_shift_202607_validation import _read_region, _calculate, DEFAULT_SOUTH, DEFAULT_EAST
from scripts.domestic_night_feedback_review import review_note

DATA = Path('/Users/zt27532/Documents/AI算薪')
OUT = ROOT / 'outputs/regression_20260909'
HISTORY = ROOT / 'outputs/01a061c0-14fb-7962-8f9a-6bbbefead92f'


def money(value):
    return float(Decimal(str(value)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP))


def day_text(value):
    return value.strftime('%Y-%m-%d') if isinstance(value, (date, datetime)) else str(value or '')[:10]


def load_material(paths):
    # Only ancillary sheets are ignored. No source file is altered.
    mapping = {}
    for i, path in enumerate(paths):
        parser = ExcelParser(path)
        parser.load()
        for name in parser.get_sheet_names():
            raw = parser.parse_sheet(name)
            if MultiFilePayrollDataLoader._sheet_type(name, raw.headers) is None:
                mapping[f'{i}:{name}'] = 'ignore'
        parser.close()
    loader = MultiFilePayrollDataLoader(paths, sheet_mapping=mapping)
    loader.load()
    monthly = loader.monthly.rows
    daily = loader.group_daily_by_employee()
    temp = loader.temperature.rows if loader.temperature else []
    for parser in loader.parsers:
        parser.close()
    return monthly, daily, temp, mapping


def night_material(label, paths, month, compare):
    monthly, grouped, _, ignored = load_material(paths)
    engine = YeBanBuTieEngine()
    config = load_night_shift_config(month, required=False)
    people = {row['工号']: row for row in monthly}
    counts, reasons, months = Counter(), Counter(), Counter()
    total = 0
    mismatch_examples = []
    for eid, days in grouped.items():
        if eid not in people:
            counts['days_without_monthly_employee'] += len(days)
            continue
        result = engine.calculate(people[eid], days, config=config)
        details = result.details['daily_results']
        assert len(details) == len(days)
        for raw, detail in zip(days, details):
            months[day_text(raw.get('出勤日期') or raw.get('日期'))[:7]] += 1
            counts['daily_rows'] += 1
            counts['status_' + detail['status']] += 1
            reasons[detail['reason_code']] += 1
            value = detail.get('amount')
            if value is not None:
                assert 0 <= value <= 25, (label, detail['reason_code'], value)
                total += value
            if compare:
                offline = raw.get('夜班补贴')
                if offline not in (None, '') and not isinstance(offline, (int, float)):
                    counts['offline_non_numeric'] += 1
                    continue
                offline = float(offline or 0)
                counts['comparable_rows'] += 1
                counts['offline_paid_rows'] += int(offline > 0)
                if abs((value or 0) - offline) < .011:
                    counts['numeric_equal_rows'] += 1
                else:
                    counts['numeric_different_rows'] += 1
                    if len(mismatch_examples) < 12:
                        mismatch_examples.append({'date': day_text(raw.get('出勤日期')), 'shift': detail['shift_code'], 'offline': offline, 'current': value, 'reason': detail['reason_code']})
    assert set(months) == {month[:4] + '-' + month[4:]}, (label, months)
    return {'sources': [str(p) for p in paths], 'ignored_sheets': list(ignored), 'monthly_rows': len(monthly), 'actual_months': dict(months), 'counts': dict(counts), 'reasons': dict(reasons), 'amount': money(total), 'comparison': '旧线下金额；空白按0对照，未定金额单独看状态' if compare else '无独立应发金额，仅核算覆盖与边界检查', 'examples': mismatch_examples}


def july_feedback():
    prior = json.loads((HISTORY / 'night_shift_202607_after_lb15.json').read_text())
    fixed = {(r['region'], r['source_row']) for r in prior['confirmed_offline_formula_details']}
    cached = json.loads((HISTORY / 'night_shift_feedback_review_20260907.json').read_text())
    feedback = {(r['region'], r['source']['source_row']): r['feedback'] for r in cached['joined']}
    counters = Counter()
    examples = []
    config = load_night_shift_config('202607', required=False)
    for label, region, path in [('south', '华南', DEFAULT_SOUTH), ('east', '华东', DEFAULT_EAST)]:
        people, grouped, offline, duplicates = _read_region(label, path)
        assert duplicates == 0
        platform, _, _ = _calculate(people, grouped, config)
        assert set(platform) == set(offline)
        for key, source in offline.items():
            current = platform[key]
            loc = (region, source['source_row'])
            diff = money((current['amount'] or 0) - source['amount'])
            counters['rows'] += 1
            if not diff:
                counters['numeric_equal'] += 1
                continue
            counters['numeric_different'] += 1
            if loc in fixed:
                counters['previously_confirmed_offline_formula'] += 1
                continue
            f = feedback.get(loc)
            conclusion = ''
            if f:
                conclusion, _ = review_note({'feedback': f, 'current': current, 'source': source, 'numeric_difference': diff})
            if conclusion == '平台符合业务明确金额':
                counters['platform_matches_feedback_amount'] += 1
            elif conclusion.startswith('业务确认'):
                counters['business_confirmed_offline'] += 1
            else:
                counters['remaining_for_review'] += 1
                examples.append({'region': region, 'source_row': source['source_row'], 'date': source['attendance_date'], 'shift': source['shift_code'], 'offline': source['amount'], 'current': current['amount'], 'status': current['status'], 'reason': current['reason_code'], 'feedback_row': f['sheet_row'] if f else None, 'conclusion': conclusion})
    return {'counts': dict(counters), 'remaining': examples, 'feedback_source': '本地既有583条反馈及已保存业务决定，未刷新飞书；归类不代表线下已更正'}


def temperature_july():
    monthly, grouped, temperatures, ignored = load_material([DEFAULT_EAST, DEFAULT_SOUTH])
    engine = GaoWenBuTieEngine(temperatures)
    # Existing independently extracted offline monthly totals and source locators.
    offline = {}
    p = HISTORY / '高温及岗位补贴线上线下差异明细_202607_20260903.xlsx.inspect.ndjson'
    for line in p.open():
        if '"sheet":"高温月度全量"' not in line:
            continue
        block = json.loads(line)
        if block.get('kind') == 'table':
            for row in block['values'][1:]:
                offline[row[2]] = {'amount': row[8], 'region': row[15], 'source_row': row[16]}
    assert len(offline) > 1000
    stats, regions, changes, residuals = Counter(), defaultdict(Counter), [], []
    for emp in monthly:
        eid = emp['工号']
        days = grouped.get(eid, [])
        result = engine.calculate(emp, days)
        prior_emp = dict(emp)
        prior_emp.pop('办公地点是否有空调', None)
        prior_days = [{k: v for k, v in d.items() if k != '测温网点'} for d in days]
        before = engine.calculate(prior_emp, prior_days)
        stats['employees'] += 1
        stats['days'] += len(days)
        assert len(result.details['daily_results']) == len(days)
        assert 0 <= result.amount <= result.details['月度封顶']
        exact_total = Decimal('0')
        for raw, d in zip(days, result.details['daily_results']):
            if d['amount'] > 0:
                hours = max(Decimal(str(raw.get('正班时数') or 0)), Decimal(str(raw.get('刷卡加班') or 0)), Decimal('0'))
                exact_total += min(hours * Decimal(str(result.details['小时单价'])), Decimal(str(result.details['单日封顶'])))
        assert result.amount == money(min(exact_total, Decimal(str(result.details['月度封顶']))))
        for raw, d in zip(days, result.details['daily_results']):
            explicit = str(raw.get('测温网点') or '').strip()
            if explicit:
                assert d['site'] == explicit
            if raw.get('测温班次') in ('白班', '夜班'):
                assert d['shift'] == raw['测温班次']
            assert 0 <= d['amount'] <= result.details['单日封顶']
            if d['amount'] > 0:
                assert d['temperature'] >= 33 and d['attendance_hours'] > 0
            if d['reason_code'] == 'no_matching_temperature':
                assert d['amount'] == 0
                stats['missing_temperature_days'] += 1
        if emp.get('办公地点是否有空调') == '是':
            assert result.amount == 0
            stats['air_conditioned_employees'] += 1
        if result.details['reason_counts'].get('no_matching_temperature'):
            stats['employees_missing_temperature'] += 1
            stats['zero_employees_missing_temperature'] += int(result.amount == 0)
        source = offline.get(eid)
        if not source:
            stats['no_offline_match'] += 1
            continue
        expected = source['amount']
        group = regions[source['region']]
        group['employees'] += 1
        group['current_total'] += result.amount
        group['offline_total'] += expected
        if source['region'] == '华东':
            legacy_total = Decimal('0')
            for raw, detail in zip(days, result.details['daily_results']):
                if detail['amount'] > 0:
                    hours = max(Decimal(str(raw.get('正班时数') or 0)), Decimal(str(raw.get('刷卡加班') or 0)), Decimal('0'))
                    legacy_total += min(hours * Decimal('1.725'), Decimal('13.8'))
            legacy_amount = money(min(legacy_total, Decimal('200')))
            group['same_inputs_legacy_rate_matches_offline'] += int(abs(legacy_amount - expected) < .011)
            group['same_inputs_legacy_rate_differs_offline'] += int(abs(legacy_amount - expected) >= .011)
            for raw, detail in zip(days, result.details['daily_results']):
                offline_day = raw.get('高温补贴')
                if offline_day in (None, ''):
                    offline_day = 0
                if not isinstance(offline_day, (int, float)):
                    continue
                hours = max(Decimal(str(raw.get('正班时数') or 0)), Decimal(str(raw.get('刷卡加班') or 0)), Decimal('0'))
                legacy_day = min(hours * Decimal('1.725'), Decimal('13.8')) if detail['amount'] > 0 else Decimal('0')
                if abs(float(legacy_day) - offline_day) >= .011:
                    group['daily_legacy_difference_' + detail['reason_code']] += 1
                    if not isinstance(raw.get('温度'), (int, float)):
                        group['daily_legacy_difference_with_missing_offline_temperature'] += 1
        equal = abs(result.amount - expected) < .011
        if source['region'] == '华东' and not equal and abs(legacy_amount - expected) < .011:
            group['current_difference_explained_by_rate_only'] += 1
        was_equal = abs(before.amount - expected) < .011
        group['equal'] += int(equal)
        group['different'] += int(not equal)
        stats['previously_equal_now_different'] += int(was_equal and not equal)
        info = {**source, 'before_recent_changes': before.amount, 'current': result.amount, 'difference': money(result.amount - expected), 'site': result.details['测温网点'], 'qualification': result.details['资格判断'], 'reasons': result.details['reason_counts']}
        if source['region'] == '华东':
            info['legacy_rate_amount'] = legacy_amount
        if before.amount != result.amount:
            changes.append(info)
        if not equal:
            residuals.append(info)
    return {'counts': dict(stats), 'regions': {k: {a: money(b) if 'total' in a else b for a,b in v.items()} for k,v in regions.items()}, 'changed_employees': len(changes), 'changes': changes, 'residuals': residuals, 'temperature_rows': len(temperatures), 'baseline_note': '近期网点与空调改动前：保留当前其他规则和浙江9.2元标准，仅移除日考勤网点与导入空调标记；非历史生产版本'}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    report = {'generated_at': datetime.now().isoformat(), 'mode': '本地只读复算，未修改生产或原始工作簿', 'files': {}}
    for name in ['parser.py', 'engines/gaowen_butie.py', 'engines/yeban_butie.py', 'data/night_shift_breaks.json']:
        path = ROOT / 'bonus_platform/engine/domestic_labor' / name
        report['files'][name] = hashlib.sha256(path.read_bytes()).hexdigest()
    report['night'] = {}
    cases = [('may_south', [DATA/'中国操作部5月考勤补贴-外包人员/202605日考勤数据 (操作).xlsx'], '202605', True), ('may_east', [DATA/'中国操作部5月考勤补贴-外包人员/5月华东枢纽外包费用.xlsx'], '202605', True)]
    for path in sorted((DATA/'考勤数据/6月考勤').glob('*.xlsx')):
        cases.append((path.stem, [path], '202606', False))
    for label, paths, month, compare in cases:
        report['night'][label] = night_material(label, paths, month, compare)
        (OUT/'expanded.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        print('completed', label, flush=True)
    report['night_july_feedback'] = july_feedback()
    (OUT/'expanded.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print('completed night July feedback', flush=True)
    report['temperature_july'] = temperature_july()
    (OUT/'expanded.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print('completed', OUT/'expanded.json', flush=True)


if __name__ == '__main__':
    main()

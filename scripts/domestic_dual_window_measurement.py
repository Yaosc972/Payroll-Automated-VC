"""Read-only July scenario comparison; does not change production rules."""
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.domestic_labor_night_shift_202607_validation import _read_region, _calculate, DEFAULT_EAST, DEFAULT_SOUTH, _day
from bonus_platform.engine.domestic_labor.engines.yeban_butie import YeBanBuTieEngine, _time_minutes, _parse_schedule_period
from bonus_platform.engine.domestic_labor.night_shift_config import load_night_shift_config


def main():
    config = load_night_shift_config('202607', required=False)
    engine = YeBanBuTieEngine()
    rows = []
    scanned = 0
    missing_punches = 0
    for region, path in [('south', DEFAULT_SOUTH), ('east', DEFAULT_EAST)]:
        people, grouped, offline, duplicates = _read_region(region, path)
        assert not duplicates
        platform, _, _ = _calculate(people, grouped, config)
        scanned += len(offline)
        for employee, attendance in grouped.items():
            for original in attendance:
                start = _time_minutes(original['上班一'])
                end = _time_minutes(original['下班一'])
                if start is None or end is None:
                    missing_punches += 1
                    continue
                # Same-date morning and evening overlap; overnight single-window rows stay unchanged.
                if not (start < 480 and 1320 < end < 1440):
                    continue
                key = (employee, _day(original['出勤日期']))
                source = offline[key]
                current = platform[key]
                if original['班次编号'] == 'LB15':
                    continue
                schedule = _parse_schedule_period(original['班次时间段'])
                if schedule is None:
                    rows.append({'source': source, 'region': region, 'blocked': 'missing_schedule'})
                    continue
                segments = []
                for updates in [{'下班一': '08:00'}, {'上班一': '22:00'}]:
                    row = dict(original, **updates)
                    result = engine.calculate(dict(people[employee]), [row], config=config).details['daily_results'][0]
                    segments.append(result)
                effective = [max(0, r['night_minutes']-r['break_minutes']) if r['status'].startswith('calculated') else 0 for r in segments]
                separate_minutes = sum(math.floor(m/30)*30 for m in effective if m >= 60)
                combined_minutes = math.floor(sum(effective)/30)*30 if sum(effective) >= 60 else 0
                separate = min(25, separate_minutes/60*3)
                combined = min(25, combined_minutes/60*3)
                per_window_cap = sum(min(25, math.floor(m/30)*1.5) for m in effective if m >= 60)
                rows.append({'source': source, 'region': region, 'current': current['amount'], 'current_reason': current['reason_code'], 'effective_minutes': effective, 'separate_threshold_daily_cap': separate, 'combined_threshold_daily_cap': combined, 'separate_window_caps': per_window_cap, 'segments': segments})
    valid = [r for r in rows if 'blocked' not in r]
    changed = [r for r in valid if abs(r['separate_threshold_daily_cap']-(r['current'] or 0)) > .000001]
    summary = {'scanned': scanned, 'missing_punches_not_inferred': missing_punches, 'raw_morning_evening_candidates_excluding_LB15': len(rows), 'both_effective_windows': sum(all(m>0 for m in r['effective_minutes']) for r in valid), 'both_at_least_one_hour': sum(all(m>=60 for m in r['effective_minutes']) for r in valid), 'separate_vs_combined_different': sum(r['separate_threshold_daily_cap'] != r['combined_threshold_daily_cap'] for r in valid), 'daily_vs_window_cap_different': sum(r['separate_threshold_daily_cap'] != r['separate_window_caps'] for r in valid), 'changed_count': len(changed), 'change_amount': sum(r['separate_threshold_daily_cap']-(r['current'] or 0) for r in changed), 'blocked': sum('blocked' in r for r in rows)}
    result = {'summary': summary, 'changed': changed, 'candidates': rows, 'scope': 'Same-date morning/evening punches only; known eligibility and break rules retained. Missing punches not inferred; LB15 unchanged. Scenario amounts are not approved payroll.'}
    out = ROOT/'outputs/01a061c0-14fb-7962-8f9a-6bbbefead92f/dual_window_measurement_20260908.json'
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    print(json.dumps({'summary': summary, 'changed': [{k:v for k,v in r.items() if k != 'segments'} for r in changed]}, ensure_ascii=False, default=str))


if __name__ == '__main__':
    main()

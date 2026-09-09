"""Read-only reconciliation of Lark feedback against the current July engine."""
import csv
import io
import json
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.domestic_labor_night_shift_202607_validation import (
    _read_region, _calculate, DEFAULT_SOUTH, DEFAULT_EAST,
)
from bonus_platform.engine.domestic_labor.night_shift_config import load_night_shift_config

OUT = ROOT / 'outputs/01a061c0-14fb-7962-8f9a-6bbbefead92f'

def review_note(r):
    f = r['feedback']; n = f['sheet_row']; x = f.get('差异',''); c=r['current']
    if n in [35, 137, 224, 225]:
        confirmed = {35: 10.5, 137: 21, 224: 25, 225: 16.5}[n]
        return ('业务确认按平台金额收口，不再待确认',
                f'2026-09-08用户确认本行不再待确认，以平台{confirmed:g}元为准；转线下更正跟踪，不再要求重复确认金额或享有资格，不代表线下已完成更正。')
    if n in [5,7,8] and r['source']['shift_code'] == 'HD003' and c['amount'] == 6:
        return ('早晨漏算已修复，超长考勤仍需复核',
                '2026-09-07修复早班22点后下班时漏计早晨的问题，06:00至08:00现计6元。第5行与业务明确金额一致；第7、8行旧线下4.5元仍需登记更正。')
    if (47 <= n <= 65 or 274 <= n <= 333) and r['source']['shift_code'] == 'HD005':
        return ('业务确认线下漏算（用户转述王雯雯）',
                '2026-09-07用户转述王雯雯确认该79条为线下漏算；平台07:00至08:00计3元正确，无需改算法。接口版本413仍为旧反馈，保留原文并单独记录确认来源。')
    notes = {
        4: ('业务确认线下核算有误', '2026-09-08用户确认本行线下核算有误。平台按有效夜班8.5小时封顶暂算25元，金额及算法不变；保留超16小时复核提示，本次确认不等于已核实真实连班或完成线下更正。'),
        5: ('平台早晨跨日计算待修正', '当前0元虽与旧线下一致，业务明确应为6元；05:58至22:30的早晨06:00至08:00被漏计，不能标已解决。'),
        7: ('平台早晨跨日计算待修正', '05:48至22:14漏计早晨窗口；若06:00至08:00享有，应6元；旧线下4.5元也需复核。'),
        8: ('平台早晨跨日计算待修正', '05:49至22:08漏计早晨窗口；若06:00至08:00享有，应6元；旧线下4.5元也需复核。'),
        46: ('业务确认线下漏算，平台无问题', '2026-09-08用户提供截图明确“线下漏算，应该有3元夜班补贴”。HD005按排班07:00至08:00计1小时，平台3元正确，旧线下0元需补算3元；原“线上计算错误”标签不再作为修改算法依据。'),
        66: ('业务未回填，休息边界待核', '00:29下班取整至00:00，未覆盖00:00至01:00休息；平台6元，线下3元。'),
        69: ('业务确认线下漏扣休息，平台无问题', '2026-09-08用户确认线下漏扣休息时间。23:00至08:00共9小时，扣晚休1小时、早休0.5小时，平台22.5元保持；旧线下25元需更正，原反馈24元不再作为目标金额。'),
        70: ('业务确认线下漏扣休息，平台无问题', '2026-09-08用户确认线下漏扣休息时间。23:23取整至23:30，至08:00共8.5小时，扣实际覆盖晚休0.5小时、早休0.5小时，平台22.5元保持；旧线下25元需更正，原反馈21元不再作为目标。不扩大为无论到岗时间均扣完整1小时。'),
        264: ('业务确认线下漏算', '2026-09-08用户确认线下没算。沿用已确认排班起点，HD005从07:00至08:00计1小时，平台3元保持；原反馈06:30不作为扩大计发时段的依据。线下需补算并复核，平台算法不变。'),
        270: ('业务确认线下漏算', '2026-09-08用户确认线下漏算。沿用原表07:00打卡，计至08:00满1小时，平台3元保持；原反馈07:01不作为修改原始打卡或归零的依据。线下需补算并复核，平台算法不变。'),
        355: ('资格与时长门槛需同时判断', '20点班具备候选资格，但19:37至22:32取整后夜间仅0.5小时；按新确认门槛为0元，不能直接按线下漏发处理。'),
        583: ('业务确认线下计算错误', '2026-09-08用户确认：平台19.5元正确，线下22.5元应更正。双方早休均0.5小时，线下漏扣00:00至01:00晚休1小时；平台算法及休息配置不变。'),
        584: ('业务确认线下计算错误', '2026-09-08用户确认：平台25元正确，线下24元应更正。HD029仅配置01:00至02:00晚休，线下额外扣早休0.5小时；平台算法及休息配置不变。'),
    }
    if n in notes:return notes[n]
    cause = f.get('差异原因', '')
    if any(word in cause for word in ['线下漏算', '线下漏发', '线下没有核算', '线下没算']) and not any(word in cause + x for word in ['线上', '平台', 'AI']):
        return ('业务确认线下漏算，平台无问题',
                '2026-09-08用户统一确认：业务明确标记线下漏算的记录，按平台无问题处理，转线下按平台结果补算；不再要求逐条确认正确金额或休息日资格。平台算法不变，不代表线下已完成补算。')
    if x == '6点之后没有夜班补贴':
        return ('HD005资格口径互相矛盾', '本行计07:00至08:00共3元；06:00至06:30休息不影响。与第46行同班次应享有表述冲突。')
    if x.startswith('应该是'):
        expected=float(x.replace('应该是',''))
        assert abs(c['amount']-expected)<0.011
        return ('平台符合业务明确金额', '平台金额已等于业务给定正确金额，旧线下差额应由业务登记更正。')
    if x == '保洁不享有夜班补贴':
        if r['source']['work_area'] == '东莞' and r['source']['position'] == '保洁' and c['amount'] == 0:
            return ('东莞保洁排除已按用户确认落实', '2026-09-07用户明确东莞保洁不论班次均不享有；最新核算0元，其他地区范围未扩展。')
        return ('保洁排除需核验适用地区', '本次明确确认的新增排除范围为东莞保洁。')
    if n in [338,342,343,344]:
        return ('业务确认线下漏算，平台无问题', '2026-09-08用户确认第338、342—344行平台无问题、线下漏算。东莞招聘、行政、HRBP这4条LB05各3元，合计12元，转线下补算；移出岗位资格待确认清单，不新增岗位排除或扩大其他人员确认范围。')
    if '1小时' in x and not (c['amount'] or 0):
        return ('已按1小时门槛不计发', '最新金额为0；业务反馈已由现有起点边界和新门槛覆盖。')
    if '班次为准' in x or '也是从7点开始' in x:
        return ('排班起点已修正', '最新起点不早于排班，金额已与旧线下一致；有异常标记时仍需核验考勤。')
    if n in [73,74,346,138]:return ('不足1小时已不计发', '最新为0元，符合实际打卡及门槛。')
    if x in ['6点-8点有夜班补贴','6点半-8点有夜班补贴','7点-8点应该有夜班补贴']:
        return ('早晨计发反馈待核对', '按排班及实际打卡取整计发；本条未命中明确线下漏算反馈，不自动扩大业务确认范围。')
    if n in [2,3]:return ('业务确认线下核算有误', '2026-09-08用户确认线下核算有误，结合原反馈登记为缺卡线下多发，转线下更正复核。平台仍缺有效打卡、金额未定，不将展示0解释为已算应发0元；不补造打卡或修改算法。')
    if not r['numeric_difference']:
        return ('当前金额已一致，勿扩展为整类班次排除', '该行新规则为0元；白班晚间是否一律不享有仍不是本行已证明的结论。')
    return ('仍需逐项核对', '保留业务原文，未据此自动更改平台规则。')

def write_review_csv(output):
    path=OUT/'night_shift_feedback_review_20260907.csv'
    with path.open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.writer(stream)
        writer.writerow(['飞书行号','地区','班次','岗位','出勤日期','班次时间','原始上班','原始下班','平台旧金额','平台最新金额','旧线下金额','差异原文','差异原因原文','梳理结论','依据及待确认事项','最新状态','原表行号'])
        for r in output['joined']:
            f=r['feedback'];s=r['source'];c=r['current']; conclusion,note=review_note(r)
            writer.writerow([f['sheet_row'],r['region'],s['shift_code'],s['position'],s['attendance_date'],s['shift_schedule'],s['raw_start'],s['raw_end'],f['平台金额'],c['amount'],s['amount'],f['差异'],f['差异原因'],conclusion,note,c['status'],s['source_row']])
    return path

def main():
    response = json.loads(subprocess.check_output([
        '/Users/zt27532/.hermes/node/bin/lark-cli', 'sheets', '+csv-get', '--spreadsheet-token',
        'PzaLszTE9hJQZpteZGAcBG0Qnlh',
        '--sheet-id', 'mLIRoK', '--range', 'A1:AD700', '--max-chars', '500000',
        '--as', 'user', '--format', 'json',
    ], text=True))
    assert response['ok']
    data = response['data']
    assert not data.get('has_more')
    parsed = list(csv.reader(io.StringIO(data['annotated_csv'])))
    header = parsed[0]
    header[0] = re.sub(r'^\[row=\d+\] ?', '', header[0])
    feedback = []
    for row in parsed[1:]:
        m = re.match(r'^\[row=(\d+)\] ?', row[0])
        assert m
        row[0] = row[0][m.end():]
        feedback.append({'sheet_row': int(m[1]), **dict(zip(header, row))})
    assert len(feedback) == 583
    history = json.loads((OUT / 'night_shift_202607_after_lb15.json').read_text())
    confirmed = {(r['region'], r['source_row']) for r in history['confirmed_offline_formula_details']}
    pending = {(r['region'], r['source_row']): r for r in history['details']}
    all_rows = {}
    cfg = load_night_shift_config('202607', required=False)
    for label, region, path in [('south','华南',DEFAULT_SOUTH),('east','华东',DEFAULT_EAST)]:
        people, grouped, offline, duplicates = _read_region(label, path)
        assert not duplicates
        platform, _, _ = _calculate(people, grouped, cfg)
        for key, source in offline.items():
            result = platform[key]
            all_rows[(region, source['source_row'])] = {
                'region': region, 'source': source, 'current': result,
                'numeric_difference': round((result['amount'] or 0) - source['amount'], 6),
                'confirmed_offline': (region,source['source_row']) in confirmed,
                'previous_pending': (region,source['source_row']) in pending,
            }
    joined = []
    for f in feedback:
        loc = f.get('线下原表定位','')
        m = re.search(r'[!！]\s*(\d+)\s*$',loc)
        assert m, (f['sheet_row'],loc)
        key = (f['地区'],int(m[1]))
        assert key in all_rows, key
        r = all_rows[key]
        assert f['工号'] == r['source']['employee_id']
        joined.append({**r,'feedback':f})
    remaining = [r for r in all_rows.values() if r['numeric_difference'] and not r['confirmed_offline']]
    grouped = defaultdict(list)
    for r in joined:
        f=r['feedback'];grouped[(f.get('差异',''),f.get('差异原因',''))].append(r)
    summary=[]
    for (x,y),rows in grouped.items():
        summary.append({'feedback':x,'cause':y,'count':len(rows),
            'currently_equal':sum(not r['numeric_difference'] for r in rows),
            'confirmed_offline':sum(r['confirmed_offline'] for r in rows),
            'remaining':sum(bool(r['numeric_difference']) and not r['confirmed_offline'] for r in rows),
            'sheet_rows':[r['feedback']['sheet_row'] for r in rows],
            'shifts':dict(Counter(r['current']['shift_code'] for r in rows))})
    output={'revision':data.get('revision'),'range':data['actual_range'],
        'total':len(all_rows),'numeric_mismatches':sum(bool(r['numeric_difference']) for r in all_rows.values()),
        'remaining_count':len(remaining),'confirmed_count':len(confirmed),
        'remaining_in_sheet':sum(bool(r['numeric_difference']) and not r['confirmed_offline'] for r in joined),
        'summary':summary,'joined':joined,'remaining':remaining}
    path=OUT/'night_shift_feedback_review_20260907.json'
    path.write_text(json.dumps(output,ensure_ascii=False,indent=2,default=str)+'\n')
    write_review_csv(output)
    print(json.dumps({k:v for k,v in output.items() if k not in ['joined','remaining']},ensure_ascii=False))

if __name__=='__main__':
    main()

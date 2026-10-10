"""Portable, fail-closed payroll skill adapter. No platform services or network."""
import argparse
import calendar
import importlib
import json
import math
import re
from copy import deepcopy
from types import SimpleNamespace
from collections import Counter
from dataclasses import asdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = json.loads((ROOT / 'references/input-contract.json').read_text())
SUBJECT = SPEC['subject']


def number(value):
    if isinstance(value, bool) or value is None or value == '':
        raise ValueError('必须提供数值，不能用空值代替零')
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError('必须为有限非负数')
    return result


def run(payload, mode='calculate'):
    if not isinstance(payload, dict):
        return {'status':'blocked','issues':[{'code':'INVALID_INPUT','message':'顶层必须为JSON对象'}],'results':[]}
    payload = deepcopy(payload)
    issues = []
    def issue(code, path, message):
        issues.append({'code': code, 'path': path, 'message': message, 'action': '补充或修正该项，保留来源后重新执行'})
    def require(row, fields, path):
        for field in fields:
            if field not in row or row[field] is None or row[field] == '':
                issue('MISSING_FIELD', path + '.' + field, '缺少必需字段：' + field)
    month = payload.get('month', '')
    try:
        if not isinstance(month, str) or len(month) != 6: raise ValueError()
        first = date(int(month[:4]), int(month[4:]), 1)
        last = date(first.year, first.month, calendar.monthrange(first.year, first.month)[1])
    except (ValueError, TypeError):
        return {'status': 'blocked', 'issues': [{'code': 'INVALID_MONTH', 'path': 'month', 'message': '月份须为有效的YYYYMM'}], 'results': []}
    employees = payload.get('employees', [])
    if not isinstance(employees, list) or not employees:
        return {'status': 'blocked', 'issues': [{'code': 'MISSING_SOURCE', 'path': 'employees', 'message': '请提供月考勤或员工核算主表'}], 'results': []}
    sources = payload.get('sources', {})
    if not isinstance(sources, dict):
        return {'status':'blocked','issues':[{'code':'INVALID_SOURCE','message':'sources必须为对象'}],'results':[]}
    for key in ('employees','daily','housing','abandonment_roster','seniority_roster','temperatures','temperature_exclusions','offline'):
        if key in payload and (not isinstance(payload[key],list) or any(not isinstance(r,dict) for r in payload[key])):
            return {'status':'blocked','issues':[{'code':'INVALID_TABLE','path':key,'message':'数据表必须为对象数组'}],'results':[]}
    if any(not isinstance(v,dict) for v in sources.values()):
        return {'status':'blocked','issues':[{'code':'INVALID_SOURCE','message':'每个来源须为对象'}],'results':[]}
    if any(not isinstance(e.get('工号'),str) or not e['工号'].strip() for e in employees):
        return {'status':'blocked','issues':[{'code':'INVALID_ID','message':'工号必须为非空文本，保留前导零'}],'results':[]}
    needed = {'employees'}
    for emp in employees:
        if not isinstance(emp, dict):
            issue('INVALID_ROW', 'employees', '员工记录必须为对象'); continue
        area = emp.get('工作地区')
        needed.update(SPEC['sources'])
        if SUBJECT == 'canbu' and area == '东莞': needed.add('daily')
        if SUBJECT == 'gonglingjiang' and emp.get('二级部门名称') == '第四纵队': needed.add('seniority_roster')
    if mode == 'reconcile': needed.add('offline')
    for key in sorted(needed):
        meta = sources.get(key, {})
        rows = payload.get(key)
        if not isinstance(rows, (list, dict)):
            issue('MISSING_SOURCE', key, '缺少数据源：' + SPEC['source_labels'].get(key, key)); continue
        if meta.get('month') != month or not meta.get('evidence') or meta.get('complete') is not True:
            issue('UNCONFIRMED_COVERAGE', 'sources.' + key, '请提供来源及核算月份，并确认覆盖本次全部人员和期间；不得由AI猜测完整性')
        expected_status = 'provided' if rows else 'confirmed_empty'
        if meta.get('status') != expected_status:
            issue('UNCONFIRMED_EMPTY', 'sources.' + key, '非空数据标记provided；空名单须由数据提供方确认无记录后标记confirmed_empty')
    ids = [e.get('工号') for e in employees if isinstance(e, dict)]
    names = {e.get('工号'): e.get('姓名') for e in employees if isinstance(e, dict)}
    for ident, count in Counter(ids).items():
        if count > 1: issue('DUPLICATE_EMPLOYEE', 'employees', '工号重复：' + str(ident))
    numeric_fields = set(SPEC['numeric_fields']) | {'旷工时数','排休请假时数','排休请假天数','入离职缺勤时数'}
    for i, emp in enumerate(employees):
        if not isinstance(emp, dict): continue
        path = f'employees[{i}]'
        require(emp, SPEC['fields'] + SPEC['regional_fields'].get(emp.get('工作地区'), []), path)
        if not isinstance(emp.get('工号'), str) or not emp.get('工号', '').strip(): issue('INVALID_ID', path, '工号必须为非空文本，保留前导零')
        if emp.get('考勤月份') != month: issue('MONTH_MISMATCH', path, '员工考勤月份与本次月份不一致')
        if emp.get('工作地区') not in ('东莞','嘉善','义乌','晋江'): issue('RULE_SCOPE', path, '地区不在此规则快照的自动核算范围，请先确认适用口径')
        if SUBJECT=='gaowen_butie' and emp.get('办公地点是否有空调') not in ('是','否'):
            issue('INVALID_ENUM',path+'.办公地点是否有空调','须明确填写是或否')
        for field in numeric_fields.intersection(emp):
            try: emp[field] = number(emp[field])
            except (ValueError, TypeError): issue('INVALID_NUMBER', path + '.' + field, '字段必须为有限非负数；缺失不能自动补零')
        for field in ('入职日期', '最后工作日'):
            if field not in emp and field in SPEC.get('nullable_fields', []): issue('MISSING_FIELD', path + '.' + field, '必须提供字段；确认在职时最后工作日可填null')
            if emp.get(field):
                try: emp[field] = date.fromisoformat(emp[field])
                except (ValueError, TypeError): issue('INVALID_DATE', path + '.' + field, '日期须为YYYY-MM-DD')
        hire, leave = emp.get('入职日期'), emp.get('最后工作日')
        if isinstance(hire,date) and isinstance(leave,date) and hire > leave: issue('DATE_ORDER',path,'入职日期晚于最后工作日')
        scheduled, actual = emp.get('排班天数'), emp.get('实际在职工作日天数')
        if isinstance(scheduled,(int,float)):
            if scheduled <= 0 or scheduled > last.day: issue('INVALID_SCHEDULE',path,'排班天数须大于0且不超过当月天数')
            if isinstance(actual,(int,float)) and actual > scheduled: issue('INVALID_ATTENDANCE',path,'实际在职工作日天数超过排班天数')
    daily_by_id = {ident: [] for ident in ids}
    seen_days = set()
    for i, row in enumerate(payload.get('daily', [])):
        path = f'daily[{i}]'
        require(row, ['工号','出勤日期'] + SPEC.get('daily_fields', []), path)
        ident = row.get('工号')
        if ident not in names: issue('UNMATCHED_ID', path, '日考勤工号不在主表；请按核算范围筛选并记录筛选依据'); continue
        if row.get('姓名') and row['姓名'] != names[ident]: issue('NAME_MISMATCH', path, '日考勤姓名与工号不一致')
        try:
            day = date.fromisoformat(row['出勤日期'])
            if not first <= day <= last: raise ValueError()
        except (KeyError,ValueError,TypeError): issue('INVALID_DATE',path,'出勤日期缺失、无效或不属本月'); continue
        row['出勤日期'] = day
        key = (ident, day)
        if key in seen_days: issue('DUPLICATE_DAY', path, '同一员工同一天重复；多班次必须先确认合并口径，不可直接累加')
        seen_days.add(key)
        for field in ('正班时数','刷卡加班','实际上班时数'):
            if field in row:
                try: row[field] = number(row[field])
                except (ValueError,TypeError): issue('INVALID_NUMBER',path+'.'+field,'工时缺失或无效')
        for field in SPEC.get('daily_numeric_fields', []):
            if field in row:
                try: row[field] = number(row[field])
                except (ValueError,TypeError): issue('INVALID_NUMBER',path+'.'+field,'逐日请假或缺勤工时须为有限非负数，不能用缺失代替零')
        for field in SPEC.get('daily_nullable_fields', []):
            if field not in row: issue('MISSING_FIELD',path+'.'+field,'缺少字段；源表确认缺卡可使用null，缺列不能推定缺卡')
        for field in ('上班一','下班一'):
            if row.get(field) not in (None,''):
                match=re.fullmatch(r'(\d{1,2}):(\d{2})(?::(\d{2}))?',str(row[field]))
                if not match or int(match[1])>23 or int(match[2])>59 or (match[3] and int(match[3])>59):
                    issue('INVALID_TIME',path+'.'+field,'打卡时间格式错误；不得当作缺卡归零')
        for field in ('工作地区','岗位名称'):
            if row.get(field) and row[field] != next(e for e in employees if e['工号']==ident).get(field):
                issue('EMPLOYEE_SCOPE_CONFLICT',path+'.'+field,'月日考勤地区或岗位不同，请确认转岗/跨地区期间，不能按单月单岗自动合并')
        daily_by_id[ident].append(row)
    for emp in employees:
        ident = emp.get('工号')
        employee_needs_daily = 'daily' in SPEC['sources'] or (SUBJECT=='canbu' and emp.get('工作地区')=='东莞')
        if employee_needs_daily and not daily_by_id.get(ident): issue('MISSING_EMPLOYEE_DAILY',str(ident),'缺少该员工日考勤；不能以空集合推定零出勤')
        if SUBJECT == 'quanqinjiang' and len(daily_by_id.get(ident, [])) != last.day:
            issue('INCOMPLETE_CALENDAR',str(ident),'请补齐全月逐日工作状态，避免按普通周末猜测入离职期间排班')
        if SUBJECT == 'waisu_butie' and any(row.get('工号') == ident and row.get('退宿时间') for row in payload.get('housing', [])):
            from vendor.engines.waisu_butie import WaiSuBuTieEngine
            if WaiSuBuTieEngine()._absence_hours(emp, emp.get('工作地区','')) >= 56:
                for index, row in enumerate(daily_by_id.get(ident, [])):
                    require(row, SPEC.get('checkout_daily_fields', []), f'daily[{ident}][{index}]')
    for source in ('housing','abandonment_roster','seniority_roster'):
        seen = set()
        for i, row in enumerate(payload.get(source, [])):
            path=f'{source}[{i}]'
            require(row,['工号','姓名'],path)
            ident=row.get('工号')
            if ident not in names or row.get('姓名') != names.get(ident): issue('ROSTER_MISMATCH',path,'名单工号或姓名与主表不一致')
            if source != 'housing' and ident in seen: issue('DUPLICATE_ROSTER',path,'名单重复工号')
            seen.add(ident)
            if source == 'housing':
                require(row,['入住时间'],path)
                if '退宿时间' not in row: issue('MISSING_FIELD',path,'须提供退宿时间，确认尚未退宿可填null')
                for field in ('入住时间','退宿时间'):
                    if row.get(field):
                        try: row[field]=date.fromisoformat(row[field])
                        except (ValueError,TypeError): issue('INVALID_DATE',path+'.'+field,'住宿日期格式无效')
                if isinstance(row.get('入住时间'),date) and isinstance(row.get('退宿时间'),date) and row['入住时间'] > row['退宿时间']: issue('DATE_ORDER',path,'退宿早于入住')
    intervals={}
    for row in payload.get('housing',[]):
        start,end=row.get('入住时间'),row.get('退宿时间') or date.max
        if isinstance(start,date) and isinstance(end,date):
            for a,b in intervals.get(row.get('工号'),[]):
                if start < b and a < end: issue('HOUSING_OVERLAP','housing','同一员工住宿区间重叠，请确认并去重')
            intervals.setdefault(row.get('工号'),[]).append((start,end))
    if SUBJECT == 'gaowen_butie':
        for i,row in enumerate(payload.get('temperatures', [])):
            require(row,['班次日期','测温班次','测温网点','测温温度'],f'temperatures[{i}]')
            try:
                d=date.fromisoformat(row['班次日期']); t=number(row['测温温度'])
                if not first <= d <= last or row['测温班次'] not in ('白班','夜班'): raise ValueError()
            except (KeyError,ValueError,TypeError): issue('INVALID_TEMPERATURE',f'temperatures[{i}]','测温日期、班次或温度无效')
    config=payload.get('night_config',{})
    if SUBJECT == 'yeban_butie':
        if not isinstance(config,dict): config={}
        if any(e.get('工作地区')=='晋江' for e in employees) and config.get('jinjiang_list_confirmed') is not True:
            issue('MISSING_ROSTER_CONFIRMATION','night_config','确认本月晋江额外排除名单；没有也需明确确认')
        if 'effective_shift_breaks' in config: issue('INVALID_CONFIG','night_config','请只使用shift_breaks，避免两套配置互相覆盖')
        if not isinstance(config.get('shift_breaks'),list) or any(not isinstance(r,dict) for r in config.get('shift_breaks',[])):
            issue('INVALID_CONFIG','night_config.shift_breaks','必须为配置对象数组'); config['shift_breaks']=[]
        if not isinstance(config.get('jinjiang_exclusions',[]),list) or any(not isinstance(r,dict) for r in config.get('jinjiang_exclusions',[])):
            issue('INVALID_CONFIG','night_config.jinjiang_exclusions','必须为名单对象数组'); config['jinjiang_exclusions']=[]
        for row in config.get('jinjiang_exclusions',[]):
            require(row,['employee_id','employee_name','reason','start_date'],'night_config.jinjiang_exclusions')
            if row.get('employee_id') not in names or names.get(row.get('employee_id'))!=row.get('employee_name'):
                issue('ROSTER_MISMATCH','night_config.jinjiang_exclusions','排除名单工号姓名与本次主表不一致')
            try:
                start=date.fromisoformat(row['start_date']);end=date.fromisoformat(row['end_date']) if row.get('end_date') else date.max
                if start>end: raise ValueError()
            except (KeyError,ValueError,TypeError): issue('INVALID_DATE','night_config.jinjiang_exclusions','名单生效/失效日期错误')
        seen_shifts=set()
        for row in config.get('shift_breaks',[]):
            code=row.get('shift_code')
            if code in seen_shifts: issue('DUPLICATE_SHIFT','night_config',f'班次重复：{code}')
            seen_shifts.add(code)
            require(row,['shift_code','effective_start_date'],'night_config.shift_breaks')
            try: date.fromisoformat(row['effective_start_date'])
            except (KeyError,ValueError,TypeError): issue('INVALID_DATE','night_config.shift_breaks','班次生效日期错误')
            periods=row.get('break_segments',row.get('break_periods'))
            if not isinstance(periods,list): issue('INVALID_BREAKS',str(code),'休息段必须为数组')
            if 'break_periods' not in row and 'break_segments' not in row: issue('MISSING_BREAKS',str(code),'需提供休息段；确认无休息时才填空数组')
    if issues: return {'status':'blocked','subject':SUBJECT,'issues':issues,'results':[]}
    supplemental_audit = {}
    exclusion_records = []
    if SUBJECT in ('waisu_butie', 'gaowen_butie'):
        from vendor.supplemental_inputs import prepare_supplemental_inputs
        from vendor.temperature_sites import prepare_temperature_sites
        loader = SimpleNamespace(
            monthly=SimpleNamespace(rows=employees),
            daily=SimpleNamespace(rows=payload.get('daily', [])),
            housing=SimpleNamespace(rows=payload.get('housing', [])),
            temperature=SimpleNamespace(rows=payload.get('temperatures', [])),
            temperature_exclusions=SimpleNamespace(rows=payload.get('temperature_exclusions', [])),
            supplemental_raw={'temperature':payload.get('temperatures', []), 'housing':payload.get('housing', [])},
            _month_digits=lambda value: re.sub(r'\D', '', str(value)),
        )
        confirmation = {key:'none' for key in ('housing','temperature_exclusions')
                        if sources.get(key, {}).get('status') == 'confirmed_empty'}
        for i, row in enumerate(payload.get('temperature_exclusions', [])):
            require(row, ['工号','姓名','工作地区','不享有原因','生效日期'], f'temperature_exclusions[{i}]')
            if '结束日期' not in row: issue('MISSING_FIELD',f'temperature_exclusions[{i}]','须提供结束日期，持续生效可填null')
        if not issues:
            try:
                supplemental_audit.update(prepare_supplemental_inputs(loader, [SUBJECT], confirmation))
                if SUBJECT == 'gaowen_butie':
                    supplemental_audit.update(prepare_temperature_sites(loader, payload.get('temperature_site_mapping', {})))
                    exclusion_records = loader.validated_temperature_exclusions
            except ValueError as exc:
                detail = getattr(exc, 'detail', {})
                issue(detail.get('code','INVALID_SUPPLEMENTAL_INPUT'), SUBJECT, str(exc))
        if issues: return {'status':'blocked','subject':SUBJECT,'issues':issues,'results':[]}
    if mode == 'validate':
        return {'status':'validated','subject':SUBJECT,'rule_version':SPEC['rule_version'],'issues':[],'results':[]}
    mod=importlib.import_module('vendor.engines.'+SUBJECT)
    engine=getattr(mod,SPEC['engine'])(**({'temperature_records':payload.get('temperatures',[]),'exclusion_records':exclusion_records} if SUBJECT=='gaowen_butie' else {}))
    results=[]
    for emp in employees:
        ident=emp['工号']; kwargs={}
        if SUBJECT in ('canbu','waisu_butie','quanqinjiang','yeban_butie','gaowen_butie'): kwargs['daily_attendance']=daily_by_id.get(ident,[])
        if SUBJECT=='waisu_butie':
            kwargs.update(housing_records=[r for r in payload['housing'] if r['工号']==ident],abandoned_employee_ids={r['工号'] for r in payload['abandonment_roster']})
        if SUBJECT=='gonglingjiang': kwargs['hrbp_list']=[r['工号'] for r in payload.get('seniority_roster',[])]
        if SUBJECT=='yeban_butie': kwargs['config']=config
        try:
            result=asdict(engine.calculate(emp,**kwargs))
            # Provisional engine outputs must never be represented as verified pay.
            details=result['details']; exceptions=details.get('exceptions',[])
            reviews=[r for r in details.get('daily_results',[]) if r.get('status') in ('manual_review','calculated_review','calculated_pending','pending_rule') or r.get('reason_code') in ('no_matching_temperature','measurement_site_unresolved','attendance_shift_unresolved')]
            if reviews: result['validation_issues']=[{'code':r.get('reason_code'),'date':r.get('attendance_date'),'message':'补齐对应日期的配置或数据后重新核算'} for r in reviews]
            needs_review=bool(exceptions or reviews or any(w in str(result['warnings']) for w in ('缺','待','复核','异常','未配置','未提供')))
            result['status']='needs_review' if needs_review else 'calculated'
            if needs_review: result['provisional_amount']=result.pop('amount'); result['amount']=None
            results.append(result)
        except Exception as exc:
            results.append({'employee_id':ident,'employee_name':emp['姓名'],'status':'blocked','amount':None,'issues':[{'code':'ENGINE_ERROR','message':str(exc)}]})
    report={'subject':SUBJECT,'month':month,'rule_version':SPEC['rule_version'],'status':'needs_review' if any(r['status']!='calculated' for r in results) else 'calculated','results':results,'issues':[], 'supplemental_audit':supplemental_audit}
    if mode=='reconcile':
        offline=payload.get('offline',[]); counts=Counter(r.get('工号') for r in offline)
        index={r.get('工号'):r for r in offline}; comparison=[]
        for result in results:
            ident=result['employee_id']; row=index.get(ident)
            entry={'employee_id':ident,'employee_name':result['employee_name'],'calculated_amount':result['amount'],'offline_amount':None,'difference':None}
            if counts[ident]>1: entry['status']='duplicate_offline'
            elif row is None: entry['status']='missing_offline'
            elif row.get('姓名')!=result['employee_name']: entry['status']='identity_mismatch'
            elif row.get('考勤月份')!=month or row.get('科目')!=SPEC['name']: entry['status']='scope_mismatch'
            else:
                try:
                    amount=number(row.get('金额'))
                    money=Decimal(str(row.get('金额')))
                    if money != money.quantize(Decimal('.01')): raise ValueError('线下金额须保留到分')
                except (ValueError,TypeError): entry['status']='invalid_offline_amount'
                else:
                    entry['offline_amount']=amount
                    if result['status']!='calculated': entry['status']='not_verifiable'
                    else:
                        diff=Decimal(str(result['amount']))-Decimal(str(amount))
                        entry['difference']=float(diff.quantize(Decimal('.01'), rounding=ROUND_HALF_UP))
                        entry['status']='match' if diff==0 else 'amount_difference'
            comparison.append(entry)
        for ident,row in index.items():
            if ident not in names: comparison.append({'employee_id':ident,'status':'duplicate_offline' if counts[ident]>1 else 'offline_only','offline_amount':row.get('金额')})
        report['comparison']=comparison
        report['status']='verified' if comparison and all(r['status']=='match' for r in comparison) else 'differences_or_unverifiable'
    return report


def main():
    p=argparse.ArgumentParser(description='先验证数据，再核算或核验线下金额')
    p.add_argument('input',type=Path);p.add_argument('--mode',choices=['validate','calculate','reconcile'],default='calculate');p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    try:
        payload=json.loads(args.input.read_text(encoding='utf-8'))
        result=run(payload, args.mode)
        if args.mode=='validate': result.pop('results',None)
    except (ValueError,TypeError,KeyError,ImportError) as exc: result={'status':'blocked','issues':[{'code':'INVALID_INPUT','message':str(exc)}],'results':[]}
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str,allow_nan=False),encoding='utf-8')
    print(json.dumps({'status':result['status'],'output':str(args.output)},ensure_ascii=False))

if __name__=='__main__': main()

"""Versioned standard-currency estimates. These are never payment instructions."""
from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import datetime, timedelta
import hashlib
import json
from math import isfinite, trunc
from itertools import product
from pathlib import Path
import re

from .models import add_months, as_date, yyyymm
from .recruitment_draft_sources import text, digest
from .recruitment_import_validation import (
    _normalize_offer_channel, _channel_notes, _domestic_holiday_exclusion_days, DOMESTIC_HOLIDAY_RANGES,
    _classify_overseas_country, _is_domestic_location, _is_uk_location,
)

RULE_BYTES = Path(__file__).with_name('recruitment_rules.json').read_bytes()
CATALOG = json.loads(RULE_BYTES)
RULE_HASH = hashlib.sha256(RULE_BYTES).hexdigest()
ENGINE_VERSION = '4.25'
NODES = ('入职满一个月', '入职满三个月', '入职满六个月', '转正')
EUROPE = ('德国','捷克','英国','法国','荷兰','意大利','西班牙','葡萄牙','奥地利','瑞士','比利时',
          '卢森堡','丹麦','瑞典','挪威','芬兰','爱尔兰','波兰','匈牙利','罗马尼亚','germany','czech',
          'united kingdom','england','france','netherlands','italy','spain','poland','belgium','europe')
NO_RECRUIT = {'猎头','猎头推荐','猎头推荐入职','外包转正式','体系外转体系内','人员调动',
              '跨主体调动','跨体系调动','内部调动','体系内调动','调动'}
FULL_CHANNELS = {'招聘网站','网站招聘','社招','社会招聘','自主招聘','自主开发','广告','招聘会','直接招聘'}
CORE_FIELDS = {'入职日期','候选人入职时间','标签分类','职级','ABC类别','奖金地区类型'}
CURRENCY_FIELDS = {'二级组织','三级组织','四级组织','五级组织','工作地'}
REFERRAL_QUALIFICATION_FIELDS = {'推荐人职级','推荐人职位','招聘渠道','是否二次入职','推荐人是否直接/间接上级','推荐人与候选人上下级关系',
    '直线经理工号','直接上级工号','间接上级1工号','间接上级2工号','间接上级3工号','间接上级4工号'}
RECRUIT_FIELDS = CORE_FIELDS | {'招聘渠道','招聘启动日期','周期剔除天数','上次离职日期','原计划入职日期','二次入职执行口径'}


def number(value):
    try:
        result = Decimal(str(value).replace(',', ''))
        return result if result.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def money(value):
    return float(Decimal(str(value)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP))


def present(value):
    return text(value) not in {'', '-', '无', '无工号', 'N/A'}


def grade_level(value):
    match = re.fullmatch(r'[PM](\d+)(?:-\d+)?', text(value).upper())
    return int(match.group(1)) if match else None


def country_currency(values):
    if values.get('标签分类') == '国内':
        return '人民币', '中国大陆'
    org = ' '.join(text(values.get(f)) for f in ('二级组织','三级组织','四级组织','五级组织'))
    adopted = org if _classify_overseas_country(org) else text(values.get('工作地'))
    if _is_uk_location(adopted) or any(token in adopted.lower() for token in EUROPE):
        return '欧元', adopted
    if _classify_overseas_country(adopted):
        return '美元', adopted
    return '', adopted


def lookup(row, kind):
    v = row['values']; version = row['rule']['version']
    category = text(v.get('ABC类别')).replace('类','').replace('C1','C')
    level = grade_level(v.get('职级'))
    if version == 'unresolved' or level is None:
        return None
    label = v.get('标签分类'); region = label if kind == 'recruitment' else v.get('奖金地区类型')
    if version == '2026-07':
        return next((dict(s, scope='集团统一', source=f"2026年7月制度第{s['page']}页")
                     for s in CATALOG['standards'] if s['kind']==kind and s['region']==region
                     and s['category']==category and s['minimum']<=level<=s['maximum']), None)
    grade = text(v.get('职级')).upper()
    if kind == 'recruitment':
        categories = {category+'类'}
        if label == '海外' and category == 'C': categories = {'C1类'}
        candidates = [s for s in CATALOG['legacyRecruitment'] if s['region']==region and s['category'] in categories]
    else:
        scope = row['rule'].get('specialScope') or '集团统一'
        special_region = scope if scope != '集团统一' else region
        categories = {category+'类', category}
        if scope=='集团统一' and label=='海外' and category=='C': categories.add('C1类')
        candidates = [s for s in CATALOG['legacyReferral'] if s['scope']==scope and s['region_type']==special_region and s['category'] in categories]
    exact = next((s for s in candidates if s['grade']==grade), None)
    if exact is None and '-' not in grade:
        matches = [s for s in candidates if s['grade'].split('-')[0]==grade]
        signatures = {json.dumps({k:v for k,v in s.items() if k!='grade'},sort_keys=True,ensure_ascii=False) for s in matches}
        if len(signatures)==1: exact=matches[0]
    if exact is None:
        if kind=='recruitment':
            from .recruitment_business_basis import legacy_person_standard
            ratios=([.2,0,0,.8] if category in {'A','B'} else [.5,0,0,.5]) if label=='国内' else ([.3,.3,.4,0] if category=='A' else [.3,.7,0,0] if category=='B' else [.5,.5,0,0])
            return legacy_person_standard(row,candidates,ratios)
        return None
    result = dict(exact, source=exact.get('source','已保存旧版规则库'))
    if kind == 'referral':
        result['ratios'] = [exact['ratio_1m'],exact['ratio_3m'],exact['ratio_6m'],exact['ratio_probation']]
    elif label == '国内':
        result['ratios'] = [.2,0,0,.8] if category in {'A','B'} else [.5,0,0,.5]
    else:
        result['ratios'] = [.3,.3,.4,0] if category=='A' else [.3,.7,0,0] if category=='B' else [.5,.5,0,0]
    return result


def observed_values(row, field, *, include_empty=False):
    values=[row['values'].get(field)]
    values.extend(value for c in row.get('conflicts',[]) if c['field']==field for value in c['values'])
    return list(dict.fromkeys(v for v in values if include_empty or present(v)))


def recipient_conflict_fields(row, prefix):
    fields=set(row.get('unresolvedFields',[])) & {prefix+'工号',prefix+'人员状态',prefix+'最后工作日'}
    status=prefix+'人员状态'
    choices=observed_values(row,status,include_empty=True)
    # Probation and regular employment have the same recipient eligibility.
    # Keep the source conflict itself, and retain unknown or departed choices.
    if len(choices)>1 and all(text(v) in {'正式','正式在职','试用','试用在职','在职'} for v in choices):
        fields.discard(status)
    return fields


def uses_previous_exit(row):
    if row['rule']['version']=='legacy': return False
    if row['values'].get('是否二次入职')=='是': return True
    channels=observed_values(row,'招聘渠道') if '招聘渠道' in row.get('unresolvedFields',[]) else [row['values'].get('招聘渠道')]
    return any(_normalize_offer_channel(v,row['values'].get('其他渠道'))[0] in {'二次入职','返聘'} for v in channels)


def referrer_role_exclusion(values):
    level=grade_level(values.get('推荐人职级'));position=text(values.get('推荐人职位'))
    if level is not None and level>=4 or '招聘' in position or 'HRBP' in position.upper():return True
    return False if level is not None and position else None


def material_conflicts(row,kind):
    """Only unresolved choices used by this award block its calculation.

    Preserve all observed differences. Grade alternatives can be ignored only
    when each resolves to the same complete standard, cycle and installments.
    Unknown standards or other unresolved lookup inputs remain blocking.
    """
    unresolved=set(row.get('unresolvedFields',[]))
    fields=unresolved & (RECRUIT_FIELDS if kind=='recruitment' else CORE_FIELDS | REFERRAL_QUALIFICATION_FIELDS)
    country_fields=sorted(unresolved & CURRENCY_FIELDS)
    if country_fields and (row['values'].get('标签分类')!='国内' or '标签分类' in unresolved):
        choices=[observed_values(row,f,include_empty=True) for f in country_fields]
        combinations=1
        for values in choices:combinations*=len(values)
        currencies={country_currency({**row['values'],**dict(zip(country_fields,values))})[0]
                    for values in product(*choices)} if 0<combinations<=256 else set()
        if len(currencies)!=1 or '' in currencies:fields.update(country_fields)
    if kind=='referral':
        qualification=sorted(unresolved & {'推荐人职级','推荐人职位'})
        for field in qualification:
            choices=observed_values(row,field,include_empty=True)
            known=all(grade_level(value) is not None if field=='推荐人职级' else present(value) for value in choices)
            others=[f for f in qualification if f!=field]
            contexts=product(*(observed_values(row,f,include_empty=True) for f in others))
            equivalent=True
            for context in contexts:
                values={**row['values'],**dict(zip(others,context))}
                outcomes={referrer_role_exclusion({**values,field:value}) for value in choices}
                if len(outcomes)!=1 or None in outcomes and not known:equivalent=False;break
            if equivalent:fields.discard(field)
        fields.update(unresolved & {'推荐人工号','推荐人姓名'})
    if not uses_previous_exit(row): fields.discard('上次离职日期')
    if '职级' in fields and not unresolved & (CORE_FIELDS-{'职级'}):
        grades=observed_values(row,'职级')
        signatures=[]
        for grade in grades:
            standard=lookup({**row,'values':{**row['values'],'职级':grade}},kind)
            if standard is None: break
            signatures.append((standard['amount'],standard.get('cycle'),tuple(standard['ratios']),standard.get('currency'),standard.get('scope')))
        if len(grades)>1 and len(signatures)==len(grades) and len(set(signatures))==1:
            fields.remove('职级')
    return fields


def cycle(values, standard, version, *, exclusion_basis=None):
    start, hire = as_date(values.get('招聘启动日期')), as_date(values.get('入职日期') or values.get('候选人入职时间'))
    issues=[]; result={'standardDays':standard, 'actualDays':None,'holidayDays':0,'exclusionDays':None,'factor':None,'exempt':False}
    exemption = text(values.get('周期豁免依据') or values.get('管培生资格依据'))
    if version=='2026-07' and values.get('标签分类')=='国内' and exemption:
        original = as_date(values.get('原计划入职日期'))
        approved_list = values.get('管培生已批名单资格')=='是'
        complete = (values.get('应届校招')=='是' and values.get('延后入职原因') in {'毕业离校','公司集训'}
                    and hire and original and 0 <= (hire-original).days <= 15)
        if complete or approved_list:
            result.update(factor=1.0, exempt=True, basis=exemption)
            return result, issues
        issues.append('管培生免周期资格待核')
    standard_days = number(standard)
    if (not start or not hire or standard_days is None or standard_days <= 0
            or not isfinite(float(standard_days))):
        return result, issues+['招聘起止日期或标准周期待核']
    raw=(hire-start).days
    if raw < 0:
        exclusion = number(values.get('周期剔除天数')) if present(values.get('周期剔除天数')) else Decimal(0)
        if exclusion is None or exclusion < 0 or not isfinite(float(exclusion)):
            return result, issues+['周期剔除天数或免周期资格待核']
        snapshot = number(values.get('负周期确认剔除天数'))
        # Existing legacy confirmations predate the exclusion snapshot.
        old_confirmation = ('负周期确认剔除天数' not in values
                            and version == 'legacy' and raw == -1 and exclusion == 0)
        confirmed = (version in {'legacy', '2026-07'}
                     and text(values.get('负周期确认依据'))
                     and as_date(values.get('负周期确认启动日期')) == start
                     and as_date(values.get('负周期确认入职日期')) == hire
                     and (snapshot == exclusion or old_confirmation))
        if not confirmed:
            return result, issues+['招聘起止日期或标准周期待核']
        if exclusion>0 and not values.get('周期剔除依据') and not exclusion_basis:
            issues.append('周期剔除依据待核')
        actual_days = Decimal(raw)-exclusion
        actual = float(actual_days)
        warning = (f'按原日期核算：招聘启动日 {start:%Y-%m-%d}，入职日 {hire:%Y-%m-%d}，'
                   f'剔除 {float(exclusion):g} 天，实际招聘周期 {actual:g} 天。')
        result.update(actualDays=actual, exclusionDays=float(exclusion),
                      factor=round(max(.3,min(1.3,1-trunc((actual_days-standard_days)/10)*.1)),4),
                      warning=warning, confirmationBasis=text(values['负周期确认依据']))
        if exclusion_basis:result['exclusionBasis']=exclusion_basis
        return result, issues
    holidays=0
    if values.get('标签分类')=='国内':
        if any(year not in DOMESTIC_HOLIDAY_RANGES for year in range(start.year,hire.year+1)):
            issues.append('招聘周期缺少对应年度假期配置')
        holidays=_domestic_holiday_exclusion_days(start,hire)
    raw_exclusion=values.get('周期剔除天数')
    exclusion=number(raw_exclusion) if present(raw_exclusion) else Decimal(holidays)
    if exclusion is None or exclusion<0 or exclusion>raw:
        return result, issues+['周期剔除天数或免周期资格待核']
    # A historical/approved total is one adopted value, never stacked with holiday days.
    if present(raw_exclusion) and exclusion>0 and float(exclusion)!=holidays:
        if not values.get('周期剔除依据') and not exclusion_basis:
            issues.append('周期剔除依据待核')
    if exclusion_basis:result['exclusionBasis']=exclusion_basis
    actual=raw-float(exclusion)
    result.update(actualDays=actual,holidayDays=holidays,exclusionDays=float(exclusion),
                  factor=round(max(.3,min(1.3,1-trunc((actual-standard)/10)*.1)),4))
    return result, issues


def rehire_basis(values, version):
    """Explain only the dated case where the specific and general terms agree.

    The <=12-month 0%/40% discrepancy still needs a genuine rule decision.
    This is derived evidence, never a fabricated manual approval field.
    """
    if version!='2026-07':return None
    hire=as_date(values.get('入职日期') or values.get('候选人入职时间'))
    previous=as_date(values.get('上次离职日期'))
    if not previous or not hire or hire<=add_months(previous,12):return None
    previous_date=previous.strftime('%Y-%m-%d');hire_date=hire.strftime('%Y-%m-%d')
    return {'previousExitDate':previous_date,'hireDate':hire_date,
            'twelveMonthDate':add_months(previous,12).strftime('%Y-%m-%d'),'factor':.4,
            'description':f'上次离职 {previous_date}，本次入职 {hire_date}，间隔超过12个月；招聘渠道比例为40%。',
            'source':'2026年7月制度第2、3页招聘专项条款及第8页通用说明，均按40%计算。'}


def channel(values, version):
    raw=text(values.get('招聘渠道'))
    if raw=='其他':return 0,[],'其他'
    normalized, uncertain=_normalize_offer_channel(raw, values.get('其他渠道'), _channel_notes(values))
    value=normalized or raw
    rehire=raw in {'二次入职','返聘'} or value in {'二次入职','返聘'} or values.get('是否二次入职')=='是'
    if rehire:
        if version=='legacy': return .4, [], '二次入职'
        hire=as_date(values.get('入职日期') or values.get('候选人入职时间'))
        previous=as_date(values.get('上次离职日期'))
        if not previous and values.get('二次入职专项口径依据') and values.get('二次入职间隔结论') in {'超过十二个月','不超过十二个月'}:
            return (.4 if values['二次入职间隔结论']=='超过十二个月' else 0),[], '二次入职'
        if not previous or not hire or previous>=hire: return None,['二次入职的上一段离职日期待核'],'二次入职'
        if hire<=add_months(previous,12) and values.get('二次入职执行口径'):
            choice=values['二次入职执行口径']
            if choice not in {'不发招聘奖金','按40%核算'}:
                return None,['二次入职专项条款执行依据待核'],'二次入职'
            return (0 if choice=='不发招聘奖金' else .4),[],'二次入职'
        factor=0 if hire<=add_months(previous,12) else .4
        return factor,[],'二次入职'
    if raw in NO_RECRUIT or value in NO_RECRUIT: return 0,[],value
    if value in {'内推','校招'}: return .4,[],value
    if raw in FULL_CHANNELS or value in FULL_CHANNELS or (raw=='其他' and text(values.get('其他渠道')) in {'招聘广告','广告','招聘会','网站'}): return 1,[],value
    return None,['招聘渠道待核'],raw


def offline_employment_basis(row, prefix):
    """External/GL relationships supplied offline do not require internal HR records.

    Require an explicitly external identifier and matching source evidence;
    an unknown internal employee or a manually invented identifier is not enough.
    """
    field=prefix+'工号'; identifier=text(row['values'].get(field)).casefold()
    if not ('体系外' in identifier or re.fullmatch(r'(?:海外-)?gl\d+',identifier)):
        return None
    if any(f.startswith(prefix) for f in row.get('unresolvedFields',[])):
        return None
    return next((p for p in row.get('provenance',{}).get(field,[])
                 if p.get('sourceId') and p.get('role') in {'ledger','overseas_offer','supplement'}
                 and text(p.get('value')).casefold()==identifier),None)


def status_at(values, prefix, at, formal=False, *, offline=False):
    entry=as_date(values.get(prefix+'入职日期') if prefix else values.get('入职日期') or values.get('候选人入职时间'))
    last=as_date(values.get(prefix+'最后工作日') if prefix else values.get('最后工作日'))
    status=text(values.get(prefix+'人员状态') if prefix else values.get('人员状态'))
    if not at: return '任职日期待核'
    if (entry and entry>at) or (last and last<at): return '适用日期已不在职'
    if not entry and not prefix and not offline: return '任职日期待核'
    if status in {'待入职','未入职'}: return '适用日期在职状态待核'
    if formal:
        probation=as_date(values.get(prefix+'转正日期'))
        if probation and probation>at: return '适用日期尚未转正'
        if status in {'试用','试用在职'} and not probation: return '适用日期尚未转正'
        if offline and not status: return ''
        if status not in {'正式','正式在职'} and not (probation and probation<=at and last and last>=at):
            return '推荐人正式在职状态待核'
    elif status not in {'正式','正式在职','试用','试用在职','在职'} and not (last and last>=at) and not (offline and not status):
        return '适用日期在职状态待核'
    return ''


def node_due_date(values, index):
    hire=as_date(values.get('入职日期') or values.get('候选人入职时间'))
    return (add_months(hire,(1,3,6)[index])-timedelta(days=1)) if hire and index<3 else as_date(values.get('转正日期')) if index==3 else None


def award(row, kind, month, *, evaluate_employment=True, cutoff_policy=None):
    v=row['values']; version=row['rule']['version']; standard=lookup(row,kind)
    qualification_basis=[]
    if kind=='referral':
        from .recruitment_employment import referrer_fact_missing, referrer_qualification
        v={**v,**{field:'' for field in ('推荐人职级','推荐人职位') if referrer_fact_missing(v.get(field))}}
        if standard:
            hire=as_date(v.get('入职日期') or v.get('候选人入职时间'))
            qualification_basis=referrer_qualification(row,[hire] if hire else [])
            if qualification_basis:v={**v,**qualification_basis[0]['values']}
            elif not row.get('frozenRecruitmentFacts'):
                reviewed={e['field'] for e in row.get('edits',[]) if e.get('active',True)}
                for field in ('推荐人职级','推荐人职位'):
                    refs=row.get('provenance',{}).get(field,[])
                    if refs and all(p.get('role')=='roster' for p in refs) and field not in reviewed:
                        # An undated current roster cannot prove the role at hire.
                        v[field]=''
    currency, country=country_currency(v)
    issues=[]; reasons=[]; total=None; cycle_info=None; channel_factor=None
    conflict_fields=material_conflicts(row,kind)
    if conflict_fields: issues.append('核算字段来源冲突：'+'、'.join(sorted(conflict_fields)))
    if version=='unresolved': issues.append('本次任职与规则版本待核')
    if row.get('scopeStatus') not in {'已纳入底稿','调动记录，保留核对'}: issues.append('人员核算范围待核')
    if not currency: issues.append('标准币种对应地区待核')
    if kind=='recruitment':
        channel_factor, channel_issues, normalized=channel(v,version); issues+=channel_issues
        if channel_factor==0:
            if not channel_issues:
                total=0; reasons.append('二次入职离职间隔不超过十二个月' if normalized=='二次入职' else '该招聘渠道不享受招聘奖金')
        elif standard:
            from .recruitment_business_basis import opening_exclusion_basis
            cycle_info, cycle_issues=cycle(v,standard['cycle'],version,exclusion_basis=opening_exclusion_basis(row)); issues+=cycle_issues
            if cycle_info.get('warning'): reasons.append(cycle_info['warning'])
            if cycle_info['factor'] is not None and channel_factor is not None:
                total=money(Decimal(str(standard['amount']))*Decimal(str(cycle_info['factor']))*Decimal(str(channel_factor)))
        if total!=0 and not standard: issues.append('招聘奖金标准待核')
        if not (present(v.get('招聘负责人工号')) or present(v.get('招聘负责人姓名'))) and total!=0: issues.append('招聘负责人待核')
        hire=as_date(v.get('入职日期') or v.get('候选人入职时间')); last=as_date(v.get('最后工作日')); probation=as_date(v.get('转正日期'))
        if evaluate_employment and hire and last and last < add_months(hire,1)-timedelta(days=1):
            total=0; reasons.append('入职未满一个月离职')
        if evaluate_employment and probation and last and yyyymm(probation)==yyyymm(last):
            total=0; reasons.append('转正当月离职')
    else:
        ref=present(v.get('推荐人工号')) or present(v.get('推荐人姓名'))
        ref_level=grade_level(v.get('推荐人职级'))
        position=text(v.get('推荐人职位'))
        hierarchy={text(v.get(f)).lower() for f in ('直线经理工号','直接上级工号','间接上级1工号','间接上级2工号','间接上级3工号','间接上级4工号') if present(v.get(f))}
        excluded=(v.get('招聘渠道') in NO_RECRUIT-{'猎头','猎头推荐','猎头推荐入职'} or v.get('招聘渠道') in {'其他','二次入职','返聘'} or v.get('是否二次入职')=='是')
        if excluded: total=0; reasons.append('该招聘渠道不享受内推奖金' if v.get('招聘渠道')=='其他' else '二次入职、调动或外包转正式不享受内推奖金')
        elif ref and referrer_role_exclusion(v) is True:
            total=0; reasons.append('推荐人岗位或职级不符合资格')
        elif ref and (text(v.get('推荐人工号')).lower() in hierarchy or v.get('推荐人是否直接/间接上级')=='是' or v.get('推荐人与候选人上下级关系')=='是'):
            total=0; reasons.append('推荐人与候选人属于上下级汇报关系')
        elif not ref:
            from .recruitment_business_basis import opening_has_no_referral
            if opening_has_no_referral(row):total=0;reasons.append('上月核算表已明确无内推奖金，沿用原记录')
            elif v.get('招聘渠道')=='内推': issues.append('推荐人待补充')
            else: total=0; reasons.append('无推荐关系')
        elif standard:
            total=money(standard['amount'])
            offline_referrer=offline_employment_basis(row,'推荐人')
            if not offline_referrer:
                if ref_level is None or not position: issues.append('推荐人岗位与职级待核')
                if not hierarchy and v.get('推荐人与候选人上下级关系')!='否': issues.append('推荐人与候选人汇报关系待核')
            if version=='legacy' and row['rule'].get('specialScope'):
                reasons.append('按入职日期及部门适用'+row['rule']['specialScope']+'旧内推规则')
        else: issues.append('内推奖金标准待核')
        if standard and standard.get('scope')=='FBU捷克': currency=standard.get('currency') or currency
    # An unresolved fact never masquerades as a computed zero.
    if version=='unresolved' or conflict_fields:
        total=None
    formula_total=total
    if v.get('核算范围')=='不纳入核算':
        total=0;issues=[];reasons=['经核对不纳入本次招聘奖金范围']
    decision=next((d for d in reversed(row.get('awardDecisions',[])) if d['kind']==kind and not d.get('role')),None)
    if decision and decision['action']=='exclude' and version!='unresolved' and not conflict_fields:
        total=0;reasons.append(('手工取消本次任职的' if decision.get('basisType')=='manual' else '按审批取消本次任职的')+('招聘奖金' if kind=='recruitment' else '内推奖金'))
    result={'kind':kind,'standard':standard['amount'] if standard else None,'total':total,'currency':currency,
            'formulaTotal':formula_total,'approvalDecision':decision,
            'countryBasis':country,'source':standard['source'] if standard else '',
            'cycle':cycle_info,'channelFactor':channel_factor,'issues':list(dict.fromkeys(issues)),
            'reasons':reasons,'nodes':[], 'currentAmount':None,'historyStatus':'未核实支付',
            'roundingPolicy':'逐期四舍五入，单列尾差' if version=='legacy' else '末期分摊尾差',
            'scheduledTotal':None,'roundingDifference':None,'recipientTotals':[]}
    if standard and standard.get('openingBasis'):result['standardBasis']=standard['openingBasis']
    if qualification_basis:result['referrerQualificationBasis']=qualification_basis
    if kind=='recruitment' and normalized=='二次入职' and not conflict_fields:
        basis=rehire_basis(v,version)
        if basis:result['rehireBasis']=basis
    if standard and total is not None and total>0:
        ratios=standard['ratios']
        recipients=[('推荐人','推荐人',1)] if kind=='referral' else [('招聘负责人','招聘负责人',.7 if (present(v.get('协助招聘人工号')) or present(v.get('协助招聘人姓名'))) else 1)]
        if kind=='recruitment' and (present(v.get('协助招聘人工号')) or present(v.get('协助招聘人姓名'))): recipients.append(('协助招聘人','协助招聘人',.3))
        allocated=Decimal('0')
        for recipient_index,(role,prefix,share) in enumerate(recipients):
            role_decision=next((d for d in reversed(row.get('awardDecisions',[])) if d['kind']==kind and d.get('role')==role and d['action']=='exclude'),None)
            offline_basis=offline_employment_basis(row,prefix)
            role_total=Decimal(str(money(total*share))) if recipient_index<len(recipients)-1 else Decimal(str(total))-allocated
            allocated+=role_total; distributed=Decimal('0'); active=[i for i,r in enumerate(ratios) if r]
            for i in active:
                amount=Decimal(str(money(role_total*Decimal(str(ratios[i]))))) if version=='legacy' or i!=active[-1] else role_total-distributed
                distributed+=amount
                due=node_due_date(v,i)
                due_month=yyyymm(due)
                node_issues=list(result['issues']);ineligible=[]
                prefix_id='招聘负责人工号' if role=='招聘负责人' else '协助招聘人工号' if role=='协助招聘人' else '推荐人工号'
                if recipient_conflict_fields(row,prefix): node_issues.append('领取人资料冲突')
                phase='未到期' if due_month and due_month>month else '本月到期' if due_month==month else '往期待核' if due_month else '待转正'
                if due_month and due_month<=month:
                    from .recruitment_special import evaluation_date
                    at=evaluation_date(cutoff_policy,kind,due,month)
                    for who,p,formal in [('候选人','',False),(role,prefix,False)]:
                        from .recruitment_employment import status_from_timeline
                        problem=status_from_timeline(row,p,at,formal)
                        if problem is None:problem=status_at(v,p,at,formal,offline=bool(p and offline_basis))
                        contested=bool(recipient_conflict_fields(row,p) if p else {'入职日期','人员状态','最后工作日','转正日期'} & set(row.get('unresolvedFields',[])))
                        if problem in {'适用日期已不在职','适用日期尚未转正'} and not contested:ineligible.append(who+'：'+problem)
                        elif problem: node_issues.append(who+'：'+problem)
                result['nodes'].append({'id':digest(row['id']+'|'+kind+'|'+role+'|'+str(i)), 'rowId':row['id'],
                    'role':role,'recipientId':text(v.get(prefix_id)), 'recipientName':text(v.get(prefix+'姓名')),
                    'label':NODES[i],'amount':float(amount),'currency':currency,'dueDate':due.strftime('%Y-%m-%d') if due else '',
                    'dueMonth':due_month,'status':'待核对' if node_issues else phase,'timing':phase,'issues':list(dict.fromkeys(node_issues)),
                    'paidAmount':None,'paymentStatus':'未核实','paymentReady':False})
                if offline_basis:
                    result['nodes'][-1]['employmentBasis']={**offline_basis,'description':'体系外业务同事提供的线下资料，不要求内部任职记录'}
                if ineligible:
                    result['nodes'][-1].update(status='按规则不发',scheduledMonth=None,
                        eligibilityReasons=ineligible,scheduleText='；'.join(ineligible))
                if role_decision:
                    reason=('手工取消' if role_decision.get('basisType')=='manual' else '按审批取消')+role+'奖金：'+role_decision['reason']
                    result['nodes'][-1].update(status='按规则不发',scheduledMonth=None,
                        eligibilityReasons=[reason],scheduleText=reason,roleDecision=role_decision)
            result['recipientTotals'].append({'role':role,'allocatedAmount':float(role_total),'scheduledAmount':float(distributed),'roundingDifference':money(distributed-role_total)})
    if total is not None:
        result['scheduledTotal']=money(sum(Decimal(str(n['amount'])) for n in result['nodes']))
        result['roundingDifference']=money(Decimal(str(result['scheduledTotal']))-Decimal(str(total)))
        result['currentAmount']=money(sum(n['amount'] for n in result['nodes'] if n.get('scheduledMonth',n['dueMonth'])==month))
    return result


def calculate_base(state,row,*,evaluate_employment=True):
    from .recruitment_special import cutoff, apply_special
    result={'ruleVersion':row['rule']['version'],'ruleHash':RULE_HASH,
            'recruitment':award(row,'recruitment',state['month'],evaluate_employment=evaluate_employment,cutoff_policy=cutoff(state,'recruitment')),
            'referral':award(row,'referral',state['month'],evaluate_employment=evaluate_employment,cutoff_policy=cutoff(state,'referral'))}
    if state.get('settlement') or state.get('confirmedInstallments'):
        from .recruitment_settlement import apply_settlement
        apply_settlement(state,row,result)
    elif state.get('offlineReplay') and state['offlineReplay'].get('month',state['month'])==state['month']:
        from .recruitment_opening import apply_opening
        apply_opening(state,row,result)
    apply_special(state,row,result)
    return result


def calculate_row(state,row):
    """Use identical rules and existing arrangements for calculation and previews."""
    from .recruitment_external_results import empty_award, overlay
    if row.get('externalOnly'):
        return overlay(state,row,{'ruleVersion':'external','ruleHash':RULE_HASH,
            'recruitment':empty_award('recruitment'),'referral':empty_award('referral')})
    result=calculate_base(state,row)
    return overlay(state,row,result)


def calculate_draft(state):
    from .recruitment_cancellation import checkpoint
    checkpoint()
    from .recruitment_business_basis import select_unique_opening
    select_unique_opening(state)
    from .recruitment_external_results import attach_rows
    attach_rows(state)
    if state.get('baseline'):
        for row in state['rows']:
            for h in row.get('history',[]):h['isBaseline']=h['ref']['sourceId']==state['baseline']
        state['todos']=[t for t in state['todos'] if t['kind']!='baseline']
        state['summary']['baselineConfirmed']=True
    rows=state['rows']; groups={}; totals=defaultdict(Decimal); statuses=Counter()
    for row in rows:
        checkpoint()
        # Recompute the removed diagnostic in old drafts too. Preserve source
        # facts, explicit scope decisions and unrelated employment diagnostics.
        if row.get('scopeStatus')=='操作类范围待核':
            from .recruitment_drafts import scope_status
            row['scopeStatus']=scope_status(row['values'])
        result=calculate_row(state,row)
        for kind in ('recruitment','referral'):
            a=result[kind]; label='招聘奖金' if kind=='recruitment' else '内推奖金'
            relevant=list(a['issues'])+[i['reason'] for i in a.get('accountingIssues',[]) if i['accountingMonth']==state['month']]
            for n in a['nodes']:
                statuses[n['status']]+=1
                if n.get('scheduledMonth',n['dueMonth'])==state['month']:
                    if n.get('amount') is not None:totals[n['currency']]+=Decimal(str(n['amount']))
                    relevant.extend(n['issues'])
                elif n.get('adjustmentId') and n.get('accountingMonth')==state['month']:
                    relevant.extend(n['issues'])
            for issue in set(relevant):
                key=digest(kind+'|'+issue)
                task=groups.setdefault(key,{'id':key,'kind':'calculation','title':label+'：'+issue,'detail':'','rowIds':[],'sourceIds':[]})
                task['rowIds'].append(row['id'])
        row['calculation']=result
        row['needsReview']=row.get('needsReview',False) or any(a['issues'] for a in (result['recruitment'],result['referral']))
    state['calculation']={'engineVersion':ENGINE_VERSION,'ruleHash':RULE_HASH,'draftRevision':state['revision'],
        'standardCurrencyOnly':True,'paymentReady':False,'totalsByCurrency':{k:money(v) for k,v in totals.items()},
        'nodeStatuses':dict(statuses),'people':len(rows),'pendingPeople':sum(any(r['calculation'][k]['total'] is None or r['calculation'][k]['issues'] for k in ('recruitment','referral')) for r in rows),
        'ruleSource':CATALOG['source'],'legacyRuleSource':CATALOG['legacySource']}
    state['todos']=[t for t in state['todos'] if t['kind']!='calculation']+list(groups.values())
    state['summary']['todoGroups']=len(state['todos'])
    state['paymentReady']=False
    if state.get('strictInputs'):
        from .recruitment_settlement import validation
        state['ruleValidation']=validation(state)
    return state


def ensure_calculated(state, *, copy_if_stale=False):
    saved=state.get('calculation',{})
    if saved.get('engineVersion')!=ENGINE_VERSION or saved.get('ruleHash')!=RULE_HASH or saved.get('draftRevision')!=state['revision']:
        if copy_if_stale:
            from copy import deepcopy
            state=deepcopy(state)
        return calculate_draft(state)
    return state

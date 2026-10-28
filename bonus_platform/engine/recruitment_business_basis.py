"""Reuse supplied business evidence without inventing another approval step."""
from .recruitment_draft_sources import text


def select_unique_opening(state):
    """Only an unambiguous, explicitly dated previous-month ledger is automatic.

    An existing choice, carried month or explicit empty opening always wins.
    Current comparison results can never become calculation inputs.
    """
    if not state.get('strictInputs') or any(state.get(k) for k in ('baseline','parentMonth','openingEmptyConfirmed')):
        return
    from .recruitment_attention import named_month
    previous=(state['month']//100-1)*100+12 if state['month']%100==1 else state['month']-1
    candidates=[s for s in state.get('sources',[]) if s.get('active',True)
                and not s.get('error') and not s.get('comparisonOnly') and 'ledger' in s.get('roles',[])
                and named_month([s['name']])==previous]
    if len(candidates)!=1:return
    source=candidates[0]
    state['baseline']=source['id']
    state['settlement']={**state.get('settlement',{}),'version':1,'baselineId':source['id']}
    state['openingSelection']={'mode':'uniquePreviousMonth','sourceId':source['id'],
                               'month':previous,'description':'自动承接已导入的唯一上月核算表'}


def adopted_history(row):
    matches=[h for h in row.get('history',[]) if h.get('isBaseline')]
    return matches[0] if len(matches)==1 else None


def opening_has_no_referral(row):
    """Explicit zero in an adopted ledger is not an unknown referral person.

    Blank cells, changed relationships and any positive installment must remain
    unresolved or be recalculated; this does not infer zero from missing data.
    """
    history=adopted_history(row)
    if not history:return False
    cells={c['column']:c['value'] for c in history['cells']}
    absent={'','-','无','无工号','N/A'}
    if any(text(row['values'].get(f)) not in absent or f in row.get('unresolvedFields',[])
           for f in ('推荐人工号','推荐人姓名')):return False
    if any(text(cells.get(c)) not in absent for c in (58,59)):return False
    from .recruitment_awards import number
    return all(number(cells.get(c))==0 for c in (61,62,64,66,68))


def opening_exclusion_basis(row):
    history=adopted_history(row)
    if not history or '周期剔除天数' in row.get('unresolvedFields',[]):return None
    from .recruitment_awards import number
    cells={c['column']:c['value'] for c in history['cells']}
    previous=number(cells.get(33));current=number(row['values'].get('周期剔除天数'))
    if previous is not None and previous>0 and current==previous:
        return {**history['ref'],'description':'承接上月核算表已采用的周期剔除天数'}
    return None


def unchanged_opening(row):
    if not row.get('frozenRecruitmentFacts') or not adopted_history(row):return False
    from .recruitment_awards import RECRUIT_FIELDS
    fields=RECRUIT_FIELDS | {'招聘负责人工号','协助招聘人工号','推荐人工号','推荐人姓名',
                             '二级组织','三级组织','四级组织','五级组织','工作地'}
    from .recruitment_drafts import staff_id
    def same(field):
        before=row.get('original',{}).get(field);after=row['values'].get(field)
        if field=='奖金地区类型' and not before:return True  # Derived from the unchanged region/organization.
        if field.endswith('工号'):return staff_id(before)==staff_id(after)
        return text(before)==text(after)
    return not (set(row.get('unresolvedFields',[])) & fields) and all(same(f) for f in fields)


def legacy_person_standard(row, candidates, ratios):
    """A missing catalog mapping must not erase an existing person's terms.

    Only reuse an adopted historical standard already present in the catalog
    for this category/region, with unchanged recruitment facts and a fully
    reconciling prior schedule. Never generalize it to others or new hires.
    """
    if not unchanged_opening(row):return None
    from .recruitment_awards import number, channel, cycle, money
    h=adopted_history(row);cells={c['column']:c['value'] for c in h['cells']};v=row['values']
    category=lambda s:text(s).replace('类','').replace('C1','C')
    if (text(cells.get(9))!=text(v.get('职级')) or cells.get(19)!=v.get('标签分类')
            or category(cells.get(21))!=category(v.get('ABC类别'))):return None
    amount=number(cells.get(37));days=number(cells.get(32))
    if not amount or not days or not any(number(s['amount'])==amount and number(s['cycle'])==days for s in candidates):return None
    # Column 37 can already include channel sharing in old workbooks. Limit
    # this fallback to unambiguous full-rate records, avoiding double scaling.
    if channel(v,'legacy')[0]!=1:return None
    cyc,issues=cycle(v,float(days),'legacy',exclusion_basis=opening_exclusion_basis(row))
    if issues or cyc['factor'] is None:return None
    total=number(cells.get(38))
    if total is None or money(amount*number(cyc['factor']))!=float(total):return None
    if any(number(cells.get(c)) not in (None,0) for c in (45,46,48,50,54)):return None
    if any(money(total*number(r))!=float(number(cells.get(c)) or 0) for r,c in zip(ratios,(39,41,43,52))):return None
    return {'amount':float(amount),'cycle':float(days),'ratios':ratios,
            'source':'沿用上月核算表中该员工的奖金标准','openingBasis':h['ref']}


def historical_arrangements_complete(row, kind, month):
    """Keep complete past ledger schedules without reopening their old pricing.

    Every positive installment needs a recorded past month. An unfinished total,
    a cancelled standard, or changed facts still needs reconciliation. Historical
    installments can exceed an old nominal standard; retaining them is not proof
    of payment or a completed recovery.
    """
    if not unchanged_opening(row):return False
    from .recruitment_awards import number
    from .recruitment_opening import COLUMNS, period
    cells={c['column']:c['value'] for c in adopted_history(row)['cells']}
    total_columns=(38,45) if kind=='recruitment' else (61,)
    totals=[number(cells.get(c)) for c in total_columns]
    if totals[0] is None or any(t is not None and t<0 for t in totals):return False
    arranged=0
    for index,columns in enumerate(COLUMNS[kind].values()):
        role_arranged=0
        for amount_col,month_col,_ in columns:
            amount=number(cells.get(amount_col))
            if amount is None or amount==0:continue
            due=period(cells.get(month_col))
            if amount<0 or not due or due>=month:return False
            arranged+=amount
            role_arranged+=amount
        declared=totals[index] or 0
        if role_arranged<declared or (role_arranged>0 and declared<=0):return False
    return arranged>=sum(t or 0 for t in totals)

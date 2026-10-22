"""Offline-ledger column order, projected from adopted facts and calculated nodes.

This is presentation only: never import the comparison workbook's answers.
Excel helper columns and historical deduction workings remain in source records.
"""
from decimal import Decimal

from .recruitment_awards import NODES, present as has_value


def columns():
    result=[]
    def add(key,label,group,kind='text',width=128):
        result.append(dict(key=key,label=label,group=group,type=kind,width=width))
    for key,label in [('name','姓名'),('employeeId','工号'),('证件号','身份证'),
                      ('hireDate','入职日期'),('人员状态','人员状态'),('工作地','工作地'),
                      ('最后工作日','最后工作日'),('职级','职级'),('二级组织','二级组织'),
                      ('三级组织','三级组织'),('四级组织','四级组织'),('五级组织','五级组织'),
                      ('职位','职位'),('直线经理','直线经理'),('直线经理工号','直线经理工号'),
                      ('标签分类','标签分类（国内/海外）')]:
        add(key,label,'人员资料',width=160 if key=='name' else 180 if key=='证件号' or '组织' in key or key=='职位' else 128)
    for key,label in [('ABC类别','ABC类别'),('招聘负责人工号','招聘负责人工号'),('recruiter','招聘负责人姓名'),
                      ('协助招聘人工号','协助招聘人工号'),('assistant','协助招聘人姓名'),('channel','招聘渠道'),
                      ('海外offer流程编号','海外offer流程编号'),('招聘启动日期','招聘启动日期'),
                      ('候选人入职时间','候选人入职时间'),('转正日期','转正日期')]:
        add(key,label,'招聘信息',width=160 if '编号' in key else 136)
    group='招聘负责人入职奖金明细'
    for key,label,kind in [('standardDays','标准入职周期','number'),('exclusionDays','周期天数剔除','number'),
                           ('actualDays','实际入职周期','number'),('difference','入职周期差异','number'),
                           ('channelFactor','奖金比例','percent'),('standard','奖金标准','money')]:
        add('recruitment.'+key,label,group,kind)
    def allocated(role,group):
        add('recruitment.'+role+'.allocated','实际发放标准（保底：30%）' if role=='招聘负责人' else '实际发放标准',group,'money',156)
    def installment(kind,role,index,group,caption):
        prefix=f'{kind}.{role}.{index}'
        add(prefix+'.amount',caption+'奖金',group,'money',148)
        add(prefix+'.period',caption+'周期',group,width=148)
    allocated('招聘负责人',group)
    for i,m in enumerate((1,3,6)):installment('recruitment','招聘负责人',i,group,f'入职{m}个月发放')
    group='协助人入职奖金明细';allocated('协助招聘人',group)
    for i,m in enumerate((1,3,6)):installment('recruitment','协助招聘人',i,group,'入职6个月/转正发放' if m==6 else f'入职{m}个月发放')
    installment('recruitment','招聘负责人',3,'招聘人转正奖金','转正发放')
    installment('recruitment','协助招聘人',3,'协助人转正奖金','转正发放')
    add('currency','奖金对应币种','币种',width=156)
    group='内推奖明细'
    for key,label in [('奖金地区类型','发达国家/发展中国家'),('referrer','推荐人姓名'),
                      ('推荐人工号','推荐人工号'),('referral.relationship','推荐人是否直接/间接上级')]:
        add(key,label,group,width=176 if key=='referral.relationship' else 148)
    add('referral.standard','推荐奖金标准',group,'money',148)
    for i,m in enumerate((1,3,6)):installment('referral','推荐人',i,group,f'入职{m}个月发放')
    installment('referral','推荐人',3,group,'转正发放')
    add('note','备注','备注',width=300)
    for key,label,kind in [('recruitmentAmount','本月招聘奖金','money'),('referralAmount','本月内推奖金','money'),('status','核对情况','text')]:
        add(key,label,'本月核算',kind,136)
    return result


def cells(row):
    """Do not confuse a missing amount, an unused installment, and calculated zero."""
    v=row['values'];out={c['key']:v.get(c['key'],'') for c in columns()};notes={}
    out['候选人入职时间']=v.get('候选人入职时间') or v.get('入职日期','')
    recruitment=row['calculation']['recruitment'];cycle=recruitment.get('cycle') or {}
    unused_cycle=recruitment['total']==0 and not cycle
    for key in ('standardDays','exclusionDays','actualDays'):out['recruitment.'+key]=cycle.get(key,'' if unused_cycle else None)
    out['recruitment.difference']=cycle['actualDays']-cycle['standardDays'] if all(cycle.get(k) is not None for k in ('actualDays','standardDays')) else '' if unused_cycle else None
    out['recruitment.channelFactor']=recruitment.get('channelFactor')
    if cycle.get('exempt'):notes['recruitment.actualDays']='已按有效依据免招聘周期考核'
    relation=v.get('推荐人是否直接/间接上级') or v.get('推荐人与候选人上下级关系','')
    if any('上下级汇报关系' in reason for reason in row['calculation']['referral'].get('reasons',[])):relation='是'
    out['referral.relationship']=relation
    for kind,roles in [('recruitment',('招聘负责人','协助招聘人')),('referral',('推荐人',))]:
        a=row['calculation'][kind]
        out[kind+'.standard']=a.get('standard') if a.get('standard') is not None else '' if a['total']==0 else None
        for role in roles:
            present=role=='招聘负责人' or has_value(v.get(role+'姓名')) or has_value(v.get(role+'工号'))
            if kind=='referral' and not present and a['total']==0:out[kind+'.standard']=''
            allocation=next((r for r in a.get('recipientTotals',[]) if r['role']==role),None)
            out[f'{kind}.{role}.allocated']=allocation['allocatedAmount'] if allocation else 0 if a['total']==0 and present else None if present else ''
            for i,label in enumerate(NODES):
                prefix=f'{kind}.{role}.{i}'
                nodes=[n for n in a['nodes'] if n['role']==role and n['label']==label]
                if not nodes:
                    out[prefix+'.amount']=None if present and a['total'] is None else ''
                    out[prefix+'.period']=''
                    if present and a['total'] is None:notes[prefix+'.amount']='资料尚不完整，尚不能计算此分期'
                    continue
                units={n['currency'] for n in nodes}
                out[prefix+'.amount']=float(sum((Decimal(str(n['amount'])) for n in nodes),Decimal(0))) if len(units)==1 and all(n.get('amount') is not None for n in nodes) else None
                periods=[];explanations=[]
                for n in nodes:
                    period=n.get('scheduledMonth',n.get('dueMonth'))
                    periods.append(str(period) if period else n.get('status') if n.get('status') in {'按规则不发','暂缓安排','往期未安排','依据已失效','安排需重新核对'} else '待转正' if i==3 and not n.get('dueDate') else '待核对')
                    explanations.extend(filter(None,[role+'：'+str(n.get('recipientName') or n.get('recipientId') or '待补充'),n.get('amountBasis'),n.get('scheduleText'),*n.get('issues',[])]))
                out[prefix+'.period']='；'.join(dict.fromkeys(periods))
                notes[prefix+'.amount']='；'.join(dict.fromkeys([*units,*explanations]))
                notes[prefix+'.period']='；'.join(dict.fromkeys(explanations))
    return out,notes

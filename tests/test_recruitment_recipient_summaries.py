from copy import deepcopy
from decimal import Decimal
from bonus_platform.engine.recruitment_monthly import recipient_summaries


def test_summary_combines_roles_separates_currency_pending_and_unknown():
    state={'rows':[{'id':'a','values':{'招聘负责人职位':'主管','推荐人职位':'专员'}}]}
    def node(**kw):
        return dict(rowId='a',kind='recruitment',scope='current',role='招聘负责人',recipientId='ZT1',recipientName='甲',currency='人民币',label='入职满一个月',amount=10,review=False,reasons=[],**kw)
    first=node(); assistant={**first,'role':'协助招聘人','recipientId':'zt1','label':'转正','amount':2.5}
    pending={**first,'review':True,'amount':3,'reasons':['待核对']}
    unknown={**pending,'amount':None}
    foreign={**first,'currency':'欧元','amount':5}
    dollar={**first,'currency':'美元','amount':8}
    future={**first,'scope':'future','amount':100}
    held={**first,'scope':'held','amount':100}
    referral={**first,'kind':'referral','role':'推荐人','amount':7}
    nodes=[first,assistant,pending,unknown,foreign,dollar,future,held,referral]
    before=deepcopy((state,nodes));result=recipient_summaries(state,nodes)
    assert (state,nodes)==before
    r=next(r for r in result['recruitment']['rows'] if r['currency']=='人民币')
    assert (r['confirmed'],r['pending'],r['unknown'],r['month1'],r['probation'])==(12.5,3,1,10,2.5)
    overseas=[r for r in result['recruitment']['rows'] if r['currency']!='人民币']
    assert {r['currency']:r['confirmed'] for r in overseas}=={'欧元':5,'美元':8}
    assert all(r['employeeId']=='海外-ZT1' and r['sourceCurrencies']==[r['currency']] for r in overseas)
    assert r['position']=='主管'
    assert result['referral']['rows'][0]['position']=='专员'
    for kind in ('recruitment','referral'):
        for total in result[kind]['totals']:
            for key,review in [('confirmed',False),('pending',True)]:
                expected=sum(Decimal(str(n['amount'])) for n in nodes if n['kind']==kind and n['scope']=='current' and n['currency']==total['currency'] and n['review']==review and n['amount'] is not None)
                assert Decimal(str(total[key]))==expected


def test_unidentified_people_do_not_merge():
    nodes=[dict(rowId=r,kind='referral',scope='current',role='推荐人',recipientId='',recipientName='同名',currency='人民币',label='转正',amount=None,review=True,reasons=[]) for r in ('a','b')]
    result=recipient_summaries({'rows':[]},nodes)['referral']
    assert len(result['rows'])==2
    assert result['totals'][0]['unknown']==2


def test_foreign_recipient_prefix_is_written_once_without_changing_grouped_amounts():
    state={'month':202608,'rows':[]}
    nodes=[]
    for index,(number,amount) in enumerate([('海外-zt25991',123.75),('zt25991',126.5)]):
        nodes.append({'rowId':str(index),'kind':'recruitment','scope':'current','role':'招聘负责人',
            'recipientId':number,'recipientKey':'number:zt25991','recipientName':'领取人','currency':'欧元',
            'label':'体系外月度核定','amount':amount,'review':False,'reasons':[]})
    before=deepcopy(nodes)
    result=recipient_summaries(state,nodes)['recruitment']
    assert len(result['rows'])==1
    assert (result['rows'][0]['employeeId'],result['rows'][0]['confirmed'])==('海外-zt25991',250.25)
    assert result['totals'][0]['confirmed']==250.25
    assert nodes==before

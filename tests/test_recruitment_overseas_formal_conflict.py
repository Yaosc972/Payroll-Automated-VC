from test_recruitment_awards import person
from bonus_platform.engine.recruitment_awards import award


def test_formal_history_followed_by_trial_movement_is_pending_instead_of_definite_nonpayment():
    row=person(hire='2026-07-25',招聘渠道='内推',推荐人工号='zt2',推荐人姓名='推荐人',推荐人职级='P2-1',推荐人职位='专员',推荐人入职日期='2026-07-01',推荐人与候选人上下级关系='否')
    row['edits']=[]
    row['recipientSourceRegions']={'推荐人':'海外'}
    common=dict(provider='oehr',queriedAt='2026-10-22',employmentType='0',employmentStatus='1',entryDate='2026-07-01',lastWorkDay='')
    row['employmentTimelines']={'推荐人':[
        dict(common,startDate='2026-07-23',endDate='2026-07-23',employeeStatus='3'),
        dict(common,startDate='2026-07-24',endDate='9999-12-31',employeeStatus='2')]}
    nodes=award(row,'referral',202608)['nodes']
    due=[n for n in nodes if n['dueMonth']==202608]
    assert due
    assert all(n['status']=='待核对' for n in due)
    assert all(not n.get('eligibilityReasons') for n in due)

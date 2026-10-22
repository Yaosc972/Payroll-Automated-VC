from bonus_platform.engine.recruitment_overseas import scope


def test_historical_inverted_start_dates_request_only_the_exact_unresolved_offers():
    def row(code, hire, start, matched=False):
        return {'offerMatched':matched,'values':{'标签分类':'海外','工号':'zt123',
            '海外offer流程编号':code,'入职日期':hire,'招聘启动日期':start}}
    rows=[row('HIST-GAP','2026-05-13','2026-05-14'),
          row('HIST-OK','2026-05-13','2026-05-01'),
          row('RESOLVED','2026-05-13','2026-05-14',True),
          row('UNKNOWN','2026-05-13',''),
          row('MONTH','2026-08-10','2026-08-01')]
    result=scope({'month':202608,'rows':rows})
    assert result['offer_codes']==['hist-gap','month','resolved']
    assert result['job_numbers']==['zt123']

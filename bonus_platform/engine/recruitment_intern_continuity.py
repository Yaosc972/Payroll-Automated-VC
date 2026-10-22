"""Prove recruitment continuity from the original effective-dated HR segments."""
from collections import defaultdict
from datetime import date, timedelta


def _date(value):
    try:
        return date.fromisoformat(str(value or '')[:10])
    except ValueError:
        return None


def employment_key(history):
    return (history.get('userID'),str(history.get('jobNumber') or '').strip().lower(),
            history.get('lUOffer'),str(history.get('entryDate') or '')[:10])


def intern_continuities(histories):
    """Return only unique adjacent internship-to-main-employment bridges.

    A segment closing is not an exit. An explicit internship exit, a gap, a
    competing employment or a missing relationship prevents the bridge.
    Duplicate segments for the same employment remain harmless evidence.
    """
    groups=defaultdict(list)
    for position,h in enumerate(histories):
        user,number,offer,entry=employment_key(h)
        start,stop=_date(h.get('startDate')),_date(h.get('stopDate'))
        if (not user or not number or not offer or not _date(entry) or not start or not stop
            or not _date(entry)<=start<=stop
            or str(h.get('approvalStatus'))!='4' or str(h.get('serviceType'))!='0'):
            continue
        groups[(user,number,offer)].append((position,h))
    result={}
    for (user,number,offer),items in groups.items():
        entries={str(h.get('entryDate'))[:10] for _,h in items if str(h.get('employType'))=='0'
                 and _date(h.get('startDate'))==_date(h.get('entryDate'))}
        for formal in entries:
            previous=_date(formal)-timedelta(days=1)
            before=[(i,h) for i,h in items if str(h.get('employType'))=='2'
                    and _date(h.get('stopDate'))==previous and not h.get('lastWorkDate')]
            starts={str(h.get('entryDate'))[:10] for _,h in before}
            if len(starts)!=1:continue
            original=next(iter(starts))
            after=[(i,h) for i,h in items if str(h.get('employType'))=='0'
                   and str(h.get('entryDate'))[:10]==formal]
            beginning=_date(original);ending=max(_date(h.get('stopDate')) for _,h in after)
            conflict=False
            for other in histories:
                other_user,other_number,other_offer,other_entry=employment_key(other)
                if other_user!=user and other_number!=number:continue
                start,stop=_date(other.get('startDate')),_date(other.get('stopDate'))
                if not start or not stop or stop<beginning or start>ending:continue
                same=(other_user,other_number,other_offer)==(user,number,offer)
                internship=same and other_entry==original and str(other.get('employType'))=='2'
                formal_segment=same and other_entry==formal and str(other.get('employType'))=='0'
                if internship and (other.get('lastWorkDate') or stop>=_date(formal)):
                    conflict=True;break
                if not internship and not formal_segment:
                    conflict=True;break
            if conflict:continue
            result[(user,number,offer,formal)]={
                'recruitmentEntryDate':original,'formalEntryDate':formal,
                'internStopDate':str(previous),'internHistoryIndexes':[i for i,_ in before],
                'formalHistoryIndexes':[i for i,_ in after]}
    return result

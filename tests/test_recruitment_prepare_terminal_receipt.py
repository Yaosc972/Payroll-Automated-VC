from threading import Event
from test_recruitment_monthly_sync import MONTH,payloads
from bonus_platform.engine import recruitment_prepare as jobs
from bonus_platform.engine.recruitment_drafts import DraftStore


def test_terminal_receipt_and_registration_are_observed_atomically(tmp_path,monkeypatch):
    store=DraftStore(tmp_path);payloads(monkeypatch)
    original=jobs.ACTIVE;at_cleanup=Event();release=Event()
    class Context:
        def set(self,value):return original.set(value)
        def reset(self,token):
            at_cleanup.set()
            assert release.wait(5)
            original.reset(token)
    monkeypatch.setattr(jobs,'ACTIVE',Context())
    jobs.start(store,MONTH,0,monthly_all=True)
    try:
        assert at_cleanup.wait(5)
        receipt=jobs.read_status(store,MONTH)
        assert receipt['status']=='complete'
        assert jobs.key_for(store,MONTH) not in jobs.RUNNING
    finally:
        release.set()

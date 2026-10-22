"""Cooperative cancellation for a monthly preparation worker."""
from contextvars import ContextVar


ACTIVE = ContextVar('recruitment_preparation_cancel', default=None)


class PreparationCancelled(Exception):
    pass


def checkpoint():
    event = ACTIVE.get()
    if event is not None and event.is_set():
        raise PreparationCancelled()

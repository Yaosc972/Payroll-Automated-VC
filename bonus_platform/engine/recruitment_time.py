"""Recruitment audit timestamps use explicit Beijing time on every runtime."""
from datetime import datetime
from zoneinfo import ZoneInfo


def now():
    return datetime.now(ZoneInfo('Asia/Shanghai'))

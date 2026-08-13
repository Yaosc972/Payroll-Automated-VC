"""UTC helpers that preserve the platform's legacy naive datetime contracts."""

from datetime import datetime, timezone


def utcnow_naive() -> datetime:
    """Return naive UTC without relying on the deprecated ``datetime.utcnow``."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

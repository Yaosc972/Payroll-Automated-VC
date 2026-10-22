"""Company runtime boundary for the file-based recruitment workbench.

The old run API keeps its OBS backend. New workbench files require one shared,
backed-up POSIX volume; container writable layers are never accepted as storage.
"""
from contextlib import contextmanager
import hashlib
import logging
import os
from pathlib import Path

from fastapi import HTTPException

from .. import config
from ..auth import production_runtime
from .mysql_db import mysql_connection

LOG = logging.getLogger(__name__)
SHARED_FILESYSTEMS = {"nfs", "nfs4", "ceph", "fuse.ceph", "glusterfs", "fuse.glusterfs"}


def data_root():
    return Path(os.getenv("SIGMA_RECRUITMENT_DATA_DIR") or config.OUTPUT_DIR).expanduser()


def shared_mount(path):
    """Use the kernel mount table, including bind mounts invisible to is_mount."""
    mountinfo = Path("/proc/self/mountinfo")
    if not mountinfo.is_file():
        return False
    path = path.resolve()
    matches = []
    for line in mountinfo.read_text().splitlines():
        left, separator, right = line.partition(" - ")
        fields = left.split()
        if not separator or len(fields) < 5:
            continue
        mount = Path(fields[4].replace("\\040", " ").replace("\\134", "\\"))
        if path.is_relative_to(mount):
            matches.append((len(mount.parts), right.split()[0]))
    return bool(matches and max(matches)[1] in SHARED_FILESYSTEMS)


def require_runtime():
    if not production_runtime():
        return
    root = data_root()
    if (not os.getenv("SIGMA_RECRUITMENT_DATA_DIR") or not root.is_absolute()
            or not root.is_dir() or not shared_mount(root)):
        raise HTTPException(503, "招聘工作台共享持久卷尚未接通，请联系管理员；历史批次入口仍可使用。")
    if not config.ADMIN_DATABASE_URL.startswith(("mysql://", "mysql+pymysql://")):
        raise HTTPException(503, "招聘同步任务的 MySQL 互斥锁尚未配置。")


@contextmanager
def task_lock(name):
    """A connection-owned lock has no lease expiry during a slow HR query."""
    if not production_runtime():
        yield True
        return
    require_runtime()
    namespace = os.getenv("SIGMA_LABOR_STORAGE_ENV", "production")
    lock_name = "sigma-recruitment-" + hashlib.sha256((namespace + ":" + name).encode()).hexdigest()[:40]
    connection = mysql_connection(config.ADMIN_DATABASE_URL)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT GET_LOCK(%s, 0) AS acquired", (lock_name,))
            acquired = cursor.fetchone()["acquired"] == 1
        yield acquired
    finally:
        # Closing also releases the named lock after exceptions or process exit.
        connection.close()


def start_scheduler():
    if os.getenv("SIGMA_RECRUITMENT_SCHEDULER_ENABLED", "").lower() != "true":
        return None
    try:
        require_runtime()
    except HTTPException:
        LOG.error("Recruitment scheduler disabled: shared storage/MySQL runtime is not ready")
        return None
    from ..recruitment_draft_api import store
    from .recruitment_snapshot_library import SnapshotScheduler
    return SnapshotScheduler(store).start()

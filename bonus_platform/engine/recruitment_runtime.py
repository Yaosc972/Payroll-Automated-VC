"""Company recruitment runtime, reusing existing MySQL and private OBS."""
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


def data_root():
    from .recruitment_persistence import SESSION
    session = SESSION.get()
    return session.root if session else config.OUTPUT_DIR


def require_runtime():
    if not production_runtime():
        return
    from .recruitment_persistence import ready
    if not ready():
        raise HTTPException(503, '招聘工作台需要现有 MySQL 和 OBS 持久化连接，请联系管理员核实。')


@contextmanager
def task_lock(name):
    if not production_runtime():
        yield True
        return
    require_runtime()
    from .recruitment_persistence import environment
    lock_name = 'sigma-recruitment-' + hashlib.sha256((environment() + ':' + name).encode()).hexdigest()[:40]
    connection = mysql_connection(config.ADMIN_DATABASE_URL)
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT GET_LOCK(%s, 0) AS acquired', (lock_name,))
            acquired = cursor.fetchone()['acquired'] == 1
        yield acquired
    finally:
        connection.close()


def start_scheduler():
    default = 'true' if production_runtime() else 'false'
    if os.getenv('SIGMA_RECRUITMENT_SCHEDULER_ENABLED', default).lower() != 'true':
        return None
    try:
        require_runtime()
    except HTTPException:
        LOG.error('Recruitment scheduler disabled: MySQL/OBS runtime is not ready')
        return None
    from ..recruitment_draft_api import store
    from .recruitment_snapshot_library import SnapshotScheduler
    return SnapshotScheduler(store).start()

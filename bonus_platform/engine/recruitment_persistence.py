"""Transactional file working copies backed by existing company MySQL and OBS.

MySQL publishes immutable, content-addressed OBS manifests atomically. Temporary
working copies are disposable, including after a process or container restart.
Readers see the last committed state while a single writer performs HR intake.
"""
from contextvars import ContextVar
import hashlib
import json
import logging
import os
from pathlib import Path, PurePosixPath
import re
from tempfile import TemporaryDirectory
import time

from fastapi import HTTPException
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.routing import APIRoute
from starlette.concurrency import run_in_threadpool

from .. import config
from .mysql_db import mysql_connection
from .labor.obs_storage import obs_get_bytes, obs_put_bytes, obs_storage_configured

SESSION = ContextVar('recruitment_persistent_session', default=None)
ROOTS = {'recruitment_activities', 'recruitment_drafts', 'recruitment_trials', 'recruitment_shared_snapshots'}
MAX_FILE = 100 * 1024 * 1024
MAX_TOTAL = 500 * 1024 * 1024
LOG = logging.getLogger(__name__)


class Busy(Exception):
    pass


def enabled():
    return os.getenv('SIGMA_RECRUITMENT_STORAGE_BACKEND', '').lower() in {'obs', 's3'}


def ready():
    return (enabled() and obs_storage_configured()
            and config.ADMIN_DATABASE_URL.startswith(('mysql://', 'mysql+pymysql://')))


def environment():
    # Existing previews inherited the production storage label. Platform identity
    # separates these new tables/objects without changing any existing module.
    label = os.getenv('SIGMA_LABOR_STORAGE_ENV', 'local')
    stage = os.getenv('AIDEPLOY_ENV', '').strip().lower() or 'local'
    name = re.sub('[^a-zA-Z0-9_-]', '-', label + '-' + stage)
    return name if len(name) <= 64 else hashlib.sha256(name.encode()).hexdigest()


def lock_name():
    return 'recruitment-state-' + hashlib.sha256(environment().encode()).hexdigest()[:40]


def object_key(digest):
    return 'recruitment-workbench/' + environment() + '/objects/' + digest


def relative_path(value):
    if not isinstance(value, str) or '\\' in value:
        raise ValueError('Invalid saved recruitment path')
    path = PurePosixPath(value)
    if (path.is_absolute() or '..' in path.parts or not path.parts
            or path.parts[0] not in ROOTS or len(path.parts) < 2):
        raise ValueError('Invalid saved recruitment path')
    return path


class Repository:
    def __init__(self, write=False, wait=0):
        self.connection = mysql_connection(config.ADMIN_DATABASE_URL)
        self.write = write
        self.owns = False
        try:
            with self.connection.cursor() as cursor:
                if write:
                    cursor.execute('SELECT GET_LOCK(%s, %s) AS acquired', (lock_name(), wait))
                    if cursor.fetchone()['acquired'] != 1:
                        raise Busy()
                    self.owns = True
                cursor.execute('SELECT CONNECTION_ID() AS id')
                self.connection_id = cursor.fetchone()['id']
        except BaseException:
            self.connection.close()
            raise

    def read(self):
        with self.connection.cursor() as cursor:
            cursor.execute('SELECT revision, document FROM sigma_recruitment_state WHERE environment=%s', (environment(),))
            row = cursor.fetchone()
            cursor.execute('SELECT IS_USED_LOCK(%s) AS owner', (lock_name(),))
            owner = cursor.fetchone()['owner']
        self.connection.commit()
        return (row['revision'], json.loads(row['document']), owner) if row else (0, {'files': {}}, owner)

    def save(self, revision, document):
        if not self.owns:
            raise RuntimeError('Recruitment writer does not own state lock')
        encoded = json.dumps(document, ensure_ascii=False, separators=(',', ':'))
        try:
            with self.connection.cursor() as cursor:
                cursor.execute('SELECT IS_USED_LOCK(%s) = CONNECTION_ID() AS owned', (lock_name(),))
                if cursor.fetchone()['owned'] != 1:
                    raise RuntimeError('Recruitment writer lost ownership')
                if revision:
                    cursor.execute('UPDATE sigma_recruitment_state SET revision=%s, document=%s WHERE environment=%s AND revision=%s',
                                   (revision + 1, encoded, environment(), revision))
                    if cursor.rowcount != 1:
                        raise RuntimeError('Recruitment state version changed')
                else:
                    cursor.execute('INSERT INTO sigma_recruitment_state(environment,revision,document) VALUES (%s,%s,%s)',
                                   (environment(), 1, encoded))
                cursor.execute('INSERT INTO sigma_recruitment_versions(environment,revision,document) VALUES (%s,%s,%s)',
                               (environment(), revision + 1, encoded))
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise

    def close(self):
        self.connection.close()  # Connection lifetime owns GET_LOCK; no expiring lease.


class Session:
    def __init__(self, write=False, wait=0, job_id=None):
        self.write, self.wait, self.job_id = write, wait, job_id
        self.repo = None
        self.temporary = None
        self.last_progress = 0

    def open(self):
        try:
            self.repo = Repository(self.write, self.wait)
            self.revision, self.document, self.lock_owner = self.repo.read()
            files = self.document.get('files')
            if not isinstance(files, dict) or len(files) > 50000:
                raise ValueError('Invalid recruitment manifest')
            self.temporary = TemporaryDirectory(prefix='recruitment-state-')
            self.root = Path(self.temporary.name)
            cache = config.OUTPUT_DIR / 'recruitment_object_cache' / environment()
            cache.mkdir(parents=True, exist_ok=True, mode=0o700)
            total = 0
            for name, entry in files.items():
                relative = relative_path(name)
                digest, size = entry.get('sha256'), entry.get('size')
                if (not isinstance(digest, str) or not re.fullmatch('[a-f0-9]{64}', digest)
                        or type(size) is not int or not 0 <= size <= MAX_FILE):
                    raise ValueError('Invalid recruitment object descriptor')
                total += size
                if total > MAX_TOTAL:
                    raise ValueError('Recruitment workspace exceeds the verified size limit')
                cached = cache / digest
                content = cached.read_bytes() if cached.is_file() else None
                if content is None or len(content) != size or hashlib.sha256(content).hexdigest() != digest:
                    content = obs_get_bytes(object_key(digest))
                    if content is None or len(content) != size or hashlib.sha256(content).hexdigest() != digest:
                        raise ValueError('Saved recruitment object is missing or corrupt')
                    temporary = cached.with_name(digest + '.' + self.root.name + '.tmp')
                    temporary.write_bytes(content); temporary.chmod(0o600)
                    os.replace(temporary, cached)
                target = self.root / relative
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                target.write_bytes(content); target.chmod(0o600)
            return self
        except BaseException:
            self.close()
            raise

    def publish(self, active=False):
        if not self.write:
            return
        files, total = {}, 0
        previous = self.document.get('files', {})
        for folder in ROOTS:
            for path in sorted((self.root / folder).rglob('*')):
                if path.is_symlink():
                    raise ValueError('Recruitment storage cannot contain external links')
                if not path.is_file() or path.name.startswith('.') or path.name.endswith('.tmp'):
                    continue
                content = path.read_bytes(); total += len(content)
                if len(content) > MAX_FILE or total > MAX_TOTAL:
                    raise ValueError('Recruitment workspace exceeds the verified size limit')
                name = path.relative_to(self.root).as_posix()
                digest = hashlib.sha256(content).hexdigest()
                entry = {'sha256': digest, 'size': len(content)}
                if previous.get(name) != entry:
                    obs_put_bytes(object_key(digest), content, content_type='application/octet-stream')
                files[name] = entry
        document = {'version': 1, 'files': files}
        if active and self.job_id:
            document.update(activeJobId=self.job_id, writerConnectionId=self.repo.connection_id)
        if document != self.document:
            # All immutable objects exist before the SQL pointer becomes visible.
            self.repo.save(self.revision, document)
            self.revision += 1
            self.document = document
        self.last_progress = time.monotonic()

    def close(self):
        if self.repo:
            self.repo.close(); self.repo = None
        if self.temporary:
            self.temporary.cleanup(); self.temporary = None


def progress(force=False):
    session = SESSION.get()
    if session and session.write and (force or time.monotonic() - session.last_progress >= 2):
        session.publish(active=True)


def job_active(identifier):
    session = SESSION.get()
    return bool(session and session.document.get('activeJobId') == identifier
                and session.lock_owner == session.document.get('writerConnectionId'))


def logical_path(path):
    session = SESSION.get()
    if session and Path(path).is_relative_to(session.root):
        return config.OUTPUT_DIR / Path(path).relative_to(session.root)
    return Path(path)


def run_background(fn, job_id=None, wait=0):
    if not enabled():
        return fn()
    # A copied request ContextVar belongs to a completed temporary working copy.
    token = SESSION.set(None)
    session = None
    try:
        session = Session(write=True, wait=wait, job_id=job_id).open()
        SESSION.set(session)
        result = fn()
        session.publish()
        return result
    finally:
        SESSION.reset(token)
        if session: session.close()


def request_cancel(identifier):
    if not isinstance(identifier, str) or not re.fullmatch('[a-f0-9]{32}', identifier):
        raise ValueError('Invalid preparation job')
    connection = mysql_connection(config.ADMIN_DATABASE_URL)
    try:
        with connection.cursor() as cursor:
            cursor.execute('INSERT IGNORE INTO sigma_recruitment_cancellations(environment,job_id) VALUES (%s,%s)',
                           (environment(), identifier))
        connection.commit()
    finally:
        connection.close()


class Cancellation:
    def __init__(self, identifier, local):
        self.identifier, self.local = identifier, local
        self.last_check, self.stopped = 0, False

    def is_set(self):
        if self.stopped or self.local and self.local.is_set():
            return True
        if time.monotonic() - self.last_check < 1:
            return False
        connection = mysql_connection(config.ADMIN_DATABASE_URL)
        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT job_id FROM sigma_recruitment_cancellations WHERE environment=%s AND job_id=%s',
                               (environment(), self.identifier))
                self.stopped = bool(cursor.fetchone())
        finally:
            connection.close()
        self.last_check = time.monotonic()
        return self.stopped


async def materialize(response):
    if isinstance(response, FileResponse):
        content = await run_in_threadpool(Path(response.path).read_bytes)
    elif isinstance(response, StreamingResponse):
        chunks, size = [], 0
        async for chunk in response.body_iterator:
            if isinstance(chunk, str): chunk = chunk.encode()
            size += len(chunk)
            if size > MAX_FILE:
                raise HTTPException(413, '导出文件超过当前验证的大小限制。')
            chunks.append(chunk)
        content = b''.join(chunks)
    else:
        return response
    if len(content) > MAX_FILE:
        raise HTTPException(413, '导出文件超过当前验证的大小限制。')
    return Response(content, status_code=response.status_code, headers=dict(response.headers),
                    media_type=response.media_type, background=response.background)


class PersistentRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()
        async def handler(request):
            if not enabled():
                return await original(request)
            write = request.method not in {'GET', 'HEAD', 'OPTIONS'} and not request.url.path.endswith('/prepare/cancel')
            session = None
            token = None
            try:
                session = await run_in_threadpool(Session(write=write).open)
                token = SESSION.set(session)
                response = await materialize(await original(request))
                if response.status_code < 400:
                    await run_in_threadpool(session.publish)
                return response
            except Busy:
                raise HTTPException(409, '资料同步或保存正在进行，可继续查看；完成后再提交修改。') from None
            except HTTPException:
                raise
            except Exception as exc:
                LOG.error('Recruitment persistence unavailable (%s)', type(exc).__name__)
                raise HTTPException(503, '招聘资料持久化暂不可用，本次修改未确认保存，请刷新核实后重试。') from None
            finally:
                if token is not None: SESSION.reset(token)
                if session: await run_in_threadpool(session.close)
        return handler

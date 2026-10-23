"""Outbound Ego intake over existing workbench HTTPS and user authentication."""
from contextlib import contextmanager
import hashlib
import json
import secrets
import time
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request

from .. import config
from ..auth import current_user_from_request, user_can_enter_module
from .mysql_db import mysql_connection
from .recruitment_persistence import SESSION, environment, object_key
from .labor.obs_storage import obs_get_bytes, obs_put_bytes

MAX_RESPONSE = 32 * 1024 * 1024

router = APIRouter(prefix='/api/recruitment/browser-worker', tags=['recruitment-browser-worker'])


@contextmanager
def connection():
    db = mysql_connection(config.ADMIN_DATABASE_URL)
    try:
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def actor(request):
    current = current_user_from_request(request)
    if not current:
        raise HTTPException(401, '请先登录招聘工作台。')
    if not user_can_enter_module(current, 'recruitment'):
        raise HTTPException(403, '无权使用招聘取数任务。')
    return str(current.get('user', {}).get('id', ''))


def enqueue(month, numbers, codes):
    from .recruitment_overseas import _month, _numbers
    _month(month)
    query = {'month':month,'jobNumbers':_numbers(numbers),'offerCodes':_numbers(codes)}
    if any(len(query[k]) > 5000 for k in ('jobNumbers','offerCodes')):
        raise ValueError('本次海外查询范围过大')
    session = SESSION.get()
    identifier = uuid4().hex
    key = hashlib.sha256(((session.job_id if session else identifier) + json.dumps(query, sort_keys=True)).encode()).hexdigest()
    with connection() as db, db.cursor() as cursor:
        cursor.execute('INSERT IGNORE INTO sigma_recruitment_browser_jobs(environment,id,request_key,request_document,status,document,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s)',
                       (environment(),identifier,key,json.dumps(query),'pending','{}',time.time()))
        cursor.execute('SELECT id FROM sigma_recruitment_browser_jobs WHERE environment=%s AND request_key=%s', (environment(),key))
        return cursor.fetchone()['id']


def get(identifier):
    with connection() as db, db.cursor() as cursor:
        cursor.execute('SELECT status,document,claims FROM sigma_recruitment_browser_jobs WHERE environment=%s AND id=%s',
                       (environment(),identifier))
        row = cursor.fetchone()
        if not row: raise ValueError('海外取数任务不存在')
        return {**row,'document':json.loads(row['document'])}


class QueuedClient:
    def fetch(self, month, job_numbers=(), offer_codes=(), progress=None):
        from .recruitment_cancellation import checkpoint, PreparationCancelled
        from .recruitment_overseas import validate_snapshot
        identifier = enqueue(month,job_numbers,offer_codes)
        deadline, message, last_report = time.monotonic()+900, '', 0
        while time.monotonic() < deadline:
            try:
                checkpoint()
            except PreparationCancelled:
                with connection() as db, db.cursor() as cursor:
                    cursor.execute("UPDATE sigma_recruitment_browser_jobs SET status='failed',document=%s WHERE environment=%s AND id=%s AND status IN ('pending','running')",
                                   (json.dumps({'message':'海外取数已停止，原资料保留'}),environment(),identifier))
                raise
            row = get(identifier); document = row['document']
            if row['status'] == 'completed':
                content = obs_get_bytes(document['objectKey'])
                if content is None or hashlib.sha256(content).hexdigest() != document['sha256']:
                    raise ValueError('海外取数结果校验失败，原资料保留')
                return validate_snapshot(json.loads(content),month)
            if row['status'] == 'failed':
                raise ValueError(document.get('message','海外取数未完成，原资料保留'))
            latest = document.get('message') or ('等待已登录的 Ego 取数端领取任务' if row['status']=='pending' else '海外 Ego 取数端正在读取资料')
            if progress and (latest != message or time.monotonic()-last_report >= 5):
                progress(latest); message = latest; last_report = time.monotonic()
            time.sleep(2)
        with connection() as db, db.cursor() as cursor:
            cursor.execute("UPDATE sigma_recruitment_browser_jobs SET status='failed',document=%s WHERE environment=%s AND id=%s AND status IN ('pending','running')",
                           (json.dumps({'message':'等待海外取数端超时，请确认 Ego 在线且已登录；原资料保留'}),environment(),identifier))
        raise ValueError('等待海外取数端超时，请确认 Ego 在线且已登录；原资料保留')


@router.post('/claim')
def claim(request:Request):
    user = actor(request)
    with connection() as db, db.cursor() as cursor:
        cursor.execute('SELECT id,request_document FROM sigma_recruitment_browser_jobs WHERE environment=%s AND claims<3 AND (status=%s OR (status=%s AND lease_until<UNIX_TIMESTAMP())) ORDER BY created_at LIMIT 1 FOR UPDATE',
                       (environment(),'pending','running'))
        row=cursor.fetchone()
        if not row: return {'job':None}
        token=secrets.token_urlsafe(32)
        cursor.execute("UPDATE sigma_recruitment_browser_jobs SET status='running',lease_token=%s,lease_until=UNIX_TIMESTAMP()+300,claims=claims+1,document=%s WHERE environment=%s AND id=%s",
                       (token,json.dumps({'workerUserId':user,'message':'海外 Ego 取数端已领取任务'}),environment(),row['id']))
        return {'job':{'id':row['id'],'lease':token,**json.loads(row['request_document'])}}


def owned(cursor, identifier, token):
    if not isinstance(token,str) or len(token)>100:
        raise HTTPException(409, '取数任务租约已失效。')
    cursor.execute("SELECT request_document,document FROM sigma_recruitment_browser_jobs WHERE environment=%s AND id=%s AND status='running' AND lease_token=%s AND lease_until>=UNIX_TIMESTAMP() FOR UPDATE",
                   (environment(),identifier,token))
    row=cursor.fetchone()
    if not row: raise HTTPException(409, '取数任务租约已失效。')
    return json.loads(row['request_document']),json.loads(row['document'])


@router.post('/{identifier}/progress')
def heartbeat(identifier:str,payload:dict,request:Request):
    actor(request)
    message=payload.get('message')
    if not isinstance(message,str) or len(message)>180:
        raise HTTPException(400, '取数进度格式无效。')
    with connection() as db, db.cursor() as cursor:
        _, document=owned(cursor,identifier,payload.get('lease'))
        document['message']=message
        cursor.execute('UPDATE sigma_recruitment_browser_jobs SET document=%s,lease_until=UNIX_TIMESTAMP()+300 WHERE environment=%s AND id=%s',
                       (json.dumps(document,ensure_ascii=False),environment(),identifier))
    return {'status':'running'}


@router.post('/{identifier}/complete')
def complete(identifier:str,payload:dict,request:Request):
    actor(request)
    from .recruitment_overseas import validate_snapshot, _numbers
    with connection() as db, db.cursor() as cursor:
        query, _=owned(cursor,identifier,payload.get('lease'))
    try:
        value=validate_snapshot(payload.get('snapshot'),query['month'])
        if (_numbers(value['requestedJobNumbers']) != query['jobNumbers']
                or _numbers(value['requestedOfferCodes']) != query['offerCodes']):
            raise ValueError('取数范围与任务不一致')
        content=json.dumps(value,ensure_ascii=False,separators=(',',':')).encode()
        if len(content)>MAX_RESPONSE:raise ValueError('海外快照过大')
    except (ValueError,TypeError,KeyError) as exc:
        raise HTTPException(400,str(exc)) from None
    digest=hashlib.sha256(content).hexdigest();key=object_key(digest)
    obs_put_bytes(key,content,content_type='application/json')
    with connection() as db, db.cursor() as cursor:
        # Recheck fencing after network I/O; no database lock spans the upload.
        _, document=owned(cursor,identifier,payload.get('lease'))
        document.update(objectKey=key,sha256=digest,message='海外资料已完整回传')
        cursor.execute("UPDATE sigma_recruitment_browser_jobs SET status='completed',document=%s WHERE environment=%s AND id=%s",
                       (json.dumps(document,ensure_ascii=False),environment(),identifier))
    return {'status':'completed'}


@router.post('/{identifier}/fail')
def failed(identifier:str,payload:dict,request:Request):
    actor(request)
    messages={'LOGIN_REQUIRED':'海外登录已失效，请在 Ego 登录 HRMS 和 OEHR，原资料保留',
              'CONTROL_RELEASED':'海外取数端已暂停，原资料保留','CANCELLED':'海外取数已停止，原资料保留'}
    with connection() as db, db.cursor() as cursor:
        _,document=owned(cursor,identifier,payload.get('lease'))
        document['message']=messages.get(payload.get('code'),'海外接口未完整返回，原资料保留')
        cursor.execute("UPDATE sigma_recruitment_browser_jobs SET status='failed',document=%s WHERE environment=%s AND id=%s",
                       (json.dumps(document,ensure_ascii=False),environment(),identifier))
    return {'status':'failed'}

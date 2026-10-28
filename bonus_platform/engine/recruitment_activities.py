"""Local calculation activities. Independent files, not an authorization layer."""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
from tempfile import TemporaryDirectory
from uuid import uuid4

from .recruitment_time import now as recruitment_now
from .recruitment_drafts import DraftStore, DraftConflict

ACTIVITY=ContextVar('recruitment_activity',default='')


@lru_cache(maxsize=256)
def _saved_summary(path,stamp):
    state=json.loads(Path(path).read_text())
    return {'month':state['month'],'revision':state['revision'],'people':len(state['rows']),
            'sources':len(state['sources']),'updatedAt':state.get('updatedAt','')}


def _draft_summary(path,month):
    if not path.is_file():return {'month':month,'revision':0,'people':0,'sources':0,'updatedAt':''}
    stamp=path.stat()
    # Atomic replacements and in-place edits both invalidate this small cache.
    return _saved_summary(str(path),(stamp.st_dev,stamp.st_ino,stamp.st_size,stamp.st_mtime_ns,stamp.st_ctime_ns))


def activity_url(identifier,month,trial=''):
    return f'recruitment.html?activity={identifier}&month={month//100}-{month%100:02d}'+('&trial='+trial if trial else '')


class ActivityStore:
    @property
    def activity_root(self):return self.base_root.parent/'recruitment_activities'

    def activity(self,identifier):
        if not isinstance(identifier,str) or not re.fullmatch('[a-f0-9]{32}',identifier):raise ValueError('核算活动不存在')
        path=self.activity_root/identifier/'activity.json'
        if not path.is_file():raise ValueError('核算活动不存在')
        return json.loads(path.read_text())

    @contextmanager
    def activity_lock(self,identifier,exclusive=False):
        self.activity(identifier)
        with (self.activity_root/identifier/'.activity-lock').open('a') as lock:
            try:fcntl.flock(lock, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)|fcntl.LOCK_NB)
            except BlockingIOError:raise DraftConflict('活动正在更新，请稍后重试') from None
            try:yield self.activity(identifier)
            finally:fcntl.flock(lock,fcntl.LOCK_UN)

    def create_activity(self,month,name='',opening=None,creator=None):
        if type(month) is not int:raise ValueError('请选择核算月份')
        DraftStore(self.base_root)._folder(month)
        if not isinstance(name,str) or len(name)>60:raise ValueError('活动名称不能超过60字')
        now=recruitment_now().isoformat(timespec='seconds')
        item={'id':uuid4().hex,'month':month,'name':name.strip() or f'{month//100}年{month%100}月招聘与内推奖金',
              'createdAt':now,'updatedAt':now,'archived':False,'version':1,
              'creator':{key:str((creator or {}).get(key) or '') for key in ('userId','name','avatarUrl')}}
        self.activity_root.mkdir(parents=True,exist_ok=True)
        with TemporaryDirectory(prefix='.create-',dir=self.activity_root) as temporary:
            staged=Path(temporary)/'activity';target=DraftStore(staged/'drafts')
            state=target.read(month);state.update(strictInputs=True,settlement={'version':1},monthlyWorkflow=True)
            target._write(target._folder(month)/'draft.json',state)
            if opening is not None:
                if not isinstance(opening,dict) or set(opening)!={'activityId','revision'}:raise ValueError('请选择上月已确认活动')
                previous=(month//100-1)*100+12 if month%100==1 else month-1
                with self.activity_lock(opening['activityId']) as parent_item:
                    if parent_item['month']!=previous:raise ValueError('只能承接紧邻上月的已确认活动')
                    origin=DraftStore(self.activity_root/parent_item['id']/'drafts')
                    with origin._lock(previous) as folder:
                        receipt=folder/'accepted.json'
                        if not receipt.exists():raise ValueError('所选活动尚未确认')
                        accepted=json.loads(receipt.read_text());parent=accepted['state']
                        if type(opening['revision']) is not int or accepted['revision']!=opening['revision']:raise DraftConflict('上月确认结果已更新，请重新选择')
                        if parent['month']!=previous or parent['revision']!=accepted['revision']:raise ValueError('上月确认记录不完整')
                        for source in parent['sources']:
                            for category,filename in [('sources',source['storedName']),('parsed',source['id']+'.json')]:
                                if Path(filename).name!=filename:raise ValueError('资料路径无效')
                                raw=folder/category/filename
                                if raw.is_symlink():raise ValueError('资料不能是外部链接')
                                if not raw.is_file():
                                    if category=='parsed' and source.get('error'):continue
                                    raise ValueError('上月确认资料不完整，请先补齐')
                                dest=target._folder(previous)/category/filename;dest.parent.mkdir(parents=True,exist_ok=True)
                                shutil.copy2(raw,dest)
                        target._write(target._folder(previous)/'accepted.json',accepted)
                        target.carry_forward(month,previous,0)
                        item['opening']={'activityId':parent_item['id'],'name':parent_item['name'],'month':previous,'revision':accepted['revision']}
            from .recruitment_snapshot_library import SnapshotLibrary
            item['snapshotSources']=SnapshotLibrary(self).adopt(target,month)
            self._write(staged/'activity.json',item)
            os.replace(staged,self.activity_root/item['id'])
        return item

    def update_activity(self,identifier,payload):
        if not isinstance(payload,dict) or not set(payload)<= {'name','archived','version'}:raise ValueError('只可修改活动名称或归档状态')
        with self.activity_lock(identifier,exclusive=True) as item:
            if type(payload.get('version')) is not int or payload['version']!=item['version']:raise DraftConflict('活动已更新，请刷新列表后再修改')
            if 'name' in payload:
                name=payload['name']
                if not isinstance(name,str) or not name.strip() or len(name)>60:raise ValueError('请填写不超过60字的活动名称')
                item['name']=name.strip()
            if 'archived' in payload:
                if type(payload['archived']) is not bool:raise ValueError('归档状态无效')
                from .recruitment_prepare import RUNNING
                folder=self.activity_root/identifier
                from .recruitment_persistence import logical_path
                if payload['archived'] and any(Path(key).is_relative_to(logical_path(folder)) for key in RUNNING):
                    raise DraftConflict('资料正在整理，完成后再归档')
                item['archived']=payload['archived']
            item.update(version=item['version']+1,updatedAt=recruitment_now().isoformat(timespec='seconds'))
            self._write(self.activity_root/identifier/'activity.json',item)
        return item

    def activity_summary(self,item):
        from .recruitment_prepare import read_status
        folder=self.activity_root/item['id'];drafts=DraftStore(folder/'drafts')
        state=_draft_summary(drafts._folder(item['month'])/'draft.json',item['month']);receipt=drafts._folder(item['month'])/'accepted-status.json'
        accepted=json.loads(receipt.read_text()) if receipt.exists() else {}
        confirmed=bool(accepted and accepted.get('revision')==state['revision'])
        records=list((folder/'recruitment_trials').glob('*/drafts/*/draft.json'))
        updates=[item['updatedAt'],state.get('updatedAt','')]
        for p in records:updates.append(_draft_summary(p,int(p.parent.name))['updatedAt'])
        jobs=[read_status(drafts,item['month'])]
        for p in records:jobs.append(read_status(DraftStore(p.parents[1]),int(p.parent.name)))
        preparing=any(j and j['status'] in {'running','cancelling'} for j in jobs)
        status='已归档' if item['archived'] else '正在整理' if preparing else '已确认' if confirmed else '核算中' if state['revision'] or records else '未开始'
        return {**item,'people':state['people'],'sources':state['sources'],'records':len(records),
                'updatedAt':max(updates),'status':status,'confirmedRevision':accepted.get('revision'),
                'url':activity_url(item['id'],item['month'])}

    def list_activities(self):
        return sorted((self.activity_summary(json.loads(p.read_text())) for p in self.activity_root.glob('*/activity.json')),
                      key=lambda a:a['updatedAt'],reverse=True)

    def legacy_records(self):
        records=[]
        paths=list(self.base_root.glob('*/draft.json'))+list((self.base_root.parent/'recruitment_trials').glob('*/drafts/*/draft.json'))
        for path in paths:
            state=_draft_summary(path,int(path.parent.name));month=state['month']
            is_trial=path.parent.parent!=self.base_root
            if not is_trial and not (state['revision'] or state['sources']):continue
            metadata=path.parents[2]/'trial.json'
            item=json.loads(metadata.read_text()) if is_trial and metadata.is_file() else {}
            url=f'recruitment.html?month={month//100}-{month%100:02d}'+('&trial='+item['id'] if item else '')
            records.append({'id':item.get('id',str(month)),'month':month,'name':item.get('name') or f'{month//100}年{month%100}月原核算表',
                'updatedAt':state['updatedAt'] or item.get('createdAt',''),'people':state['people'],'sources':state['sources'],
                'status':'原核算记录','legacy':True,'url':url})
        return sorted(records,key=lambda a:(a['month'],a['updatedAt']),reverse=True)

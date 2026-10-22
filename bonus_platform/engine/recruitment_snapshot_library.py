"""Shared monthly HR inputs. Payroll decisions always remain inside activities."""
from contextlib import contextmanager
from datetime import datetime, timedelta
import fcntl
import hashlib
import json
import logging
from pathlib import Path
from threading import Event, RLock, Thread
from zoneinfo import ZoneInfo

from . import recruitment_domestic as domestic, recruitment_overseas as overseas
from .recruitment_cancellation import ACTIVE, PreparationCancelled, checkpoint
from .recruitment_drafts import DraftStore

TZ=ZoneInfo('Asia/Shanghai')
MODULES={'domestic':domestic,'overseas':overseas}
LABELS={'domestic':'国内','overseas':'海外'}
LOG=logging.getLogger(__name__)
REFRESH_GUARD=RLock()


def now():return datetime.now(TZ)


def previous(month):return (month//100-1)*100+12 if month%100==1 else month-1


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


class SnapshotLibrary:
    def __init__(self,store):
        self.store=store
        self.data_root=Path(store.base_root).parent
        self.root=self.data_root/'recruitment_shared_snapshots'
        self.files=DraftStore(self.root)

    def _folder(self,month):
        overseas._month(month)
        return self.root/str(month)

    def _read(self,path,default):
        return json.loads(path.read_text()) if path.is_file() else default

    @contextmanager
    def lock(self,name):
        from .recruitment_runtime import task_lock
        with task_lock(name) as acquired:
            if not acquired:
                yield False
                return
            with self.file_lock(name) as locked:
                yield locked

    @contextmanager
    def file_lock(self,name):
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        with (self.root/name).open('a') as handle:
            try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:
                yield False
                return
            try:yield True
            finally:fcntl.flock(handle,fcntl.LOCK_UN)

    def settings(self):
        return self._read(self.root/'schedule.json',{'enabled':True,'hour':8,'minute':0})

    def configure(self,value):
        if not isinstance(value,dict) or set(value)!={'enabled','hour','minute'}:
            raise ValueError('请填写自动同步开关和北京时间')
        if type(value['enabled']) is not bool or type(value['hour']) is not int or type(value['minute']) is not int or not 0<=value['hour']<=23 or not 0<=value['minute']<=59:
            raise ValueError('定时同步时间无效')
        with self.lock('.settings-lock') as acquired:
            if not acquired:raise ValueError('定时设置正在保存，请重试')
            self.files._write(self.root/'schedule.json',value)
        return self.schedule_status()

    def schedule_status(self,at=None):
        at=(at or now()).astimezone(TZ);settings=self.settings()
        target=at.replace(hour=settings['hour'],minute=settings['minute'],second=0,microsecond=0)
        receipt=self._read(self.root/'daily.json',{})
        if receipt.get('date')==at.date().isoformat() and receipt.get('complete'):target+=timedelta(days=1)
        elif at>target:target=at
        return {**settings,'timezone':'Asia/Shanghai','nextRunAt':target.isoformat(timespec='seconds') if settings['enabled'] else None,
                'lastRun':receipt,'running':bool(getattr(self.store,'snapshot_scheduler_running',False))}

    def current(self,month):
        return self._read(self._folder(month)/'latest.json',{})

    def load(self,month,name,entry):
        # Validate both content integrity and the source/month boundary before adoption.
        payload=self._read(self._folder(month)/'versions'/name/(entry['id']+'.json'),None)
        if payload is None or digest(payload)!=entry['id']:raise ValueError('公共资料快照校验失败，请手动重新同步')
        return MODULES[name].validate_snapshot(payload,month)

    def publish(self,month,name,payload):
        payload=MODULES[name].validate_snapshot(payload,month);identifier=digest(payload)
        manifest=self.current(month);old=manifest.get(name,{})
        content=self._folder(month)/'versions'/name/(identifier+'.json')
        self.files._write(content,payload);content.chmod(0o600)
        entry={'id':identifier,'version':old.get('version',0)+int(old.get('id')!=identifier),
               'queriedAt':payload['queriedAt'],'rosterCount':len(payload['roster']),'offerCount':len(payload['offers'])}
        manifest[name]=entry
        self.files._write(self._folder(month)/'latest.json',manifest)
        return entry

    def status(self,month):
        manifest=self.current(month)
        job=self._read(self._folder(month)/'job.json',{'status':'idle','sources':{}})
        if job['status']=='running':
            with self.lock('.refresh-lock') as acquired:
                if acquired:job={**job,'status':'interrupted','message':'上次同步已中断，上次成功资料保留，可重新同步。'}
        return {'month':month,'snapshots':manifest,'job':job,'schedule':self.schedule_status()}

    def scope(self,month):
        # Read saved facts only. No activity recalculation, updates or manual decisions are copied.
        rows=[];activities=self.data_root/'recruitment_activities'
        for path in activities.glob('*/activity.json'):
            item=json.loads(path.read_text())
            if item['archived']:continue
            draft=path.parent/'drafts'/str(month)/'draft.json'
            if item['month']==month and draft.is_file():rows.extend(json.loads(draft.read_text()).get('rows',[]))
            if item['month']==previous(month):
                accepted=path.parent/'drafts'/str(item['month'])/'accepted.json'
                if accepted.is_file():rows.extend(json.loads(accepted.read_text())['state'].get('rows',[]))
        legacy=self.store.base_root/str(month)/'draft.json'
        if legacy.is_file():rows.extend(json.loads(legacy.read_text()).get('rows',[]))
        return {'month':month,'rows':rows}

    def refresh(self,month,stop=None,started=None):
        folder=self._folder(month)
        with self.lock('.refresh-lock') as acquired:
            if not acquired:raise ValueError('公共资料正在同步，请稍后查看进度')
            token=ACTIVE.set(stop)
            job={'status':'running','startedAt':now().isoformat(timespec='seconds'),'sources':{},'message':'正在同步公共资料'}
            def save(**values):
                job.update(values);self.files._write(folder/'job.json',job)
            try:
                save()
                if started:started.set()
                scope=self.scope(month);payloads={}
                for name,module in MODULES.items():
                    checkpoint();job['sources'][name]={'status':'running'};save(message='正在读取'+LABELS[name]+'公共资料')
                    try:
                        value=module.fetch(month,**module.scope(scope),client=getattr(self.store,name+'_client',None),progress=lambda message:save(message=message))
                        payloads[name]=module.validate_snapshot(value,month)
                        job['sources'][name]={'status':'complete'}
                    except PreparationCancelled:raise
                    except Exception as exc:
                        LOG.warning('Shared %s sync failed (%s)',name,type(exc).__name__)
                        job['sources'][name]={'status':'failed','message':str(exc) if isinstance(exc,ValueError) else '接口未完整返回，请重试'}
                    save()
                # OEHR can identify domestic recipients absent from the domestic roster.
                if 'domestic' in payloads and 'overseas' in payloads:
                    from .recruitment_beisen import fetch_employment
                    value=payloads['domestic']
                    covered={str(h.get('jobNumber','')).lower() for h in value.get('candidateHistories',[])+value.get('recipientHistories',[])}
                    required={r['data']['工号'].lower() for r in payloads['overseas']['roster'] if r['scope']=='lookup' and r['data']['人员来源']=='EHR入职'}
                    missing=sorted(n for n in required-covered if n.startswith('zt'))
                    if missing:
                        try:
                            extra=fetch_employment(missing,client=getattr(self.store,'domestic_client',None))
                            value.setdefault('recipientHistories',[]).extend(extra.get('recipientHistories',[]))
                            value.setdefault('employeeMappings',[]).extend(extra.get('employeeMappings',[]))
                            value['requestedRecipientJobNumbers']=sorted(set(value.get('requestedRecipientJobNumbers',[]))|set(missing))
                            from .recruitment_beisen import sync_coverage
                            value['syncCoverage']=sync_coverage(value)
                        except PreparationCancelled:raise
                        except Exception:
                            payloads.pop('domestic')
                            job['sources']['domestic']={'status':'failed','message':'关联领取人资料未完整返回，上次成功快照保留'}
                for name,value in payloads.items():
                    checkpoint();entry=self.publish(month,name,value)
                    job['sources'][name].update(entry)
                failed=any(s['status']=='failed' for s in job['sources'].values())
                save(status='failed' if failed else 'complete',finishedAt=now().isoformat(timespec='seconds'),
                     message='部分资料同步失败，上次成功快照保留。' if failed else '公共资料已更新，新建活动可直接使用。')
            except PreparationCancelled:
                save(status='interrupted',message='同步已停止，上次成功快照保留。')
            except Exception:
                save(status='failed',message='公共资料保存未完成，上次成功版本保留。')
                LOG.exception('Shared snapshot refresh failed')
            finally:ACTIVE.reset(token)
        return self.status(month)

    def adopt(self,target,month):
        entries=self.current(month);adopted={}
        # Capture this manifest once so a concurrent refresh cannot change the selection halfway.
        for name,entry in entries.items():
            payload=self.load(month,name,entry);state=target.read(month)
            action=target.save_beisen_snapshot if name=='domestic' else target.save_overseas_snapshot
            result=action(month,state['revision'],payload)
            adopted[name]={**entry,'adoptedAt':now().isoformat(timespec='seconds'),'revision':result['revision']}
        return adopted

    def months(self,at):
        current=at.year*100+at.month;months={current,previous(current)}
        for path in (self.data_root/'recruitment_activities').glob('*/activity.json'):
            item=json.loads(path.read_text())
            receipt=path.parent/'drafts'/str(item['month'])/'accepted-status.json'
            state=path.parent/'drafts'/str(item['month'])/'draft.json'
            accepted=self._read(receipt,{})
            revision=self._read(state,{}).get('revision',0)
            if not item['archived'] and item['month']<=current and accepted.get('revision')!=revision:months.add(item['month'])
        return sorted(months,reverse=True)

    def tick(self,at=None,stop=None):
        at=(at or now()).astimezone(TZ);settings=self.settings()
        if not settings['enabled'] or (at.hour,at.minute)<(settings['hour'],settings['minute']):return False
        with self.lock('.daily-lock') as acquired:
            if not acquired:return False
            receipt=self._read(self.root/'daily.json',{})
            same_day=receipt.get('date')==at.date().isoformat()
            if same_day and receipt.get('complete'):return False
            outcomes=dict(receipt.get('months',{})) if same_day else {}
            for month in self.months(at):
                if stop and stop.is_set():return False
                if str(month) in outcomes:continue
                try:outcomes[str(month)]=self.refresh(month,stop)['job']['status']
                except ValueError:return False # A manual refresh owns the single flight; retry next tick.
                if stop and stop.is_set():return False
                self.files._write(self.root/'daily.json',{'date':at.date().isoformat(),'complete':False,'months':outcomes})
            self.files._write(self.root/'daily.json',{'date':at.date().isoformat(),'complete':True,'finishedAt':now().isoformat(timespec='seconds'),'months':outcomes})
            return True


class SnapshotScheduler:
    """Service-owned daily worker. Restart catches up once after the configured time."""
    def __init__(self,store):
        self.library=SnapshotLibrary(store);self.stop=Event();self.thread=None

    def start(self):
        self.library.store.snapshot_scheduler_running=True
        def run():
            while not self.stop.is_set():
                try:self.library.tick(stop=self.stop)
                except Exception:LOG.exception('Shared HR scheduler tick failed')
                self.stop.wait(30)
        self.thread=Thread(target=run,name='recruitment-snapshot-scheduler',daemon=True);self.thread.start()
        return self

    def close(self):
        self.stop.set()
        if self.thread:self.thread.join(timeout=2)
        manual=getattr(self.library.store,'snapshot_refresh_stop',None)
        if manual:manual.set()
        manual_thread=getattr(self.library.store,'snapshot_refresh_thread',None)
        if manual_thread:manual_thread.join(timeout=2)
        self.library.store.snapshot_scheduler_running=False


def start_refresh(store,month):
    library=SnapshotLibrary(store);library._folder(month)
    # Reserve before returning a job receipt; duplicate clicks never spawn another query.
    with REFRESH_GUARD:
        thread=getattr(store,'snapshot_refresh_thread',None)
        if thread and thread.is_alive():raise ValueError('公共资料正在同步，请稍后查看进度')
        started=Event();errors=[];stop=Event()
        def run():
            try:library.refresh(month,stop,started)
            except ValueError as exc:errors.append(str(exc))
            finally:started.set()
        thread=Thread(target=run,name='recruitment-snapshot-manual',daemon=True)
        store.snapshot_refresh_stop=stop
        store.snapshot_refresh_thread=thread;thread.start()
        started.wait(timeout=2)
        if errors:raise ValueError(errors[0])
    return {'status':'running','month':month}

"""Isolated, user-created calculation batches; never copy an answer-filled draft."""
from contextvars import ContextVar
from contextlib import contextmanager
from copy import deepcopy
import filecmp
import json
import os
from pathlib import Path
import re
import shutil
from tempfile import TemporaryDirectory
from uuid import uuid4
from .recruitment_time import now as recruitment_now
from .recruitment_drafts import DraftStore, DraftConflict
from .recruitment_activities import ActivityStore, ACTIVITY, activity_url

TRIAL=ContextVar('recruitment_trial',default='')


def confirmation_blockers(state,store=None):
    """The same eligibility checks for ordinary and adopted monthly results."""
    from .recruitment_awards import ensure_calculated
    from .recruitment_attention import project as attention
    from .recruitment_monthly import project as monthly
    ensure_calculated(state)
    if store:
        from .recruitment_approval_intake import project as approval_project
        state,_=approval_project(store,state)
    result=monthly(state,attention(state))
    blockers=[]
    if not state['rows']:blockers.append('尚未有核算资料')
    elif result['cases'] or result['coverage']['sourceErrors'] or result['coverage']['syncRequired']:
        blockers.append('请先完成资料准备和待确认事项；仍可导出工作稿')
    previous=previous_confirmed(store,state['month']) if store else None
    if previous and state.get('parentMonth')==previous['month'] and state.get('parentRevision')!=previous['revision']:
        blockers.append('上月已确认结果已更新，请按最新上月结果重新核算后再确认')
    return blockers


def require_confirmation(state,coverage_confirmed,store=None):
    blockers=confirmation_blockers(state,store)
    if blockers:raise ValueError(blockers[0])
    if coverage_confirmed is not True:raise ValueError('请确认本月人员和外部资料已完整纳入')


def _monthly_store(store):
    return DraftStore(getattr(store,'default_root',None) or store.root)


def previous_confirmed(store,month):
    previous=(month//100-1)*100+12 if month%100==1 else month-1
    if previous<200001:return None
    path=_monthly_store(store)._folder(previous)/'accepted.json'
    if not path.exists():return None
    accepted=json.loads(path.read_text())
    return {'month':previous,'revision':accepted['revision'],'confirmedAt':accepted['confirmedAt']}


@contextmanager
def previous_confirmation_lock(store,month):
    previous=(month//100-1)*100+12 if month%100==1 else month-1
    if previous<200001:yield
    else:
        # Match carry_forward's previous-before-current lock order. Confirmation
        # then sees one stable accepted parent until its own version is saved.
        with _monthly_store(store)._lock(previous):yield


def next_month_status(store,month,revision):
    following=(month//100+1)*100+1 if month%100==12 else month+1
    canonical=_monthly_store(store);state=canonical.read(following)
    path=canonical._folder(following)/'accepted.json'
    confirmed=json.loads(path.read_text()) if path.exists() else {}
    exists=bool(state['revision'] or state['sources'] or state['rows'])
    return {'month':following,'exists':exists,'parentMonth':state.get('parentMonth'),'parentRevision':state.get('parentRevision'),
            'willNeedRecalculation':exists and state.get('parentMonth')==month and state.get('parentRevision')!=revision,
            'confirmedRevision':confirmed.get('revision')}


def confirmation_message(prefix,following):
    if following['willNeedRecalculation']:
        tail=f"{following['month']%100}月仍引用原结果，请按最新上月结果重新核算"
    elif following['exists']:
        tail=f"已有{following['month']%100}月核算记录保持不变"
    else:tail='下月新建核算可承接此结果'
    return prefix+'；'+tail+'；未标记为已支付。'


def _require_idle(month,*stores):
    from . import recruitment_prepare as jobs
    for store in stores:
        path=store._folder(month)/'prepare.json'
        job=json.loads(path.read_text()) if path.exists() else None
        if jobs.key_for(store,month) in jobs.RUNNING or job and job.get('status')=='running':
            raise DraftConflict('资料正在整理，请完成后再确认本月结果')


def _summary(state,name,folder):
    from .recruitment_attention import project as attention
    from .recruitment_monthly import project as monthly
    from .recruitment_awards import ensure_calculated
    ensure_calculated(state);result=monthly(state,attention(state))
    receipt=folder/'accepted-status.json'
    confirmed=json.loads(receipt.read_text()) if receipt.exists() else {}
    return {'name':name,'month':state['month'],'revision':state['revision'],'people':len(state['rows']),
            'currentPeople':len({n['rowId'] for n in result['nodes'] if n['scope']=='current'}),
            'updatedAt':state.get('updatedAt',''),'confirmedAt':confirmed.get('confirmedAt',''),
            'confirmedRevision':confirmed.get('revision'),'totals':result['totals']}


class ScopedDraftStore(ActivityStore,DraftStore):
    def __init__(self,root):self._base_root=Path(root)
    @property
    def base_root(self):
        from .recruitment_persistence import SESSION
        session=SESSION.get()
        return session.root/"recruitment_drafts" if session else self._base_root
    @property
    def default_root(self):
        return self.activity_root/ACTIVITY.get()/'drafts' if ACTIVITY.get() else self.base_root
    @property
    def root(self):
        return self.default_root.parent/'recruitment_trials'/TRIAL.get()/'drafts' if TRIAL.get() else self.default_root
    @property
    def trial_root(self):return self.default_root.parent/'recruitment_trials'
    def trial(self,identifier):
        if not re.fullmatch('[a-f0-9]{32}',identifier):raise ValueError('试算批次不存在')
        path=self.trial_root/identifier/'trial.json'
        if not path.is_file():raise ValueError('试算批次不存在')
        return json.loads(path.read_text())
    def read(self,month,*,_refresh_changes=None):
        state=super().read(month,_refresh_changes=_refresh_changes)
        if TRIAL.get() and month==self.trial(TRIAL.get())['month']:
            # Archived draft bytes stay unchanged; only their UI identity differs.
            state['trial']=self.trial(TRIAL.get())
        return state
    def create_trial(self,month,name='',opening=None):
        if ACTIVITY.get() and self.activity(ACTIVITY.get())['month']!=month:raise ValueError('请在活动的核算月份内操作')
        self._folder(month)
        if not isinstance(name,str) or len(name)>60:raise ValueError('名称不能超过60字')
        name=name.strip() or f'{month//100}年{month%100}月核算'
        item={'id':uuid4().hex,'month':month,'name':name,'createdAt':recruitment_now().isoformat(timespec='seconds')}
        if opening is not None:return self._create_from_previous(item,opening)
        self._write(self.trial_root/item['id']/'trial.json',item)
        fresh={'month':month,'revision':0,'sources':[],'rows':[],'todos':[],'baseline':'','edits':[],'manualRows':[],
               'parentMonth':None,'parentRevision':None,'paymentReady':False,'summary':{},'updatedAt':'','strictInputs':True,'trial':item,'settlement':{'version':1}}
        self._write(self.trial_root/item['id']/'drafts'/str(month)/'draft.json',fresh)
        return item
    def _create_from_previous(self,item,opening):
        month=item['month'];previous=(month//100-1)*100+12 if month%100==1 else month-1
        if not isinstance(opening,dict) or set(opening)!={'month','revision'} or opening.get('month')!=previous or type(opening.get('revision')) is not int:
            raise ValueError('请选择紧邻上月已确认的核算结果')
        canonical=_monthly_store(self)
        with canonical._lock(previous) as origin:
            path=origin/'accepted.json'
            if not path.exists():raise ValueError('上月尚未确认，请从空表开始或先确认上月结果')
            accepted=json.loads(path.read_text())
            if opening['revision']!=accepted['revision']:
                raise DraftConflict('上月已确认结果已更新，请重新选择后创建')
            parent=accepted['state']
            if parent['month']!=previous or parent['revision']!=accepted['revision']:
                raise ValueError('上月确认记录不完整，请先核对上月结果')
            item.update(parentMonth=previous,parentRevision=accepted['revision'])
            try:
                with TemporaryDirectory(prefix='.recruitment-create-',dir=self.default_root.parent) as temporary:
                    staged=Path(temporary)/'record';folder=staged/'drafts'/str(month)
                    for source in parent['sources']:
                        for category,filename in [('sources',source['storedName']),('parsed',source['id']+'.json')]:
                            if Path(filename).name!=filename:raise ValueError('上月资料路径无效')
                            original=origin/category/filename
                            if original.is_symlink():raise ValueError('上月资料含外部链接，请先核对')
                            if not original.is_file():
                                if category=='parsed' and source.get('error'):continue
                                raise DraftConflict('上月已确认结果的原始资料不完整，请补齐后创建')
                            destination=folder/category/filename;destination.parent.mkdir(parents=True,exist_ok=True)
                            shutil.copy2(original,destination)
                    state=deepcopy(parent)
                    state.update(month=month,revision=0,parentMonth=previous,parentRevision=parent['revision'],redoOperations=[],trial=item,externalImports=[])
                    state.pop('adoptedFrom',None)
                    staged_store=DraftStore(staged/'drafts')
                    staged_store._save(folder,staged_store._rebuild(folder,state))
                    self._write(staged/'trial.json',item)
                    self.trial_root.mkdir(parents=True,exist_ok=True)
                    os.replace(staged,self.trial_root/item['id'])
            except OSError as exc:
                raise ValueError('未能完整承接上月资料，原核算记录保留，请重试') from exc
        return item
    @contextmanager
    def _lock(self,month):
        if TRIAL.get() and month!=self.trial(TRIAL.get())['month']:
            raise ValueError('独立批次的核算月份固定，请另建批次')
        with super()._lock(month) as folder:yield folder
    def list_trials(self):
        return sorted((json.loads(p.read_text()) for p in self.trial_root.glob('*/trial.json')),key=lambda r:r['createdAt'],reverse=True)

    def adoption_preview(self,month,source_revision):
        if not TRIAL.get():raise ValueError('请从需要采用的核算记录打开')
        item=self.trial(TRIAL.get())
        if item['month']!=month:raise ValueError('核算月份不一致')
        source=self.read(month);self._check(source,source_revision)
        target_store=DraftStore(self.default_root);target=target_store.read(month)
        blockers=confirmation_blockers(source,self)
        try:_require_idle(month,self,target_store)
        except DraftConflict as exc:blockers.append(str(exc))
        return {'month':month,'sourceRevision':source['revision'],'targetRevision':target['revision'],
                'source':_summary(source,item['name'],self._folder(month)),
                'target':_summary(target,(target.get('trial') or {}).get('name') or f'{month//100}年{month%100}月核算',target_store._folder(month)),
                'canAdopt':not blockers,'blockers':blockers,'requiresCoverageConfirmation':True,
                'nextMonth':next_month_status(self,month,target['revision']+1),
                'returnUrl':activity_url(ACTIVITY.get(),month) if ACTIVITY.get() else f'recruitment.html?month={month//100}-{month%100:02d}'}

    def adopt_month(self,month,source_revision,target_revision,coverage_confirmed):
        from . import recruitment_prepare as jobs
        if not TRIAL.get():raise ValueError('请从需要采用的核算记录打开')
        if type(source_revision) is not int or type(target_revision) is not int:
            raise DraftConflict('请重新查看新旧核算版本后再采用')
        item=self.trial(TRIAL.get())
        if item['month']!=month:raise ValueError('核算月份不一致')
        source_store=DraftStore(self.root);target_store=DraftStore(self.default_root)
        # start() takes the same guard before registering a preparation task.
        # Lock source and destination before checking either reviewed revision.
        with jobs.GUARD:
            _require_idle(month,source_store,target_store)
            with source_store._lock(month) as source_folder, previous_confirmation_lock(self,month), target_store._lock(month) as target_folder:
                source=source_store.read(month);target=target_store.read(month)
                self._check(source,source_revision);self._check(target,target_revision)
                require_confirmation(source,coverage_confirmed,self)
                return self._commit_adoption(month,item,source,target,source_folder,target_folder)

    def _commit_adoption(self,month,item,source,target,source_folder,target_folder):
        """Stage evidence and a full recovery copy before changing monthly files."""
        now=recruitment_now().isoformat(timespec='seconds');revision=target['revision']+1
        for info in source['sources']:
            raw=source_folder/'sources'/info['storedName']
            parsed=source_folder/'parsed'/(info['id']+'.json')
            if not raw.is_file() or not info.get('error') and not parsed.is_file():
                raise ValueError('原始资料或解析记录缺失，请补齐后再采用')
        if any(p.is_symlink() for folder in (source_folder,target_folder) for p in folder.rglob('*')):
            raise ValueError('资料目录含外部链接，无法完整保存核算依据')
        archive=None
        if (target_folder/'draft.json').exists():
            archive={'id':uuid4().hex,'month':month,'name':f'{month//100}年{month%100}月原核算记录（采用前）',
                     'createdAt':now,'kind':'monthly-archive','archivedRevision':target['revision']}
        adopted=deepcopy(source);adopted.update(revision=revision,updatedAt=now,trial=item)
        adopted['calculation']['draftRevision']=revision
        adopted['adoptedFrom']={'id':item['id'],'name':item['name'],'revision':source['revision'],'adoptedAt':now,
                                'archiveId':archive['id'] if archive else None}
        accepted={'revision':revision,'confirmedAt':now,'state':adopted}
        values={f'revisions/{revision}.json':adopted,'draft.json':adopted,
                'prepare.json':{'id':uuid4().hex,'status':'complete','stage':'complete','startedAt':now,
                                'revision':revision,'message':'已采用并确认本月资料与核算结果'},
                f'accepted/{revision}.json':accepted,'accepted-status.json':{'revision':revision,'confirmedAt':now},
                'accepted.json':accepted}
        try:
            with TemporaryDirectory(prefix='.recruitment-adopt-',dir=self.default_root.parent) as temporary:
                staging=Path(temporary);commit=staging/'commit';before=staging/'before';installed=[];prior=set()
                # The complete original monthly tree includes accepted snapshots,
                # source files, parsed data, history and earlier draft revisions.
                if archive:
                    archived=staging/'archive';shutil.copytree(target_folder,archived/'drafts'/str(month))
                    self._write(archived/'trial.json',archive)
                for name in ('sources','parsed','external-previews'):
                    origin=source_folder/name
                    if origin.exists():shutil.copytree(origin,commit/name)
                materials=sorted(p.relative_to(commit) for p in commit.rglob('*') if p.is_file()) if commit.exists() else []
                changed=[]
                for relative in materials:
                    destination=target_folder/relative
                    if destination.exists():
                        if filecmp.cmp(commit/relative,destination,shallow=False):continue
                        if relative.parts[0]=='sources':raise ValueError('同名原始资料内容不同，请先核对资料')
                    changed.append(relative)
                for relative,value in values.items():self._write(commit/relative,value)
                changed.extend(Path(relative) for relative in values)
                # Backup every overwritten file before the first replacement.
                for relative in changed:
                    destination=target_folder/relative
                    if destination.exists():
                        backup=before/relative;backup.parent.mkdir(parents=True,exist_ok=True)
                        shutil.copy2(destination,backup);prior.add(relative)
                if archive:
                    self.trial_root.mkdir(parents=True,exist_ok=True)
                    os.replace(staging/'archive',self.trial_root/archive['id'])
                try:
                    # Evidence comes first; accepted.json is the final commit.
                    for relative in changed:
                        destination=target_folder/relative;destination.parent.mkdir(parents=True,exist_ok=True)
                        os.replace(commit/relative,destination);installed.append(relative)
                except Exception:
                    for relative in reversed(installed):
                        destination=target_folder/relative
                        if relative in prior:os.replace(before/relative,destination)
                        else:destination.unlink(missing_ok=True)
                    raise
        except OSError as exc:
            raise ValueError('采用未完成，原月度结果和原始资料已保留，请重试') from exc
        url=f'recruitment.html?month={month//100}-{month%100:02d}'
        if ACTIVITY.get():url=activity_url(ACTIVITY.get(),month)
        following=next_month_status(self,month,revision)
        return {'month':month,'revision':revision,'confirmedAt':now,'name':item['name'],'url':url,
                'archive':{**archive,'url':url+'&trial='+archive['id']} if archive else None,
                'nextMonth':following,'message':confirmation_message('已采用并确认本月核算',following)}

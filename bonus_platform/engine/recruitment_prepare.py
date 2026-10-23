"""Resumable UI status for the existing monthly intake; no payroll execution."""
from contextvars import copy_context
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
from threading import Event, RLock
from uuid import uuid4

from .recruitment_cancellation import ACTIVE, PreparationCancelled, checkpoint

POOL=ThreadPoolExecutor(max_workers=2,thread_name_prefix='recruitment-intake')
RUNNING={}
CANCELLATIONS={}
GUARD=RLock()


def key_for(store,month):
    from .recruitment_persistence import logical_path
    return str(logical_path(store._folder(month)/'prepare.json'))


def coverage_gaps(state,month):
    from .recruitment_beisen import coverage_sets
    from .recruitment_drafts import staff_id
    from .recruitment_attention import recipient_requirements, is_current, applicable, intake_fields, needed
    from .recruitment_awards import present
    offer_needs=set();employment_needs=set()
    for row in state['rows']:
        v=row['values'];number=staff_id(v.get('工号'))
        current={kind for kind in ('recruitment','referral') if applicable(row,kind) and is_current(row,kind,month,set())}
        if not current or v.get('标签分类')!='国内' or v.get('是否虚拟员工')=='是' or not number:continue
        if not row.get('offerMatched') and intake_fields(row,month):offer_needs.add(number)
        if any(not present(v.get(field)) and current.intersection(needed(row,field,month)) for field in ('入职日期','人员状态')):employment_needs.add(number)
    coverage=coverage_sets([s for s in state['sources'] if s.get('kind')=='beisen' and s.get('forMonth')==month])
    matched={staff_id(r['values'].get('工号')) for r in state['rows'] if r.get('offerMatched')}
    return ([{'role':'候选人','employee':n,'reason':'未取得任职资料'} for n in sorted(employment_needs-coverage['candidateEmployment'])]
            +recipient_requirements(state,month)['coverageGaps']
            +[{'role':'候选人','employee':n,'reason':'未取得有效录用资料'} for n in sorted(offer_needs-coverage['candidateOffer']-matched)])


def coverage_message(gaps):
    return '；'.join(f'{count} 名{role}{reason}' for (role,reason),count in Counter((g['role'],g['reason']) for g in gaps).items()) if gaps else '资料已整理，核算已更新。'


def read_status(store,month):
    """Read the job receipt without opening or recalculating its draft."""
    path=store._folder(month)/'prepare.json'
    with GUARD:
        if not path.exists():return None
        data=json.loads(path.read_text())
        from .recruitment_persistence import job_active
        if data['status'] in {'running','cancelling'} and key_for(store,month) not in RUNNING and not job_active(data.get('id')):
            return {**data,'status':'interrupted','message':'准备任务已中断，已有资料保留，可重新准备。'}
        return data


def read(store,month):
    data=read_status(store,month)
    if data is None:return None
    if data['status']=='complete' and not any(data.get(flag) for flag in ('overseasOnly','domesticOnly','monthlyAll')):
        state=store.read(month)
        if state['revision']:
            gaps=coverage_gaps(state,month)
            return {**data,'coverageGaps':gaps,'coverageRevision':state['revision'],'message':coverage_message(gaps)}
    return data


def start(store,month,revision,force=False,local_only=False,include_overseas=False,overseas_only=False,domestic_only=False,monthly_all=False):
    if local_only and (include_overseas or overseas_only or domestic_only or monthly_all):raise ValueError('重新读取已保存资料不能同时查询外部接口')
    if monthly_all and (overseas_only or domestic_only):raise ValueError('同步范围不能同时指定全部与单一来源')
    key=key_for(store,month)
    with GUARD:
        if key in RUNNING:return read(store,month)
        state=store.read(month);store._check(state,revision)
        job={'id':uuid4().hex,'status':'running','stage':'sync' if overseas_only or domestic_only or monthly_all else 'refresh',
             'message':'正在同步本月国内及海外资料' if monthly_all else '正在读取本月国内花名册和 Offer' if domestic_only else '正在读取本月海外花名册和 Offer' if overseas_only else '正在整理已保存的资料',
             'startedAt':datetime.now().isoformat(timespec='seconds'),'revision':revision,'localOnly':local_only,
             'includeOverseas':include_overseas,'overseasOnly':overseas_only,'domesticOnly':domestic_only,'monthlyAll':monthly_all}
        if monthly_all:job['syncResults']={name:{'status':'pending'} for name in ('domestic','overseas')}
        store._write(store._folder(month)/'prepare.json',job)
        RUNNING[key]=job['id']
        CANCELLATIONS[key]=(job['id'],Event())
        context=copy_context()
        POOL.submit(context.run,run,store,month,job,force,key,local_only,include_overseas,overseas_only,domestic_only,monthly_all)
        return dict(job)


def cancel(store,month,job_id):
    key=key_for(store,month)
    with GUARD:
        path=store._folder(month)/'prepare.json'
        if not path.exists():raise ValueError('未找到资料准备任务')
        job=json.loads(path.read_text())
        if not job_id or job.get('id')!=job_id:raise ValueError('资料准备任务已变化，请刷新后重试')
        if job['status'] not in {'running','cancelling'}:return job
        from .recruitment_persistence import enabled, request_cancel, job_active
        if enabled() and job_active(job_id):
            request_cancel(job_id)
            return {**job,'status':'cancelling','message':'正在停止，已保存的资料保留'}
        active=CANCELLATIONS.get(key)
        if RUNNING.get(key)!=job_id or not active or active[0]!=job_id:
            return {**job,'status':'interrupted','message':'准备任务已中断，已有资料保留，可重新准备。'}
        active[1].set()
        job.update(status='cancelling',message='正在停止，已保存的资料保留')
        store._write(path,job)
        return job


def run(store,month,job,force,key,local_only=False,include_overseas=False,overseas_only=False,domestic_only=False,monthly_all=False):
    from .recruitment_persistence import run_background
    return run_background(lambda:_run(store,month,job,force,key,local_only,include_overseas,overseas_only,domestic_only,monthly_all),job_id=job.get('id'),wait=15)


def _run(store,month,job,force,key,local_only=False,include_overseas=False,overseas_only=False,domestic_only=False,monthly_all=False):
    from .recruitment_beisen import fetch, fetch_employment, fetch_channel_details, coverage_sets, CHANNEL
    from .recruitment_drafts import staff_id
    from .recruitment_attention import recipient_requirements
    from .recruitment_trials import TRIAL
    active=CANCELLATIONS.get(key)
    from .recruitment_persistence import enabled, Cancellation, progress
    event=active[1] if active and active[0]==job.get('id') else None
    context_token=ACTIVE.set(Cancellation(job['id'],event) if enabled() else event)
    def save(**values):
        with GUARD:
            if values.get('status')!='cancelled':checkpoint()
            job.update(values);store._write(store._folder(month)/'prepare.json',job)
            if values.get('status') in {'complete','failed','cancelled'} and RUNNING.get(key)==job.get('id'):
                RUNNING.pop(key,None);CANCELLATIONS.pop(key,None)
        progress(force=values.get('status') in {'complete','failed','cancelled'})
    try:
        checkpoint()
        if not store.read(month)['revision']:
            previous=(month//100-1)*100+12 if month%100==1 else month-1
            if previous>=200001 and not TRIAL.get():
                if (store._folder(previous)/'accepted.json').exists():
                    checkpoint()
                    state=store.carry_forward(month,previous,0);job['revision']=state['revision']
        checkpoint()
        if monthly_all:
            from . import recruitment_domestic as domestic, recruitment_overseas as overseas
            from .recruitment_drafts import DraftConflict
            results=job['syncResults'];overseas_snapshot=None
            for name,label,module,kind in [('domestic','国内',domestic,'beisen'),('overseas','海外',overseas,'overseas_api')]:
                checkpoint();results[name]={'status':'running'}
                save(stage='sync',syncSource=name,message=f'正在读取本月{label}花名册和 Offer')
                try:
                    state=store.read(month);store._check(state,job['revision'])
                    options=module.scope(state)
                    snapshot=module.fetch(month,**options,client=getattr(store,name+'_client',None),
                                          progress=lambda message:save(message=message))
                    snapshot=module.validate_snapshot(snapshot,month);checkpoint()
                    if name=='overseas':overseas_snapshot=snapshot
                    fingerprint=module.data_digest(snapshot);before=state['revision']
                    action=store.save_beisen_snapshot if name=='domestic' else store.save_overseas_snapshot
                    state=action(month,job['revision'],snapshot);job['revision']=state['revision']
                    source=next(s for s in state['sources'] if s.get('kind')==kind and s.get('forMonth')==month
                                and s.get('dataDigest')==fingerprint and not s.get('error'))
                    results[name]={'status':'complete','sourceId':source['id'],'queriedAt':snapshot['queriedAt'],
                                   'snapshotAt':source['addedAt'],'snapshotVersion':source['snapshotVersion'],
                                   'rosterCount':source['rosterCount'],'offerCount':source['offerCount'],
                                   'snapshotOnly':source['snapshotOnly'],'reused':before==state['revision']}
                    save(message=f'{label}资料已保存')
                except (PreparationCancelled,DraftConflict):raise
                except Exception as exc:
                    checkpoint()
                    message=str(exc) if isinstance(exc,ValueError) else f'{label}接口同步未完成，请重试'
                    results[name]={'status':'failed','message':message}
                    save(message=f'{label}资料未完成：{message}')
            if (overseas_snapshot and results['overseas']['status']=='complete'
                    and not results['overseas']['snapshotOnly']):
                domestic_recipients={staff_id(r['data'].get('工号')) for r in overseas_snapshot['roster']
                                     if r['scope']=='lookup' and r['data'].get('人员来源')=='EHR入职'}
                state=store.read(month);store._check(state,job['revision'])
                covered=coverage_sets([s for s in state['sources'] if s.get('forMonth')==month])['recipientEmployment']
                needed=sorted(n for n in domestic_recipients-covered if n.startswith('zt'))
                if needed:
                    save(stage='sync',syncSource='domestic',message=f'正在补齐海外招聘关联的 {len(needed)} 名国内领取人的任职资料')
                    try:
                        extra=fetch_employment(needed,client=getattr(store,'domestic_client',None));checkpoint()
                        state=store.save_beisen_snapshot(month,job['revision'],extra);job['revision']=state['revision']
                        results['domestic']['relatedEmploymentPeople']=len(needed)
                        save(message='关联领取人的国内任职资料已保存')
                    except (PreparationCancelled,DraftConflict):raise
                    except Exception as exc:
                        checkpoint();message=str(exc) if isinstance(exc,ValueError) else '关联领取人的国内任职资料未完整返回'
                        results['domestic'].update(status='failed',message=message)
            failures=[label for name,label in [('domestic','国内'),('overseas','海外')] if results[name]['status']=='failed']
            if failures:
                details='；'.join(f'{label}：{results[name]["message"]}' for name,label in [('domestic','国内'),('overseas','海外')] if results[name]['status']=='failed')
                save(status='failed',message=f'{"、".join(failures)}资料同步未完成，已取得的资料已保留。{details}')
            else:
                preserved=all(item['snapshotOnly'] or item['reused'] for item in results.values())
                save(status='complete',stage='complete',message='国内及海外资料快照已保存，'+('已有核算与待办保留。' if preserved else '本月核算已更新。'))
            return
        if domestic_only:
            from . import recruitment_domestic as domestic
            snapshot=domestic.fetch(month,**domestic.scope(store.read(month)),client=getattr(store,'domestic_client',None),
                                    progress=lambda message:save(stage='sync',message=message))
            checkpoint();state=store.save_beisen_snapshot(month,job['revision'],snapshot)
            saved=next(s for s in reversed(state['sources']) if s.get('monthlyRoster') and s.get('forMonth')==month)
            message=(f'已保存 {month//100}年{month%100}月国内资料快照，已有核算与待办保留。'
                     if saved['snapshotOnly'] else '国内资料已同步，本月核算已更新。')
            save(status='complete',stage='complete',revision=state['revision'],message=message)
            return
        if include_overseas or overseas_only:
            from . import recruitment_overseas as overseas
            state=store.read(month)
            save(stage='sync',message='正在读取本月海外花名册和 Offer')
            snapshot=overseas.fetch(month,**overseas.scope(state),client=getattr(store,'overseas_client',None),
                                    progress=lambda message:save(stage='sync',message=message))
            checkpoint()
            state=store.save_overseas_snapshot(month,job['revision'],snapshot)
            job['revision']=state['revision'];checkpoint()
            if overseas_only:
                saved=next(s for s in reversed(state['sources']) if s.get('kind')=='overseas_api' and s.get('forMonth')==month)
                message=(f'已保存 {month//100}年{month%100}月海外资料快照，已有核算与待办保留。'
                         if saved['snapshotOnly'] else '海外资料已同步，本月核算已更新。')
                save(status='complete',stage='complete',revision=state['revision'],message=message)
                return
        state=store.refresh(month,job['revision'])
        job['revision']=state['revision'];checkpoint()
        if local_only:
            gaps=coverage_gaps(state,month)
            save(status='complete',stage='complete',revision=state['revision'],coverageGaps=gaps,message=coverage_message(gaps))
            return
        from .recruitment_external_results import automatic_roles
        numbers=sorted({staff_id(r['values'].get('工号')) for r in state['rows'] if r['values'].get('标签分类')=='国内'
                        and r['values'].get('是否虚拟员工')!='是' and staff_id(r['values'].get('工号')) and any(automatic_roles(r,k) for k in ('recruitment','referral'))})
        sources=[s for s in state['sources'] if s.get('active',True) and s.get('kind')=='beisen' and not s.get('comparisonOnly') and not s.get('error') and s.get('forMonth')==month]
        coverage=coverage_sets(sources)
        covered=coverage['candidateEmployment']
        recipient_needs=recipient_requirements(state,month)
        recipient_covered=recipient_needs['coveredRecipients']
        recipients=sorted(recipient_needs['domesticRecipients'])
        matched_offers={staff_id(r['values'].get('工号')) for r in state['rows'] if r.get('offerMatched')}
        missing_offers=(set(numbers)-coverage['candidateOffer']-matched_offers) | (set(numbers) & coverage['candidateOfferGap'])
        missing_candidates=sorted((set(numbers)-covered)|missing_offers)
        if (numbers or recipients) and (force or missing_candidates):
            target=numbers if force else missing_candidates
            save(stage='sync',message=f'正在补查 {len(target)} 名国内人员及奖金领取人的资料')
            options={'recipient_numbers':sorted(set(recipients)-recipient_covered) if not force else recipients}
            if not force and missing_offers & covered:
                cached={}
                for source in sources:
                    checkpoint()
                    if source.get('employmentOnly') or source.get('channelDetailsOnly') or not source.get('storedName'):continue
                    payload=json.loads((store._folder(month)/'sources'/source['storedName']).read_text())
                    for history in payload.get('candidateHistories',[]):
                        number=str(history.get('jobNumber','')).lower()
                        if number not in missing_offers & covered:continue
                        proof={**history,'_queriedAt':history.get('_queriedAt',payload.get('queriedAt',''))}
                        marker=(number,history.get('userID'),history.get('startDate'),history.get('stopDate'))
                        if marker not in cached or cached[marker]['_queriedAt']<proof['_queriedAt']:cached[marker]=proof
                if cached:options['candidate_histories']=list(cached.values())
            snapshot=fetch(target,**options)
            checkpoint()
            state=store.save_beisen_snapshot(month,state['revision'],snapshot)
            job['revision']=state['revision'];checkpoint()
        elif set(recipients)-recipient_covered:
            missing=sorted(set(recipients)-recipient_covered)
            save(stage='sync',message=f'正在自动补查 {len(missing)} 名领取人的任职资料，无需重新扫描全部录用记录')
            snapshot=fetch_employment(missing)
            checkpoint()
            state=store.save_beisen_snapshot(month,state['revision'],snapshot)
            job['revision']=state['revision'];checkpoint()
        # Older snapshots predate Remarks intake. Upgrade those facts without
        # asking the user to enter channels or replacing the primary snapshot.
        checked={oid for s in state['sources'] if s.get('active',True) for oid in s.get('channelDetailsCheckedOfferIds',[])}
        for source in list(state['sources']):
            checkpoint()
            if source.get('kind')!='beisen' or not source.get('active',True) or source.get('comparisonOnly') or source.get('employmentOnly') or source.get('channelDetailsOnly') or not source.get('storedName'):continue
            payload=json.loads((store._folder(month)/'sources'/source['storedName']).read_text())
            if not any(str(o.get('customProperties',{}).get(CHANNEL))=='10'
                       and 'remarks' not in o and o.get('objectId') not in checked for o in payload.get('offers',[])):continue
            save(stage='sync',message='正在补查其他招聘渠道的原始备注')
            extra=fetch_channel_details(payload,checked)
            checkpoint()
            if extra:
                state=store.save_beisen_snapshot(month,state['revision'],extra)
                job['revision']=state['revision'];checkpoint()
                checked.update(extra['channelDetailsCheckedOfferIds'])
        gaps=coverage_gaps(state,month)
        save(status='complete',stage='complete',revision=state['revision'],coverageGaps=gaps,
             message=coverage_message(gaps))
    except PreparationCancelled:
        save(status='cancelled',message='已停止，已保存的资料保留')
    except Exception as exc:
        # Keep credentials/network responses out of persisted status.
        from .recruitment_drafts import DraftConflict
        try:
            checkpoint()
            message='资料在准备期间已更新，请重新准备。' if isinstance(exc,DraftConflict) else str(exc) if isinstance(exc,ValueError) else '资料准备未完成，已有资料保留，请重试。'
            save(status='failed',message=message)
        except PreparationCancelled:
            save(status='cancelled',message='已停止，已保存的资料保留')
    finally:
        ACTIVE.reset(context_token)
        with GUARD:
            if RUNNING.get(key)==job.get('id'):
                RUNNING.pop(key,None);CANCELLATIONS.pop(key,None)

"""Isolated recruitment UI preview. Copies inputs; never changes the source batch.

Run from repository root:
  python3 scripts/preview_recruitment_flow.py --port 8187
External HR queries are disabled by default. Use --enable-domestic-api for the
existing domestic connection and --enable-overseas-api for the logged-in Ego
browser connection. Local data remains in this sandbox.
"""
import argparse
from contextlib import asynccontextmanager
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from bonus_platform import recruitment_draft_api as api
from bonus_platform.engine.recruitment_trials import ScopedDraftStore
from bonus_platform.engine import recruitment_beisen


def create_app(data_root, *, enable_domestic_api=False, enable_overseas_api=False):
    # Both ordinary monthly records and independently-created records belong
    # to this preview. ScopedDraftStore derives trials beside this drafts root.
    api.store=ScopedDraftStore(Path(data_root)/'drafts')
    def offline(*args,**kwargs):raise ValueError('隔离预览不访问外部接口；已保存的真实快照可用于核算。')
    if not enable_overseas_api:
        from types import SimpleNamespace
        api.store.overseas_client=SimpleNamespace(fetch=offline)
    if not enable_domestic_api:
        from types import SimpleNamespace
        api.store.domestic_client=SimpleNamespace(post=offline)
        recruitment_beisen.fetch=offline
        recruitment_beisen.fetch_employment=offline
        recruitment_beisen.fetch_channel_details=offline
    local_store=api.store
    @asynccontextmanager
    async def lifespan(app):
        from bonus_platform.engine.recruitment_snapshot_library import SnapshotScheduler
        scheduler=SnapshotScheduler(local_store).start() if enable_domestic_api and enable_overseas_api else None
        try:yield
        finally:
            if scheduler:scheduler.close()
    app=FastAPI(lifespan=lifespan);app.include_router(api.router)
    app.include_router(api.trials_router);app.include_router(api.trial_drafts_router)
    app.include_router(api.activities_router);app.include_router(api.activity_drafts_router)
    app.mount('/',StaticFiles(directory=ROOT/'bonus_platform/static',html=True),name='static')
    return app


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8187)
    parser.add_argument('--data-root',type=Path,default=ROOT/'outputs/recruitment-review/flow-20260922/sandbox')
    parser.add_argument('--enable-domestic-api',action='store_true',help='Enable existing read-only domestic HR queries; local data stays isolated')
    parser.add_argument('--enable-overseas-api',action='store_true',help='Enable read-only overseas HR queries through the existing browser session')
    args=parser.parse_args();destination=args.data_root/'drafts/202607'
    if not (destination/'draft.json').exists():
        source=ROOT/'outputs/recruitment_trials/f4b8af47b923463789bd91e14544a0bb/drafts/202607'
        if source.exists():
            destination.mkdir(parents=True,exist_ok=True)
            shutil.copy2(source/'draft.json',destination/'draft.json')
            for name in ('sources','parsed'):shutil.copytree(source/name,destination/name,dirs_exist_ok=True)
    app=create_app(args.data_root,enable_domestic_api=args.enable_domestic_api,enable_overseas_api=args.enable_overseas_api)
    if (destination/'draft.json').exists():
        before=api.store.read(202607)
        after=api.store.refresh(202607,before['revision'])
        current=api.public(after)
        print(json.dumps({'isolated':True,'domesticApiEnabled':args.enable_domestic_api,'revision':after['revision'],'people':len(after['rows']),
                          'cases':len(current['monthly']['cases']),'reviewPeople':current['monthly']['reviewPeople']},ensure_ascii=False),flush=True)
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=args.port)

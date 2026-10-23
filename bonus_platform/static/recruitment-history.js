/* Legacy calculation is an explicit compatibility view, separate from archive lookup. */
(() => {
  const params=new URLSearchParams(location.search),legacy=params.get('mode')==='legacy';
  document.body.classList.toggle('legacy-calculation',legacy);
  document.getElementById('legacyPageTitle').textContent=legacy?'旧版核算（兼容）':'历史批次';
  document.getElementById('legacyPurpose').textContent=legacy?'沿用旧版导入、核算和确认流程。':'查阅旧版记录与下载文件；新核算请从活动列表开始。';
  document.getElementById('legacyModeNote').textContent=legacy?'当前为旧版兼容流程。新核算建议在活动列表新建活动，已有旧版批次仍可在此查阅和下载。':'这里保留旧版批次查阅和下载。新核算请在活动列表新建活动，按需导入上月未结奖金资料。';
  const context=new URLSearchParams();
  for(const key of ['activity','trial']){
    const value=params.get(key);
    if(value&&/^[a-zA-Z0-9_-]{1,100}$/.test(value))context.set(key,value);
  }
  const month=params.get('month'),view=params.get('view');
  if(month&&/^20\d{2}-(0[1-9]|1[0-2])$/.test(month))context.set('month',month);
  if(view&&/^[a-z][a-z-]{0,30}$/.test(view))context.set('view',view);
  const back=document.getElementById('legacyReturnActivity');
  if(context.has('activity')){
    const target=new URL('recruitment.html',location.href);target.search=context.toString();
    back.href=target.href;back.hidden=false;
  }
  const modeLink=document.getElementById('legacyModeLink'),target=new URL('recruitment-history.html',location.href);
  target.search=context.toString();target.hash=location.hash;
  if(!legacy)target.searchParams.set('mode','legacy');
  modeLink.href=target.href;modeLink.textContent=legacy?'返回历史查阅':'旧版核算（兼容）';
})();

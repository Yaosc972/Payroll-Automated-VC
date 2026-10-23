/* Keep auxiliary pages attached to the current calculation. */
(() => {
  const targets=[['recruitmentGuide','recruitment-guide.html'],['recruitmentHistory','recruitment-history.html']]
    .map(([id,page])=>({link:document.getElementById(id),page})).filter(item=>item.link);
  if(!targets.length)return;
  const update=()=>{
    const params=new URLSearchParams(location.search),month=document.getElementById('draftMonth')?.value;
    for(const {link,page} of targets){
      const target=new URL(page,location.href);
      for(const key of ['activity','month','trial'])if(params.has(key))target.searchParams.set(key,params.get(key));
      if(month)target.searchParams.set('month',month);
      if(page==='recruitment-history.html'&&params.has('view'))target.searchParams.set('view',params.get('view'));
      link.href=target.href;
    }
  };
  targets.forEach(({link})=>link.addEventListener('click',update));
  document.addEventListener('recruitment:render',update);
  update();
})();

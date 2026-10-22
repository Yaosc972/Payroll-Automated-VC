/* Carry the current calculation into the read-only operation guide. */
(() => {
  const link=document.getElementById('recruitmentGuide');
  if(!link)return;
  const update=()=>{
    const params=new URLSearchParams(location.search), guide=new URL('recruitment-guide.html',location.href);
    for(const key of ['activity','month','trial'])if(params.has(key))guide.searchParams.set(key,params.get(key));
    const month=document.getElementById('draftMonth')?.value;
    if(month)guide.searchParams.set('month',month);
    link.href=guide.href;
  };
  link.addEventListener('click',update);
  document.addEventListener('recruitment:render',update);
  update();
})();

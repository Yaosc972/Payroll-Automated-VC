(function(root){
  'use strict';
  const escape=value=>String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
  function choice(definition,value,attributes=''){
    if(!definition||!Array.isArray(definition.choices))return null;
    const choices=definition.choices;
    const saved=value!==''&&value!=null&&!choices.some(c=>String(c.value)===String(value));
    const action=definition.people?definition.people.map(p=>`<button type="button" class="rd-text-button" data-fact-person="${escape(p.id)}" data-fact-context-field="${escape(definition.field)}">${escape(p.label||p.name)}</button>`).join(''):'<button type="button" class="rd-text-button" data-fact-upload>上传对应资料</button>';
    return `<select ${attributes}><option value="">${escape(choices.length?'请选择':definition.missingMessage||'暂无可采用资料')}</option>${saved?`<option value="${escape(value)}" selected>沿用已保存值</option>`:''}${choices.map(c=>`<option value="${escape(c.value)}" ${String(c.value)===String(value)?'selected':''}>${escape(c.label)}</option>`).join('')}</select>${!choices.length&&definition.missingMessage&&definition.upload!==false?action:''}`;
  }
  const api={choice};
  if(typeof module==='object'&&module.exports)module.exports=api;else {
    root.RecruitmentFactControls=api;
    document.addEventListener('click',event=>{
      const person=event.target.closest('[data-fact-person]');
      if(person){const w=root.RecruitmentWorkbench;w.editor([person.dataset.factPerson],null,w.ui.data.revision,{field:person.dataset.factContextField});return;}
      if(event.target.closest('[data-fact-upload]')){document.getElementById('draftInspector').close();document.getElementById('draftUpload').click();}
    });
  }
})(typeof window==='undefined'?globalThis:window);

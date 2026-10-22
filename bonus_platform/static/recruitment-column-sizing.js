/* Content sizing and on-end resizing, without changing the worksheet model. */
(() => {
  'use strict';
  const host=document.getElementById('draftContent');if(!host)return;
  const states=new WeakMap(),ctx=document.createElement('canvas').getContext('2d');
  const button=document.createElement('button');button.id='flowAutoColumns';button.type='button';button.className='rd-text-button flow-auto-columns';button.textContent='自动列宽';button.title='按当前页内容自动适配，清除本表的手动列宽';button.hidden=true;
  document.querySelector('.flow-column-nav').after(button);
  let current=null,drag=null,queued=false,lastWidth=0;
  const clamp=(value,min,max)=>Math.max(min,Math.min(max,Math.round(value)));
  const minimum=key=>window.RecruitmentDetailTable.isIdentity(key)?116:/Date|日期|时间|工作日/.test(key)?96:key==='name'||key==='employeeId'?88:key==='note'?120:72;
  const storageKey=()=>`recruitment:column-widths:v1:${current?.kind||'detail'}`;
  function load(kind){try{const value=JSON.parse(localStorage.getItem(`recruitment:column-widths:v1:${kind}`));return value&&typeof value==='object'&&!Array.isArray(value)?value:{};}catch{return {};}}
  function save(){try{localStorage.setItem(storageKey(),JSON.stringify(current.custom));}catch{}}
  function measured(col){
    const headerStyle=getComputedStyle(col.header),body=current.table.tBodies[0];
    const rows=[...[...body?.rows||[]].slice(0,40),...current.table.tFoot?.rows||[]],index=col.element.parentElement? [...col.element.parentElement.children].indexOf(col.element):col.index;
    const font=rows[0]?.cells[index]?getComputedStyle(rows[0].cells[index]):headerStyle;
    ctx.font=`${font.fontWeight} ${font.fontSize} ${font.fontFamily}`;
    let text=0;for(const row of rows)text=Math.max(text,ctx.measureText(row.cells[index]?.textContent||'').width);
    ctx.font=`${headerStyle.fontWeight} ${headerStyle.fontSize} ${headerStyle.fontFamily}`;
    const heading=ctx.measureText(col.label).width/2;
    const max=col.key==='note'?280:/组织|职位|position/.test(col.key)?164:col.key==='name'?160:col.type==='money'?140:140;
    return clamp(Math.max(text+24,heading+26),minimum(col.key),max);
  }
  function apply(){
    if(!current?.table.isConnected)return;
    const cols=current.columns;
    const width=cols.map(c=>Number.isFinite(current.custom[c.key])?clamp(current.custom[c.key],minimum(c.key),520):c.auto);
    const check=current.table.querySelector('col:not([data-column-key])');const checkWidth=check?42:0;
    const total=width.reduce((a,b)=>a+b,checkWidth),free=host.clientWidth-total;
    if(free>0&&!Object.keys(current.custom).length){const extra=Math.floor(free/cols.length);width.forEach((_,i)=>width[i]+=extra);}
    cols.forEach((col,i)=>{col.width=width[i];col.element.style.width=width[i]+'px';col.handle.setAttribute('aria-valuenow',width[i]);});
    current.table.style.width=width.reduce((a,b)=>a+b,checkWidth)+'px';
    const name=cols.find(c=>c.key==='name')?.width||0,id=cols.find(c=>c.key==='employeeId')?.width||0;
    current.table.style.setProperty('--flow-name-left',checkWidth+'px');current.table.style.setProperty('--flow-id-left',(checkWidth+name)+'px');
    current.table.style.setProperty('--flow-fixed-width',(checkWidth+name+id)+'px');current.table.dataset.fixedWidth=checkWidth+name+id;
    host.dispatchEvent(new Event('recruitment:columns-resized'));
  }
  function resetOne(col){delete current.custom[col.key];col.auto=measured(col);save();apply();}
  function cancel(){if(!drag)return;drag.controller?.abort();drag.line.remove();drag=null;document.body.classList.remove('flow-resizing-columns');}
  function addHandle(col){
    const label=document.createElement('span');label.className='flow-column-label';label.textContent=col.label;col.header.replaceChildren(label);col.header.title=col.label;
    const handle=document.createElement('span');handle.className='flow-column-handle';handle.tabIndex=0;handle.setAttribute('role','separator');handle.setAttribute('aria-orientation','vertical');handle.setAttribute('aria-label',`调整${col.label}列宽`);handle.setAttribute('aria-valuemin',minimum(col.key));handle.setAttribute('aria-valuemax','520');handle.title='拖动调整列宽，双击自动适配';col.handle=handle;col.header.append(handle);
    handle.addEventListener('pointerdown',event=>{
      if(event.button!==0)return;event.preventDefault();event.stopPropagation();cancel();handle.setPointerCapture(event.pointerId);
      const line=document.createElement('div');line.className='flow-column-resize-guide';line.setAttribute('aria-hidden','true');document.body.append(line);
      drag={col,startX:event.clientX,startWidth:col.width,width:col.width,line,controller:new AbortController()};document.body.classList.add('flow-resizing-columns');
      const h=col.header.getBoundingClientRect(),box=host.getBoundingClientRect();line.style.top=Math.max(box.top,h.top)+'px';line.style.height=Math.max(0,Math.min(box.bottom,innerHeight)-Math.max(box.top,h.top))+'px';line.style.left=h.right+'px';drag.edge=h.right;
      const options={signal:drag.controller.signal,capture:true};
      document.addEventListener('pointermove',move,options);document.addEventListener('pointerup',finish,options);document.addEventListener('pointercancel',cancel,options);
    });
    function move(event){if(drag?.col!==col)return;drag.width=clamp(drag.startWidth+event.clientX-drag.startX,minimum(col.key),520);drag.line.style.left=(drag.edge+drag.width-drag.startWidth)+'px';}
    function finish(event){if(drag?.col!==col)return;const width=clamp(drag.startWidth+event.clientX-drag.startX,minimum(col.key),520),start=drag.startWidth;cancel();if(Math.abs(width-start)>1){current.custom[col.key]=width;save();apply();}}
    handle.addEventListener('dblclick',event=>{event.preventDefault();event.stopPropagation();resetOne(col);});
    handle.addEventListener('keydown',event=>{if(event.key==='Escape'){cancel();return;}if(!['ArrowLeft','ArrowRight','Home'].includes(event.key))return;event.preventDefault();event.stopPropagation();if(event.key==='Home')resetOne(col);else{current.custom[col.key]=clamp(col.width+(event.key==='ArrowRight'?8:-8),minimum(col.key),520);save();apply();}});
  }
  function setup(){
    queued=false;const table=host.querySelector('.flow-ledger,.flow-recipient-table');button.hidden=!table;
    if(!table){cancel();current=null;return;}
    if(states.has(table)){current=states.get(table);return;}
    cancel();const kind=table.classList.contains('flow-ledger')?'detail':window.RecruitmentWorkbench.ui.flowResult;
    const headers=[...table.querySelectorAll('th[data-column-key]')];
    if(!headers.length)return;
    let group=table.querySelector('colgroup');if(!group){group=document.createElement('colgroup');table.prepend(group);headers.forEach(header=>{const col=document.createElement('col');col.dataset.columnKey=header.dataset.columnKey;group.append(col);});}
    current={table,kind,custom:load(kind),columns:headers.map((header,index)=>({key:header.dataset.columnKey,type:header.dataset.columnType||'text',label:header.textContent.trim(),header,index,element:[...group.children].find(col=>col.dataset.columnKey===header.dataset.columnKey)}))};
    current.columns.forEach(col=>{col.auto=measured(col);addHandle(col);});table.dataset.columnsSized='true';states.set(table,current);apply();
  }
  function schedule(){if(!queued){queued=true;queueMicrotask(setup);}}
  button.onclick=()=>{if(!current)return;current.custom={};current.columns.forEach(col=>col.auto=measured(col));save();apply();};
  new MutationObserver(schedule).observe(host,{childList:true});
  new ResizeObserver(()=>{if(host.clientWidth!==lastWidth){lastWidth=host.clientWidth;apply();}}).observe(host);
  document.addEventListener('recruitment:render',schedule);window.addEventListener('keydown',event=>{if(event.key==='Escape')cancel();});
  setup();
})();

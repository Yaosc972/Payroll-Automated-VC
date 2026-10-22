(() => {
  'use strict';
  const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function groups(columns){
    const result=[];
    columns.slice(2).forEach(c=>{
      let group=result.at(-1);
      if(!group||group.label!==c.group){group={label:c.group,key:c.key,columns:[]};result.push(group);}
      group.columns.push(c);
    });
    return result;
  }
  function format(value,type){
    if(value==null)return '待核对';
    if(value==='')return '—';
    if(type==='money')return Number(value).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2});
    if(type==='percent')return `${Number((Number(value)*100).toFixed(2))}%`;
    return String(value);
  }
  function isIdentity(column){
    const label=typeof column==='string'?column:[column?.key,column?.label].join(' ');
    return /身份证|证件号|nationalId|identityNumber|idNumber/i.test(label);
  }
  function maskIdentity(value){
    if(value==null||value==='')return value;
    const text=String(value).trim();
    if(text==='—')return text;
    if(text.length<=7)return '*'.repeat(text.length);
    return text.slice(0,3)+'********'+text.slice(-4);
  }
  const display=(value,column)=>format(isIdentity(column)?maskIdentity(value):value,column.type);
  function tone(group){
    if(group==='本月核算')return 'total';
    if(group==='备注')return 'neutral';
    if(group.includes('内推'))return 'referral';
    if(group.includes('转正'))return 'probation';
    if(group.includes('奖金明细'))return 'installment';
    if(group==='招聘信息')return 'recruiting';
    return 'people';
  }
  function table(columns,rows){
    const grouped=groups(columns),width=columns.reduce((n,c)=>n+c.width,42);
    const heading=(c,i)=>`<th data-tone="${tone(c.group)}" data-detail-column="${escape(c.key)}" data-column-key="${escape(c.key)}" data-column-type="${c.type||'text'}" scope="col" ${i<2?'rowspan="2"':''} class="${i===0?'flow-fixed-name':i===1?'flow-fixed-id':''}">${escape(c.label)}</th>`;
    return `<table class="rd-table flow-worksheet flow-ledger" style="width:${width}px" aria-label="招聘奖金核算明细，按线下表字段分组"><colgroup>${columns.map(c=>`<col data-column-key="${escape(c.key)}" style="width:${c.width}px">`).join('')}</colgroup><thead><tr>${columns.slice(0,2).map(heading).join('')}${grouped.map(g=>`<th data-tone="${tone(g.label)}" scope="colgroup" colspan="${g.columns.length}" class="flow-ledger-group"><span>${escape(g.label)}</span></th>`).join('')}</tr><tr>${columns.slice(2).map(c=>heading(c,2)).join('')}</tr></thead><tbody>${rows.map(r=>`<tr>${columns.map((c,i)=>{
      const value=r.cells[c.key],shown=display(value,c),note=isIdentity(c)?null:r.cellNotes?.[c.key];
      const content=i===0?`<button class="rd-row-open" data-flow-row="${escape(r.id)}" type="button">${escape(value||'姓名待补')}</button>`:escape(shown);
      return `<td data-tone="${tone(c.group)}" class="${i===0?'flow-fixed-name':i===1?'flow-fixed-id':''} ${['money','percent','number'].includes(c.type)?'rd-number':''} ${value==null?'flow-warn':''}" title="${escape([shown,note].filter(Boolean).join(' · '))}">${content}</td>`;
    }).join('')}</tr>`).join('')}</tbody></table>`;
  }
  window.RecruitmentDetailTable={groups,format,table,isIdentity,maskIdentity,display};
})();

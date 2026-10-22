/* Material navigation is derived from parsed contents, not upload filenames. */
(() => {
  'use strict';
  const types = [
    {id:'opening',title:'上月核算表',icon:'table',section:'主要资料',description:'上月核算明细，用于继续计算未发完的奖金。'},
    {id:'roster',title:'本月花名册',icon:'people',section:'主要资料',description:'国内、海外花名册，保留工号、入职日期、人员状态等原始字段。'},
    {id:'domestic',title:'国内招聘资料',icon:'building',section:'主要资料',description:'同步核算月份的国内花名册、Offer 与任职资料，按月保存快照；也可补充原始文件。'},
    {id:'overseas',title:'海外 Offer',icon:'globe',section:'主要资料',description:'同步本月海外花名册、Offer 与带生效日期的任职记录，按核算月份保存快照；也可导入原始资料。'},
    {id:'external',title:'体系外核算结果',icon:'table',section:'按需提供',description:'导入体系外同事提供的本月核定结果。'},
    {id:'extra',title:'离职与特殊审批',icon:'checklist',section:'按需提供',description:'有离职或特殊审批时，导入原始离职资料、审批 PDF 或图片。'},
    {id:'comparison',title:'线下核对表',icon:'checklist',section:'其他资料',description:'仅与本月结果比较，不作为上月核算表，也不参与计算。'},
    {id:'other',title:'补充与其他文件',icon:'file',section:'其他资料',description:'补充表及暂未识别的文件，保留原件供查看。'},
  ];
  function categories(source) {
    if (source.purpose==='external-results') return ['external'];
    if (source.kind==='overseas_api') return ['roster','overseas'];
    if (source.kind==='beisen'&&source.monthlyRoster) return ['roster','domestic'];
    if (source.comparisonOnly) return ['comparison'];
    if (source.kind==='beisen') return ['domestic'];
    if (source.attachment) return ['extra'];
    const roles = new Set(source.roles || []), result = [];
    for (const [role,id] of [['ledger','opening'],['roster','roster'],['domestic_offer','domestic'],['overseas_offer','overseas'],['resignation','extra'],['approval','extra']]) {
      if (roles.has(role) && !result.includes(id)) result.push(id);
    }
    return result.length ? result : ['other'];
  }
  function format(source) {
    if (source.kind==='overseas_api') return {badge:'API',description:'海外接口月度快照'};
    if (source.kind==='beisen') return {badge:'API',description:'国内接口快照'};
    const extension = /\.([^.]+)$/.exec(source.name || '')?.[1].toUpperCase() || 'FILE';
    const sheets = source.sheets?.length || 0;
    const description = ['XLSX','XLSM','XLS'].includes(extension) ? `Excel${sheets ? ` · ${sheets} 个工作表` : ''}`
      : extension==='PDF' ? 'PDF 文件' : ['PNG','JPG','JPEG','WEBP'].includes(extension) ? '图片附件' : '原始文件';
    return {badge:extension,description};
  }
  const isSyncHistory = source => source.kind==='beisen' && source.active===false;
  function syncStatus(source) {
    if(source.kind==='overseas_api')return source.error?'读取失败':source.active===false?'已停用':source.snapshotOnly?'已保存 · 待核对':'当前采用';
    if(source.kind!=='beisen')return '';
    if(source.monthlyRoster)return source.error?'读取失败':source.snapshotOnly?'已保存 · 待核对':'当前采用';
    if(isSyncHistory(source))return '历史版本';
    if(source.error)return '读取失败';
    if(source.comparisonOnly)return '仅供核对';
    return source.employmentOnly||source.channelDetailsOnly ? '补查已采用' : '当前采用';
  }
  const syncTime = source => ['beisen','overseas_api'].includes(source.kind) ? String(source.addedAt||'').replace('T',' ').slice(0,16) : '';
  function snapshotNote(source){
    if(!['beisen','overseas_api'].includes(source.kind))return '';
    const period=source.forMonth?`${Math.floor(source.forMonth/100)}年${source.forMonth%100}月`:'未记录';
    const history=source.employmentRecords!=null?`含 ${source.employmentPeople} 人、${source.employmentRecords} 条任职记录，按奖金适用日期核对资格；历史资料有冲突时仍需核对。`:'快照记录采集时的数据，不能单独证明核算月份当时的状态。';
    return `核算月：${period}；接口采集时间：${syncTime(source)||'未记录'}${source.snapshotVersion?`（第 ${source.snapshotVersion} 版）`:''}。${history}`;
  }
  function build(data) {
    const coverage = data.monthly?.coverage || {};
    return types.map(type => {
      const files = (data.sources || []).filter(source => categories(source).includes(type.id));
      const active = files.filter(source => source.active!==false && !source.error);
      const current = active.filter(source => source.forMonth==null || source.forMonth===data.month);
      const failed = files.filter(source => source.active!==false && source.error).length;
      let status = active.length ? `已导入 ${active.length} 份` : files.length ? '已停用' : '待导入';
      let tone = active.length ? 'info' : files.length ? 'muted' : 'missing';
      let note = type.description;
      if (type.id==='opening') {
        status = coverage.hasOpening ? data.baseline ? '已采用' : data.parentMonth ? '已承接上月' : '已确认无历史奖金'
          : data.previousAccepted ? '可承接上月' : active.length ? '待采用' : '待导入';
        tone = coverage.hasOpening ? 'ready' : 'missing';
        if (coverage.hasOpening) note = data.baseline ? '已采用上月核算表，继续计算未发完的奖金。'
          : data.parentMonth ? `已承接 ${Math.floor(data.parentMonth/100)}年${data.parentMonth%100}月的核算结果。` : '已确认没有历史未结奖金，直接从本月开始。';
        else if (data.previousAccepted) note = '上月已有确认结果，开始核算时自动承接。';
      } else if (type.id==='roster') {
        if (!current.length) {status=active.length ? '待导入本月资料' : status;tone='missing';}
        else if(current.every(s=>(s.kind==='overseas_api'||s.monthlyRoster)&&s.snapshotOnly))status='已保存快照';
        else {
          const snapshots=current.filter(s=>(s.kind==='overseas_api'||s.monthlyRoster)&&s.snapshotOnly).length;
          status=`已导入 ${current.length-snapshots} 份${snapshots?` · 快照 ${snapshots}`:''}`;
        }
      } else if (type.id==='domestic') {
        const snapshots=current.filter(s=>s.monthlyRoster);
        if(snapshots.length){status=snapshots.some(s=>!s.snapshotOnly)?'已同步':'已保存快照';tone='info';}
        else if (coverage.syncRequired) {status='待同步';tone='missing';}
        else if (coverage.syncedAt && coverage.domesticPeople) {status=`已同步 · ${coverage.queriedPeople || 0} 人`;tone='ready';}
        else if (!active.length) {status='待同步';tone='muted';}
      } else if (type.id==='external') {
        const context=data.externalResults;
        const result=window.RecruitmentExternalResults?.cardState(context)||{label:'按需导入',tone:'muted'};
        status=result.label;tone=result.tone;
      } else if (type.id==='extra' && !files.length) {status='按需提供';tone='muted';}
      else if (type.id==='overseas') {
        const snapshots=current.filter(s=>s.kind==='overseas_api');
        if(snapshots.length){status=snapshots.some(s=>!s.snapshotOnly)?'已同步':'已保存快照';tone='info';}
        else if(!files.length){status='待同步或导入';tone='muted';}
      }
      else if (type.id==='comparison') {status='仅供核对';tone='muted';}
      if (failed) {status=`${failed} 份需处理`;tone='error';}
      return {...type,files,status,tone,note};
    }).filter(group => !['comparison','other'].includes(group.id) || group.files.length);
  }
  function approvalStatus(data, source) {
    if(source.approvalSummary)return source.approvalSummary.label;
    const scope=data.monthly?.workItems?.find(i=>i.key==='approval:'+source.id)?.approvalPeople||[];
    if(scope.length)return `已处理 ${scope.filter(p=>p.status==='已处理').length} 人 · ${scope.filter(p=>p.status!=='已处理').length} 人待处理`;
    const available=new Set((data.sources||[]).filter(s=>s.active!==false&&!s.error&&!s.comparisonOnly).map(s=>s.name));
    if((source.mentionedAttachments||[]).some(name=>!available.has(name)))return '缺少引用附件';
    if(source.documentInspectionError)return '原件需核对';
    const active=new Set(data.activeOperations || []);
    const review=(data.reviewEntries || []).filter(r=>r.sourceId===source.id && (!r.operationId || active.has(r.operationId))).at(-1);
    return !review ? '待审阅' : review.applied ? (review.scopeComplete ? '已应用更正' : '已部分应用') : review.status;
  }
  window.RecruitmentMaterials = {categories,format,build,approvalStatus,isSyncHistory,syncStatus,syncTime,snapshotNote};
})();

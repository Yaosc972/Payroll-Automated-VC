/* Presentation state only: never changes calculation, coverage or source data. */
(() => {
  'use strict';
  function measuredProgress(message) {
    const text=String(message||'');
    const matched=text.match(/^(?:海外 Offer 已核对|海外任职记录已核对|正在读取国内花名册：)\s*(\d+)\s*\/\s*(\d+)\s*(份|人)$/);
    const starting=text.match(/^正在补查\s*(\d+)\s*份海外录用资料中的核算缺项$/);
    const completed=matched?Number(matched[1]):starting?0:null;
    const total=matched?Number(matched[2]):starting?Number(starting[1]):null;
    if(completed===null||!Number.isSafeInteger(total)||total<=0||completed>total)return null;
    return {completed,total,unit:matched?matched[3]:'份',percent:Math.round(completed*100/total)};
  }
  function model(data, job, operation = {}) {
    const coverage = data?.monthly?.coverage || {};
    const sources = (data?.sources || []).filter(source => source.active !== false);
    const people = data?.monthly?.worksheet?.rows.filter(row => row.current).length || 0;
    const review = data?.monthly?.actionCount || 0;
    const ruleReview = data?.monthly?.ruleActionCount || 0;
    const reviewNote = ruleReview ? `${data.monthly.operatorActionCount || 0} 项待办 · ${ruleReview} 项制度` : `${review} 项需核对`;
    const calculated = !!data?.rows?.length;
    const currentJob = job && (['running','cancelling'].includes(job.status) || job.revision === data?.revision);
    const running = currentJob && ['running','cancelling'].includes(job.status);
    const failed = currentJob && ['failed', 'interrupted'].includes(job.status);
    const complete = currentJob && job.status === 'complete';
    const gaps = job?.coverageGaps?.length || 0;
    const ready = calculated && coverage.hasOpening && !coverage.syncRequired && !coverage.recipientSyncRequired && !coverage.sourceErrors && !data?.parentOutdated;
    const confirmed = data?.confirmation?.revision === data?.revision;
    const steps = [
      {id:'sources', title:'导入资料', icon:'file', state:coverage.syncRequired || coverage.sourceErrors ? 'attention' : sources.length ? 'available' : 'waiting', note:coverage.syncRequired ? '资料待补齐' : sources.length ? `${data.sources.length} 份资料` : '准备本月材料'},
      {id:'rows', title:'核算明细', icon:'table', state:running || operation.busy ? 'running' : calculated ? review ? 'attention' : 'available' : 'waiting', note:running ? '正在更新核算' : calculated ? review ? reviewNote : `${people} 人本月核算` : '导入后自动核算'},
      {id:'export', title:'导出表格', icon:'down', state:operation.exportedRevision === data?.revision && calculated ? 'complete' : ready && !review ? 'available' : 'waiting', note:operation.exportedRevision === data?.revision && calculated ? '本版已导出' : calculated ? ready && !review ? confirmed ? '已确认，可导出' : '可导出本月表格' : '可导出供核对' : '招聘与内推奖金'},
    ];
    let progress = null;
    if (running) {
      const sync = job.stage === 'sync';
      const syncLabel=job.monthlyAll?'国内及海外资料':job.overseasOnly?'海外资料':job.domesticOnly?'国内资料':'接口资料';
      const phases=job.monthlyAll?['同步国内资料','同步海外资料']:job.overseasOnly||job.domesticOnly?['读取花名册','关联 Offer','保存月度快照']:job.localOnly?['整理资料','更新核算']:['整理资料',`同步${syncLabel}`,'更新核算'];
      progress = {tone:'running', title:job.status==='cancelling' ? '正在停止' : sync ? `正在同步${syncLabel}` : '正在整理资料', detail:job.message || '已有资料保留，完成后自动更新核算。', phase:job.monthlyAll?(job.syncSource==='overseas'?1:0):sync ? 1 : 0, phases, retry:false,canCancel:!!job.id&&job.status==='running'};
      if(sync&&job.status==='running')progress.measurement=measuredProgress(job.message);
      if(job.monthlyAll)progress.phaseStates=['domestic','overseas'].map(name=>({complete:'done',running:'active',failed:'error'})[job.syncResults?.[name]?.status]||'waiting');
    } else if (currentJob && job.status==='cancelled') {
      progress = {tone:'cancelled',title:'已停止',detail:(job.message||'已保存的资料保留。').replace(/^已停止[，,。\s]*/,''),phase:0,phases:[],retry:false};
    } else if (operation.busy) {
      const message = operation.message || '';
      const uploading=Number.isSafeInteger(operation.uploadCount)&&operation.uploadCount>0;
      const importing = uploading || /整理.*份|导入|上传/.test(message);
      const loading = /读取/.test(message);
      const exporting = /导出|生成.*表格/.test(message);
      progress = {tone:'running', title:importing ? '正在导入资料' : loading ? '正在读取本月资料' : exporting ? '正在生成导出表格' : '正在更新核算', detail:uploading ? `正在读取、识别并保存 ${operation.uploadCount} 份资料` : message.startsWith('正在') ? message : '已有资料保留，请稍候。', phase:0, phases:[], retry:false};
    } else if (failed || operation.error) {
      progress = {tone:'error', title:failed ? job.status === 'interrupted' ? '资料整理已中断' : job.monthlyAll?'资料同步未完成':'资料整理未完成' : '操作未完成', detail:failed ? job.message : operation.message, phase:0, phases:[], retry:!!failed};
    } else if (complete && (job.overseasOnly||job.domesticOnly||job.monthlyAll)) {
      progress = {tone:gaps?'attention':'complete',title:gaps?'资料尚未齐全':`${job.monthlyAll?'国内及海外':job.domesticOnly?'国内':'海外'}资料快照已保存`,detail:job.message,phase:3,phases:[],retry:!!gaps};
    } else if (complete && calculated) {
      progress = {tone:review || !ready || gaps ? 'attention' : 'complete', title:gaps ? '资料尚未齐全' : '资料已整理，核算已更新', detail:gaps ? job.message : review ? `${people} 人参与本月核算 · ${ruleReview?reviewNote+'待核对':review+' 项待办需核对'}` : `${people} 人参与本月核算`, phase:3, phases:[], retry:!!gaps};
    }
    if (data?.activity?.archived) progress = {tone:'neutral', title:'活动已归档', detail:'可查看和导出；恢复活动后可继续修改。', phase:0, phases:[], retry:false};
    return {steps, progress};
  }
  window.RecruitmentExperience = {model};
})();

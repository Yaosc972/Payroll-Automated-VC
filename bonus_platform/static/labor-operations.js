const elements = Object.fromEntries([
  "adminToken","connectButton","refreshButton","accessStatus","updatedAt","failureRate","averageDuration",
  "cacheHitRate","modelFailureRate","alertCount","alerts","jobCount","jobs","storageBackend","storageFree","storageMinimum"
].map(id => [id, document.getElementById(id)]));

function percent(value){return `${(Number(value||0)*100).toFixed(1)}%`}
function duration(value){const seconds=Number(value||0);return seconds>=60?`${Math.round(seconds/60)} 分钟`:`${Math.round(seconds)} 秒`}
function bytes(value){const size=Number(value||0);if(!size)return "0 B";const units=["B","KB","MB","GB","TB"];const index=Math.min(Math.floor(Math.log(size)/Math.log(1024)),units.length-1);return `${(size/1024**index).toFixed(index>2?1:0)} ${units[index]}`}
function escapeHtml(value){return String(value??"").replace(/[&<>"]/g,char=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[char]))}
function localTime(value){if(!value)return "-";const date=new Date(value);return Number.isNaN(date.getTime())?"-":date.toLocaleString("zh-CN",{hour12:false})}

async function refresh(){
  const token=elements.adminToken.value.trim()||sessionStorage.getItem("laborOperationsToken")||"";
  if(!token){elements.accessStatus.textContent="请输入运维访问令牌。";elements.adminToken.focus();return}
  elements.accessStatus.textContent="正在读取...";
  try{
    const response=await fetch("/api/labor/operations",{headers:{"x-admin-token":token}});
    if(!response.ok)throw new Error(response.status===401?"访问令牌无效。":"运维数据读取失败。")
    const data=await response.json();sessionStorage.setItem("laborOperationsToken",token);render(data);elements.accessStatus.textContent="已连接";
  }catch(error){elements.accessStatus.textContent=error.message}
}

function render(data){
  const metrics=data.metrics||{};elements.failureRate.textContent=percent(metrics.taskFailureRate);elements.averageDuration.textContent=duration(metrics.averageDurationSeconds);
  elements.cacheHitRate.textContent=percent(metrics.ocrCacheHitRate);elements.modelFailureRate.textContent=percent(metrics.modelCallFailureRate);
  const alerts=Array.isArray(data.alerts)?data.alerts:[];elements.alertCount.textContent=alerts.length;
  elements.alerts.innerHTML=alerts.length?alerts.map(item=>`<div class="alert ${escapeHtml(item.severity)}"><strong>${escapeHtml(item.code)}</strong><span>${escapeHtml(item.message)}</span></div>`).join(""):'<p class="empty">当前无活动告警。</p>';
  const jobs=Array.isArray(data.recentJobs)?data.recentJobs:[];elements.jobCount.textContent=jobs.length;
  elements.jobs.innerHTML=jobs.length?jobs.map(job=>`<tr><td>${escapeHtml(job.id)}</td><td>${escapeHtml(job.runId)}</td><td><span class="status ${escapeHtml(job.status)}">${escapeHtml(job.status)}</span></td><td>${Number(job.attempt||0)} / ${Number(job.maxAttempts||0)}</td><td>${escapeHtml(localTime(job.heartbeatAt))}</td><td>${escapeHtml(job.errorCode||"-")}</td></tr>`).join(""):'<tr><td colspan="6" class="empty">暂无任务</td></tr>';
  const storage=data.storage||{};elements.storageBackend.textContent=storage.backend||"local";elements.storageFree.textContent=bytes(storage.freeBytes);elements.storageMinimum.textContent=bytes(storage.minimumFreeBytes);
  elements.updatedAt.textContent=`更新于 ${localTime(data.generatedAt)}`;
}

elements.connectButton.addEventListener("click",refresh);elements.refreshButton.addEventListener("click",refresh);document.getElementById("accessBand").addEventListener("submit",event=>{event.preventDefault();refresh()});
elements.adminToken.value=sessionStorage.getItem("laborOperationsToken")||"";if(elements.adminToken.value)refresh();

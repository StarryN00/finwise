/* Server-owned processing status. Rendering and polling never start model calls. */
let materialAgentTimer=null;
function materialAgentData(){return state.overview?.material_review?.agent_processing;}
function renderMaterialAgent(){
  const data=materialAgentData();if(!data?.enabled||!data.jobs.length)return '';
  const canWrite=!readonly()&&['operator','accountant','admin'].includes(state.role);
  const title=data.active?'系统正在读取与核验':data.not_started?'先让系统处理原件':data.blocked?'部分原件需要系统继续处理':'原件自动检查已完成';
  const start=data.not_started&&canWrite?'<button type="button" class="primary" data-action="material-agent-start">开始自动处理</button>':'';
  return `<section class="panel pad material-agent" aria-label="资料自动处理"><div class="row"><h2>${title}</h2><div class="actions">${start}<button type="button" class="secondary" data-action="material-agent-refresh">刷新处理进度</button></div></div>
    <p role="status">已核验 ${data.verified} 份 · 处理中 ${data.active} 份 · 受阻 ${data.blocked} 份</p>
    <p class="small muted">系统先查证和核验，再交接具体问题。读取一致不等于业务已确认或正式入账。</p>
    ${data.jobs.map(job=>`<article class="agent-source"><div class="row"><strong>${esc(job.filename)}</strong><span>${esc(job.label)}</span></div><p>${esc(job.message)}</p>
      ${job.proof?.status==='PASS'?`<p class="small">已核验 ${job.proof.records} 条记录、${job.proof.field_checks} 项字段。</p>`:''}
      ${['BLOCKED','FAILED'].includes(job.status)?`<div class="actions">${canWrite?`<button type="button" class="secondary" data-action="material-agent-resume" data-job="${esc(job.id)}">继续处理</button>`:''}<button type="button" class="text" data-action="artifacts">查看原件与资料类型</button></div>`:''}
      ${job.steps.length?`<details><summary>查看处理过程 · ${job.steps.length} 步</summary><ol>${job.steps.map(step=>`<li><strong>${esc(step.label)}</strong><p>${esc(step.reason)}</p>${step.result?.message?`<p class="small">${esc(step.result.message)}</p>`:''}</li>`).join('')}</ol></details>`:''}</article>`).join('')}
    ${data.withheld_tasks?`<p class="small muted">${data.withheld_tasks} 项原始提醒仍由系统检查，尚未作为人工待办交出。</p>`:''}</section>`;
}
function installMaterialAgentActions(){
  async function execute(path){
    if(readonly())return;
    const key=scopeKey(scope()),epoch=state.epoch;
    const result=await request(path,{scope:scope()});
    if(key!==scopeKey(scope())||epoch!==state.epoch)return;
    await loadWorkbench();notify(result.message||'处理状态已更新。');
  }
  actions['material-agent-start']=()=>execute('/api/v1/materials/process');
  actions['material-agent-resume']=button=>{
    const job=materialAgentData()?.jobs.find(j=>j.id===button.dataset.job);
    if(!job||!['BLOCKED','FAILED'].includes(job.status))return;
    return execute('/api/v1/materials/process/'+encodeURIComponent(job.id)+'/resume');
  };
  actions['material-agent-refresh']=async()=>{await loadWorkbench();notify('处理进度已刷新。');};
}
function scheduleMaterialAgentPoll(){
  clearTimeout(materialAgentTimer);
  if(!materialAgentData()?.active||!['current','materials'].includes(state.view))return;
  materialAgentTimer=setTimeout(async()=>{
    if(state.busy||document.hidden||document.activeElement?.matches('input,textarea,select')){scheduleMaterialAgentPoll();return;}
    const epoch=state.epoch,key=scopeKey(scope()),sequence=state.loadSequence;
    try{
      const next=await request('/api/v1/workbench',{scope:scope()});
      if(epoch!==state.epoch||key!==scopeKey(scope())||sequence!==state.loadSequence||state.busy||document.activeElement?.matches('input,textarea,select'))return;
      state.overview=next;render();
    }catch{notify('暂时无法刷新处理进度，任务仍保留，可手动刷新。',true);}
    finally{scheduleMaterialAgentPoll();}
  },3000);
}

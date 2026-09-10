'use strict';
// Additive review projection. Rendering and refresh never request a review.
const problemReviewLabels=Object.freeze({QUEUED:'等待复核',RUNNING:'正在复核',PASSED:'复核通过',BUSINESS_REVIEW:'业务待确认',SYSTEM_REVIEW:'系统待检查',INSUFFICIENT:'依据不足',FAILED:'复核失败',STALE:'依据已变化'});
function problemReviewData(){
  const o=state.overview,p=o?.problem_review;
  return o?.scope&&scopeKey(o.scope)===scopeKey(scope())&&p&&Array.isArray(p.jobs)?p:null;
}
function problemReviewToken(target){return JSON.stringify([state.user?.user_id,state.epoch,scopeKey(scope()),target?.object_id,target?.version]);}
function problemReviewStatus(job){return job.valid===false?'STALE':Object.hasOwn(problemReviewLabels,job.status)?job.status:'UNKNOWN';}
function problemReviewLabel(status){return problemReviewLabels[status]||'状态待核对';}
function problemReviewButton(action,title,target){return '<button type="button" class="secondary" data-action="problem-review-'+action+'" data-review-id="'+esc(target?.object_id||'')+'" data-review-token="'+esc(problemReviewToken(target))+'">'+esc(title)+'</button>';}
function problemReviewEvidence(job){
  const result=job.data?.result||{},refs=Array.isArray(result.evidence)?result.evidence:[],seen=new Set();
  return refs.filter(e=>e&&typeof e.artifact_id==='string').map(e=>{
    const key=JSON.stringify([e.fact_id,e.artifact_id,e.region]);if(seen.has(key))return '';seen.add(key);
    const a=state.overview.artifacts?.find(a=>a.object_id===e.artifact_id);
    const r=state.overview.material_review?.records?.find(r=>r.object_id===e.fact_id&&r.source_artifact_id===e.artifact_id);
    const binding=job.data?.binding,boundRecord=binding?.records?.find(r=>r.id===e.fact_id);
    const boundArtifact=binding?.artifact?.id===e.artifact_id?binding.artifact:null;
    const proof=(result.checks||[]).flatMap(c=>c.evidence_refs||[]).find(r=>r.fact_id===e.fact_id&&r.artifact_id===e.artifact_id)||{};
    const factVersion=e.fact_version??proof.fact_version,artifactVersion=e.artifact_version??proof.artifact_version;
    const target=e.fact_id&&Number.isInteger(factVersion)?{id:e.fact_id,version:factVersion}:boundRecord&&Number.isInteger(boundRecord.version)?boundRecord:Number.isInteger(artifactVersion)?{id:e.artifact_id,version:artifactVersion}:boundArtifact&&Number.isInteger(boundArtifact.version)?boundArtifact:null;
    const location=[...new Set([e.region,e.source_anchor?.region,proof.source_anchor?.region,...(proof.source_regions||[])].filter(r=>typeof r==='string'&&r))].join(' · ')||'来源定位未提供';
    const link=!a?'<span class="muted">来源已不在当前范围</span>':target?'<button type="button" class="text" data-object="'+esc(target.id)+'" data-object-version="'+target.version+'">查看原件依据（版本 '+target.version+'）</button>':job.valid===true?objectButton(r?.object_id||a.object_id,'查看原件依据'):'<span class="muted">历史来源版本未定位，不使用当前版本替代</span>';
    return '<li>'+esc(location)+' '+link+'</li>';
  }).join('');
}
function renderProblemReviewChecks(checks,compact=false){
  const seenAttention=new Set();
  const value=v=>v===null||v===undefined||v===''?'未提供':esc(v);
  const status=s=>({PASS:'通过',MATCH:'一致',PASSED:'通过',REVIEW:'待核对',BLOCKED:'未通过',MISMATCH:'不一致',NOT_AVAILABLE:'无法核对',FAIL:'未通过',FAILED:'未通过',SKIP:'未执行'})[s]||'待核对';
  const table=(name,headers,rows)=>'<div class="table-wrap problem-check-table" tabindex="0" role="region" aria-label="'+name+'"><table><thead><tr>'+headers.map(h=>'<th>'+h+'</th>').join('')+'</tr></thead><tbody>'+rows+'</tbody></table></div>';
  return (Array.isArray(checks)?checks:[]).map(check=>{
    if(!check||typeof check!=='object')return '';
    const relations=Array.isArray(check.relationships)?check.relationships:[],balances=Array.isArray(check.balances)?check.balances:[],steps=Array.isArray(check.check_steps)?check.check_steps:[];
    let html=check.message&&!(compact&&steps.length)?'<p>'+esc(check.message)+'</p>':'';
    if(relations.length)html+=table('红蓝发票关联',['角色／发票号码','不含税金额','税额','价税合计','原件定位'],relations.map(r=>{
      const known=state.overview.artifacts?.some(a=>a.object_id===r.artifact_id);
      const target=r.fact_id&&Number.isInteger(r.fact_version)?{id:r.fact_id,version:r.fact_version}:Number.isInteger(r.artifact_version)?{id:r.artifact_id,version:r.artifact_version}:null;
      const source=known&&target?'<button type="button" class="text" data-object="'+esc(target.id)+'" data-object-version="'+target.version+'">查看依据</button>':'';
      return '<tr><td>'+({BLUE:'蓝字发票',RED:'红字发票'}[r.role]||'角色待核对')+'<br>'+value(r.invoice_no)+'</td><td>'+value(r.amount)+'</td><td>'+value(r.tax_amount)+'</td><td>'+value(r.invoice_total)+'</td><td>'+value(r.region)+' '+source+'</td></tr>';
    }).join(''));
    if(balances.length)html+=table('金额抵销核对',['核对项目','蓝字合计','红字合计','差额','核对状态'],balances.map(b=>'<tr><td>'+value(b.label)+'</td><td>'+value(b.blue)+'</td><td>'+value(b.red)+'</td><td>'+value(b.net)+'</td><td>'+status(b.status)+'</td></tr>').join(''));
    if(steps.length){
      if(compact)html+=steps.filter(s=>{
        if(['PASS','MATCH','PASSED'].includes(s.status))return false;
        const key=JSON.stringify([s.code,s.label,s.status]);if(seenAttention.has(key))return false;seenAttention.add(key);return true;
      }).map(s=>'<p class="problem-check-attention">'+value(s.label||s.code)+' · '+status(s.status)+'</p>').join('');
      const full='<ol class="problem-check-steps">'+steps.map(s=>'<li><strong>'+value(s.label)+' · '+status(s.status)+'</strong><p>'+value(s.message)+'</p></li>').join('')+'</ol>';
      html+=compact?'<details><summary>查看完整检查依据</summary>'+(check.message?'<p>'+esc(check.message)+'</p>':'')+full+'</details>':full;
    }
    return '<section class="problem-check">'+html+'</section>';
  }).join('');
}
function renderProblemSourceAudit(audit){
  if(!audit||typeof audit.message!=='string')return '';
  return '<section class="problem-source-audit"><h4>原件字段检查</h4><p>'+esc(audit.message)+'</p>'+(Array.isArray(audit.candidates)&&audit.candidates.length?'<ul>'+audit.candidates.map(c=>'<li>'+esc(c.label||'来源标签')+' · '+esc(c.region||'定位待检查')+(Number.isInteger(c.artifact_version)&&state.overview.artifacts?.some(a=>a.object_id===c.artifact_id)?' <button type="button" class="text" data-object="'+esc(c.artifact_id)+'" data-object-version="'+c.artifact_version+'">查看原件</button>':'')+'</li>').join('')+'</ul>':'')+'</section>';
}
function problemReviewJob(job,readOnly=false,showRetry=true){
  const status=problemReviewStatus(job),result=job.data?.result||{},checks=Array.isArray(result.checks)?result.checks:[];
  const evidence=problemReviewEvidence(job),needs=Array.isArray(result.needs_confirmation)?result.needs_confirmation:[];
  readOnly=readOnly||job.triage?.route==='SYSTEM';
  const retry=showRetry&&status==='FAILED'&&job.valid===true&&materialCanWrite();
  return '<article class="problem-review-job" data-review-job="'+esc(job.object_id)+'"><div class="row"><strong>'+esc(job.data?.title||'资料问题复核')+'</strong><span class="problem-review-status">'+esc(problemReviewLabel(status))+'</span></div>'+
    (readOnly?'<p class="small muted">以下保留原复核记录；当前事项仍按系统待检查处理，不表示通过。</p>':'')+
    (job.valid===false?'<p>此结果仅作历史记录，不作为当前问题已解决的依据。</p>':'')+
    (typeof result.message==='string'?'<p>'+esc(result.message)+'</p>':'')+
    (['QUEUED','RUNNING'].includes(status)?'<p>后台处理中，可稍后手动刷新。离开此页不会代你确认。</p>':'')+
    (status==='SYSTEM_REVIEW'?'<p>解析或系统核对存在疑点，需先检查原因，不直接判定需要修正，也不作为客户补证任务。</p>':'')+
    (checks.length?'<details><summary>查看逐条核对说明（'+checks.length+'）</summary>'+renderProblemReviewChecks(checks)+'</details>':'')+
    (!readOnly&&needs.length?'<details><summary>仍有 '+needs.length+' 项待人工判断</summary><ul>'+needs.map(n=>'<li>'+esc(typeof n==='string'?n:n?.message||'请回到原有事项核对具体依据')+'</li>').join('')+'</ul><p class="small muted">请继续使用原有事项办理流程；此处不代为确认。</p></details>':'')+
    (evidence?'<details class="problem-review-evidence" '+(status==='PASSED'?'open':'')+'><summary>复核依据</summary><ul>'+evidence+'</ul></details>':'')+
    (retry?problemReviewButton('retry','重试本项复核',job):'')+'</article>';
}
function renderProblemReviewDetail(task,readOnly=false){
  const p=problemReviewData();if(!p||task.kind==='VERIFY')return '';
  const projected=task.problem_review;
  const job=projected&&p.jobs.find(j=>j.object_id===projected.object_id&&j.version===projected.version&&j.data?.task_id===task.id&&j.data?.artifact_id===task.artifact_id);
  if(readOnly)return '<section class="problem-review problem-review-detail" aria-label="问题二次复核"><div class="row"><h4>复核状态 · '+esc(job?problemReviewLabel(problemReviewStatus(job)):'暂无匹配结果')+'</h4>'+problemReviewButton('refresh','刷新复核状态',state.overview.period)+(job&&problemReviewStatus(job)==='FAILED'&&job.valid===true&&materialCanWrite()?problemReviewButton('retry','重试本项复核',job):'')+'</div>'+(job?'<details class="problem-review-history"><summary>上次复核记录</summary>'+problemReviewJob(job,true,false)+'</details>':'')+'<p class="small muted">复核结果不等于人工核实或账务可用，不代替现有业务确认及其他门禁。</p></section>';
  return '<section class="problem-review problem-review-detail" aria-label="问题二次复核"><div class="row"><h4>问题二次复核</h4>'+problemReviewButton('refresh','刷新复核状态',state.overview.period)+'</div>'+
    (job?problemReviewJob(job,readOnly):'<p class="small muted">本项暂无匹配的复核结果。可在资料概览明确发起本期问题复核。</p>')+
    '<p class="small muted">复核结果不等于人工核实或账务可用，不代替现有业务确认及其他门禁。</p></section>';
}
function renderProblemReviewOverview(){
  const p=problemReviewData();if(!p)return '';
  const period=state.overview.period,pending=p.jobs.some(j=>['QUEUED','RUNNING'].includes(problemReviewStatus(j)));
  const systemIds=new Set((p.system_tasks||[]).map(j=>j.object_id));
  const system=p.jobs.filter(j=>systemIds.has(j.object_id)&&problemReviewStatus(j)==='SYSTEM_REVIEW');
  const other=p.jobs.filter(j=>!system.includes(j));
  const counts=Object.entries(problemReviewLabels).filter(([k])=>Number.isInteger(p.counts?.[k])&&p.counts[k]>0).map(([k,v])=>'<span>'+v+' <b>'+p.counts[k]+'</b></span>').join('');
  const canRequest=materialCanWrite()&&period?.object_id&&Number.isInteger(period.version)&&!pending;
  return '<section class="panel pad problem-review" aria-label="问题二次复核概览"><div class="row"><h3>问题二次复核</h3><div class="actions">'+(canRequest?problemReviewButton('request','发起本期问题复核',period):'')+problemReviewButton('refresh','刷新复核状态',period)+'</div></div>'+
    '<p class="small muted">解析完成后自动复核；也可明确发起本期复核。刷新只读取结果。复核可能调用模型，不自动核实、不改事实、不放行账务。</p>'+
    '<div class="problem-review-counts">'+(counts||'暂无复核记录')+'</div>'+
    (pending?'<p role="status">复核正在排队或处理中，请稍后手动刷新。</p>':'')+
    (system.length?'<details><summary>历史复核分类：系统待检查 · '+system.length+' 项（独立于客户补证）</summary><p class="small muted">这里保留复核记录；当前人工／系统待办以问题列表的分流为准。</p>'+system.map(j=>problemReviewJob(j)).join('')+'</details>':'')+
    (other.length?'<details><summary>复核结果与历史 · '+other.length+' 项</summary>'+other.map(j=>problemReviewJob(j)).join('')+'</details>':'')+'</section>';
}
function problemReviewSaveDraft(){const t=currentMaterialTask();if(t)materialSaveDraft(t);}
async function problemReviewAction(action,button){
  const p=problemReviewData();if(!p)return;
  const target=action==='retry'?p.jobs.find(j=>j.object_id===button.dataset.reviewId):state.overview.period;
  if(!target||button.dataset.reviewToken!==problemReviewToken(target)){notify('范围或版本已变化，请刷新后重新选择。',true);return;}
  if(action!=='refresh'&&(!materialCanWrite()||!Number.isInteger(target.version)))return;
  if(action==='retry'&&(target.valid!==true||target.status!=='FAILED'))return;
  if(action==='request'&&p.jobs.some(j=>['QUEUED','RUNNING'].includes(problemReviewStatus(j))))return;
  const epoch=state.epoch,key=scopeKey(scope()),user=state.user?.user_id;
  const current=()=>epoch===state.epoch&&key===scopeKey(scope())&&user===state.user?.user_id;
  problemReviewSaveDraft();
  try{
    if(action!=='refresh')await command(action==='retry'?'retry_problem_review':'request_problem_review',target.object_id,target.version,{},false);
    if(!current())return;
    await loadWorkbench();
    if(current())notify(action==='refresh'?'复核状态已刷新；未发起新的复核。':'复核请求已接收，请查看排队状态；原办理草稿已保留。');
  }catch(error){if(current())notify(error.message||'复核请求未完成，原填写内容已保留。',true);}
}
function installProblemReviewActions(){
  for(const action of ['request','retry','refresh'])actions['problem-review-'+action]=button=>exclusive(()=>problemReviewAction(action,button));
  if(typeof window!=='undefined')window.addEventListener('pagehide',()=>clearTimeout(problemReviewPoll.timer));
}
// Read-only background status observation. Never replace overview or call render.
const problemReviewPoll={timer:null,inFlight:false,key:'',notified:new Set()};
function problemReviewPollKey(){return JSON.stringify([state.user?.user_id,state.epoch,scopeKey(scope())]);}
function problemReviewPollJobKey(job){return JSON.stringify([job.object_id,job.version]);}
function problemReviewPending(){return (problemReviewData()?.jobs||[]).filter(j=>['QUEUED','RUNNING'].includes(problemReviewStatus(j))&&!problemReviewPoll.notified.has(problemReviewPollJobKey(j)));}
function scheduleProblemReviewPoll(){
  clearTimeout(problemReviewPoll.timer);
  const key=problemReviewPollKey();
  if(problemReviewPoll.key!==key){problemReviewPoll.key=key;problemReviewPoll.notified.clear();}
  if(problemReviewPoll.inFlight||state.view!=='materials'||!problemReviewPending().length)return;
  problemReviewPoll.timer=setTimeout(pollProblemReview,10000);
}
async function pollProblemReview(){
  clearTimeout(problemReviewPoll.timer);
  if(problemReviewPoll.inFlight||state.view!=='materials'||!problemReviewPending().length)return;
  if(state.busy||document.hidden){scheduleProblemReviewPoll();return;}
  const key=problemReviewPollKey(),overview=state.overview,sequence=state.loadSequence,selected={...scope()},pending=problemReviewPending(),ids=pending.map(j=>j.object_id);
  problemReviewPoll.inFlight=true;
  try{
    const next=await request('/api/v1/workbench',{scope:selected});
    if(key!==problemReviewPollKey()||state.view!=='materials'||state.overview!==overview||sequence!==state.loadSequence||state.busy||document.hidden||scopeKey(next?.scope)!==scopeKey(selected))return;
    const finished=(next.problem_review?.jobs||[]).filter(j=>ids.includes(j.object_id)&&['PASSED','BUSINESS_REVIEW','SYSTEM_REVIEW','INSUFFICIENT','FAILED','STALE'].includes(problemReviewStatus(j)));
    if(finished.length){finished.forEach(j=>problemReviewPoll.notified.add(problemReviewPollJobKey(pending.find(p=>p.object_id===j.object_id))));notify('有 '+finished.length+' 项复核状态已更新，请手动刷新查看结果；当前填写内容未改变。');}
  }catch{/* Transient observation failure is silent; manual refresh remains available. */}
  finally{problemReviewPoll.inFlight=false;scheduleProblemReviewPoll();}
}

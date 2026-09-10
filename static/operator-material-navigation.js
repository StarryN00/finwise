'use strict';

// Navigation is local UI state. Task identities and command scopes remain server-owned.
function materialNavStorage(key,value){
  try{if(value===undefined)return JSON.parse(sessionStorage.getItem('finwise.material.navigation.'+key)||'null');sessionStorage.setItem('finwise.material.navigation.'+key,JSON.stringify(value));}catch{}return null;
}
function materialStoredDraft(key,id,value){
  const storageKey='finwise.material.draft.'+key+'.'+id;
  try{if(value===undefined)return JSON.parse(sessionStorage.getItem(storageKey)||'null');if(value===null)sessionStorage.removeItem(storageKey);else sessionStorage.setItem(storageKey,JSON.stringify(value));}catch{}return null;
}
function materialSaveDraft(t){
  const ui=materialState(),d=ui.drafts.get(t.id);if(!d)return;
  materialStoredDraft(ui.key,t.id,{note:d.note,reason:d.reason,defer:d.defer,bill:d.bill,resume:d.resume,fingerprint:materialTaskFingerprint(t)});
}
function materialDraftRevision(d){return JSON.stringify([d?.note,d?.reason,d?.defer,d?.bill]);}
function materialDeleteDraft(id,submittedRevision){const ui=materialState();if(submittedRevision&&materialDraftRevision(ui.drafts.get(id))!==submittedRevision)return false;ui.drafts.delete(id);materialStoredDraft(ui.key,id,null);return true;}
function materialDetailStillOpen(group,taskId){const ui=materialState();return state.view==='materials'&&ui.screen==='detail'&&ui.group===group&&ui.selected===taskId;}
function materialSupplementReceived(taskId,artifact){
  const ui=materialState(),entry=ui.group?.entries.find(e=>e.id===taskId);if(!entry)return;
  entry.supplementId=artifact.object_id;ui.feedback='补充原件已接收，原事项仍需核对；请根据最新提取结果继续处理。';
  materialSaveNavigation();render();
}
function materialNavigationSnapshot(){
  const ui=materialState();
  return {key:ui.key,screen:ui.screen,filter:ui.filter,viewMode:ui.viewMode,selected:ui.selected,page:ui.page,group:ui.group,listOrigin:ui.listOrigin,scrollY:typeof window==='undefined'?0:window.scrollY};
}
function restoreMaterialNavigation(ui,saved=materialNavStorage(ui.key)){
  ui.screen='list';ui.group=null;ui.listOrigin=null;ui.feedback='';
  if(!saved||saved.key!==ui.key||!['list','detail','summary'].includes(saved.screen))return;
  ui.screen=saved.screen;ui.filter=['all','selected','issues','system','period','deferred','results','usable','verified','VERIFY','bank-periods','other-period'].includes(saved.filter)?saved.filter:'all';
  ui.viewMode=saved.viewMode==='files'?'files':'issues';ui.selected=typeof saved.selected==='string'?saved.selected:'';
  ui.page=Number.isInteger(saved.page)?Math.max(0,saved.page):0;
  ui.group=saved.group&&Array.isArray(saved.group.entries)?saved.group:null;ui.listOrigin=saved.listOrigin||null;
  if(ui.screen!=='list'&&!ui.group)ui.screen='list';
}
function materialSaveNavigation(push=false){
  const snapshot=materialNavigationSnapshot();materialNavStorage(snapshot.key,snapshot);
  storage('finwise.material.view.'+snapshot.key,'materials');
  if(typeof window==='undefined'||!window.history)return;
  try{window.history[push?'pushState':'replaceState']({...window.history.state,finwiseMaterials:snapshot},'');}catch{}
}
function materialFocusDetail(){
  const title=$('materialDetailTitle')||$('materialTaskTitle');
  title?.focus({preventScroll:true});
  if(typeof window!=='undefined')window.scrollTo({top:0,behavior:'instant'});
}
function materialTaskFingerprint(t){
  const m=state.overview.material_review,a=state.overview.artifacts?.find(a=>a.object_id===t.artifact_id);
  return JSON.stringify([...(t.input_token?[t.input_token]:[]),t.id,t.artifact_version,a?.version,a?.status,a?.data?.sha256,
    t.record_ids.map(id=>{const r=m.records.find(r=>r.object_id===id);return [id,r?.version,r?.source_anchor];})]);
}
function materialEntry(t){return {id:t.id,artifact_id:t.artifact_id,artifact_version:t.artifact_version,kind:t.kind,reason:t.reason,filename:t.filename,title:t.title,recordIds:[...t.record_ids],factVersion:state.overview.material_review.records.find(r=>r.object_id===t.record_ids[0])?.version,fingerprint:materialTaskFingerprint(t),outcome:''};}
function materialDetailEntry(){const ui=materialState();return ui.group?.entries.find(e=>e.id===ui.selected);}
function materialTaskIsCurrent(t){const e=materialDetailEntry();return !!t&&(!e||e.fingerprint===materialTaskFingerprint(t));}
function materialRememberList(button){
  const ui=materialState();ui.listOrigin={filter:ui.filter,viewMode:ui.viewMode,page:ui.page,scrollY:typeof window==='undefined'?0:window.scrollY,action:button?.dataset?.action||'',taskId:button?.dataset?.task||''};
  materialSaveNavigation();
}
function openMaterialDetail(taskId,button,mode){
  const ui=materialState(),t=state.overview.material_review.tasks.find(t=>t.id===taskId);
  if(!t){notify('该事项已变化，请刷新列表后重新选择。',true);return;}
  if(ui.screen==='list')materialRememberList(button);
  const byFile=mode==='file'||t.kind==='VERIFY'||ui.viewMode==='files';
  const candidates=t.kind==='VERIFY'||materialSystemTask(t)?[t]:materialTasks(true).filter(x=>!materialSystemTask(x)&&(byFile?x.artifact_id===t.artifact_id:x.kind===t.kind&&x.reason===t.reason));
  const tasks=candidates.some(x=>x.id===t.id)?candidates:[t];
  ui.group={mode:byFile?'file':'issue',title:byFile?t.filename:t.title,kind:t.kind,reason:t.reason,artifact_id:t.artifact_id,entries:tasks.map(materialEntry)};
  if(t.kind==='VERIFY'){
    ui.filter='VERIFY';
    ui.group.entries[0].recordIds=[...new Set(state.overview.material_review.tasks.filter(x=>x.kind==='VERIFY'&&x.artifact_id===t.artifact_id&&x.artifact_version===t.artifact_version).flatMap(x=>x.record_ids))];
  }
  ui.screen='detail';ui.selected=t.id;ui.page=0;ui.feedback='';ui.skipped.delete(t.id);state.view='materials';state.category=null;
  materialSaveNavigation(true);render();materialFocusDetail();
}
function materialReturnList(push=true,historySnapshot=null){
  const ui=materialState(),origin=historySnapshot?{...((ui.listOrigin?.filter===ui.filter)?ui.listOrigin:{}),scrollY:historySnapshot.scrollY||0}:ui.listOrigin;ui.screen='list';ui.feedback='';
  if(origin&&!historySnapshot){ui.filter=origin.filter;ui.viewMode=origin.viewMode;ui.page=origin.page||0;}
  materialSaveNavigation(push);render();
  const buttons=typeof document.querySelectorAll==='function'?[...document.querySelectorAll('#materialWorkbench [data-action]')]:[];
  const target=buttons.find(b=>b.dataset.action===origin?.action&&b.dataset.task===origin?.taskId)||$('materialListTitle')||$('materialTaskTitle');
  target?.focus({preventScroll:true});if(typeof window!=='undefined')window.scrollTo(0,origin?.scrollY||0);
}
function materialEntryStatus(entry){
  const m=state.overview.material_review,t=m.tasks.find(t=>t.id===entry.id);
  if(t&&!t.deferred&&materialSystemTask(t))return 'system';
  if(entry.outcome==='bank_period_confirmed'&&entry.recordIds.every(id=>m.records.some(r=>r.object_id===id&&r.period_assignment?.valid===true)))return 'bank_period_confirmed';
  if(entry.kind==='INVOICE_AMOUNT'&&state.overview.invoice_amount_review?.confirmations.some(c=>c.valid&&entry.recordIds.includes(c.data.binding.fact_id)&&c.data.binding.fact_version===entry.factVersion&&c.data.binding.artifact_version===entry.artifact_version))return 'invoice_amount_confirmed';
  if(entry.kind==='BILL'){const c=state.overview.bill_review?.confirmations.find(c=>c.valid&&entry.recordIds.includes(c.data.binding.fact_id)&&c.data.binding.fact_version===entry.factVersion);if(c)return c.status==='OPINION'?'bill_opinion':'bill_confirmed';}
  if(materialRecordedOpinion(t))return 'opinion_recorded';
  if(t?.deferred)return 'deferred';
  if(state.overview.payroll_mappings?.some(j=>[entry.artifact_id,entry.supplementId].includes(j.data.artifact_id)&&['QUEUED','RUNNING'].includes(j.status)))return 'waiting';
  const verified=entry.recordIds.length>0&&entry.recordIds.every(id=>m.records.some(r=>r.object_id===id&&r.state==='SOURCE_VERIFIED'));
  if(entry.kind==='VERIFY'&&verified)return 'verified';
  if(entry.outcome==='linked'&&state.overview.bank_accounts?.statements.some(s=>s.artifact_id===entry.artifact_id&&s.status==='LINKED'))return 'linked';
  if(!t||!materialFingerprintMatches(entry,t))return 'changed';
  return entry.outcome==='skipped'?'skipped':entry.outcome==='waiting'?'waiting':'pending';
}
function materialFingerprintMatches(entry,t){return entry.fingerprint===materialTaskFingerprint(t);}
function materialAdvance(t,outcome){
  const ui=materialState(),entry=ui.group?.entries.find(e=>e.id===t.id);
  if(!entry)return;
  if(entry.suggestionPlan&&['verified','bank_period_confirmed','invoice_amount_confirmed','bill_confirmed','bill_opinion','linked','deferred'].includes(outcome))entry.suggestionPlan.recorded=true;
  if(outcome==='bank_period_confirmed'){
    const remaining=state.overview.material_review.tasks.find(x=>x.bank_period&&!materialSystemTask(x)&&x.artifact_id===t.artifact_id&&x.artifact_version===t.artifact_version&&x.reason===t.reason&&x.bank_period.target_period===t.bank_period.target_period);
    if(remaining){
      const prior=ui.drafts.get(t.id),next=materialDraft(remaining);if(prior&&remaining.id!==t.id&&!next.note)next.note=prior.note;
      next.selected.clear();entry.id=remaining.id;entry.fingerprint=materialTaskFingerprint(remaining);ui.selected=remaining.id;ui.page=0;ui.feedback='所选记录已确认归属；请继续本事项剩余记录。未核实原件、未入账。';materialSaveNavigation();render();materialFocusDetail();return;
    }
  }
  if(outcome==='verified'){
    // A partial page confirmation creates a new server task for the remaining rows.
    const remaining=state.overview.material_review.tasks.find(x=>x.kind==='VERIFY'&&x.artifact_id===t.artifact_id&&x.artifact_version===t.artifact_version&&x.reason===t.reason);
    if(remaining){entry.id=remaining.id;entry.fingerprint=materialTaskFingerprint(remaining);ui.selected=remaining.id;ui.page=0;ui.feedback='所选记录已核实，请继续核对本份资料剩余记录。';materialSaveNavigation();render();materialFocusDetail();return;}
  }
  entry.outcome=outcome;
  const feedback={bank_period_confirmed:'本事项流水归属已确认；等待目标期间接续，未核实原件或入账。',invoice_amount_confirmed:'本张发票金额核对已完成，已加入已处理记录；其他问题仍保留。',bill_confirmed:'票据业务归属已人工补充确认；拟用科目和其他问题仍按实际条件核对。',bill_opinion:'处理意见已记录，业务归属仍待确认。',verified:'本项资料核实已完成。',deferred:'原因已记录，仍待补充。',skipped:'本项暂未处理，未计入完成。',linked:'所属银行已确认，其他资料问题仍保留。'};
  ui.feedback=feedback[outcome]||'处理结果已更新。';
  // Bank assignment can also legitimately resolve other original tasks in this group.
  if(outcome==='linked')for(const e of ui.group.entries)if(e.reason===t.reason&&state.overview.bank_accounts?.statements.some(s=>s.artifact_id===e.artifact_id&&s.status==='LINKED'))e.outcome='linked';
  const next=ui.group.entries.find(e=>materialEntryStatus(e)==='pending');
  if(next){ui.selected=next.id;ui.page=0;ui.screen='detail';}else ui.screen='summary';
  materialSaveNavigation();render();materialFocusDetail();
}
function materialNextGroupTask(){
  const ui=materialState(),g=ui.group;if(!g)return null;
  return materialTasks().find(t=>!materialSystemTask(t)&&!t.deferred&&!ui.skipped.has(t.id)&&(g.kind==='VERIFY'?t.kind==='VERIFY':t.kind!=='VERIFY')&&
    !(g.mode==='file'?t.artifact_id===g.artifact_id:t.kind===g.kind&&t.reason===g.reason));
}
function materialUnavailableDetail(){
  const ui=materialState(),old=ui.drafts.get(ui.selected)||materialStoredDraft(ui.key,ui.selected);
  old?.selected?.clear();
  return `<section class="panel pad"><h3>此事项的来源或版本已变化</h3><p>请返回列表查看最新问题，原选中记录不能继续提交。</p>${old?.note||old?.reason||old?.bill?`<details open><summary>之前填写的内容（仅供参考）</summary><p class="mat-draft-reference">${esc(old.note||old.reason||[old.bill?.business_kind,old.bill?.business_period,old.bill?.account_name,old.bill?.reason].filter(Boolean).join(' · '))}</p></details>`:''}<button class="primary" data-action="material-return-list">返回问题列表</button></section>`;
}
function materialPlanFollowup(entry){
  const plan=entry?.suggestionPlan;if(!plan?.recorded||!plan.pending?.length)return '';
  return '<section class="panel pad" aria-label="方案后续步骤"><h4>本次仅保存所选动作，整份建议未执行完成</h4><p>以下步骤仍需分别核对，不能复用上一步的确认：</p><ul>'+plan.pending.map(s=>'<li>'+esc(s.label)+'：'+esc(s.instruction)+'（未执行）</li>').join('')+'</ul><button type="button" class="secondary" data-action="material-return-list">下一步：返回问题列表核对后续事项</button></section>';
}
function renderMaterialDetail(){
  const ui=materialState(),g=ui.group,entry=materialDetailEntry(),t=currentMaterialTask();
  if(!g)return materialUnavailableDetail();
  const header=`<button class="text return-link" data-action="material-return-list">← 返回${g.kind==='VERIFY'?'已有成果':'问题列表'}</button><section class="mat-detail-context mat-detail-compact"><div class="row"><span>本组共 ${g.entries.length} 项，涉及 ${new Set(g.entries.map(e=>e.artifact_id)).size} 份原件</span><strong class="mono">本组第 ${Math.max(0,g.entries.indexOf(entry))+1} 项／共 ${g.entries.length} 项</strong></div></section>`;
  const feedback=(ui.feedback?`<p class="notice mat-inline-feedback" role="status">${esc(ui.feedback)}</p>`:'')+materialPlanFollowup(entry);
  if(!t||!materialTaskIsCurrent(t))return `<div id="materialWorkbench" data-screen="detail">${header}${feedback}${materialUnavailableDetail()}</div>`;
  return `<div id="materialWorkbench" data-screen="detail">${header}${feedback}${renderMaterialTask()}</div>`;
}
function renderMaterialGroupResult(){
  const ui=materialState(),g=ui.group;if(!g)return materialUnavailableDetail();
  const labels={bank_period_confirmed:'其他期间归属已确认（未入账）',system:'系统待检查（未通过）',invoice_amount_confirmed:'金额核对已处理',bill_confirmed:'人工补充确认',bill_opinion:'意见已记录，仍待确认',opinion_recorded:'已选择处理方式（尚未执行）',verified:'资料已核实',deferred:'已记录待补',skipped:'暂未处理',waiting:'等待系统处理',pending:'仍需处理',changed:'来源或任务已变化',linked:'银行归属已确认'};
  const statuses=g.entries.map(e=>materialEntryStatus(e)),next=materialNextGroupTask();
  const totals=Object.entries(labels).map(([key,label])=>[label,statuses.filter(s=>s===key).length]).filter(([,n])=>n);
  return `<div id="materialWorkbench" data-screen="summary"><button class="text return-link" data-action="material-return-list">← 返回问题列表</button><section class="panel pad"><p class="small muted">本组处理结果</p><h2 id="materialDetailTitle" tabindex="-1">${esc(g.title)}</h2><p role="status">本组共 ${g.entries.length} 项。${statuses.includes('deferred')?'暂无法补充的原因已保存，相关问题仍保留。':''}${statuses.includes('opinion_recorded')?'已选择的处理方式仅代表意见已记录，尚未执行。':''}</p><div class="mat-group-totals">${totals.map(([label,n])=>`<div><strong>${n}</strong><span>${label}</span></div>`).join('')}</div>${g.entries.map((e,i)=>`<article class="mat-summary-entry"><div><strong>${esc(e.filename)}</strong><p>${esc(e.title)}</p><span>${labels[statuses[i]]}</span>${statuses[i]==='deferred'?`<p class="small">${esc(state.overview.material_review.tasks.find(t=>t.id===e.id)?.response?.data?.reason||'原因已记录')}</p>`:''}</div>${['skipped','pending','deferred','waiting','bill_opinion','opinion_recorded'].includes(statuses[i])?`<button class="text" data-action="material-revisit" data-task="${esc(e.id)}">${statuses[i]==='deferred'||statuses[i]==='opinion_recorded'?'查看处理记录':'继续本项'} →</button>`:''}</article>`).join('')}${g.entries.map(e=>materialPlanFollowup(e)).join('')}<p class="small muted">资料核实和处理记录已分别保留；期初、业务校验及证据条件仍按当前结果执行。</p><div class="actions mat-summary-actions">${next?`<button class="primary" data-action="material-next-group">${g.kind==='VERIFY'?'核对下一份资料':'处理下一类问题'}</button><button class="text" data-action="material-return-list">返回问题列表</button>`:'<button class="primary" data-action="material-overview">返回资料概览</button>'}</div></section></div>`;
}
function renderMaterialFileGroups(){
  const groups=new Map();for(const t of materialTasks(true)){if(!groups.has(t.artifact_id))groups.set(t.artifact_id,[]);groups.get(t.artifact_id).push(t);}
  return `<section class="mat-issue-groups"><h3 id="materialListTitle" tabindex="-1">按原件查看</h3>${[...groups.values()].map(tasks=>{const selected=tasks.filter(materialRecordedOpinion).length,pending=tasks.length-selected,status=[pending?`${pending} 项待处理`:'',selected?`${selected} 项已选择处理方式`:''].filter(Boolean).join(' · ');return `<article class="mat-issue-group"><div><strong>${esc(tasks[0].filename)}</strong><p>${status} · ${new Set(tasks.flatMap(t=>t.record_ids)).size} 条记录</p><p class="small muted">${tasks.map(t=>esc(t.title)).join('；')}</p></div><button class="text" data-action="material-select-file" data-task="${esc(tasks[0].id)}">${selected===tasks.length?'查看已选方案':tasks.every(t=>t.deferred)?'查看处理记录':'进入处理'} →</button></article>`;}).join('')||'<p>当前没有此类事项。</p>'}</section>`;
}
function materialCaptureFocus(){
  if(state.view!=='materials'||typeof document.querySelectorAll!=='function')return null;
  const root=$('materialWorkbench');if(!root)return null;
  const el=document.activeElement,focused=el&&root.contains(el);
  // Navigation updates state before render; capture identity from the old DOM, not the new selection.
  const card=root.querySelector('.decision-chat');
  return {key:materialState().key,screen:root.dataset.screen||'list',selected:card?.dataset.taskId||'',id:focused?el.id:'',record:focused?el.dataset?.materialRecord:null,start:focused?el.selectionStart:null,end:focused?el.selectionEnd:null,open:[...root.querySelectorAll('details')].map((el,i)=>el.open?i:-1).filter(i=>i>=0),scrollY:window.scrollY};
}
function materialRestoreFocus(focus){
  if(!focus||state.view!=='materials'||focus.key!==materialState().key||focus.screen!==materialState().screen||focus.selected!==materialState().selected)return;
  const root=$('materialWorkbench');if(!root)return;
  [...root.querySelectorAll('details')].forEach((el,i)=>{el.open=focus.open.includes(i);});
  const target=focus.id?$(focus.id):[...root.querySelectorAll('[data-material-record]')].find(el=>el.dataset.materialRecord===focus.record);
  target?.focus({preventScroll:true});if(target?.setSelectionRange&&Number.isInteger(focus.start))try{target.setSelectionRange(focus.start,focus.end);}catch{}
  window.scrollTo(0,focus.scrollY);
}
function installMaterialNavigation(){
  actions['material-return-list']=()=>materialReturnList();
  actions['material-overview']=()=>{const ui=materialState();ui.listOrigin={filter:'all',viewMode:ui.viewMode,scrollY:0};materialReturnList();};
  actions['material-next-group']=()=>{const t=materialNextGroupTask();if(t)openMaterialDetail(t.id);else actions['material-overview']();};
  actions['material-select-file']=b=>openMaterialDetail(b.dataset.task,b,'file');
  actions['material-revisit']=b=>{const ui=materialState(),t=state.overview.material_review.tasks.find(t=>t.id===b.dataset.task);if(!t){notify('事项已变化，请返回列表查看最新结果。',true);return;}ui.selected=t.id;ui.screen='detail';ui.page=0;ui.feedback='';const e=materialDetailEntry();if(e)e.outcome='';ui.skipped.delete(t.id);materialSaveNavigation();render();materialFocusDetail();};
  if(typeof window==='undefined')return;
  window.addEventListener('popstate',event=>{
    if(!state.overview)return;const saved=event.state?.finwiseMaterials,ui=materialState();
    if(!saved||saved.key!==ui.key){if(state.view==='materials'){ui.screen='list';ui.group=null;state.view='current';closeDialog();render();}return;}
    closeDialog();restoreMaterialNavigation(ui,saved);state.view='materials';materialNavStorage(ui.key,saved);render();
    if(ui.screen==='list')materialReturnList(false,saved);else materialFocusDetail();
  });
  window.addEventListener('pagehide',()=>{if(state.overview&&state.view==='materials')materialNavStorage(materialState().key,materialNavigationSnapshot());});
}

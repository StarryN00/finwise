'use strict';
const mappingUI={key:'',id:'',draft:null,confirmed:false,timer:null};
const mappingLabels={QUEUED:'等待识别',RUNNING:'AI 正在识别表格结构',REVIEW:'请核对字段对应',APPLIED:'已按确认格式提取',FAILED:'识别失败',STALE:'原件已变化'};
function mappingState(){const key=JSON.stringify([state.user?.user_id,scopeKey(scope())]);if(mappingUI.key!==key){mappingUI.key=key;mappingUI.id='';mappingUI.draft=null;mappingUI.confirmed=false;}return mappingUI;}
function mappingJob(){const ui=mappingState();return (state.overview?.payroll_mappings||[]).find(j=>j.object_id===ui.id);}
function mappingButton(a){if(!a||a.data.parse_options?.document_kind!=='payroll'||a.status!=='ACTIVE')return '';const j=[...(state.overview.payroll_mappings||[])].reverse().find(j=>j.data.artifact_id===a.object_id&&j.status!=='STALE');return `<button class="text" data-action="mapping-open" data-artifact="${esc(a.object_id)}">${j?esc(mappingLabels[j.status]):'AI 识别工资表格式'}</button>`;}
function mappingIndex(col){let n=0;for(const c of col)n=n*26+c.charCodeAt(0)-64;return n-1;}
function mappingCol(n){let s='';for(n++;n;n=Math.floor((n-1)/26))s=String.fromCharCode(65+(n-1)%26)+s;return s;}
function mappingDirty(){const ui=mappingState(),j=mappingJob();return !!(ui.draft&&j&&JSON.stringify(ui.draft)!==JSON.stringify(j.data.proposal));}
function renderMapping(){
 const ui=mappingState(),j=mappingJob();
 if(!j)return '<button class="text return-link" data-action="mapping-return">← 返回本期资料</button><section class="panel pad"><h2>工资表格式适配</h2><p>请选择当前工资表。</p></section>';
 const d=j.data,p=ui.draft||d.proposal;
 let body=`<div class="row"><div><h2 id="mappingTitle" tabindex="-1">${esc(mappingLabels[j.status])}</h2><p>${esc(d.filename||'工资表')} · ${esc(scope().accounting_period_id)}</p></div>${badge(j.status==='REVIEW'?'待核对':mappingLabels[j.status],j.status==='FAILED'?'red':'blue')}</div>`;
 if(['QUEUED','RUNNING'].includes(j.status))body+='<div class="goal" role="status"><b>系统正在处理，无需重复点击</b>识别表头与字段含义，不改写金额。可以离开页面，回来后查看结果。</div>';
 if(['FAILED','STALE'].includes(j.status))body+=`<p class="issue-banner">${esc(d.error||'原件版本已改变，请重新识别')}</p><button class="primary" data-action="mapping-retry" data-artifact="${esc(d.artifact_id)}" ${readonly()?'disabled':''}>重新识别格式</button>`;
 if(j.status==='APPLIED')body+=`<div class="goal"><b>字段对应已保存，本地提取完成</b>格式确认不代表逐条人工核实或账务可用；请继续查看本期成果及剩余问题。</div><button class="primary" data-action="mapping-return">查看本期成果与问题</button>`;
 if(j.status==='REVIEW'){
  if(!ui.draft)ui.draft=JSON.parse(JSON.stringify(p));
  body+=`<div class="goal"><b>${d.reused_from?'已匹配本企业确认过的格式':'AI 已提出字段对应方案'}</b>请核对每列含义、样例及期间依据；可修改下方对应列。${p.confidence<.8?'模型把握较低，请特别检查全部字段。':''}此次确认仅用于读取原表，不确认工资计算或发放结果。</div>`;
  body+=p.sheets.map((sheet,si)=>{
   const columns=d.columns.find(c=>c.sheet_index===sheet.sheet_index),records=(d.preview?.records||[]).filter(r=>r.original_value.sheet===columns.sheet),sample=records.slice(0,3),fields=['person_name','basic_salary','actual_salary','tax','employer_social','employee_social','employer_housing_fund','employee_housing_fund','housing_fund'];
   const rows=fields.map(f=>{const chosen=ui.draft.sheets[si].fields[f]||'',values=sample.map(r=>chosen?r.original_value.values[mappingIndex(chosen)]:'—');return `<tr><th>${esc(materialFieldLabels[f]||f)}${['person_name','actual_salary'].includes(f)?' *':''}</th><td><select aria-label="${esc(columns.sheet+' '+materialFieldLabels[f])}" data-mapping-field="${f}" data-sheet="${si}" ${readonly()?'disabled':''}><option value="">未提供／不映射</option>${columns.headers.map((h,c)=>h?`<option value="${mappingCol(c)}" ${chosen===mappingCol(c)?'selected':''}>${mappingCol(c)} · ${esc(h)}</option>`:'').join('')}</select></td><td data-sample="${si}-${f}">${values.map(v=>`<div>${v==null?'空白':esc(v)}</div>`).join('')}</td></tr>`;}).join('');
   const unassigned=columns.headers.filter((h,c)=>h&&!Object.values(sheet.fields).includes(mappingCol(c)));
   const period=records[0]?.field_sources?.period;
   return `<section class="mapping-sheet"><h3>${esc(columns.sheet)}</h3><p class="small">表头第 ${sheet.header_rows.join('、')} 行 · ${records.length} 条候选记录 · 显示前 ${sample.length} 条原始样例</p><div class="table-wrap" tabindex="0"><table class="mapping-table"><thead><tr><th>系统字段</th><th>对应原表列</th><th>原始样例（不改金额）</th></tr></thead><tbody>${rows}</tbody></table></div><div class="goal"><b>期间依据</b>${esc(period?.original_value||'原表未能确定期间，提取后仍保留期间问题')} ${esc(period?.region||'')}</div><details><summary>查看其他列及未归类字段</summary><p>${unassigned.map(esc).join('、')||'无'}</p></details></section>`;
  }).join('');
  const flagged=(d.preview.records||[]).filter(r=>r.extraction_issues?.length||r.period_check!=='PASS');
  if(flagged.length)body+=`<details class="issue-banner"><summary>提取检查：${flagged.length} 条仍有需要核对的内容</summary><p>字段格式确认不会消除公式、期间或原件问题。</p>${[...new Set(flagged.flatMap(r=>r.extraction_issues||[]))].map(t=>`<p class="small">${esc(t)}</p>`).join('')}</details>`;
  body+=`<div id="mappingPreviewNotice" class="issue-banner" ${mappingDirty()?'':'hidden'}>字段已修改；请更新提取预览，再核对记录数量、排除行和样例。</div><details><summary>查看行处理范围（含排除项）</summary><p>候选 ${d.preview.records.length} 条；表头、汇总、附注等未作工资明细的行如下，请检查是否遗漏员工。</p>${(d.preview.checks.excluded_rows||[]).map(r=>`<div class="small">${esc(r.sheet)} 第 ${r.row} 行 · ${esc(r.reason)}</div>`).join('')}</details>${objectButton(d.artifact_id,'查看完整原件')}<label class="mat-checkbox"><input id="mappingConfirmed" type="checkbox" ${ui.confirmed?'checked':''} ${readonly()||mappingDirty()?'disabled':''}>已核对字段对应、期间依据和处理行范围</label><div class="mat-actionbar"><button class="primary" data-action="mapping-preview" ${mappingDirty()?'':'hidden'} ${readonly()?'disabled':''}>更新提取预览</button><button class="primary" data-action="mapping-apply" ${mappingDirty()?'hidden':''} ${!ui.confirmed||readonly()?'disabled':''}>确认字段对应并提取</button><button class="text" data-action="mapping-return">暂不处理</button></div>`;
 }
 body+=`<details class="small muted"><summary>识别与审计记录</summary><p>${d.reused_from?'复用本企业已确认格式，无新增模型调用':d.gateway?`${esc(d.gateway.model_version)} · ${d.gateway.mock===false?'真实调用':'测试调用'} · ${esc(d.gateway.prompt_version)} · ${d.gateway.latency_ms} ms`:'尚无成功模型返回'}</p><p>仅发送脱敏结构语义，不发送姓名、账号和工资金额。原件版本 ${d.artifact_version}。</p></details>`;
 return `<button class="text return-link" data-action="mapping-return">← 返回本期资料</button><section class="panel pad" id="mappingWorkbench">${body}</section>`;
}
async function openMapping(artifact,retry=false){
 const epoch=state.epoch,ui=mappingState(),originView=state.view,materialReturn=originView==='materials'&&materialState().screen==='detail',originGroup=materialReturn?materialState().group:null,originTask=materialReturn?materialState().selected:null;let j=[...(state.overview.payroll_mappings||[])].reverse().find(j=>j.data.artifact_id===artifact.object_id);
 if(!j||retry){const r=await command('request_payroll_mapping',artifact.object_id,artifact.version);if(epoch!==state.epoch)return;j=r.effect.object;}
 if(state.view!==originView||(materialReturn&&!materialDetailStillOpen(originGroup,originTask))){notify('格式识别任务已保存，可从资料入口查看处理结果。');return;}
 ui.materialReturn=materialReturn;
 ui.id=j.object_id;ui.draft=null;ui.confirmed=false;state.view='mapping';storage('finwise.mapping.view.'+ui.key,j.object_id);closeDialog();render();scheduleMappingPoll();$('mappingTitle')?.focus({preventScroll:true});
}
function scheduleMappingPoll(){clearTimeout(mappingUI.timer);if(!(state.overview?.payroll_mappings||[]).some(j=>['QUEUED','RUNNING'].includes(j.status)))return;mappingUI.timer=setTimeout(async()=>{
 const epoch=state.epoch,seq=state.loadSequence,selected=scope();
 if(state.view!=='mapping'||state.busy||document.hidden||$('dialog').open||document.activeElement?.matches('input,select,textarea'))return scheduleMappingPoll();
 try{const next=await request('/api/v1/workbench',{scope:selected});if(state.view!=='mapping'||epoch!==state.epoch||seq!==state.loadSequence||state.busy||$('dialog').open||document.activeElement?.matches('input,select,textarea'))return;const old=JSON.stringify(state.overview.payroll_mappings);state.overview=next;if(JSON.stringify(next.payroll_mappings)!==old)render();}catch(e){if(epoch===state.epoch)notify('暂时无法获取识别进度，请刷新重试；已保存任务仍保留。',true);}finally{scheduleMappingPoll();}
 },1500);}
function installMappingActions(){
 actions['mapping-open']=b=>exclusive(()=>openMapping(fileById(b.dataset.artifact)));
 actions['mapping-retry']=b=>exclusive(()=>openMapping(fileById(b.dataset.artifact),true));
 actions['mapping-return']=()=>{const ui=mappingState();storage('finwise.mapping.view.'+ui.key,'');ui.draft=null;ui.confirmed=false;if(ui.materialReturn&&materialState().screen==='detail'){state.view='materials';render();materialFocusDetail();}else openMaterialWorkbench();};
 actions['mapping-preview']=()=>exclusive(async()=>{const ui=mappingState(),j=mappingJob(),epoch=state.epoch;if(!j)return;await command('preview_payroll_mapping',j.object_id,j.version,{proposal:ui.draft});if(epoch!==state.epoch)return;ui.draft=null;ui.confirmed=false;render();notify('已按修改后的字段更新预览，请核对样例及处理范围。');});
 actions['mapping-apply']=()=>exclusive(async()=>{const ui=mappingState(),j=mappingJob(),epoch=state.epoch;if(!j||!ui.confirmed)throw Error('请先核对字段对应及处理范围');await command('apply_payroll_mapping',j.object_id,j.version,{proposal:ui.draft,mapping_confirmed:true});if(epoch!==state.epoch)return;ui.draft=null;ui.confirmed=false;render();notify('字段格式已确认，提取完成；请查看成果及仍需核对的问题。');});
 document.addEventListener('change',e=>{if(!e.target.closest('#mappingWorkbench'))return;const ui=mappingState();if(e.target.id==='mappingConfirmed'){ui.confirmed=e.target.checked&&!mappingDirty();document.querySelector('[data-action="mapping-apply"]').disabled=!ui.confirmed||readonly();}if(e.target.dataset.mappingField){const f=e.target.dataset.mappingField,si=Number(e.target.dataset.sheet);ui.draft.sheets[si].fields[f]=e.target.value||null;ui.confirmed=false;const j=mappingJob(),col=j.data.columns.find(c=>c.sheet_index===ui.draft.sheets[si].sheet_index);const vals=j.data.preview.records.filter(r=>r.original_value.sheet===col.sheet).slice(0,3).map(r=>e.target.value?r.original_value.values[mappingIndex(e.target.value)]:'—');document.querySelector(`[data-sample="${si}-${f}"]`).innerHTML=vals.map(v=>`<div>${v==null?'空白':esc(v)}</div>`).join('');const dirty=mappingDirty();$('mappingConfirmed').checked=false;$('mappingConfirmed').disabled=dirty||readonly();$('mappingPreviewNotice').hidden=!dirty;document.querySelector('[data-action="mapping-preview"]').hidden=!dirty;document.querySelector('[data-action="mapping-apply"]').hidden=dirty;document.querySelector('[data-action="mapping-apply"]').disabled=true;}});
}

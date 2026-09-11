'use strict';
// Descriptors supply presentation only. All writes remain in existing local handlers.
const decisionAdapters=Object.freeze({
  verify_source_values:{form:'decisionVerifyForm',action:'material-verify',fields:{records:'record_selection',note:'materialNote'}},
  confirm_bank_period:{form:'bankPeriodForm',action:'bank-period-confirm',fields:{records:'period_record_selection',reason:'materialNote'}},
  confirm_invoice_amount:{form:'invoiceAmountForm',submit:true,resume:'invoice-amount-resume',fields:{reason:'materialNote'}},
  confirm_bill_business:{form:'billForm',submit:true,resume:'bill-resume',fields:{business:'bill_business'}},
  confirm_statement_account:{form:'bankAccountForm',submit:true,fields:{ownership:'bank_ownership'}},
  defer_material_issue:{form:'materialDeferForm',submitAction:'material-save-defer',action:'material-defer',fields:{reason:'materialReason'}},
  supplement:{form:'decisionSupplementForm',action:'material-supplement',fields:{}},
  parse:{form:'decisionParseForm',action:'material-parse',fields:{}},
  record_judgement:{form:'taskActionForm',taskAction:true,fields:{judgement:'taskActionJudgement',reason:'taskActionReason'}},
  suspend:{form:'taskActionForm',taskAction:true,fields:{reason:'taskActionReason'}},
  request_supplement:{form:'taskActionForm',taskAction:true,fields:{material:'taskActionMaterial',fact_to_verify:'taskActionFact'}},
  mark_out_of_scope:{form:'taskActionForm',taskAction:true,fields:{reason:'taskActionReason'}},
  escalate:{form:'taskActionForm',taskAction:true,fields:{reason:'taskActionReason'}}
});
const decisionProperties=Object.freeze({bill_business:['business_kind','business_period','original_receipt_period','business_date','search','account_candidate_id','account_name','account_code','reason','evidence_ids'],bank_ownership:['account_id','bank_name','account_number','holder','currency','confirmed'],record_selection:[],period_record_selection:[]});
function decisionValid(d){try{return decisionValidShape(d);}catch{return false;}}
function decisionValidShape(d){
  const strings=a=>Array.isArray(a)&&a.every(x=>typeof x==='string');
  const v1=d?.version==='decision-v1',v2=d?.version==='decision-v2';
  if(!d||!v1&&!v2||v2&&(!['SOURCE_REVIEW','BUSINESS_REVIEW','SYSTEM_REVIEW'].includes(d.stage)||typeof d.why_now!=='string'||!d.why_now.trim())||typeof d.title!=='string'||!d.why||!['facts','rule','recommendation','origin'].every(k=>typeof d.why[k]==='string')||!Array.isArray(d.why.evidence)||!d.scope||!Array.isArray(d.options)||!d.options.length||!Array.isArray(d.steps)||d.steps.length)return false;
  const effect=e=>e&&typeof e.kind==='string'&&typeof e.target==='string'&&typeof e.description==='string'&&e.grants_accounting_usable===false;
  return (v2||d.options.slice(1).every(o=>['defer_material_issue','supplement'].includes(o.id)))&&new Set(d.options.map(o=>o.id)).size===d.options.length&&d.options.every(o=>{
    const a=Object.hasOwn(decisionAdapters,o.id)&&decisionAdapters[o.id];
    const execution=o.execution_type||( ['parse','supplement'].includes(o.id)?'NAVIGATION':'COMMAND');
    const owner=o.post_submit_owner||'NONE';
    return a&&typeof o.label==='string'&&(o.submit_label===undefined||typeof o.submit_label==='string')&&['COMMAND','NAVIGATION'].includes(execution)&&(o.confirmation_label===undefined||typeof o.confirmation_label==='string')&&(o.success_label===undefined||typeof o.success_label==='string')&&['SYSTEM','EXTERNAL','NONE'].includes(owner)&&typeof o.completion==='string'&&typeof o.available==='boolean'&&typeof o.unavailable_reason==='string'&&strings(o.requires)&&(v1?strings(o.effects):Array.isArray(o.effects)&&o.effects.every(effect))&&strings(o.not_effects)&&Array.isArray(o.fields)&&o.fields.length===Object.keys(a.fields).length&&new Set(o.fields.map(f=>f.name)).size===o.fields.length&&decisionStepsValid(o)&&o.fields.every(f=>{
      if(!Object.hasOwn(a.fields,f.name)||typeof f.label!=='string'||typeof f.required!=='boolean')return false;
      if(f.component==='textarea')return (o.fallback===true||['materialNote','materialReason'].includes(a.fields[f.name]))&&Number.isInteger(f.max_length)&&f.max_length>0&&f.max_length<=2000&&typeof f.placeholder==='string';
      if(f.component!=='slot'||a.fields[f.name]!==f.slot||!Object.hasOwn(decisionProperties,f.slot))return false;
      const names=decisionProperties[f.slot],p=f.properties||[];
      return Array.isArray(p)&&p.length===names.length&&new Set(p.map(x=>x.name)).size===names.length&&p.every(x=>names.includes(x.name)&&typeof x.label==='string'&&typeof x.required==='boolean'&&typeof x.help==='string'&&typeof x.placeholder==='string'&&x.choices&&typeof x.choices==='object'&&!Array.isArray(x.choices)&&Object.values(x.choices).every(v=>typeof v==='string')&&Object.keys(x.choices).every(v=>x.name!=='business_kind'||['RECEIVED','HELD','ENDORSED','OTHER'].includes(v)));
    });
  });
}
function decisionExecution(o){return o.execution_type||(['parse','supplement'].includes(o.id)?'NAVIGATION':'COMMAND');}
function decisionOptionAvailable(o){return !!o?.available&&(!Array.isArray(o.permissions)||o.permissions.includes(state.role));}
function decisionConfirmationLabel(o){return o.confirmation_label||o.submit_label||o.label;}
function decisionSuccessLabel(o){return o.success_label||o.completion||'本项处理结果已更新。';}
function decisionEffectText(value){return typeof value==='string'?value:value?.description||'';}
function decisionStageLabel(stage){return {SOURCE_REVIEW:'原件核对',BUSINESS_REVIEW:'业务判断',SYSTEM_REVIEW:'系统检查'}[stage]||'待确认阶段';}
function decisionPropertyMap(field){return Object.fromEntries(field.properties.map(p=>[p.name,p]));}
function decisionBound(t){
  try{
    const d=t.descriptor,current=scope(),bound=d.scope,a=state.overview.artifacts.find(a=>a.object_id===t.artifact_id);
    const keys=['tenant_id','organization_id','legal_entity_id','ledger_id','accounting_period_id','baseline_id'];
    if(!keys.every(k=>typeof bound[k]==='string'&&bound[k]===current[k])||!a||bound.artifact.id!==a.object_id||bound.artifact.version!==a.version||a.version!==t.artifact_version||bound.artifact.sha256!==a.data.sha256)return false;
    const index=new Map(state.overview.material_review.records.map(r=>[r.object_id,r]));
    return bound.records.length===t.record_ids.length&&bound.records.every((r,i)=>{const actual=index.get(t.record_ids[i]);return actual&&r.id===actual.object_id&&r.version===actual.version&&JSON.stringify(r.source_anchor)===JSON.stringify(actual.source_anchor??null);})&&JSON.stringify(d.why.evidence)===JSON.stringify(bound.records);
  }catch{return false;}
}
function decisionPropertyLabel(p,control){return `<label>${esc(p.label)}${control}${p.help?`<small>${esc(p.help)}</small>`:''}</label>`;}
function decisionTriage(t){
  const q=t.triage;
  return q&&q.version==='issue-triage-v1'&&['HUMAN','SYSTEM'].includes(q.route)&&['title','explanation','next_action'].every(k=>typeof q[k]==='string')&&Array.isArray(q.questions)&&q.questions.every(s=>typeof s==='string')&&Array.isArray(q.checks)?q:null;
}
function decisionSystemTask(t){return !!t.triage&&decisionTriage(t)?.route!=='HUMAN';}
function decisionSource(t,selectable=false){
  const {rows}=decisionEvidenceRows(t),d=materialDraft(t);
  d.selected=new Set([...d.selected].filter(id=>rows.some(r=>r.object_id===id)));
  return '<div class="decision-selection"><p class="small muted">完整对照在上方；只勾选本页已逐条核对的记录，切换查看不会自动勾选。</p>'+rows.map((r,i)=>'<div class="decision-select-row"><label class="mat-checkbox"><input type="checkbox" data-material-record="'+esc(r.object_id)+'" '+(d.selected.has(r.object_id)?'checked':'')+' '+(selectable?'':'disabled')+'>已核对 '+esc(r.values?.invoice_no||r.values?.person_name||r.values?.acceptance_no||'本页记录 '+(i+1))+' · '+esc(r.source_anchor?.region||'来源定位未提供')+'</label><button type="button" class="text" data-guide="record" data-record="'+esc(r.object_id)+'" data-source-jump="true">查看对照</button></div>').join('')+'</div>';
}
function decisionPresentation(t){
  const p=t.descriptor.presentation;
  if(!p||typeof p.type_label!=='string'||typeof p.explanation!=='string'||!Array.isArray(p.records)||new Set(p.records.map(r=>r?.id)).size!==p.records.length)return null;
  return p.records.every(r=>r&&t.record_ids.includes(r.id)&&Array.isArray(r.focus_fields)&&r.focus_fields.every(f=>typeof f==='string'))?p:null;
}
function decisionEvidenceRows(t){
  const ui=materialState(),all=state.overview.material_review.records.filter(r=>t.record_ids.includes(r.object_id));
  ui.page=Math.max(0,Math.min(ui.page,Math.max(0,Math.ceil(all.length/5)-1)));
  return {all,rows:all.slice(ui.page*5,ui.page*5+5)};
}
function decisionFocusFields(t,r){
  const declared=decisionPresentation(t)?.records.find(x=>x.id===r.object_id)?.focus_fields;
  if(declared?.length)return declared;
  const names=(r.issues||[]).map(i=>i.split('：')[0]);
  return (r.comparison||[]).filter(c=>names.includes(c.field)||names.includes(decisionFieldName(c.field))||names.includes(c.source_label)).map(c=>c.field);
}
function decisionFieldName(k){
  const material=typeof materialFieldLabels!=='undefined'?materialFieldLabels[k]:'';
  const common=typeof fieldLabels!=='undefined'?fieldLabels[k]:'';
  return material||common||'来源字段';
}
function decisionEvidence(t){
  const {all,rows}=decisionEvidenceRows(t),g=decisionGuide(t);
  const selected=rows.find(r=>r.object_id===g.sourceRecord)||rows[0];
  const keyValues=r=>{
    const fields=decisionFocusFields(t,r),comparisons=(r.comparison||[]).filter(x=>fields.includes(x.field));
    if(!comparisons.length)return '请展开记录查看原始字段；当前未提供具体字段定位。';
    return comparisons.map(x=>decisionFieldName(x.field)+'：'+(x.source_value==null?(x.state==='MISSING'?'原件此字段为空':'原值尚未定位'):String(x.source_value))+(x.region?' · '+x.region:'')).join('；');
  };
  const identity=r=>{const v=r.values||{};return v.invoice_no||v.acceptance_no||v.person_name||v.transaction_id||'记录 '+(all.indexOf(r)+1);};
  const context=r=>{const v=r.values||{};return [v.invoice_date||v.transaction_date||v.issue_date||v.period,v.invoice_total??v.amount??v.actual_salary].filter(v=>v!==undefined&&v!==null).join(' · ');};
  let detail='';
  if(selected){
    const fields=decisionFocusFields(t,selected),focused=(selected.comparison||[]).filter(x=>fields.includes(x.field));
    const display=decisionSystemTask(t)?{...selected,verification:null}:selected;
    detail=focused.length?materialComparison({...display,comparison:focused}) : materialComparison(display);
    if(focused.length)detail+='<details class="decision-full"><summary>查看本条完整字段对照</summary>'+materialComparison(display)+'</details>';
  }
  return '<section class="decision-evidence" aria-label="问题数据清单"><h4>问题数据 · '+all.length+' 条</h4><p class="small muted">'+esc(t.filename||t.descriptor.why.facts)+' · 点击记录查看对照，仅切换查看，不会确认数据。</p>'+
    (rows.length?'<div class="table-wrap"><table class="decision-key-table"><thead><tr><th>记录／日期与金额</th><th>问题字段的原值</th><th>来源位置</th><th>查看</th></tr></thead><tbody>'+rows.map(r=>'<tr '+(selected===r?'class="decision-selected"':'')+'><td>'+esc(identity(r))+'<small>'+esc(context(r))+'</small></td><td>'+esc(keyValues(r))+'</td><td>'+esc(r.source_anchor?.region||'来源定位未提供')+'</td><td><button type="button" class="text" data-guide="record" data-record="'+esc(r.object_id)+'" aria-pressed="'+(selected===r)+'">'+(selected===r?'当前记录':'查看对照')+'</button></td></tr>').join('')+'</tbody></table></div>'+materialPager(all.length):'<p>尚未形成可定位的提取记录。请查看原件与识别失败原因。</p>'+objectButton(t.artifact_id,'查看原件'))+
    (selected?'<details class="decision-source" open><summary>当前记录原件与提取值</summary>'+detail+'</details>':'')+'</section>';
}
function decisionField(t,o,f){
  if(f.component==='textarea'){const id=decisionAdapters[o.id].fields[f.name],draft=materialDraft(t),fallback=o.fallback===true,value=fallback?(draft.taskAction?.[f.name]||''):draft[id==='materialReason'?'reason':'note'];return `<label for="${id}">${esc(f.label)}<textarea id="${id}" ${fallback?'data-task-action-field="'+esc(f.name)+'"':''} ${!decisionOptionAvailable(o)||!materialCanWrite()?'disabled':''} ${f.required?'required':''} maxlength="${f.max_length}" placeholder="${esc(f.placeholder)}">${esc(value||'')}</textarea></label>`;}
  if(f.slot==='record_selection')return `<div>${esc(f.label)}${decisionSource(t,decisionOptionAvailable(o)&&materialCanWrite())}</div>`;
  if(f.slot==='period_record_selection')return typeof bankPeriodFields==='function'?bankPeriodFields(t,decisionOptionAvailable(o)&&decisionReady(t)):'<p>跨期办理组件尚未加载，本项未执行。</p>';
  if(!decisionOptionAvailable(o))return '';
  if(f.slot==='bill_business')return billDecisionFields(t,f);
  if(f.slot==='bank_ownership')return bankDecisionFields(t,f);
  return '';
}

function decisionIdentity(t){return JSON.stringify([state.user?.user_id,scope(),t.id,t.input_token,t.descriptor.fingerprint||t.descriptor,t.triage]);}
function decisionHandling(t){
  const h=t?.handling,states=['NEEDS_DECISION','NEEDS_INPUT','READY_TO_CONFIRM','RUNNING','WAITING_SYSTEM','WAITING_EXTERNAL','COMPLETED','FAILED','STALE'];
  return h&&h.version==='material-handling-v1'&&states.includes(h.state)&&['USER','SYSTEM','EXTERNAL','NONE'].includes(h.owner)&&typeof h.label==='string'&&typeof h.explanation==='string'?h:null;
}
function decisionRequiresChoice(t){return !!(t.bank_period||t.material_guidance||t.personal_material_guidance||Object.hasOwn(t,'material_opinions'));}
function decisionRecordedOpinion(t){return (Array.isArray(t?.material_opinions)?t.material_opinions:[]).find(o=>o?.valid===true&&(o.status==='SAVED_NOT_EXECUTED'||o.data?.status==='SAVED_NOT_EXECUTED'||typeof o.text==='string'||typeof o.data?.text==='string'))||null;}
function decisionRemember(t){
  const d=materialDraft(t);materialSaveDraft(t);
  try{sessionStorage.setItem('finwise.material.guide.'+materialState().key+'.'+t.id,JSON.stringify(d.decision));}catch{}
}
function decisionGuide(t){
  const d=materialDraft(t),key=decisionIdentity(t);
  if(!d.decision){try{d.decision=JSON.parse(sessionStorage.getItem('finwise.material.guide.'+materialState().key+'.'+t.id)||'null');if(d.decision?.agent)d.decision.agent.busy=false;if(d.decision?.custom)d.decision.custom.busy=false;}catch{}}
  if(!d.decision||d.decision.key!==key){const h=decisionHandling(t),first=t.descriptor.options.find(decisionOptionAvailable)||t.descriptor.options[0],seed=h?.owner==='USER'&&['NEEDS_INPUT','READY_TO_CONFIRM'].includes(h.state)&&t.descriptor.options.some(o=>o.id===h.option_id&&decisionOptionAvailable(o))?h.option_id:null;d.decision={key,option:seed||first.id,step:0,reviewed:'',agent:null,chosen:!!seed};}
  if(d.defer)d.decision.option='defer_material_issue';
  if(!t.descriptor.options.some(o=>o.id===d.decision.option&&decisionOptionAvailable(o)))d.decision.option=(t.descriptor.options.find(decisionOptionAvailable)||t.descriptor.options[0]).id;
  return d.decision;
}
function decisionOption(t){return t.descriptor.options.find(o=>o.id===decisionGuide(t).option);}
function decisionAnswers(t,o){
  const d=materialDraft(t);
  if(o.id==='confirm_bill_business')return d.bill||{};
  if(o.id==='confirm_statement_account'){const c=bankData().statements.find(c=>c.artifact_id===t.artifact_id);return c?bankDraft(c):{};}
  if(o.fallback===true)return d.taskAction||{};
  return {reason:o.id==='defer_material_issue'?d.reason:d.note,note:d.note,records:[...d.selected]};
}
function decisionAnswerHash(t,o){return JSON.stringify([o.id,decisionAnswers(t,o)]);}
function decisionSteps(t,o){
  return o.steps.map(step=>{
    const fields=[];
    for(const name of step.fields){
      const direct=o.fields.find(f=>f.name===name);if(direct){fields.push(direct);continue;}
      const parent=o.fields.find(f=>f.properties?.some(p=>p.name===name));if(!parent)continue;
      let group=fields.find(f=>f.name===parent.name);if(!group){group={...parent,properties:[]};fields.push(group);}
      group.properties.push(parent.properties.find(p=>p.name===name));
    }
    return {title:step.prompt,fields};
  });
}
function decisionStepsValid(o){
  if(!Array.isArray(o.steps)||new Set(o.steps.map(s=>s.id)).size!==o.steps.length)return false;
  const expected=o.fields.flatMap(f=>f.properties?.length?f.properties.map(p=>p.name):[f.name]),used=[];
  for(const step of o.steps){
    if(typeof step.id!=='string'||!step.id||typeof step.prompt!=='string'||!step.prompt||!Array.isArray(step.fields)||!step.fields.length)return false;
    for(const name of step.fields){
      const f=o.fields.find(f=>f.name===name);
      if(f)used.push(...(f.properties?.length?f.properties.map(p=>p.name):[f.name]));
      else if(expected.includes(name))used.push(name);else return false;
    }
  }
  return used.length===expected.length&&new Set(used).size===expected.length&&expected.every(n=>used.includes(n));
}
function decisionValue(t,o,f){
  const a=decisionAnswers(t,o),properties=f.properties||[];
  if(f.slot==='record_selection')return a.records?.length?'已核对 '+a.records.length+' 条':'尚未选择记录';
  if(f.slot==='period_record_selection')return '目标期间 '+(t.bank_period?.target_period||'待检查')+' · 明确选择 '+(a.records?.length||0)+' 条（仅归属，不计作核实或入账）';
  if(f.component==='textarea')return a[f.name]||'未填写（可选）';
  return properties.filter(p=>p.name!=='search').filter(p=>p.name!=='original_receipt_period'||a.business_kind==='HELD').filter(p=>!['account_name','account_code'].includes(p.name)||!a.account_candidate_id).map(p=>{
    let v=a[p.name];
    if(p.name==='account_candidate_id'&&v){const c=state.overview.bill_review?.candidates.find(c=>c.id===v);v=c?c.code+' '+c.name+' · '+c.source_label:'所选科目依据已变化';}
    if(p.name==='account_id'&&v){const c=bankData().accounts.find(c=>c.object_id===v);v=c?c.data.bank_name+' · '+(c.data.account_number||'默认账户'):'所选账户已变化';}
    if(p.name==='evidence_ids')v=(v||[]).map(id=>activeArtifacts().find(a=>a.object_id===id)?.data.filename||'依据已变化').join('、');
    return p.label+'：'+(p.choices?.[v]||(v===true?'已确认':v===false?'未确认':v)||'未填写');
  }).join('；');
}
function decisionValidateStep(t,o,index,form){
  const step=decisionSteps(t,o)[index],answers=decisionAnswers(t,o);if(!step)return false;
  for(const f of step.fields){
    if(f.slot==='record_selection'&&!answers.records?.length)return false;
    if(f.slot==='period_record_selection'&&(typeof bankPeriodSelection!=='function'||!bankPeriodSelection(t)))return false;
    if(f.component==='textarea'&&f.required&&!String(answers[f.name]||'').trim())return false;
    for(const p of f.properties||[]){
      if(p.name==='original_receipt_period'&&answers.business_kind!=='HELD'||['account_name','account_code'].includes(p.name)&&answers.account_candidate_id||['bank_name','account_number','holder','currency'].includes(p.name)&&answers.account_id)continue;
      if(p.required&&!answers[p.name])return false;
    }
  }
  const section=form?.querySelector('[data-guide-step="'+index+'"]');
  for(const el of section?.querySelectorAll('input,select,textarea')||[]){if(!el.disabled&&!el.checkValidity()){el.reportValidity();return false;}}
  return true;
}
function decisionReady(t){const h=decisionHandling(t);return !!t&&t.descriptor?.version==='decision-v2'&&!decisionSystemTask(t)&&(!h||h.owner==='USER')&&decisionValid(t.descriptor)&&decisionBound(t)&&materialTaskIsCurrent(t)&&materialCanWrite();}
function decisionShowStep(){render();document.querySelector?.('.decision-chat [data-current-question]')?.focus({preventScroll:true});}
function decisionChoose(t,id,preserveSuggestion=false){
  if(!decisionReady(t))return;
  const o=t.descriptor.options.find(o=>o.id===id);if(!decisionOptionAvailable(o))return;
  const g=decisionGuide(t);
  if(!preserveSuggestion){delete g.suggestionChoice;const entry=typeof materialDetailEntry==='function'?materialDetailEntry():null;if(entry)delete entry.suggestionPlan;}
  g.option=id;g.chosen=true;g.step=0;g.reviewed='';materialDraft(t).defer=id==='defer_material_issue';materialDraft(t).resume=true;decisionRemember(t);decisionShowStep();
}
function decisionNext(t,form){
  if(!decisionReady(t))return;
  const o=decisionOption(t),g=decisionGuide(t),steps=decisionSteps(t,o);
  if(decisionRequiresChoice(t)&&g.chosen!==true)return;
  if(!decisionOptionAvailable(o)||g.step>=steps.length)return;
  if(!decisionValidateStep(t,o,g.step,form)){notify('请完成当前问题，核对必填内容。',true);return;}
  g.step++;if(g.step===steps.length)g.reviewed=decisionAnswerHash(t,o);
  decisionRemember(t);decisionShowStep();
}
const decisionAllowedSubmits=new WeakSet();
function decisionCanSubmit(t){
  if(!decisionReady(t))return false;
  const o=decisionOption(t),g=decisionGuide(t),steps=decisionSteps(t,o);
  return (!decisionRequiresChoice(t)||g.chosen===true)&&steps.length>0&&decisionOptionAvailable(o)&&g.step===steps.length&&g.reviewed===decisionAnswerHash(t,o)&&steps.every((s,i)=>decisionValidateStep(t,o,i));
}
function decisionOpen(t){
  if(!decisionReady(t))return;
  if(decisionRequiresChoice(t)&&decisionGuide(t).chosen!==true)return;
  const o=decisionOption(t);if(!decisionOptionAvailable(o)||decisionExecution(o)!=='NAVIGATION'||o.fields.length||!['parse','supplement'].includes(o.id))return;
  // The old parse action can write immediately; enter its existing confirmation dialog instead.
  if(o.id==='parse')openParseDialog(fileById(t.artifact_id));
  else actions['material-supplement']?.();
}
function decisionCommit(t,form){
  if(!decisionCanSubmit(t)){notify('回答或依据已变化，请重新核对摘要。',true);return;}
  const o=decisionOption(t),a=decisionAdapters[o.id];
  if(decisionExecution(o)!=='COMMAND'||!a){notify('当前处理方式不能在这里执行，请重新选择。',true);return;}
  const sections=[...(form?.querySelectorAll?.('[data-guide-step]')||[])],disabled=sections.map(s=>s.disabled);
  try{
    sections.forEach(s=>s.disabled=false);
    for(let i=0;i<sections.length;i++)for(const el of sections[i].querySelectorAll('input,select,textarea'))if(!el.disabled&&!el.checkValidity()){
      const g=decisionGuide(t);g.step=i;g.reviewed='';decisionRemember(t);decisionShowStep();notify('请核对该步骤的字段格式。',true);return;
    }
    if(a.taskAction){void decisionExecuteTaskAction(t,o);}
    else if(a.submit){decisionAllowedSubmits.add(form);form.requestSubmit();}
    else Promise.resolve(actions[a.submitAction||a.action]?.()).catch(e=>notify(e.message,true));
  }finally{if(form)decisionAllowedSubmits.delete(form);sections.forEach((s,i)=>s.disabled=disabled[i]);}
}
async function decisionExecuteTaskAction(t,o){
  if(!decisionReady(t)||o.fallback!==true)return;
  const identity=decisionIdentity(t),epoch=state.epoch,revision=materialDraftRevision(materialDraft(t));
  await exclusive(async()=>{
    try{
      const result=await command('execute_task_action',t.artifact_id,t.artifact_version,{
        task_id:t.id,descriptor_hash:t.descriptor.fingerprint,action_type_id:o.id,
        values:decisionAnswers(t,o)
      },false);
      if(epoch!==state.epoch)return;
      materialDeleteDraft(t.id,revision);await loadWorkbench();
      const next=result.next||state.overview.material_review?.next_step;
      const nextTask=next?.task_id&&state.overview.material_review.tasks.find(x=>x.id===next.task_id);
      if(nextTask){const ui=materialState();ui.selected=nextTask.id;ui.screen='detail';ui.page=0;materialSaveNavigation();}
      else materialState().screen='list';
      render();notify(decisionSuccessLabel(o)+(next?.title?'；下一步：'+next.title:'。'));
    }catch(error){if(epoch===state.epoch)notify(error.message,true);}
  });
}
function decisionAgentValid(r,hash){
  return r&&r.descriptor_hash===hash&&['PROPOSED','NEEDS_HUMAN','RUNNING','FAILED'].includes(r.status)&&
    (['RUNNING','FAILED'].includes(r.status)||r.suggestion&&[null,'string'].includes(r.suggestion.option_id===null?null:typeof r.suggestion.option_id)&&typeof r.suggestion.reason==='string'&&Array.isArray(r.suggestion.uncertainties)&&r.suggestion.uncertainties.every(x=>typeof x==='string')&&r.suggestion.prefill&&Object.keys(r.suggestion.prefill).length===0);
}
async function decisionAskAgent(t,fresh=false){
  if(!decisionReady(t)||!t.descriptor.fingerprint)return;
  const g=decisionGuide(t);if(g.agent?.busy)return;
  if(fresh||!g.agent)g.agent={request_id:crypto.randomUUID()};
  const request=g.agent,key=decisionIdentity(t),epoch=state.epoch,hash=t.descriptor.fingerprint;
  request.busy=true;request.message='正在分析；你可以继续填写，已有回答会保留。';decisionRemember(t);render();
  const current=()=>state.epoch===epoch&&state.view==='materials'&&materialState().screen==='detail'&&currentMaterialTask()?.id===t.id&&decisionIdentity(currentMaterialTask())===key&&materialDraft(currentMaterialTask()).decision===g&&g.agent===request;
  try{
    const body={scope:scope(),stage:'MATERIAL_GUIDANCE',task_id:t.id,descriptor_hash:hash,request_id:request.request_id};
    const response=typeof api==='function'?await api('/agent/suggestion',body):await requestGuidance(body);
    if(!current())return;
    if(!decisionAgentValid(response,hash))throw Error('建议与当前依据不匹配，未展示；可重试。');
    request.response=response;delete request.selected;request.message=response.status==='RUNNING'?'同一请求仍在处理中，可稍后检查结果。':response.status==='FAILED'?(response.message||'分析失败，可以重试。'):'';
  }catch(error){if(current())request.message=error.message||'网络失败，请重试；会复用本次请求。';}
  finally{request.busy=false;if(current()){decisionRemember(t);render();}}
}
function requestGuidance(body){return request('/api/v1/agent/suggestion',body);}
// Local presentation adapter; candidates never supply fields, effects or commands.
function decisionSuggestionCards(t,candidates){
  const g=decisionGuide(t),seen=new Set();
  const cards=(Array.isArray(candidates)?candidates:[]).filter(s=>{
    if(!s||typeof s.option_id!=='string'||typeof s.reason!=='string'||!Array.isArray(s.uncertainties)||!s.uncertainties.every(x=>typeof x==='string')||seen.has(s.option_id))return false;
    if(!t.descriptor.options.some(o=>o.id===s.option_id&&decisionOptionAvailable(o)))return false;seen.add(s.option_id);return true;
  }).slice(0,3);
  if(!cards.length)return '';
  return '<section class="decision-suggestions" aria-label="处理建议"><p class="small muted">以下是系统整理的处理方式。请点击一张卡片选择，选中后再继续核对；系统不会自动执行。</p>'+cards.map(s=>{
    const o=t.descriptor.options.find(o=>o.id===s.option_id),chosen=g.agent?.selected===o.id&&g.option===o.id;
    return '<article class="decision-suggestion'+(chosen?' is-selected':'')+'" data-guide="legacy-suggestion-card" data-option="'+esc(o.id)+'" tabindex="0" role="group" aria-label="'+esc(o.label)+'" aria-selected="'+chosen+'"><div class="suggestion-heading"><h4>'+esc(o.label)+'</h4><span class="suggestion-state">'+(chosen?'已选中，待提交':'点击卡片选择')+'</span></div><p>'+esc(s.reason)+'</p><ul>'+s.uncertainties.map(x=>'<li>还需要确认：'+esc(x)+'</li>').join('')+'</ul><p><strong>选择后：</strong>'+o.effects.map(decisionEffectText).map(esc).join('；')+'</p><p class="small muted"><strong>不会改变：</strong>'+o.not_effects.map(esc).join('；')+'</p>'+(!o.available?'<p>'+esc(o.unavailable_reason)+'</p>':'')+'</article>';
  }).join('')+'</section>';
}
function decisionUseSuggestion(t,id){
  if(!decisionReady(t))return;
  const g=decisionGuide(t),r=g.agent?.response;
  if(!decisionAgentValid(r,t.descriptor.fingerprint)||r.status!=='PROPOSED'||r.suggestion?.option_id!==id||!t.descriptor.options.some(o=>o.id===id&&decisionOptionAvailable(o)))return;
  g.agent.selected=id;decisionChoose(t,id);
}
function decisionAgentPanel(t){
  if(decisionRequiresChoice(t))return typeof renderMaterialGuidance==='function'?renderMaterialGuidance(t):'';
  const agent=decisionGuide(t).agent,r=agent?.response,s=r?.suggestion,available=t.descriptor.options.filter(decisionOptionAvailable),proposed=available.find(o=>o.id===s?.option_id);
  const origin=r?.metadata?.mock===false?'真实调用':r?.metadata?.mock===true?'模拟调用':'调用方式未知';
  return '<aside class="decision-agent"><strong>Agent建议·待人工判断</strong>'+(r?'<small>'+origin+(r.metadata?.model_version?' · '+esc(r.metadata.model_version):'')+'</small>':'')+'<button type="button" data-guide="agent" '+(!materialCanWrite()||!t.descriptor.fingerprint||agent?.busy?'disabled':'')+'>'+(agent?(r?.status==='RUNNING'?'检查分析结果':'重试本次分析'):'请 Agent 帮我分析')+'</button>'+(agent?'<button type="button" class="text" data-guide="reanalyze" '+(agent.busy?'disabled':'')+'>重新分析</button>':'')+
    (agent?.message?'<p role="status">'+esc(agent.message)+'</p>':'')+
    (s?(proposed&&r.status==='PROPOSED'?decisionSuggestionCards(t,[s]):'<p>'+esc(s.reason)+'</p><ul>'+s.uncertainties.map(x=>'<li>'+esc(x)+'</li>').join('')+'</ul><p>暂未给出可执行选项，可记录无法确认的原因。</p>'):'')+'</aside>';
}
function decisionSuggestionRecorded(t,g,d,triage,recorded){
  const choice=g.suggestionChoice||{},channel=choice.channel||'auto',response=typeof materialGuidanceResponse==='function'?materialGuidanceResponse(t,channel):null,candidates=typeof materialGuidanceCandidates==='function'?materialGuidanceCandidates(t,response):[],candidate=candidates[choice.index],option=candidate?.option_id?t.descriptor.options.find(o=>o.id===candidate.option_id):null;
  const label=typeof materialGuidanceLabel==='function'&&candidate?materialGuidanceLabel(candidate,option,choice.index):option?.label||'已提交的处理意见';
  const opinionText=recorded?.text||recorded?.data?.text||recorded?.data?.reason||'';
  return '<section class="panel mat-task decision-chat" data-task-id="'+esc(t.id)+'"><div class="focus-head"><h3 id="materialTaskTitle" tabindex="-1">'+esc(triage?.title||decisionPresentation(t)?.type_label||d.title)+'</h3><p class="decision-explanation">'+esc(triage?.explanation||decisionPresentation(t)?.explanation||d.why.rule)+'</p><small>'+esc(t.filename||d.why.facts)+'</small></div><div class="pad">'+decisionEvidence(t)+(typeof renderProblemReviewDetail==='function'?renderProblemReviewDetail(t):'')+'<section class="decision-handling decision-recorded" aria-label="系统处理状态"><h4 tabindex="-1" data-current-question>意见已记录，系统正在整理</h4><p><strong>你的意见：</strong>'+esc(label)+'</p>'+(opinionText?'<p>'+esc(opinionText)+'</p>':'')+'<p>目前没有需要你继续确认的内容。系统形成可执行方案后，会重新显示明确的确认动作。</p><p class="small muted">原问题和后续审核条件继续保留；这不是人工核实或账务完成。</p><p class="notice" role="status">'+esc(choice.message||'你的操作已完成，等待系统整理。')+'</p><div class="actions"><button type="button" class="secondary" data-action="material-return-list">返回问题列表</button></div></section></div></section>';
}
function decisionWaitingTask(t,d,triage,h){
  const title=triage?.title||decisionPresentation(t)?.type_label||d.title;
  const waiting=h.owner==='SYSTEM'?'系统负责下一步':h.owner==='EXTERNAL'?'等待外部资料或条件':'本项无需继续处理';
  const revoke=t.task_action?.valid?'<button type="button" class="text" data-guide="task-action-revoke">撤销本次处置</button>':'';
  return '<section class="panel mat-task decision-chat" data-task-id="'+esc(t.id)+'"><div class="focus-head"><h3 id="materialTaskTitle" tabindex="-1">'+esc(title)+'</h3><p class="decision-explanation">'+esc(triage?.explanation||decisionPresentation(t)?.explanation||d.why.rule)+'</p><small>'+esc(t.filename||d.why.facts)+'</small></div><div class="pad">'+decisionEvidence(t)+(typeof renderProblemReviewDetail==='function'?renderProblemReviewDetail(t):'')+'<section class="decision-handling decision-waiting" aria-label="当前处理状态"><p class="small muted">'+esc(waiting)+'</p><h4 tabindex="-1" data-current-question>'+esc(h.label)+'</h4><p>'+esc(h.explanation)+'</p><div class="goal"><b>你现在要做什么</b>'+esc(h.owner==='USER'?'按提示继续办理。':'你当前无需操作。状态变化后，系统会给出明确的确认动作。')+'</div><details><summary>查看处理记录与撤销入口</summary><p class="small muted">处置对象 '+esc(t.task_action?.object_id||'')+' · 版本 '+esc(t.task_action?.version||'')+'</p>'+revoke+'</details><div class="actions"><button type="button" class="secondary" data-action="material-return-list">返回问题列表</button></div></section></div></section>';
}
function decisionOpenTaskActionRevoke(t){
  const decision=t.task_action;if(!decision?.valid)return;
  openDialog('撤销本次处置',`<form id="taskActionRevokeForm" class="stack" data-decision="${esc(decision.object_id)}" data-version="${decision.version}" data-task="${esc(t.id)}"><p>撤销后，本事项将按当前原件与规则重新进入办理队列；不会修改原件、事实或正式凭证。</p><label>撤销原因<textarea id="taskActionRevokeReason" required maxlength="2000" placeholder="说明取得了什么新依据或为什么需要重新办理"></textarea></label><button type="submit" class="primary">确认撤销本次处置</button></form>`);
}
function renderDecisionTask(t){
  const d=t.descriptor;
  if(!decisionValid(d)||!decisionBound(t))return '<section class="panel pad"><h3 id="materialTaskTitle" tabindex="-1">任务契约暂不支持或依据已变化</h3><p>请刷新或升级服务后重新核对。本项未执行。</p><button type="button" class="text" data-action="material-return-list">返回问题列表</button></section>';
  const triage=decisionTriage(t);
  if(d.version==='decision-v1')return '<section class="panel mat-task decision-chat" data-task-id="'+esc(t.id)+'" data-decision-version="decision-v1"><div class="focus-head"><h3 id="materialTaskTitle" tabindex="-1">'+esc(triage?.title||d.title)+'</h3><p class="decision-explanation">'+esc(triage?.explanation||d.why.rule)+'</p></div><div class="pad">'+decisionEvidence(t)+'<section class="decision-handling"><h4>历史办理契约（只读）</h4><p>该事项使用旧版 decision-v1，仅保留查看；刷新服务端任务后才能执行当前动作。</p><details><summary>查看旧版动作与影响</summary>'+d.options.map(o=>'<p><strong>'+esc(o.label)+'</strong>：'+o.effects.map(decisionEffectText).map(esc).join('；')+'</p>').join('')+'</details><button type="button" class="secondary" data-action="material-return-list">返回问题列表</button></section></div></section>';
  const handling=decisionHandling(t);
  if(handling&&handling.owner!=='USER')return decisionWaitingTask(t,d,triage,handling);
  if(decisionSystemTask(t))return '<section class="panel mat-task decision-chat" data-task-id="'+esc(t.id)+'"><div class="focus-head"><h3 id="materialTaskTitle" tabindex="-1">'+esc(triage?.title||'分流契约待检查')+'</h3><p class="decision-explanation">'+esc(triage?.explanation||'当前分流契约无法识别，请刷新后核对；本项未执行。')+'</p><small>'+esc(t.filename||d.why.facts)+'</small></div><div class="pad"><p class="small muted">下方初筛提示为原始规则记录，不是当前人工待办结论。</p>'+decisionEvidence(t)+(typeof renderProblemSourceAudit==='function'?renderProblemSourceAudit(triage?.source_audit):'')+('<section aria-label="系统已核对的数据"><h4>系统已核对的数据</h4>'+(typeof renderProblemReviewChecks==='function'?renderProblemReviewChecks(triage?.checks||[],true):'')+'</section>')+'<section class="decision-handling"><h4>下一步</h4><p>'+esc(triage?.next_action||'返回问题列表，交由系统检查负责人核对后刷新。')+'</p><p class="small muted">系统待检查不代表通过；不要求你在此确认、暂缓或补充上传。其他人工待办仍可继续处理。</p>'+(typeof renderProblemReviewDetail==='function'&&t.problem_review?renderProblemReviewDetail(t,true):'')+(t.deferred?'<p class="record-note">原暂缓记录：'+esc(t.response?.data?.reason||'原因已记录')+'</p>':'')+'<button type="button" class="secondary" data-action="material-return-list">返回问题列表</button></section></div></section>';
  const g=decisionGuide(t),o=decisionOption(t),a=decisionAdapters[o.id],steps=decisionSteps(t,o),draft=materialDraft(t);
  const recorded=decisionRecordedOpinion(t);
  if(decisionRequiresChoice(t)&&(g.suggestionChoice?.submitted===true||recorded)&&g.chosen!==true)return decisionSuggestionRecorded(t,g,d,triage,recorded);
  if(decisionRequiresChoice(t)&&g.chosen!==true)return '<section class="panel mat-task decision-chat" data-task-id="'+esc(t.id)+'"><div class="focus-head"><h3 id="materialTaskTitle" tabindex="-1">'+esc(triage?.title||decisionPresentation(t)?.type_label||d.title)+'</h3><p class="decision-explanation">'+esc(triage?.explanation||decisionPresentation(t)?.explanation||d.why.rule)+'</p></div><div class="pad">'+decisionEvidence(t)+(typeof renderProblemReviewDetail==='function'?renderProblemReviewDetail(t):'')+decisionAgentPanel(t)+'<section class="decision-handling"><h4 tabindex="-1" data-current-question>请选择处理方式</h4><p>未默认选择任何方案。选择只进入逐步核对，不会自动提交。</p><nav class="decision-options" aria-label="选择处理方式">'+d.options.map((x,i)=>'<button type="button" class="'+(i===d.options.findIndex(decisionOptionAvailable)?'primary':'secondary')+'" data-guide="option" data-option="'+esc(x.id)+'" aria-pressed="false" '+(!decisionOptionAvailable(x)||!materialCanWrite()?'disabled':'')+'>'+esc(x.label)+'</button>').join('')+'</nav><div class="mat-actionbar"><button type="button" class="text" data-action="material-skip">先看下一项</button></div></section></div></section>';
  g.step=Math.max(0,Math.min(g.step,steps.length));
  if(!steps.length)g.reviewed='';
  if(g.reviewed&&g.reviewed!==decisionAnswerHash(t,o)){g.reviewed='';g.step=Math.min(g.step,steps.length-1);}
  const summary=steps.length>0&&g.step===steps.length,paused=t.deferred&&!draft.resume&&!draft.defer,disabled=!materialCanWrite()||!decisionOptionAvailable(o)||paused,presentation=decisionPresentation(t);
  const list=(title,items)=>items.length?'<details><summary>'+title+'</summary><ul>'+items.map(x=>'<li>'+esc(decisionEffectText(x))+'</li>').join('')+'</ul></details>':'';
  const bankField=d.options.flatMap(x=>x.fields).find(f=>f.slot==='bank_ownership');
  const result=(d.options.some(x=>x.fields.some(f=>f.slot==='bill_business'))?billDecisionSource(t):'')+(bankField?bankDecisionSource(t,bankField):'');
  const answers=steps.slice(0,g.step).map((s,i)=>'<article class="decision-answer"><div><small>'+esc(s.title)+'</small><p>'+esc(s.fields.length?s.fields.map(f=>decisionValue(t,o,f)).join('；'):o.label)+'</p></div><button type="button" class="text" data-guide="edit" data-step="'+i+'">修改</button></article>').join('');
  const fields=steps.map((s,i)=>'<fieldset data-guide-step="'+i+'" '+(i!==g.step?'hidden disabled':disabled&&!s.fields.some(f=>f.slot==='record_selection')?'disabled':'')+'><legend tabindex="-1" '+(i===g.step?'data-current-question':'')+'>'+esc(s.title)+'</legend>'+(s.explanation?'<p>'+esc(s.explanation)+'</p>':'')+s.fields.map(f=>decisionField(t,o,f)).join('')+'</fieldset>').join('');
  const button=paused?'<button type="button" class="primary" data-guide="resume">继续：'+esc(o.label)+'</button>':!steps.length?'<button type="button" class="primary" data-guide="open" '+(disabled?'disabled':'')+'>'+esc(decisionConfirmationLabel(o))+'</button>':summary?'<button type="button" class="primary" data-guide="commit" '+(disabled?'disabled':'')+'>'+esc(decisionConfirmationLabel(o))+'</button>':'<button type="button" class="primary" data-guide="next" '+(disabled?'disabled':'')+'>下一步：'+esc(g.step+1===steps.length?'确认执行内容':steps[g.step+1].title)+'</button>';
  return '<section class="panel mat-task decision-chat" data-task-id="'+esc(t.id)+'" data-decision-version="'+esc(d.version)+'"><div class="focus-head"><h3 id="materialTaskTitle" tabindex="-1">'+esc(triage?.title||presentation?.type_label||d.title)+'</h3><p class="decision-explanation">'+esc(triage?.explanation||presentation?.explanation||'当前尚未提供具体问题解释，请先核对下方原值和来源；不能据此判断客户缺少资料。')+'</p><p class="small">'+esc(d.why.facts)+'</p><small>办理期间：'+esc(d.scope.accounting_period_id)+' · '+esc(decisionStageLabel(d.stage))+'</small></div><div class="pad">'+decisionEvidence(t)+(typeof renderProblemReviewDetail==='function'?renderProblemReviewDetail(t):'')+result+'<section class="decision-handling"><h4 '+(!steps.length?'tabindex="-1" data-current-question':'')+'>接下来怎么处理</h4><div class="decision-question"><p>'+esc(triage?.next_action||d.why_now||d.why.recommendation)+'</p>'+list('需要明确的问题',triage?.questions||[])+list('系统规则',[d.why.rule])+'</div>'+
    '<nav class="decision-options" aria-label="选择处理方式">'+d.options.map(x=>'<button type="button" class="secondary" data-guide="option" data-option="'+esc(x.id)+'" '+(!decisionOptionAvailable(x)||!materialCanWrite()?'disabled':'')+' aria-pressed="'+(x.id===o.id)+'">'+esc(x.label)+'</button>').join('')+'</nav>'+answers+
    (t.deferred?'<div class="record-note">'+esc(t.response?.data.reason)+'</div>':'')+
    '<form id="'+a.form+'" data-artifact="'+esc(t.artifact_id)+'" novalidate>'+fields+
    (summary?'<div class="decision-summary"><h4 tabindex="-1" data-current-question>确认执行内容</h4><p><strong>'+esc(o.label)+'</strong> · '+esc(t.filename||d.why.facts)+'</p><p class="mat-completion">'+esc(o.completion)+'</p>'+list('执行后',o.effects)+list('不会改变',o.not_effects)+'</div>':'')+
    (o.unavailable_reason?'<p class="issue-banner">'+esc(o.unavailable_reason)+'</p>':'')+
    '<div class="mat-actionbar">'+button+(g.step?'<button type="button" class="text" data-guide="back">上一步</button>':'')+'<button type="button" class="text" data-action="material-skip">先看下一项</button></div></form>'+
    list('执行条件',o.requires)+decisionAgentPanel(t)+'</section></div></section>';
}
function decisionCapture(event){
  const card=event.target.closest?.('.decision-chat');if(!card)return;
  const t=currentMaterialTask();if(!t)return;
  if(event.type==='submit'){
    if(decisionAllowedSubmits.has(event.target)&&decisionCanSubmit(t)){decisionAllowedSubmits.delete(event.target);return;}
    event.preventDefault();event.stopImmediatePropagation();decisionNext(t,event.target);return;
  }
  if(event.type==='keydown'&&['Enter',' '].includes(event.key)){
    const suggestionCard=event.target.closest?.('.decision-suggestion[data-guide="suggestion-card"]');
    if(suggestionCard?.dataset?.guide==='suggestion-card'){event.preventDefault();event.stopImmediatePropagation();materialGuidanceChoose(t,suggestionCard.dataset.channel,Number(suggestionCard.dataset.index),suggestionCard.dataset.guidanceToken);return;}
    const legacySuggestionCard=event.target.closest?.('.decision-suggestion[data-guide="legacy-suggestion-card"]');
    if(legacySuggestionCard?.dataset?.guide==='legacy-suggestion-card'){event.preventDefault();event.stopImmediatePropagation();decisionUseSuggestion(t,legacySuggestionCard.dataset.option);return;}
  }
  if(event.type==='keydown'&&event.key==='Enter'&&!event.isComposing&&event.target.tagName==='INPUT'&&['text','search','email','url','tel','password','number'].includes(event.target.type||'text')){
    const form=event.target.closest('form');if(!form)return;
    event.preventDefault();event.stopImmediatePropagation();decisionNext(t,form);return;
  }
  if(event.type!=='click')return;
  const suggestionCard=event.target.closest?.('.decision-suggestion[data-guide="suggestion-card"]');
  if(suggestionCard?.dataset?.guide==='suggestion-card'&&!event.target.closest?.('button,details,summary,a,input,select,textarea')){
    event.preventDefault();event.stopImmediatePropagation();materialGuidanceChoose(t,suggestionCard.dataset.channel,Number(suggestionCard.dataset.index),suggestionCard.dataset.guidanceToken);return;
  }
  const legacySuggestionCard=event.target.closest?.('.decision-suggestion[data-guide="legacy-suggestion-card"]');
  if(legacySuggestionCard?.dataset?.guide==='legacy-suggestion-card'&&!event.target.closest?.('details,summary,a,input,select,textarea')){
    event.preventDefault();event.stopImmediatePropagation();decisionUseSuggestion(t,legacySuggestionCard.dataset.option);return;
  }
  const b=event.target.closest('button');if(!b)return;
  const old=b.dataset.action,op=typeof old==='string'&&old.length?t.descriptor.options.find(o=>decisionAdapters[o.id]?.action===old||decisionAdapters[o.id]?.submitAction===old):null;
  if(!b.dataset.guide&&!op&&!['bill-confirm','invoice-amount-confirm','bill-resume','invoice-amount-resume','decision-resume','material-cancel-defer'].includes(old))return;
  event.preventDefault();event.stopImmediatePropagation();
  if(b.dataset.guide==='record'){
    if(!decisionValid(t.descriptor)||!decisionBound(t))return;
    const r=decisionEvidenceRows(t).rows.find(r=>r.object_id===b.dataset.record);if(!r)return;
    decisionGuide(t).sourceRecord=r.object_id;decisionRemember(t);render();
    const source=document.querySelector?.('.decision-source');if(source)source.open=true;
    if(b.dataset.sourceJump==='true'){const title=source?.querySelector('summary');if(title){title.tabIndex=-1;title.focus();}}
    else [...(document.querySelectorAll?.('.decision-evidence [data-record]')||[])].find(el=>el.dataset.record===r.object_id)?.focus({preventScroll:true});return;
  }
  if(b.dataset.guide==='guidance-refresh')return void exclusive(async()=>{const epoch=state.epoch;try{await loadWorkbench();if(epoch===state.epoch)notify('建议状态已刷新，未调用模型或执行业务处理。');}catch(e){if(epoch===state.epoch)notify(e.message,true);}});
  if(b.dataset.guide==='task-action-revoke')return decisionOpenTaskActionRevoke(t);
  if(!decisionReady(t))return;
  const g=decisionGuide(t),form=card.querySelector('form'),act=b.dataset.guide;
  if(op){if(op.id===g.option)decisionNext(t,form);else decisionChoose(t,op.id);return;}
  if(act==='option')return decisionChoose(t,b.dataset.option);
  if(act==='suggestion')return decisionUseSuggestion(t,b.dataset.option);
  if(act==='suggestion-v2'||act==='suggestion-select')return materialGuidanceChoose(t,b.dataset.channel,Number(b.dataset.index),b.dataset.guidanceToken);
  if(act==='suggestion-submit')return void materialGuidanceSubmit(t,b.dataset.channel,Number(b.dataset.index),b.dataset.guidanceToken);
  if(act==='custom-validate')return void materialGuidanceCustom(t);
  if(act==='opinion-save')return void materialGuidanceSaveOpinion(t);
  if(act==='guidance-retry')return void exclusive(()=>materialGuidanceRetry(t,b.dataset.channel,b.dataset.guidanceToken));
  if(act==='agent'||act==='reanalyze')return void decisionAskAgent(t,act==='reanalyze');
  if(act==='commit')return decisionCommit(t,form);
  if(act==='open')return decisionOpen(t);
  if(act==='resume'||old?.endsWith('resume')){materialDraft(t).resume=true;materialDraft(t).defer=false;}
  else if(act==='edit'||act==='back'){g.step=act==='edit'?Math.max(0,Math.min(Number(b.dataset.step)||0,g.step)):Math.max(0,g.step-1);g.reviewed='';}
  else if(old==='material-cancel-defer')return decisionChoose(t,t.descriptor.options[0].id);
  else return decisionNext(t,form);
  decisionRemember(t);decisionShowStep();
}
document.addEventListener('click',decisionCapture,true);
document.addEventListener('submit',decisionCapture,true);
document.addEventListener('submit',event=>{
  if(event.target.id!=='taskActionRevokeForm')return;
  event.preventDefault();const form=event.target,epoch=state.epoch,taskId=form.dataset.task;
  exclusive(async()=>{try{
    const result=await command('revoke_task_action',form.dataset.decision,Number(form.dataset.version),{reason:$('taskActionRevokeReason').value},false);
    if(epoch!==state.epoch)return;closeDialog();await loadWorkbench();
    const task=state.overview.material_review.tasks.find(item=>item.id===taskId),next=result.next||state.overview.material_review.next_step;
    if(task){const ui=materialState();ui.selected=task.id;ui.screen='detail';materialSaveNavigation();}
    render();notify('处置已撤销；'+(next?.title?'下一步：'+next.title:'事项已重新进入办理队列。'));
  }catch(error){if(epoch===state.epoch)notify(error.message,true);}});
},true);
document.addEventListener('keydown',decisionCapture,true);
document.addEventListener('input',event=>{
  if(!event.target.closest?.('.decision-chat'))return;
  const t=currentMaterialTask();if(!t)return;
  if(event.target.id==='materialCustomText'){
    const g=decisionGuide(t);g.custom=g.custom||{text:''};g.custom.text=event.target.value;g.custom.dirty=true;delete g.custom.response;delete g.suggestionChoice;decisionRemember(t);return;
  }
  if(event.target.dataset.taskActionField){materialDraft(t).taskAction[event.target.dataset.taskActionField]=event.target.value;materialSaveDraft(t);}
  const g=decisionGuide(t),key=decisionIdentity(t);g.reviewed='';
  if(g.step>=decisionSteps(t,decisionOption(t)).length)g.step=0;
  // Existing input listeners save the actual business draft during this same event.
  queueMicrotask(()=>{if(currentMaterialTask()?.id===t.id&&decisionIdentity(currentMaterialTask())===key)decisionRemember(t);});
},true);

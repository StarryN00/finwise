'use strict';
const billKinds={RECEIVED:'本期收到',HELD:'以前期间收到、本期持有',ENDORSED:'本期背书转出',OTHER:'其他（仅记录意见）'};
function billDraft(t){const d=materialDraft(t);if(!d.bill)d.bill={business_kind:'',business_period:'',business_date:'',original_receipt_period:'',account_candidate_id:'',account_name:'',account_code:'',reason:'',evidence_ids:[],search:''};return d.bill;}
function billConfirmationCard(c){
  const d=c.data,active=c.valid&&c.status!=='REVOKED';
  return `<article class="proof bill-confirmation"><div class="row"><h4>票据 ${esc(d.binding.acceptance_no)} · 子票 ${esc(d.binding.sub_range)}</h4>${badge(c.status==='REVOKED'?'已撤销':c.stale?'依据已变化':c.status==='OPINION'?'意见已记录，归属待确认':'人工补充确认',active?'blue':'')}</div><p>${esc(billKinds[d.business_kind])} · 业务期间 ${esc(d.business_period)}${d.original_receipt_period?` · 原收票期间 ${esc(d.original_receipt_period)}`:''}${d.business_date?` · 日期 ${esc(d.business_date)}`:' · 日期精度：月份'}</p><p>科目：${esc(d.account_code)} ${esc(d.account_name)} · ${esc(d.account_source)}</p><p>判断依据：${esc(d.reason)}</p><p class="small muted">确认人 ${esc(d.confirmed_by)} · ${esc(d.confirmed_at)}。原件未记载的字段仍保留为空；此记录不代表账务可用。</p>${objectButton(d.binding.fact_id,'查看原件与提取值')}${c.status!=='REVOKED'?`<button class="text" data-action="bill-revoke" data-confirmation="${esc(c.object_id)}" ${materialCanWrite()?'':'disabled'}>撤销本条确认</button>`:''}</article>`;
}
function billResults(){
  const review=state.overview.bill_review;if(!review?.confirmations?.length)return '';
  return `<section class="panel pad"><h3>票据人工补充记录 · 有效确认 ${review.confirmed_count} 条</h3><p class="small muted">单独留痕，不加入原件核实数量。拟用或历史科目仍需账套核对。</p>${review.confirmations.map(billConfirmationCard).join('')}</section>`;
}
function billDecisionSource(t){const r=state.overview.material_review.records.find(r=>t.record_ids.includes(r.object_id));return r?.bill_confirmation?billConfirmationCard(r.bill_confirmation):'';}
function billDecisionFields(t,field){
  const d=billDraft(t),p=decisionPropertyMap(field),candidates=state.overview.bill_review?.candidates||[],selected=candidates.find(c=>c.id===d.account_candidate_id);
  const options=candidates.filter(c=>!d.search||`${c.code} ${c.name}`.includes(d.search));
  if(selected&&!options.some(c=>c.id===selected.id))options.unshift(selected);
  const ids={business_kind:'billKind',business_period:'billPeriod',original_receipt_period:'billOriginalPeriod',business_date:'billDate',search:'billSearch',account_candidate_id:'billAccount',account_name:'billAccountName',account_code:'billAccountCode',reason:'billReason'};
  return '<div class="bill-grid">'+field.properties.map(prop=>{
    const k=prop.name;if(k==='original_receipt_period'&&d.business_kind!=='HELD'||['account_name','account_code'].includes(k)&&d.account_candidate_id)return '';
    if(k==='evidence_ids')return `<details><summary>${esc(prop.label)}</summary><p>${esc(prop.help)}</p>${activeArtifacts().map(a=>`<label><input type="checkbox" data-bill-evidence="${esc(a.object_id)}" ${d.evidence_ids.includes(a.object_id)?'checked':''}>${esc(a.data.filename)}</label>`).join('')}</details>`;
    const attrs=`id="${ids[k]}" data-bill-field="${k}" ${prop.required?'required':''} placeholder="${esc(prop.placeholder)}"`;
    let control;
    if(k==='business_kind')control=`<select ${attrs}><option value="">请选择</option>${Object.entries(prop.choices).map(([v,label])=>`<option value="${esc(v)}" ${d[k]===v?'selected':''}>${esc(label)}</option>`).join('')}</select>`;
    else if(k==='account_candidate_id')control=`<select ${attrs}><option value="">未选择／手工填写</option>${options.map(c=>`<option value="${esc(c.id)}" ${d[k]===c.id?'selected':''}>${esc(c.code)} ${esc(c.name)} · ${esc(c.source_label)}</option>`).join('')}</select>${d[k]&&!selected?'<small>已选科目依据已变化，请重新选择。</small>':''}`;
    else if(k==='reason')control=`<textarea ${attrs} maxlength="2000">${esc(d[k])}</textarea>`;
    else control=`<input ${attrs} type="${['business_period','original_receipt_period'].includes(k)?'month':k==='business_date'?'date':k==='search'?'search':'text'}" maxlength="${k==='account_code'?40:200}" value="${esc(d[k])}">`;
    return decisionPropertyLabel(prop,control);
  }).join('')+'</div>';
}
function installBillActions(){
  actions['bill-resume']=()=>{const t=currentMaterialTask();if(!t||!materialCanWrite()||!materialTaskIsCurrent(t))return;materialDraft(t).resume=true;materialSaveDraft(t);render();$('billKind')?.focus();};
  actions['bill-confirm']=()=>exclusive(async()=>{
    const t=currentMaterialTask();if(t?.kind!=='BILL'||!materialCanWrite()||!materialTaskIsCurrent(t))return;
    const r=state.overview.material_review.records.find(r=>t.record_ids.includes(r.object_id)),d=billDraft(t);
    const payload={input_token:t.input_token,business_kind:d.business_kind,business_period:d.business_period,business_date:d.business_date,original_receipt_period:d.business_kind==='HELD'?d.original_receipt_period:'',account_candidate_id:d.account_candidate_id,account_name:d.account_candidate_id?'':d.account_name,account_code:d.account_candidate_id?'':d.account_code,reason:d.reason,evidence_ids:[...d.evidence_ids]};
    const epoch=state.epoch,group=materialState().group,revision=materialDraftRevision(materialDraft(t));
    await command('confirm_bill_business',r.object_id,r.version,payload);
    if(epoch!==state.epoch)return;
    const cleared=materialDeleteDraft(t.id,revision);
    if(!cleared||!materialDetailStillOpen(group,t.id)){notify('票据处理记录已保存，未改变当前查看位置。');return;}
    const latest=state.overview.material_review.tasks.find(x=>x.id===t.id),entry=group?.entries.find(x=>x.id===t.id);
    if(latest&&entry)entry.fingerprint=materialTaskFingerprint(latest);
    materialAdvance(t,payload.business_kind==='OTHER'?'bill_opinion':'bill_confirmed');
  });
  actions['bill-revoke']=b=>exclusive(async()=>{
    if(!materialCanWrite())return;const c=state.overview.bill_review?.confirmations.find(c=>c.object_id===b.dataset.confirmation);if(!c)return;
    const epoch=state.epoch;await command('revoke_bill_business',c.object_id,c.version,{reason:'用户撤销，重新核对'});
    if(epoch!==state.epoch)return;
    for(const entry of materialState().group?.entries||[]){const latest=state.overview.material_review.tasks.find(t=>t.id===entry.id);if(latest&&entry.recordIds.includes(c.data.binding.fact_id)){entry.fingerprint=materialTaskFingerprint(latest);entry.outcome='';}}
    materialSaveNavigation();notify('票据确认已撤销，业务归属问题已恢复；原件没有改变。');render();
  });
  document.addEventListener('input',e=>{
    if(!e.target.closest('#billForm'))return;const t=currentMaterialTask();if(t?.kind!=='BILL')return;const d=billDraft(t),field=e.target.dataset.billField;
    if(field)d[field]=e.target.value;
    const evidence=e.target.dataset.billEvidence;if(evidence)d.evidence_ids=e.target.checked?[...new Set([...d.evidence_ids,evidence])]:d.evidence_ids.filter(id=>id!==evidence);
    materialSaveDraft(t);if(['business_kind','account_candidate_id','search'].includes(field))render();
  });
  document.addEventListener('submit',e=>{if(e.target.id==='billForm'){e.preventDefault();actions['bill-confirm']().catch(error=>notify(error.message,true));}});
}

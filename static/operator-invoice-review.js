'use strict';
function invoiceAmountResults(){
  const all=state.overview.invoice_amount_review?.confirmations||[];
  if(!all.length)return '';
  return `<section class="panel pad"><h3>红字／零金额核对 · 已处理 ${all.filter(c=>c.valid).length} 条</h3><p class="muted">仅表示该金额提醒已人工核对；其他问题与账务校验独立保留。</p>${all.map(c=>`<article class="proof"><div class="row"><h4>发票 ${esc(c.data.invoice_no)}</h4>${badge(c.status==='REVOKED'?'已撤销':c.stale?'依据已变化':'已处理',c.valid?'green':'')}</div><p>价税合计 ${esc(c.data.invoice_total)} 元 · ${esc(c.data.reason)}</p><p class="small muted">核对人 ${esc(c.data.confirmed_by)} · ${esc(c.data.confirmed_at)}</p>${objectButton(c.data.binding.fact_id,'查看原件与提取值')}${c.status==='CONFIRMED'?`<button class="text" data-action="invoice-amount-revoke" data-confirmation="${esc(c.object_id)}" ${materialCanWrite()?'':'disabled'}>撤销本条核对</button>`:''}</article>`).join('')}</section>`;
}
function installInvoiceAmountActions(){
  actions['invoice-amount-resume']=()=>{const t=currentMaterialTask();if(!t||!materialTaskIsCurrent(t)||!materialCanWrite())return;materialDraft(t).resume=true;materialSaveDraft(t);render();};
  actions['invoice-amount-confirm']=()=>exclusive(async()=>{
    const t=currentMaterialTask();if(t?.kind!=='INVOICE_AMOUNT'||!materialCanWrite()||!materialTaskIsCurrent(t))return;
    const r=state.overview.material_review.records.find(r=>t.record_ids.includes(r.object_id)),d=materialDraft(t);
    const epoch=state.epoch,group=materialState().group,revision=materialDraftRevision(d);
    await command('confirm_invoice_amount',r.object_id,r.version,{input_token:t.input_token,reason:d.note});
    if(epoch!==state.epoch)return;
    if(!materialDeleteDraft(t.id,revision)||!materialDetailStillOpen(group,t.id)){notify('本张发票的金额核对已保存，未改变当前查看位置。');return;}
    materialAdvance(t,'invoice_amount_confirmed');
  });
  actions['invoice-amount-revoke']=b=>exclusive(async()=>{
    if(!materialCanWrite())return;
    const c=state.overview.invoice_amount_review?.confirmations.find(c=>c.object_id===b.dataset.confirmation);if(!c)return;
    const epoch=state.epoch;await command('revoke_invoice_amount',c.object_id,c.version,{reason:'用户撤销，重新核对'});
    if(epoch!==state.epoch)return;notify('本条金额核对已撤销，对应待办已恢复。');render();
  });
  document.addEventListener('submit',e=>{if(e.target.id==='invoiceAmountForm'){e.preventDefault();actions['invoice-amount-confirm']().catch(error=>notify(error.message,true));}});
}

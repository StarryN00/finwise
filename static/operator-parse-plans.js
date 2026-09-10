'use strict';

// Source samples stay in memory; session drafts contain structural pointers only.
const parsePlanUI = {key:'', id:'', kind:'', entry:null, drafts:new Map(), sequence:0, pending:false, error:'', feedback:'', origin:null};
const parsePlanKinds = ['bank_statement','purchase_invoices','sales_invoices'];
const parsePlanLabels = {REVIEW:'结构方案待核对',NEEDS_INPUT:'请人工指认结构',FAILED:'结构识别失败',APPLIED:'方案已应用',STALE:'方案已失效',RUNNING:'正在识别结构',QUEUED:'等待识别'};
const parsePlanRoles = {DATA:'业务数据表',REFERENCE:'参考表（不提取）',UNKNOWN:'用途待确认'};
function parsePlanSupported(a,kind){return !!a&&a.status==='ACTIVE'&&parsePlanKinds.includes(kind||a.data?.parse_options?.document_kind)&&/\.xlsx?$/i.test(a.data?.filename||'')&&!(a.data?.parse_sheets||[]).some(s=>['single_amount_bank','boc-text-v1'].includes(s.layout));}
function resetParsePlanState(){parsePlanUI.sequence++;parsePlanUI.key='';parsePlanUI.id='';parsePlanUI.entry=null;parsePlanUI.drafts.clear();parsePlanUI.pending=false;parsePlanUI.error='';parsePlanUI.feedback='';parsePlanUI.origin=null;}
function parsePlanState(){const key=JSON.stringify([state.user?.user_id,scopeKey(scope())]);if(parsePlanUI.key!==key){resetParsePlanState();parsePlanUI.key=key;}return parsePlanUI;}
function parsePlanDraftKey(a,kind){return JSON.stringify([parsePlanState().key,a.object_id,a.version,a.data.sha256,kind]);}
function parsePlanStore(key,value){try{const k='finwise.parse-plan.draft.'+key;if(value===undefined)return JSON.parse(sessionStorage.getItem(k)||'null');sessionStorage.setItem(k,JSON.stringify(value));}catch{}return null;}
function parsePlanCopy(value){return JSON.parse(JSON.stringify(value));}
function parsePlanColumn(index){let s='';for(index++;index;index=Math.floor((index-1)/26))s=String.fromCharCode(65+(index-1)%26)+s;return s;}
function parsePlanColumnIndex(col){return [...col].reduce((n,c)=>n*26+c.charCodeAt(0)-64,0)-1;}
function parsePlanButton(a){return Array.isArray(state.overview?.parse_plans)&&parsePlanSupported(a)?`<button class="text" data-action="parse-plan-open" data-artifact="${esc(a.object_id)}">核对表格结构</button>`:'';}
function parsePlanCurrent(){const ui=parsePlanState(),a=state.overview?.artifacts?.find(a=>a.object_id===ui.id);return Array.isArray(state.overview?.parse_plans)&&a&&ui.entry&&parsePlanDraftKey(a,ui.kind)===ui.entry.key&&a.status==='ACTIVE';}
function parsePlanSave(){const e=parsePlanState().entry;if(e)parsePlanStore(e.key,{proposal:e.proposal,sheet:e.sheet});}
function parsePlanInvalidate(){const e=parsePlanState().entry;if(!e)return;e.revision++;e.preview=null;e.token='';e.confirmed=false;e.step='edit';parsePlanSave();}
function parsePlanCanApply(){const ui=parsePlanState(),e=ui.entry;return !!(e&&parsePlanCurrent()&&!readonly()&&!ui.pending&&e.step==='impact'&&e.confirmed&&e.preview?.apply_ready===true&&e.token&&e.plan?.status==='REVIEW');}
function parsePlanFields(kind){return kind==='bank_statement'?['transaction_date','expense','income','balance','counterparty','counterparty_account','transaction_id','summary','note']:['invoice_no','invoice_date','net_amount','tax','tax_rate','invoice_total','seller_name','seller_tax_id','buyer_name','buyer_tax_id','invoice_status'];}
function parsePlanHeader(sheet,number){const rows=sheet.cachedRows||sheet.rows,row=rows.find(r=>r.row===Number(number));if(!row)return [];const values=[...row.values];for(const [c1,r1,c2,r2] of sheet.merged_cells||[]){if(r1<=number&&number<=r2){const anchor=rows.find(r=>r.row===r1)?.values[c1-1];for(let c=c1-1;c<c2;c++)if(values[c]==null||values[c]==='')values[c]=anchor;}}return values;}
function parsePlanValidate(e,kind){
  if(e.proposal.outcome!=='PLAN')throw Error('请先逐表确认用途和字段对应。');
  for(const s of e.proposal.sheets){
    if(s.role==='UNKNOWN')throw Error('还有工作表用途待确认，请逐表核对。');
    if(s.role!=='DATA')continue;
    if(!Number.isInteger(s.header_row)||s.header_row<1||s.header_row>20000)throw Error('表头行号须为 1–20000 的整数。');
    const cols=Object.values(s.fields);if(new Set(cols).size!==cols.length)throw Error('同一原表列不能对应多个目标字段。');
    const required=kind==='bank_statement'?['transaction_date']:['invoice_no','invoice_date','net_amount','tax'];
    if(kind==='bank_statement'&&!s.fields.income&&!s.fields.expense)throw Error('本期通用银行方案仅支持收入、支出分列。若原表只有单金额列和方向列，此结构暂不支持，请保留原件交由专用解析处理；无需重复补资料。');
    if(required.some(f=>!s.fields[f]))throw Error('请补齐必需字段对应；原表没有该字段时请保留当前方案，不能用其他值替代。');
  }
}
async function openParsePlan(artifact,kind){
  kind=kind||artifact?.data?.parse_options?.document_kind;if(!Array.isArray(state.overview?.parse_plans)||!parsePlanSupported(artifact,kind))return;
  const ui=parsePlanState(),origin=state.view==='parse-plans'?ui.origin:{view:state.view,scrollY:window.scrollY};
  ui.id=artifact.object_id;ui.kind=kind;ui.origin=origin;ui.entry=null;ui.error='';ui.feedback='';ui.pending=true;
  const epoch=state.epoch,seq=++ui.sequence,key=parsePlanDraftKey(artifact,kind),selected=parsePlanCopy(scope());
  state.view='parse-plans';closeDialog();render();
  try{
    const response=await request('/api/v1/commands',{scope:selected,action:'inspect_parse_plan',target_id:artifact.object_id,target_version:artifact.version,payload:{document_kind:kind},idempotency_key:'inspect-'+crypto.randomUUID()});
    const result=response.effect;
    if(epoch!==state.epoch||seq!==ui.sequence||state.view!=='parse-plans')return;
    if(response.command?.status!=='SUCCEEDED'||result?.artifact?.version!==artifact.version||result?.artifact?.sha256!==artifact.data.sha256||!Array.isArray(result?.sheets)||!result?.proposal)throw Error('原件版本或样本响应不完整，请重新打开；草稿仍保留。');
    const plans=(result.parse_plans||[]).filter(p=>p.data.artifact_id===artifact.object_id&&(p.status==='APPLIED'?p.data.applied_artifact_version:p.data.artifact_version)===artifact.version&&p.data.sha256===artifact.data.sha256);
    const plan=[...plans].reverse().find(p=>!['STALE','APPLIED'].includes(p.status));
    const applied=[...plans].reverse().find(p=>p.status==='APPLIED');
    const saved=ui.drafts.get(key)||parsePlanStore(key),proposal=plan?.data.proposal?.sheets?.length?plan.data.proposal:applied?.data.proposal||result.proposal;
    ui.entry={key,source:result,plan:plan||null,proposal:parsePlanCopy(saved?.proposal||proposal),sheet:saved?.sheet??result.sheets[0]?.sheet_index??0,revision:0,preview:null,token:'',confirmed:false,step:'edit',windowStart:1,pageSize:40};
    ui.drafts.set(key,ui.entry);ui.error=plan?.data.error||'';
  }catch(error){if(epoch===state.epoch&&seq===ui.sequence)ui.error=error.message;}
  finally{if(epoch===state.epoch&&seq===ui.sequence){ui.pending=false;if(state.view==='parse-plans'){render();$('parsePlanTitle')?.focus({preventScroll:true});}}}
}
async function parsePlanOperation(kind){
  const ui=parsePlanState(),e=ui.entry;if(!e||ui.pending||readonly()||!parsePlanCurrent())return;
  if(kind==='apply'&&!parsePlanCanApply())return;
  const epoch=state.epoch,seq=++ui.sequence,revision=e.revision,selected=parsePlanCopy(scope());
  ui.pending=true;ui.error='';ui.feedback=kind==='identify'?'正在识别表格结构，请等待…':kind==='preview'?'正在按原件检查方案…':'正在应用已确认方案…';render();
  const valid=()=>epoch===state.epoch&&seq===ui.sequence&&ui.entry===e&&e.revision===revision&&state.view==='parse-plans';
  try{
    let result;
    if(kind==='identify'){
      e.requestKey=e.requestKey||'structure-'+crypto.randomUUID();
      result=await request('/api/v1/agent/suggestion',{stage:'STRUCTURE_PLAN',scope:selected,artifact_id:ui.id,artifact_version:e.source.artifact.version,document_kind:ui.kind,idempotency_key:e.requestKey});
      if(!valid())return;
      if(!result.object?.object_id)throw Error('未收到完整识别结果，请重试；当前输入保留。');
      e.requestKey='';e.plan=result.object;parsePlanInvalidate();
      if(result.object.status==='REVIEW'&&result.object.data.proposal?.sheets?.length){e.proposal=parsePlanCopy(result.object.data.proposal);parsePlanSave();ui.feedback='结构建议已返回，请对照原件逐表核对，再检查方案。';}
      else throw Error(result.object.data.error||'未形成可靠结构方案，请根据原件人工调整。');
    }else if(kind==='preview'){
      parsePlanValidate(e,ui.kind);e.confirmed=false;e.preview=null;e.token='';
      const target=e.plan||e.source.artifact;
      result=await command('preview_parse_plan',target.object_id,target.version,{proposal:parsePlanCopy(e.proposal),...(!e.plan?{document_kind:ui.kind}:{})},false);
      if(!valid())return;
      const p=result.effect?.object;if(!p?.object_id||!p.data?.preview||!p.data.preview_token||!p.data.impact)throw Error('预览响应不完整，暂不能应用；请重试检查方案。');
      e.plan=p;e.preview=p.data.preview;e.token=p.data.preview_token;e.step='preview';e.previewPage=0;ui.feedback='已完成本地方案检查，请核对记录范围、排除行和检查结果。';
    }else{
      result=await command('apply_parse_plan',e.plan.object_id,e.plan.version,{proposal:parsePlanCopy(e.proposal),preview_token:e.token,plan_confirmed:true},false);
      if(!valid())return;
      if(result.effect?.object?.status!=='APPLIED')throw Error('未收到完整应用结果，请重试核对；当前输入保留。');
      e.plan=result.effect.object;e.confirmed=false;e.token='';e.step='applied';ui.feedback='方案已应用，旧事实保留历史版本；请继续核对新提取结果。';
      await loadWorkbench();
    }
  }catch(error){if(valid()){ui.error=error.message;ui.feedback='';if(error.status===409){e.confirmed=false;e.token='';e.preview=null;e.step='edit';}}}
  finally{if(epoch===state.epoch&&seq===ui.sequence){ui.pending=false;if(state.view==='parse-plans')render();}}
}
async function parsePlanLoadWindow(){
  const ui=parsePlanState(),e=ui.entry;if(!e||ui.pending||!parsePlanCurrent())return;
  const start=e.windowStart,size=e.pageSize;
  if(!Number.isInteger(start)||start<1||start>20000||!Number.isInteger(size)||size<1||size>100){ui.error='起始行须为 1–20000 的整数，每页行数须为 1–100。';render();return;}
  const epoch=state.epoch,seq=++ui.sequence;ui.pending=true;ui.error='';render();
  try{
    const response=await request('/api/v1/commands',{scope:parsePlanCopy(scope()),action:'inspect_parse_plan',target_id:ui.id,target_version:e.source.artifact.version,payload:{document_kind:ui.kind,row_start:start,page_size:size},idempotency_key:'inspect-'+crypto.randomUUID()});
    if(epoch!==state.epoch||seq!==ui.sequence||ui.entry!==e||state.view!=='parse-plans')return;
    const next=response.effect;
    if(response.command?.status!=='SUCCEEDED'||next?.artifact?.version!==e.source.artifact.version||next?.artifact?.sha256!==e.source.artifact.sha256||!Array.isArray(next.sheets))throw Error('原件窗口响应不完整，已保留当前输入。');
    for(const sheet of next.sheets){const previous=e.source.sheets.find(s=>s.sheet_index===sheet.sheet_index),cache=new Map((previous?.cachedRows||previous?.rows||[]).map(r=>[r.row,r]));for(const r of sheet.rows)cache.set(r.row,r);sheet.cachedRows=[...cache.values()];}
    e.source.sheets=next.sheets;ui.feedback=`已读取第 ${start}–${start+size-1} 行范围，结构输入保持；可调整表头及问题行用途。`;
  }catch(error){if(epoch===state.epoch&&seq===ui.sequence)ui.error=error.message;}
  finally{if(epoch===state.epoch&&seq===ui.sequence){ui.pending=false;if(state.view==='parse-plans')render();}}
}
function renderParsePlanWindow(e){return `<div class="pp-window"><label>原件起始行<input type="number" min="1" max="20000" step="1" data-pp="window-start" value="${e.windowStart}"></label><label>每页行数<select data-pp="page-size">${[20,40,100].map(n=>`<option ${e.pageSize===n?'selected':''} value="${n}">${n} 行</option>`).join('')}</select></label><button class="secondary" data-action="parse-plan-window" ${parsePlanState().pending?'disabled':''}>读取行范围</button><p class="small muted">表头或疑点不在样本中时，输入对应行号读取。${objectButton(parsePlanState().id,'查看完整原件')}</p></div>`;}
function renderParsePlanSample(e){
  const s=e.source.sheets.find(s=>s.sheet_index===e.sheet),p=e.proposal.sheets.find(s=>s.sheet_index===e.sheet);if(!s||!p)return '<p>当前工作表样本不可用。</p>';
  const width=Math.max(0,...s.rows.map(r=>r.values.length)),rows=s.rows;
  return `<section class="pp-source"><h3>1. 对照原始样本</h3><p class="small muted">本地读取的原值 · 行号与原件一致 · 展示 ${rows.length} 行样本，检查时按完整原件计算</p><div class="pp-controls"><label>工作表<select data-pp="sheet">${e.source.sheets.map(s=>`<option value="${s.sheet_index}" ${s.sheet_index===e.sheet?'selected':''}>${esc(s.name)}</option>`).join('')}</select></label><label>工作表用途<select data-pp="role" ${readonly()?'disabled':''}>${Object.entries(parsePlanRoles).map(([k,v])=>`<option value="${k}" ${p.role===k?'selected':''}>${v}</option>`).join('')}</select></label><label>表头所在行<input data-pp="header" type="number" min="1" max="20000" step="1" value="${esc(p.header_row||'')}" ${p.role!=='DATA'||readonly()?'disabled':''}></label></div><div class="table-wrap pp-sample" tabindex="0" role="region" aria-label="原件样本，可横向滚动"><table><thead><tr><th>原件行号</th>${Array.from({length:width},(_,i)=>`<th>${parsePlanColumn(i)}</th>`).join('')}<th>行用途指认</th></tr></thead><tbody>${rows.map(r=>`<tr class="${r.row===p.header_row?'pp-header-row':''}"><th>${r.row}${r.row===p.header_row?' · 表头':''}</th>${Array.from({length:width},(_,i)=>`<td>${esc(r.values[i]??'')}</td>`).join('')}<td>${r.row>p.header_row&&p.role==='DATA'?`<select aria-label="第 ${r.row} 行用途" data-pp="reference" data-row="${r.row}" ${readonly()?'disabled':''}>${[['','按结构检查'],['TOTAL','合计参考行'],['HEADER','重复表头'],['NOTE','附注参考行']].map(([k,v])=>`<option value="${k}" ${(p.reference_rows||[]).find(x=>x.row===r.row)?.role===k?'selected':''}>${v}</option>`).join('')}</select>`:'—'}</td></tr>`).join('')}</tbody></table></div></section>`;
}
function renderParsePlanFields(e,kind){
  const s=e.source.sheets.find(s=>s.sheet_index===e.sheet),p=e.proposal.sheets.find(s=>s.sheet_index===e.sheet);if(!s||!p||p.role!=='DATA')return '<p class="issue-banner">请逐表明确用途。参考表不生成明细；用途待确认会阻止应用。</p>';
  const headers=parsePlanHeader(s,p.header_row),required=kind==='bank_statement'?['transaction_date']:['invoice_no','invoice_date','net_amount','tax'];
  return `<section><h3>2. 核对字段对应</h3><p class="small muted">${kind==='bank_statement'?'日期必填，收入和支出至少对应一列。':'发票号码、开票日期、不含税金额和税额必填。'} 只能选择原表列，不修改原始值。</p><div class="pp-fields">${parsePlanFields(kind).map(f=>{const chosen=p.fields[f]||'',samples=s.rows.filter(r=>r.row>p.header_row).slice(0,3).map(r=>chosen?r.values[parsePlanColumnIndex(chosen)]:null);return `<label><span>${esc(materialFieldLabels[f]||fieldLabels[f]||'其他字段')}${required.includes(f)?' *':''}</span><select data-pp="field" data-field="${f}" ${readonly()?'disabled':''}><option value="">未映射</option>${chosen&&!headers[parsePlanColumnIndex(chosen)]?`<option selected value="${esc(chosen)}">${esc(chosen)} · 原表头未定位，请重新选择</option>`:''}${headers.map((h,i)=>h!=null&&h!==''?`<option value="${parsePlanColumn(i)}" ${chosen===parsePlanColumn(i)?'selected':''}>${parsePlanColumn(i)} · ${esc(h)}</option>`:'').join('')}</select><small>原始样例：${samples.map(v=>esc(v??'空白')).join(' / ')}</small></label>`;}).join('')}</div></section>`;
}
function parsePlanDisplay(value){
  if(value==null)return '未提供';
  if(typeof value==='boolean')return value?'是':'否';
  if(Array.isArray(value))return value.map(parsePlanDisplay).join('、');
  if(typeof value==='object')return Object.entries(value).map(([k,v])=>(materialFieldLabels[k]||fieldLabels[k]||({source_regions:'来源',forward:'正序',reverse:'倒序',balance:'余额'})[k]||'检查值')+'：'+parsePlanDisplay(v)).join('；');
  return ({IN:'收入',OUT:'支出',CNY:'人民币',PASS:'通过',FAIL:'未通过',UNKNOWN:'待确认',UNIT:'单位汇总',DETAIL:'明细',PERIOD_EXCEPTION:'期间待确认'})[value]||String(value);
}
function parsePlanTable(head,rows){return `<div class="table-wrap pp-result-table" tabindex="0" role="region" aria-label="预览对照表，可横向滚动"><table><thead><tr>${head.map(v=>`<th>${esc(v)}</th>`).join('')}</tr></thead><tbody>${rows.length?rows.join(''):`<tr><td colspan="${head.length}">暂无可展示结果</td></tr>`}</tbody></table></div>`;}
function parsePlanDifference(declared,computed){
  // Integer minor units avoid a misleading floating-point difference in the UI.
  const minor=v=>{if(!/^-?\d+(\.\d{1,2})?$/.test(String(v)))return null;const [whole,fraction='']=String(v).replace('-','').split('.');return (BigInt(whole)*100n+BigInt(fraction.padEnd(2,'0')))*(String(v).startsWith('-')?-1n:1n);};
  const d=minor(declared),c=minor(computed);if(d===null||c===null)return '详见检查说明';const n=c-d,abs=n<0n?-n:n;return `${n<0n?'-':''}${abs/100n}.${String(abs%100n).padStart(2,'0')}`;
}
function renderParsePlanPreview(e){
  const p=e.preview;if(!p)return '';
  const checks=p.checks||{},status={MATCH:'已完成对账检查',PASS:'已完成对账检查',REVIEW:'检查发现疑点',UNATTESTED:'缺少独立对账依据',RECONCILED:'已完成对账检查',RECONCILED_OUT_OF_PERIOD:'全量对账一致，存在跨期记录',NONE:'缺少独立对账依据'};
  const page=e.previewPage||0,records=(p.records||[]).slice(page*5,page*5+5);
  const fields=records.flatMap(r=>Object.entries(r.normalized_value||{}).filter(([,v])=>v!=null).map(([f,v])=>{const location=r.field_sources?.[f];return `<tr><td>${esc(r.original_value?.sheet||r.source_anchor?.sheet||'原件')} · 第 ${esc(r.original_value?.row||r.source_anchor?.row||'—')} 行</td><td>${esc(materialFieldLabels[f]||fieldLabels[f]||({period:'业务期间',direction:'收支方向',amount:'金额'})[f]||'其他提取字段')}</td><td>${esc(parsePlanDisplay(v))}</td><td>${esc(location?.region||location?.source_anchor?.region||'尚未返回字段来源，请核对原件')}</td></tr>`;}));
  const states={MATCH:'一致',MISMATCH:'不一致',SUSPECT:'存在疑点',NOT_AVAILABLE:'依据不足',PASS:'通过',REVIEW:'待核对'};
  const items=(checks.items||[]).map(i=>`<tr><td>${esc(i.message||'请核对来源')}</td><td>${esc(states[i.status]||'待核对')}</td><td>${esc(parsePlanDisplay(i.declared))}</td><td>${esc(parsePlanDisplay(i.computed))}</td><td>${esc(parsePlanDifference(i.declared,i.computed))}</td><td>${esc((i.source_regions||[]).join('、')||'未提供')}</td></tr>`);
  return `<section class="pp-preview"><h3>3. 本地检查结果</h3><p>${p.records?.length??0} 条候选记录 · ${esc(status[checks.overall]||'请核对检查依据')}</p><p class="small muted">解析检查、人工核实和账务可用分别判定。以下预览尚未替换已有事实。</p>${(p.errors||[]).map(x=>`<p class="issue-banner">${esc(x)}</p>`).join('')}${(p.unresolved_rows||[]).map(r=>`<p class="issue-banner">${esc(r.sheet)} · 第 ${esc(r.row)} 行：${esc(r.reason)}</p>`).join('')}<h4>候选字段与原件定位</h4>${parsePlanTable(['原件行','字段名','提取值','来源'],fields)}<div class="pp-pagination"><button class="secondary" data-action="parse-plan-preview-page" data-page="${page-1}" ${page===0?'disabled':''}>上一组记录</button><span>第 ${page+1} / ${Math.max(1,Math.ceil((p.records?.length||0)/5))} 组，每组 5 条记录</span><button class="secondary" data-action="parse-plan-preview-page" data-page="${page+1}" ${(page+1)*5>=(p.records?.length||0)?'disabled':''}>下一组记录</button></div><h4>对账与检查依据</h4>${parsePlanTable(['检查说明','检查状态','原件声明','本地计算','差额（计算减声明）','来源位置'],items)}<details><summary>查看排除的表头、合计与参考行</summary>${(p.sheets||[]).map(s=>`<p>${esc(s.sheet)}：${(s.reference_rows||[]).map(r=>'第 '+r.row+' 行').join('、')||'无排除行'}</p>`).join('')}</details>${p.apply_ready!==true?'<p class="issue-banner">当前检查不满足应用条件，请根据原件调整方案后重新检查。</p>':''}</section>`;
}
function renderParsePlans(){
  const ui=parsePlanState(),e=ui.entry;
  let body=`<button class="text return-link" data-action="parse-plan-return">← 返回资料办理</button><section class="panel pad pp-workbench" id="parsePlanWorkbench" aria-busy="${ui.pending}"><h2 id="parsePlanTitle" tabindex="-1">核对${esc(kindLabels[ui.kind]||'资料')}表格结构</h2>`;
  if(ui.error)body+=`<p class="issue-banner" role="alert">${esc(ui.error)}</p>${e?'<button class="secondary" data-action="parse-plan-reload">重新读取原件与方案</button>':''}`;
  if(ui.feedback)body+=`<p class="pp-feedback" role="status">${esc(ui.feedback)}</p>`;
  if(!e)return body+`<p role="status">${ui.pending?'正在读取原件本地样本…':'原件样本未加载，输入草稿仍保留。'}</p>${!ui.pending?'<button class="secondary" data-action="parse-plan-reload">重新读取原件样本</button>':''}</section>`;
  body+=`<p class="pp-file">${esc(e.source.artifact.filename)} · 原件版本 ${esc(e.source.artifact.version)}</p>`;
  if(e.step==='applied')return body+'<div class="goal"><b>方案已应用</b>结构确认不代表逐条人工核实或账务放行，请返回资料办理继续核对。</div><button class="primary" data-action="parse-plan-return">查看资料与剩余问题</button></section>';
  if(!parsePlanCurrent())body+='<p class="issue-banner">原件或范围已变化，旧预览不能应用；请重新读取原件后核对。</p>';
  body+=renderParsePlanWindow(e)+renderParsePlanSample(e)+(ui.kind==='bank_statement'?'<p class="small muted">本期通用银行方案仅支持 Excel 收入、支出分列。单金额加方向列暂不支持，保留原件交由专用解析处理，无需重复补资料。</p>':'')+`<div class="pp-identify"><div><strong>需要结构识别建议？</strong><p class="small muted">仅点击后通过 Gateway 识别脱敏结构；模型只建议位置与字段，金额由本地原件读取。返回建议会替换当前结构草稿。</p></div><button class="secondary" data-action="parse-plan-identify" ${readonly()||ui.pending||!parsePlanCurrent()?'disabled':''}>识别表格结构</button></div>`+renderParsePlanFields(e,ui.kind)+renderParsePlanPreview(e);
  if(e.step==='impact'){
    const i=e.plan.data.impact;
    body+=`<section class="pp-impact"><h3>4. 应用前核对影响</h3><p>将以 ${esc(i.new_fact_count)} 条新事实替换 ${esc(i.previous_fact_count)} 条旧事实；旧版本保留。</p><p>涉及 ${esc(i.invalidated_confirmation_count)} 项已有确认、${esc(i.dependent_check_count??'待核对')} 项下游校验。</p><p>${esc(i.message||'关联确认和下游校验需重新评估，不代表已删除或全部失效。')}</p>${i.dependencies?.length?parsePlanTable(['关联对象','当前版本','应用影响'],i.dependencies.map(d=>`<tr><td>${esc(({SourceVerification:'资料核实',BusinessConfirmation:'业务确认',ConfirmationCard:'确认卡',ValidationResult:'业务校验',VoucherVersion:'凭证版本',BusinessGroup:'业务组',BusinessEvent:'业务事件',SourceArtifact:'原始资料'})[d.object_type]||'关联确认或校验')} · ${esc(d.object_id)}</td><td>${esc(d.version)}</td><td>${esc(d.effect||'需重新评估')}</td></tr>`)):''}<label class="pp-consent"><input type="checkbox" data-pp="confirmed" ${e.confirmed?'checked':''} ${ui.pending||readonly()?'disabled':''}>我已核对原件、字段对应和检查结果，理解已有确认可能失效及关联校验需重新评估</label></section>`;
  }
  body+=`<div class="pp-actions"><button class="${e.step==='edit'?'primary':'secondary'}" data-action="parse-plan-preview" ${ui.pending||readonly()||!parsePlanCurrent()?'disabled':''}>${e.preview?'重新检查方案':'检查方案并预览'}</button>${e.preview?.apply_ready===true&&e.step==='preview'?'<button class="primary" data-action="parse-plan-impact">查看应用影响</button>':''}${e.step==='impact'?`<button class="primary" data-action="parse-plan-apply" ${parsePlanCanApply()?'':'disabled'}>明确应用方案</button>`:''}<button class="text" data-action="parse-plan-return">暂不处理，保留输入</button></div></section>`;
  return ui.pending?body.replace(/<(input|select)\b/g,'<$1 disabled'):body;
}
function installParsePlanActions(){
  actions['parse-plan-window']=parsePlanLoadWindow;
  actions['parse-plan-preview-page']=b=>{const e=parsePlanState().entry;if(e?.preview){e.previewPage=Math.max(0,Math.min(Math.ceil(e.preview.records.length/5)-1,Number(b.dataset.page)||0));render();}};
  actions['parse-plan-open']=b=>openParsePlan(fileById(b.dataset.artifact));
  actions['parse-plan-reload']=async()=>{const ui=parsePlanState(),epoch=state.epoch,id=ui.id,kind=ui.kind;parsePlanSave();try{await loadWorkbench();if(epoch===state.epoch&&state.view==='parse-plans'&&ui.id===id)await openParsePlan(fileById(id),kind);}catch(error){if(epoch===state.epoch){ui.error=error.message;render();}}};
  actions['parse-plan-identify']=()=>parsePlanOperation('identify');actions['parse-plan-preview']=()=>parsePlanOperation('preview');actions['parse-plan-apply']=()=>parsePlanOperation('apply');
  actions['parse-plan-impact']=()=>{const ui=parsePlanState(),e=ui.entry;if(!ui.pending&&parsePlanCurrent()&&e?.preview?.apply_ready===true&&e.token){e.step='impact';e.confirmed=false;render();document.querySelector('.pp-impact')?.scrollIntoView({block:'nearest'});}};
  actions['parse-plan-return']=()=>{const ui=parsePlanState();parsePlanSave();ui.sequence++;ui.pending=false;const origin=ui.origin;state.view=['materials','artifacts'].includes(origin?.view)?origin.view:'materials';render();window.scrollTo(0,origin?.scrollY||0);};
  // The material module remains owned by its worker; route its existing action here.
  const previous=actions['material-parse'];actions['material-parse']=()=>{const t=currentMaterialTask(),a=t&&fileById(t.artifact_id);if(Array.isArray(state.overview?.parse_plans)&&parsePlanSupported(a)&&materialTaskIsCurrent(t))return openParsePlan(a);return previous?.();};
  document.addEventListener('change',event=>{
    const input=event.target;if(!input.closest('#parsePlanWorkbench')||!input.dataset.pp)return;
    const ui=parsePlanState(),e=ui.entry;if(!e||ui.pending)return;
    if(input.dataset.pp==='sheet'){e.sheet=Number(input.value);parsePlanSave();render();return;}
    if(input.dataset.pp==='window-start'){e.windowStart=input.value===''?null:Number(input.value);return;}
    if(input.dataset.pp==='page-size'){e.pageSize=Number(input.value);return;}
    if(readonly()||!parsePlanCurrent())return;
    if(input.dataset.pp==='confirmed'){e.confirmed=input.checked&&!!e.token;const b=document.querySelector('[data-action="parse-plan-apply"]');if(b)b.disabled=!parsePlanCanApply();return;}
    const s=e.proposal.sheets.find(s=>s.sheet_index===e.sheet);if(!s)return;
    if(input.dataset.pp==='header')s.header_row=input.value===''?null:Number(input.value);
    if(input.dataset.pp==='field'){if(input.value)s.fields[input.dataset.field]=input.value;else delete s.fields[input.dataset.field];}
    if(input.dataset.pp==='role'){s.role=input.value;if(s.role!=='DATA'){s.header_row=0;s.fields={};s.reference_rows=[];}}
    if(input.dataset.pp==='reference'){s.reference_rows=(s.reference_rows||[]).filter(r=>r.row!==Number(input.dataset.row));if(input.value)s.reference_rows.push({row:Number(input.dataset.row),role:input.value});}
    e.proposal.outcome='PLAN';parsePlanInvalidate();ui.feedback='结构已调整，请重新检查方案；旧预览与确认已撤销。';render();
  });
}

/* The autonomous projection is the sole source of current monthly state. */
let autonomousTimer=null;
let autonomousFinding=null;
const autonomousDrafts=new Map();
const autonomousChoices=new Map();
const autonomousMatchingDrafts=new Map();
// Settings drafts stay in memory and never cross user, enterprise, ledger or period.
const autonomousSettingsDrafts=new Map();
const settingsDraftKey=()=>JSON.stringify([state.user?.user_id,scope()]);
const currentSettingsDraft=()=>state.view==='settings'?autonomousSettingsDrafts.get(settingsDraftKey()):null;
function rememberSettingsInput(target){
 if(state.view!=='settings'||readonly()||!state.overview?.autonomous_workflow)return;
 const fields={bookkeepingMode:'mode',bookkeepingCostRatio:'ratio',bookkeepingSourceNote:'note'};
 if(target.id!=='autonomousExecutor'&&!fields[target.id])return;
 const w=state.overview.autonomous_workflow;
 if(['QUEUED','ANALYZING','REVIEWING'].includes(w.status))return;
 const draft=currentSettingsDraft()||{};
 if(target.id==='autonomousExecutor')draft.executor={backend:target.value};
 else {
  const p=w.bookkeeping_profile;
  draft.bookkeeping??={mode:p.id,ratio:p.cost_ratio==null?'':String(Number(p.cost_ratio)*100),note:p.source_note||'',expectedVersion:p.selection_version};
  draft.bookkeeping[fields[target.id]]=target.value;
 }
 autonomousSettingsDrafts.set(settingsDraftKey(),draft);
 for(const node of document.querySelectorAll('[data-settings-dirty]'))node.classList.remove('hidden');
}
const matchingDraftKey=id=>JSON.stringify([scope(),state.overview?.autonomous_workflow?.job?.object_id,id]);
const matchingLabels={MISSING:'没找到票据',CANDIDATE:'票据归属待确认',AMOUNT_DIFFERENCE:'已确认票据，金额有差异'};
let autonomousSourcesScope=null;
let autonomousSourcesOpen=false;
const autonomousDraftKey=()=>JSON.stringify([scope(),state.overview?.autonomous_workflow?.job?.object_id,autonomousFinding]);
const autonomousStatus=s=>({READY_FOR_REVIEW:'依据齐备，可复核',NEEDS_EVIDENCE:'待补关键依据',SYSTEM_BLOCKED:'系统继续处理'})[s]||'状态待核实';
function autonomousEvidence(refs){return (refs||[]).map(r=>{const a=fileById(r.source_id);return `<li>${a?objectButton(a.object_id,a.data.filename):esc(r.source_id)} · ${esc(r.sheet||'')}${r.page?'第 '+esc(r.page)+' 页 ':''}${r.row?'第 '+esc(r.row)+' 行':''}${esc(r.location||'')}</li>`;}).join('');}
function findingEmphasis(text){
 // Escape every fragment, including matched tokens; model text is never HTML.
 const pattern=/20\d{2}[-/]\d{1,2}[-/]\d{1,2}|记-?\d+(?:[—–-]\d+)?|(?<![\d.])(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2}(?![\d.])|\d+(?:\.\d+)?%|\d{1,2}(?:[—–-]\d{1,2})?月(?:\d{1,2}日)?/g;
 let html='',offset=0;
 for(const match of String(text).matchAll(pattern)){
  html+=esc(text.slice(offset,match.index))+`<strong class="finding-value">${esc(match[0])}</strong>`;
  offset=match.index+match[0].length;
 }
 return html+esc(text.slice(offset));
}
function renderFindingDetail(detail){
 const text=String(detail||'');
 // Split only at written boundaries; preserve order, punctuation and all caveats.
 const parts=text.match(/[^。；;\n]+[。；;]?|[。；;]|\n+/g)||[];
 const groups=[];
 for(const part of parts){
  const value=part.trim();if(!value)continue;
  const kind=/^(?:暂不|暂未|不能|不得|不应|尚不能)/.test(value)?'caution':/(?:^|[，,])(?:请|补|需(?!求)|须|还须)/.test(value)?'action':'context';
  if(groups.at(-1)?.kind===kind)groups.at(-1).items.push(value);
  else groups.push({kind,items:[value]});
 }
 const titles={context:'核查说明',action:'需要你补充',caution:'当前处理边界'};
 return `<div class="finding-detail">${groups.map(g=>`<section class="finding-block finding-${g.kind}" aria-label="${titles[g.kind]}"><h3>${titles[g.kind]}</h3><ul>${g.items.map(item=>`<li>${findingEmphasis(item)}</li>`).join('')}</ul></section>`).join('')}</div>`;
}
function renderFindingRequest(f){
 const r=f.request;
 const impact=f.blocks_confirmation===false?'可后续处理 · 不影响已有依据的凭证复核':'需要补充信息后，才能确认这笔账';
 const banner=`<p>${badge(impact,f.blocks_confirmation===false?'blue':'yellow')}${r?.scope==='ONBOARDING'?' <span class="small muted">接账基础资料 · 核实后供后续期间复用</span>':''}</p>`;
 if(!r)return banner+renderFindingDetail(f.detail);
 return banner+`<div class="finding-detail">${[['这笔账已处理到哪一步',r.can_continue,'context'],['还需要你说明什么',r.question,'action'],['会影响什么',r.why_needed,'context'],['补充这些就可以',r.evidence_request,'action']].map(([title,text,kind])=>`<section class="finding-block finding-${kind}"><h3>${title}</h3><p>${findingEmphasis(String(text||''))}</p></section>`).join('')}</div><details><summary>查看详细核对记录</summary>${renderFindingDetail(f.detail)}</details>`;
}
function renderAutonomousDecision(f){
 const d=f.decision;if(!d)return '';
 const choice=autonomousChoices.get(autonomousDraftKey())||{};
 const r=f.request;
 return `<section class="review-decision">${r?.can_continue?`<p>${findingEmphasis(r.can_continue)}</p>`:''}<h3>${esc(d.question)}</h3>${r?.why_needed?`<p>会影响什么：${findingEmphasis(r.why_needed)}</p>`:''}<p class="small muted">按实际情况选择，系统会据此重新处理，再交给你复核。</p>${d.options.length?d.options.map(o=>`<label class="review-option ${choice.id===o.id?'selected':''}"><span class="review-option-heading"><input type="radio" name="reviewOption" value="${esc(o.id)}" ${choice.id===o.id?'checked':''} ${readonly()?'disabled':''}><strong>${esc(o.label)}</strong>${o.recommended?badge('建议方案','blue'):''}</span><p>这样处理：${findingEmphasis(o.effect)}</p><p class="small">适用情况：${o.assumptions.map(esc).join('；')}</p><details><summary>查看依据和后续处理</summary><p>${esc(o.basis)}</p><p>选择后：${esc(o.next_step)}</p></details></label>`).join(''):''}${d.unavailable_reason?`<p class="finding-block finding-caution">${esc(d.unavailable_reason)}</p>`:''}${d.options.length?`<label class="review-ack"><input id="reviewAcknowledged" type="checkbox" ${choice.acknowledged?'checked':''} ${readonly()?'disabled':''}>我确认所选情况和适用条件符合这笔业务</label><button class="primary" data-action="autonomous-decision" ${readonly()||!choice.id||!choice.acknowledged?'disabled':''}>按所选情况继续处理</button>`:''}</section>`;
}
function matchingItems(){return state.overview?.autonomous_workflow?.invoice_matching?.items||[];}
function matchingGroupItems(){const active=matchingItems().find(i=>i.finding_id===autonomousFinding);return matchingItems().filter(i=>i.party===active?.party).sort((a,b)=>Number(b.finding_id===autonomousFinding)-Number(a.finding_id===autonomousFinding));}
function matchingDraft(id){return autonomousMatchingDrafts.get(matchingDraftKey(id))||{invoice_ids:[],note:''};}
function invoiceChoiceTable(item,invoices,selectable=true){
 const draft=matchingDraft(item.finding_id);
 return table([selectable?'选择':'归属','开票日期 / 票号','价税合计','已知情况 / 原件'],invoices.map(i=>`<tr><td>${selectable?`<input type="checkbox" data-matching-invoice="${esc(i.id)}" data-matching-finding="${esc(item.finding_id)}" aria-label="选择发票 ${esc(i.number||i.id)}，${esc(i.gross)}元" ${draft.invoice_ids.includes(i.id)?'checked':''} ${readonly()?'disabled':''}>`:'已确认'}</td><td>${esc(i.date||'日期未识别')}<br><span class="mono">${esc(i.number||'票号未识别')}</span></td><td class="amount">${amount(i.gross)}</td><td>${item.confirmed_invoice_ids.includes(i.id)?'归属已确认':item.candidate_invoice_ids.includes(i.id)?'可能相关，归属待确认':'尚未关联本笔'}${i.used_by.some(v=>!item.affected_vouchers.includes(v))?`<br><span class="matching-warning">已关联 ${i.used_by.filter(v=>!item.affected_vouchers.includes(v)).map(esc).join('、')}，再选时需核查分次付款或重复</span>`:''}<ul>${autonomousEvidence([i.source])}</ul></td></tr>`));
}
function renderInvoiceMatching(w){
 const data=w.invoice_matching,items=matchingGroupItems(),parties=[...new Set(data.items.map(i=>i.party))];
 const counts=Object.keys(matchingLabels).map(k=>`${matchingLabels[k]} ${data.items.filter(i=>i.state===k).length} 笔`).join(' · ');
 return `<section class="matching-workspace" aria-label="票款集中核对"><p>先选出属于这笔款项的票据，系统再核对金额和重复。暂时配不上的可以保留，其他凭证继续复核。</p><p class="small muted">${counts}</p><label for="matchingParty">按收付款对象集中核对</label><select id="matchingParty">${parties.map(p=>`<option value="${esc(data.items.find(i=>i.party===p).finding_id)}" ${p===items[0]?.party?'selected':''}>${esc(p)} · ${data.items.filter(i=>i.party===p).length} 笔</option>`).join('')}</select>
 ${items.map(item=>{
  const known=new Set([...item.candidate_invoice_ids,...item.confirmed_invoice_ids]),draft=matchingDraft(item.finding_id);
  const candidates=data.invoices.filter(i=>known.has(i.id)),others=data.invoices.filter(i=>!known.has(i.id));
  return `<section class="matching-card" aria-label="${esc(item.party)} ${esc(item.payment_total)}元票款核对"><div class="row"><h3>${esc(item.party)} · ${amount(item.payment_total)} 元</h3>${badge(matchingLabels[item.state],'yellow')}</div>
   <p>${item.payments.map(p=>`${esc(p.date)} ${Number(p.expense)>0?'付款':'收款'} <strong>${amount(Number(p.expense)||Number(p.income))}</strong> 元 · ${esc(p.memo||'摘要未识别')}`).join('<br>')}</p>
   ${item.state==='MISSING'?'<p>暂时没找到对应票据。可从已有发票中选择，或补充票据。</p>':item.state==='CANDIDATE'?`<p>找到可能相关的票据，合计 <strong>${amount(item.candidate_total)}</strong> 元。先确认哪些票属于这笔款项。</p>${Number(item.confirmed_total)?`<p>另有 ${amount(item.confirmed_total)} 元票据归属已确认。</p>`:''}`:`<p>归属已确认的票据合计 <strong>${amount(item.confirmed_total)}</strong> 元，${Number(item.difference)>0?'款项比票据多':'票据比款项多'} <strong>${amount(Math.abs(Number(item.difference)))}</strong> 元。请说明差额是什么。</p>`}
   ${item.confirmed_invoice_ids.length?invoiceChoiceTable(item,candidates.filter(i=>item.confirmed_invoice_ids.includes(i.id)),false):''}
   ${item.candidate_invoice_ids.length?invoiceChoiceTable(item,candidates.filter(i=>item.candidate_invoice_ids.includes(i.id))):''}
   ${others.length?`<details><summary>从已提供的其他发票中选择 · ${others.length} 张</summary>${invoiceChoiceTable(item,others)}</details>`:''}
   <p class="small" data-matching-summary="${esc(item.finding_id)}">${matchingSelectionSummary(item)}</p>
   <label for="matching-note-${esc(item.finding_id)}">补充说明（选票时可不填）</label><textarea id="matching-note-${esc(item.finding_id)}" data-matching-note="${esc(item.finding_id)}" rows="2" maxlength="10000" placeholder="例如：这些票都不属于这笔；还有票未提供；或说明已确定的差额。" ${readonly()?'disabled':''}>${esc(draft.note)}</textarea>
   <details><summary>查看已知情况与依据</summary><p>${esc(item.can_continue)}</p><p>${esc(item.reason)}</p><p>影响凭证：${item.affected_vouchers.map(esc).join('、')}</p><ul>${autonomousEvidence(item.evidence)}</ul></details></section>`;
 }).join('')}
 <p class="small muted">提交选票只确认票据归属。系统会继续核查差额、重复和记账依据，再生成待复核结果。</p><div class="actions"><button class="primary" data-action="autonomous-match-submit" ${readonly()||!matchingSubmission().length?'disabled':''}>${matchingSubmitLabel()}</button><button class="secondary" data-action="autonomous-upload" ${readonly()?'disabled':''}>补充票据</button></div></section>`;
}
function matchingSelectionSummary(item){
 const ids=matchingDraft(item.finding_id).invoice_ids,invoices=state.overview.autonomous_workflow.invoice_matching.invoices;
 const cents=invoices.filter(i=>ids.includes(i.id)).reduce((n,i)=>n+Math.round(Number(i.gross)*100),0);
 if(!ids.length&&item.state==='AMOUNT_DIFFERENCE')return '票据归属已确认，请填写差额说明；无需重复选票。如需更正归属，可在说明中指出。';
 return ids.length?`已选 ${ids.length} 张，合计 ${amount(cents/100)} 元；提交后重新核对。`:'尚未选择票据，也可以只补充说明；不填写的项目会保留待处理。';
}
function matchingSubmission(){return matchingGroupItems().map(i=>({finding_id:i.finding_id,...matchingDraft(i.finding_id)})).filter(d=>d.invoice_ids.length||d.note.trim());}
function matchingSubmitLabel(){const n=matchingSubmission().length;return n?`确认选票与说明，重新核对 ${n} 笔`:'选择票据或填写说明后提交';}
async function submitInvoiceMatching(){
 const items=matchingSubmission();if(!items.length)throw new Error('请选择对应票据或填写具体说明。');
 const keys=items.map(i=>matchingDraftKey(i.finding_id));
 await request('/api/v1/autonomous/invoice-matching',{scope:scope(),run_id:state.overview.autonomous_workflow.job.object_id,items,acknowledged:true});
 keys.forEach(k=>autonomousMatchingDrafts.delete(k));
 await loadWorkbench();notify(`已提交 ${items.length} 笔票款说明，系统正在重新核对；未填写的项目继续保留。`);
}
function refreshMatchingControls(){
 matchingGroupItems().forEach(item=>{const el=document.querySelector(`[data-matching-summary="${CSS.escape(item.finding_id)}"]`);if(el)el.textContent=matchingSelectionSummary(item);});
 const b=document.querySelector('[data-action="autonomous-match-submit"]');if(b){b.disabled=readonly()||!matchingSubmission().length;b.textContent=matchingSubmitLabel();}
}
function matchingSidebar(w,pending){
 const items=w.invoice_matching?.items||[],ids=new Set(items.map(i=>i.finding_id)),other=pending.filter(f=>!ids.has(f.id));
 return `${items.length?`<h3>票款待匹配 · ${items.length} 笔</h3>${[...new Set(items.map(i=>i.party))].map(p=>{const group=items.filter(i=>i.party===p);return `<button class="autonomous-issue ${group.some(i=>i.finding_id===autonomousFinding)?'selected':''}" data-autonomous-finding="${esc(group[0].finding_id)}">${esc(p)} · ${group.length} 笔 <span class="small">集中核对票据</span></button>`;}).join('')}<h3>其他记账问题 · ${other.length} 项</h3>`:''}${other.map(x=>`<button class="autonomous-issue ${x.id===autonomousFinding?'selected':''}" data-autonomous-finding="${esc(x.id)}">${esc(x.title)}</button>`).join('')||(!items.length?'<p class="small muted">暂无需要补充的问题</p>':'')}`;
}
function renderDecisionResponses(w){
 const labels={APPLIED:'已应用',PARTIAL:'部分应用',UNRESOLVED:'仍未解决'};
 return (w.decision_responses||[]).length?`<details class="review-responses"><summary>上次回应的处理结果 · ${w.decision_responses.length} 项</summary>${w.decision_responses.map(r=>`<section><p>${badge(labels[r.outcome]||'待核实',r.outcome==='APPLIED'?'green':'yellow')} ${(w.answers||[]).find(a=>a.answer_id===r.answer_id)?.option?esc(w.answers.find(a=>a.answer_id===r.answer_id).option.label):'业务说明与资料范围'}</p><p>${esc(r.explanation)}</p><p class="small muted">${r.affected_vouchers.map(esc).join('、')}</p></section>`).join('')}</details>`:'';
}
function renderTravelPolicy(w){
 const p=w.travel_policy;if(!p)return '';
 const applied=w.applied_travel_policy;
 const previous=document.querySelector?.('[data-travel-policy]');
 const expanded=!!previous&&previous.dataset.travelPolicy===p.id&&previous.open;
 const categories=p.rules?`<p>本企业默认分类：餐费 → ${esc(p.rules.meal_default_account_name)}；礼品 → ${esc(p.rules.gift_default_account_name)}。已有明确用途时按实际用途调整，税务处理另行核验。</p>`:'';
 const status=p.enabled?(applied?.enabled&&applied.version===p.version?'本轮已采用':'已启用，待本轮分析采用'):'已停用';
 return `<details class="review-responses" data-travel-policy="${esc(p.id)}" ${expanded?'open':''} aria-label="企业差旅规则"><summary>企业差旅规则 · 第 ${esc(p.version)} 版 · ${status}</summary><p>${esc(p.summary)}</p>${categories}<p class="small muted">补贴及借款核销须逐笔人工确认；未设置补贴自动金额限额。</p><p>确认人：${esc(p.confirmed_by)} · ${esc(p.confirmed_at)}</p><p>确认来源：${esc(p.source_note)}</p></details>`;
}
function travelApplicationEvidence(number){
 const applications=(state.overview.autonomous_workflow?.travel_policy_applications||[]).filter(p=>p.voucher===number);
 const labels={TRAVEL:'差旅',MEAL:'餐费',GIFT:'礼品',ALLOWANCE:'差旅补贴',LOAN_OFFSET:'借款核销',SETTLEMENT:'往来结算'};
 const manual={ALLOWANCE:'补贴确认',DUPLICATE:'重复报销确认',LOAN_OFFSET:'借款核销确认',EMPLOYEE_SETTLEMENT:'员工结算确认',PERIOD:'期间确认',AMOUNT_GAP:'票款差额',CLASSIFICATION:'用途分类',INVOICE_MISSING:'发票缺失'};
 return applications.length?`<section class="finding-block finding-context"><h3>本笔采用的企业规则</h3>${applications.map(p=>`<p>差旅规则第 ${esc(p.policy_version)} 版 · ${labels[p.kind]||'相关处理'}</p><p>${esc(p.reason)}</p>${(p.manual_reasons||[]).length?`<p>仍待人工：${p.manual_reasons.map(c=>manual[c]||'待确认').join('、')}</p>`:''}`).join('')}</section>`:'';
}
function autonomousEntryTable(entries){return `<div class="autonomous-entry-table">${table(['科目编码','科目 / 摘要','借方','贷方'],entries.map(e=>`<tr><td class="mono">${esc(e.code)}</td><td>${esc(e.name)}<br><span class="small muted">${esc(e.memo||'')}</span></td><td class="amount">${amount(e.debit)}</td><td class="amount">${amount(e.credit)}</td></tr>`))}</div>`;}
function autonomousFindingLinks(findings){
 return findings.filter(f=>f.needs_user).map(f=>`<button class="text" data-autonomous-finding="${esc(f.id)}">${esc(f.title)}</button>`).join('');
}
function renderAutonomousExecutor(w,busy){
 const options=w.executors||[],selected=currentSettingsDraft()?.executor?.backend||w.executor||'codex';
 const current=w.job?.data.runtime;
 return `<section class="autonomous-executor settings-section panel" aria-labelledby="executorTitle"><header class="settings-section-heading"><h2 id="executorTitle">处理 Agent</h2><p class="small muted">选择负责分析和独立审查的 Agent，应用于当前企业本期。</p></header><div class="settings-form-row"><label class="settings-field" for="autonomousExecutor">分析工具与模型<select id="autonomousExecutor" ${busy||readonly()?'disabled':''}>${options.map(o=>`<option value="${esc(o.id)}" ${o.id===selected?'selected':''} ${!o.available?'disabled':''}>${esc(o.label)}${o.model?' · '+esc(o.model):''}${!o.available?' · 未配置':''}</option>`).join('')}</select></label><button class="secondary" data-action="autonomous-executor" ${busy||readonly()?'disabled':''}>${w.source_count?'切换并重新分析':'保存选择'}</button></div><p class="small muted settings-current">${current?`本轮：${esc(current.label)} · ${esc(current.model)}`:'选择后用于自主分析及独立审查'}</p><p class="small muted">${busy?'处理中请先暂停，再切换 Agent。':'已有资料时切换会新建一轮处理，原结果保留在历史中。'}${options.filter(o=>!o.available).map(o=>' '+esc(o.message)+'。').join('')}</p></section>`;
}
function renderBookkeepingProfile(w,busy){
 const p=w.bookkeeping_profile;if(!p)return '';
 const locked=busy||readonly(), applied=w.applied_bookkeeping_profile;
 const draft=currentSettingsDraft(),values=draft?.bookkeeping;
 const options=w.bookkeeping_profiles||[], mode=values?.mode||p.id,ratio=values?.ratio??(p.cost_ratio==null?'':String(Number(p.cost_ratio)*100));
 const summary=options.find(o=>o.id===mode)?.summary||p.summary;
 return `<section class="autonomous-bookkeeping settings-section panel" aria-labelledby="bookkeepingTitle"><header class="settings-section-heading"><h2 id="bookkeepingTitle">记账方式</h2><p class="small muted">应用于当前企业的本账套各月；其他企业保持各自的设置。</p></header><div class="settings-form-row"><label class="settings-field" for="bookkeepingMode">处理方式<select id="bookkeepingMode" ${locked?'disabled':''}>${options.map(o=>`<option value="${esc(o.id)}" ${o.id===mode?'selected':''}>${esc(o.label)}${o.id==='AGENCY_SIMPLE'?'（默认）':''}</option>`).join('')}</select></label><button class="secondary" data-action="bookkeeping-save" ${locked?'disabled':''}>${w.source_count?'保存并重新分析':'保存选择'}</button></div><p id="bookkeepingSummary">${esc(summary)}</p><p class="small muted settings-current">${applied?`本轮采用：${esc(applied.label)}${applied.version?' · 规则第 '+esc(applied.version)+' 版':' · 历史运行'}`:`新任务将采用：${esc(p.label)}。`} ${busy?'处理中请先暂停再切换。':'选择用于本账套各月；切换后重新审查，旧结果保留。'}</p><details class="settings-cost" ${draft?.costExpanded?'open':''}><summary>本企业成本比例${ratio?' · '+esc(ratio)+'%':' · 未设置'}</summary><p class="small muted">仅简易代账使用。企业已确认按销售收入比例结转成本时填写；留空则依据本企业实际成本资料处理。</p><div class="bookkeeping-policy-fields"><label for="bookkeepingCostRatio">当月不含税销售收入 × 比例（%）<input id="bookkeepingCostRatio" type="number" min="0.01" max="100" step="0.01" value="${esc(ratio)}" ${locked||mode==='ORIGINAL'?'disabled':''}></label><label for="bookkeepingSourceNote">比例确认来源<input id="bookkeepingSourceNote" maxlength="1000" value="${esc(values?.note??p.source_note??'')}" placeholder="例如：财务公司已确认，2026年10月1日" ${locked||mode==='ORIGINAL'?'disabled':''}></label></div><p class="small muted">暂估及特殊调整仍需单独提供；保存比例不会补造历史费用。</p></details></section>`;
}
function renderAutonomousVoucherPage(){
 const w=state.overview.autonomous_workflow,previews=w.entry_previews||[],actual=new Map(state.overview.vouchers.map(v=>[v.data.voucher_number,v]));
 return `<button class="text return-link" data-action="return-current">← 返回本期办理</button><section class="panel pad autonomous-voucher-table"><h2>本期分录与凭证复核</h2><p>${previews.length} 张分录可查看 · ${Math.max(0,w.ready_count-w.confirmed_count)} 张可确认 · ${w.pending_count} 张待补关键依据 · ${w.confirmed_count} 张已复核</p><p class="small muted">${w.mode==='JOURNAL_REVIEW'?'当前为原账复核：分录来自已提供的本期账，不代表独立做账结果。':'当前按原始资料提出候选分录。'}待补证分录可查看与补充依据，通过查证后才能确认；本地复核不等于正式入账。</p>${previews.length?table(['凭证 / 日期','处理状态','借方 / 贷方','相关事项','操作'],previews.map(p=>{
 const v=actual.get(p.voucher),status=v?.status==='LOCALLY_CONFIRMED'?'已复核':autonomousStatus(p.assessment.status),ready=v&&p.assessment.status==='READY_FOR_REVIEW';
 const debit=p.entries.reduce((n,e)=>n+Math.round(Number(e.debit)*100),0)/100,credit=p.entries.reduce((n,e)=>n+Math.round(Number(e.credit)*100),0)/100;
 return `<tr><td class="mono">${esc(p.voucher)}<br><span class="small muted">${esc(p.entries[0]?.date||'')}</span></td><td>${badge(status,v?.status==='LOCALLY_CONFIRMED'?'green':ready?'blue':'yellow')}</td><td class="amount">${amount(debit)}<br>${amount(credit)}</td><td>${autonomousFindingLinks(p.findings)||'<span class="muted">无待补充事项</span>'}</td><td><button class="text" data-action="autonomous-preview" data-number="${esc(p.voucher)}">查看分录与依据</button>${ready&&v.status==='DRAFT'?'<br>'+commandButton('validate_draft',v,'复核凭证'):''}</td></tr>`;
 })):'<p class="empty">尚未形成可展示的分录；系统处理完成后自动更新。</p>'}</section>`;
}
function showAutonomousPreview(number){
 const p=state.overview.autonomous_workflow.entry_previews.find(p=>p.voucher===number);
 if(!p)throw new Error('资料版本已变化，请刷新后查看。');
 const pending=p.assessment.status!=='READY_FOR_REVIEW';
 openDialog(`${p.voucher} · 分录与依据`,`<p>${badge(autonomousStatus(p.assessment.status),pending?'yellow':'blue')}</p><p>${esc(p.assessment.reason)}</p>${travelApplicationEvidence(p.voucher)}${pending?'<p class="finding-block finding-caution">以下为待核查分录，尚不能确认通过。补充依据后系统会重新查证相关凭证和结转。</p>':''}${p.revision?`<section class="finding-block finding-context"><h3>本轮修订方案</h3><p>${esc(p.revision.reason)}</p></section>`:''}${autonomousEntryTable(p.entries)}${p.revision?`<details><summary>查看原账分录（未改写）</summary>${autonomousEntryTable(p.original_entries)}</details>`:''}<h3>关联待补充事项</h3>${autonomousFindingLinks(p.findings)||'<p>无待补充事项，可在凭证列表发起复核。</p>'}<h3>核查依据</h3><ul>${autonomousEvidence(p.assessment.evidence)}</ul>`);
}
// 工具条原来是 8 个动作平铺。「重新审查补证范围」「按已有历史资料重新核查」
// 「继续处理」光看名字分不出差别，真正该点的那一个被淹没在里面。
// 规则和问题卡的 decisionOptionsNav 一样，不另发明一种：按状态选出一个主操作，
// 其余收进「其他操作 · N 项」；没有主操作时（系统正在跑）不折叠 —— 否则一个
// 可点的都不剩。
//
// 每个按钮的 readonly 行为原样保留：这是纯结构改动。注意「启动自动处理」本来
// 就没有 readonly 门，只读账号看到的是可点的按钮（服务端会挡）—— 这是原有的
// 不一致，没有在这里顺手改，改权限该是独立一件事。
function autonomousActions(w,j,busy,pendingCount){
 const ro=readonly()?'disabled':'';
 // 顺序就是优先级：越靠前越是"现在最该做的那一件"。
 const all=[
  {on:!j&&w.source_count,          act:'autonomous-start',              label:'启动自动处理',               lead:true, dis:''},
  {on:w.can_retry&&!busy,          act:'autonomous-retry',              label:'继续处理',                   lead:true, dis:ro},
  {on:w.can_reassess&&!busy,       act:'autonomous-retry',              label:'重新审查补证范围',           lead:true, dis:ro},
  {on:w.accepted&&pendingCount&&!w.materials_complete,
                                   act:'autonomous-materials-complete', label:'现有资料已全部提供，分析可行方案', lead:true, dis:ro},
  {on:w.accepted&&pendingCount&&!w.can_reassess&&!w.can_retry,
                                   act:'autonomous-history-recheck',    label:'按已有历史资料重新核查',     lead:false, dis:ro},
  {on:busy,                        act:'autonomous-cancel',             label:'暂停自动处理',               lead:false, dis:ro},
  {on:true,                        act:'autonomous-upload',             label:'补充原始资料',               lead:false, dis:ro},
  {on:true,                        act:'refresh',                       label:'刷新状态',                   lead:false, dis:''},
 ].filter(x=>x.on);
 const lead=all.find(x=>x.lead),extra=lead?all.filter(x=>x!==lead):all;
 const btn=(x,cls)=>`<button class="${cls}" data-action="${x.act}" ${x.dis}>${esc(x.label)}</button>`;
 return (lead?btn(lead,'primary'):'')
  +(lead&&extra.length
    ?`<details class="decision-more-options"><summary>其他操作 · ${extra.length} 项</summary><nav class="decision-options" aria-label="其他操作">${extra.map(x=>btn(x,'secondary')).join('')}</nav></details>`
    :extra.map(x=>btn(x,'secondary')).join(''));
}
function renderAutonomous(){
 const w=state.overview.autonomous_workflow,j=w.job,p=state.overview.progress;
 const sourcesScope=JSON.stringify(scope());
 if(autonomousSourcesScope!==sourcesScope){autonomousSourcesScope=sourcesScope;autonomousSourcesOpen=false;}
 const pending=w.findings.filter(f=>f.needs_user);
 const followupCount=pending.filter(f=>f.blocks_confirmation===false).length;
 if(!pending.some(f=>f.id===autonomousFinding))autonomousFinding=pending[0]?.id||null;
 const f=pending.find(f=>f.id===autonomousFinding);
 const busy=['QUEUED','ANALYZING','REVIEWING'].includes(w.status);
 // 和期间工作台共用同一份六步投影，序号只给主线（见 app/main_flow.py）。
 const stages=p.stages.filter(s=>s.main_line!==false).map((s,i)=>`<div class="stage ${s.status==='COMPLETED'?'done':''} ${s.id===p.current_stage?'current':''}"><strong>${i+1} ${esc(s.name)}</strong><span>${esc(s.summary)}</span></div>`).join('')
   +p.stages.filter(s=>s.main_line===false).map(s=>`<div class="stage stage-aside ${s.status==='COMPLETED'?'done':''}"><strong>· ${esc(s.name)} · 主线之外</strong><span>${esc(s.summary)}</span></div>`).join('');
 const buttons=autonomousActions(w,j,busy,pending.length);
 return `<section class="panel pad workbench-overview"><div class="row"><div><h2>${esc(w.label)}</h2><p>${esc(j?.data.message||'上传原件后开始处理')}</p></div><span class="small muted">第 ${j?.data.revision||1} 轮处理</span></div><div class="autonomous-stages">${stages}</div><div class="actions workbench-toolbar">${buttons}</div>${w.materials_complete?'<p class="small review-boundary">已记录：现有资料已全部提供。系统按此范围分析可行方案，你仍可补充说明或上传新材料。</p>':''}</section>
 ${w.previous_result?`<section class="panel pad" aria-label="已保留的上一轮成果"><h2>上一轮成果已保留</h2><p>第 ${esc(w.previous_result.revision)} 轮共 ${esc(w.previous_result.candidate_count)} 张凭证：${esc(w.previous_result.ready_count)} 张依据齐备，${esc(w.previous_result.pending_count)} 张待补关键依据。本轮完成后更新复核结果。</p><button class="text" data-action="autonomous-process" data-run-id="${esc(w.previous_result.run_id)}">查看上一轮处理记录</button></section>`:''}
 <div class="work-grid"><section class="panel pad"><h2 class="autonomous-status-title">${busy?'<span class="autonomous-spinner" aria-hidden="true"></span>':''}${f?.invoice_matching?'票款待匹配':f?esc(f.title):busy?'系统正在自行查证':w.accepted?'当前自动处理结果':'处理状态'}</h2>${busy?'<p class="autonomous-live-note" role="status">处理中 · 状态自动更新，无需手动刷新</p>':''}${f?f.invoice_matching?renderInvoiceMatching(w):`${f.decision?renderAutonomousDecision(f)+`<details><summary>核查说明与补充依据</summary>${renderFindingRequest(f)}</details>`:renderFindingRequest(f)}<div class="finding-impact"><span>影响凭证</span>${(f.affected_vouchers||[]).map(id=>`<span class="finding-voucher">${esc(id)}</span>`).join('')||'<span>尚未形成候选</span>'}</div><label for="autonomousAnswer">补充业务说明</label><textarea id="autonomousAnswer" rows="4" placeholder="填写实际情况或提供依据；系统会继续核查，不会直接修改账务。">${esc(autonomousDrafts.get(autonomousDraftKey())||'')}</textarea><div class="actions"><button class="primary" data-action="autonomous-answer" ${readonly()?'disabled':''}>提交说明并继续处理</button><button class="secondary" data-action="autonomous-upload" ${readonly()?'disabled':''}>上传证明资料</button></div><details><summary>查看调查依据</summary><ul>${autonomousEvidence(f.evidence)}</ul></details>`:busy?'<p>正在识别资料、交叉核算并查阅历史关联。完成独立审查后，系统会交接有依据的候选和确实需要补充的信息。</p>':`<p>${esc(w.accepted?'已查证的候选可以进入复核；复核通过仍不等于正式入账。':j?.data.message||'等待资料')}</p>`}
 ${renderTravelPolicy(w)}${renderDecisionResponses(w)}
 ${j?'<details><summary>处理计划与过程</summary>':''}<ol>${(j?.data.events||[]).map(e=>`<li>${esc(e.at)} · ${esc(e.message)}</li>`).join('')}</ol>${j?'<button class="text" data-action="autonomous-process">查看完整处理记录</button></details>':''}
 ${w.accepted?`<details><summary>处理报告与审查范围</summary><div class="autonomous-prose">${esc(w.report)}</div><h3>独立审查</h3><ul>${(w.review.coverage||[]).map(c=>`<li><strong>${esc(c.area)}</strong>：${esc(c.conclusion)}</li>`).join('')}</ul><p>${esc((w.review.limitations||[]).join('；'))}</p></details>`:''}</section>
 <aside class="panel pad workbench-results"><h2>本期结果</h2><p><strong>${Math.max(0,w.ready_count-w.confirmed_count)}</strong> 张待复核 · <strong>${w.confirmed_count}</strong> 张已复核</p><button class="primary" data-action="vouchers" ${w.entry_preview_count?'':'disabled'}>查看全部 ${w.entry_preview_count||0} 张分录与复核事项</button><p>${w.pending_count} 张待补证 · ${w.blocked_count} 张系统受阻</p><h3>待处理事项 ${pending.length} 项</h3>${pending.length?`<p class="small muted">${pending.length-followupCount} 项需补充信息；${followupCount} 项可后续处理。</p>`:''}${matchingSidebar(w,pending)}<details><summary>记账说明 ${w.findings.length-pending.length} 项</summary>${w.findings.filter(x=>!x.needs_user).map(x=>`<p><strong>${esc(x.title)}</strong><br>${esc(x.detail)}</p>`).join('')}</details></aside></div>
 <section class="panel pad"><details class="autonomous-sources" ${autonomousSourcesOpen?'open':''}><summary><strong>原始资料 · ${w.source_count} 份</strong><span class="autonomous-expand-label">展开清单</span><span class="autonomous-collapse-label">收起清单</span></summary>${table(['原件','用途与状态','操作'],activeArtifacts().map(a=>`<tr><td class="filename">${esc(a.data.filename)}</td><td>${w.accepted?'已纳入本次分析':'已保存，等待处理'}</td><td>${objectButton(a.object_id,'查看原件')}</td></tr>`))}<details><summary>历次处理 ${w.history.length} 次</summary>${w.history.map(h=>`<p>第 ${h.revision} 轮 · ${esc(h.executor||'Codex CLI')} · ${esc(h.bookkeeping_mode||'原有处理')} · ${esc(h.status)} <button class="text" data-action="autonomous-process" data-run-id="${esc(h.id)}">查看过程</button></p>`).join('')}</details></details><nav class="secondary-nav" aria-label="往期记录"><button class="text" data-action="history">往期与归档</button></nav></section>`;
}
function autonomousVoucherEvidence(v){
 if(v.data.origin!=='autonomous-monthly-v1')return '';
 const findings=state.overview.autonomous_workflow?.entry_previews?.find(p=>p.voucher===v.data.voucher_number)?.findings||[];
 return `<div class="goal"><b>${esc(v.data.voucher_number)} · ${esc(v.data.date)}</b><p>${esc(v.data.assessment.reason)}</p><p>当前分录依据已通过独立审查，最终处理由复核人确认。</p>${travelApplicationEvidence(v.data.voucher_number)}${autonomousFindingLinks(findings)}<ul>${autonomousEvidence(v.data.assessment.evidence)}</ul></div>`;
}
function scheduleAutonomousPoll(){
 clearTimeout(autonomousTimer);
 if(!['current','materials','artifacts','historical'].includes(state.view))return;
 if(!state.overview?.autonomous_workflow||!['QUEUED','ANALYZING','REVIEWING','STALE'].includes(state.overview.autonomous_workflow.status))return;
 const epoch=state.epoch;
 autonomousTimer=setTimeout(async()=>{if(epoch!==state.epoch||!['current','materials','artifacts','historical'].includes(state.view)||!state.overview?.autonomous_workflow)return;
  if(state.busy||$('dialog').open||document.querySelector('#workspace details[open]:not(.autonomous-sources)')||document.activeElement?.tagName==='TEXTAREA'){scheduleAutonomousPoll();return;}
  try{await loadWorkbench();}catch(error){notify(error.message);scheduleAutonomousPoll();}
 },5000);
}
function installAutonomousActions(){
 actions['bookkeeping-save']=async()=>{
  if(readonly()||['QUEUED','ANALYZING','REVIEWING'].includes(state.overview?.autonomous_workflow?.status))throw new Error('当前不能修改设置；处理中请先暂停，只读或已关闭期间不能修改。');
  const draftKey=settingsDraftKey(),draft=currentSettingsDraft();
  const p=state.overview.autonomous_workflow.bookkeeping_profile, raw=$('bookkeepingCostRatio').value.trim();
  const value=raw===''?null:Number(raw);
  if(value!==null&&(!Number.isFinite(value)||value<=0||value>100||Math.abs(value*100-Math.round(value*100))>0.000001))throw new Error('成本比例须大于0且不超过100%，最多两位小数。');
  const note=$('bookkeepingSourceNote').value.trim();
  if(value!==null&&!note)throw new Error('请记录本企业成本比例的确认来源。');
  let result;
  try{result=await request('/api/v1/autonomous/bookkeeping-profile',{scope:scope(),mode:$('bookkeepingMode').value,expected_version:draft?.bookkeeping?.expectedVersion??p.selection_version,cost_ratio:value===null?null:(value/100).toFixed(4).replace(/0+$/,'').replace(/\.$/,''),source_note:note});}
  catch(error){
   if(error.code==='VERSION_CONFLICT')error.message='设置版本已变化，你填写的内容已保留。请先刷新，再点“恢复已保存设置”查看最新内容，重新修改后保存。';
   throw error;
  }
  if(draft)delete draft.bookkeeping;
  if(draftKey!==settingsDraftKey())return;
  await loadWorkbench();notify(result.changed===false?'当前已采用该记账方式，选择已确认。':result.run_id?'记账方式已保存，已新建一轮分析；旧结果保留。':'记账方式已保存，上传资料后生效。');
 };
 actions['autonomous-executor']=async()=>{
  if(readonly()||['QUEUED','ANALYZING','REVIEWING'].includes(state.overview?.autonomous_workflow?.status))throw new Error('当前不能修改设置；处理中请先暂停，只读或已关闭期间不能修改。');
  const key=settingsDraftKey(),draft=currentSettingsDraft(),backend=$('autonomousExecutor').value;
  const result=await request('/api/v1/autonomous/executor',{scope:scope(),backend});
  if(draft)delete draft.executor;
  if(key!==settingsDraftKey())return;
  await loadWorkbench();notify(result.changed===false?'当前已使用该 Agent，选择已确认。':result.run_id?'Agent 选择已保存，当前处理版本已更新；旧结果保留。':'Agent 选择已保存，上传资料后将使用所选 Agent。');
 };
 actions['autonomous-upload']=openAutonomousUpload;
 actions['autonomous-preview']=button=>showAutonomousPreview(button.dataset.number);
 actions['autonomous-cancel']=async()=>{await request('/api/v1/autonomous/cancel',{scope:scope()});await loadWorkbench();notify('已暂停自动处理，原件和过程记录已保留。');};
 actions['autonomous-retry']=async()=>{await request('/api/v1/autonomous/start',{scope:scope(),retry:true});await loadWorkbench();notify('已进入继续处理队列。');};
 actions['autonomous-history-recheck']=async()=>{await request('/api/v1/autonomous/start',{scope:scope(),retry:true,recheck:true});await loadWorkbench();notify('已按现有资料重新查证待决事项；旧结论保留在处理历史中。');};
 actions['autonomous-start']=async()=>{await request('/api/v1/autonomous/start',{scope:scope()});await loadWorkbench();notify('已启动月度自主处理。');};
 actions['autonomous-answer']=async()=>{const text=$('autonomousAnswer').value.trim();if(!text)throw new Error('请先填写实际业务情况。');await request('/api/v1/autonomous/answer',{scope:scope(),run_id:state.overview.autonomous_workflow.job.object_id,finding_id:autonomousFinding,text});autonomousDrafts.delete(autonomousDraftKey());await loadWorkbench();notify('业务说明已保存，系统将结合原件重新核查。');};
 actions['autonomous-materials-complete']=()=>openDialog('按现有资料继续分析',`<p>系统将逐项分析：哪些凭证可以完成，哪些需要你确认业务情况，以及确实无法完成的部分。</p><p class="small muted">这表示目前无法再提供附件，并不表示所有业务事实已确认。</p><label for="materialsCompleteNote">补充说明（可不填）</label><textarea id="materialsCompleteNote" rows="3" maxlength="10000"></textarea><button class="primary" data-action="autonomous-materials-submit">确认资料范围并继续分析</button>`);
 actions['autonomous-materials-submit']=async()=>{await request('/api/v1/autonomous/materials-complete',{scope:scope(),run_id:state.overview.autonomous_workflow.job.object_id,note:$('materialsCompleteNote').value.trim()});closeDialog();await loadWorkbench();notify('已记录资料范围，系统将继续分析可行方案。');};
 actions['autonomous-decision']=async()=>{const key=autonomousDraftKey(),choice=autonomousChoices.get(key);if(!choice?.id||!choice.acknowledged)throw new Error('请选择方案并确认适用前提。');await request('/api/v1/autonomous/decision',{scope:scope(),run_id:state.overview.autonomous_workflow.job.object_id,finding_id:autonomousFinding,option_id:choice.id,acknowledged:true,note:$('autonomousAnswer')?.value.trim()||''});autonomousChoices.delete(key);autonomousDrafts.delete(key);await loadWorkbench();notify('选择已记录，系统将重新计算并独立审查相关凭证。');};
 actions['autonomous-match-submit']=submitInvoiceMatching;
 actions['autonomous-process']=async(button)=>{const epoch=state.epoch;const data=await request('/api/v1/autonomous/process',{scope:scope(),run_id:button?.dataset.runId||state.overview.autonomous_workflow.job.object_id});if(epoch!==state.epoch)return;openDialog('处理计划与执行过程',Object.entries(data.documents).map(([name,text])=>`<h3>${name.endsWith('plan.md')?'工作计划':'执行记录'}</h3><pre class="autonomous-prose">${esc(text)}</pre>`).join('')||'<p>任务尚未形成过程文档，进度事件已在工作台显示。</p>');};
 scheduleAutonomousPoll();
}
document.addEventListener('toggle',event=>{if(event.target.matches?.('.autonomous-sources')&&event.target.isConnected)autonomousSourcesOpen=event.target.open;},true);
document.addEventListener('toggle',event=>{
 if(state.view!=='settings'||!event.target.matches?.('.settings-cost')||!event.target.isConnected)return;
 const draft=currentSettingsDraft()||{};draft.costExpanded=event.target.open;autonomousSettingsDrafts.set(settingsDraftKey(),draft);
},true);
document.addEventListener('input',event=>rememberSettingsInput(event.target));
document.addEventListener('input',event=>{if(event.target.id==='autonomousAnswer')autonomousDrafts.set(autonomousDraftKey(),event.target.value);});
document.addEventListener('input',event=>{
 const id=event.target.dataset?.matchingNote;if(!id||readonly()||state.busy)return;
 const draft=matchingDraft(id);draft.note=event.target.value;autonomousMatchingDrafts.set(matchingDraftKey(id),draft);refreshMatchingControls();
});
document.addEventListener('change',event=>{
 rememberSettingsInput(event.target);
 if(event.target.id==='bookkeepingMode'){
  const w=state.overview.autonomous_workflow, option=(w.bookkeeping_profiles||[]).find(o=>o.id===event.target.value);
  $('bookkeepingSummary').textContent=option?.summary||'';
  const locked=readonly()||['QUEUED','ANALYZING','REVIEWING'].includes(w.status)||event.target.value==='ORIGINAL';
  $('bookkeepingCostRatio').disabled=locked;$('bookkeepingSourceNote').disabled=locked;return;
 }
 if(event.target.id==='matchingParty'){autonomousFinding=event.target.value;render();return;}
 const id=event.target.dataset?.matchingFinding,invoice=event.target.dataset?.matchingInvoice;
 if(!id||!invoice||readonly()||state.busy)return;
 const draft=matchingDraft(id);draft.invoice_ids=draft.invoice_ids.filter(i=>i!==invoice);
 if(event.target.checked)draft.invoice_ids.push(invoice);
 autonomousMatchingDrafts.set(matchingDraftKey(id),draft);refreshMatchingControls();
});
document.addEventListener('click',event=>{const b=event.target.closest('[data-autonomous-finding]');if(b?.dataset.autonomousFinding&&!state.busy){autonomousFinding=b.dataset.autonomousFinding;closeDialog();state.view='current';render();$('autonomousAnswer')?.focus({preventScroll:true});document.querySelector('.autonomous-status-title')?.scrollIntoView({block:'start'});}});
document.addEventListener('submit',event=>{
 if(event.target.id!=='autonomousUploadForm')return;
 event.preventDefault();
 exclusive(submitAutonomousUpload).finally(renderAutonomousUpload);
});

// Keep the local selection until every file is saved; retries send only failures.
let autonomousUpload=null;
const uploadSize=n=>n<1024?`${n} B`:n<1024*1024?`${(n/1024).toFixed(1)} KB`:`${(n/1024/1024).toFixed(1)} MB`;
function openAutonomousUpload(){
 if(readonly())return;
 autonomousUpload={files:[],message:'',epoch:state.epoch,busy:false};
 openDialog('补充原始资料',`<form id="autonomousUploadForm" class="stack upload-form"><p>可一次拖入多份资料，也可分次追加。系统会自主识别用途、历史范围和本期业务，保存后自动处理。</p><label id="uploadDropzone" class="upload-dropzone" for="autonomousFiles" tabindex="0" role="button" aria-describedby="uploadDropHint"><input id="autonomousFiles" type="file" multiple class="sr-only"><strong>将文件拖到这里</strong><span>或点击选择多份文件</span><small id="uploadDropHint">单个文件不超过 16 MB；提交前可检查清单、删除文件。</small></label><section id="uploadQueue" class="upload-queue" aria-label="待上传文件"></section><p id="uploadSelectionStatus" class="small muted" role="status" aria-live="polite"></p><button id="uploadSubmit" class="primary" type="submit" disabled>请先选择文件</button></form>`);
 renderAutonomousUpload();$('uploadDropzone').focus({preventScroll:true});
}
function currentAutonomousUpload(ui=autonomousUpload){return !!ui&&ui===autonomousUpload&&ui.epoch===state.epoch&&!!$('autonomousUploadForm')&&$('dialog').open;}
function renderAutonomousUpload(){
 if(!currentAutonomousUpload())return;
 const ui=autonomousUpload,files=ui.files,pending=files.filter(e=>e.status!=='SUCCEEDED'),busy=ui.busy;
 const names={READY:'待提交',UPLOADING:'上传中',SUCCEEDED:'已保存',FAILED:'上传失败'};
 const colors={READY:'',UPLOADING:'blue',SUCCEEDED:'green',FAILED:'red'};
 $('uploadQueue').innerHTML=files.length?`<div class="upload-queue-head"><strong>已选择 ${files.length} 份</strong><span>${uploadSize(files.reduce((n,e)=>n+e.file.size,0))}</span></div><ul class="upload-file-list">${files.map((e,i)=>`<li><div class="upload-file-name"><strong>${esc(e.file.name)}</strong>${e.error?`<small>${esc(e.error)}</small>`:''}</div><span class="upload-file-size">${uploadSize(e.file.size)}</span><span class="badge ${colors[e.status]}">${names[e.status]}</span>${e.status==='SUCCEEDED'?'<span class="upload-remove-placeholder" aria-hidden="true"></span>':`<button class="text upload-remove" type="button" data-upload-index="${i}" aria-label="删除 ${esc(e.file.name)}" ${busy?'disabled':''}>删除</button>`}</li>`).join('')}</ul>`:'<p class="upload-empty">尚未选择文件。拖入后可先检查清单，再统一提交。</p>';
 const retry=pending.length&&pending.every(e=>e.status==='FAILED');
 $('uploadSubmit').textContent=busy?'正在保存资料…':pending.length?`${retry?'重试失败的':'保存'} ${pending.length} 份资料并自动处理`:files.length?'全部资料已保存':'请先选择文件';
 $('uploadSubmit').disabled=readonly()||state.busy||busy||!pending.length;
 $('autonomousFiles').disabled=readonly()||state.busy||busy;
 $('uploadDropzone').setAttribute('aria-disabled',String(readonly()||state.busy||busy));
 $('uploadSelectionStatus').textContent=ui.message||'文件先保留在本地清单，点击保存后才上传。';
}
function addAutonomousFiles(fileList){
 if(!currentAutonomousUpload()||autonomousUpload.busy||state.busy||readonly())return;
 const ui=autonomousUpload;let added=0,duplicate=0,oversized=0;
 for(const file of Array.from(fileList)){
  if(file.size>16*1024*1024){oversized++;continue;}
  // Do not discard a changed file merely because its name and size match.
  const key=JSON.stringify([file.name,file.size,file.lastModified]);
  if(ui.files.some(e=>e.key===key)){duplicate++;continue;}
  ui.files.push({file,key,status:'READY',error:''});added++;
 }
 ui.message=[added&&`已加入 ${added} 份`,duplicate&&`忽略 ${duplicate} 份重复选择的文件`,oversized&&`${oversized} 份超过 16 MB，请拆分后上传`].filter(Boolean).join('；')||'没有新增文件。';
 renderAutonomousUpload();
}
async function submitAutonomousUpload(){
 const ui=autonomousUpload;
 if(!currentAutonomousUpload(ui)||readonly())return;
 const targets=ui.files.filter(e=>e.status!=='SUCCEEDED');
 if(!targets.length)return;
 ui.busy=true;
 try{
  for(const e of targets){
   if(!currentAutonomousUpload(ui))return;
   e.status='UPLOADING';e.error='';ui.message=`正在保存 ${e.file.name}…`;renderAutonomousUpload();
   try{
    const artifact=await uploadFile(e.file,'business',scope().accounting_period_id,null);
    if(!currentAutonomousUpload(ui))return;
    if(!artifact)throw new Error('处理范围已变化，请重新选择文件');
    e.status='SUCCEEDED';
   }catch(error){
    if(!currentAutonomousUpload(ui))return;
    e.status='FAILED';e.error=error.message||'上传失败';
    if(error.status===401||error.status===403)break;
   }
   renderAutonomousUpload();
  }
 }finally{ui.busy=false;}
 if(!currentAutonomousUpload(ui))return;
 const saved=ui.files.filter(e=>e.status==='SUCCEEDED').length,remaining=ui.files.length-saved;
 ui.message=remaining?`${saved} 份已保存，${remaining} 份未保存；可删除或重试未保存文件。`:`已保存 ${saved} 份资料，系统将自动继续处理。`;
 renderAutonomousUpload();notify(ui.message,!!remaining);
 if(!remaining)closeDialog();
 if(saved){state.view='current';await loadWorkbench();}
}
document.addEventListener('change',event=>{
 if(event.target.id!=='autonomousFiles')return;
 addAutonomousFiles(event.target.files);event.target.value='';
});
document.addEventListener('click',event=>{
 const button=event.target.closest('[data-upload-index]');
 if(!button||button.disabled||state.busy||!currentAutonomousUpload()||autonomousUpload.busy||readonly())return;
 const index=Number(button.dataset.uploadIndex),entry=autonomousUpload.files[index];
 if(!entry||entry.status==='SUCCEEDED')return;
 autonomousUpload.files.splice(index,1);autonomousUpload.message=`已从清单移除 ${entry.file.name}。`;renderAutonomousUpload();
});
document.addEventListener('dragover',event=>{
 const zone=event.target.closest?.('#uploadDropzone');if(!zone)return;
 event.preventDefault();if(!autonomousUpload?.busy)zone.classList.add('dragging');
});
document.addEventListener('dragleave',event=>{const zone=event.target.closest?.('#uploadDropzone');if(zone&&!zone.contains(event.relatedTarget))zone.classList.remove('dragging');});
document.addEventListener('drop',event=>{
 const zone=event.target.closest?.('#uploadDropzone');if(!zone)return;
 event.preventDefault();zone.classList.remove('dragging');addAutonomousFiles(event.dataTransfer?.files||[]);
});
document.addEventListener('keydown',event=>{
 if(event.target.id==='uploadDropzone'&&['Enter',' '].includes(event.key)){
  event.preventDefault();if(!readonly()&&!autonomousUpload?.busy)$('autonomousFiles').click();
 }
});

document.addEventListener('change',event=>{
 if(event.target.name!=='reviewOption'&&event.target.id!=='reviewAcknowledged')return;
 if(readonly()||state.busy)return;
 const key=autonomousDraftKey(),choice=autonomousChoices.get(key)||{};
 if(event.target.name==='reviewOption'){choice.id=event.target.value;choice.acknowledged=false;}else choice.acknowledged=event.target.checked;
 autonomousChoices.set(key,choice);
 document.querySelectorAll('input[name="reviewOption"]').forEach(input=>input.closest('.review-option').classList.toggle('selected',input.value===choice.id));
 $('reviewAcknowledged').checked=!!choice.acknowledged;
 document.querySelector('[data-action="autonomous-decision"]').disabled=!choice.id||!choice.acknowledged;
});

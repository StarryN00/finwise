'use strict';

const OPERATOR_HTTP_ENTRY='http://127.0.0.1:8767/static/operator.html';
const $ = id => document.getElementById(id);
const state = {scopes: [], selected: null, overview: null, csrf: '', role: '', user: null, epoch: 0,
  sessionEpoch: 0, portfolioSequence: 0, historySequence: 0, operations: new Map(),
  loadSequence: 0, dialogSequence: 0, busy: false, view: 'current', category: null,
  candidate: null, sources: {balance: '', close: ''}, uploadRole: null, returnFocus: null,
  filesFilter: 'all', filesReturn: null};
const labels = {
  OPEN:'期间开放', CLOSED:'已关闭', LOCKED:'已锁账', ARCHIVED:'已归档', ACTIVE:'有效原件',
  DRAFT:'待核实', CONFIRMED:'已确认', BLOCKED:'已阻断', SUSPENDED:'待补证', CANDIDATE:'候选业务组',
  READY:'可继续处理', PARSED:'已提取，待核实', PARSED_WITH_ISSUES:'提取结果需核对',
  EXTRACTED:'已提取，待核实', CHECKED:'业务校验通过', NEEDS_REVIEW:'需核对提取结果',
  OTHER_PERIOD:'已确认其他期间归属', RECEIVED:'已接收，待提取', PERIOD_EXCEPTION:'期间需确认', FAILED:'处理失败',
  SUCCEEDED:'建议已生成', RUNNING:'处理中', PAUSED:'已暂停', CANCELLED:'已取消', PENDING:'待审阅',
  REVISED:'已修订待复核', LOCALLY_CONFIRMED:'本地已复核', DELIVERABLE:'待导出',
  EXPORT_CREATED:'等待外部回执', EXTERNAL_IMPORTED:'外部回执已记录', APPROVED:'已审阅通过',
  COMPLETED:'已完成', PARTIAL:'部分完成', WAITING:'等待处理', NOT_STARTED:'尚未开始',
  INVOICE:'采购发票', SALES_INVOICE:'销售发票', PAYMENT:'付款', RECEIPT:'收款',
  CONTRACT:'采购合同', STOCK_IN:'入库证据', BANK_TRANSACTION:'银行记录',
  PAYROLL:'工资', SOCIAL_SECURITY:'社保', HOUSING_FUND:'公积金', INDIVIDUAL_INCOME_TAX:'个税',
  ELECTRONIC_ACCEPTANCE:'电子承兑', RULE_SUGGESTION:'规则建议', DOCUMENT_UNDERSTANDING:'资料理解',
  BUSINESS_EVENT:'业务识别', GROUPING:'候选分组', EXCEPTION:'异常分析', DEBIT:'借方', CREDIT:'贷方'
};
const kindLabels = {purchase_invoices:'采购进项发票',sales_invoices:'销售发票',contract:'采购合同',stock_in:'入库单',
  bank_statement:'银行流水',payroll:'工资表',social_security:'社保明细',housing_fund:'公积金明细',
  electronic_acceptance:'电子承兑',individual_income_tax:'个人所得税申报'};
const fieldLabels = {invoice_no:'发票号码',invoice_total:'价税合计',tax:'税额',net_amount:'不含税金额',tax_rate:'税率',
  transaction_date:'交易日期',business_date:'业务日期',payment_total:'付款金额',amount:'金额',supplier:'交易对方',
  direction:'收支方向',income:'收入金额',expense:'支出金额',balance:'余额',invoice_status:'发票状态',
  account_code:'科目编码',account_name:'科目名称',contract_no:'合同编号',stock_in_no:'入库编号',
  transaction_id:'交易编号',external_id:'外部编号',bank_account_ref:'账户标识'};
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const label = value => labels[value] || '待核对';
const amount = value => value == null ? '未提供' : Number.isFinite(Number(value)) ? Number(value).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2}) : esc(value);
const scope = () => state.scopes[state.selected]?.scope;
const scopeKey = s => s ? ['tenant_id','organization_id','legal_entity_id','ledger_id','accounting_period_id','baseline_id'].map(k=>s[k]).join('|') : '';
const readiness = () => state.overview.data_readiness;
function operatorRecordedMaterialOpinion(t) {
  return (Array.isArray(t?.material_opinions) ? t.material_opinions : []).find(o =>
    o?.valid === true && (
      o.status === 'SAVED_NOT_EXECUTED' ||
      o.data?.status === 'SAVED_NOT_EXECUTED' ||
      typeof o.text === 'string' ||
      typeof o.data?.text === 'string'
    )
  ) || null;
}
function operatorMaterialIsSystemTask(t) {
  if (typeof materialSystemTask === 'function') return materialSystemTask(t);
  return !!t?.triage && (t.triage.version !== 'issue-triage-v1' || t.triage.route !== 'HUMAN');
}
function materialCounts() {
  const review=state.overview?.material_review||{},m=review.counts||{},flow=review.flow?.counts||{},tasks=review.tasks,c=readiness()?.counts||{},usable=readiness()?.usable_results||[];
  const unresolved=(tasks||[]).filter(t=>t.kind!=='VERIFY'&&!t.deferred);
  const opinionTasks=unresolved.filter(t=>operatorRecordedMaterialOpinion(t));
  const systemTasks=unresolved.filter(t=>operatorMaterialIsSystemTask(t));
  const humanTasks=unresolved.filter(t=>!operatorMaterialIsSystemTask(t)&&!operatorRecordedMaterialOpinion(t));
  return {files:m.files??c.files??0, records:m.records??c.records??0,
    system_checked:m.system_checked??(m.awaiting_verification??0)+(m.source_verified??0),
    issue_confirmed:m.issue_confirmed??0, invoice_amount_confirmed:m.invoice_amount_confirmed??0, business_confirmed:m.business_confirmed??0, bill_confirmed:m.bill_confirmed??0,
    source_verified:m.source_verified??0, needs_review:m.needs_review??c.needs_review??0,
    period_exceptions:m.period_exceptions??c.period_exceptions??0,other_period:m.other_period??0,
    issue_tasks:m.issue_tasks??0, deferred:m.deferred??0,
    selected_processing_tasks:flow.system_processing??m.selected_processing_tasks??opinionTasks.length,
    human_issue_tasks:flow.user_total??(m.human_issue_tasks!==undefined?Math.max(0,m.human_issue_tasks-(m.selected_processing_tasks===undefined?opinionTasks.length:0)):humanTasks.length),
    system_issue_tasks:flow.system_check??m.system_issue_tasks??systemTasks.length,
    needs_decision:flow.needs_decision??0,needs_input:flow.needs_input??0,ready_to_confirm:flow.ready_to_confirm??0,user_action:flow.user_action??m.human_issue_tasks??0,
    system_processing:flow.system_processing??(tasks?opinionTasks.length:m.selected_processing_tasks??0),
    system_check:flow.system_check??m.system_issue_tasks??systemTasks.length,
    system_total:flow.system_total??(tasks?systemTasks.length+opinionTasks.length:(m.system_issue_tasks??0)+(m.selected_processing_tasks??0)),waiting_external:flow.waiting_external??m.deferred??0,
    completed:flow.completed??0,failed:flow.failed??0,stale:flow.stale??0,
    accounting_usable:m.accounting_usable??usable.length,
    file_states:m.file_states||{}};
}
const fileById = id => state.overview.artifacts.find(a=>a.object_id===id);
const activeArtifacts = () => state.overview.artifacts.filter(a=>a.status!=='ARCHIVED');
const baselineArtifacts = () => activeArtifacts().filter(a=>readiness().categories.find(c=>c.id==='baseline').artifact_ids.includes(a.object_id));
const purposeLabel = d => ({opening_balance:'期初余额',prior_close:'上期结账',historical_reference:'历史账表（用途待核对）'}[d.source_purpose]||kindLabels[d.parse_options?.document_kind]||'用途待核对');
const displayCompany = s => s.legal_entity_id === 'kunshan-juxianda' ? '聚贤达' : s.legal_entity_id;
const companyName = item => item.display_context?.company_name || displayCompany(item.scope);
const licenseNumber = item => item.display_context?.business_license_number || '营业执照编号待补充';
const ledgerName = item => item.display_context?.ledger_name || '主账套';
const readonly = () => state.role==='viewer' || !state.overview || state.overview.period.status!=='OPEN';
const previousPeriod = period => {const [y,m]=period.split('-').map(Number);return `${m===1?y-1:y}-${String(m===1?12:m-1).padStart(2,'0')}`;};
function storage(key,value) { try { if(value===undefined)return localStorage.getItem(key); localStorage.setItem(key,value); } catch (_) {} return null; }
function badge(text,color='') {return `<span class="badge ${color}">${esc(text)}</span>`;}
function statusBadge(status) {return badge(label(status),['CHECKED','LOCALLY_CONFIRMED','CONFIRMED','EXTERNAL_IMPORTED','COMPLETED'].includes(status)?'green':['BLOCKED','FAILED'].includes(status)?'red':['DRAFT','NEEDS_REVIEW','PERIOD_EXCEPTION','SUSPENDED','PENDING'].includes(status)?'yellow':'blue');}
function table(head,rows) {return `<div class="table-wrap" tabindex="0" role="region" aria-label="可横向滚动的数据表"><table><thead><tr>${head.map(h=>`<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table></div>`;}
function objectButton(id,text='查看依据') {return `<button type="button" class="text" data-object="${esc(id)}">${esc(text)}</button>`;}
function renderMaterialGuidanceRecords(){
  const calls=state.overview.material_guidance||[];
  return `<h3>资料办理建议</h3><p class="small muted">只解释问题与推荐已有操作，不计入业务事实覆盖，也不代表人工确认。</p>${calls.length?table(['时间／责任人','模型','建议状态','依据'],calls.map(r=>{const d=r.data,g=d.gateway||{},response=d.response||{},text=({PROPOSED:'候选待人工判断',NEEDS_HUMAN:'需要人工判断',FAILED:'未得到有效建议',RUNNING:'正在请求建议'})[response.status]||'状态待核对';return `<tr><td>${esc(r.created_at)}<p>${esc(d.requested_by)}</p></td><td>${esc(g.model_version||'未记录')}<p>${g.mock===true?'模拟调用':g.mock===false?'真实调用尝试':'调用方式未记录'}</p></td><td>${esc(text)}</td><td>${objectButton(r.object_id,'查看建议与版本依据')}</td></tr>`;})):'<p class="empty-proof">尚未请求资料办理建议；规则引导不会自动调用模型。</p>'}`;
}
function notify(message,error=false) {$('notice').className=`notice${error?' error':''}`;$('notice').textContent=message;}
function clearNotice() {$('notice').className='notice hidden';$('notice').textContent='';}
function clearSession() {
  clearNotice();
  if(typeof resetParsePlanState==='function')resetParsePlanState();
  if(typeof resetBankState==='function')resetBankState();
  if(typeof resetMaterialState==='function')resetMaterialState();
  if(typeof resetHistoricalPlans==='function')resetHistoricalPlans();
  state.user=null;
  state.epoch++;state.sessionEpoch++;state.portfolioSequence++;state.loadSequence++;state.scopes=[];state.selected=null;state.overview=null;state.csrf='';state.role='';state.operations.clear();
  state.candidate=null;state.sources={balance:'',close:''};state.category=null;state.view='current';
  state.filesFilter='all';state.filesReturn=null;
  $('baselineFile').value='';closeDialog();$('dialogBody').replaceChildren();
  $('workspace').innerHTML='<div class="empty">请登录后查看授权企业。</div>';
  $('loginForm').classList.remove('hidden');$('scopeChooser').classList.add('hidden');$('logout').classList.add('hidden');$('authState').textContent='需要登录';renderScopes();
}
async function request(path,body,method) {
  const sessionEpoch=state.sessionEpoch;
  const headers={'Content-Type':'application/json'};if(state.csrf)headers['X-CSRF-Token']=state.csrf;
  const response=await fetch(path,{method:method||(body?'POST':'GET'),headers,credentials:'same-origin',...(body?{body:JSON.stringify(body)}:{})});
  let data={};
  try{data=await response.json();}
  catch(_){if(response.ok)throw new Error('响应未完整接收，操作结果尚不确定。请重试核对，系统会复用本次操作记录，避免重复执行。');}
  if(!response.ok){
    if(sessionEpoch===state.sessionEpoch){
      if(response.status===401)clearSession();
      else if(response.status===403&&data.error?.code==='SCOPE_VIOLATION'&&scopeKey(body?.scope)===scopeKey(scope())){
        clearSession();loadPortfolio().catch(()=>{});
      }
    }
    const error=new Error(data.error?.message||`请求未完成（${response.status}），请检查资料或登录状态`);error.status=response.status;throw error;
  }
  return data;
}
async function exclusive(fn) {
  if(state.busy)return;state.busy=true;
  const controls=[...document.querySelectorAll('button,input,select,textarea')].filter(el=>!el.disabled&&!['closeDialog'].includes(el.id));
  controls.forEach(el=>el.disabled=true);
  try{await fn();}catch(e){notify(e.message,true);}finally{state.busy=false;controls.forEach(el=>{if(el.isConnected)el.disabled=false;});renderScopes();}
}
function renderScopes() {
  const term=$('search').value.trim().toLowerCase();
  $('scopeList').innerHTML=state.scopes.map((item,i)=>({item,i})).filter(({item})=>[companyName(item),licenseNumber(item),ledgerName(item),...Object.values(item.scope)].join(' ').toLowerCase().includes(term)).map(({item,i})=>
    `<button class="scope ${state.selected===i?'selected':''}" data-scope="${i}" ${state.busy?'disabled':''} aria-pressed="${state.selected===i}"><span class="scope-main"><strong>${esc(companyName(item))}</strong><span class="scope-license" title="营业执照编号：${esc(licenseNumber(item))}">${esc(licenseNumber(item))}</span><span>${esc(item.scope.accounting_period_id)}</span></span><span class="scope-tools">${badge(item.blockers.length?'已阻断':item.baseline.validation.status!=='VALID'?'待核实':'处理中',item.blockers.length?'red':'yellow')}<br>${item.blockers.length?`${item.blockers.length} 组阻断`:`${item.pending_confirmation_cards} 项待审阅`}</span></button>`).join('')||'<p class="muted small">没有匹配的授权范围</p>';
}
async function loadPortfolio() {
  const sessionEpoch=state.sessionEpoch,sequence=++state.portfolioSequence;
  const current=()=>sessionEpoch===state.sessionEpoch&&sequence===state.portfolioSequence;
  const session=await request('/api/v1/auth/me');if(!current())return;state.csrf=session.csrf_token||'';state.role=session.role;state.user={user_id:session.user_id};
  const result=await request('/api/v1/portfolio');if(!current())return;state.scopes=result.scopes||[];
  $('authState').textContent=state.role==='viewer'?'只读账号':'已登录';$('loginForm').classList.add('hidden');$('scopeChooser').classList.remove('hidden');$('logout').classList.remove('hidden');
  const saved=storage('finwise.operator.scope');let index=state.scopes.findIndex(i=>scopeKey(i.scope)===saved);
  if(index<0)index=state.scopes.findIndex(i=>[i.scope.legal_entity_id,i.scope.ledger_id,i.scope.accounting_period_id].join('|')===saved);
  if(state.scopes.length)await selectScope(index<0?0:index);else renderScopes();
}
async function selectScope(index) {
  clearNotice();
  if(typeof resetBankState==='function')resetBankState();
  if(typeof resetMaterialState==='function')resetMaterialState();
  if(typeof resetHistoricalPlans==='function')resetHistoricalPlans();
  if(typeof resetParsePlanState==='function')resetParsePlanState();
  state.epoch++;state.selected=index;state.overview=null;state.category=null;state.view='current';
  if(typeof materialState==='function'&&storage('finwise.material.view.'+materialState().key)==='materials')state.view='materials';
  if(typeof mappingState==='function'){const ui=mappingState(),saved=storage('finwise.mapping.view.'+ui.key);ui.draft=null;ui.confirmed=false;if(saved){ui.id=saved;state.view='mapping';}}
  state.filesFilter='all';state.filesReturn=null;
  state.candidate=null;state.sources={balance:'',close:''};state.uploadRole=null;$('baselineFile').value='';
  closeDialog();$('dialogBody').replaceChildren();closeSidebar();storage('finwise.operator.scope',scopeKey(scope()));
  $('workspace').innerHTML='<div class="empty" role="status">正在读取该企业的资料与核对状态…</div>';renderScopes();
  await loadWorkbench();
}
async function loadWorkbench() {
  const selected=scope(),epoch=state.epoch,sequence=++state.loadSequence;if(!selected)return;
  const data=await request('/api/v1/workbench',{scope:selected});
  if(epoch!==state.epoch||sequence!==state.loadSequence)return;
  state.overview=data;
  if(!data.data_readiness)throw new Error('工作台服务尚未更新，请重新启动当前服务后刷新。');
  for(const role of ['balance','close']) {
    if(state.sources[role]&&!data.artifacts.some(a=>a.object_id===state.sources[role]&&a.status!=='ARCHIVED'))state.sources[role]='';
    if(!state.sources[role]&&data.data_readiness.baseline_sources[role].length===1)state.sources[role]=data.data_readiness.baseline_sources[role][0];
  }
  render();
  if(typeof scheduleHistoricalPoll==='function')scheduleHistoricalPoll();
  if(typeof scheduleMappingPoll==='function')scheduleMappingPoll();
}
function renderContext() {const d=state.overview;return `<section class="context row"><div><h1>${esc(companyName(d))}</h1><p class="small muted">账套 <span>${esc(ledgerName(d))}</span> · <button class="text" data-action="accounts-open">对公账户 ${d.bank_accounts?.accounts.length||0}</button></p></div><div><div class="period">${esc(d.scope.accounting_period_id)}</div>${statusBadge(d.period.status)}</div></section>`;}
function renderProgress() {
  const p=state.overview.progress;
  const stages=p.stages.map((s,i)=>{
    const source=s.id==='source',tag=source?'button':'div';
    return `<${tag} class="stage ${source?'stage-link':''} ${s.status==='COMPLETED'?'done':''} ${s.id===p.current_stage?'current':''}" ${source?'id="sourceStage" data-action="artifacts" aria-label="资料接收：查看已上传资料清单" title="查看已上传资料清单"':''} ${s.id===p.current_stage?'aria-current="step"':''}><strong><span class="stage-marker">${s.status==='COMPLETED'?'✓':i+1}</span> ${esc(s.name)}${source?'<span class="stage-entry" aria-hidden="true"> ↗</span>':''}</strong><span class="stage-summary">${esc(s.id==='analysis'&&s.status==='COMPLETED'?`已提取 ${materialCounts().records} 条记录`:s.summary)}</span></${tag}>`;
  }).join('');
  const c=materialCounts();
  return `<section class="panel pad" aria-label="本期办理进度"><div class="progress-head"><div class="progress-explain"><span class="small muted">本期办理</span><strong>已完成 ${p.completed_count} / ${p.total_count} 阶段</strong><div class="track" role="progressbar" aria-label="整体阶段完成度" aria-valuenow="${p.overall_percent}" aria-valuemin="0" aria-valuemax="100"><span style="width:${p.overall_percent}%"></span></div></div><div class="progress-aside small muted">${c.files} 份原件 · ${state.overview.blockers.length} 组业务阻断</div></div><div id="stages" class="stages">${stages}</div><div class="actions mobile-only"><button class="text" data-action="stages" aria-expanded="false">阶段总览</button><button id="mobileFiles" class="text" data-action="artifacts">已接收资料 ${c.files} 份 →</button></div></section>`;
}
function categoryButton(id,text) {return `<button class="text" data-category="${id}">${esc(text)}</button>`;}
function renderStructure() {
  const cats=readiness().categories,base=cats[0],unknown=cats.at(-1),business=cats.slice(1,-1),count=business.reduce((s,n)=>s+n.file_count,0),c=materialCounts();
  return `<section class="structure" aria-labelledby="structureTitle"><div class="row section-title"><h2 id="structureTitle">资料结构</h2><span class="small muted">${c.files} 份本期原件</span></div><div class="structure-grid"><div class="structure-tile ${state.category==='baseline'?'active':''}">${categoryButton('baseline','期初与历史衔接')}<div class="structure-count">${base.file_count} 份 · ${state.overview.baseline_validation.status==='VALID'?'已通过':'待核实'}</div><p class="small muted">历史账表与期初依据，单独处理</p></div><div class="structure-tile ${business.some(c=>c.id===state.category)?'active':''}">${categoryButton('business',`${Number(scope().accounting_period_id.slice(-2))}月业务资料`)}<div class="structure-count">${count} 份</div><div class="category-links">${business.map(c=>categoryButton(c.id,`${c.name} ${c.file_count}`)).join('')}</div></div><div class="structure-tile ${state.category==='unassigned'?'active':''}">${categoryButton('unassigned','归属或用途待确认')}<div class="structure-count">${unknown.file_count} 份待定原件</div><p class="small muted">另有 ${c.period_exceptions} 条期间待确认记录</p></div></div></section>`;
}
function renderPrerequisite(){
  const p=state.overview.progress?.prerequisite;if(!p)return '';
  const action=p.status==='ACTION_REQUIRED',valid=p.status==='VALID';
  const job=state.overview.historical_preparation;
  return `<section class="panel pad prerequisite ${action?'attention':''}" aria-label="期初与历史衔接"><div class="row"><div><span class="small muted">期初与历史衔接</span><h2>${esc(p.summary)}</h2></div>${badge(valid?'已通过':action?'需要处理':'等待中',valid?'green':action?'yellow':'blue')}</div><div class="prerequisite-meta"><span>已记录意见 <b>${p.recorded_count||0} / ${p.issue_count||0}</b></span><span>暂无法补充 <b>${p.deferred_count||0}</b></span><span>仍待处理 <b>${p.pending_count||0}</b></span></div><p class="small muted">${valid?'历史资料已作为期初依据保留。':`影响：${(p.blocks||[]).join('、')}；不影响：${(p.does_not_block||[]).join('、')}。`}</p>${job?'<button class="text" data-action="historical-details">查看历史处理记录</button>':''}</section>`;
}
function renderResults() {
  const r=readiness(),c=materialCounts(),model=r.model_coverage||{};
  const drill=(text,value,filter)=>`<button class="result-value" data-action="material-open-filter" data-filter="${filter}"><strong>${value}</strong><span>${text}</span></button>`;
  return `<aside class="result-summary" aria-label="本期资料办理状态"><section class="panel pad"><div class="row"><h2>办理状态</h2><span class="small muted">${c.records} 条资料记录</span></div><div class="result-grid flow-result-grid"><div class="result-metric">${drill('待你处理',c.user_action,'all')}<p class="small muted">现在需要你选择或补充</p></div><div class="result-metric">${drill('待确认执行',c.ready_to_confirm,'ready')}<p class="small muted">方案已明确，等待最终确认</p></div><div class="result-metric">${drill('系统处理中',c.system_processing,'system')}<p class="small muted">另有系统检查 ${c.system_check} 项；你当前无需操作</p></div><div class="result-metric">${drill('等待外部',c.waiting_external,'deferred')}<p class="small muted">原因已记录，不重复提交</p></div><div class="result-metric">${drill('已完成',c.completed,'results')}<p class="small muted">已形成明确处理或核实结果</p></div></div><p class="small muted result-equation">资料记录口径：系统检查通过 ${c.system_checked} 条，其中人工核实 ${c.source_verified} 条；仍需核对 ${c.needs_review} 条、期间待确认 ${c.period_exceptions} 条。事项状态与记录数量分别统计。</p><button class="text" data-action="material-open-filter" data-filter="results">查看资料成果与来源 →</button></section><section class="panel pad result-usable"><div class="row"><h2>账务可用</h2>${badge(`${c.accounting_usable} 条`,c.accounting_usable?'green':'')}</div><p class="small muted">沿用基线、业务和证据校验结果，不把资料提取或人工核实直接当成账务可用。</p><button class="text" data-action="material-open-filter" data-filter="usable">查看账务可用依据</button><div class="record-note"><strong>处理记录</strong><p>${model.real_successful_calls||0} 次业务建议真实调用 · 调用时涉及 ${model.historical_fact_count||0} 条事实</p><button class="text" data-action="records">查看模型与格式识别记录</button></div></section></aside>`;
}
function historicalActionable() {
  const job=state.overview?.historical_preparation,status=job?.status;
  if(!job)return false;
  if(['READY_FOR_CONFIRMATION','WAITING_INPUT','NEEDS_SELECTION','FAILED','STALE'].includes(status))return true;
  if(status==='NEEDS_REVIEW'&&typeof historicalIssueFlow==='function')return historicalIssueFlow(job).pending.length>0;
  return false;
}
function historyCanWaitForCurrent() {
  const status=state.overview?.historical_preparation?.status;
  if(['QUEUED','RUNNING'].includes(status))return true;
  if(status==='NEEDS_REVIEW'&&typeof historicalIssueFlow==='function')return historicalIssueFlow().pending.length===0;
  return false;
}
function currentTask() {
  const d=state.overview,r=readiness();
  const next=d.material_review?.next_step;
  if(next?.version==='workbench-next-step-v1'){
    const kind=next.action?.kind;
    if(kind==='HISTORICAL')return 'baseline';
    if(kind==='UPLOAD')return 'upload';
    if(kind==='MATERIAL_TASK')return 'guided-material';
    if(kind==='BLOCKERS')return 'blockers';
    if(kind==='CONFIRMATION_CARDS')return 'cards';
    if(kind==='VOUCHERS')return 'vouchers';
    if(kind==='GROUPS')return 'groups';
    if(!next.action)return 'guided-wait';
  }
  if(d.historical_preparation&&d.baseline_validation.status!=='VALID'&&historicalActionable())return 'baseline';
  const currentFiles=d.artifacts.filter(a=>a.status!=='ARCHIVED'&&a.data.observed_period===scope().accounting_period_id);
  if(!currentFiles.length)return 'upload';
  if(d.baseline_validation.status!=='VALID'&&!historyCanWaitForCurrent())return 'baseline';
  if(materialCounts().human_issue_tasks)return 'issues';
  if(currentFiles.some(a=>['RECEIVED','FAILED'].includes(a.data.parse_status||'RECEIVED')&&!d.material_review?.tasks?.some(t=>t.artifact_id===a.object_id&&operatorMaterialIsSystemTask(t))))return 'analysis';
  if(!d.material_review&&(r.counts.needs_review||r.counts.period_exceptions))return 'issues';
  if(materialCounts().selected_processing_tasks)return 'selected-issues';
  if(d.blockers.length)return 'blockers';
  if(d.pending_confirmation_cards.length)return 'cards';
  if(d.vouchers.length)return 'vouchers';
  if(materialCounts().system_issue_tasks)return 'system-issues';
  return 'groups';
}
function taskShell(title,body,actions,taskStatus) {
  const stage=state.overview.progress.stages.find(s=>s.id===state.overview.progress.current_stage);
  const inline=body.includes('<!--task-action-->');
  if(inline)body=body.replace('<!--task-action-->',`<div class="inline-task-actions">${actions}</div>`);
  return `<section class="panel" id="currentTask"><div class="focus-head row"><div><span class="small">当前步骤 · ${esc(stage.name)}</span><h2>${esc(title)}</h2></div>${readonly()?badge('只读'):taskStatus||badge('需要处理','yellow')}</div><div class="task-content">${body}</div>${actions&&!inline?`<div class="task-actions">${actions}</div>`:''}</section>`;
}
function primary(action,text,disabled=false) {return `<button class="primary" data-action="${action}" ${disabled?'disabled':''}>${esc(text)}</button>`;}
function renderBaseline() {
  if(state.overview.historical_preparation)return renderHistoricalTask(state.overview.historical_preparation);
  const r=readiness(),prior=previousPeriod(scope().accounting_period_id),candidate=state.candidate;
  const missing=['balance','close'].filter(k=>!state.sources[k]);
  const received=baselineArtifacts(),unassigned=received.filter(a=>!Object.values(state.sources).includes(a.object_id));
  const reviewUploaded=missing.length>0&&unassigned.length>0;
  const pending=received.some(a=>['RECEIVED','FAILED'].includes(a.data.parse_status||'RECEIVED'));
  const headline=reviewUploaded?`已接收 ${received.length} 份历史 / 期初资料，${pending?'待解析与用途核对':'待核对用途'}`:missing.length?`尚有 ${missing.length} 类来源未指定`:'来源已选，仍需逐行比较';
  let body=`<div class="issue-banner">${headline}</div><p>${reviewUploaded?'先查看已上传账表，核对资料用途和提取状态，无需重复上传。':''}需要确认本期期初余额与 ${esc(prior)} 期末余额一致。</p>${!candidate?'<!--task-action-->':''}<div class="goal"><b>完成条件</b>来源完整、科目及辅助核算逐行一致、借贷平衡，并经人工核实。</div>`;
  body+=['balance','close'].map(role=>{
    const selected=fileById(state.sources[role]),name=role==='balance'?'本期期初余额':'上期末余额 / 结账资料';
    const eligible=new Set(r.baseline_sources[role]),all=state.overview.artifacts.filter(a=>a.status!=='ARCHIVED'&&a.data.observed_period===prior);
    const options=items=>items.map(a=>`<option value="${esc(a.object_id)}" ${a.object_id===state.sources[role]?'selected':''}>${esc(a.data.filename)} · v${a.version}</option>`).join('');
    return `<div class="source-slot"><div class="row"><strong>${name}</strong>${badge(selected?'已选，未核实':reviewUploaded?'待核对用途':'待指定来源',selected?'blue':'yellow')}</div>${selected?`<p class="small">${esc(selected.data.filename)} ${objectButton(selected.object_id,'原件')}</p>`:''}<details><summary class="small">${selected?'更换':'选择已接收的'}原件</summary><label class="small">按用途选择，不按月份自动匹配<select data-source-role="${role}" aria-label="${name}来源" ${readonly()?'disabled':''}><option value="">请明确选择来源</option>${options(all.filter(a=>eligible.has(a.object_id)))}<optgroup label="其他上期原件（用途尚未核对）">${options(all.filter(a=>!eligible.has(a.object_id)))}</optgroup></select></label><button class="text" data-upload-role="${role}" ${readonly()?'disabled':''}>添加新的${name}原件</button></details></div>`;
  }).join('');
  if(candidate)body+=renderComparison(candidate);
  let action;
  if(candidate?.status==='READY_FOR_CONFIRMATION')action=primary('confirm-baseline','确认期初核对结果',true);
  else if(reviewUploaded)action=primary('baseline-files','查看已上传账表');
  else if(missing.length)action=primary('upload-baseline',missing[0]==='balance'?'添加期初余额资料':'添加上期末余额资料',readonly());
  else action=primary('compare-baseline',candidate?'重新核对余额':'生成余额核对结果',readonly());
  return taskShell(reviewUploaded?'核对已上传的期初衔接资料':'补充并核对期初余额',body,action);
}
function renderComparison(c) {
  const sourceCell=(role,line,side)=>{
    const source=c.sources[role],id=source?.artifact_id||state.sources[role],a=fileById(id);
    return `<td class="amount"><span class="mono">${amount(line?.[side+'_debit'])} / ${amount(line?.[side+'_credit'])}</span><p class="small muted">${esc(a?.data.filename||source?.filename||'来源')} · v${source?.version||a?.version||'—'}</p><p class="small mono">${esc(line?.source_anchor?.region||`第 ${line?.source_anchor?.row||'—'} 行`)}</p>${objectButton(id,'查看此侧原件')}</td>`;
  };
  return `<div id="comparison" style="margin-top:16px"><div class="row"><h3>余额核对结果</h3>${badge(`${c.matched_lines} / ${c.line_count} 行一致`,c.status==='READY_FOR_CONFIRMATION'?'green':'red')}</div><p class="small muted">期初借方 / 贷方 ${amount(c.totals.opening_debit)} / ${amount(c.totals.opening_credit)}</p>${c.issues.length?`<ul class="issue-list">${c.issues.map(i=>`<li>${esc(i)}</li>`).join('')}</ul>`:''}
    ${table(['科目 / 辅助核算','期初借方 / 贷方及来源','上期末借方 / 贷方及来源','结果'],c.comparisons.map(i=>`<tr><td>${esc(i.account_code)} ${esc(i.opening?.account_name||i.closing?.account_name)}<p>${esc(i.auxiliary_key||'')}</p></td>${sourceCell('balance',i.opening,'opening')}${sourceCell('close',i.closing,'closing')}<td>${badge(i.status==='MATCH'?'一致':'待核对',i.status==='MATCH'?'green':'red')}</td></tr>`))}
    ${c.status==='READY_FOR_CONFIRMATION'?'<label class="check-label"><input id="baselineConfirmed" type="checkbox">我已核对来源、科目及辅助核算明细的完整性，确认本期期初与上期末一致。</label>':'<p class="small muted">请补充或更换原始资料，再重新核对。当前不能确认。</p>'}</div>`;
}
function renderTask() {
  const task=currentTask(),d=state.overview,r=readiness();
  const next=d.material_review?.next_step;
  if(task==='guided-material')return taskShell(next.title,`<p>${esc(next.explanation)}</p><div class="goal"><b>现在要做</b>进入对应问题，核对源数据并完成这一项明确操作。</div>`,`<button type="button" class="primary" data-action="material-open-task" data-task="${esc(next.task_id)}">${esc(next.action?.label||'进入处理')}</button>`,badge(next.state==='READY_TO_CONFIRM'?'待确认执行':next.state==='NEEDS_INPUT'?'待补充信息':'待你处理','yellow'));
  if(task==='guided-wait'){
    const waiting=Array.isArray(next?.waiting)&&next.waiting.length?`<ul>${next.waiting.map(item=>`<li>${esc(item)}</li>`).join('')}</ul>`:'';
    const secondary=materialCounts().system_total?'<button type="button" class="secondary" data-action="material-open-filter" data-filter="system">查看系统处理中事项</button>':materialCounts().waiting_external?'<button type="button" class="secondary" data-action="material-open-filter" data-filter="deferred">查看等待事项</button>':'';
    return taskShell('你当前无需操作',`<p>${esc(next?.explanation||'当前没有需要你处理的事项。')}</p>${waiting}<div class="goal"><b>下一步</b>条件变化后，系统会在这里给出唯一的明确操作，无需反复检查各个功能入口。</div>`,secondary,badge(next?.owner==='SYSTEM'?'系统处理中':next?.owner==='EXTERNAL'?'等待外部':'当前无待办','blue'));
  }
  if(task==='baseline')return renderBaseline();
  if(task==='upload')return taskShell('接收本期业务资料','<p>当前尚未接收本期业务原件。</p><div class="goal"><b>需要提供</b>本期发票、银行与票据、薪酬及税费资料；期初衔接资料单独归类。</div><p class="small muted">保存后按资料类型提取，提取完成不表示已核实。</p>',primary('upload','添加本期资料',readonly()));
  if(task==='analysis')return taskShell('完成资料提取','<p>部分原件尚未解析或解析失败。请先选择正确的资料类型，查看提取结果和具体错误。</p><div class="goal"><b>完成条件</b>本批资料完成提取，缺失字段和期间例外保留待核对。</div>',primary('artifacts','查看待提取资料'));
  if(task==='issues')return taskShell('处理待你确认的事项',`<p>当前有 ${materialCounts().human_issue_tasks} 项需要你选择处理方式或补充确认信息。</p><p>仍有 ${r.counts.needs_review} 条提取结果需核对、${r.counts.period_exceptions} 条期间例外；记录数与任务数分别统计。</p>`,primary('issues','查看待你处理的事项'));
  if(task==='selected-issues')return taskShell('你当前无需操作',`<p>已有 ${materialCounts().system_processing} 项由系统继续整理；原问题、资料核实和账务门禁仍保留。</p><div class="goal"><b>下一步</b>系统形成可执行方案后，会给出明确的确认动作。</div>`,`<button type="button" class="secondary" data-action="material-open-filter" data-filter="system">查看系统处理中事项</button>`,badge('系统处理中','blue'));
  if(task==='system-issues')return taskShell('系统问题待检查','<p>当前系统事项尚未通过，不需要在此确认或上传。请查看来源、检查结果及明确下一步；其他业务门禁保持。</p>','<button type="button" class="primary" data-action="material-open-filter" data-filter="system">查看系统待检查事项</button>');
  if(task==='blockers')return taskShell('补齐阻断业务的证据',`<div class="issue-banner red">${d.blockers.length} 组业务尚不能继续</div>${d.blockers.map(b=>`<p>${esc(b.reason)}；缺少 ${(b.missing_evidence||[]).map(label).map(esc).join('、')||'有效校验依据'}。</p>`).join('')}<div class="goal"><b>完成条件</b>补齐对应业务证据，确认归属，再通过确定性校验。上传本身不会解除阻断。</div>`,primary('blockers','查看补证清单'));
  if(task==='cards')return taskShell('审阅候选规则',`<p>${d.pending_confirmation_cards.length} 项建议待审阅。模型建议仅供参考，应先核对来源和适用范围。</p><div class="goal"><b>完成条件</b>经有权人员审阅并通过原有规则门禁，才生成正式规则。</div>`,primary('cards','查看待审阅事项'));
  if(task==='vouchers')return taskShell('复核凭证与交付结果',`<p>本期 ${d.vouchers.length} 个凭证版本，${d.deliveries.length} 个交付包。</p><div class="goal"><b>完成条件</b>凭证本地复核与外部回执分别核对，不把导出当成入账。</div>`,primary('vouchers','查看本期全部凭证'));
  return taskShell('核对业务归属并继续处理','<p>请检查业务组的事实、规则和最新校验结果。</p><div class="goal"><b>完成条件</b>证据、规则和确定性校验全部通过后，才能生成待复核凭证。</div>',primary('groups','查看业务处理组'));
}
function artifactTable(artifacts) {
  return artifacts.length?table(['原始资料','资料期间','提取结果','用途 / 类型','操作'],artifacts.map(a=>{
    const d=a.data,canParse=!readonly()&&d.observed_period===scope().accounting_period_id&&['RECEIVED','FAILED'].includes(d.parse_status||'RECEIVED');
    const historical=typeof historicalSourceStatus==='function'?historicalSourceStatus(a):'';
    return `<tr><td class="filename">${esc(d.filename)}<p class="small muted">版本 ${a.version}</p></td><td class="mono">${esc(d.observed_period)}</td><td>${historical||statusBadge(d.parse_status||'RECEIVED')}${d.parse_errors?.length?`<p class="small">${d.parse_errors.map(esc).join('；')}</p>`:''}</td><td>${historical?'历史账表 · 独立于本期业务':esc(purposeLabel(d))}</td><td>${objectButton(a.object_id,'查看原件')}${typeof mappingButton==='function'?mappingButton(a):''}${typeof parsePlanButton==='function'?parsePlanButton(a):''}${canParse?`<br><button class="text" data-parse="${esc(a.object_id)}">选择类型并提取</button>`:''}</td></tr>`;
  })):'<p class="empty">此类尚未接收原件。</p>';
}
function renderArtifactsPage() {
  const r=readiness(),groups=[['all','全部资料',r.categories],['baseline','期初与历史',r.categories.filter(c=>c.id==='baseline')],
    ['business','本期业务',r.categories.filter(c=>!['baseline','unassigned'].includes(c.id))],['unassigned','归属待确认',r.categories.filter(c=>c.id==='unassigned')]];
  const ids=groups.find(g=>g[0]===state.filesFilter)[2].flatMap(c=>c.artifact_ids),files=activeArtifacts().filter(a=>ids.includes(a.object_id));
  const historyHelp=state.overview.historical_preparation?'历史账表由后台自动处理，结果保存在“历史账表核对详情”。若有差异会明确列出；只有最终采用期初时才需要人工确认。':'历史账表已保留，不等于期初基线已经核实。先查看原件；返回任务后按用途指定来源，再进行余额比较。未完成提取或格式尚未适配时，应先处理解析问题，不必重复上传同一文件。';
  const handoff=state.filesFilter==='business'&&state.filesReturn?.selector==='[data-action="history-next-work"]';
  const nextHelp=handoff?`<div class="goal"><b>${esc(historicalNextWork().label)}</b>${esc(historicalNextWork().reason)}</div>${!files.length?`<button class="secondary" data-action="upload" ${readonly()?'disabled':''}>添加本期资料</button>`:''}`:'';
return `<button class="text return-link" data-action="return-files">← 返回当前任务</button><section class="panel pad" id="receivedFiles" aria-labelledby="receivedTitle"><div class="row"><h2 id="receivedTitle" tabindex="-1">已接收资料清单</h2><span class="small muted">共 ${r.counts.files} 份原件</span></div><p class="small muted">原件已保存；接收、提取和核实是不同状态。</p><nav class="file-filters" aria-label="资料范围">${groups.map(([id,name,cats])=>`<button class="secondary" data-files-filter="${id}" aria-pressed="${id===state.filesFilter}">${name} ${cats.reduce((n,c)=>n+c.file_count,0)}</button>`).join('')}</nav>${state.filesFilter==='baseline'?`<div class="goal"><b>下一步：核对用途与解析结果</b>${historyHelp}</div>`:''}<p class="small muted">当前显示 ${files.length} 份</p>${nextHelp}${artifactTable(files)}</section>`;
}
function showArtifacts(filter,button) {
  const originView=state.view;
  state.filesReturn={scrollY:window.scrollY,stagesExpanded:$('stages')?.classList.contains('expanded'),selector:button?.id?`#${button.id}`:button?.dataset.action?`[data-action="${button.dataset.action}"]`:null};
  state.filesFilter=filter;state.view='artifacts';closeDialog();render();
  state.filesReturn.view=originView;
  $('receivedTitle').focus({preventScroll:true});window.scrollTo(0,0);
}
function renderCategory() {
  const r=readiness(),ids=state.category==='business'?['purchase','sales','bank','people']:[state.category];
  const cats=r.categories.filter(c=>ids.includes(c.id)),files=cats.flatMap(c=>c.artifact_ids),issues=cats.flatMap(c=>c.issues);
  let body=`<button class="text return-link" data-action="return-task">← 返回当前任务</button><h2>${esc(state.category==='business'?'本期业务资料':cats[0]?.name||'资料详情')}</h2>`;
  if(state.category==='baseline')body+=`<div class="goal"><b>用途</b>建立本期期初与上期结账的衔接。${state.overview.baseline_validation.status==='VALID'?'当前基线已核实有效。':'当前尚未完成有效期初核对。'}</div>`;
  if(state.category==='unassigned')body+='<div class="issue-banner">文件期间不等于业务用途。请核实资料是本期业务、历史参考，还是应另行提供的期初衔接资料；不能自动套用。</div>';
  body+=`<p class="muted small">${files.length} 份原件 · ${cats.reduce((n,c)=>n+c.record_count,0)} 条提取记录 · ${cats.reduce((n,c)=>n+c.verified_count,0)} 条业务校验通过</p>`;
  if(issues.length)body+=`<h3>需要核对的问题</h3>${issues.map(i=>`<div class="issue-row"><div><strong>${esc(i.title)}</strong><p>${esc(fileById(i.artifact_id)?.data.filename)} · 涉及 ${i.record_count} 条</p></div><button class="text" data-issue="${esc(i.id)}">查看依据</button></div>`).join('')}`;
  else body+='<p class="record-note">未检出提取字段问题，不代表业务完整或已经核实。</p>';
  const businessIssues=cats.flatMap(c=>c.business_issues||[]);
  if(businessIssues.length)body+=`<h3>业务归属与补证</h3>${businessIssues.map(b=>`<div class="issue-row"><div><strong>候选采购业务组 · ${esc(b.reason)}</strong><p>缺少 ${(b.missing_evidence||[]).map(label).map(esc).join('、')||'有效校验依据'}；${state.overview.groups.find(g=>g.object_id===b.group_id)?.data.member_fact_ids?.length||0} 条关联事实。候选分组不等于已核实业务。</p></div>${objectButton(b.group_id,'查看关联业务')}</div>`).join('')}<button class="text" data-action="upload" ${readonly()?'disabled':''}>补充业务证据</button>`;
  body+=`<h3>已有原件与提取结果</h3>${artifactTable(files.map(fileById))}`;
  if(state.category==='unassigned')body+=`<p class="record-note">另有 ${r.counts.period_exceptions} 条期间例外记录，仍归在其原始文件内。</p><button class="text" data-record-state="PERIOD_EXCEPTION">查看期间例外记录</button>`;
  return `<section class="panel category-detail">${body}</section>`;
}
function render() {
  if(!state.overview)return;
  const materialFocus=typeof materialCaptureFocus==='function'?materialCaptureFocus():null;
  const historicalFocus=typeof historicalPlanFocus==='function'?historicalPlanFocus():null;
  let html=renderContext();
  if(state.view==='artifacts')html+=renderArtifactsPage();
  else if(state.view==='accounts')html+=renderAccounts();
  else if(state.view==='mapping')html+=renderMapping();
  else if(state.view==='parse-plans')html+=renderParsePlans();
  else if(state.view==='materials')html+=renderMaterialWorkbench();
  else if(state.view==='historical')html+=renderHistoricalDetails();
  else if(state.view==='vouchers')html+=renderVoucherPage();
  else if(state.view==='history')html+='<button class="text return-link" data-action="return-current">← 返回本期办理</button><section class="panel pad" id="historyContent"><h2>往期数据与已归档凭证</h2><p>正在读取授权历史…</p></section>';
  else html+=renderProgress()+renderPrerequisite()+renderStructure()+`<div class="work-grid">${state.category?renderCategory():renderTask()}${renderResults()}</div><nav class="secondary-nav" aria-label="本期详情"><button class="text" data-action="artifacts">全部资料</button><button class="text" data-action="groups">业务对象与处理工具</button><button class="text" data-action="vouchers">本期凭证</button><button class="text" data-action="history">往期与归档</button><button class="text" data-action="upload" ${readonly()?'disabled':''}>补充资料</button><button class="text" data-action="refresh">刷新状态</button></nav>`;
  $('workspace').innerHTML=html;
  if(typeof installHistoricalActions==='function'&&state.view==='current') {
    const nav=document.querySelector('.secondary-nav');
    const job=state.overview.historical_preparation;
    if(nav&&!readonly()&&!['NEEDS_REVIEW','WAITING_INPUT'].includes(job?.status))nav.insertAdjacentHTML('beforeend','<button class="text" data-action="upload-history">补充历史账表</button>');
  }
  if(typeof restoreHistoricalPlanFocus==='function')restoreHistoricalPlanFocus(historicalFocus);
  if(typeof materialRestoreFocus==='function')materialRestoreFocus(materialFocus);
}
function openDialog(title,html) {
  if(!$('dialog').open)state.returnFocus=document.activeElement;
  $('dialogTitle').textContent=title;$('dialogBody').innerHTML=html;
  if(!$('dialog').open)$('dialog').showModal();
}
function closeDialog() {state.dialogSequence++;if($('dialog').open)$('dialog').close();if(state.returnFocus?.isConnected)state.returnFocus.focus({preventScroll:true});}
function recordTable(records) {
  return records.length?table(['事实 / 主要值','核实状态','来源与定位','问题','操作'],records.map(r=>`<tr><td>${esc(label(r.record_type))}<p class="mono small">${Object.entries(r.values).filter(([k])=>['invoice_no','transaction_date','payment_total','invoice_total','amount'].includes(k)).map(([k,v])=>`${esc(fieldLabels[k])} ${esc(v??'未提供')}`).join('<br>')||'详见提取值'}</p></td><td>${statusBadge(r.state)}</td><td class="filename">${esc(r.filename)}<p class="small mono">${esc(r.source_anchor?.region||`第 ${r.source_anchor?.row||'—'} 行`)}</p></td><td>${r.issues.map(esc).join('<br>')||'未发现提取字段问题；业务仍须核实'}</td><td>${objectButton(r.object_id,'核对原始值')}</td></tr>`)):'<p class="empty">当前没有此类记录。</p>';
}
function showRecords(records,title) {openDialog(title,`<p class="small muted">${records.length} 条记录 · 仅当前企业与期间</p>${recordTable(records)}`);}
function showIssue(id) {
  const issue=readiness().categories.flatMap(c=>c.issues).find(i=>i.id===id);if(!issue)return;
  openDialog('核对问题与来源',`<h3>${esc(issue.title)}</h3><div class="goal"><b>需要你做什么</b>核对下列原件位置和提取值。若原件缺失或有误，补充正确资料；不要用估算值或点击确认代替证据。</div>${recordTable(readiness().records.filter(r=>issue.record_ids.includes(r.object_id)))}<p class="record-note">本项完成条件：来源字段完整、期间归属有据，并通过后续确定性校验。</p><button class="secondary" data-action="upload" ${readonly()?'disabled':''}>补充原始资料</button>`);
}
async function showObject(id,version) {
  const epoch=state.epoch,sequence=++state.dialogSequence;
  openDialog('来源与核实依据','<p role="status">正在读取当前范围的对象…</p>');
  const result=await request('/api/v1/objects/detail',{scope:scope(),object_id:id,...(version?{version}:{})});
  if(epoch!==state.epoch||sequence!==state.dialogSequence||!$('dialog').open)return;
  const o=result.object,d=o.data;let body=`<div class="row"><h3>${esc(d.filename||d.business_identity||'对象与来源')}</h3>${statusBadge(o.status)}</div><p class="small muted">版本 ${o.version} · ${esc(o.created_at)} · ${esc(o.created_by)}</p>`;
  if(o.object_type==='SourceArtifact') {
    const historical=state.overview.historical_preparation?.data.sources.some(s=>s.artifact_id===id&&s.version===o.version);
    body+=`<div class="goal"><b>资料期间与用途</b>${esc(d.observed_period)} · ${esc(purposeLabel(d))}</div><p class="small">原件哈希 <span class="mono">${esc(d.sha256)}</span></p><a class="button secondary" href="/api/v1/artifacts/${encodeURIComponent(id)}/content?${new URLSearchParams(scope())}" download>下载原始文件</a>${historical?'<button class="text" data-action="historical-details">查看历史提取结果</button>':`<button class="text" data-file-records="${esc(id)}">查看提取记录</button>`}`;
  }
  if(o.object_type==='FactRecord') {
    const values=d.normalized_value||{};
    body+=`<div class="goal"><b>来源定位</b>${esc(fileById(d.source_artifact_id)?.data.filename||'来源原件')} · ${esc(d.source_anchor?.region||`第 ${d.source_anchor?.row||'—'} 行`)} ${objectButton(d.source_artifact_id,'查看原件')}</div>${table(['提取字段','当前提取值','字段来源'],Object.entries(values).map(([k,v])=>`<tr><td>${esc(fieldLabels[k]||'其他字段')} <span class="small muted">${esc(k)}</span></td><td>${esc(v==null?'未提供':typeof v==='object'?JSON.stringify(v):labels[v]||v)}</td><td class="mono small">${esc(d.field_sources?.[k]?.region||'详见原始定位')}</td></tr>`))}<details open><summary>原始值（未经改写）</summary><pre>${esc(JSON.stringify(d.original_value,null,2))}</pre></details>`;
  }
  if(o.object_type==='VoucherVersion')body+=voucherLines(o);
  if(o.object_type==='BaselineSnapshot')body+=`<div class="goal"><b>用途：本期账务衔接</b>核实人 ${esc(d.confirmed_by||'尚未核实')} · ${esc(d.decision_time||'')}</div>`;
  if(d.member_fact_ids?.length)body+=`<h3>来源事实</h3>${d.member_fact_ids.map(fid=>objectButton(fid,'查看事实')).join(' · ')}`;
  body+=`<details style="margin-top:16px"><summary>版本、关系与核实记录</summary><pre>${esc(JSON.stringify({data:d,relations:result.relations,audits:result.audits},null,2))}</pre></details>`;
  $('dialogBody').innerHTML=body;
}
async function uploadFile(file,purpose,observed,kind) {
  if(!file)throw new Error('请选择文件');if(file.size>16*1024*1024)throw new Error('文件超过 16MB，请拆分后上传');
  const selected=scope(),epoch=state.epoch,bytes=new Uint8Array(await file.arrayBuffer());let binary='';
  for(let i=0;i<bytes.length;i+=0x8000)binary+=String.fromCharCode(...bytes.subarray(i,i+0x8000));
  const artifact=await request('/api/v1/artifacts',{scope:selected,filename:file.name,content_base64:btoa(binary),observed_period:observed,source_purpose:purpose,mime_type:file.type||'application/octet-stream'});
  if(epoch!==state.epoch)return;
  notify('原件已保存（同内容复用既有原件），尚未完成核实。');
  if(kind&&!(Array.isArray(state.overview?.parse_plans)&&typeof parsePlanSupported==='function'&&parsePlanSupported(artifact,kind))&&observed===selected.accounting_period_id&&['RECEIVED','FAILED'].includes(artifact.data.parse_status||'RECEIVED')) {
    try{if(kind==='payroll'){await command('request_payroll_mapping',artifact.object_id,artifact.version,{},false);}else await command('parse_artifact',artifact.object_id,artifact.version,{document_kind:kind},false);}
    catch(error){await loadWorkbench();throw new Error(`原件已保留，但提取未完成：${error.message}`);}
  }
  return artifact;
}
function chooseBaselineFile(role) {if(readonly())return;state.uploadRole=role;$('baselineFile').value='';$('baselineFile').click();}
function openParseDialog(artifact){
  const selected=artifact.data.parse_options?.document_kind;
  if(Array.isArray(state.overview?.parse_plans)&&typeof parsePlanSupported==='function'&&parsePlanSupported(artifact))return openParsePlan(artifact);
  openDialog('选择资料类型并提取',`<form id="parseForm" class="stack" data-artifact="${esc(artifact.object_id)}"><p>${esc(artifact.data.filename)}</p><label>资料类型<select id="parseKind" ${selected?'disabled':''}>${Object.entries(kindLabels).map(([k,v])=>`<option value="${k}" ${k===selected?'selected':''}>${v}</option>`).join('')}</select></label><button class="primary" type="submit" ${readonly()?'disabled':''}>按所选类型提取</button></form>`);
}
function uploadDialog() {
  openDialog('补充原始资料',`<form id="uploadForm" class="stack"><p>原件只追加保存，资料不足不会自动消除。此操作写入当前测试账套，不是模拟上传。</p><label>文件<input id="uploadFile" type="file" required></label><div class="form-grid"><label>资料类型<select id="uploadKind">${Object.entries(kindLabels).map(([k,v])=>`<option value="${k}">${v}</option>`).join('')}</select></label><label>原件资料期间<input id="uploadPeriod" type="month" value="${esc(scope().accounting_period_id)}" required></label></div><p class="small muted">跨期资料单独保留，不能自动计入本期。期初余额请从当前期初核对任务添加。</p><button class="primary" type="submit" ${readonly()?'disabled':''}>保存并提取资料</button></form>`);
}
async function command(action,id,version,payload={},reload=true) {
  if(readonly())throw new Error('当前账号或期间只允许查看');
  const epoch=state.epoch;
  const signature=JSON.stringify([state.sessionEpoch,scope(),action,id,version,payload]);
  if(!state.operations.has(signature))state.operations.set(signature,`readiness-${crypto.randomUUID()}`);
  let result;
  try {result=await request('/api/v1/commands',{scope:scope(),action,target_id:id,target_version:version,
    idempotency_key:state.operations.get(signature),payload});
    if(result?.command?.status!=='SUCCEEDED'||!Object.hasOwn(result,'effect'))
      throw new Error('未取得完整操作结果，请重试核对；不会重复执行同一操作。');
    if(['save_historical_issue_plan','review_historical_issue_plan'].includes(action)&&
      (!result.effect?.object?.object_id||!Number.isInteger(result.effect.object.version)||!['SUBMITTED','UNAVAILABLE_RECORDED','REVIEWED','RETURNED'].includes(result.effect.object.status)))
      throw new Error('未取得完整处理记录，请重试核对；不会重复执行同一操作。');
    if(action==='verify_source_values'&&(!Array.isArray(result.effect?.objects)||result.effect.objects.length!==payload.records.length||result.effect.objects.some(o=>!o.object_id||o.status!=='VERIFIED')))
      throw new Error('未取得完整核实结果，请重试核对。');
    if(['defer_material_issue','revoke_source_verification'].includes(action)&&(!result.effect?.object?.object_id||result.effect.object.status!==(action==='defer_material_issue'?'DEFERRED':'REVOKED')))
      throw new Error('未取得完整处理记录，请重试核对。');
  }
  catch(error){if(error.status&&error.status<500)state.operations.delete(signature);throw error;}
  if(epoch!==state.epoch)return result;
  const extraction=result.effect?.artifact?.data;
  const failed=action==='parse_artifact'&&extraction?.parse_status==='FAILED';
  if(failed){
    if(reload){closeDialog();await loadWorkbench();}
    state.operations.delete(signature);
    throw new Error('资料提取失败：'+(extraction.parse_errors||result.effect.errors||['请检查资料类型与文件格式']).join('；'));
  }
  if(reload){state.candidate=null;closeDialog();await loadWorkbench();notify('操作已记录，当前状态已更新。');}
  state.operations.delete(signature);
  return result;
}
async function compareBaseline() {
  const epoch=state.epoch,selection={...state.sources};
  const result=await request('/api/v1/baseline/candidate',{scope:scope(),balance_artifact_id:selection.balance,close_artifact_id:selection.close});
  if(epoch!==state.epoch||JSON.stringify(selection)!==JSON.stringify(state.sources))return;
  state.candidate=result;render();notify(result.status==='READY_FOR_CONFIRMATION'?'逐行比较通过，请核对完整性后明确确认。':'余额核对仍有差异，请检查结果。',result.status!=='READY_FOR_CONFIRMATION');
}
function commandButton(action,o,text) {return `<button class="text" data-command="${action}" data-id="${esc(o.object_id)}" data-version="${o.version}" ${readonly()?'disabled':''}>${esc(text)}</button>`;}
function showGroups() {
  const d=state.overview;
  openDialog('业务对象与处理工具',`<p class="small muted">候选业务组并不表示已识别为真实完整业务；请核对成员和来源归属。</p>${d.groups.length?table(['业务组','状态','证据缺口','操作'],d.groups.map(g=>`<tr><td class="filename">${esc(g.data.business_identity||'候选业务组')}</td><td>${statusBadge(g.status)}</td><td>${(g.data.missing_evidence||[]).map(label).map(esc).join('、')||'须查看校验结果'}</td><td>${objectButton(g.object_id,'查看来源')}<br>${commandButton('reconcile_group',g,'运行确定性校验')}${g.status==='CANDIDATE'?'<br>'+commandButton('confirm_grouping',g,'核实业务归属'):''}${['READY','CONFIRMED'].includes(g.status)&&g.data.reconciliation_status==='PASS'?'<br>'+commandButton('generate_draft',g,'生成凭证草稿'):''}</td></tr>`)):'<p class="empty">尚未建立业务处理组。</p>'}<details style="margin-top:16px"><summary>建立采购处理组</summary><p class="small muted">只按真实业务关系选择事实，不能因为出现在同一文件就归为一组。</p><label>业务标识<input id="businessIdentity"></label>${table(['选择','事实类型','来源','状态'],(d.fact_summaries||[]).filter(f=>['INVOICE','PAYMENT','CONTRACT','STOCK_IN'].includes(f.record_type)).map(f=>`<tr><td><input type="checkbox" data-fact="${esc(f.object_id)}" aria-label="选择 ${esc(f.object_id)}" ${f.status==='PARSED'&&!readonly()?'':'disabled'}></td><td>${esc(label(f.record_type))}</td><td>${esc(fileById(f.source_artifact_id)?.data.filename)} · ${esc(f.source_anchor?.region)}</td><td>${statusBadge(f.status)}</td></tr>`))}<button class="secondary" data-action="create-group" ${readonly()?'disabled':''}>建立候选处理组</button></details>`);
}
async function showCard(id) {
  const epoch=state.epoch,sequence=++state.dialogSequence;
  openDialog('审阅候选规则','<p>正在读取建议与依据…</p>');
  const result=await request('/api/v1/objects/detail',{scope:scope(),object_id:id});
  if(epoch!==state.epoch||sequence!==state.dialogSequence||!$('dialog').open)return;
  const card=result.object,d=card.data,group=state.overview.groups.find(g=>g.object_id===d.group_id);
  const blocked=group&&['BLOCKED','SUSPENDED'].includes(group.status);
  const allowed=!readonly()&&['accountant','reviewer','admin'].includes(state.role)&&card.status==='PENDING'&&!blocked;
  $('dialogBody').innerHTML=`<div class="row"><h3>候选规则与适用业务</h3>${statusBadge(card.status)}</div><p>${esc(group?.data.business_identity||'关联业务组')}</p><div class="goal"><b>候选处理建议</b>${(d.suggested_rule||[]).map(rule=>`<p>借方科目：${esc(rule.debit_account||'未提供')} · 贷方科目：${esc(rule.credit_account||'未提供')}<br>${esc(rule.description||rule.reason||'具体内容见完整建议')}</p>`).join('')}</div><h3>来源依据</h3><div class="actions">${(d.evidence_ids||[]).map(e=>objectButton(e,'查看证据')).join('')}</div><details><summary>完整建议与影响范围</summary><pre>${esc(JSON.stringify({建议:d.suggested_rule,影响范围:d.impact_preview},null,2))}</pre></details>${blocked?'<div class="issue-banner red">关联业务尚有阻断，不能直接确认正式规则。请先补证并重新校验。</div>':''}<label class="check-label"><input id="ruleConfirmed" type="checkbox" ${allowed?'':'disabled'}>我已核对建议、来源及适用范围，同意在当前业务中采用该规则。</label><button class="primary" data-execute="approve_rule" data-id="${esc(id)}" data-version="${card.version}" disabled>确认采用此规则</button>${!allowed&&!blocked?'<p class="small muted">当前账号、期间或卡片状态不允许审批。</p>':''}`;
}
function voucherLines(voucher) {
  const lines=voucher.data.lines||[];
  return table(['会计科目','方向','金额'],lines.map(l=>`<tr><td>${esc(l.account_code||'')} ${esc(l.account_name||l.account||'科目缺失，不能确认')}</td><td>${esc(label(l.direction))}</td><td class="amount mono">${amount(l.amount)}</td></tr>`))+`<p class="record-note">借方合计 ${amount(voucher.data.debit_total)} · 贷方合计 ${amount(voucher.data.credit_total)}</p>`;
}
function renderVoucherPage() {
  const d=state.overview;
  return `<button class="text return-link" data-action="return-current">← 返回本期办理</button><section class="panel pad"><h2>本期全部凭证</h2><p class="small muted">${d.vouchers.length} 个版本 · 本地复核不等于外部入账</p>${d.vouchers.length?table(['版本','状态','借 / 贷合计','操作'],d.vouchers.map(v=>`<tr><td class="filename mono">${esc(v.object_id)} · v${v.version}</td><td>${statusBadge(v.status)}</td><td class="amount">${amount(v.data.debit_total)} / ${amount(v.data.credit_total)}</td><td>${objectButton(v.object_id,'查看分录')}${['DRAFT','REVISED'].includes(v.status)?'<br>'+commandButton('validate_draft',v,'复核凭证'):''}${v.status==='LOCALLY_CONFIRMED'&&d.groups.some(g=>g.object_id===v.data.group_id)?'<br>'+commandButton('release_delivery',d.groups.find(g=>g.object_id===v.data.group_id),'建立交付包'):''}</td></tr>`)):'<p class="empty">尚无凭证。未满足证据与校验条件时，不会生成正式凭证。</p>'}<h3 style="margin-top:20px">交付与外部回执</h3>${d.deliveries.length?table(['交付包','状态','操作'],d.deliveries.map(p=>`<tr><td class="filename mono">${esc(p.object_id)}</td><td>${statusBadge(p.status)}</td><td>${objectButton(p.object_id,'查看记录')}${p.status==='DELIVERABLE'?'<br>'+commandButton('export_package',p,'生成导出包'):''}</td></tr>`)):'<p class="empty">尚无交付包。</p>'}<p class="small muted">外部回执须以实际导入结果为依据，此页不提供模拟成功回执按钮。</p></section>`;
}
async function showHistory() {
  state.view='history';render();const epoch=state.epoch,sequence=++state.historySequence,selected=scopeKey(scope());
  const data=await request('/api/v1/history',{scope:scope()});if(epoch!==state.epoch||state.view!=='history'||sequence!==state.historySequence||selected!==scopeKey(scope()))return;
  const past=data.periods.filter(p=>p.scope.accounting_period_id<scope().accounting_period_id);
  $('historyContent').innerHTML=`<h2>往期数据</h2><p class="small muted">仅展示本账号有权查看的真实期间，不生成演示历史。</p>${past.length?table(['期间','资料','凭证','操作'],past.map(p=>`<tr><td>${esc(p.scope.accounting_period_id)}</td><td>${p.counts.source_artifacts}</td><td>${p.counts.facts} 条事实</td><td><button class="text" data-history-key="${esc(scopeKey(p.scope))}">查看该期</button></td></tr>`)):'<p class="empty">没有可查看的往期授权数据。</p>'}<h3>当前范围已归档凭证</h3>${data.archived_vouchers.length?table(['凭证版本','状态','操作'],data.archived_vouchers.map(a=>`<tr><td class="filename">${esc(a.voucher.object_id)} · v${a.voucher.version}</td><td>${statusBadge(a.package.status)}</td><td><button class="text" data-object="${esc(a.voucher.object_id)}" data-object-version="${a.voucher.version}">查看分录</button></td></tr>`)):'<p class="empty">当前范围尚无具有外部成功回执的凭证。</p>'}`;
}
function showModelRecords() {
  const m=readiness().model_coverage||{},maps=state.overview.payroll_mappings||[],mapStatus=j=>j.data?.reused_from?'复用已确认格式':({QUEUED:'等待识别',RUNNING:'识别中',REVIEW:'候选待核对',APPLIED:'已应用',FAILED:'识别失败',STALE:'原件已变化'}[j.status]||'状态待核对');
  openDialog('处理记录',`<p>业务建议调用、工资表格式识别和已确认格式复用分开记录；成功识别不等于人工核实或账务可用。</p><div class="goal"><b>业务建议调用</b>${m.real_successful_calls||0} 次真实成功调用，历史输入涉及 ${m.historical_fact_count||0} 条事实。${esc(m.note||'仅表示调用时的输入覆盖，不代表当前版本已核实')}。</div>${m.calls?.length?table(['调用任务','模型','结果','当次输入','依据'],m.calls.map(c=>`<tr><td>${esc(label(c.stage))}</td><td>${esc(c.model||'未记录')}</td><td>${statusBadge(c.status)}<p class="small">${c.mock===false?'真实调用':c.mock===true?'模拟调用':'调用方式未记录'}</p></td><td>${c.input_count} 条事实</td><td>${objectButton(c.object_id,'查看调用记录')}</td></tr>`)):'<p class="empty-proof">暂无业务建议调用记录。</p>'}${renderMaterialGuidanceRecords()}<h3>工资表格式识别</h3>${maps.length?table(['原件','处理方式','状态','记录'],maps.map(j=>`<tr><td class="filename">${esc(j.data?.filename||j.data?.artifact_id||'工资表')}</td><td>${esc(j.data?.reused_from?'复用已确认格式':j.data?.gateway?.model_version||'本地格式任务')}</td><td>${badge(mapStatus(j),j.status==='FAILED'||j.status==='STALE'?'red':j.status==='APPLIED'?'green':'yellow')}</td><td class="small">${j.data?.gateway?`${j.data.gateway.mock===false?'真实调用':'模拟调用'} · ${esc(j.data.gateway.prompt_version||'版本未记录')}`:'复用，不新增调用'}</td></tr>`)):'<p class="empty-proof">暂无工资表格式识别记录。</p>'}`);
}
function openSidebar() {$('sidebar').classList.add('open');$('scrim').classList.remove('hidden');$('main').inert=true;document.querySelector('.topbar').inert=true;$('sidebar').setAttribute('role','dialog');$('sidebar').setAttribute('aria-modal','true');$('search').focus();}
function closeSidebar() {const opened=$('sidebar').classList.contains('open');$('sidebar').classList.remove('open');$('scrim').classList.add('hidden');$('main').inert=false;document.querySelector('.topbar').inert=false;$('sidebar').removeAttribute('role');$('sidebar').removeAttribute('aria-modal');if(opened)$('openSidebar').focus({preventScroll:true});}

const actions = {
  stages:button=>{const expanded=$('stages').classList.toggle('expanded');button.setAttribute('aria-expanded',String(expanded));button.textContent=expanded?'收起阶段总览':'阶段总览';},
  'return-task':()=>{state.category=null;render();},'return-current':()=>{state.view='current';render();},
  'upload-baseline':()=>chooseBaselineFile(!state.sources.balance?'balance':'close'),
  'compare-baseline':compareBaseline,
  'confirm-baseline':async()=>{if(!$('baselineConfirmed')?.checked||state.candidate?.status!=='READY_FOR_CONFIRMATION')return;const b=state.overview.baseline;await command('confirm_baseline',b.object_id,b.version,{...state.candidate.confirmation_payload,completeness_confirmed:true});},
  upload:uploadDialog,artifacts:button=>showArtifacts('all',button),
  'baseline-files':button=>showArtifacts('baseline',button),
  'return-files':()=>{const origin=state.filesReturn;state.view=['historical','materials'].includes(origin?.view)?origin.view:'current';render();if(origin?.stagesExpanded)actions.stages(document.querySelector('[data-action="stages"]'));if(origin?.selector)document.querySelector(origin.selector)?.focus({preventScroll:true});window.scrollTo(0,origin?.scrollY||0);},
  records:showModelRecords,groups:showGroups,
  issues:()=>{if(typeof openMaterialWorkbench==='function'){openMaterialWorkbench();return;}const c=readiness().categories.find(c=>c.issues.length);if(c){state.category=c.id;closeDialog();render();}},
  blockers:()=>openDialog('补证清单',state.overview.blockers.map(b=>`<div class="issue-banner red"><strong>${esc(b.reason)}</strong><p>缺少 ${(b.missing_evidence||[]).map(label).map(esc).join('、')||'有效校验依据'}</p>${objectButton(b.group_id,'查看受影响业务')}</div>`).join('')+'<p class="small muted">请核实业务归属后补充相应资料。补证后须重新校验。</p><button class="secondary" data-action="upload">补充资料</button>'),
  cards:()=>openDialog('待审阅规则',state.overview.pending_confirmation_cards.map(c=>`<div class="source-slot">${statusBadge(c.status)} <button class="text" data-card="${esc(c.object_id)}">审阅建议、来源及影响范围</button></div>`).join('')),
  vouchers:()=>{state.view='vouchers';closeDialog();render();},history:showHistory,
  refresh:async()=>{state.candidate=null;await loadWorkbench();notify('状态已刷新 · '+new Date().toLocaleTimeString('zh-CN'));},
  'create-group':async()=>{const ids=[...document.querySelectorAll('[data-fact]:checked')].map(i=>i.dataset.fact),identity=$('businessIdentity').value.trim();if(!ids.length||!identity)throw new Error('请填写业务标识并选择对应事实');await request('/api/v1/business/procurement',{scope:scope(),fact_ids:ids,business_identity:identity,idempotency_key:`readiness-group-${identity}`});closeDialog();await loadWorkbench();notify('候选业务组已建立，请核对来源与校验结果。');}
};
document.addEventListener('click',event=>{
  const button=event.target.closest('button');if(!button||button.disabled||state.busy)return;
  const d=button.dataset;
  const perform=async()=>{
    if(d.scope!==undefined)return selectScope(Number(d.scope));
    if(d.filesFilter){state.filesFilter=d.filesFilter;render();document.querySelector(`[data-files-filter="${d.filesFilter}"]`).focus({preventScroll:true});return;}
    if(d.category){state.category=state.category===d.category?null:d.category;return render();}
    if(d.recordState)return showRecords(readiness().records.filter(r=>r.state===d.recordState),label(d.recordState));
    if(d.fileRecords)return showRecords(readiness().records.filter(r=>r.source_artifact_id===d.fileRecords),'原件提取记录');
    if(d.issue)return showIssue(d.issue);
    if(d.card)return showCard(d.card);
    if(d.object)return showObject(d.object,d.objectVersion?Number(d.objectVersion):undefined);
    if(d.uploadRole)return chooseBaselineFile(d.uploadRole);
    if(d.historyKey){const index=state.scopes.findIndex(i=>scopeKey(i.scope)===d.historyKey);if(index>=0)return selectScope(index);}
    if(d.parse)return openParseDialog(fileById(d.parse));
    if(d.command)return openDialog('核对后执行',`<p>操作：${esc(button.textContent)}</p><div class="goal"><b>请先核对来源与适用范围</b>此操作将通过服务端权限、版本和业务门禁。失败时不会按完成处理。</div><button class="primary" data-execute="${esc(d.command)}" data-id="${esc(d.id)}" data-version="${d.version}">确认执行</button>`);
    if(d.execute){
      if(d.execute==='approve_rule'&&!$('ruleConfirmed')?.checked)return;
      if(d.execute==='validate_draft'){
        const v=state.overview.vouchers.find(v=>v.object_id===d.id);
        if(!v?.data.lines?.length||v.data.lines.some(l=>!(l.account||l.account_name)))throw new Error('凭证科目缺失，不能确认复核');
      }
      return command(d.execute,d.id,Number(d.version));
    }
    if(d.action)return actions[d.action]?.(button);
  };
  const writing=d.execute||['compare-baseline','confirm-baseline','confirm-historical','retry-historical','select-historical','create-group','refresh','save-history-plan','review-history-plan'].includes(d.action);
  if(writing)exclusive(perform);else perform().catch(error=>notify(error.message,true));
});
document.addEventListener('change',event=>{
  if(event.target.dataset.historyConfirm)document.querySelector('[data-action="confirm-historical"]').disabled=readonly()||[...document.querySelectorAll('[data-history-confirm]')].some(n=>!n.checked);
  if(event.target.dataset.sourceRole){state.sources[event.target.dataset.sourceRole]=event.target.value;state.candidate=null;render();}
  if(event.target.id==='baselineConfirmed')document.querySelector('[data-action="confirm-baseline"]').disabled=!event.target.checked||readonly();
  if(event.target.id==='ruleConfirmed')document.querySelector('[data-execute="approve_rule"]').disabled=!event.target.checked||readonly();
});
$('baselineFile').addEventListener('change',()=>exclusive(async()=>{
  if(!$('baselineFile').files.length)return;const role=state.uploadRole;
  if(role==='history') {
    const artifact=await uploadFile($('baselineFile').files[0],'historical_reference',previousPeriod(scope().accounting_period_id));
    if(artifact){state.view='current';state.category=null;closeDialog();await loadWorkbench();notify('历史原件已保存，后台将自动核对。若已有多个版本，请在当前任务中选择来源。');document.querySelector('#currentTask .primary')?.focus();}
    return;
  }
  const artifact=await uploadFile($('baselineFile').files[0],role==='balance'?'opening_balance':'prior_close',previousPeriod(scope().accounting_period_id));
  if(!artifact)return;state.sources[role]=artifact.object_id;state.candidate=null;await loadWorkbench();
  notify('期初核对原件已保存，尚未核实。请补齐另一项来源或生成余额核对结果。');
}));
document.addEventListener('submit',event=>{
  if(!['loginForm','uploadForm','parseForm'].includes(event.target.id))return;
  event.preventDefault();const form=event.target;
  exclusive(async()=>{
    if(form.id==='loginForm') {state.sessionEpoch++;state.portfolioSequence++;await request('/api/v1/auth/login',{username:$('username').value,password:$('password').value});$('password').value='';await loadPortfolio();closeSidebar();return;}
    if(form.id==='uploadForm'){const materialTask=state.view==='materials'&&materialState().screen==='detail'?currentMaterialTask():null,materialGroup=materialState().group,uploadOriginView=state.view;const kind=$('uploadKind').value,artifact=await uploadFile($('uploadFile').files[0],'business',$('uploadPeriod').value,kind);if(artifact){closeDialog();await loadWorkbench();if(materialTask&&materialDetailStillOpen(materialGroup,materialTask.id))materialSupplementReceived(materialTask.id,artifact);if(Array.isArray(state.overview?.parse_plans)&&typeof parsePlanSupported==='function'&&parsePlanSupported(fileById(artifact.object_id),kind)&&artifact.data.observed_period===scope().accounting_period_id){if(state.view===uploadOriginView&&(!materialTask||materialDetailStillOpen(materialGroup,materialTask.id)))await openParsePlan(fileById(artifact.object_id),kind);return;}if(kind==='payroll'){if(state.view!==uploadOriginView||(materialTask&&!materialDetailStillOpen(materialGroup,materialTask.id))){notify('补充原件和格式识别任务已保存，可从资料入口查看。');return;}await openMapping(fileById(artifact.object_id));}}return;}
    const artifact=fileById(form.dataset.artifact),kind=$('parseKind').value;if(Array.isArray(state.overview?.parse_plans)&&typeof parsePlanSupported==='function'&&parsePlanSupported(artifact,kind)){await openParsePlan(artifact,kind);return;}if(kind==='payroll'){await openMapping(artifact);return;}await command('parse_artifact',artifact.object_id,artifact.version,artifact.data.parse_options||{document_kind:kind});
  });
});
$('search').addEventListener('input',renderScopes);
$('logout').addEventListener('click',()=>exclusive(async()=>{state.sessionEpoch++;state.portfolioSequence++;await request('/api/v1/auth/logout',null,'POST');clearSession();notify('已退出，页面中的企业资料已清除。');}));
$('closeDialog').addEventListener('click',closeDialog);
$('dialog').addEventListener('cancel',()=>{state.dialogSequence++;});
$('openSidebar').addEventListener('click',openSidebar);$('closeSidebar').addEventListener('click',closeSidebar);$('scrim').addEventListener('click',closeSidebar);
document.addEventListener('keydown',event=>{
  if(!$('sidebar').classList.contains('open'))return;
  if(event.key==='Escape')closeSidebar();
  if(event.key==='Tab') {const nodes=[...$('sidebar').querySelectorAll('button,input')].filter(e=>!e.disabled&&e.getClientRects().length),first=nodes[0],last=nodes.at(-1);if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}}
});
if(typeof installHistoricalActions==='function')installHistoricalActions();
if(typeof installMaterialActions==='function')installMaterialActions();
if(typeof installBillActions==='function')installBillActions();
if(typeof installInvoiceAmountActions==='function')installInvoiceAmountActions();
if(typeof installMappingActions==='function')installMappingActions();
if(typeof installBankActions==='function')installBankActions();
if(typeof installParsePlanActions==='function')installParsePlanActions();
if(location.protocol==='file:'){
  if(typeof location.replace==='function')location.replace(OPERATOR_HTTP_ENTRY);
  else notify('真实工作台需要登录服务，请通过当前 Staging 服务地址打开。',true);
}
else loadPortfolio().catch(error=>{if(error.status!==401)notify(error.message,true);});

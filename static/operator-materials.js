'use strict';
const materialUI={key:'',selected:'',filter:'all',page:0,viewMode:'issues',screen:'list',group:null,listOrigin:null,feedback:'',drafts:new Map(),skipped:new Set()};
function resetMaterialState(){materialUI.key='';materialUI.selected='';materialUI.filter='all';materialUI.page=0;materialUI.viewMode='issues';materialUI.drafts.clear();materialUI.skipped.clear();}
function materialState(){
  const key=JSON.stringify([state.user?.user_id,scopeKey(scope())]);
  if(materialUI.key!==key){materialUI.key=key;materialUI.selected=storage('finwise.material.task.'+key)||'';materialUI.filter='all';materialUI.viewMode=storage('finwise.material.mode.'+key)||'issues';materialUI.page=0;materialUI.drafts.clear();materialUI.skipped.clear();restoreMaterialNavigation(materialUI);}
  return materialUI;
}
function materialCanWrite(){return !readonly()&&['operator','accountant','admin'].includes(state.role);}
function materialSystemTask(t){return !!t?.triage&&(t.triage.version!=='issue-triage-v1'||t.triage.route!=='HUMAN');}
function materialRecordedOpinion(t){return (Array.isArray(t?.material_opinions)?t.material_opinions:[]).find(o=>o?.valid===true&&(o.status==='SAVED_NOT_EXECUTED'||o.data?.status==='SAVED_NOT_EXECUTED'||typeof o.text==='string'||typeof o.data?.text==='string'))||null;}
function materialHumanIssueTasks(){return (state.overview.material_review?.tasks||[]).filter(t=>t.kind!=='VERIFY'&&!t.deferred&&!materialSystemTask(t));}
function materialTasks(includeSkipped=false){
  const ui=materialState(),m=state.overview.material_review,records=m.records||[];
  return m.tasks.filter(t=>{
    const opinion=!!materialRecordedOpinion(t);
    if(ui.filter==='deferred')return t.deferred;
    if(t.deferred||(!includeSkipped&&ui.skipped.has(t.id)))return false;
    if(ui.filter==='VERIFY')return t.kind==='VERIFY';
    if(ui.filter==='system')return t.kind!=='VERIFY'&&materialSystemTask(t);
    if(ui.filter==='period')return t.kind!=='VERIFY'&&t.record_ids.some(id=>records.find(r=>r.object_id===id)?.state==='PERIOD_EXCEPTION');
    if(ui.filter==='issues')return t.kind!=='VERIFY';
    if(ui.filter==='selected')return t.kind!=='VERIFY'&&!materialSystemTask(t)&&opinion;
    if(materialSystemTask(t))return false;
    return t.kind!=='VERIFY'&&!opinion;
  });
}
function currentMaterialTask(){const ui=materialState();if(ui.screen==='detail')return state.overview.material_review.tasks.find(t=>t.id===ui.selected);if(ui.screen==='summary')return undefined;const tasks=materialTasks();return tasks.find(t=>t.id===ui.selected)||tasks[0];}
function materialDraft(t){const ui=materialState();if(!ui.drafts.has(t.id)){const saved=materialStoredDraft(ui.key,t.id);ui.drafts.set(t.id,{note:typeof saved?.note==='string'?saved.note:'',reason:typeof saved?.reason==='string'?saved.reason:'',selected:new Set(),defer:saved?.defer===true,resume:saved?.resume===true,bill:saved?.bill&&typeof saved.bill==='object'?saved.bill:null});}return ui.drafts.get(t.id);}
function materialIssueGroups(){
  const groups=new Map();
  for(const task of materialTasks(true).filter(t=>t.kind!=='VERIFY')){
    const key=`${task.kind}::${task.reason}::${materialSystemTask(task)?'SYSTEM':'HUMAN'}`;
    if(!groups.has(key))groups.set(key,{key,title:task.triage?.title||task.title,reason:task.reason,tasks:[],fileIds:new Set(),recordIds:new Set()});
    const group=groups.get(key);group.tasks.push(task);group.fileIds.add(task.artifact_id);task.record_ids.forEach(id=>group.recordIds.add(id));
  }
  return [...groups.values()];
}
function renderMaterialIssueGroups(){
  const ui=materialState(),groups=materialIssueGroups();
  if(!groups.length)return '';
  return `<section class="mat-issue-groups" aria-labelledby="materialListTitle"><div class="row"><h3 id="materialListTitle" tabindex="-1">按问题查看</h3><span class="small muted">${groups.length} 类问题</span></div>${groups.map(g=>{
    const first=g.tasks.find(t=>!ui.skipped.has(t.id))||g.tasks[0];
    const selected=g.tasks.filter(materialRecordedOpinion).length,pending=g.tasks.length-selected,status=[pending?`${pending} 项待处理`:'',selected?`${selected} 项已选择处理方式`:''].filter(Boolean).join(' · ');
    return `<article class="mat-issue-group"><div><strong>${esc(g.title)}</strong><p class="small muted">${status} · ${g.fileIds.size} 份原件 · ${g.recordIds.size} 条记录</p><p class="small">${esc(g.tasks.map(t=>t.filename).filter((v,i,a)=>a.indexOf(v)===i).join('、'))}</p></div><button class="text" data-action="material-select-group" data-task="${esc(first?.id||'')}">${selected===g.tasks.length?'查看已选方案':first?.deferred?'查看处理记录':'进入处理'} →</button></article>`;
  }).join('')}</section>`;
}
const materialFieldLabels={employer_housing_fund:'单位公积金',employee_housing_fund:'个人公积金',invoice_status:'发票状态',payment_total:'付款金额',transaction_date:'交易日期',transaction_id:'交易流水号',balance:'账户余额',bank_account_ref:'本方账户',invoice_no:'发票号码',date:'业务日期',invoice_date:'开票日期',tax_amount:'税额',invoice_total:'价税合计',net_amount:'不含税金额',period:'业务期间',aggregation_level:'汇总层级',insurance_type:'险种',employer_amount:'单位应缴',employee_amount:'个人应缴',total:'合计',employer_base:'单位基数',employee_base:'个人基数',people_count:'人数',payment_status:'缴费状态',actual_salary:'实发工资',basic_salary:'基本工资',person_name:'姓名',person_id:'个人编号',period_ref:'费款所属期',employee_social:'个人社保',employer_social:'单位社保',housing_fund:'公积金',acceptance_no:'票据包号',sub_range:'子票区间',issue_date:'出票日期',maturity_date:'到期日期',status:'票据状态',issuer:'出票人',payee:'收款人',endorser:'背书人',endorsee:'被背书人',register_kind:'资料性质',receipt_total:'收款金额',summary:'摘要',currency:'币种',bank_account_origin:'账户来源',start_period:'起始期间',end_period:'截止期间',seller_name:'销售方',buyer_name:'购买方',seller_tax_id:'销方识别号',buyer_tax_id:'购方识别号',counterparty:'对方名称',counterparty_account:'对方账户',note:'附言',base:'缴费基数',arrival_date:'到账日期',acceptance_type:'票据类型',transaction_type:'业务类型',account:'账号',entry_date:'入账日期',income:'收入',expense:'支出',tax:'税额'};
materialFieldLabels.bank_name='所属银行';
function materialValue(v){return esc(({UNIT:'单位汇总（不与人员明细相加）',endorsement:'背书记录',bill_register:'票据清单（业务角色待确认）',MANUAL_PARSE_OPTION:'人工指定，非原件提取',CNY:'人民币'})[v]||v);}
function materialComparison(r,selectable=false){
  const o=r.original_value||{},raw=(o.headers||[]).map((h,n)=>[h,o.values?.[n]]).filter(([h,v])=>h&&v!==null&&v!==undefined&&v!=='');
  const rows=r.comparison||Object.entries(r.values).filter(([k,v])=>v!=null&&!k.endsWith('_derivation')).map(([field,value])=>({field,value,state:'UNLOCATED'}));
  const labels={DIRECT_MATCH:'读取一致',NORMALIZED_MATCH:'格式规范化后一致',DIFFERENT:'需要核对差异',DERIVED:'由原始字段计算',AMBIGUOUS:'字段含义待确认',UNLOCATED:'查看取值依据',MISSING:'原表未提供'};
  const payroll=r.record_type==='PAYROLL';
  return `<article class="mat-record"><div class="row"><h4>${esc(r.values.person_name||r.values.invoice_no||r.filename)} · ${esc(r.source_anchor?.region||'查看来源定位')}</h4>${objectButton(r.object_id,'查看完整来源')}</div>${payroll?'<p class="small muted">这里只核对读取与字段归类，不代表工资计算正确、已发放或账务可用。</p>':''}<div class="table-wrap mat-comparison" tabindex="0" aria-label="原件与提取值逐字段对照"><table><thead><tr><th>字段</th><th>原件数据</th><th>提取结果</th><th>系统检查</th></tr></thead><tbody>${rows.map(x=>`<tr class="${x.state==='DIFFERENT'?'mat-difference':''}"><th scope="row">${esc(materialFieldLabels[x.field]||fieldLabels[x.field]||(x.field.startsWith('unmapped_')?'未归类列':'来源属性'))}${x.source_label?`<small>原列：${esc(x.source_label)}</small>`:''}</th><td>${x.source_value==null?'—':esc(x.source_value)}</td><td>${x.value==null?(x.state==='AMBIGUOUS'?'尚未确定':x.state==='DIFFERENT'?'无效原值':'未提供'):materialValue(x.value)}</td><td>${labels[x.state]||'查看取值依据'}${x.region?`<small>${esc(x.region)}</small>`:''}</td></tr>`).join('')}</tbody></table></div>${r.values.tax_rate===null&&['INVOICE','SALES_INVOICE'].includes(r.record_type)?'<p class="small muted">税额保留原值；未提供税率不等于税额错误。涉及税率的后续账务校验仍需独立依据。</p>':''}<details class="mat-raw"><summary>查看原始行全部字段（含未用于本次提取的字段）</summary><dl>${raw.map(([h,v])=>`<dt>${esc(h)}</dt><dd>${esc(v)}</dd>`).join('')||`<dd>${esc(o.raw_text||'请查看完整来源')}</dd>`}</dl></details>${r.issues.length?`<p class="issue-banner">${r.issues.map(i=>esc(i.replace(/^([^：]+)：/,(_,key)=>(materialFieldLabels[key]||key)+'：'))).join('；')}</p>`:''}${selectable?`<label class="mat-checkbox"><input type="checkbox" data-material-record="${esc(r.object_id)}" ${materialDraft(currentMaterialTask()).selected.has(r.object_id)?'checked':''} ${materialCanWrite()?'':'disabled'}>已核对本条字段含义、提取值及所属期间</label>`:''}${r.period_assignment?.valid?`<p class="record-note">已确认归属 ${esc(r.period_assignment.data?.target_period)}；此处其他问题仍保留，不代表原件核实或账务可用。</p>`:''}${r.verification?`<p class="small">核实人 ${esc(r.verification.data.verified_by)} · ${esc(r.verification.data.verified_at)}${r.verification.data.note?` · ${esc(r.verification.data.note)}`:''}</p><button class="text" data-action="material-revoke" data-check="${esc(r.verification.object_id)}" ${materialCanWrite()?'':'disabled'}>撤销本条资料核实</button>`:''}</article>`;
}
function renderMaterialTask(){
  const ui=materialState(),m=state.overview.material_review,t=currentMaterialTask();
  if(ui.filter==='bank-periods')return typeof renderBankPeriods==='function'?renderBankPeriods():'<p>跨期办理组件尚未加载。</p>';
  if(ui.filter==='other-period'){
    const all=m.records.filter(r=>r.state==='OTHER_PERIOD');ui.page=Math.min(ui.page,Math.max(0,Math.ceil(all.length/5)-1));
    return '<section class="panel pad"><h3 id="materialTaskTitle" tabindex="-1">已确认其他期间归属 · '+all.length+' 条</h3><p>不计入本期流水发生额；不是原件核实、目标期间已接续或账务可用。</p><button type="button" class="secondary" data-action="material-filter" data-filter="bank-periods">查看归属及接续记录</button>'+all.slice(ui.page*5,ui.page*5+5).map(r=>materialComparison(r)).join('')+materialPager(all.length)+'</section>';
  }
  if(ui.filter==='results')return renderMaterialResults();
  if(ui.filter==='usable')return renderMaterialUsable();
  if(!t&&ui.filter==='system')return '<section class="panel pad"><h3>当前没有系统待检查事项</h3><p>这不代表人工待办或账务门禁已通过。</p><button type="button" class="secondary" data-action="material-filter" data-filter="all">查看人工待办</button></section>';
  if(ui.filter==='verified'){
    const all=m.records.filter(r=>r.state==='SOURCE_VERIFIED');ui.page=Math.min(ui.page,Math.max(0,Math.ceil(all.length/5)-1));const page=all.slice(ui.page*5,ui.page*5+5);
    return `<section class="panel pad"><h3 id="materialTaskTitle" tabindex="-1">资料已核实 · ${all.length} 条</h3><p>原件与提取值已核对，不等于账务可用。</p>${page.map(r=>materialComparison(r)).join('')||'<p>尚无人工核实记录；提取结果已保留，可从待核实事项开始。</p>'}${materialPager(all.length)}</section>`;
  }
  if(!t)return `<section class="panel pad"><h3 id="materialTaskTitle" tabindex="-1">${ui.filter==='selected'?'当前没有已选择处理方式的事项':m.counts.files?'本轮暂无其他待处理事项':'接收本期资料'}</h3><p>${ui.filter==='selected'?'已提交的处理意见会保留在“已选择处理方式”中；它们尚未执行，也不会直接变成账务可用。':m.counts.files?`系统提取检查通过 ${m.counts.system_checked??m.counts.awaiting_verification+m.counts.source_verified} 条；人工已核实 ${m.counts.source_verified} 条。${m.counts.deferred?`另有 ${m.counts.deferred} 项等待补充，已保留原因。`:''}历史期初与业务门禁继续保留。`:'本期尚无业务原件，请添加发票、银行与票据或薪酬税费资料。'}</p>${m.counts.files?`<button class="secondary" data-action="material-filter" data-filter="results">查看已有成果</button>${ui.skipped.size?'<button class="text" data-action="material-resume">继续查看暂未处理的事项</button>':''}`:primary('upload','添加本期资料',!materialCanWrite())}</section>`;
  ui.selected=t.id;storage('finwise.material.task.'+ui.key,t.id);
  return renderDecisionTask(t);
}

function renderMaterialUsable(){
  const results=state.overview.data_readiness?.usable_results||[];
  return `<section class="panel pad"><h3 id="materialTaskTitle" tabindex="-1">账务可用成果</h3><p class="muted">这里只展示原有基线、业务校验和凭证门禁实际形成的成果；资料提取检查或人工核实不会直接变成账务可用。</p>${results.length?results.map(p=>`<article class="proof"><div class="row"><h4>${esc(p.title)}</h4>${badge('可用','green')}</div><p>${esc(p.use)}</p>${p.confirmed_by?`<p class="small muted">核实人 ${esc(p.confirmed_by)} · ${esc(p.confirmed_at||'详见记录')}</p>`:''}${objectButton(p.object_id,'查看依据')}</article>`).join(''):'<p class="empty-proof">当前没有满足账务可用条件的成果。期初、业务校验或证据门禁未通过时，这里不会显示可用结果。</p>'}<button class="text" data-action="material-filter" data-filter="results">查看全部资料成果</button></section>`;
}
function renderMaterialResults(){
  const m=state.overview.material_review,c=m.counts,files=[...new Set(m.records.map(r=>r.source_artifact_id))];
  return `<section class="panel pad"><h3 id="materialTaskTitle" tabindex="-1">已有成果</h3><p class="muted">系统检查与人工核实分别留痕；账务可用仍由基线、业务与证据校验决定。</p><div class="mat-result-summary"><div><strong>${c.system_checked??c.awaiting_verification+c.source_verified} 条</strong><span>系统提取检查通过</span><small>未检出提取问题，不代表人工核实</small></div><div><strong>${c.source_verified} 条</strong><span>人工已核实</span><button class="text" data-action="material-filter" data-filter="verified">查看核实记录</button></div><div><strong>${c.accounting_usable} 条</strong><span>账务可用</span><small>业务及基线校验通过</small></div></div><div class="table-wrap"><table><thead><tr><th>资料</th><th>提取检查通过</th><th>人工已核实</th><th>查看与核实</th></tr></thead><tbody>${files.map(id=>{const records=m.records.filter(r=>r.source_artifact_id===id),passed=records.filter(r=>['SOURCE_VERIFIED','AWAITING_VERIFICATION'].includes(r.state)),task=m.tasks.find(t=>t.artifact_id===id&&t.kind==='VERIFY');return `<tr><td>${esc(records[0].filename)}</td><td>${passed.length} / ${records.length} 条</td><td>${passed.filter(r=>r.state==='SOURCE_VERIFIED').length} 条</td><td>${task?`<button class="text" data-action="material-filter" data-filter="VERIFY" data-task="${esc(task.id)}">查看提取值并核实</button>`:objectButton(id,'查看原件')}${typeof mappingButton==='function'?mappingButton(fileById(id)):''}</td></tr>`;}).join('')||'<tr><td colspan="4">暂无已提取资料</td></tr>'}</tbody></table></div></section>`;
}
function materialPager(count){const ui=materialState();return count>5?`<nav class="mat-pager"><button class="secondary" data-action="material-page" data-page="${ui.page-1}" ${ui.page===0?'disabled':''}>上一页</button><span>第 ${ui.page+1} / ${Math.ceil(count/5)} 页 · ${count} 条</span><button class="secondary" data-action="material-page" data-page="${ui.page+1}" ${(ui.page+1)*5>=count?'disabled':''}>下一页</button></nav>`:'';}
function renderMaterialWorkbench(){
  if(typeof scheduleProblemReviewPoll==='function')scheduleProblemReviewPoll();
  const m=state.overview.material_review;
  if(!m)return '<section class="panel pad">办理服务尚未更新，请刷新。</section>';
  const c=m.counts,ui=materialState(),history=historicalIssueFlow(),month=Number(scope().accounting_period_id.slice(-2));
  if(ui.screen==='detail')return renderMaterialDetail();
  if(ui.screen==='summary')return renderMaterialGroupResult();
  const opinionTasks=materialHumanIssueTasks().filter(materialRecordedOpinion),pendingHumanTasks=materialHumanIssueTasks().filter(t=>!materialRecordedOpinion(t)),opinionCount=opinionTasks.length,issues=pendingHumanTasks.length;
  const isResult=['results','usable','VERIFY','verified','bank-periods','other-period'].includes(ui.filter),allIssueCount=materialHumanIssueTasks().length;
  const systemIssues=c.system_issue_tasks??m.tasks.filter(t=>t.kind!=='VERIFY'&&!t.deferred&&materialSystemTask(t)).length;
  const current=materialTasks(true)[0],tabs=[['all',`待人工处理 ${issues} 项`],['selected',`已选择处理方式 ${opinionCount} 项`],['system',`系统待检查 ${systemIssues} 项`],['issues',`全部问题 ${allIssueCount} 项`],['results','已有成果']];
  return `<div id="materialWorkbench"><button class="text return-link" data-action="return-current">← 返回期间工作台</button>
  <section class="panel pad mat-history"><div class="row"><strong>历史处理交接</strong><button class="text" data-action="historical-details">查看历史处理记录</button></div><p>${history.done?`${history.count} 项处理意见已记录，其中 ${history.plans.filter(p=>p?.status==='UNAVAILABLE_RECORDED').length} 项暂无法补充。`:'历史资料仍有未完成的核对事项。'}${state.overview.baseline_validation.status==='VALID'?'期初已通过原有校验。':'期初余额仍待核实，不能据此放行账务。'}</p></section>
  <section class="panel pad mat-overview"><div class="row"><h2 tabindex="-1">${month}月资料概览</h2><span>${c.files} 份本期原件 · ${c.records} 条提取记录</span></div>
  <p class="small muted">已提取 ${c.file_states.extracted||0} 份${c.file_states.failed?` · 识别失败 ${c.file_states.failed} 份`:''}${c.file_states.pending?` · 待识别 ${c.file_states.pending} 份`:''}；另有历史 ${readiness().categories[0].file_count} 份、归属待确认 ${c.unassigned_files} 份。</p>
  <div class="mat-categories">${m.categories.map(cat=>`<div><strong>${esc(cat.name)}</strong><p>${cat.file_count} 份资料 · ${cat.record_count} 条记录</p><small>需核对 ${m.records.filter(r=>r.category_id===cat.id&&['NEEDS_REVIEW','PERIOD_EXCEPTION'].includes(r.state)).length} 条</small></div>`).join('')}</div>
  <div class="mat-overview-status"><span>系统提取检查通过 <b>${c.system_checked??c.awaiting_verification+c.source_verified}</b> 条</span><span>需核对问题 <b>${c.needs_review+c.period_exceptions}</b> 条</span>${opinionCount?`<span>已选择处理方式 <b>${opinionCount}</b> 项</span>`:''}${c.invoice_amount_confirmed?`<span>红字／零金额已处理 <b>${c.invoice_amount_confirmed}</b> 条</span>`:''}${c.bill_confirmed?`<span>票据人工补充确认 <b>${c.bill_confirmed}</b> 条（独立口径）</span>`:''}${c.deferred?`<span>已记录待补 <b>${c.deferred}</b> 项</span>`:''}</div>
  <details class="small muted mat-method"><summary>查看统计口径</summary>记录数去重：系统提取检查通过 ${c.awaiting_verification+c.source_verified} 条（其中人工核实 ${c.source_verified} 条）＋字段问题 ${c.needs_review} 条＋期间问题 ${c.period_exceptions} 条＋人工归属确认且无剩余资料问题 ${c.business_confirmed||0} 条＋金额核对已处理且无剩余资料问题 ${c.issue_confirmed||0} 条＋其他期间归属 ${c.other_period||0} 条＝${c.records} 条。任务按原件与问题聚合，不能与记录数相加。账务可用 ${c.accounting_usable} 条单独统计。明确补证缺口 ${c.supplement_issues} 项；其他问题待核对后判定。</details></section>
  ${typeof renderProblemReviewOverview==='function'?renderProblemReviewOverview():''}
  ${typeof renderMaterialGuidanceOverview==='function'?renderMaterialGuidanceOverview():''}
  ${state.overview.bank_periods?'<section class="panel pad"><h3>跨期流水交接</h3><p>本期已确认其他期间归属 '+(state.overview.bank_periods.counts?.confirmed_other_period||0)+' 条（含仍有其他问题的记录）；其中无剩余资料问题 '+(c.other_period||0)+' 条。转入来源引用独立展示，不计作本期提取事实、原件核实或账务可用。</p><button type="button" class="secondary" data-action="material-filter" data-filter="bank-periods">查看转出与接续</button><button type="button" class="text" data-action="material-filter" data-filter="other-period">查看其他期间归属记录</button></section>':''}
  <nav class="mat-filters" aria-label="资料办理导航">${tabs.map(([id,text])=>`<button class="secondary" data-action="material-filter" data-filter="${id}" aria-pressed="${id==='results'?['results','usable','verified'].includes(ui.filter):id==='system'?ui.filter==='system':id==='issues'?['issues','period'].includes(ui.filter):id==='selected'?ui.filter==='selected':['all','deferred'].includes(ui.filter)}">${text}</button>`).join('')}<button class="secondary" data-action="material-files">全部资料</button></nav>
  ${!isResult?`<div class="mat-view-modes" role="group" aria-label="待办查看方式"><span class="small muted">查看方式</span><button class="text" data-action="material-mode" data-mode="issues" aria-pressed="${ui.viewMode==='issues'}">按问题查看</button><button class="text" data-action="material-mode" data-mode="files" aria-pressed="${ui.viewMode==='files'}">按原件查看</button></div>`:''}
  ${!isResult&&c.deferred?`<div class="mat-subfilters"><button class="text" data-action="material-filter" data-filter="all" aria-pressed="${ui.filter!=='deferred'}">可继续处理 ${issues} 项</button><button class="text" data-action="material-filter" data-filter="deferred" aria-pressed="${ui.filter==='deferred'}">已记录待补 ${c.deferred} 项</button></div>`:''}
  ${!isResult?(ui.viewMode==='issues'?renderMaterialIssueGroups():renderMaterialFileGroups()):''}
  ${isResult||!current?renderMaterialTask():''}${isResult&&typeof billResults==='function'?billResults():''}${isResult&&typeof invoiceAmountResults==='function'?invoiceAmountResults():''}<nav class="secondary-nav"><button class="text" data-action="records">处理记录</button><button class="text" data-action="refresh">刷新状态</button></nav></div>`;
}
function openMaterialWorkbench(){state.view='materials';state.category=null;closeDialog();const ui=materialState();ui.screen='list';ui.filter='all';ui.feedback='';materialSaveNavigation(true);render();document.querySelector('#materialWorkbench h2')?.focus({preventScroll:true});}
function installMaterialActions(){
  if(typeof installProblemReviewActions==='function')installProblemReviewActions();
  if(typeof installBankPeriodActions==='function')installBankPeriodActions();
  if(typeof installMaterialGuidanceActions==='function')installMaterialGuidanceActions();
  actions['material-open']=openMaterialWorkbench;
  actions['material-locate']=b=>{const t=currentMaterialTask();if(t)openMaterialDetail(t.id,b);};
  actions['material-files']=b=>showArtifacts('all',b);
  actions['material-open-filter']=b=>{const ui=materialState();state.view='materials';state.category=null;ui.screen='list';ui.filter=b.dataset.filter||'all';ui.selected='';ui.page=0;closeDialog();materialSaveNavigation(true);render();$('materialTaskTitle')?.focus({preventScroll:true});};
  actions['material-mode']=b=>{const ui=materialState(),mode=b.dataset.mode==='files'?'files':'issues';ui.screen='list';ui.viewMode=mode;storage('finwise.material.mode.'+ui.key,mode);materialSaveNavigation();render();$('materialListTitle')?.focus({preventScroll:true});};
  actions['material-select-group']=b=>openMaterialDetail(b.dataset.task,b);
  actions['material-filter']=b=>{const ui=materialState();if(b.dataset.task){openMaterialDetail(b.dataset.task,b,'file');return;}ui.screen='list';ui.filter=b.dataset.filter;ui.feedback='';ui.selected='';ui.page=0;materialSaveNavigation(true);render();$('materialTaskTitle')?.focus({preventScroll:true});};
  actions['material-page']=b=>{materialState().page=Math.max(0,Number(b.dataset.page)||0);const t=currentMaterialTask();if(t)materialDraft(t).selected.clear();materialSaveNavigation();render();$('materialTaskTitle')?.focus({preventScroll:true});};
  actions['material-skip']=()=>{const t=currentMaterialTask();if(t){materialState().skipped.add(t.id);materialAdvance(t,'skipped');}};
  actions['material-resume']=()=>{const ui=materialState();ui.skipped.clear();ui.screen='list';ui.filter='all';ui.selected='';ui.page=0;materialSaveNavigation();render();};
  actions['material-defer']=()=>{const t=currentMaterialTask();if(!t||!materialCanWrite()||!materialTaskIsCurrent(t))return;materialDraft(t).defer=true;materialSaveDraft(t);render();$('materialReason')?.focus();};
  actions['material-cancel-defer']=()=>{const t=currentMaterialTask();if(t){materialDraft(t).defer=false;materialSaveDraft(t);}render();};
  actions['material-supplement']=()=>{const t=currentMaterialTask();uploadDialog();if(t){$('uploadKind').value=fileById(t.artifact_id).data.parse_options?.document_kind||'purchase_invoices';$('dialogBody').insertAdjacentHTML('afterbegin',`<p class="issue-banner">关联问题：${esc(t.title)}。新资料会追加保存，不会自动覆盖旧原件或关闭此问题。</p>`);}};
  actions['material-parse']=()=>exclusive(async()=>{const t=currentMaterialTask();if(!t||!materialCanWrite()||!materialTaskIsCurrent(t))return;const a=fileById(t.artifact_id),options=a.data.parse_options,epoch=state.epoch;if(!options){openParseDialog(a);return;}if(options.document_kind==='payroll'){await openMapping(a);return;}notify('正在本地识别当前资料，请等待结果…');await command('parse_artifact',a.object_id,a.version,options);if(epoch!==state.epoch)return;materialUI.feedback='识别已结束，请返回问题列表核对最新结果；提取成功不代表资料已核实。';render();materialFocusDetail();});
  actions['material-verify']=()=>exclusive(async()=>{const t=currentMaterialTask();if(!t||!materialCanWrite()||!materialTaskIsCurrent(t))return;const d=materialDraft(t),all=state.overview.material_review.records.filter(r=>t.record_ids.includes(r.object_id)),visible=all.slice(materialUI.page*5,materialUI.page*5+5),records=visible.filter(r=>d.selected.has(r.object_id)).map(r=>({object_id:r.object_id,version:r.version}));if(!records.length)throw Error('请先比较数据，并选择当前页已核对的记录。');const epoch=state.epoch,group=materialState().group,draftRevision=materialDraftRevision(d);await command('verify_source_values',t.artifact_id,t.artifact_version,{task_id:t.id,records,note:d.note});if(epoch!==state.epoch)return;const draftCleared=materialDeleteDraft(t.id,draftRevision);if(!draftCleared||!materialDetailStillOpen(group,t.id)){notify('资料核实已保存，可返回列表查看结果。');return;}materialAdvance(t,'verified');});
  actions['material-save-defer']=()=>exclusive(async()=>{const t=currentMaterialTask();if(!t||!materialCanWrite()||!materialTaskIsCurrent(t))return;const d=materialDraft(t);if(!d.reason.trim())throw Error('请填写暂无法补充的原因。');const epoch=state.epoch,group=materialState().group,draftRevision=materialDraftRevision(d);await command('defer_material_issue',t.artifact_id,t.artifact_version,{task_id:t.id,reason:d.reason.trim()});if(epoch!==state.epoch)return;const draftCleared=materialDeleteDraft(t.id,draftRevision);if(!draftCleared||!materialDetailStillOpen(group,t.id)){notify('暂无法补充的原因已保存，问题仍保留。');return;}materialAdvance(t,'deferred');});
  actions['material-revoke']=b=>exclusive(async()=>{if(!materialCanWrite())return;const r=state.overview.material_review.records.find(r=>r.verification?.object_id===b.dataset.check);if(!r)return;await command('revoke_source_verification',r.verification.object_id,r.verification.version,{});render();notify('本条资料核实已撤销，已返回待核实范围。');});
  document.addEventListener('input',e=>{if(!e.target.closest('#materialWorkbench'))return;const t=currentMaterialTask();if(!t)return;const d=materialDraft(t);if(e.target.id==='materialNote')d.note=e.target.value;if(e.target.id==='materialReason')d.reason=e.target.value;if(e.target.dataset.materialRecord){if(e.target.checked)d.selected.add(e.target.dataset.materialRecord);else d.selected.delete(e.target.dataset.materialRecord);}materialSaveDraft(t);});
  document.addEventListener('submit',e=>{if(e.target.id==='materialDeferForm'){e.preventDefault();actions['material-save-defer']().catch(error=>notify(error.message,true));}});
  installMaterialNavigation();
}

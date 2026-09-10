'use strict';

// Server-owned preparation state. No browser timer starts financial processing.
let historicalPollTimer;
const historicalStatus = status => ({QUEUED:'已排队',RUNNING:'系统处理中',WAITING_INPUT:'等待另一份账表',
  NEEDS_SELECTION:'待选择来源',NEEDS_REVIEW:'有问题待核实',READY_FOR_CONFIRMATION:'待人工确认',FAILED:'处理失败',STALE:'来源已变化'}[status]||'待核对');

function renderHistoricalTask(job) {
  if(historicalIssueFlow(job).done)return taskShell('历史问题的处理意见已记录',historicalHandoff(job,false),primary('history-next-work',historicalNextWork().label),badge('余额仍待核实','yellow'));
  const d=job.data,r=d.result,active=['QUEUED','RUNNING'].includes(job.status);
  let title=active?'系统正在核对历史账表':job.status==='READY_FOR_CONFIRMATION'?'确认上期末余额结转本期期初':r?'处理历史账表核对问题':'继续历史账表核对';
  let body=`<div class="issue-banner ${job.status==='FAILED'?'red':''}" role="status"><strong>${historicalStatus(job.status)}</strong> · ${esc(d.error||d.step)}</div>`;
  if(active)body+=`<p>无需再次点击启动。后台会读取已上传账表、核对发生额与期末余额；完成后这里自动更新。</p><p class="small muted">${d.started_at?'开始时间 '+esc(d.started_at):'已进入后台队列'} · 第 ${d.attempt||1} 次处理。可以离开页面，任务会保留。</p>`;
  if(r)body+=`<p><strong>${esc(r.start_period)} — ${esc(r.end_period)}</strong>：已提取 ${r.entry_count} 条分录、${r.voucher_count} 张历史凭证、${r.account_count} 个科目及 ${r.auxiliary_count||0} 条辅助明细。</p>
    ${job.status==='NEEDS_REVIEW'?'<!--task-action-->':''}
    <div class="goal"><b>系统已核对 ${r.passed_checks} 项 · ${r.issues.length} 项需处理</b>历史数据单独保留，不计入 ${esc(r.opening_period)} 的业务记录；系统校验通过不等于已获人工批准。</div>`;
  let action='';
  if(job.status==='READY_FOR_CONFIRMATION') {
    body+=`<p>以 ${esc(r.end_period)} 的<strong>期末余额</strong>建立 ${esc(r.opening_period)} 期初候选，不采用报表中的上年年初余额。</p><p class="small muted">本项完成条件：确认原件为最终结账版本、科目及辅助明细完整，并同意按期末数结转期初。</p>
      <details><summary>查看余额及来源</summary>${historicalBalanceTable(r)}</details>
      <label class="check-label"><input type="checkbox" data-history-confirm="final_close_confirmed" ${readonly()?'disabled':''}>我已确认这两份账表是人民币口径的上期最终结账版本</label>
      <label class="check-label"><input type="checkbox" data-history-confirm="completeness_confirmed" ${readonly()?'disabled':''}>我已核对科目、辅助明细及资料完整性</label>
      <label class="check-label"><input type="checkbox" data-history-confirm="carry_forward_confirmed" ${readonly()?'disabled':''}>同意将上期末余额结转为本期期初</label>`;
    action=primary('confirm-historical','确认期初核对结果',true);
  } else if(job.status==='NEEDS_REVIEW') {
    body+=`<p>逐项核对已有依据，选择补充材料、提交处理方案，或记录暂无法补充的原因。处理记录不会直接确认期初。</p>${r.issues.map((i,n)=>renderHistoricalIssue(i,n,true)).join('')}`;
    action=primary('historical-details',`处理 ${r.issues.length} 项核对问题`);
  } else if(job.status==='FAILED'||job.status==='STALE') {
    body+='<p>原件已保留。请先检查上述原因，修复后可重试；未知格式或资料问题不会伪装成已完成。</p>';
    action=primary('retry-historical','重新处理历史账表',readonly());
  } else if(job.status==='WAITING_INPUT')action=primary('upload-history','添加另一份历史账表',readonly());
  else if(job.status==='NEEDS_SELECTION') {
    body+='<p>请从已接收原件中选择本次核对的一份余额表、一份序时账，不按文件名自动替换。</p>';
    body+=['余额表','序时账'].map((name,i)=>`<label>${name}<select id="historySource${i}" ${readonly()?'disabled':''}><option value="">请选择</option>${baselineArtifacts().filter(a=>a.data.source_purpose==='historical_reference').map(a=>`<option value="${esc(a.object_id)}">${esc(a.data.filename)} · v${a.version}</option>`).join('')}</select></label>`).join('');
    action=primary('select-historical','按所选账表重新核对',readonly());
  }
  body+=`<div class="record-note"><button class="text" data-action="baseline-files">查看已上传账表</button> ${r&&job.status!=='NEEDS_REVIEW'?'<button class="text" data-action="historical-details">核对详情</button>':''}</div>`;
  return taskShell(title,body,action,badge(historicalStatus(job.status),active?'blue':job.status==='FAILED'?'red':'yellow'));
}

function historicalBalanceTable(r) {
  return `<p class="small">原表一级科目期末：借方 <span class="mono">¥${amount(r.source_totals.debit)}</span> / 贷方 <span class="mono">¥${amount(r.source_totals.credit)}</span>；末级明细不抵销：借方 <span class="mono">¥${amount(r.totals.debit)}</span> / 贷方 <span class="mono">¥${amount(r.totals.credit)}</span>。两个口径不同，不重复加总父级与明细。</p>
    ${table(['科目 / 辅助核算','上期末借方 → 本期期初借方','上期末贷方 → 本期期初贷方','来源'],r.balances.map(b=>`<tr><td>${esc(b.account_code)} ${esc(b.account_name)}${b.auxiliary?.length?`<p class="small">${b.auxiliary.length} 项辅助明细</p>`:''}</td><td class="mono amount">${amount(b.closing_debit)} → ${amount(b.opening_debit)}</td><td class="mono amount">${amount(b.closing_credit)} → ${amount(b.opening_credit)}</td><td class="small">${esc(b.source_anchor.region)}${b.auxiliary?.map(a=>`<p>辅助 ${esc(a.key)} · ${esc(a.source_anchor.region)} · 借 ${amount(a.closing_debit)} / 贷 ${amount(a.closing_credit)}</p>`).join('')||''}</td></tr>`))}`;
}

function showHistoricalDetails() {
  const job=state.overview.historical_preparation,r=job?.data.result;
  if(!job)return;
  state.view='historical';closeDialog();render();$('historicalTitle')?.focus({preventScroll:true});window.scrollTo(0,0);
}

function historicalAmount(value) {
  const text=String(value??'');
  return /^-?\d+\.\d{2}$/.test(text)?text.replace(/\B(?=(\d{3})+(?!\d))/g,','):'未提供';
}

function historicalEntryTable(rows, issueIndex=null) {
return `<div class="history-entry-table">${table(['日期 / 凭证','摘要与科目','借方金额','贷方金额','来源'],rows.map((row,n)=>`<tr class="${Number(row.debit)<0||Number(row.credit)<0?'negative-entry':''}"><td class="entry-date"><span class="mono">${esc(row.date)}</span><br>${esc(row.voucher_number)}</td><td class="entry-description">${esc(row.summary||'原件未填摘要')}<p class="small muted">${esc(row.account_code)} · ${esc(row.account_name)}</p></td><td data-label="借方金额" class="amount mono ${Number(row.debit)<0?'negative-amount':''}">${esc(historicalAmount(row.debit))}</td><td data-label="贷方金额" class="amount mono ${Number(row.credit)<0?'negative-amount':''}">${esc(historicalAmount(row.credit))}</td><td class="entry-source">${issueIndex===null?`第 ${row.anchor.row} 行`:`<button class="text" data-action="history-source" data-history-issue="${issueIndex}" data-row="${n}" aria-label="查看 ${esc(row.voucher_number)} 第 ${row.anchor.row} 行来源">第 ${row.anchor.row} 行 ↗</button>`}</td></tr>`))}</div>`;
}

function renderHistoricalIssue(issue,index,compact=false) {
  const e=issue.evidence,s=e?.summary,rows=e?.rows||[];
  const title=`<div class="row"><h3>${esc(issue.title)}</h3>${!compact&&rows[0]?`<button class="text" data-action="history-source" data-history-issue="${index}" data-row="0">查看来源与原件 ↗</button>`:''}</div>`;
  if(compact)return `<article class="source-slot">${title}${s?`<p>${s.account_names.map(esc).join('、')} · ${s.record_count} 条分录</p><p class="small">发生净额 ${esc(historicalAmount(s.net_movement))} 元 · ${s.negative_count} 条含负数金额；余额表未列示期末余额。</p><p class="small"><strong>建议：</strong>${esc(e.advice[0])}</p>`:`<p>${esc(issue.message)}</p>`}</article>`;
  const facts=s?`<p class="history-account-name">${s.account_names.map(esc).join('、')} · ${s.record_count} 条关联分录</p>
    <dl class="history-facts"><div><dt>借方正数发生额</dt><dd class="mono">${esc(historicalAmount(s.debit_positive))}</dd><p class="small muted">负数 ${esc(historicalAmount(s.debit_negative))}</p></div><div><dt>贷方正数发生额</dt><dd class="mono">${esc(historicalAmount(s.credit_positive))}</dd><p class="small muted">负数 ${esc(historicalAmount(s.credit_negative))}</p></div><div><dt>借贷净变动</dt><dd class="mono">${esc(historicalAmount(s.net_movement))}</dd><p class="small muted">不是期末余额</p></div><div><dt>余额表期末数</dt><dd class="history-missing">未列示</dd><p class="small muted">须补充余额依据</p></div></dl>`:`<p>${esc(issue.message)}</p>`;
  let data='';
  if(rows.length&&rows.every(row=>'debit' in row))data=`<div class="row small"><strong>关联分录</strong><span class="muted">金额单位：元 · 日期倒序 · 负数按原件保留</span></div>${historicalEntryTable(rows,index)}`;
  else if(rows.length)data=rows.map((row,n)=>`<div class="history-raw-row"><strong>${esc(row.anchor.region)}</strong>${table(['原件字段','原始值'],row.cells.map(c=>`<tr><td>${esc(c.label)}</td><td>${esc(c.value===null||c.value===''?'（空白）':c.value)}</td></tr>`))}<button class="text" data-action="history-source" data-history-issue="${index}" data-row="${n}">查看来源与原件 ↗</button></div>`).join('');
  else data=`<p class="empty-proof">${esc(e?.omitted_rows?'此项明细超出本次展示上限，原始数据仍保留在原件中。':state.overview.historical_preparation.data.evidence_error||'此项暂无可唯一定位的行级明细，请核对下方原件与校验要求。')}</p>`;
  if(e?.missing_locations)data+=`<p class="issue-banner">另有 ${e.missing_locations} 处来源无法唯一定位，未猜测或补齐。</p>`;
  if(e?.omitted_rows||e?.contexts_omitted)data+=`<p class="issue-banner">本次展示已达上限：${e.omitted_rows||0} 条问题明细、${e.contexts_omitted||0} 张凭证上下文未展开。汇总仍按完整关联数据计算，请下载原件核对剩余内容。</p>`;
  const advice=e?.advice||[issue.message];
  return `<article class="history-issue" data-history-issue="${index}">${title}${facts}${data}<section class="history-advice"><h4>建议怎么处理</h4><ol>${advice.map(a=>`<li>${esc(a)}</li>`).join('')}</ol><p class="small muted">基于原件与校验规则的核对建议，尚未经人工确认。</p></section><p class="history-condition"><strong>完成条件：</strong>${esc(e?.completion_condition||'补全原件依据并通过校验，再进行人工确认。')}</p></article>`;
}

function showHistoricalSource(button) {
  const issue=state.overview.historical_preparation?.data.result?.issues[Number(button.dataset.historyIssue)];
  const row=issue?.evidence?.rows[Number(button.dataset.row)];
  if(!row)return;
  const context=issue.evidence.related_vouchers?.find(v=>v.date===row.date&&v.voucher_number===row.voucher_number&&v.source_id===row.source.artifact_id);
  const related=state.overview.historical_preparation.data.result.evidence_vouchers?.find(v=>v.id===context?.context_id);
  const ref=row.source;
  openDialog('问题来源与原始数据',`<h3>${esc(ref.filename)}</h3><p class="small">${esc(row.anchor.region)} · 原件版本 ${ref.version}</p>
    <p class="small muted">以下值来自本次核对绑定的原件，空白及负数按原件保留。</p>${table(['原件字段','原始值'],row.cells.map(c=>`<tr><td>${esc(c.label)}</td><td>${esc(c.value===null||c.value===''?'（空白）':c.value)}</td></tr>`))}
    ${related?`<h3>同张凭证的其他分录及当前行</h3><p class="small muted">用于核对调整关系，不代表系统已确定科目对应关系。</p>${historicalEntryTable(related.rows)}${related.omitted_rows?`<p class="issue-banner">另有 ${related.omitted_rows} 条上下文超出展示上限，请下载原件查看完整凭证。</p>`:''}`:''}
    <p class="small muted">文件哈希 <span class="mono">${esc(ref.sha256)}</span></p><button class="secondary" data-object="${esc(ref.artifact_id)}" data-object-version="${ref.version}">查看原件详情与下载</button>`);
}

function renderHistoricalDetails() {
  const job=state.overview.historical_preparation,d=job.data,r=d.result;
  const checks=r?.checks||[];
  const groups=[...new Set(checks.map(c=>c.code))].map(code=>{
    const rows=checks.filter(c=>c.code===code);
    return {title:({ACCOUNT_EQUATION:'科目余额衔接',HIERARCHY:'科目层级汇总',BALANCE_TOTAL:'原表合计',TRIAL_BALANCE:'借贷平衡',JOURNAL_TOTAL:'全年发生额',VOUCHER_BALANCE:'逐张凭证平衡',ACCOUNT_MOVEMENT:'逐科目发生额',AUXILIARY_REQUIRED:'辅助明细',UNMAPPED_ACCOUNT:'科目映射'}[code]||'其他校验'),rows};
  });
  return `<button class="text return-link" data-action="return-current">← 返回当前任务</button><section class="panel pad"><div class="row"><h2 id="historicalTitle" tabindex="-1">历史账表核对详情</h2>${badge(historicalStatus(job.status),'yellow')}</div><p class="small muted">解析版本 ${esc(d.parser_version)} · ${esc(d.finished_at||d.queued_at)} · 第 ${d.attempt||1} 次处理</p>${d.error?`<p class="issue-banner red">${esc(d.error)}</p>`:''}
    ${r?`${r.issues.length?renderHistoricalIssueWorkspace():'<p>自动校验已通过。返回当前任务，核实最终结账版本与完整性后再确认。</p>'}
    <details class="history-secondary"><summary>系统校验结果 · ${r.passed_checks} 项通过</summary>${table(['校验项目','通过 / 总数','结果'],groups.map(g=>`<tr><td>${esc(g.title)}</td><td>${g.rows.filter(i=>i.passed).length} / ${g.rows.length}</td><td>${badge(g.rows.every(i=>i.passed)?'通过':'待核对',g.rows.every(i=>i.passed)?'green':'yellow')}</td></tr>`))}
    <p>全年发生额：借方 ${amount(r.movement_totals.debit)} / 贷方 ${amount(r.movement_totals.credit)}</p></details><details class="history-secondary"><summary>期末余额 → 期初候选</summary>${historicalBalanceTable(r)}</details>`:''}
    <h3>本次使用的原件</h3>${d.sources.map(s=>`<p>${esc(s.filename)} · v${s.version} ${objectButton(s.artifact_id,'查看原件')}</p>`).join('')}
    <p class="small muted">原件、结果与输入输出哈希均保留版本记录；处理方案单独留痕，不修改原件、科目或期初余额。</p>${objectButton(job.object_id,'查看处理留痕')}
    <div class="record-note"><button class="secondary" data-action="history-current-files">继续整理本期资料</button><p>仅查看、整理本期资料；期初未确认前，依赖该基线的后续操作仍受原有门禁约束。</p></div></section>`;
}

// Unsaved text is memory-only. Persisted outcomes always come from workbench.
const historicalPlansUI={scope:'',selection:new Map(),drafts:new Map(),pending:null};
function resetHistoricalPlans() {
  historicalPlansUI.scope='';historicalPlansUI.selection.clear();historicalPlansUI.drafts.clear();
}
const historicalPlanStatus=status=>({SUBMITTED:'方案已提交，待复核',UNAVAILABLE_RECORDED:'暂无法补充，已记录',REVIEWED:'方案复核通过',RETURNED:'退回补充说明'}[status]||'处理状态待核对');
function historicalIssueFlow(job=state.overview?.historical_preparation) {
  const issues=job?.data.result?.issues||[],records=state.overview?.historical_issue_plans||[];
  const plans=issues.map(issue=>records.find(p=>job.status==='NEEDS_REVIEW'&&issue.issue_key&&!p.stale&&
    p.data.issue_key===issue.issue_key&&p.data.historical_preparation?.object_id===job.object_id&&
    p.data.historical_preparation?.version===job.version&&p.data.input_hash===job.data.input_hash));
  const pending=issues.map((_,n)=>n).filter(n=>!['SUBMITTED','REVIEWED','UNAVAILABLE_RECORDED'].includes(plans[n]?.status));
  return {issues,plans,pending,count:issues.length-pending.length,done:issues.length>0&&pending.length===0};
}
function historicalNextWork() {
  const flow=historicalIssueFlow(),reviewIndex=flow.plans.findIndex(p=>p?.status==='SUBMITTED'&&!readonly()&&
    ['accountant','reviewer','admin'].includes(state.role)&&p.data.submitted_by!==state.user?.user_id);
  if(reviewIndex>=0)return {mode:'review',index:reviewIndex,label:`复核第 ${reviewIndex+1} 项方案`,reason:'处理方案已提交，请先核对依据与处理意见。方案复核不替代余额校验。'};
  if(typeof openMaterialWorkbench==='function')return {mode:'materials',label:`处理${Number(scope()?.accounting_period_id?.slice(-2))}月资料`,reason:'先查看本期资料整体情况、已核实成果与剩余问题，再逐项办理。'};
  const r=state.overview?.data_readiness,cats=(r?.categories||[]).filter(c=>!['baseline','unassigned'].includes(c.id));
  const ids=new Set(cats.flatMap(c=>c.artifact_ids)),files=(state.overview?.artifacts||[]).filter(a=>a.status!=='ARCHIVED'&&ids.has(a.object_id));
  const pending=files.filter(a=>a.data.observed_period===scope()?.accounting_period_id&&['RECEIVED','FAILED'].includes(a.data.parse_status||'RECEIVED')).length;
  const month=Number(scope()?.accounting_period_id?.slice(-2));
  if(pending)return {mode:'files',label:`继续提取${month}月资料`,reason:`还有 ${pending} 份本期资料未完成提取。进入清单后，点击对应文件的“选择类型并提取”；先核对类型，再查看提取结果。`};
  const category=cats.find(c=>c.issues?.length);
  if(category)return {mode:'category',category:category.id,label:`核对${month}月资料问题`,reason:`下一步先核对“${category.name}”的 ${category.issues.length} 项问题，逐项查看原始依据与提取值。`};
  return {mode:'files',label:`查看${month}月资料清单`,reason:files.length?'可以继续检查本期已接收资料及提取结果。资料核实与历史期初衔接分别处理。':'尚未接收本期业务资料，可在清单中添加；历史资料不能代替本期资料。'};
}
function historicalHandoff(job,withButton=true) {
  const flow=historicalIssueFlow(job),next=historicalNextWork();
  const waiting=flow.plans.filter(p=>p?.status==='SUBMITTED').length,unavailable=flow.plans.filter(p=>p?.status==='UNAVAILABLE_RECORDED').length;
  return `<section class="history-handoff" id="historyHandoff" tabindex="-1" aria-label="下一步工作"><h3>本轮处理意见已记录 ${flow.count} / ${flow.issues.length}</h3>
    <p>${unavailable?`${unavailable} 项暂无法补充已记录。`:''}${waiting?`${waiting} 项方案等待复核。`:''}原始 ${flow.issues.length} 项余额问题仍待核实，期初尚不能确认。</p>
    <div class="goal"><b>下一步：${esc(next.label)}</b>${esc(next.reason)}</div>
    ${withButton?primary('history-next-work',next.label):'<button class="text" data-action="historical-details">查看本轮处理记录</button>'}<p class="small muted">可以继续资料整理与核对；依赖有效期初的制证、交付仍不可继续。</p></section>`;
}
function historicalPlanContext() {
  const job=state.overview?.historical_preparation;
  if(!job)return null;
  const range=scopeKey(scope());
  if(historicalPlansUI.scope!==range){resetHistoricalPlans();historicalPlansUI.scope=range;}
  const jobKey=JSON.stringify([range,job.object_id,job.version,job.data.input_hash]);
  const issues=job.data.result?.issues||[],index=historicalPlansUI.selection.get(jobKey)||0,issue=issues[index]||issues[0];
  if(!issue)return null;
  const key=JSON.stringify([jobKey,issue.issue_key||index]);
  const records=state.overview.historical_issue_plans||[];
  const matching=records.filter(p=>p.data.issue_key===issue.issue_key&&issue.issue_key);
  const plan=matching.find(p=>!p.stale&&p.data.historical_preparation?.object_id===job.object_id&&p.data.historical_preparation?.version===job.version&&p.data.input_hash===job.data.input_hash);
  const old=records.filter(p=>p!==plan&&(matching.includes(p)||(p.stale&&p.data.issue_snapshot?.title===issue.title)));
  return {job,issues,issue,index:issues.indexOf(issue),jobKey,key,plan,old};
}
function historicalPlanDraft(c) {
  if(!historicalPlansUI.drafts.has(c.key)) {
    const d=c.plan?.data||{};
    historicalPlansUI.drafts.set(c.key,{route:d.route||'',conclusion:d.conclusion||'',action_plan:d.action_plan||'',owner:d.owner||'',follow_up:d.follow_up||'',
      evidence:(d.evidence||[]).map(historicalEvidenceKey),basePlanVersion:c.plan?.version||0,dirty:false,editing:false,
      evidence_filter:'',review_note:'',review_decision:'approved',error:''});
  }
  const draft=historicalPlansUI.drafts.get(c.key);
  // A clean form may follow fresh server data; a dirty form must remain visible.
  if(!draft.dirty&&!draft.editing&&!draft.review_note&&draft.basePlanVersion!==(c.plan?.version||0)) {
    historicalPlansUI.drafts.delete(c.key);return historicalPlanDraft(c);
  }
  return draft;
}
function historicalEvidenceKey(ref) {return JSON.stringify([ref.artifact_id,ref.version,ref.anchor?.region,ref.anchor?.row]);}
function historicalEvidenceOptions(c) {
  const options=new Map(),sources=c.job.data.sources||[],r=c.job.data.result;
  const add=(ref,anchor,description)=>{
    const source=sources.find(s=>s.artifact_id===ref?.artifact_id&&s.version===ref.version&&(!ref.sha256||s.sha256===ref.sha256));
    if(!source||!Number.isSafeInteger(anchor?.row)||anchor.row<1||typeof anchor.region!=='string'||!anchor.region.endsWith(`!第${anchor.row}行`)||anchor.region===`!第${anchor.row}行`)return;
    const reference={artifact_id:source.artifact_id,version:source.version,anchor:{region:anchor.region,row:anchor.row}};
    const key=historicalEvidenceKey(reference);
    options.set(key,{key,reference,label:`${source.filename} · v${source.version} · ${anchor.region} · ${description||'原件记录'}`});
  };
  for(const row of c.issue.evidence?.rows||[])add(row.source,row.anchor,[row.date,row.voucher_number,row.account_code,row.summary].filter(Boolean).join(' · '));
  const contexts=new Set((c.issue.evidence?.related_vouchers||[]).map(v=>v.context_id));
  for(const voucher of r.evidence_vouchers||[])if(contexts.has(voucher.id))for(const row of voucher.rows)add(row.source,row.anchor,[row.date,row.voucher_number,row.account_code,row.summary].filter(Boolean).join(' · '));
  for(const b of r.balances||[]) {
    add(r.balance_source,b.source_anchor,`${b.account_code} ${b.account_name} · 期末借 ${historicalAmount(b.closing_debit)} / 贷 ${historicalAmount(b.closing_credit)}`);
    for(const a of b.auxiliary||[])add(r.balance_source,a.source_anchor,`${b.account_code} · 辅助 ${a.key}`);
  }
  return [...options.values()];
}
function canReviewHistoricalPlan(c) {
  return !!c&&c.job.status==='NEEDS_REVIEW'&&!readonly()&&!!state.user?.user_id&&['accountant','reviewer','admin'].includes(state.role)&&
    c.plan?.status==='SUBMITTED'&&!c.plan.stale&&!!c.plan.data.submitted_by&&state.user.user_id!==c.plan.data.submitted_by;
}
function canSubmitHistoricalPlan(c) {
  return !!c&&c.job.status==='NEEDS_REVIEW'&&!readonly()&&!!state.user?.user_id&&['operator','accountant','admin'].includes(state.role)&&
    (!c.plan||c.plan.data.submitted_by===state.user.user_id);
}
function historicalPlanPreview(route) {
  if(route==='unavailable')return '<p class="small muted">仅记录原因，不修改账表或解除期初阻断。</p>';
  return '<div class="history-plan-preview"><strong>处理预览 · 0 金额变更</strong><p>只保存处理方案与依据，不修改科目、原件、基线或财务事实；未解除原始阻断。方案复核通过不等于余额已核实，也不自动执行账务调整。</p></div>';
}
function renderHistoricalPlanRecord(plan,old=false) {
  const d=plan.data,unavailable=d.route==='unavailable';
  return `<section class="history-plan-record"><div class="row"><h3>${old?'旧处理记录':'已保存的处理记录'}</h3>${badge(historicalPlanStatus(plan.status),'yellow')}</div>
    ${old?`<p class="issue-banner">${esc(plan.stale_reason||'来源或校验版本已变化')}。旧记录只读，请基于新校验重新提交。</p>`:''}
    <p class="small muted">提交人 ${esc(d.submitted_by||plan.created_by)} · ${esc(d.submitted_at||plan.created_at)} · 记录版本 ${plan.version}</p>
    <dl class="history-plan-values"><div><dt>${unavailable?'无法补充原因':'核实结论'}</dt><dd>${esc(d.conclusion)}</dd></div>${unavailable?'':`<div><dt>拟处理方案</dt><dd>${esc(d.action_plan)}</dd></div>`}<div><dt>责任人</dt><dd>${esc(d.owner)}</dd></div>${unavailable?'':`<div><dt>后续安排</dt><dd>${esc(d.follow_up)}</dd></div>`}</dl>
    ${(d.evidence||[]).length?`<details><summary>已关联 ${(d.evidence||[]).length} 处依据</summary><ul>${d.evidence.map(e=>`<li>${esc(e.filename||e.artifact_id)} · v${e.version} · ${esc(e.anchor?.region)}</li>`).join('')}</ul></details>`:''}
    ${d.review?`<div class="record-note"><strong>${d.review.decision==='approved'?'方案复核通过':'退回补充说明'}</strong><p>${esc(d.review.note)}</p><p>复核人 ${esc(d.review.reviewed_by)} · ${esc(d.review.reviewed_at)}</p></div>`:''}
    ${plan.status==='SUBMITTED'&&!old&&!plan.stale?'<p class="small">等待另一位有权限的人员登录本企业复核；不能由提交人自审。</p>':''}
    <p class="small history-retained">已记录，期初阻断仍保留。</p>${objectButton(plan.object_id,'查看记录与复核留痕')}</section>`;
}
function renderHistoricalEvidence(c,draft) {
  const options=historicalEvidenceOptions(c),term=draft.evidence_filter.trim().toLowerCase();
  const shown=options.filter(o=>!term||o.label.toLowerCase().includes(term));
  return `<p class="small muted">仅可选择本次绑定的历史账表及已定位的真实行；请选择支持方案的依据，不自动推断对应关系。</p>
    <label>查找文件、科目或行号<input type="search" data-history-field="evidence_filter" value="${esc(draft.evidence_filter)}" autocomplete="off"></label>
    <div id="historyEvidenceChoices" class="history-evidence-options">${shown.map(o=>`<label class="check-label"><input type="checkbox" data-history-evidence="${esc(o.key)}" ${draft.evidence.includes(o.key)?'checked':''}><span>${esc(o.label)}</span></label>`).join('')||'<p class="empty-proof">没有匹配的可选行。可更换搜索条件，或选择其他处理方式；不能编造来源。</p>'}</div>
    <p class="small muted" id="historyEvidenceCount">已选择 ${draft.evidence.length} 处依据 · 当前显示 ${shown.length} 处</p>`;
}
function renderHistoricalPlanForm(c,draft) {
  const unavailable=draft.route==='unavailable',conflict=draft.basePlanVersion!==(c.plan?.version||0);
  const labels=unavailable?{conclusion:'无法补充原因'}:{conclusion:'核实结论',action_plan:'拟处理方案',owner:'责任人',follow_up:'后续安排'};
  const routes=[['upload','补充材料','有新材料或正确版本'],['existing_evidence','依据现有资料提交方案','关联已有凭证与余额依据'],['unavailable','暂无法补充','只需说明原因，责任人自动记录']];
  return `<form id="historicalPlanForm" class="history-plan-form" data-history-form-key="${esc(c.key)}"><fieldset ${historicalPlansUI.pending?'disabled':''}><legend>本项处理方式</legend>
    <div class="history-routes">${routes.map(([value,name,help])=>`<label class="history-route ${draft.route===value?'selected':''}"><input type="radio" name="historicalRoute" data-history-field="route" value="${value}" ${draft.route===value?'checked':''}><span><strong>${name}</strong><small>${help}</small></span></label>`).join('')}</div>
    ${draft.route==='upload'?'<div class="history-upload"><h3>补充本项核对所需的历史账表</h3><p>上传正确版本的余额表或序时账，原件继续保留。存在多个版本时，需要明确选择本次两份账表再核对。</p><button type="button" class="primary" data-action="upload-history">选择并上传历史账表</button></div>':''}
    ${['existing_evidence','unavailable'].includes(draft.route)?`<div class="history-plan-fields">${Object.entries(labels).map(([name,label])=>`<label>${label}<span class="sr-only">（必填）</span>${name==='owner'?`<input data-history-field="${name}" value="${esc(draft[name])}" required maxlength="128">`:`<textarea data-history-field="${name}" required maxlength="${name==='follow_up'?500:2000}">${esc(draft[name])}</textarea>`}</label>`).join('')}</div>
      ${unavailable?`<p class="small muted">责任人：${esc(state.user?.user_id)}（当前登录用户，自动记录）</p>`:`<section class="history-evidence"><h4>关联已有依据（至少 1 处）</h4>${renderHistoricalEvidence(c,draft)}</section>`}
      ${historicalPlanPreview(draft.route)}${conflict?'<p class="issue-banner">记录版本已更新，草稿未被覆盖。请先查看最新记录，再重新载入表单。</p><button type="button" class="secondary" data-action="reload-history-plan">重新载入最新记录</button>':''}
      <p class="small ${draft.error?'history-form-error':'muted'}" data-history-error role="status">${esc(draft.error||'未提交内容仅临时保留，刷新页面后恢复服务端已保存记录。')}</p>
      <button type="submit" class="primary" ${conflict?'disabled':''}>${unavailable?'记录暂无法补充':'提交处理方案'}</button>`:!draft.route?'<p class="small muted">请选择与当前情况相符的处理方式，再填写依据或后续安排。</p>':''}
    </fieldset></form>`;
}
function renderHistoricalReview(c,draft) {
  const conflict=draft.basePlanVersion!==c.plan.version;
  return `<form id="historicalReviewForm" class="history-plan-form" data-history-form-key="${esc(c.key)}"><fieldset ${historicalPlansUI.pending?'disabled':''}><legend>复核处理方案</legend>
    <label>复核决定<select data-history-field="review_decision"><option value="approved" ${draft.review_decision==='approved'?'selected':''}>方案复核通过</option><option value="returned" ${draft.review_decision==='returned'?'selected':''}>退回补充说明</option></select></label>
    <label>复核意见（必填）<textarea data-history-field="review_note" maxlength="2000" required>${esc(draft.review_note)}</textarea></label>${historicalPlanPreview()}
    ${conflict?'<p class="issue-banner">记录版本已更新，请重新载入最新记录后再复核。</p><button type="button" class="secondary" data-action="reload-history-plan">重新载入最新记录</button>':''}
    <p class="history-form-error" data-history-error role="status">${esc(draft.error)}</p><button type="submit" class="primary" ${conflict?'disabled':''}>提交方案复核</button></fieldset></form>`;
}
function renderHistoricalIssueWorkspace() {
  const c=historicalPlanContext(),draft=historicalPlanDraft(c),writable=!readonly()&&c.job.status==='NEEDS_REVIEW'&&!!c.issue.issue_key;
  const flow=historicalIssueFlow(c.job),summary=flow.done&&!historicalPlansUI.selection.has(c.jobKey);
const navigation=`<p class="small muted">本轮处理 ${flow.count} / ${c.issues.length} · 仅统计处理意见，不代表余额已核实</p><nav class="history-issue-nav" aria-label="选择核对问题">${c.issues.map((i,n)=>`<button class="secondary" data-action="history-select-issue" data-history-index="${n}" aria-pressed="${!summary&&n===c.index}" ${historicalPlansUI.pending?'disabled':''}>${n+1}. ${esc(i.title)}<small>${esc(flow.plans[n]?historicalPlanStatus(flow.plans[n].status):'待处理')}</small></button>`).join('')}</nav>`;
  if(summary)return `<h3 id="historyCurrentIssue" tabindex="-1">本轮处理记录</h3>${historicalHandoff(c.job)}${navigation}<p class="small muted">点击上方事项可查看原始问题、处理记录或补充新材料。</p>`;
  return `${navigation}
    <div class="row"><h3 id="historyCurrentIssue" tabindex="-1">第 ${c.index+1} 项 / 共 ${c.issues.length} 项</h3><button class="secondary" data-action="history-handling">${c.plan?'查看本项处理记录':'选择本项处理方式'} ↓</button></div>
    ${renderHistoricalIssue(c.issue,c.index)}<section id="historyHandling" class="history-processing" tabindex="-1" aria-label="当前问题处理">
    ${c.plan?renderHistoricalPlanRecord(c.plan):''}${c.old.length?`<details class="history-secondary"><summary>旧处理记录 · ${c.old.length} 条（只读）</summary>${c.old.map(p=>renderHistoricalPlanRecord(p,true)).join('')}</details>`:''}
    ${!writable?`<p class="issue-banner">${readonly()?'当前账号或期间只允许查看处理记录。':c.job.status!=='NEEDS_REVIEW'?'来源已变化或校验尚未就绪，请等待新校验结果后再提交。':'服务尚未提供问题标识，请刷新以取得可提交的核对结果。'}</p>`:
      canSubmitHistoricalPlan(c)&&(!c.plan||draft.editing)?renderHistoricalPlanForm(c,draft):`${canReviewHistoricalPlan(c)?renderHistoricalReview(c,draft):historicalPlanPreview()}${canSubmitHistoricalPlan(c)?'<button class="text" data-action="edit-history-plan">修改处理记录</button>':!c.plan?'<p class="small muted">请由会计或管理员提交处理方案；复核人员在提交后复核。</p>':''}`}
    ${['SUBMITTED','REVIEWED','UNAVAILABLE_RECORDED'].includes(c.plan?.status)&&!draft.editing&&!canReviewHistoricalPlan(c)&&!historicalPlansUI.pending?`<div class="record-note">${primary('history-next-item',flow.pending.length?`处理下一项（还剩 ${flow.pending.length} 项）`:'查看下一步')}</div>`:''}</section>`;
}
function updateHistoricalPlanInput(event) {
  const target=event.target,form=target.closest?.('[data-history-form-key]'),c=historicalPlanContext();
  if(!form||!c||form.dataset.historyFormKey!==c.key||readonly()||historicalPlansUI.pending)return;
  const draft=historicalPlanDraft(c),field=target.dataset.historyField;
  if(draft.error&&(field||target.dataset.historyEvidence)) {
    if($('notice')?.textContent===draft.error)$('notice').className='notice hidden';
    document.querySelectorAll('[data-history-error]').forEach(el=>{el.textContent='';});
  }
  if(field&&['route','conclusion','action_plan','owner','follow_up','evidence_filter','review_note','review_decision'].includes(field)) {
    draft[field]=target.value;if(field!=='evidence_filter')draft.dirty=true;draft.error='';
    if(field==='route') {if(event.type==='change'){render();document.querySelector(`[name="historicalRoute"][value="${draft.route}"]`)?.focus({preventScroll:true});}}
    if(field==='evidence_filter') {
      const host=document.querySelector('.history-evidence');
      if(host){const focus=historicalPlanFocus();host.innerHTML='<h4>关联已有依据（至少 1 处）</h4>'+renderHistoricalEvidence(c,draft);restoreHistoricalPlanFocus(focus);}
    }
  } else if(target.dataset.historyEvidence) {
    const key=target.dataset.historyEvidence;
    draft.evidence=target.checked?[...new Set([...draft.evidence,key])]:draft.evidence.filter(k=>k!==key);draft.dirty=true;draft.error='';
    if($('historyEvidenceCount'))$('historyEvidenceCount').textContent=`已选择 ${draft.evidence.length} 处依据`;
  }
}
function historicalPlanFocus() {
  const el=document.activeElement,form=el?.closest?.('[data-history-form-key]');
  if(!form||!el.dataset.historyField)return null;
  return {key:form.dataset.historyFormKey,field:el.dataset.historyField,start:el.selectionStart,end:el.selectionEnd};
}
function restoreHistoricalPlanFocus(focus) {
  if(!focus||readonly())return;
  const c=historicalPlanContext();if(c?.key!==focus.key)return;
  const el=document.querySelector(`[data-history-field="${focus.field}"]`);
  if(!el||el.type==='radio')return;el.focus({preventScroll:true});
  if(typeof focus.start==='number'&&['text','search','textarea'].includes(el.type))el.setSelectionRange(focus.start,focus.end);
}
async function submitHistoricalPlan(review=false) {
  if(historicalPlansUI.pending)return;
  if(readonly())throw new Error('当前账号或期间只允许查看');
  const c=historicalPlanContext();
  if(!c||c.job.status!=='NEEDS_REVIEW'||!c.issue.issue_key)throw new Error('请先取得当前有效的校验问题');
  const draft=historicalPlanDraft(c),epoch=state.epoch;
  const pending={key:c.key};
  let result;
  try {
    if(draft.basePlanVersion!==(c.plan?.version||0))throw new Error('记录版本已更新，请先查看最新记录并重新载入表单');
    let action,id,version,payload;
    if(review) {
      if(!canReviewHistoricalPlan(c))throw new Error('此记录需由另一位有权限的人员复核');
      if(!draft.review_note.trim())throw new Error('请填写复核意见');
      if(draft.review_note.trim().length>2000)throw new Error('复核意见不能超过 2000 字');
      if(!['approved','returned'].includes(draft.review_decision))throw new Error('请选择有效的复核决定');
      action='review_historical_issue_plan';id=c.plan.object_id;version=c.plan.version;payload={decision:draft.review_decision,note:draft.review_note.trim()};
    } else {
      if(!canSubmitHistoricalPlan(c))throw new Error('仅经办人员、会计或管理员可提交，已有记录仅允许原提交人修订');
      if(!['existing_evidence','unavailable'].includes(draft.route))throw new Error('请选择提交方案或暂无法补充');
      const fields=draft.route==='unavailable'?{conclusion:2000}:{conclusion:2000,action_plan:2000,owner:128,follow_up:500};
      if(Object.keys(fields).some(f=>!draft[f].trim()))throw new Error(draft.route==='unavailable'?'请填写暂无法补充的原因':'请填写结论、处理安排、责任人和后续安排');
      if(Object.entries(fields).some(([f,max])=>draft[f].trim().length>max))throw new Error('填写内容超出长度限制，请精简后再提交');
      const options=historicalEvidenceOptions(c),evidence=draft.route==='existing_evidence'?draft.evidence.map(key=>options.find(o=>o.key===key)?.reference):[];
      if(draft.route==='existing_evidence'&&(!evidence.length||evidence.some(e=>!e)))throw new Error('请关联至少一处当前绑定账表中的有效依据');
      if(evidence.length>20)throw new Error('最多关联 20 处依据，请保留直接支持方案的来源');
      action='save_historical_issue_plan';id=c.job.object_id;version=c.job.version;
      payload={issue_key:c.issue.issue_key,expected_plan_version:c.plan?.version||0,route:draft.route,...Object.fromEntries(Object.keys(fields).map(f=>[f,draft[f].trim()])),...(draft.route==='existing_evidence'?{evidence}:{})};
    }
    historicalPlansUI.pending=pending;draft.error='';
    result=await command(action,id,version,payload);
    if(epoch!==state.epoch||historicalPlanContext()?.key!==c.key)return;
    if(!result?.effect?.object?.object_id||!Number.isInteger(result.effect.object.version))throw new Error('未取得完整处理记录，请刷新核对服务端状态，草稿仍保留');
    historicalPlansUI.drafts.delete(c.key);
    const flow=historicalIssueFlow(c.job);
    if(flow.done)historicalPlansUI.selection.delete(c.jobKey);
    notify(flow.done?'本轮处理意见已全部记录，请按“下一步工作”继续。期初阻断仍保留。':`已记录，期初阻断仍保留。还有 ${flow.pending.length} 项待处理，请点击“处理下一项”。`);
  } catch(error) {
    if(epoch===state.epoch&&historicalPlanContext()?.key===c.key){draft.error=error.message;render();}
    throw error;
  } finally {
    if(historicalPlansUI.pending===pending)historicalPlansUI.pending=null;
    if(epoch===state.epoch&&historicalPlanContext()?.key===c.key)render();
  }
  if(result&&epoch===state.epoch){render();(historicalIssueFlow().done?$('historyHandoff'):document.querySelector('[data-action="history-next-item"]'))?.focus();}
  return result;
}

function historicalSourceStatus(artifact) {
  const job=state.overview.historical_preparation;
  if(!job||!job.data.sources.some(s=>s.artifact_id===artifact.object_id&&s.version===artifact.version))return '';
  return `${badge(historicalStatus(job.status),['QUEUED','RUNNING'].includes(job.status)?'blue':'yellow')}${job.data.result?'<br><button class="text" data-action="historical-details">查看历史提取结果</button>':''}`;
}

function scheduleHistoricalPoll() {
  clearTimeout(historicalPollTimer);
  if(!['QUEUED','RUNNING'].includes(state.overview?.historical_preparation?.status))return;
  historicalPollTimer=setTimeout(pollHistorical,1500);
}
async function pollHistorical() {
  const epoch=state.epoch,sequence=state.loadSequence,selected=scope();
  if(!selected)return;
  // Never replace an in-progress form, an open dialog or another scope's response.
  if(state.busy||document.hidden||$('dialog').open||document.activeElement?.matches('input,textarea,select,[contenteditable="true"]'))return scheduleHistoricalPoll();
  try {
    const next=await request('/api/v1/workbench',{scope:selected});
    if(epoch!==state.epoch||sequence!==state.loadSequence||state.busy||$('dialog').open||document.activeElement?.matches('input,textarea,select,[contenteditable="true"]'))return;
    const old=state.overview.historical_preparation;
    if(next.historical_preparation?.version!==old?.version||next.historical_preparation?.status!==old?.status) {
      const expanded=$('stages')?.classList.contains('expanded'),focused=document.activeElement?.dataset.action;
      state.overview=next;
      if(state.view!=='history')render();
      if(expanded&&$('stages'))$('stages').classList.add('expanded');
      if(focused)document.querySelector(`[data-action="${focused}"]`)?.focus({preventScroll:true});
      if(!['QUEUED','RUNNING'].includes(next.historical_preparation?.status))notify('历史账表处理状态已更新：'+historicalStatus(next.historical_preparation?.status));
    }
  } catch(error) {
    if(epoch===state.epoch&&state.overview)notify('暂时无法读取后台状态，请检查服务连接。原件和已保存任务不会因关闭页面丢失。',true);
  } finally {scheduleHistoricalPoll();}
}

function installHistoricalActions() {
  actions['historical-details']=showHistoricalDetails;
  actions['history-handling']=()=>{$('historyHandling')?.focus();};
  actions['history-source']=showHistoricalSource;
  actions['upload-history']=()=>chooseBaselineFile('history');
  actions['history-select-issue']=button=>{
    if(historicalPlansUI.pending)return;
    const c=historicalPlanContext(),index=Number(button.dataset.historyIndex);
    if(!c||!Number.isInteger(index)||!c.issues[index])return;
    historicalPlansUI.selection.set(c.jobKey,index);render();$('historyCurrentIssue')?.focus({preventScroll:true});
  };
  actions['history-current-files']=button=>showArtifacts('business',button);
  actions['history-next-item']=()=>{
    const c=historicalPlanContext(),flow=historicalIssueFlow();if(!c)return;
    if(flow.pending.length)historicalPlansUI.selection.set(c.jobKey,flow.pending[0]);else historicalPlansUI.selection.delete(c.jobKey);
    render();(flow.done?$('historyHandoff'):$('historyCurrentIssue'))?.focus();
  };
  actions['history-next-work']=button=>{
    if(!historicalIssueFlow().done)return;
    const next=historicalNextWork();
    if(next.mode==='materials')return openMaterialWorkbench();
    if(next.mode==='review'){state.view='historical';return actions['history-select-issue']({dataset:{historyIndex:String(next.index)}});}
    if(next.mode==='category'){state.view='current';state.category=next.category;closeDialog();render();const heading=document.querySelector('.category-detail h2');if(heading){heading.tabIndex=-1;heading.focus();}return;}
    showArtifacts('business',button);
  };
  actions['edit-history-plan']=()=>{
    const c=historicalPlanContext();if(!canSubmitHistoricalPlan(c))return;
    historicalPlanDraft(c).editing=true;render();document.querySelector('[name="historicalRoute"]')?.focus({preventScroll:true});
  };
  actions['reload-history-plan']=()=>{
    const c=historicalPlanContext();if(!c)return;
    historicalPlansUI.drafts.delete(c.key);render();notify('已重新载入服务端最新处理记录，未提交草稿已丢弃。');
  };
  actions['save-history-plan']=()=>submitHistoricalPlan(false);
  actions['review-history-plan']=()=>submitHistoricalPlan(true);
  document.addEventListener('input',updateHistoricalPlanInput);
  document.addEventListener('change',updateHistoricalPlanInput);
  document.addEventListener('submit',event=>{
    if(!['historicalPlanForm','historicalReviewForm'].includes(event.target.id))return;
    event.preventDefault();
    const c=historicalPlanContext();if(!c||event.target.dataset.historyFormKey!==c.key)return;
    exclusive(()=>submitHistoricalPlan(event.target.id==='historicalReviewForm'));
  });
  actions['retry-historical']=async()=>{const b=state.overview.baseline;await command('prepare_historical',b.object_id,b.version);};
  actions['select-historical']=async()=>{const b=state.overview.baseline,ids=[$('historySource0').value,$('historySource1').value];if(!ids[0]||!ids[1]||ids[0]===ids[1])throw new Error('请选择两份不同的余额表和序时账');await command('prepare_historical',b.object_id,b.version,{artifact_ids:ids});};
  actions['confirm-historical']=async()=>{
    const flags=Object.fromEntries([...document.querySelectorAll('[data-history-confirm]')].map(n=>[n.dataset.historyConfirm,n.checked]));
    if(Object.keys(flags).length!==3||Object.values(flags).some(v=>!v))return;
    const b=state.overview.baseline,j=state.overview.historical_preparation;
    await command('confirm_baseline',b.object_id,b.version,{...flags,historical_preparation:{object_id:j.object_id,version:j.version}});
  };
}

const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../static/operator-historical.js'),'utf8');
function api(){const context=vm.createContext({esc:s=>String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;'),amount:s=>Number(s).toFixed(2),table:(head,rows)=>`<table>${head.join('|')}${rows.join('')}</table>`,state:{overview:{historical_preparation:{data:{}}}}});vm.runInContext(source+';globalThis.api={historicalBalanceTable,historicalStatus,renderHistoricalIssue,historicalAmount};',context);return context.api;}
test('unbalanced historical totals retain both sides, never claim they are equal',()=>{
  const html=api().historicalBalanceTable({source_totals:{debit:'100.00',credit:'99.00'},totals:{debit:'120.00',credit:'119.00'},balances:[]});
  for(const n of ['100.00','99.00','120.00','119.00'])assert(html.includes(n));
  assert.doesNotMatch(html,/合计各/);
});
test('pending input and human review are not labelled as running',()=>{
  const a=api();assert.equal(a.historicalStatus('WAITING_INPUT'),'等待另一份账表');assert.equal(a.historicalStatus('NEEDS_REVIEW'),'有问题待核实');assert.equal(a.historicalStatus('FAILED'),'处理失败');
});
test('issue data and recommendations are directly visible and untrusted text is escaped',()=>{
  const html=api().renderHistoricalIssue({title:'科目 9999 未在余额表列出',message:'核对来源',evidence:{rows:[{date:'2025-12-31',voucher_number:'记-002',summary:'<img src=x onerror=alert(1)>',account_code:'9999',account_name:'测试',debit:'-100.00',credit:'0.00',anchor:{row:6}}],advice:['核对记-002，不自动补零'],completion_condition:'核对依据',summary:{account_names:['测试'],record_count:1,debit_positive:'0.00',debit_negative:'-100.00',credit_positive:'0.00',credit_negative:'0.00',net_movement:'-100.00'}}},0);
  for(const text of ['-100.00','记-002','2025-12-31','建议怎么处理','不自动补零','未列示','data-action="history-source"'])assert(html.includes(text));
  assert.doesNotMatch(html,/<details|<img/);assert.match(html,/&lt;img/);
});
test('missing evidence stays explicit rather than displaying invented balances',()=>{
  const html=api().renderHistoricalIssue({title:'问题',message:'需要余额依据',anchors:[]},0);
  assert.match(html,/暂无可唯一定位/);assert.doesNotMatch(html,/0\.00/);
});
test('historical amounts keep cents without floating point and do not turn missing values into zero',()=>{
  const a=api();assert.equal(a.historicalAmount('-99999999999999.99'),'-99,999,999,999,999.99');
  assert.equal(a.historicalAmount('0.00'),'0.00');assert.equal(a.historicalAmount(null),'未提供');
});
test('bounded evidence explicitly directs users to the original without implying rows are missing',()=>{
  const html=api().renderHistoricalIssue({title:'核对问题',evidence:{rows:[],omitted_rows:20,contexts_omitted:1,advice:['核对原件']}},0);
  assert.match(html,/20 条问题明细、1 张凭证上下文未展开/);assert.match(html,/请下载原件/);assert.doesNotMatch(html,/暂无可唯一定位/);
});

const clone=value=>JSON.parse(JSON.stringify(value));
function issueFixture() {
  const journal={artifact_id:'journal',version:1,sha256:'journal-hash',filename:'序时账.xls'};
  const balance={artifact_id:'balance',version:2,sha256:'balance-hash',filename:'余额表.xls'};
  const issue=n=>({issue_key:`missing-${n}`,code:'UNMAPPED_ACCOUNT',title:`科目 ${n} 未列示`,message:'须核对余额',
    evidence:{advice:['核对调整及最终余额，不自动补零'],related_vouchers:[],rows:[{source:journal,anchor:{region:`序时账!第${n}行`,row:n},date:'2025-12-31',voucher_number:'记-075',summary:'调整记录',account_code:String(n),account_name:'借款',debit:'-100.00',credit:'0.00',cells:[]}]}});
  return {object_id:'job',version:3,status:'NEEDS_REVIEW',data:{input_hash:'input-hash',sources:[journal,balance],
    step:'等待人工核实',finished_at:'2026-09-06T07:18:07Z',parser_version:'v1',result:{issues:[issue(73),issue(147)],checks:[],
      start_period:'2025-01',end_period:'2025-12',opening_period:'2026-01',passed_checks:1139,entry_count:2472,voucher_count:607,account_count:255,
      balance_source:balance,balances:[{account_code:'2701',account_name:'长期应付款',source_anchor:{region:'余额表!第30行',row:30},closing_debit:'0.00',closing_credit:'100.00',opening_debit:'0.00',opening_credit:'100.00'}],
      totals:{debit:'100.00',credit:'100.00'},source_totals:{debit:'100.00',credit:'100.00'},movement_totals:{debit:'100.00',credit:'100.00'}}}};
}
function workflow() {
  const listeners={},nodes=new Map(),calls=[],notices=[];
  const state={role:'accountant',user:{user_id:'alice'},epoch:1,view:'historical',busy:false,
    overview:{scope:{legal_entity_id:'a',accounting_period_id:'2026-01'},period:{status:'OPEN'},historical_preparation:issueFixture(),historical_issue_plans:[]}};
  const context=vm.createContext({state,actions:{},scope:()=>state.overview?.scope,scopeKey:s=>JSON.stringify(s),
    readonly:()=>state.role==='viewer'||state.overview?.period.status!=='OPEN',esc:s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
    table:(head,rows)=>`<table>${head.join('|')}${rows.join('')}</table>`,amount:s=>s,objectButton:(id,label)=>`<button class="text" data-object="${id}">${label}</button>`,
    badge:(label,color)=>`<span class="badge ${color}">${label}</span>`,primary:(action,label,disabled)=>`<button class="primary" data-action="${action}" ${disabled?'disabled':''}>${label}</button>`,
    taskShell:(title,body,action)=>`<h2>${title}</h2>${body}${action}`,baselineArtifacts:()=>[],
    document:{addEventListener:(type,fn)=>(listeners[type]??=[]).push(fn),querySelector:()=>null,querySelectorAll:()=>[],activeElement:null},
    $:id=>nodes.get(id),render:()=>{},closeDialog:()=>{},window:{scrollTo(){}},notify:(...args)=>notices.push(args),
    exclusive:async fn=>{if(state.busy)return;state.busy=true;try{return await fn();}finally{state.busy=false;}},
    chooseBaselineFile:role=>calls.push(['upload',role]),showArtifacts:(filter,button)=>calls.push(['files',filter,button]),
    command:async(...args)=>{calls.push(clone(args));return context.transport(...args);}});
  vm.runInContext(source+`;globalThis.api={historicalIssueFlow,historicalNextWork,renderHistoricalTask,renderHistoricalDetails,installHistoricalActions,historicalPlanContext,historicalPlanDraft,historicalEvidenceOptions,historicalEvidenceKey,resetHistoricalPlans,canReviewHistoricalPlan,updateHistoricalPlanInput};`,context);
  context.transport=async(action,id,version,payload)=>{
    const object=action==='save_historical_issue_plan'?{object_id:'plan-'+payload.issue_key,version:payload.expected_plan_version+1,status:payload.route==='unavailable'?'UNAVAILABLE_RECORDED':'SUBMITTED',created_at:'now',created_by:'alice',stale:false,
      data:{...clone(payload),historical_preparation:{object_id:id,version},input_hash:'input-hash',submitted_by:'alice',submitted_at:'2026-09-06T08:00:00Z'}}:
      {...clone(state.overview.historical_issue_plans[0]),version:version+1,status:payload.decision==='approved'?'REVIEWED':'RETURNED',data:{...state.overview.historical_issue_plans[0].data,review:{...payload,reviewed_by:state.user.user_id,reviewed_at:'now'}}};
    state.overview.historical_issue_plans=[...state.overview.historical_issue_plans.filter(p=>p.object_id!==object.object_id),object];return {effect:{object}};
  };
  context.api.installHistoricalActions();
  return {...context.api,state,calls,notices,nodes,listeners,actions:context.actions,context,
    draft:()=>context.api.historicalPlanDraft(context.api.historicalPlanContext()),
    html:()=>context.api.renderHistoricalDetails(),click:action=>context.actions[action]({dataset:{action}})};
}
function fill(a,route='existing_evidence') {
  Object.assign(a.draft(),{route,conclusion:'核实结论',action_plan:'取得明细并复核',owner:'负责会计',follow_up:'9月10日跟进',dirty:true});
  if(route==='existing_evidence')a.draft().evidence=[a.historicalEvidenceOptions(a.historicalPlanContext())[0].key];
}
test('recorded issues hand off to the next task without completing financial validation',async()=>{
  const a=workflow(),before=JSON.stringify(a.state.overview.historical_preparation);
  fill(a,'unavailable');await a.click('save-history-plan');
  assert.equal(a.historicalIssueFlow().count,1);assert.match(a.html(),/处理下一项/);
  a.click('history-next-item');assert.equal(a.historicalPlanContext().index,1);
  fill(a,'unavailable');await a.click('save-history-plan');
  assert.equal(a.historicalIssueFlow().done,true);assert.match(a.html(),/本轮处理意见已记录 2 \/ 2/);
  assert.doesNotMatch(a.html(),/id="historicalPlanForm"/);
  assert.equal((a.html().match(/class="primary"/g)||[]).length,1);
  assert.equal(JSON.stringify(a.state.overview.historical_preparation),before);
  a.click('history-next-work');assert.equal(a.calls.at(-1)[0],'files');
  const job=a.state.overview.historical_preparation;
  assert.match(a.renderHistoricalTask(job),/history-next-work/);
  for(const status of ['RETURNED','UNKNOWN']){a.state.overview.historical_issue_plans[0].status=status;assert.equal(a.historicalIssueFlow().done,false);}
  a.state.overview.historical_issue_plans[0].status='REVIEWED';
  a.state.overview.historical_issue_plans[0].stale=true;assert.equal(a.historicalIssueFlow().done,false);
});
test('next work targets only current-period extractable files, then actual category issues',()=>{
  const a=workflow();a.state.overview.data_readiness={categories:[{id:'bank',name:'银行与票据',artifact_ids:['file'],issues:[{id:'problem'}]}]};
  a.state.overview.artifacts=[{object_id:'file',status:'ACTIVE',data:{observed_period:'2026-01',parse_status:'RECEIVED'}}];
  assert.equal(a.historicalNextWork().mode,'files');assert.match(a.historicalNextWork().label,/继续提取1月/);
  a.state.overview.artifacts[0].data.observed_period='2025-12';assert.equal(a.historicalNextWork().mode,'category');
  a.state.overview.artifacts[0].data.parse_status='PARSED';assert.equal(a.historicalNextWork().category,'bank');
});
test('eligible reviewer handoff opens the correct submitted issue from the workbench',async()=>{
  const a=workflow();fill(a,'unavailable');await a.click('save-history-plan');a.click('history-next-item');
  fill(a);await a.click('save-history-plan');a.state.user.user_id='bob';a.state.view='current';
  assert.equal(a.historicalNextWork().mode,'review');a.click('history-next-work');
  assert.equal(a.state.view,'historical');assert.equal(a.historicalPlanContext().index,1);
});
test('review task has one clear action and no repeated historical upload; waiting input keeps one upload',()=>{
  const a=workflow(),job=a.state.overview.historical_preparation,html=a.renderHistoricalTask(job);
  assert.match(html,/处理 2 项核对问题/);assert.doesNotMatch(html,/data-action="upload-history"/);
  assert.equal((html.match(/class="primary"/g)||[]).length,1);
  job.status='WAITING_INPUT';job.data.result=null;
  assert.equal((a.renderHistoricalTask(job).match(/data-action="upload-history"/g)||[]).length,1);
});
test('one issue is expanded with three paths and direct facts before the processing form',()=>{
  const a=workflow(),html=a.html();
  for(const text of ['第 1 项 / 共 2 项','补充材料','依据现有资料提交方案','暂无法补充','继续整理本期资料'])assert(html.includes(text));
  assert.equal((html.match(/class="history-issue"/g)||[]).length,1);
  assert(html.indexOf('记-075')<html.indexOf('id="historicalPlanForm"'));
  assert.doesNotMatch(html,/data-action="upload-history"/);
  a.draft().route='upload';assert.equal((a.html().match(/class="primary"/g)||[]).length,1);
  assert.match(a.html(),/data-action="upload-history"/);
});
test('evidence choices only include bound versions and real anchors, including balance rows',()=>{
  const a=workflow(),c=a.historicalPlanContext();
  c.issue.evidence.rows.push({...clone(c.issue.evidence.rows[0]),source:{artifact_id:'foreign',version:1},anchor:{region:'他表!第2行',row:2}});
  c.issue.evidence.rows.push({...clone(c.issue.evidence.rows[0]),source:{...c.job.data.sources[0],version:9}});
  c.issue.evidence.rows.push({...clone(c.issue.evidence.rows[0]),anchor:{region:'序时账!第3行',row:4}});
  const options=a.historicalEvidenceOptions(c);assert.equal(options.length,2);
  assert.deepEqual(clone(options.map(o=>o.reference.artifact_id)),['journal','balance']);
  assert(options.some(o=>o.label.includes('长期应付款')));
});
test('missing fields or unavailable evidence never sends a command',async()=>{
  const a=workflow();a.draft().route='existing_evidence';await assert.rejects(a.click('save-history-plan'),/填写/);
  fill(a);a.draft().evidence=[];await assert.rejects(a.click('save-history-plan'),/依据/);
  a.draft().evidence=['forged'];await assert.rejects(a.click('save-history-plan'),/依据/);
  assert.equal(a.calls.length,0);
});
test('save submits exact versioned references, restores server record and preserves original blockers',async()=>{
  const a=workflow(),before=JSON.stringify(a.state.overview.historical_preparation);fill(a);
  await a.click('save-history-plan');
  const [action,id,version,payload]=a.calls[0];assert.equal(action,'save_historical_issue_plan');assert.equal(id,'job');assert.equal(version,3);
  assert.equal(payload.issue_key,'missing-73');assert.equal(payload.expected_plan_version,0);
  assert.deepEqual(payload.evidence,[{artifact_id:'journal',version:1,anchor:{region:'序时账!第73行',row:73}}]);
  assert.equal(JSON.stringify(a.state.overview.historical_preparation),before);
  a.resetHistoricalPlans();const html=a.html();
  for(const text of ['方案已提交，待复核','负责会计','9月10日跟进','2026-09-06','0 金额变更','未解除原始阻断'])assert(html.includes(text));
  assert.match(a.notices.at(-1)[0],/已记录，期初阻断仍保留/);assert.doesNotMatch(html,/badge green|id="historicalPlanForm"/);
});
test('unavailable branch only asks for reason and never submits a client owner',async()=>{
  const a=workflow();a.draft().route='unavailable';
  await assert.rejects(a.click('save-history-plan'),/原因/);assert.equal(a.calls.length,0);
  a.draft().conclusion='客户无法补充';
  for(const label of ['无法补充原因','责任人：alice','自动记录'])assert(a.html().includes(label));
  assert.doesNotMatch(a.html(),/data-history-field="(?:owner|action_plan|follow_up)"/);
  // Hidden fields from a previous proposal must not leak into this route.
  Object.assign(a.draft(),{owner:'forged',action_plan:'old',follow_up:'old'});
  await a.click('save-history-plan');
  assert.deepEqual(a.calls[0][3],{issue_key:'missing-73',expected_plan_version:0,route:'unavailable',conclusion:'客户无法补充'});
  assert.match(a.html(),/暂无法补充，已记录/);assert.doesNotMatch(a.html(),/已解决|badge green/);
});
test('issue switching retains unsaved input, while job version, scope and reset isolate it',()=>{
  const a=workflow();fill(a,'unavailable');
  a.actions['history-select-issue']({dataset:{historyIndex:'1'}});assert.equal(a.draft().conclusion,'');
  a.actions['history-select-issue']({dataset:{historyIndex:'0'}});assert.equal(a.draft().conclusion,'核实结论');
  a.state.overview=clone(a.state.overview);a.html();assert.equal(a.draft().conclusion,'核实结论');
  a.state.overview.historical_preparation.version=4;assert.equal(a.draft().conclusion,'');
  a.state.overview.scope.legal_entity_id='b';assert.equal(a.draft().conclusion,'');
  a.resetHistoricalPlans();assert.equal(a.draft().conclusion,'');
});
test('only another authorized accountant reviewer or admin can review a submitted current plan',async()=>{
  const a=workflow();fill(a);await a.click('save-history-plan');
  let c=a.historicalPlanContext();assert.equal(a.canReviewHistoricalPlan(c),false);
  for(const role of ['accountant','reviewer','admin']){a.state.role=role;a.state.user.user_id='bob';assert.equal(a.canReviewHistoricalPlan(c),true);}
  a.state.role='operator';assert.equal(a.canReviewHistoricalPlan(c),false);
  a.state.role='reviewer';a.state.user=null;assert.equal(a.canReviewHistoricalPlan(c),false);
  a.state.user={user_id:'bob'};a.state.overview.period.status='LOCKED';assert.equal(a.canReviewHistoricalPlan(c),false);
});
test('review needs a note, submits the plan version and never claims balance approval',async()=>{
  for(const decision of ['approved','returned']){
    const a=workflow();fill(a);await a.click('save-history-plan');a.state.user.user_id='bob';
    await assert.rejects(a.click('review-history-plan'),/复核意见/);
    Object.assign(a.draft(),{review_note:'已检查所关联的依据',review_decision:decision});
    await a.click('review-history-plan');
    assert.deepEqual(a.calls.at(-1),['review_historical_issue_plan','plan-missing-73',1,{decision,note:'已检查所关联的依据'}]);
    assert.match(a.html(),decision==='approved'?/方案复核通过/:/退回补充说明/);
    assert.doesNotMatch(a.html(),/余额核实通过|badge green/);
    assert.equal(a.state.overview.historical_preparation.status,'NEEDS_REVIEW');
  }
});
test('read-only and stale jobs expose records but no writable controls',async()=>{
  const a=workflow();fill(a);await a.click('save-history-plan');
  a.state.role='viewer';assert.doesNotMatch(a.html(),/id="historicalPlanForm"|id="historicalReviewForm"|data-action="upload-history"|data-action="edit-history-plan"/);
  await assert.rejects(a.click('save-history-plan'),/只读|只允许查看/);
  a.state.role='accountant';a.state.overview.historical_preparation.status='STALE';a.state.overview.historical_issue_plans[0].stale=true;
  assert.match(a.html(),/来源已变化/);assert.doesNotMatch(a.html(),/id="historicalPlanForm"|id="historicalReviewForm"/);
});
test('old plan is read-only after recheck; a new plan uses the new job and zero expected version',async()=>{
  const a=workflow();fill(a);await a.click('save-history-plan');
  a.state.overview.historical_preparation.version=4;a.state.overview.historical_issue_plans[0].stale=true;
  const html=a.html();assert.match(html,/旧处理记录/);assert.match(html,/新校验/);
  fill(a,'unavailable');await a.click('save-history-plan');
  assert.equal(a.calls.at(-1)[2],4);assert.equal(a.calls.at(-1)[3].expected_plan_version,0);
});
test('concurrent server update preserves draft and rejects stale form submission',async()=>{
  const a=workflow();fill(a);await a.click('save-history-plan');a.click('edit-history-plan');fill(a);
  a.state.overview.historical_issue_plans[0].version++;
  assert.match(a.html(),/记录版本已更新/);assert.equal(a.draft().conclusion,'核实结论');
  await assert.rejects(a.click('save-history-plan'),/版本已更新/);assert.equal(a.calls.length,1);
});
test('pending save prevents duplicates; rejected or incomplete responses retain the draft',async()=>{
  const a=workflow();fill(a);let release;
  a.context.transport=()=>new Promise(resolve=>release=resolve);
  const pending=a.click('save-history-plan');await a.click('save-history-plan');assert.equal(a.calls.length,1);
  release({effect:{}});await assert.rejects(pending,/完整/);
  assert.equal(a.draft().conclusion,'核实结论');assert.equal(a.state.overview.historical_issue_plans.length,0);
  a.context.transport=async()=>{throw new Error('服务拒绝');};
  await assert.rejects(a.click('save-history-plan'),/服务拒绝/);assert.equal(a.draft().conclusion,'核实结论');
});
test('late save after scope change cannot clear a new scope draft or show old success',async()=>{
  const a=workflow();fill(a);let release;a.context.transport=()=>new Promise(resolve=>release=resolve);
  const pending=a.click('save-history-plan');a.state.epoch++;a.state.overview.scope.legal_entity_id='b';fill(a,'unavailable');
  release({effect:{object:{object_id:'old',version:1,status:'SUBMITTED'}}});await pending;
  assert.equal(a.draft().conclusion,'核实结论');assert.equal(a.notices.length,0);
});
test('upload and continue controls reuse existing source flows without pretending to advance a stage',()=>{
  const a=workflow(),before=JSON.stringify(a.state.overview);a.click('upload-history');a.click('history-current-files');
  assert.equal(a.calls[0][0],'upload');assert.equal(a.calls[0][1],'history');assert.equal(a.calls[1][1],'business');
  assert.equal(JSON.stringify(a.state.overview),before);
});
test('reviewers cannot create plans and another author cannot edit existing records',async()=>{
  const a=workflow();a.state.role='reviewer';assert.doesNotMatch(a.html(),/id="historicalPlanForm"/);
  fill(a);await assert.rejects(a.click('save-history-plan'),/仅经办人员、会计或管理员/);
  a.state.role='accountant';await a.click('save-history-plan');a.state.user.user_id='bob';
  assert.doesNotMatch(a.html(),/data-action="edit-history-plan"/);a.click('edit-history-plan');
  assert.equal(a.draft().editing,false);assert.match(a.html(),/id="historicalReviewForm"/);
});
test('field lengths and evidence limits mirror the server constraints before submission',async()=>{
  const a=workflow();fill(a);
  for(const [field,max] of Object.entries({conclusion:2000,action_plan:2000,owner:128,follow_up:500})){
    const old=a.draft()[field];a.draft()[field]='文'.repeat(max+1);await assert.rejects(a.click('save-history-plan'),/长度/);a.draft()[field]=old;
  }
  fill(a);a.draft().evidence=Array(21).fill(a.draft().evidence[0]);
  await assert.rejects(a.click('save-history-plan'),/20/);assert.equal(a.calls.length,0);
});
test('input/change events retain drafts and route changes render the current business action',()=>{
  const a=workflow(),form={dataset:{historyFormKey:a.historicalPlanContext().key}};
  const input=(field,value,type='input')=>{const event={type,target:{dataset:{historyField:field},value,closest:()=>form}};a.listeners[type].forEach(fn=>fn(event));};
  input('route','unavailable','change');input('conclusion','不能取得旧资料');input('owner','会计甲');
  assert.match(a.html(),/记录暂无法补充/);assert.match(a.html(),/不能取得旧资料/);
  input('route','existing_evidence','change');assert.match(a.html(),/提交处理方案/);assert.equal(a.draft().conclusion,'不能取得旧资料');
  const key=a.historicalEvidenceOptions(a.historicalPlanContext())[0].key;
  a.listeners.change.forEach(fn=>fn({type:'change',target:{dataset:{historyEvidence:key},checked:true,closest:()=>form}}));
  assert.deepEqual(clone(a.draft().evidence),[key]);
  form.dataset.historyFormKey='old-scope';input('owner','不得覆盖');assert.equal(a.draft().owner,'会计甲');
});
test('native form submit dispatches a save, not a DOM event as business payload',async()=>{
  const a=workflow();fill(a,'unavailable');let prevented=false;
  a.listeners.submit[0]({target:{id:'historicalPlanForm',dataset:{historyFormKey:a.historicalPlanContext().key}},preventDefault(){prevented=true;}});
  await new Promise(resolve=>setImmediate(resolve));assert(prevented);assert.equal(a.calls.length,1);
  assert.equal(a.calls[0][0],'save_historical_issue_plan');assert.equal(a.calls[0][1],'job');assert.equal(a.calls[0][3].owner,undefined);
});
test('saved text and raw references are escaped rather than interpreted as markup',async()=>{
  const a=workflow();fill(a,'unavailable');a.draft().conclusion='<img src=x onerror=alert(1)>';
  assert.doesNotMatch(a.html(),/<img/);await a.click('save-history-plan');
  assert.match(a.html(),/&lt;img/);assert.doesNotMatch(a.html(),/<img/);
});

// Exercise the actual operator router/auth/command integration without a server
// or the retained financial database. Only transport and visual chrome are stubbed.
function integratedApp() {
  const listeners={},nodes=new Map(),requests=[];
  const element=id=>({id,value:'',innerHTML:'',textContent:'',dataset:{},isConnected:true,disabled:false,open:false,
    classList:{add(){},remove(){},contains(){return false;}},addEventListener(){},focus(){},replaceChildren(){},close(){this.open=false;},removeAttribute(){}});
  const context=vm.createContext({location:{protocol:'file:'},crypto:{randomUUID:()=>String(requests.length)},clearTimeout(){},setTimeout(){},
    localStorage:{getItem(){return null;},setItem(){}},window:{scrollY:120,scrollTo(){}},
    document:{activeElement:null,addEventListener:(type,fn)=>(listeners[type]??=[]).push(fn),
      getElementById:id=>{if(!nodes.has(id))nodes.set(id,element(id));return nodes.get(id);},
      querySelector:selector=>selector==='.topbar'?element('topbar'):null,querySelectorAll:()=>[]},
    fetch:async(url,options)=>{requests.push([url,options]);return context.transport(url,options);}});
  const operator=fs.readFileSync(path.join(__dirname,'../static/operator.js'),'utf8');
  vm.runInContext(source+'\n'+operator+`;globalThis.a={state,actions,loadPortfolio,selectScope,clearSession,command,historicalPlanDraft,historicalPlanContext,render,showArtifacts,resetHistoricalPlans};render=()=>{};`,context);
  const {state}=context.a;
  const scope={tenant_id:'test',organization_id:'test',legal_entity_id:'甲',ledger_id:'ledger',accounting_period_id:'2026-01',baseline_id:'baseline'};
  const overview={scope,period:{status:'OPEN'},artifacts:[],historical_preparation:issueFixture(),historical_issue_plans:[],
    data_readiness:{baseline_sources:{balance:[],close:[]}}};
  state.scopes=[{scope,baseline:{validation:{status:'INVALID'}},blockers:[],pending_confirmation_cards:0}];state.selected=0;state.role='accountant';state.user={user_id:'alice'};state.overview=clone(overview);
  const scopes=clone(state.scopes);
  context.transport=async url=>({ok:true,json:async()=>url.endsWith('/me')?{user_id:'alice',role:'accountant',csrf_token:'csrf'}:url.endsWith('/portfolio')?{scopes:clone(scopes)}:clone(overview)});
  return {a:context.a,context,state,requests,nodes,listeners,overview};
}
test('auth stores the actual user id; session and scope switching clear the unsaved plan drafts',async()=>{
  const {a,state,context}=integratedApp();await a.loadPortfolio();assert.equal(state.user.user_id,'alice');
  let d=a.historicalPlanDraft(a.historicalPlanContext());Object.assign(d,{dirty:true,owner:'旧草稿'});
  await a.selectScope(0);assert.equal(a.historicalPlanDraft(a.historicalPlanContext()).owner,'');
  d=a.historicalPlanDraft(a.historicalPlanContext());d.owner='新草稿';a.clearSession();assert.equal(state.user,null);
  await a.loadPortfolio();assert.equal(a.historicalPlanDraft(a.historicalPlanContext()).owner,'');
});
test('actual command rejects incomplete plan effects and retains retry identity without success feedback',async()=>{
  const {a,state,context,requests,nodes}=integratedApp();
  context.transport=async()=>({ok:true,json:async()=>({command:{status:'SUCCEEDED'},effect:{}})});
  const call=()=>a.command('save_historical_issue_plan','job',3,{issue_key:'missing-73'});
  await assert.rejects(call(),/完整处理记录/);await assert.rejects(call(),/完整处理记录/);
  assert.equal(JSON.parse(requests[0][1].body).idempotency_key,JSON.parse(requests[1][1].body).idempotency_key);
  assert.doesNotMatch(nodes.get('notice').textContent,/操作已记录/);assert.equal(state.overview.historical_issue_plans.length,0);
});
test('server failures keep the command identity for a safe retry',async()=>{
  const {a,context,requests}=integratedApp();
  context.transport=async()=>({ok:false,status:503,json:async()=>({error:{message:'服务临时不可用'}})});
  const call=()=>a.command('save_historical_issue_plan','job',3,{issue_key:'missing-73'});
  await assert.rejects(call(),/临时不可用/);await assert.rejects(call(),/临时不可用/);
  assert.equal(JSON.parse(requests[0][1].body).idempotency_key,JSON.parse(requests[1][1].body).idempotency_key);
});
test('operators may record plans but cannot review them',()=>{
  const f=workflow();f.state.role='operator';
  assert.match(f.renderHistoricalDetails(),/historicalPlanForm/);
  assert.equal(f.canReviewHistoricalPlan(f.historicalPlanContext()),false);
});
test('native delegated router dispatches upload and current-files buttons with explicit business arguments',async()=>{
  const {a,state,context,listeners,nodes}=integratedApp();
  vm.runInContext(`chooseBaselineFile=role=>{globalThis.uploadedRole=role;};`,context);
  const button={dataset:{action:'upload-history'},disabled:false};
  listeners.click[0]({target:{closest:()=>button}});await new Promise(resolve=>setImmediate(resolve));
  assert.equal(context.uploadedRole,'history');
  state.view='historical';button.dataset.action='history-current-files';
  listeners.click[0]({target:{closest:()=>button}});await new Promise(resolve=>setImmediate(resolve));
  assert.equal(state.view,'artifacts');assert.equal(state.filesFilter,'business');
  assert.equal(state.filesReturn.view,'historical');a.actions['return-files']();assert.equal(state.view,'historical');
});
test('secondary upload entry is absent during review and remains unique for empty and waiting scopes',()=>{
  const {a,state,nodes,context}=integratedApp();
  vm.runInContext(`renderContext=()=>'';renderProgress=()=>'';renderStructure=()=>'';renderResults=()=>'';renderTask=()=>state.overview.historical_preparation?renderHistoricalTask(state.overview.historical_preparation):'';taskShell=(title,body,action)=>body+action;`,context);
  const nav={insertAdjacentHTML(where,html){nodes.get('workspace').innerHTML+=html;}};
  context.document.querySelector=selector=>selector==='.secondary-nav'?nav:null;
  for(const status of ['NEEDS_REVIEW','WAITING_INPUT',null]){
    state.overview.historical_preparation=status?{...issueFixture(),status}:null;
    if(status==='WAITING_INPUT')state.overview.historical_preparation.data.result=null;
    a.render();const html=nodes.get('workspace').innerHTML;
    assert.equal((html.match(/data-action="upload-history"/g)||[]).length,status==='NEEDS_REVIEW'?0:1);
  }
});

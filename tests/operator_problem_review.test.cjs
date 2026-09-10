const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../static/operator-problem-review.js'),'utf8');
function fixture(){
 const scope={tenant_id:'t',organization_id:'o',legal_entity_id:'e',ledger_id:'l',accounting_period_id:'2026-01',baseline_id:'b'};
 const job={object_id:'job',version:2,status:'FAILED',valid:true,data:{task_id:'task',artifact_id:'a',title:'发票复核',result:{message:'读取失败',checks:[],evidence:[{fact_id:'r',artifact_id:'a',region:'表!A2'}],needs_confirmation:[]}}};
 const calls=[],notes=[],draft={note:'保留草稿',selected:new Set(['r'])};let reads=0;
 const c=vm.createContext({state:{epoch:1,user:{user_id:'actor'},overview:{scope,period:{object_id:'period',version:3},problem_review:{jobs:[job],system_tasks:[],counts:{FAILED:1}},artifacts:[{object_id:'a'}],material_review:{records:[{object_id:'r',source_artifact_id:'a'}]}}},scope:()=>scope,scopeKey:s=>JSON.stringify(s),esc:v=>String(v??'').replace(/[&<>"']/g,s=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[s])),materialCanWrite:()=>true,objectButton:(id,label)=>'<button type="button" data-object="'+id+'">'+label+'</button>',currentMaterialTask:()=>({id:'task'}),materialSaveDraft(){},command:async(...args)=>calls.push(args),loadWorkbench:async()=>reads++,notify:(...args)=>notes.push(args),exclusive:fn=>fn(),actions:{}});
 vm.runInContext(source+';installProblemReviewActions()',c);
 const button=target=>({dataset:{reviewId:target.object_id,reviewToken:c.problemReviewToken(target)}});
 return {c,job,calls,notes,draft,button,reads:()=>reads};
}
test('overview and details are additive, rendering never commands; system queue separate from history',()=>{
 const a=fixture();a.job.status='SYSTEM_REVIEW';a.c.state.overview.problem_review.system_tasks=[a.job];const before=JSON.stringify(a.c.state.overview);
 const html=a.c.renderProblemReviewOverview();assert.match(html,/系统待检查.*独立于客户补证/);assert.doesNotMatch(html,/系统待修正|仅在明确发起后/);assert.match(html,/解析完成后自动复核/);assert.match(html,/不自动核实、不改事实、不放行账务/);assert.equal(a.calls.length,0);assert.equal(JSON.stringify(a.c.state.overview),before);
 assert.match(a.c.renderProblemReviewDetail({id:'task',artifact_id:'a',kind:'ISSUE',problem_review:a.job}),/读取失败/);
 assert.equal(a.c.renderProblemReviewDetail({kind:'VERIFY'}),'');
});
test('explicit request binds period id/version and sends only empty payload; refresh is read-only',async()=>{
 const a=fixture(),b=a.button(a.c.state.overview.period);await a.c.actions['problem-review-request'](b);
 assert.deepEqual(JSON.parse(JSON.stringify(a.calls)),[['request_problem_review','period',3,{},false]]);assert.equal(a.reads(),1);
 await a.c.actions['problem-review-refresh'](b);assert.equal(a.calls.length,1);assert.equal(a.reads(),2);assert.match(a.notes.at(-1)[0],/未发起新的复核/);
});
test('failed retry preserves draft and does not reload; retry reuses current job version',async()=>{
 const a=fixture();a.c.command=async(...args)=>{a.calls.push(args);throw Error('隔离失败');};await a.c.actions['problem-review-retry'](a.button(a.job));
 assert.deepEqual(JSON.parse(JSON.stringify(a.calls)),[['retry_problem_review','job',2,{},false]]);assert.equal(a.reads(),0);assert.equal(a.draft.note,'保留草稿');assert.equal(a.draft.selected.size,1);assert.match(a.notes[0][0],/隔离失败/);
});
test('readonly hides request/retry, guards direct invocation but allows refresh',async()=>{
 const a=fixture();a.c.materialCanWrite=()=>false;const html=a.c.renderProblemReviewOverview();assert.doesNotMatch(html,/data-action="problem-review-(request|retry)"/);
 await a.c.actions['problem-review-request'](a.button(a.c.state.overview.period));await a.c.actions['problem-review-retry'](a.button(a.job));assert.equal(a.calls.length,0);
 await a.c.actions['problem-review-refresh'](a.button(a.c.state.overview.period));assert.equal(a.reads(),1);
});
test('old scope, actor, version and epoch buttons cannot dispatch',async()=>{
 for(const mutate of [a=>a.c.state.epoch++,a=>a.c.state.user.user_id='other',a=>a.job.version++,a=>a.c.state.overview.scope={tenant_id:'other'}]){
  const a=fixture(),b=a.button(a.job);mutate(a);await a.c.actions['problem-review-retry'](b);assert.equal(a.calls.length,0);
 }
});
test('late operation completion does not reload or notify another scope',async()=>{
 const a=fixture();let done;a.c.command=()=>new Promise(r=>done=r);const operation=a.c.actions['problem-review-retry'](a.button(a.job));a.c.state.epoch++;done();await operation;assert.equal(a.reads(),0);assert.equal(a.notes.length,0);
});
test('pending blocks duplicate queue requests; stale pass never claims a current result',async()=>{
 const a=fixture();a.job.status='RUNNING';assert.doesNotMatch(a.c.renderProblemReviewOverview(),/data-action="problem-review-request"/);await a.c.actions['problem-review-request'](a.button(a.c.state.overview.period));assert.equal(a.calls.length,0);
 a.job.status='PASSED';a.job.valid=false;const html=a.c.renderProblemReviewOverview();assert.match(html,/仅作历史记录/);assert.match(html,/依据已变化/);assert.doesNotMatch(html,/problem-review-status">复核通过/);
});
test('evidence is escaped, unknown sources have no link, and mismatched task projections are not substituted',()=>{
 const a=fixture();a.job.data.title='<script>x</script>';a.job.data.result.evidence.push({artifact_id:'outside',region:'<img>'});const html=a.c.renderProblemReviewOverview();assert.doesNotMatch(html,/<script>|<img>|data-object="outside"/);assert.match(html,/data-object="r"/);assert.match(html,/&lt;img&gt;/);
 assert.match(a.c.renderProblemReviewDetail({id:'other',artifact_id:'a',kind:'ISSUE',problem_review:a.job}),/暂无匹配/);
});
test('integration places review after source evidence and before original handling without replacing forms',()=>{
 const decision=fs.readFileSync(path.join(__dirname,'../static/operator-decision.js'),'utf8'),html=fs.readFileSync(path.join(__dirname,'../static/operator.html'),'utf8');
 assert.match(decision,/decisionEvidence\(t\)\+\(typeof renderProblemReviewDetail/);assert.match(html,/operator-problem-review.js\?v=guided-flow-1/);
});
test('historical evidence opens bound versions; missing historical versions never use current facts',()=>{
 const a=fixture();a.job.valid=false;a.job.data.binding={artifact:{id:'a',version:1},records:[{id:'r',version:4}]};
 assert.match(a.c.problemReviewEvidence(a.job),/data-object="r" data-object-version="4"/);
 delete a.job.data.binding;assert.doesNotMatch(a.c.problemReviewEvidence(a.job),/data-object=/);assert.match(a.c.problemReviewEvidence(a.job),/不使用当前版本替代/);
});
test('red blue checks render escaped local tables with missing values distinct from zero',()=>{
 const a=fixture();a.job.data.result.checks=[{message:'精确核对',relationships:[{fact_id:'r',invoice_no:'<img>',role:'BLUE',amount:0,tax_amount:null,invoice_total:'100',region:'A2',artifact_id:'a',fact_version:2,artifact_version:1}],balances:[{field:'tax',label:'税额',blue:null,red:0,net:null,status:'REVIEW'}],check_steps:[{code:'LOCAL',label:'金额关系',status:'PASS',message:'<script>'}]}];
 const html=a.c.problemReviewJob(a.job);assert.match(html,/蓝字发票/);assert.match(html,/&lt;img&gt;/);assert.match(html,/未提供/);assert.match(html,/>0</);assert.match(html,/table-wrap/);assert.match(html,/金额关系/);assert.doesNotMatch(html,/<img>|<script>/);
});
test('source audit stays escaped; SYSTEM permits only explicit valid FAILED review retry',async()=>{
 const a=fixture();const html=a.c.renderProblemSourceAudit({status:'NO_EXPLICIT_LABEL',message:'原件未找到币种；不能默认人民币 <img>',candidates:[{region:'表!C2',label:'币种',artifact_id:'a',artifact_version:2}]});
 assert.match(html,/原件未找到币种/);assert.match(html,/&lt;img&gt;/);assert.match(html,/data-object-version="2"/);a.job.triage={route:'SYSTEM'};
 assert.match(a.c.problemReviewJob(a.job,true),/data-action="problem-review-retry"/);assert.equal(a.calls.length,0);
 await a.c.actions['problem-review-retry'](a.button(a.job));assert.deepEqual(JSON.parse(JSON.stringify(a.calls)),[['retry_problem_review','job',2,{},false]]);
});
test('SYSTEM retry remains blocked for readonly, stale or non-failed jobs',async()=>{
 for(const mode of ['readonly','stale','running','passed']){const a=fixture();a.job.triage={route:'SYSTEM'};if(mode==='readonly')a.c.materialCanWrite=()=>false;if(mode==='stale')a.job.valid=false;if(mode==='running')a.job.status='RUNNING';if(mode==='passed')a.job.status='PASSED';assert.doesNotMatch(a.c.problemReviewJob(a.job,true),/data-action="problem-review-retry"/);await a.c.actions['problem-review-retry'](a.button(a.job));assert.equal(a.calls.length,0,mode);}
});
test('compact system checks retain every table and full basis, with deduplicated failed steps',()=>{
 const a=fixture(),check={message:'原始检查说明',relationships:[{role:'BLUE',invoice_no:'B',amount:0}],balances:[{label:'金额',net:0,status:'PASS'}],check_steps:[{code:'AMOUNT',label:'金额',status:'PASS',message:'完整算术依据'},{code:'CURRENCY',label:'币种来源',status:'REVIEW',message:'完整币种依据'}]};
 const html=a.c.renderProblemReviewChecks([check,check],true);
 assert.equal((html.match(/aria-label="红蓝发票关联"/g)||[]).length,2);assert.equal((html.match(/aria-label="金额抵销核对"/g)||[]).length,2);
 assert.equal((html.match(/class="problem-check-attention"/g)||[]).length,1);assert.equal((html.match(/<details><summary>查看完整检查依据/g)||[]).length,2);assert.match(html,/完整算术依据/);assert.doesNotMatch(html,/<details open/);
 const detail=a.c.renderProblemReviewDetail({id:'task',artifact_id:'a',kind:'ISSUE',problem_review:a.job},true);
 assert.match(detail,/<details class="problem-review-history"><summary>上次复核记录/);assert.equal((detail.match(/data-action="problem-review-retry"/g)||[]).length,1);assert(detail.indexOf('data-action="problem-review-retry"')<detail.indexOf('problem-review-history'));
});
test('linked red evidence uses its own recorded version and all source regions, including history',()=>{
 const a=fixture();a.job.valid=false;a.c.state.overview.artifacts.push({object_id:'red-file'});
 a.job.data.result.evidence.push({id:'linked-2',fact_id:'red',artifact_id:'red-file',region:'红表!A3'});
 a.job.data.result.checks=[{evidence_refs:[{fact_id:'red',artifact_id:'red-file',fact_version:5,artifact_version:2,source_anchor:{region:'红表!A3'},source_regions:['红表!B3','红表!C3']}]}];
 const html=a.c.problemReviewEvidence(a.job);assert.match(html,/data-object="red" data-object-version="5"/);assert.match(html,/红表!A3 · 红表!B3 · 红表!C3/);
});
function pollingFixture(){
 const a=fixture();a.c.state.view='materials';a.job.status='RUNNING';a.c.document={hidden:false};a.c.setTimeout=()=>1;a.c.clearTimeout=()=>{};
 a.c.scheduleProblemReviewPoll();return a;
}
test('background completion only notifies once: no replacement, reload, command or draft change',async()=>{
 const a=pollingFixture(),before=a.c.state.overview;let requests=0;
 a.c.request=async(url,body)=>{assert.equal(url,'/api/v1/workbench');assert.deepEqual(JSON.parse(JSON.stringify(body.scope)),JSON.parse(JSON.stringify(a.c.scope())));requests++;return {...before,problem_review:{jobs:[{...a.job,status:'BUSINESS_REVIEW'}]}};};
 await a.c.pollProblemReview();await a.c.pollProblemReview();assert.equal(requests,1);assert.equal(a.notes.length,1);assert.match(a.notes[0][0],/请手动刷新/);assert.equal(a.c.state.overview,before);assert.equal(a.job.status,'RUNNING');assert.equal(a.reads(),0);assert.equal(a.calls.length,0);assert.equal(a.draft.note,'保留草稿');
});
test('background unchanged/error/late responses are silent, including scope switch and manual reload',async()=>{
 for(const mode of ['unchanged','error','epoch','reload','view','scope','busy','hidden']){
  const a=pollingFixture();a.c.request=async()=>{if(mode==='error')throw Error('offline');if(mode==='epoch')a.c.state.epoch++;if(mode==='reload')a.c.state.overview={...a.c.state.overview};if(mode==='view')a.c.state.view='accounts';if(mode==='busy')a.c.state.busy=true;if(mode==='hidden')a.c.document.hidden=true;return {scope:mode==='scope'?{}:a.c.scope(),problem_review:{jobs:[{...a.job,status:mode==='unchanged'?'RUNNING':'PASSED'}]}};};
  await a.c.pollProblemReview();assert.equal(a.notes.length,0,mode);assert.equal(a.calls.length,0,mode);assert.equal(a.reads(),0,mode);
 }
});
test('hidden or busy pages never start background reads',async()=>{
 for(const mode of ['busy','hidden']){const a=pollingFixture();let reads=0;a.c.request=async()=>reads++;if(mode==='busy')a.c.state.busy=true;else a.c.document.hidden=true;await a.c.pollProblemReview();assert.equal(reads,0);}
});
test('retrying the same job at a new version permits a new completion notification',async()=>{
 const a=pollingFixture();a.c.request=async()=>({scope:a.c.scope(),problem_review:{jobs:[{...a.job,status:'FAILED'}]}});
 await a.c.pollProblemReview();assert.equal(a.notes.length,1);a.job.version++;await a.c.pollProblemReview();assert.equal(a.notes.length,2);
});

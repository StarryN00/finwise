// Browser-only synthetic contract fixtures: every HTTP request is intercepted.
// No backend, database, worker, model or live service is started.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..');
(async()=>{
 const browser=await chromium.launch();
 try{
  const page=await browser.newPage({viewport:{width:1040,height:900}}),errors=[],writes=[];let fail=false;
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',async route=>{
   if(route.request().url()==='http://review.test/workbench')return route.fulfill({contentType:'application/json',body:JSON.stringify(await page.evaluate(()=>({scope:scope(),problem_review:{jobs:[{...job,status:'BUSINESS_REVIEW'}]}})))});
   if(route.request().url()==='http://review.test/commands'){
    writes.push(route.request().postDataJSON());return route.fulfill({status:fail?503:200,contentType:'application/json',body:JSON.stringify({message:fail?'隔离测试请求失败':'已接收'})});
   }
   if(route.request().url()==='http://review.test/')return route.fulfill({contentType:'text/html',body:'<!doctype html><html lang="zh-CN"><body><div id="notice" role="status"></div><main id="workspace"></main><dialog id="sourceDialog"><p>合成原件 表!A2</p><button type="button" id="closeSource">关闭</button></dialog></body></html>'});
   throw Error('Unexpected network: '+route.request().url());
  });
  await page.goto('http://review.test/');
  await page.addStyleTag({content:fs.readFileSync(path.join(root,'static/operator.css'),'utf8')});
  await page.addScriptTag({content:`
   const fixtureScope={tenant_id:'t',organization_id:'o',legal_entity_id:'e',ledger_id:'l',accounting_period_id:'2026-01',baseline_id:'b'};
   const record={object_id:'r',version:1,source_artifact_id:'a',source_anchor:{region:'表!A2'},values:{invoice_no:'TEST-01',invoice_total:-100},issues:[],comparison:[{field:'invoice_total',source_value:-100,value:-100,state:'DIRECT_MATCH',region:'表!A2'}]};
   const job={object_id:'job',version:2,status:'FAILED',valid:true,data:{task_id:'task',artifact_id:'a',title:'发票金额二次复核',result:{message:'合成失败结果',checks:[{fact_id:'r',status:'REVIEW',message:'需要核对金额原值'}],evidence:[{fact_id:'r',artifact_id:'a',region:'表!A2'}],needs_confirmation:['确认业务原因']}}};
   const option={id:'confirm_invoice_amount',label:'确认已核对',available:true,unavailable_reason:'',requires:[],effects:[{kind:'CREATE',target:'InvoiceAmountConfirmation',description:'仅解除金额提醒',grants_accounting_usable:false}],not_effects:['不放行账务'],completion:'核对金额和业务原因',fields:[{name:'reason',label:'核对说明',component:'textarea',required:true,max_length:2000,placeholder:''}],steps:[{id:'reason',prompt:'请填写核对说明',fields:['reason']}]};
   const binding={...fixtureScope,artifact:{id:'a',version:1,sha256:'hash'},records:[{id:'r',version:1,source_anchor:record.source_anchor}]};
   const task={id:'task',kind:'INVOICE_AMOUNT',filename:'合成发票.xlsx',artifact_id:'a',artifact_version:1,record_ids:['r'],problem_review:job,descriptor:{version:'decision-v2',stage:'BUSINESS_REVIEW',why_now:'核对原件',title:'发票金额核对',scope:binding,why:{facts:'合成原件金额',rule:'红字金额',recommendation:'核对原件',origin:'RULE',evidence:binding.records},options:[option],steps:[]}};
   const state={epoch:1,user:{user_id:'actor'},role:'operator',view:'materials',overview:{scope:fixtureScope,period:{object_id:'period',version:3,status:'OPEN'},problem_review:{jobs:[job],counts:{FAILED:1},system_tasks:[]},material_review:{records:[record],tasks:[task]},artifacts:[{object_id:'a',version:1,data:{sha256:'hash'}}]}};
   const actions={},fieldLabels={},$=id=>document.getElementById(id),scope=()=>fixtureScope,scopeKey=s=>JSON.stringify(s),readonly=()=>state.role==='viewer';
   const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
   const storage=(k,v)=>v===undefined?sessionStorage.getItem(k):sessionStorage.setItem(k,v);
   const objectButton=(id,title)=>'<button type="button" data-object="'+esc(id)+'">'+esc(title)+'</button>';
   const notify=(message)=>{$('notice').textContent=message;};
   const exclusive=async fn=>{if(state.busy)return;state.busy=true;try{await fn();}finally{state.busy=false;}};
   let reads=0;
   async function command(action,id,version,payload,reload){const response=await fetch('/commands',{method:'POST',body:JSON.stringify({action,id,version,payload,scope:scope()})});const data=await response.json();if(!response.ok)throw Error(data.message);job.status='QUEUED';}
   async function loadWorkbench(){reads++;render();}
   async function request(url,body){if(url!=='/api/v1/workbench')throw Error('Unexpected API');return (await fetch('/workbench',{method:'POST',body:JSON.stringify(body)})).json();}
   function render(){const focus=materialCaptureFocus();$('workspace').innerHTML=materialState().screen==='detail'?'<div id="materialWorkbench" data-screen="detail">'+renderDecisionTask(task)+'</div>':'<div id="materialWorkbench" data-screen="list">'+renderProblemReviewOverview()+'</div>';materialRestoreFocus(focus);}
  `});
  for(const file of ['operator-materials.js','operator-material-navigation.js','operator-decision.js','operator-problem-review.js'])await page.addScriptTag({content:fs.readFileSync(path.join(root,'static',file),'utf8')});
  assert.deepEqual(errors,[],'Frontend scripts must load without syntax/runtime errors');
  assert.equal(await page.evaluate(()=>typeof renderDecisionTask),'function','Decision renderer must be installed before rendering');
  await page.evaluate(()=>{
   installMaterialActions();const ui=materialState();ui.screen='detail';ui.selected='task';render();
   document.addEventListener('click',event=>{const b=event.target.closest('button');if(!b)return;if(b.dataset.action)actions[b.dataset.action]?.(b);if(b.dataset.object)$('sourceDialog').showModal();if(b.id==='closeSource')$('sourceDialog').close();});
  });
  assert.equal(writes.length,0);
  assert.equal(await page.locator('form').count(),1);
  const evidenceY=(await page.locator('.decision-evidence').boundingBox()).y,reviewY=(await page.locator('.problem-review-detail').boundingBox()).y,formY=(await page.locator('.decision-handling').boundingBox()).y;
  assert(evidenceY<reviewY&&reviewY<formY);
  await page.locator('#materialNote').fill('已填业务说明，不得丢失');
  fail=true;await page.locator('[data-action="problem-review-retry"]').click();await page.getByRole('status').filter({hasText:'隔离测试请求失败'}).waitFor();
  assert.equal(await page.locator('#materialNote').inputValue(),'已填业务说明，不得丢失');assert.equal(await page.evaluate(()=>reads),0);
  assert.equal(writes[0].action,'retry_problem_review');assert.equal(writes[0].version,2);assert.deepEqual(writes[0].payload,{});
  await page.locator('[data-action="problem-review-refresh"]').click();await page.getByRole('status').filter({hasText:'未发起新的复核'}).waitFor();assert.equal(writes.length,1);assert.equal(await page.locator('#materialNote').inputValue(),'已填业务说明，不得丢失');
  await page.evaluate(()=>{job.status='RUNNING';render();$('materialNote').focus();window.savedNote=$('materialNote');window.savedReads=reads;scheduleProblemReviewPoll();});
  await page.evaluate(()=>pollProblemReview());await page.getByRole('status').filter({hasText:'请手动刷新查看结果'}).waitFor();
  assert(await page.evaluate(()=>$('materialNote')===window.savedNote&&document.activeElement===window.savedNote&&reads===window.savedReads&&job.status==='RUNNING'));assert.equal(writes.length,1);assert.equal(await page.locator('#materialNote').inputValue(),'已填业务说明，不得丢失');
  await page.evaluate(()=>{job.status='FAILED';render();});
  await page.evaluate(()=>{state.role='viewer';render();});assert.equal(await page.locator('[data-action="problem-review-retry"]').count(),0);
  await page.locator('.problem-review-evidence summary').click();await page.locator('.problem-review-evidence [data-object]').click();assert(await page.locator('#sourceDialog').isVisible());await page.locator('#closeSource').click();assert.equal(writes.length,1);
  fail=false;await page.evaluate(()=>{state.role='operator';materialState().screen='list';render();});await page.locator('.problem-review>summary').click();await page.locator('[data-action="problem-review-request"]').click();await page.getByRole('status').filter({hasText:'复核请求已接收'}).waitFor();assert.equal(writes[1].action,'request_problem_review');assert.equal(writes[1].id,'period');assert.equal(writes[1].version,3);
  assert.equal(await page.locator('[data-action="problem-review-request"]').count(),0);await page.locator('.problem-review>summary').click();assert.match(await page.locator('.problem-review').innerText(),/排队或处理中/);
  await page.evaluate(()=>{job.status='PASSED';job.data.result.message='合成核对通过，仅解除精确提醒';job.data.result.needs_confirmation=[];state.overview.artifacts.push({object_id:'red-file'});job.data.result.evidence.push({id:'linked-2',fact_id:'red',artifact_id:'red-file',region:'红表!A3'});job.data.result.checks[0].evidence_refs=[{fact_id:'red',artifact_id:'red-file',fact_version:4,artifact_version:1,source_anchor:{region:'红表!A3'},source_regions:['红表!B3']}];state.overview.problem_review.counts={PASSED:1};render();});
  await page.locator('.problem-review>summary').click();await page.locator('summary').filter({hasText:'复核结果与历史'}).click();assert.equal(await page.locator('.problem-review-evidence [data-object]').count(),2);assert.match(await page.locator('.problem-review-evidence').innerText(),/红表!A3 · 红表!B3/);assert.equal(await page.locator('[data-object="red"]').getAttribute('data-object-version'),'4');await page.locator('[data-object="red"]').click();assert(await page.locator('#sourceDialog').isVisible());await page.locator('#closeSource').click();assert.equal(writes.length,2);
  for(const width of [1040,390]){await page.setViewportSize({width,height:900});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));}
  const out=path.join(root,'output/playwright/problem-review');fs.mkdirSync(out,{recursive:true});await page.screenshot({path:path.join(out,'review-mobile.png'),fullPage:true});
  await page.evaluate(()=>{
   const checks=[{message:'系统需检查来源，未放行',relationships:[{fact_id:'r',invoice_no:'BLUE-<img>',role:'BLUE',amount:0,tax_amount:null,invoice_total:100,region:'蓝表!A2',artifact_id:'a',fact_version:1,artifact_version:1},{fact_id:'red',invoice_no:'RED-01',role:'RED',amount:-100,tax_amount:null,invoice_total:-100,region:'红表!A3',artifact_id:'red-file',fact_version:4,artifact_version:1}],balances:[{field:'invoice_total',label:'价税合计',blue:100,red:-100,net:0,status:'MATCH'},{field:'tax',label:'税额',blue:null,red:null,net:null,status:'NOT_AVAILABLE'}],check_steps:[{code:'CURRENCY',label:'币种来源',status:'REVIEW',message:'原件尚未定位明确币种，不能猜测'}]}];
   checks[0].check_steps.unshift({code:'AMOUNT',label:'金额抵销',status:'PASS',message:'三项算术检查完整依据'});
   checks.push({...checks[0],relationships:checks[0].relationships.map(r=>r.role==='BLUE'?{...r,invoice_no:'BLUE-02'}:r)});
   task.triage={version:'issue-triage-v1',route:'SYSTEM',title:'币种来源待检查',explanation:'不能把系统来源疑点当成客户补证',next_action:'由系统检查原件币种标签及字段映射，再刷新结果',questions:[],checks,source_audit:{status:'NO_EXPLICIT_LABEL',message:'已读取原件，未找到明确币种标签；不默认人民币。',candidates:[]}};
   const human={...task,id:'human',problem_review:null,triage:{version:'issue-triage-v1',route:'HUMAN',title:'请核对业务原因',explanation:'金额原值已定位，请明确业务事实',next_action:'请填写核对原因',questions:['为何为负数？'],checks:[]}};
   state.overview.material_review.tasks=[task,human];state.overview.material_review.categories=[];
   state.overview.material_review.counts={files:2,records:1,file_states:{extracted:2},unassigned_files:0,system_checked:0,awaiting_verification:0,source_verified:0,needs_review:1,period_exceptions:0,accounting_usable:0,supplement_issues:0,deferred:0,human_issue_tasks:1,system_issue_tasks:1,issue_tasks:2};
   state.overview.baseline_validation={status:'VALID'};window.historicalIssueFlow=()=>({done:true,count:0,plans:[]});window.readiness=()=>({categories:[{file_count:0}],counts:{}});
   render=()=>{const focus=materialCaptureFocus();$('workspace').innerHTML=renderMaterialWorkbench();materialRestoreFocus(focus);};
   materialState().screen='list';materialState().filter='all';notify('');render();
  });
  assert.equal(await page.locator('.mat-issue-group').count(),1);assert.match(await page.locator('.mat-issue-group').innerText(),/请核对业务原因/);
  await page.locator('[data-filter="system"]').click();assert.equal(await page.locator('.mat-issue-group').count(),1);await page.locator('.mat-issue-group button').click();
  assert.match(await page.locator('#materialTaskTitle').innerText(),/币种来源待检查/);assert.equal(await page.locator('form').count(),0);assert.match(await page.locator('.problem-source-audit').innerText(),/未找到明确币种标签/);
  assert.equal(await page.locator('[data-guide="open"],[data-guide="commit"],[data-guide="agent"],[data-action="problem-review-retry"]').count(),0);
  const checked=page.getByRole('region',{name:'系统已核对的数据',exact:true});
  assert.match(await page.locator('.decision-handling').innerText(),/由系统检查原件币种标签及字段映射/);assert.match(await checked.innerText(),/未提供/);assert.equal(await checked.locator('img').count(),0);
  const expectedTables=await page.evaluate(()=>({relationships:task.triage.checks.filter(c=>c.relationships?.length).length,balances:task.triage.checks.filter(c=>c.balances?.length).length}));
  for(const [field,label] of [['relationships','红蓝发票关联'],['balances','金额抵销核对']]){const tables=checked.getByRole('region',{name:label,exact:true});assert.equal(await tables.count(),expectedTables[field]);assert.equal(expectedTables[field],2);for(let i=0;i<expectedTables[field];i++)assert(await tables.nth(i).isVisible());}
  assert((await page.locator('.problem-source-audit').boundingBox()).y<(await checked.boundingBox()).y);assert((await checked.boundingBox()).y<(await page.locator('.decision-handling').boundingBox()).y);
  assert.equal(await checked.locator('.problem-check-attention').count(),1);assert.equal(await checked.locator('details[open]').count(),0);assert.equal(await page.locator('.problem-review-history[open]').count(),0);
  assert.match(await page.locator('.decision-chat').innerText(),/下方初筛提示为原始规则记录，不是当前人工待办结论/);
  await checked.getByText('查看完整检查依据',{exact:true}).nth(1).click();assert.match(await checked.locator('details').nth(1).innerText(),/三项算术检查完整依据/);await checked.getByText('查看完整检查依据',{exact:true}).nth(1).click();assert.equal(writes.length,2);
  const triageOut=path.join(root,'output/playwright/issue-triage');fs.mkdirSync(triageOut,{recursive:true});
  for(const width of [1440,1040,390]){await page.setViewportSize({width,height:width===390?844:900});await page.evaluate(()=>scrollTo(0,0));assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.screenshot({path:path.join(triageOut,'system-'+width+'.png'),fullPage:width!==390});if(width===390)await page.screenshot({path:path.join(triageOut,'system-390-full.png'),fullPage:true});}
  for(let i=0;i<await checked.locator('.problem-check-table').count();i++)assert(await checked.locator('.problem-check-table').nth(i).evaluate(el=>el.scrollWidth>el.clientWidth));
  await checked.locator('[data-object="red"]').nth(1).click();assert(await page.locator('#sourceDialog').isVisible());await page.locator('#closeSource').click();assert.equal(writes.length,2);
  await page.locator('[data-action="material-return-list"]').first().click();await page.locator('[data-filter="all"]').first().click();await page.locator('.mat-issue-group button').click();assert.equal(await page.locator('#invoiceAmountForm').count(),1);assert.match(await page.locator('#materialTaskTitle').innerText(),/请核对业务原因/);
  await page.locator('#materialNote').fill('人工任务草稿保留');await page.locator('[data-action="material-return-list"]').first().click();await page.locator('[data-filter="issues"]').click();assert.equal(await page.locator('.mat-issue-group').count(),2);assert.equal(writes.length,2);
  await page.locator('.mat-issue-group').filter({hasText:'请核对业务原因'}).getByRole('button').click();assert.equal(await page.locator('#materialNote').inputValue(),'人工任务草稿保留');
  await page.locator('[data-action="material-return-list"]').first().click();await page.locator('[data-filter="system"]').click();await page.locator('.mat-issue-group button').click();
  await page.evaluate(()=>{job.status='FAILED';job.triage=task.triage;render();window.savedSystemSource=document.querySelector('.decision-evidence');});
  assert.equal(writes.length,2);assert.equal(await page.locator('form,[data-guide="commit"],[data-guide="open"],[data-guide="agent"]').count(),0);assert(await page.locator('[data-action="problem-review-retry"]').isVisible());
  fail=true;await page.locator('[data-action="problem-review-retry"]').click();await page.getByRole('status').filter({hasText:'隔离测试请求失败'}).waitFor();assert.equal(writes.length,3);assert(await page.evaluate(()=>window.savedSystemSource===document.querySelector('.decision-evidence')));
  fail=false;await page.locator('[data-action="problem-review-retry"]').click();await page.getByRole('status').filter({hasText:'复核请求已接收'}).waitFor();assert.equal(writes.length,4);assert.equal(await page.locator('[data-action="problem-review-retry"]').count(),0);
  for(const write of writes.slice(2)){assert.equal(write.action,'retry_problem_review');assert.equal(write.id,'job');assert.equal(write.version,2);assert.deepEqual(write.payload,{});}
  await page.locator('[data-action="material-return-list"]').first().click();await page.locator('[data-filter="all"]').first().click();await page.locator('.mat-issue-group button').click();assert.equal(await page.locator('#materialNote').inputValue(),'人工任务草稿保留');
  console.log('PASS: two-blue table counts/every table visible, current evidence before next action, collapsed history/basis, explicit SYSTEM retry failure/success preserves HUMAN draft; only mock review commands');
  await page.evaluate(()=>{const t=currentMaterialTask();t.descriptor.fingerprint='synthetic-fingerprint';const g=decisionGuide(t);g.agent={response:{status:'PROPOSED',descriptor_hash:'synthetic-fingerprint',suggestion:{option_id:'confirm_invoice_amount',reason:'只建议核对现有业务原因 <img>',uncertainties:['仍需本人判断'],prefill:{}}}};render();});
  const suggestion=page.getByRole('region',{name:'处理建议',exact:true});assert(await suggestion.isVisible());assert.equal(await suggestion.locator('[aria-pressed="true"]').count(),0);assert.equal(await suggestion.locator('img').count(),0);assert.equal(writes.length,4);
  await suggestion.locator('[data-guide="legacy-suggestion-card"]').click();assert.equal(await suggestion.locator('[aria-selected="true"]').count(),1);assert.equal(await page.locator('#materialNote').inputValue(),'人工任务草稿保留');assert.equal(writes.length,4);assert.equal(await page.locator('[data-guide="commit"]').count(),0);
  await page.setViewportSize({width:390,height:844});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  console.log('PASS: candidate card is unselected initially; explicit selection preserves the draft and original summary gate, with no network or business command');
  console.log('PASS: triage list/detail/return/HUMAN draft/all-issues drill, source audit, versioned red evidence and 3 viewport screenshots');
  assert.deepEqual(errors,[]);console.log('PASS: 9 browser flows (source-first, failure draft, refresh, readonly, source dialog, request, pending, linked PASS evidence, background notification preserves DOM/focus/draft), desktop/mobile overflow; no live requests');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});

// Synthetic Chromium only: all requests intercepted; no service/model/database.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),{chromium}=require('playwright');
const root=path.resolve(__dirname,'..');
(async()=>{
 const browser=await chromium.launch();
 try{
  const page=await browser.newPage({viewport:{width:1040,height:900}}),writes=[],reads=[],errors=[],guidance=[];let fail=false,denySource=false,failGuidance=false;
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',async route=>{
   const req=route.request(),url=new URL(req.url());
   if(url.href==='http://bank.test/')return route.fulfill({contentType:'text/html',body:'<!doctype html><html lang="zh-CN"><body><div id="notice" role="status"></div><main id="workspace"></main><dialog id="dialog"><h2 id="dialogTitle"></h2><div id="dialogBody"></div><button id="closeDialog" type="button">返回</button></dialog></body></html>'});
   if(url.pathname==='/api/v1/agent/suggestion'){
    const body=req.postDataJSON();guidance.push(body);return route.fulfill({status:failGuidance?503:200,contentType:'application/json',body:JSON.stringify(failGuidance?{message:'合成验证失败'}:{status:'LOCAL_ONLY',descriptor_hash:body.descriptor_hash,candidates:[],suggestion:null,message:'意见仅本地保存，尚未执行；未调用模型。'})});
   }
   if(url.pathname==='/commands'){
    const body=req.postDataJSON();writes.push(body);
    if(fail)return route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({message:'合成依赖阻断，原输入保留'})});
    const effect=await page.evaluate(body=>{
     const p=state.overview.bank_periods;
     if(body.action==='save_material_opinion')return {object:{object_id:'opinion',version:1,status:'SAVED_NOT_EXECUTED'}};
     if(['retry_material_guidance','request_material_guidance'].includes(body.action))return {object:{object_id:'job',version:4,status:'QUEUED'}};
     if(body.action==='confirm_bank_period'){
      const objects=body.payload.record_ids.map(id=>({object_id:'assignment-'+id,version:1,status:'CONFIRMED',scope:scope(),valid:true,handoff_status:'WAITING_PERIOD',data:{binding:{fact_id:id,fact_version:1,artifact_id:'file',artifact_version:1,source_anchor:{region:'流水!A2'}},target_period:body.payload.target_period}}));
      p.outgoing.push(...objects);state.overview.material_review.records.filter(r=>body.payload.record_ids.includes(r.object_id)).forEach(r=>{r.state='OTHER_PERIOD';r.period_assignment=objects.find(o=>o.data.binding.fact_id===r.object_id);});
      state.overview.material_review.counts.other_period=objects.length;p.counts.confirmed_other_period=objects.length;return {objects};
     }
     const incoming=p.incoming[0];
     if(body.action==='accept_bank_period'){incoming.status='ACCEPTED';incoming.intake={object_id:'intake',version:1,status:'ACCEPTED'};return {object:incoming.intake};}
     if(body.action==='revoke_bank_period_intake'){incoming.intake={object_id:'intake',version:2,status:'REVOKED'};incoming.status='READY';return {object:incoming.intake};}
     if(body.action==='revoke_bank_period'){const o=p.outgoing.find(x=>x.object_id===body.id);o.status='REVOKED';o.version++;o.valid=false;return {object:o};}
     throw Error('Unexpected command');
    },body);return route.fulfill({contentType:'application/json',body:JSON.stringify({effect})});
   }
   if(url.pathname==='/workbench'){reads.push({kind:'wb'});return route.fulfill({contentType:'application/json',body:'{}'});}
   if(url.pathname==='/api/v1/objects/detail'){const body=req.postDataJSON();reads.push(body);return route.fulfill({status:denySource?403:200,contentType:'application/json',body:JSON.stringify(denySource?{message:'无源期间权限'}:{object:{object_id:body.object_id,version:body.version,data:{original_value:{income:0,expense:null},source_anchor:{region:'源表!A2'}}}})});}
   throw Error('Unexpected network '+url.pathname);
  });
  await page.goto('http://bank.test/');await page.addStyleTag({content:fs.readFileSync(path.join(root,'static/operator.css'),'utf8')});
  await page.addScriptTag({content:`
   if(!crypto.randomUUID){let requestNumber=0;crypto.randomUUID=()=>('synthetic-request-'+(++requestNumber));}
   const selectedScope={tenant_id:'t',organization_id:'o',legal_entity_id:'e',ledger_id:'l',accounting_period_id:'2026-01',baseline_id:'b'};
   const records=Array.from({length:6},(_,i)=>({object_id:'r'+(i+1),version:1,filename:'合成流水.xlsx',source_artifact_id:'file',state:'PERIOD_EXCEPTION',values:{transaction_date:'2026-02-01',income:0,expense:12},source_anchor:{region:'流水!A'+(i+2)},issues:['业务期间：原件为其他月份'],comparison:[{field:'transaction_date',source_value:'2026-02-01',value:'2026-02-01',state:'DIRECT_MATCH',region:'流水!A'+(i+2)}]}));
   const bound={...selectedScope,artifact:{id:'file',version:1,sha256:'hash'},records:records.map(r=>({id:r.object_id,version:1,source_anchor:r.source_anchor}))};
   const option={id:'confirm_bank_period',label:'确认归属 2026-02',available:true,unavailable_reason:'',completion:'只确认所属月份，不入账',effects:['排除本期发生额'],not_effects:['不计原件核实或账务可用'],requires:[],fields:[{name:'records',label:'选择当前页记录',component:'slot',slot:'period_record_selection',required:true,properties:[]},{name:'reason',label:'说明（可选）',component:'textarea',required:false,max_length:2000,placeholder:''}],steps:[{id:'records',prompt:'选择本页要确认归属的记录',fields:['records']},{id:'reason',prompt:'填写归属说明（可选）',fields:['reason']}]};
   const task={id:'task',kind:'ISSUE',reason:'业务期间：其他月份',title:'核对归属',filename:'合成流水.xlsx',artifact_id:'file',artifact_version:1,record_ids:records.map(r=>r.object_id),input_token:'token',bank_period:{target_period:'2026-02',record_ids:records.map(r=>r.object_id),input_token:'token'},descriptor:{version:'decision-v1',title:'核对流水月份',why:{facts:'原件日期为二月',rule:'以原件日期确认',recommendation:'先核对再明确选择',origin:'RULE',evidence:bound.records},scope:bound,options:[option],steps:[]}};
   const state={epoch:1,user:{user_id:'actor'},role:'operator',view:'materials',dialogSequence:0,overview:{scope:selectedScope,period:{object_id:'period',version:3},artifacts:[{object_id:'file',version:1,status:'ACTIVE',data:{sha256:'hash'}}],material_review:{tasks:[task],records,categories:[],counts:{files:1,records:6,file_states:{extracted:1},awaiting_verification:0,source_verified:0,accounting_usable:0,needs_review:0,period_exceptions:6,other_period:0,human_issue_tasks:1,system_issue_tasks:0,unassigned_files:0,deferred:0,supplement_issues:0}},baseline_validation:{status:'VALID'},bank_periods:{outgoing:[],incoming:[{assignment_id:'incoming',assignment_version:2,source_scope:{...selectedScope,accounting_period_id:'2025-12'},source_period:'2025-12',target_period:'2026-01',valid:true,status:'READY',intake:null,binding:{fact_id:'source-fact',fact_version:4,artifact_id:'source-file',artifact_version:2,source_anchor:{region:'源表!A2'}},filename:'转入流水<img>.xlsx',values:{income:0,expense:null},comparison:[{field:'income',source_value:0,value:0,region:'源表!A2'},{field:'expense',source_value:null,value:null,region:'源表!B2'}],original_issues:['原始字段提示<script>'],input_token:'incoming-token'}],counts:{confirmed_other_period:0}}}};
   const actions={},fieldLabels={},$=id=>document.getElementById(id),scope=()=>selectedScope,scopeKey=s=>JSON.stringify(s),readonly=()=>state.role==='viewer',storage=(k,v)=>v===undefined?sessionStorage.getItem(k):sessionStorage.setItem(k,v),esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
   const objectButton=(id,title)=>'<button type="button" data-object="'+esc(id)+'">'+esc(title)+'</button>',notify=m=>$('notice').textContent=m,readiness=()=>({categories:[{file_count:0}],counts:{}}),historicalIssueFlow=()=>({done:true,count:0,plans:[]}),exclusive=async fn=>{if(state.busy)return;state.busy=true;try{await fn();}finally{state.busy=false;}};
   function render(){$('workspace').innerHTML=renderMaterialWorkbench();}
   function openDialog(title,body){$('dialogTitle').textContent=title;$('dialogBody').innerHTML=body;if(!$('dialog').open)$('dialog').showModal();}
   function closeDialog(){state.dialogSequence++;$('dialog').close();}
   async function request(url,body){const r=await fetch(url,{method:'POST',body:JSON.stringify(body)}),data=await r.json();if(!r.ok)throw Error(data.message);return data;}
   const command=(action,id,version,payload)=>request('/commands',{action,id,version,payload,scope:scope()});
   async function loadWorkbench(){await request('/workbench',{scope:scope()});render();}
  `});
  for(const file of ['operator-materials.js','operator-material-navigation.js','operator-bank-periods.js','operator-material-guidance.js','operator-decision.js'])await page.addScriptTag({content:fs.readFileSync(path.join(root,'static',file),'utf8')});
  assert.deepEqual(errors,[]);await page.evaluate(()=>{installMaterialActions();render();document.addEventListener('click',e=>{const b=e.target.closest('button');if(b?.dataset.action)actions[b.dataset.action]?.(b);if(b?.id==='closeDialog')closeDialog();});});
  await page.locator('.mat-issue-group button').click();assert.equal(await page.locator('form').count(),0);await page.locator('[data-guide="option"][data-option="confirm_bank_period"]').click();assert.equal(await page.locator('[data-material-record]').count(),5);assert.equal(await page.locator('[data-material-record]:checked').count(),0);
  await page.locator('[data-guide="next"]').click();assert.equal(await page.locator('[data-guide="commit"]').count(),0);assert.equal(writes.length,0);
  await page.locator('[data-material-record="r1"]').check();await page.locator('[data-action="material-page"][data-page="1"]').click();assert.equal(await page.locator('[data-material-record]').count(),1);assert.equal(await page.locator('[data-material-record]:checked').count(),0);
  await page.locator('[data-material-record="r6"]').check();await page.locator('[data-guide="next"]').click();await page.locator('#materialNote').fill('核对原件日期，归属二月');await page.locator('[data-guide="next"]').click();assert.equal(writes.length,0);
  fail=true;await page.locator('[data-guide="commit"]').click();await page.getByRole('status').filter({hasText:'合成依赖阻断'}).waitFor();assert.equal(await page.locator('#materialNote').inputValue(),'核对原件日期，归属二月');
  fail=false;await page.locator('[data-guide="commit"]').click();await page.getByRole('status').filter({hasText:'所选流水已确认'}).waitFor();assert.deepEqual(writes[1].payload.record_ids,['r6']);assert.equal(writes[1].payload.target_period,'2026-02');assert.equal(writes[1].version,1);assert.equal(writes[1].id,'file');
  assert.equal(await page.evaluate(()=>materialState().screen),'detail');await page.locator('[data-action="material-return-list"]').first().click();await page.locator('[data-filter="bank-periods"]').first().click();
  const incoming=page.locator('.bank-period-item').filter({hasText:'转入流水<img>.xlsx'});await incoming.locator(':scope > summary').click();assert.match(await incoming.innerText(),/未提供/);assert.equal(await incoming.locator('img,script').count(),0);
  denySource=true;await incoming.getByRole('button',{name:'查看源期间依据'}).click();await page.getByText('无源期间权限',{exact:true}).waitFor();await page.locator('#closeDialog').click();denySource=false;
  await incoming.getByRole('button',{name:'查看源期间依据'}).click();await page.locator('#dialogBody pre').waitFor();assert.equal(reads.at(-1).scope.accounting_period_id,'2025-12');assert.equal(reads.at(-1).version,4);await page.locator('#closeDialog').click();assert.equal(await page.evaluate(()=>scope().accounting_period_id),'2026-01');
  await incoming.getByRole('button',{name:'明确接续此条来源引用'}).click();await page.getByRole('status').filter({hasText:'已按来源引用接续'}).waitFor();assert.equal(writes.at(-1).action,'accept_bank_period');assert.equal(writes.at(-1).id,'period');assert.equal(writes.at(-1).version,3);assert.equal(await page.evaluate(()=>state.overview.material_review.records.length),6);assert.equal(await page.evaluate(()=>state.overview.material_review.counts.source_verified),0);
  await incoming.locator(':scope > summary').click();await incoming.locator('[data-period-reason]').fill('误接续，撤销引用');fail=true;await incoming.getByRole('button',{name:'明确撤销本条接续'}).click();await page.getByRole('status').filter({hasText:'合成依赖阻断'}).waitFor();assert.equal(await incoming.locator('[data-period-reason]').inputValue(),'误接续，撤销引用');fail=false;
  await incoming.getByRole('button',{name:'明确撤销本条接续'}).click();await page.getByRole('status').filter({hasText:'已撤销；'}).waitFor();assert.equal(writes.at(-1).action,'revoke_bank_period_intake');assert.equal(writes.at(-1).id,'intake');
  const outgoing=page.locator('.bank-period-item').filter({hasText:'流水!A2 → 2026-02'});await outgoing.locator('summary').click();await outgoing.locator('[data-period-reason]').fill('归属撤销');await outgoing.getByRole('button',{name:'明确撤销其他期间归属'}).click();await page.waitForFunction(()=>!state.busy);assert.equal(writes.at(-1).action,'revoke_bank_period');assert.equal(writes.at(-1).id,'assignment-r6');
  const marker=writes.length;await page.locator('[data-action="bank-period-refresh"]').click();await page.getByRole('status').filter({hasText:'跨期状态已刷新'}).waitFor();assert.equal(writes.length,marker);
  await page.evaluate(()=>{state.role='viewer';render();});assert.equal(await page.locator('[data-period-action="accept"],[data-period-action="revoke"],[data-period-action="revoke-intake"]').count(),0);
  await incoming.locator(':scope > summary').click();const out=path.join(root,'output/playwright/bank-periods');fs.mkdirSync(out,{recursive:true});
  for(const width of [1440,1040,390]){await page.setViewportSize({width,height:width===390?844:900});await page.evaluate(()=>scrollTo(0,0));assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.screenshot({path:path.join(out,'bank-'+width+'.png'),fullPage:width!==390});}
  await page.evaluate(()=>{state.role='operator';task.descriptor.fingerprint='guidance-fp';task.material_opinions=[];task.material_guidance={job_id:'job',job_version:3,valid:true,status:'PROPOSED',descriptor_hash:'guidance-fp',candidates:[{option_id:'confirm_bank_period',reason:'请依据原日期归属 <img>',uncertainties:['仍须逐条选择'],confidence:.9,prefill:{},evidence_refs:['record-1'],steps:[{option_id:'confirm_bank_period',instruction:'核对当前页日期后选择'}]}]};materialState().screen='list';materialState().filter='all';materialState().drafts.delete('task');render();});
  await page.locator('.mat-issue-group button').click();assert.equal(await page.locator('form').count(),0);assert.equal(await page.locator('[data-guide="suggestion-v2"][aria-pressed="true"]').count(),0);assert.equal(guidance.length,0);
  const auto=page.getByRole('region',{name:'自动处理建议',exact:true});assert(await auto.isVisible());assert.equal(await auto.locator('img').count(),0);
  await page.locator('#materialCustomText').fill('合成自由方案，不自动变更原日期');failGuidance=true;await page.locator('[data-guide="custom-validate"]').click();await page.getByRole('status').filter({hasText:'合成验证失败'}).waitFor();assert.equal(await page.locator('#materialCustomText').inputValue(),'合成自由方案，不自动变更原日期');
  failGuidance=false;await page.locator('[data-guide="custom-validate"]').click();await page.getByRole('region',{name:'我的方案验证',exact:true}).waitFor();assert.equal(guidance[0].request_id,guidance[1].request_id);assert.equal(guidance[1].user_text,'合成自由方案，不自动变更原日期');assert.match(await auto.innerText(),/依据原日期/);assert.equal(await page.locator('form').count(),0);
  const savedCount=guidance.length;await page.locator('[data-guide="opinion-save"]').click();await page.getByRole('status').filter({hasText:'意见已保存，尚未执行'}).waitFor();assert.equal(writes.at(-1).action,'save_material_opinion');assert.equal(guidance.length,savedCount);
  await auto.locator('[data-guide="suggestion-v2"]').click();assert.equal(await page.locator('#bankPeriodForm').count(),1);assert.equal(await page.locator('[data-material-record]:checked').count(),0);assert.equal(await page.locator('[data-guide="commit"]').count(),0);
  await page.evaluate(()=>{task.material_guidance={job_id:'job',job_version:3,valid:true,status:'FAILED',descriptor_hash:'guidance-fp',candidates:[]};render();});
  await page.locator('[data-guide="guidance-retry"]').click();await page.getByRole('status').filter({hasText:'建议已明确重试'}).waitFor();assert.equal(writes.at(-1).action,'retry_material_guidance');assert.equal(writes.at(-1).version,3);assert.deepEqual(writes.at(-1).payload,{});
  const writeCount=writes.length;await page.locator('[data-guide="guidance-refresh"]').click();await page.getByRole('status').filter({hasText:'建议状态已刷新'}).waitFor();assert.equal(writes.length,writeCount);assert.equal(guidance.length,savedCount);
  await page.locator('[data-action="material-return-list"]').first().click();await page.locator('[data-action="material-guidance-request"]').click();await page.getByRole('status').filter({hasText:'本期建议已明确请求'}).waitFor();assert.equal(writes.at(-1).action,'request_material_guidance');assert.equal(writes.at(-1).id,'period');assert.equal(writes.at(-1).version,3);
  console.log('PASS: v2 automatic/personal separation, no default option, escaped candidate/source refs, free user_text explicit retry idempotency, local-only opinion save, selected existing option still requires page facts/summary, exact job retry/period queue and refresh with no implicit calls');
  assert.deepEqual(errors,[]);console.log('PASS: explicit 5-row selection/page reset, original summary gate, failure preserves draft, assign/accept/both revokes, cross-scope permission/version source, refresh read-only, viewer, unchanged fact/verification counts, 3 viewports; synthetic network only');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});

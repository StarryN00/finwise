// Explicit isolated acceptance only. Default read-only; never reads credentials from disk.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),{chromium}=require('playwright');
const digest=x=>crypto.createHash('sha256').update(JSON.stringify(x)).digest('hex');
(async()=>{
 const base=new URL(process.env.FINWISE_BROWSER_BASE_URL||'http://127.0.0.1:8767'),mode=process.env.FINWISE_BROWSER_MODE||'readonly',write=mode==='isolated-write';
 assert(['readonly','isolated-write'].includes(mode),'Unknown mode');assert(['127.0.0.1','localhost','[::1]'].includes(base.hostname),'Loopback only');assert(!write||base.port==='8768','Writes are permitted only on isolated port 8768');assert(process.env.FINWISE_BROWSER_PASSWORD,'FINWISE_BROWSER_PASSWORD required');
 const output=path.resolve('output/playwright/guidance-cards-'+mode+'-'+base.port+'-'+Date.now());fs.mkdirSync(output,{recursive:true});
 const browser=await chromium.launch(),page=await browser.newPage({viewport:{width:1440,height:900}}),blocked=[],errors=[],commands=[],httpErrors=[];
 let allowed=null;
 page.on('pageerror',e=>errors.push(e.message));
 page.on('response',r=>{const u=new URL(r.url());if(u.pathname.startsWith('/api/v1/')&&r.status()>=400)httpErrors.push({path:u.pathname,status:r.status()});});
 await page.route('**/*',async route=>{
  const r=route.request(),u=new URL(r.url()),method=r.method(),p=u.pathname;
  let ok=u.origin===base.origin&&!p.includes('/agent/');
  if(ok&&!['GET','HEAD'].includes(method)){
   ok=method==='POST'&&['/api/v1/auth/login','/api/v1/workbench','/api/v1/objects/detail'].includes(p);
   if(write&&method==='POST'&&p==='/api/v1/commands'){
    const body=r.postDataJSON();ok=!!allowed&&body.action===allowed.action&&body.target_id===allowed.id&&body.target_version===allowed.version&&JSON.stringify(body.scope)===JSON.stringify(allowed.scope)&&JSON.stringify(body.payload)===JSON.stringify(allowed.payload);
    if(ok){commands.push({action:body.action});allowed=null;}
   }
  }
  if(!ok){blocked.push({method,path:p});return route.abort();}return route.continue();
 });
 const settle=()=>page.waitForFunction(()=>!state.busy&&state.overview&&JSON.stringify(state.overview.scope)===JSON.stringify(scope()));
 const snapshot=async()=>{
  const data=await page.evaluate(()=>({scope:scope(),facts:state.overview.material_review.records.map(r=>({id:r.object_id,version:r.version,artifact:r.source_artifact_id,values:r.values,comparison:r.comparison})),artifacts:state.overview.artifacts.map(a=>({id:a.object_id,version:a.version,hash:a.data.sha256})),verified:state.overview.material_review.counts.source_verified,usable:state.overview.material_review.counts.accounting_usable}));return {hash:digest(data),records:data.facts.length,verified:data.verified,usable:data.usable};
 };
 const chooseScope=async period=>{
  const index=await page.evaluate(({period,baseline})=>{const s=scope(),keys=['tenant_id','organization_id','legal_entity_id','ledger_id'];const matches=state.scopes.map((x,i)=>({x,i})).filter(({x})=>x.scope.accounting_period_id===period&&keys.every(k=>x.scope[k]===s[k])&&(!baseline||x.scope.baseline_id===baseline));if(matches.length!==1)throw Error('Expected exactly one authorized target scope; set FINWISE_TARGET_BASELINE_ID if ambiguous');return matches[0].i;},{period,baseline:process.env.FINWISE_TARGET_BASELINE_ID||''});
  await page.locator('[data-scope="'+index+'"]').click();await settle();assert.equal(await page.evaluate(()=>scope().accounting_period_id),period);
 };
 const clickCommand=async(locator,expected)=>{
  assert(write);allowed=expected;
  const response=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/v1/commands'&&r.request().method()==='POST');await locator.click();const r=await response;assert(r.ok(),'Command rejected; inspect local page feedback');const body=await r.json();assert.equal(body.command?.status,'SUCCEEDED');await settle();assert.equal(allowed,null,'Expected command was not sent');return body.effect;
 };
 try{
  await page.goto(new URL('/static/operator.html',base).href);await page.locator('#username').fill(process.env.FINWISE_BROWSER_USERNAME||'juxianda-staging');await page.locator('#password').fill(process.env.FINWISE_BROWSER_PASSWORD);const loginResponse=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/v1/auth/login');await page.locator('#loginForm button').click();const login=await loginResponse;assert(login.ok(),'Login HTTP '+login.status()+'; no business commands sent');await page.locator('#currentTask').waitFor();await settle();
  const sourcePeriod=process.env.FINWISE_SOURCE_PERIOD||'2026-01';if(await page.evaluate(()=>scope().accounting_period_id)!==sourcePeriod)await chooseScope(sourcePeriod);
  const before=await snapshot(),sourceScope=await page.evaluate(()=>scope());
  await page.locator('[data-action="material-open-filter"][data-filter="all"]').first().click();await settle();
  const taskId=await page.evaluate(()=>{const t=state.overview.material_review.tasks.find(t=>t.bank_period&&!t.deferred&&(!t.triage||t.triage.route==='HUMAN'));if(!t)throw Error('No eligible bank_period task; use a fresh isolated copy');return t.id;});
  const group=page.locator('.mat-issue-group [data-task]').filter({hasText:/进入处理/});
  const groupTask=await page.evaluate(id=>{const groups=materialIssueGroups();const g=groups.find(g=>g.tasks.some(t=>t.id===id));return g?.tasks[0].id;},taskId);assert(groupTask,'Missing visible bank group');
  await page.locator('.mat-issue-group [data-task="'+groupTask+'"]').click();await settle();
  assert.equal(await page.evaluate(()=>currentMaterialTask().id),taskId,'Bank group first task differs; select a fresh single bank group fixture');
  assert.equal(await page.locator('.decision-chat form').count(),0,'No option may be preselected');assert(await page.locator('.decision-evidence').isVisible());
  for(const width of [1440,1040,390]){await page.setViewportSize({width,height:width===390?844:900});await page.evaluate(()=>scrollTo(0,0));assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.screenshot({path:path.join(output,'source-'+width+'.png'),fullPage:width!==390});}
  if(!write){assert.deepEqual(await snapshot(),before);assert.equal(commands.length,0);assert.equal(blocked.length,0);assert.deepEqual(errors,[]);console.log(JSON.stringify({status:'PASS',mode,commands:0,output}));return;}
  await page.locator('[data-guide="option"][data-option="confirm_bank_period"]').click();assert.equal(await page.locator('[data-material-record]:checked').count(),0);
  const recordIds=await page.locator('[data-material-record]').evaluateAll(es=>es.map(e=>e.dataset.materialRecord));assert(recordIds.length>=1&&recordIds.length<=5);await page.locator('[data-material-record]').first().check();
  const selected=[recordIds[0]],targetPeriod=await page.evaluate(()=>currentMaterialTask().bank_period.target_period);assert.equal(targetPeriod,process.env.FINWISE_TARGET_PERIOD||'2026-02');
  await page.locator('[data-guide="next"]').click();await page.locator('#materialNote').fill('隔离副本验收：已核对原件交易日期，仅确认所属月份。');await page.locator('[data-guide="next"]').click();assert(await page.locator('.decision-summary').isVisible());assert.equal(commands.length,0);
  const expected=await page.evaluate(ids=>{const t=currentMaterialTask();return {action:'confirm_bank_period',id:t.artifact_id,version:t.artifact_version,scope:scope(),payload:{task_id:t.id,input_token:t.bank_period.input_token,record_ids:ids,target_period:t.bank_period.target_period,reason:materialDraft(t).note.trim()}};},selected);
  const assigned=await clickCommand(page.locator('[data-guide="commit"]'),expected),assignment=assigned.objects?.[0];assert(assignment?.object_id);assert.deepEqual(await snapshot(),before,'Source values/versions/hash or verification/accounting counts changed');
  await page.locator('#openSidebar').click();await chooseScope(targetPeriod);
  await page.setViewportSize({width:1440,height:900});
  const targetBefore=await snapshot();await page.locator('[data-action="material-open-filter"][data-filter="all"]').first().click();await page.locator('[data-filter="bank-periods"]').first().click();
  const incoming=page.locator('.bank-period-item').filter({has:page.locator('[data-period-id="'+assignment.object_id+'"][data-period-direction="incoming"]')});await incoming.locator(':scope > summary').click();
  const accept=await page.evaluate(id=>{const x=state.overview.bank_periods.incoming.find(x=>x.assignment_id===id);if(x?.status!=='READY')throw Error('Incoming is not READY; no duplicate or stale intake will be forced');return {action:'accept_bank_period',id:state.overview.period.object_id,version:state.overview.period.version,scope:scope(),payload:{assignment_id:x.assignment_id,assignment_version:x.assignment_version,input_token:x.input_token}};},assignment.object_id);
  const intake=await clickCommand(incoming.locator('[data-period-action="accept"]'),accept);assert.deepEqual(await snapshot(),targetBefore,'Intake must not add FactRecords or verification/accounting counts');
  if(await incoming.getAttribute('open')===null)await incoming.locator(':scope > summary').click();
  await incoming.locator('[data-period-reason]').fill('隔离验收结束，撤销本次来源接续。');
  await clickCommand(incoming.locator('[data-period-action="revoke-intake"]'),{action:'revoke_bank_period_intake',id:intake.object.object_id,version:intake.object.version,scope:await page.evaluate(()=>scope()),payload:{reason:'隔离验收结束，撤销本次来源接续。'}});assert.deepEqual(await snapshot(),targetBefore);
  const sourceIndex=await page.evaluate(s=>state.scopes.findIndex(x=>JSON.stringify(x.scope)===JSON.stringify(s)),sourceScope);assert(sourceIndex>=0);await page.locator('[data-scope="'+sourceIndex+'"]').click();await settle();
  const materialLink=page.locator('[data-action="material-open-filter"][data-filter="all"]').first();
  if(await materialLink.isVisible())await materialLink.click();
  else {const back=page.locator('[data-action="material-return-list"]').first();if(await back.isVisible())await back.click();}
  await page.locator('[data-filter="bank-periods"]').first().click();
  const outgoing=page.locator('.bank-period-item').filter({has:page.locator('[data-period-id="'+assignment.object_id+'"][data-period-direction="outgoing"]')});await outgoing.locator(':scope > summary').click();await outgoing.locator('[data-period-reason]').fill('隔离验收结束，撤销本次期间归属。');
  const currentVersion=await page.evaluate(id=>state.overview.bank_periods.outgoing.find(x=>x.object_id===id).version,assignment.object_id);
  await clickCommand(outgoing.locator('[data-period-action="revoke"]'),{action:'revoke_bank_period',id:assignment.object_id,version:currentVersion,scope:sourceScope,payload:{reason:'隔离验收结束，撤销本次期间归属。'}});assert.deepEqual(await snapshot(),before);
  assert.equal(blocked.length,0);assert.deepEqual(errors,[]);fs.writeFileSync(path.join(output,'report.json'),JSON.stringify({status:'PASS',mode,commands,before,after:await snapshot(),targetBefore,output},null,2));console.log(JSON.stringify({status:'PASS',mode,commands:commands.map(x=>x.action),output}));
 }catch(e){await page.screenshot({path:path.join(output,'failure.png'),fullPage:true}).catch(()=>{});console.error(JSON.stringify({output,httpErrors,commands,blocked}));throw e;}
 finally{await browser.close();}
})().catch(e=>{console.error(e.message);process.exitCode=1;});

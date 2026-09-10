// Retained/isolated service acceptance. Browser writes are deny-by-default.
// Sensitive screenshots stay local; stdout/report contain counts and hashes only.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {chromium}=require('playwright');
const canonical=x=>Array.isArray(x)?x.map(canonical):x&&typeof x==='object'?Object.fromEntries(Object.keys(x).sort().map(k=>[k,canonical(x[k])])):x;
const hash=x=>crypto.createHash('sha256').update(JSON.stringify(canonical(x))).digest('hex');
(async()=>{
 const base=new URL(process.env.FINWISE_BROWSER_BASE_URL||'http://127.0.0.1:8767');
 assert(['127.0.0.1','localhost','[::1]'].includes(base.hostname),'Only a local acceptance service is allowed');
 assert(process.env.FINWISE_BROWSER_PASSWORD,'FINWISE_BROWSER_PASSWORD is required');
 const out=path.resolve('output/playwright/issue-triage-'+(base.port||'local')+'-'+Date.now());fs.mkdirSync(out,{recursive:true});
 const browser=await chromium.launch(),page=await browser.newPage({viewport:{width:1440,height:900}}),blocked=[],errors=[],requests=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',async route=>{
  const r=route.request(),u=new URL(r.url()),p=u.pathname;
  if(u.origin!==base.origin||p.includes('/agent/')||p==='/api/v1/commands'||(!['GET','HEAD'].includes(r.method())&&!(r.method()==='POST'&&['/api/v1/auth/login','/api/v1/workbench','/api/v1/objects/detail'].includes(p)))){
   blocked.push({method:r.method(),path:p});return route.abort();
  }
  if(p.startsWith('/api/v1/'))requests.push({method:r.method(),path:p});
  return route.continue();
 });
 const settle=()=>page.waitForFunction(()=>!state.busy);
 const snapshot=async()=>{
  const data=await page.evaluate(()=>{
   const objects=new Map();function visit(x){if(!x||typeof x!=='object')return;if(x.object_type&&x.object_id&&Number.isInteger(x.version))objects.set(x.object_type+':'+x.object_id+':'+x.version,x);for(const v of Object.values(x))visit(v);}
   visit(state.overview);
   return {objects:[...objects].sort(([a],[b])=>a.localeCompare(b)),records:state.overview.material_review.records,counts:state.overview.material_review.counts,scope:scope()};
  });return {objects:hash(data.objects),records:hash(data.records),counts:hash(data.counts),scope:hash(data.scope),objectCount:data.objects.length,recordCount:data.records.length};
 };
 try{
  await page.goto(new URL('/static/operator.html',base).href);
  await page.locator('#username').fill(process.env.FINWISE_BROWSER_USERNAME||'juxianda-staging');await page.locator('#password').fill(process.env.FINWISE_BROWSER_PASSWORD);await page.locator('#loginForm button').click();await page.locator('#currentTask').waitFor();await settle();
  const before=await snapshot();
  await page.locator('[data-action="material-open-filter"][data-filter="all"]').first().click();await page.locator('#materialWorkbench').waitFor();await settle();
  const humanIds=await page.evaluate(()=>state.overview.material_review.tasks.filter(t=>t.kind!=='VERIFY'&&!t.deferred&&(!t.triage||t.triage.route==='HUMAN')).map(t=>t.id));
  const visibleIds=await page.locator('.mat-issue-group [data-task]').evaluateAll(bs=>bs.map(b=>b.dataset.task));
  assert(visibleIds.length>0&&visibleIds.every(id=>humanIds.includes(id)),'Default queue must contain HUMAN only');
  await page.locator('[data-action="material-filter"][data-filter="system"]').click();await settle();
  assert(await page.locator('.mat-issue-group').count()>0,'Expected a current SYSTEM task');
  await page.locator('.mat-issue-group [data-task]').first().click();await settle();
  assert.equal(await page.evaluate(()=>currentMaterialTask().triage.route),'SYSTEM');
  const systemId=await page.locator('.decision-chat').getAttribute('data-task-id');
  assert(await page.locator('.decision-key-table').isVisible());assert(await page.locator('.decision-source').isVisible());
  assert(await page.locator('.problem-source-audit').isVisible(),'Source audit must be visible');
  assert(await page.evaluate(()=>document.querySelector('.problem-source-audit').textContent.includes(currentMaterialTask().triage.source_audit.message)),'Exact source audit message must be displayed');
  const expectedTables=await page.evaluate(()=>({relationships:currentMaterialTask().triage.checks.filter(c=>c.relationships?.length).length,balances:currentMaterialTask().triage.checks.filter(c=>c.balances?.length).length}));
  for(const [field,label] of [['relationships','红蓝发票关联'],['balances','金额抵销核对']]){
   const tables=page.getByRole('region',{name:'系统已核对的数据',exact:true}).getByRole('region',{name:label,exact:true});
   assert(expectedTables[field]>0,'Expected '+label+' in the triage checks');
   assert.equal(await tables.count(),expectedTables[field],label+' count must match all checks');
   for(let i=0;i<expectedTables[field];i++)assert(await tables.nth(i).isVisible(),label+' '+(i+1)+' must be visible');
  }
  assert.equal(await page.locator('.decision-chat form,.decision-chat [data-guide="option"],.decision-chat [data-guide="open"],.decision-chat [data-guide="commit"],.decision-chat [data-action="material-defer"],.decision-chat [data-action="material-supplement"]').count(),0);
  const originalRequest=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/v1/objects/detail'&&r.ok());
  await page.locator('.decision-source [data-object]').first().click();await originalRequest;await page.locator('#dialog[open]').waitFor();await page.locator('#closeDialog').click();
  assert.equal(await page.locator('.decision-chat').getAttribute('data-task-id'),systemId);
  for(const width of [1440,1040,390]){await page.setViewportSize({width,height:width===390?844:900});await page.evaluate(()=>scrollTo(0,0));assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Page overflow');await page.screenshot({path:path.join(out,'system-'+width+'.png'),fullPage:width!==390});if(width===390)await page.screenshot({path:path.join(out,'system-390-full.png'),fullPage:true});}
  const marker=requests.length,refresh=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/v1/workbench'&&r.ok());
  await page.locator('[data-action="problem-review-refresh"]').click();await refresh;await settle();
  assert(requests.slice(marker).filter(r=>r.method==='POST').every(r=>r.path==='/api/v1/workbench'),'Refresh must only read workbench');
  assert.equal(await page.locator('.decision-chat').getAttribute('data-task-id'),systemId);assert.deepEqual(await snapshot(),before,'Objects, records, counts or scope changed');
  await page.locator('[data-action="material-return-list"]').first().click();await page.locator('[data-filter="all"]').first().click();await page.locator('.mat-issue-group [data-task]').first().click();await settle();
  assert.equal(await page.evaluate(()=>currentMaterialTask().triage?.route||'HUMAN'),'HUMAN');assert(await page.locator('.decision-chat form').isVisible(),'Human workflow must remain available');
  if(await page.evaluate(()=>materialCanWrite()))assert(await page.locator('[data-guide="next"],[data-guide="open"]').first().isEnabled(),'Human action must remain enabled');
  const humanId=await page.locator('.decision-chat').getAttribute('data-task-id');
  await page.reload();await page.locator('.decision-chat').waitFor();await settle();assert.equal(await page.locator('.decision-chat').getAttribute('data-task-id'),humanId);
  assert.deepEqual(await snapshot(),before,'Read-only navigation changed persisted projections');assert.equal(blocked.length,0,'A prohibited request was attempted');assert.equal(errors.length,0,'Browser errors occurred');
  fs.writeFileSync(path.join(out,'report.json'),JSON.stringify({status:'PASS',business_writes:0,model_requests:0,before,after:await snapshot(),blocked,errors,flows:['HUMAN default','SYSTEM source audit and red-blue tables','source return','read-only refresh','return to HUMAN','reload restore','three viewports']},null,2));
  console.log(JSON.stringify({status:'PASS',business_writes:0,model_requests:0,objectCount:before.objectCount,recordCount:before.recordCount,output:out}));
 }catch(error){await page.screenshot({path:path.join(out,'failure.png'),fullPage:true}).catch(()=>{});throw error;}
 finally{await browser.close();}
})().catch(error=>{console.error(error.message);process.exitCode=1;});

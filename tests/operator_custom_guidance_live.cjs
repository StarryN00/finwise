// Formal model acceptance on port 8768 only. No financial command is permitted.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),{chromium}=require('playwright');
(async()=>{
 const base='http://127.0.0.1:8768',out=path.resolve('output/playwright/guidance-custom-live');fs.mkdirSync(out,{recursive:true});
 assert(process.env.FINWISE_BROWSER_PASSWORD);
 const browser=await chromium.launch(),page=await browser.newPage({viewport:{width:1440,height:900}}),errors=[],requests=[];
 let expected=null;
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',async route=>{
  const r=route.request(),u=new URL(r.url());assert.equal(u.origin,base);
  if(u.pathname==='/api/v1/commands')return route.abort();
  if(u.pathname==='/api/v1/agent/suggestion'){
   const b=r.postDataJSON();assert(expected,'Unsolicited model call');assert.equal(b.task_id,expected.task_id);assert.equal(b.descriptor_hash,expected.descriptor_hash);assert.equal(b.user_text,'按原交易日期归属');requests.push(b);expected=null;
  }
  return route.continue();
 });
 try{
  await page.goto(base+'/static/operator.html');await page.locator('#username').fill('juxianda-staging');await page.locator('#password').fill(process.env.FINWISE_BROWSER_PASSWORD);await page.locator('#loginForm button').click();await page.locator('#currentTask').waitFor();
  await page.locator('[data-action="material-open-filter"][data-filter="all"]').first().click();
  const id=await page.evaluate(()=>{const task=state.overview.material_review.tasks.find(t=>t.bank_period);return materialIssueGroups().find(g=>g.tasks.some(t=>t.id===task.id)).tasks[0].id;});
  await page.locator('.mat-issue-group [data-task="'+id+'"]').click();
  assert.equal(await page.locator('.decision-chat form').count(),0);
  const before=await page.evaluate(()=>({counts:state.overview.material_review.counts,facts:state.overview.fact_summaries}));
  expected=await page.evaluate(()=>({task_id:currentMaterialTask().id,descriptor_hash:currentMaterialTask().descriptor.fingerprint}));
  await page.locator('#materialCustomText').fill('按原交易日期归属');
  const result=page.waitForResponse(r=>r.url().endsWith('/api/v1/agent/suggestion'),{timeout:120000});
  await page.locator('[data-guide="custom-validate"]').click();const response=await result;assert(response.ok());const data=await response.json();
  assert(['PROPOSED','NEEDS_HUMAN'].includes(data.status));assert.equal(data.metadata.mock,false);
  await page.getByRole('region',{name:'我的方案验证',exact:true}).waitFor();assert.equal(await page.locator('.decision-chat form').count(),0);
  const i=data.candidates.findIndex(c=>c.option_id==='confirm_bank_period');
  if(i>=0)await page.locator('[data-guide="suggestion-v2"][data-channel="personal"][data-index="'+i+'"]').click();
  else await page.locator('[data-guide="option"][data-option="confirm_bank_period"]').click();
  assert.equal(await page.locator('[data-material-record]:checked').count(),0);
  assert.deepEqual(await page.evaluate(()=>({counts:state.overview.material_review.counts,facts:state.overview.fact_summaries})),before);
  await page.reload();await page.waitForFunction(()=>state.overview&&currentMaterialTask());
  assert.equal(requests.length,1);assert.equal(await page.locator('#materialCustomText').inputValue(),'按原交易日期归属');
  for(const width of [1440,1040,390]){await page.setViewportSize({width,height:width===390?844:900});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.locator('.decision-agent').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,'custom-'+width+'.png'),fullPage:width!==390});}
  assert.deepEqual(errors,[]);fs.writeFileSync(path.join(out,'report.json'),JSON.stringify({status:'PASS',suggestion_status:data.status,selected_from:i>=0?'AGENT_CANDIDATE':'DECLARED_RULE_OPTION',model_calls:1,metadata:data.metadata,financial_commands:0,refresh_calls:0,output:out},null,2));console.log(JSON.stringify({status:'PASS',model_calls:1,financial_commands:0,output:out}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e.message);process.exitCode=1;});

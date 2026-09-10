// Read-only retained-data inspection. No commands, uploads or provider calls allowed.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),{chromium}=require('playwright');
(async()=>{
 if(!process.env.FINWISE_BROWSER_PASSWORD)throw Error('Existing staging password required');
 const out=path.resolve(__dirname,'../output/playwright/mapping-live');fs.mkdirSync(out,{recursive:true});
 const browser=await chromium.launch(),page=await browser.newPage({viewport:{width:1440,height:900}}),writes=[],errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/api/v1/**',async route=>{const r=route.request();if(r.method()!=='GET'&&/\/(commands|artifacts|agent\/)/.test(new URL(r.url()).pathname)){writes.push(r.url());return route.abort();}await route.continue();});
 try{
  await page.goto('http://127.0.0.1:8767/static/operator.html');await page.locator('#username').fill('juxianda-staging');await page.locator('#password').fill(process.env.FINWISE_BROWSER_PASSWORD);await page.locator('#loginForm button').click();await page.locator('#currentTask').waitFor();
  const before=await page.evaluate(()=>JSON.stringify({counts:state.overview.material_review.counts,baseline:state.overview.baseline,historical:state.overview.historical_issue_plans}));
  await page.locator('[data-action="artifacts"]').first().click();await page.locator('tr').filter({hasText:'2026.1月聚贤达工资表.xls'}).locator('[data-action="mapping-open"]').click();await page.locator('#mappingConfirmed').waitFor();
  const job=await page.evaluate(()=>mappingJob());assert.equal(job.status,'REVIEW');assert.equal(job.data.gateway.mock,false);assert.equal(job.data.preview.records.length,14);assert.equal(await page.locator('#mappingConfirmed').isChecked(),false);
  assert.match(await page.locator('#mappingWorkbench').innerText(),/14 条候选记录/);
  for(const [width,height] of [[1440,900],[1040,900],[390,844]]){await page.setViewportSize({width,height});await page.evaluate(()=>window.scrollTo(0,0));assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.screenshot({path:path.join(out,`mapping-${width}.png`),fullPage:true});}
  await page.locator('#mappingWorkbench [data-object]').click();await page.locator('#dialog[open]').waitFor();await page.keyboard.press('Escape');
  await page.reload();await page.locator('#mappingConfirmed').waitFor();assert.equal(await page.locator('#mappingConfirmed').isChecked(),false);
  await page.locator('[data-action="mapping-return"]').first().click();await page.locator('#materialWorkbench').waitFor();
  const after=await page.evaluate(()=>JSON.stringify({counts:state.overview.material_review.counts,baseline:state.overview.baseline,historical:state.overview.historical_issue_plans}));assert.equal(before,after);assert.deepEqual(writes,[]);assert.deepEqual(errors,[]);
  const report={status:'PASS',job_id:job.object_id,preview_rows:14,mock:false,human_confirmations:0,financial_state_unchanged:true,viewports:[1440,1040,390],writes,errors};fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});

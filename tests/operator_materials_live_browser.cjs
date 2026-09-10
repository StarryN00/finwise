// Read-only live validation: command, artifact and model writes are blocked by the browser.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),{chromium}=require('playwright');
(async()=>{
 if(!process.env.FINWISE_BROWSER_PASSWORD)throw Error('Provide existing staging password');
 const out=path.resolve(__dirname,'../output/playwright/materials-live');fs.mkdirSync(out,{recursive:true});
 const browser=await chromium.launch({headless:true}),page=await browser.newPage({viewport:{width:1440,height:900}}),errors=[],writes=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/api/v1/**',async route=>{const r=route.request();if(r.method()!=='GET'&&/\/(commands|artifacts|agent\/)/.test(new URL(r.url()).pathname)){writes.push(r.url());return route.abort();}await route.continue();});
 try{
  await page.goto('http://127.0.0.1:8767/static/operator.html');await page.locator('#username').fill('juxianda-staging');await page.locator('#password').fill(process.env.FINWISE_BROWSER_PASSWORD);await page.locator('#loginForm button').click();await page.locator('#currentTask').waitFor();
  const snapshot=()=>page.evaluate(()=>JSON.stringify({scope:state.overview.scope,plans:state.overview.historical_issue_plans,baseline:state.overview.baseline,job:state.overview.historical_preparation}));const before=await snapshot();
  await page.locator('[data-action="history-next-work"]').first().click();await page.locator('#materialWorkbench').waitFor();
  assert.match(await page.locator('.mat-history').innerText(),/2 项处理意见已记录，其中 2 项暂无法补充/);
  const expected=JSON.parse(fs.readFileSync(path.resolve(__dirname,'../output/material-clarity/retained.json'),'utf8'));
  const counts=await page.evaluate(()=>state.overview.material_review.counts);assert.deepEqual(counts,expected.after);assert.equal(counts.records,232);assert.equal(counts.files,14);assert.equal(counts.source_verified,0);assert.equal(counts.accounting_usable,0);assert.equal(await page.locator('.mat-filters button').count(),3);
  for(const [width,height] of [[1440,900],[1040,900],[390,844]]){await page.setViewportSize({width,height});await page.evaluate(()=>window.scrollTo(0,0));assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));assert.equal(await page.locator('#materialWorkbench .primary').count(),1);await page.screenshot({path:path.join(out,`overview-${width}.png`)});await page.locator('.mat-task .primary').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,`task-${width}.png`)});}
  await page.setViewportSize({width:1440,height:900});await page.locator('[data-filter="results"]').first().click();await page.screenshot({path:path.join(out,'results-1440.png'),fullPage:true});
  await page.locator('tr').filter({hasText:'2026.1月聚贤达工资表.xls'}).getByRole('button',{name:'查看提取值并核实'}).click();
  const payroll=page.locator('.mat-record').first();assert.match(await payroll.innerText(),/单位公积金/);assert.match(await payroll.innerText(),/个人公积金/);assert.match(await payroll.innerText(),/工资表标题/);assert.match(await payroll.innerText(),/1,?369.23/);assert.match(await payroll.innerText(),/524.96/);assert.match(await payroll.innerText(),/248/);
  for(const [width,height] of [[1440,900],[1040,900],[390,844]]){await page.setViewportSize({width,height});await payroll.scrollIntoViewIfNeeded();assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.screenshot({path:path.join(out,`payroll-${width}.png`)});}
  assert(await payroll.locator('tbody tr').first().evaluate(row=>row.querySelector('th').getBoundingClientRect().width>row.getBoundingClientRect().width*.8),'Mobile field label must fill the row');
  await payroll.locator('[data-object]').click();await page.locator('#dialog[open]').waitFor();await page.keyboard.press('Escape');assert.equal(await page.locator('[data-material-record]:checked').count(),0);
  await page.locator('[data-action="material-files"]').click();await page.locator('#receivedFiles').waitFor();assert.match(await page.locator('#receivedFiles').innerText(),/17 份原件/);await page.locator('[data-action="return-files"]').click();await page.reload();await page.locator('#materialWorkbench').waitFor();assert.equal(await snapshot(),before);
  assert.deepEqual(writes,[]);assert.deepEqual(errors,[]);fs.writeFileSync(path.join(out,'report.json'),JSON.stringify({status:'PASS',counts,writes,errors,viewports:[1440,1040,390],flows:['historical handoff','January overview','direct data and recommendation','source inspection','all files and return','reload'],human_confirmation:false},null,2));console.log(JSON.stringify({status:'PASS',counts,writes,errors}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});

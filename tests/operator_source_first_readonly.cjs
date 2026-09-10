// Retained service: forbid every business/model write, compare current data across navigation.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright');
(async()=>{
 const out=path.resolve('output/playwright/source-first-retained');fs.mkdirSync(out,{recursive:true});
 assert(process.env.FINWISE_BROWSER_PASSWORD);const browser=await chromium.launch(),page=await browser.newPage({viewport:{width:1440,height:900}}),blocked=[],errors=[];
 await page.route('**/api/v1/**',r=>{const req=r.request(),p=new URL(req.url()).pathname;
  if(req.method()!=='GET'&&!['/api/v1/auth/login','/api/v1/workbench','/api/v1/objects/detail'].includes(p)){blocked.push(p);return r.abort();}return r.continue();});
 page.on('pageerror',e=>errors.push(e.message));
 try{
  await page.goto('http://127.0.0.1:8767/static/operator.html');await page.locator('#username').fill('juxianda-staging');await page.locator('#password').fill(process.env.FINWISE_BROWSER_PASSWORD);await page.locator('#loginForm button').click();await page.locator('#currentTask').waitFor();
  const snapshot=()=>page.evaluate(()=>({records:state.overview.material_review.records,counts:state.overview.material_review.counts,artifacts:state.overview.artifacts})),before=await snapshot();
  await page.locator('[data-action="issues"]').first().click();await page.locator('.mat-issue-group').filter({hasText:'发票状态'}).getByRole('button',{name:/进入处理/}).click();
  await page.locator('.decision-key-table').waitFor();assert.match(await page.locator('.decision-key-table').innerText(),/已红冲-全额/);assert.equal(await page.locator('.decision-summary').count(),0);
  const backendPresentation=await page.evaluate(()=>!!currentMaterialTask().descriptor.presentation);
  if(!backendPresentation)assert.match(await page.locator('.decision-explanation').innerText(),/尚未提供具体问题解释/);
  await page.locator('.decision-source [data-object]').first().click();await page.locator('#dialog[open]').waitFor();await page.keyboard.press('Escape');
  for(const [width,height] of [[1440,900],[1040,900],[390,844]]){await page.setViewportSize({width,height});await page.evaluate(()=>scrollTo(0,0));assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.screenshot({path:path.join(out,`detail-${width}.png`),fullPage:true});}
  await page.reload();await page.locator('.decision-key-table').waitFor();assert.deepEqual(await snapshot(),before);assert.deepEqual(blocked,[]);assert.deepEqual(errors,[]);
  fs.writeFileSync(path.join(out,'report.json'),JSON.stringify({status:'PASS',backendPresentation,business_writes:0,blocked,errors,counts:before.counts},null,2));console.log(JSON.stringify({status:'PASS',backendPresentation,business_writes:0}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});

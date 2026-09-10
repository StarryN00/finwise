// Read-only verification of saved historical decisions in the real January staging scope.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright');
(async()=>{
  if(!process.env.FINWISE_BROWSER_PASSWORD)throw Error('Provide existing staging password');
  const out=path.resolve(__dirname,'../output/playwright/historical-handoff-live');fs.mkdirSync(out,{recursive:true});
  const browser=await chromium.launch({headless:true}),page=await browser.newPage({viewport:{width:1440,height:900}}),errors=[],writes=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/api/v1/**',async route=>{
    const r=route.request();if(r.method()!=='GET'&&/\/(commands|artifacts|agent\/)/.test(new URL(r.url()).pathname)){writes.push(r.url());return route.abort();}await route.continue();
  });
  try{
    await page.goto('http://127.0.0.1:8767/static/operator.html');await page.locator('#username').fill('juxianda-staging');
    await page.locator('#password').fill(process.env.FINWISE_BROWSER_PASSWORD);await page.locator('#loginForm button').click();await page.locator('#currentTask').waitFor();
    const snapshot=()=>page.evaluate(()=>JSON.stringify({scope:state.overview.scope,plans:state.overview.historical_issue_plans,baseline:state.overview.baseline,job:state.overview.historical_preparation}));
    const before=await snapshot();assert.equal(await page.evaluate(()=>historicalIssueFlow().done),true);
    assert.match(await page.locator('#currentTask').innerText(),/2 \/ 2/);assert.equal(await page.locator('#currentTask .primary').count(),1);
    await page.locator('#currentTask [data-action="historical-details"]').click();await page.locator('#historyHandoff').waitFor();
    for(const [width,height] of [[1440,900],[1040,900],[390,844]]){
      await page.setViewportSize({width,height});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
      await page.screenshot({path:path.join(out,`handoff-${width}.png`)});
    }
    await page.locator('#historyHandoff [data-action="history-next-work"]').click();await page.locator('#receivedTitle').waitFor();
    assert.equal(await page.evaluate(()=>state.filesFilter),'business');assert(await page.locator('[data-parse]').count()>0);
    await page.locator('[data-parse]').first().click();await page.locator('#parseForm').waitFor();
    await page.screenshot({path:path.join(out,'next-parse-390.png')});await page.keyboard.press('Escape');
    await page.locator('[data-action="return-files"]').click();await page.locator('#historyHandoff').waitFor();
    await page.reload();await page.locator('#currentTask').waitFor();assert.equal(await snapshot(),before);
    assert.deepEqual(writes,[]);assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(out,'report.json'),JSON.stringify({status:'PASS',financialWrites:writes,errors,scope:'聚贤达 2026-01',viewportWidths:[1440,1040,390],flows:['saved round summary','next current-period files','parse dialog without submitting','return and reload']},null,2));
    console.log('PASS real January handoff, next file action, return and reload; no financial writes');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});

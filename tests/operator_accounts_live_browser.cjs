// Retained staging: read-only inspection, no account or source approvals.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),{chromium}=require('playwright');
(async()=>{
 if(!process.env.FINWISE_BROWSER_PASSWORD)throw Error('Existing staging password required');
 const out=path.resolve(__dirname,'../output/playwright/bank-accounts-live');fs.mkdirSync(out,{recursive:true});
 const browser=await chromium.launch(),page=await browser.newPage({viewport:{width:1440,height:900}}),writes=[],errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/api/v1/**',async route=>{const r=route.request();if(r.method()!=='GET'&&/\/(commands|artifacts|agent\/)/.test(new URL(r.url()).pathname)){writes.push(r.url());return route.abort();}await route.continue();});
 try{
  await page.goto('http://127.0.0.1:8767/static/operator.html');await page.locator('#username').fill('juxianda-staging');await page.locator('#password').fill(process.env.FINWISE_BROWSER_PASSWORD);await page.locator('#loginForm button').click();await page.locator('#currentTask').waitFor();
  const before=await page.evaluate(()=>JSON.stringify({counts:state.overview.material_review.counts,baseline:state.overview.baseline,historical:state.overview.historical_issue_plans,artifacts:state.overview.artifacts.map(a=>[a.object_id,a.version])}));
  await page.locator('[data-action="accounts-open"]').first().click();await page.locator('#bankTitle').waitFor();
  const bank=await page.evaluate(()=>state.overview.bank_accounts.statements.find(c=>c.filename==='2026.1月聚贤达农业银行流水.xls'));
  assert(['NEW','LINKED'].includes(bank.status));assert.equal(bank.record_count,17);assert.equal(bank.identity.sources.account_number.region,'账户明细!A2');assert(bank.identity.holder);assert.equal(bank.identity.currency,'CNY');assert.equal(bank.identity.bank_hint,'中国农业银行');
  const pending=await page.evaluate(()=>state.overview.bank_accounts.statements.find(c=>c.status==='NEW'&&!c.requires_specific_account));assert(pending);
  await page.locator(`[data-action="accounts-statement"][data-artifact="${pending.artifact_id}"]`).click();await page.locator('#bankAccountForm').waitFor();
  assert.match(await page.locator('.mat-task').innerText(),/已识别银行/);assert.equal(await page.locator('[name="confirmed"]').isChecked(),false);assert.equal(await page.locator('[name="account_number"]:visible').count(),0);
  for(const [width,height] of [[1440,900],[1040,900],[390,844]]){await page.setViewportSize({width,height});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.screenshot({path:path.join(out,`candidate-${width}.png`),fullPage:true});}
  await page.getByRole('button',{name:'查看完整原件',exact:true}).click();await page.locator('#dialog[open]').waitFor();await page.keyboard.press('Escape');
  await page.reload();await page.waitForFunction(()=>!!state.overview?.bank_accounts);
  const after=await page.evaluate(()=>JSON.stringify({counts:state.overview.material_review.counts,baseline:state.overview.baseline,historical:state.overview.historical_issue_plans,artifacts:state.overview.artifacts.map(a=>[a.object_id,a.version])}));assert.equal(before,after);
  assert.deepEqual(writes,[]);assert.deepEqual(errors,[]);
  const report={status:'PASS',source:'账户明细!A2',transactions:17,agricultural_account_status:bank.status,preview_bank:pending.identity.bank_name||pending.identity.bank_hint,human_confirmations_submitted:0,financial_state_unchanged:true,viewports:[1440,1040,390],writes,errors};fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});

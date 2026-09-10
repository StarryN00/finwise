// Read-only navigation against a refreshed dataset. All business/model writes blocked.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright');
(async()=>{
 const expected=JSON.parse(fs.readFileSync(process.env.FINWISE_REFRESH_REPORT,'utf8'));
 const out=path.resolve('output/playwright/parsing-refresh-'+expected.mode);fs.mkdirSync(out,{recursive:true});
 assert(process.env.FINWISE_BROWSER_PASSWORD,'Existing test login required');
 const browser=await chromium.launch(),page=await browser.newPage({viewport:{width:1440,height:900}}),errors=[],blocked=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/api/v1/**',async route=>{
  const r=route.request(),p=new URL(r.url()).pathname;
  if(r.method()!=='GET'&&!['/api/v1/auth/login','/api/v1/workbench','/api/v1/objects/detail'].includes(p)){blocked.push(p);return route.abort();}
  await route.continue();
 });
 try{
  await page.goto((process.env.FINWISE_BROWSER_BASE||'http://127.0.0.1:8767')+'/static/operator.html');
  await page.locator('#username').fill('juxianda-staging');await page.locator('#password').fill(process.env.FINWISE_BROWSER_PASSWORD);
  await page.locator('#loginForm button').click();await page.locator('#currentTask').waitFor();
  assert.deepEqual(await page.evaluate(()=>state.overview.material_review.counts),expected.after_counts);
  await page.locator('[data-action="issues"]').first().click();await page.locator('#materialWorkbench').waitFor();
  assert(!/金额格式无效|日期缺失或不能确定/.test(await page.locator('#materialWorkbench').innerText()));
  assert.equal(await page.evaluate(()=>state.overview.material_review.tasks.filter(t=>t.kind!=='VERIFY').length),expected.remaining_tasks.length);
  await page.screenshot({path:path.join(out,'overview-1440.png'),fullPage:true});
  await page.locator('[data-action="material-files"]').first().click();await page.locator('#receivedFiles').waitFor();
  const bank=page.locator('#receivedFiles tr').filter({hasText:'2026.1月聚贤达农业银行流水.xls'});
  await bank.getByRole('button',{name:'查看原件',exact:true}).click();await page.locator('#dialog[open]').waitFor();
  await page.keyboard.press('Escape');await page.locator('[data-action="return-files"]').click();
  await page.reload();await page.locator('#materialWorkbench').waitFor();
  assert.deepEqual(await page.evaluate(()=>state.overview.material_review.counts),expected.after_counts);
  await page.setViewportSize({width:390,height:844});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.screenshot({path:path.join(out,'overview-390.png'),fullPage:true});
  assert.deepEqual(errors,[]);assert.deepEqual(blocked,[]);
  fs.writeFileSync(path.join(out,'report.json'),JSON.stringify({status:'PASS',counts:expected.after_counts,errors,blocked,
   flows:['overview refreshed','obsolete errors absent','original inspection','return and reload','mobile overflow'],business_writes:0},null,2));
  console.log('PASS refreshed overview, original inspection, return/reload; no business writes');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});

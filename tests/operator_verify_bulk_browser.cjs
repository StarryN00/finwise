// Cross-page verification writes only to a disposable authenticated fixture.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),net=require('node:net');
const {spawn}=require('node:child_process'),{chromium}=require('playwright');
const {guided}=require('./operator_guided_helpers_browser.cjs');
const ROOT=path.resolve(__dirname,'..'),OUT=path.join(ROOT,'output/playwright/verify-bulk');
const delay=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 const temp=fs.mkdtempSync(path.join(os.tmpdir(),'finwise-verify-bulk-'));fs.mkdirSync(OUT,{recursive:true});
 const socket=net.createServer();await new Promise(r=>socket.listen(0,'127.0.0.1',r));const port=socket.address().port;await new Promise(r=>socket.close(r));
 const server=spawn('python3',['tests/materials_fixture_server.py','--root',temp,'--port',String(port)],{cwd:ROOT,stdio:['ignore','pipe','pipe']});
 let logs='',browser,page;server.stderr.on('data',b=>logs+=b);const commands=[],errors=[],base=`http://127.0.0.1:${port}`;
 try{
  for(let i=0;i<150;i++){if(server.exitCode!==null)throw Error(logs);try{if((await fetch(base+'/api/v1/health')).ok)break;}catch{}await delay(100);}
  browser=await chromium.launch();page=await browser.newPage({viewport:{width:1440,height:900}});const g=guided(page);
  page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.url().endsWith('/api/v1/commands'))commands.push(r.postDataJSON());});
  await page.goto(base+'/static/operator.html');await page.locator('#username').fill('plan-author');await page.locator('#password').fill('IssuePlanTest!2026');await page.locator('#loginForm button').click();await page.locator('#currentTask').waitFor();
  await page.locator('[data-scope]').filter({hasText:'方案核对甲'}).click();await g.settle();await page.locator('[data-action="material-open-task"]').click();await page.locator('[data-screen="detail"]').waitFor();await page.locator('[data-action="material-return-list"]').click();
  await page.locator('[data-action="material-filter"][data-filter="results"]').first().click();await page.locator('tr').filter({hasText:'1月发票.xlsx'}).getByRole('button',{name:'查看提取值并核实'}).click();
  const disclosure=page.locator('.decision-evidence-disclosure');if(!await disclosure.count())await g.choose('verify_source_values');assert.equal(await disclosure.getAttribute('open'),null);assert.equal(await disclosure.locator(':scope > summary').getAttribute('aria-expanded'),'false');assert.equal(await page.locator('#materialWorkbench .primary:visible').count(),1);
  const question=await page.locator('[data-current-question]:visible').boundingBox();assert(question&&question.y<900,'current operation should be in the first viewport');assert.equal(await page.evaluate(()=>document.activeElement?.hasAttribute('data-current-question')),true);
  await disclosure.locator(':scope > summary').click();assert.equal(await disclosure.locator(':scope > summary').getAttribute('aria-expanded'),'true');assert.equal(await page.locator('.decision-key-table tbody tr:visible').count(),5);
  await page.locator('.decision-key-table [data-guide="record"]').first().click();assert.equal(await page.locator('.decision-source').getAttribute('open'),'');assert.match(await page.locator('.decision-source').innerText(),/I-0/);assert.equal(await page.locator('[data-material-record]:checked').count(),0);assert.equal(commands.length,0);
  await page.locator('[data-guide="select-all-records"]').click();assert.match(await page.locator('[data-selection-status]').innerText(),/7\/7/);assert.equal(await page.locator('[data-material-record]:checked').count(),5);
  await page.locator('.decision-evidence [data-action="material-page"]').last().click();await g.settle();assert.equal(await page.locator('[data-material-record]:checked').count(),2);assert.match(await page.locator('[data-selection-status]').innerText(),/7\/7/);
  await page.setViewportSize({width:390,height:844});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));assert.equal(await page.locator('#materialWorkbench .primary:visible').count(),1);await page.screenshot({path:path.join(OUT,'selected-mobile.png'),fullPage:true});
  await page.setViewportSize({width:1440,height:900});await g.next();await page.locator('#materialNote').fill('已逐条核对当前事项全部记录');await g.review();
  await page.route('**/api/v1/commands',route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:{message:'隔离测试保存失败'}})}),{times:1});
  await g.commit();assert.match(await page.locator('#notice').innerText(),/保存失败/);await g.edit(0);assert.match(await page.locator('[data-selection-status]').innerText(),/7\/7/);assert.equal(await page.locator('[data-material-record]:checked').count(),2);
  await g.review();await g.commit();assert.equal(await page.evaluate(()=>state.overview.material_review.counts.source_verified),7);
  assert.equal(commands.length,2);assert.equal(commands[0].action,'verify_source_values');assert.equal(commands[0].payload.records.length,7);assert.equal(commands[0].idempotency_key,commands[1].idempotency_key);assert(!JSON.stringify(commands).includes('[object PointerEvent]'));
  assert.deepEqual(errors,[]);fs.writeFileSync(path.join(OUT,'report.json'),JSON.stringify({status:'PASS',records:7,requests:commands.length,errors,temp},null,2));console.log('PASS cross-page select-all, collapse, retry and atomic submit');
 }catch(error){if(page)await page.screenshot({path:path.join(OUT,'failure.png'),fullPage:true});console.error(logs.slice(-2500));throw error;}finally{await browser?.close();server.kill('SIGTERM');}
})().catch(error=>{console.error(error);process.exitCode=1;});

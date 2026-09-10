// Writes are restricted to this newly created fixture; no retained service/model calls.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),net=require('node:net');
const {spawn}=require('node:child_process'),{chromium}=require('playwright');
const root=path.resolve(__dirname,'..'),out=path.join(root,'output/playwright/structure-plans');
(async()=>{
 fs.mkdirSync(out,{recursive:true});const temp=fs.mkdtempSync(path.join(os.tmpdir(),'finwise-plan-browser-'));
 const socket=net.createServer();await new Promise(r=>socket.listen(0,'127.0.0.1',r));const port=socket.address().port;await new Promise(r=>socket.close(r));
 const server=spawn('/usr/bin/python3',['tests/structure_plan_fixture_server.py','--root',temp,'--port',String(port)],{cwd:root,stdio:['ignore','pipe','pipe']});
 let logs='',browser,page;server.stderr.on('data',b=>logs+=b);const base=`http://127.0.0.1:${port}`,errors=[],posts=[],flows=[];
 const check=async(name,fn)=>{await fn();flows.push(name);console.log('PASS',name);};
 try{
  for(let i=0;i<150;i++){if(server.exitCode!==null)throw Error(logs);try{if((await fetch(base+'/api/v1/health')).ok)break;}catch{}await new Promise(r=>setTimeout(r,100));}
  browser=await chromium.launch();page=await browser.newPage({viewport:{width:1440,height:900}});page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>{if(r.method()==='POST'&&/\/(commands|agent\/suggestion)$/.test(r.url()))posts.push({url:r.url(),body:r.postDataJSON()});});
  const settle=()=>page.waitForFunction(()=>!state.busy&&!parsePlanUI.pending),click=async a=>{await page.locator(`[data-action="${a}"]`).first().click();await settle();};
  await page.goto(base+'/static/operator.html');await page.locator('#username').fill('plan-author');await page.locator('#password').fill('IssuePlanTest!2026');await page.locator('#loginForm button').click();await page.locator('#currentTask').waitFor();
  await page.locator('[data-scope]').filter({hasText:'方案核对甲'}).click();await page.waitForFunction(()=>!state.busy);
  await click('artifacts');await page.locator('tr').filter({hasText:'结构验收银行流水.xlsx'}).locator('[data-action="parse-plan-open"]').click();await settle();
  await check('source first; opening does not call model',async()=>{assert.match(await page.locator('#parsePlanWorkbench').innerText(),/记账日期|入账收入/);assert.equal(posts.filter(p=>p.body.stage==='STRUCTURE_PLAN').length,0);assert.equal(await page.locator('[data-action="parse-plan-apply"]').count(),0);});
  await check('explicit model suggestion then deterministic preview',async()=>{await click('parse-plan-identify');assert.equal(posts.filter(p=>p.body.stage==='STRUCTURE_PLAN').length,1);assert.equal(await page.locator('[data-pp="field"][data-field="income"]').inputValue(),'B');await click('parse-plan-preview');assert.match(await page.locator('.pp-preview').innerText(),/2 条候选记录/);assert.equal(await page.evaluate(()=>parsePlanUI.entry.plan.data.gateway.mock),true);});
  await check('impact requires explicit consent; field edit invalidates it',async()=>{await click('parse-plan-impact');assert(await page.locator('[data-action="parse-plan-apply"]').isDisabled());await page.locator('[data-pp="confirmed"]').check();assert(await page.locator('[data-action="parse-plan-apply"]').isEnabled());await page.locator('[data-pp="field"][data-field="income"]').selectOption('C');assert.equal(await page.locator('[data-pp="confirmed"]').count(),0);await click('parse-plan-preview');assert.match(await page.locator('#parsePlanWorkbench').innerText(),/同一原表列|同一列/);await page.locator('[data-pp="field"][data-field="income"]').selectOption('B');await click('parse-plan-preview');});
  await check('desktop and mobile source, fields and main action remain reachable',async()=>{for(const [width,height] of [[1440,900],[1040,900],[390,844]]){await page.setViewportSize({width,height});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.locator('[data-action="parse-plan-impact"]').scrollIntoViewIfNeeded();assert(await page.locator('[data-action="parse-plan-impact"]').isVisible());await page.screenshot({path:path.join(out,`structure-${width}.png`),fullPage:true});}await page.setViewportSize({width:1440,height:900});});
  await check('request failure preserves preview; explicit retry applies without financial approval',async()=>{
   await click('parse-plan-impact');await page.locator('[data-pp="confirmed"]').check();let failed=false;
   await page.route('**/api/v1/commands',async r=>{if(r.request().postDataJSON().action==='apply_parse_plan'&&!failed){failed=true;await r.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:{message:'隔离网络失败，请重试'}})});}else await r.continue();});
   await click('parse-plan-apply');assert.match(await page.locator('#parsePlanWorkbench').innerText(),/隔离网络失败/);assert.equal(await page.locator('[data-pp="field"][data-field="income"]').inputValue(),'B');await click('parse-plan-apply');
   assert.match(await page.locator('#parsePlanWorkbench').innerText(),/方案已应用/);assert.equal(await page.evaluate(()=>state.overview.material_review.counts.source_verified),0);assert.equal(await page.evaluate(()=>state.overview.material_review.counts.accounting_usable),0);await page.unroute('**/api/v1/commands');
  });
  await check('return and company switch keep scope isolated; no extra model calls',async()=>{await click('parse-plan-return');await page.locator('[data-scope]').filter({hasText:'方案核对乙'}).click();await page.waitForFunction(()=>!state.busy);assert.doesNotMatch(await page.locator('#workspace').innerText(),/结构验收银行流水/);assert.equal(posts.filter(p=>p.body.stage==='STRUCTURE_PLAN').length,1);});
  assert.deepEqual(errors,[]);fs.writeFileSync(path.join(out,'report.json'),JSON.stringify({status:'PASS',flows,errors,fixture:temp,real_model_calls:0},null,2));
 }catch(e){if(page)await page.screenshot({path:path.join(out,'failure.png'),fullPage:true});console.error(logs.slice(-2000));throw e;}finally{await browser?.close();server.kill('SIGTERM');}
})().catch(e=>{console.error(e);process.exitCode=1;});

const assert=require('node:assert/strict'),fs=require('fs'),path=require('path'),os=require('os'),net=require('net');
const {spawn}=require('child_process'),{chromium}=require('playwright');
const {guided}=require('./operator_guided_helpers_browser.cjs');
const ROOT=path.resolve(__dirname,'..'),OUT=path.join(ROOT,'output/playwright/invoice-review');
const delay=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 const temp=fs.mkdtempSync(path.join(os.tmpdir(),'finwise-invoice-review-'));fs.mkdirSync(OUT,{recursive:true});
 const socket=net.createServer();await new Promise(r=>socket.listen(0,'127.0.0.1',r));const port=socket.address().port;await new Promise(r=>socket.close(r));
 const server=spawn('/usr/bin/python3',['tests/invoice_review_fixture_server.py','--root',temp,'--port',String(port)],{cwd:ROOT,stdio:['ignore','pipe','pipe']});
 let browser,page,logs='';server.stderr.on('data',b=>logs+=b);const base=`http://127.0.0.1:${port}`,errors=[],commands=[],flows=[];
 const check=async(name,fn)=>{await fn();flows.push(name);console.log('PASS',name);};
 try{
  for(let i=0;i<150;i++){if(server.exitCode!==null)throw Error(logs);try{if((await fetch(base+'/api/v1/health')).ok)break;}catch{}await delay(100);}
  browser=await chromium.launch();page=await browser.newPage({viewport:{width:1440,height:900}});
  page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.url().endsWith('/commands'))commands.push(r.postDataJSON());});
  const g=guided(page),settle=g.settle,click=async a=>{if(a==='material-defer')return g.choose('defer_material_issue');if(a==='material-save-defer')return g.finish();if(a==='invoice-amount-resume')return g.resume();await page.locator(`[data-action="${a}"]`).first().click();await settle();};
  await page.goto(base+'/static/operator.html');await page.locator('#username').fill('plan-author');await page.locator('#password').fill('IssuePlanTest!2026');await page.locator('#loginForm button').click();await page.locator('#currentTask').waitFor();
  await page.locator('[data-scope]').filter({hasText:'方案核对甲'}).click();await settle();
  await click('material-open-task');await click('material-return-list');
  await check('source-declared red invoice is system-checked, not a manual task; refresh preserves it',async()=>{
   const inspect=()=>page.evaluate(()=>{
    const m=state.overview.material_review,r=m.records.find(r=>r.values.invoice_no==='26322000000625714621');
    return {check:r.automatic_invoice_check?.status,state:r.state,tasks:m.tasks.filter(t=>t.record_ids.includes(r.object_id)).length,
     verified:m.counts.source_verified,confirmed:m.counts.invoice_amount_confirmed,usable:m.counts.accounting_usable};
   });
   assert.deepEqual(await inspect(),{check:'PASS',state:'AWAITING_VERIFICATION',tasks:0,verified:0,confirmed:0,usable:0});
   await page.reload();await page.locator('.mat-issue-group').first().waitFor();await settle();
   assert.equal((await inspect()).tasks,0);assert.equal(commands.length,0);
  });
  const open=()=>page.locator('.mat-issue-group').filter({hasText:'发票金额待核对'}).getByRole('button',{name:/进入处理|查看状态/}).click();
  await open();
  await check('one invoice per item; original amounts visible and reason required',async()=>{
   assert.match(await page.locator('.mat-detail-context').innerText(),/本组共 3 项/);
   assert.notEqual(await page.locator('.decision-source').getAttribute('open'),null);assert.equal(await page.locator('.mat-record:visible').count(),1);assert.match(await page.locator('.mat-record:visible').innerText(),/-113.00/);assert.equal(await page.locator('.decision-summary').count(),0);
   await g.choose('confirm_invoice_amount');
   await g.next();assert.equal(commands.filter(c=>c.action==='confirm_invoice_amount').length,0);
   await page.locator('#materialNote').fill('已核对退货冲红，保留原始负数。');
   for(const width of [1440,1040,390]){await page.setViewportSize({width,height:900});await page.locator('#invoiceAmountForm').scrollIntoViewIfNeeded();assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.screenshot({path:path.join(OUT,`invoice-${width}.png`),fullPage:true});}
   await page.setViewportSize({width:1440,height:900});await g.sourceDialog();
   await page.reload();await page.locator('#invoiceAmountForm').waitFor();assert.equal(await page.locator('#materialNote').inputValue(),'已核对退货冲红，保留原始负数。');
  });
  await check('failed save keeps draft; no attachment save advances one invoice',async()=>{
   await page.route('**/api/v1/commands',r=>r.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:{message:'模拟失败，请重试'}})}));
   await page.locator('#materialNote').press('Enter');assert.equal(commands.length,0);await g.review();assert.match(await page.locator('.decision-summary').innerText(),/确认执行内容/);assert.equal(commands.length,0);
   await g.commit();assert.match(await page.locator('#notice').innerText(),/模拟失败/);assert.match(await page.locator('#materialNote').inputValue(),/退货冲红/);
   await page.unroute('**/api/v1/commands');await g.commit();assert.match(await page.locator('.decision-key-table').innerText(),/ZERO-1/);
   assert.equal(await page.evaluate(()=>state.overview.material_review.counts.invoice_amount_confirmed),1);
   assert.equal(await page.evaluate(()=>state.overview.material_review.counts.source_verified),0);
  });
  await check('zero amount confirmation; defer and group summary keep distinct outcomes',async()=>{
   await g.choose('confirm_invoice_amount');await page.locator('#materialNote').fill('原始零金额已核对，业务原因已确认。');await g.finish();
   assert.match(await page.locator('.decision-key-table').innerText(),/RED-OLD/);await click('material-defer');await page.locator('#materialReason').fill('等待客户确认');await click('material-save-defer');
   assert.match(await page.locator('.mat-group-totals').innerText(),/金额核对已处理/);assert.match(await page.locator('.mat-group-totals').innerText(),/等待外部资料或条件/);
  });
  await check('results restore after refresh; revoke restores only its warning',async()=>{
   await click('material-return-list');await page.locator('[data-filter="results"]').first().click();assert.equal(await page.locator('[data-action="invoice-amount-revoke"]').count(),2);
   assert.match(await page.locator('#materialWorkbench').innerText(),/核对人 plan-author/);await page.reload();await page.locator('[data-action="invoice-amount-revoke"]').first().waitFor();await click('invoice-amount-revoke');
   assert.equal(await page.evaluate(()=>state.overview.material_review.counts.invoice_amount_confirmed),1);
  });
  await check('deferred invoice waits externally and its separate period problem remains',async()=>{
   await page.locator('[data-filter="all"]').first().click();await page.locator('[data-filter="deferred"]').click();await open();
   assert.match(await page.locator('.decision-waiting').innerText(),/你当前无需操作/);assert.equal(await page.locator('#invoiceAmountForm').count(),0);
   assert.equal(await page.evaluate(()=>state.overview.material_review.flow.counts.waiting_external),1);
   assert.equal(await page.evaluate(()=>state.overview.material_review.records.find(r=>r.values.invoice_no==='RED-OLD').state),'PERIOD_EXCEPTION');
   assert.equal(await page.evaluate(()=>state.overview.material_review.counts.accounting_usable),0);
  });
  assert.deepEqual(errors,[]);assert(commands.every(c=>['confirm_invoice_amount','revoke_invoice_amount','defer_material_issue'].includes(c.action)));
  fs.writeFileSync(path.join(OUT,'report.json'),JSON.stringify({status:'PASS',flows,errors,commands:commands.map(c=>c.action),fixture:temp},null,2));
 }catch(e){if(page)await page.screenshot({path:path.join(OUT,'failure.png'),fullPage:true});throw e;}finally{if(browser)await browser.close();server.kill('SIGTERM');}
})().catch(e=>{console.error(e);process.exitCode=1;});

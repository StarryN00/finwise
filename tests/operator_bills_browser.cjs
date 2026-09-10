// Real click/form/request regression against disposable synthetic data only.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),net=require('node:net');
const {spawn}=require('node:child_process'),{chromium}=require('playwright');
const {guided}=require('./operator_guided_helpers_browser.cjs');
const ROOT=path.resolve(__dirname,'..'),OUT=path.join(ROOT,'output/playwright/bills');
const delay=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 const temp=fs.mkdtempSync(path.join(os.tmpdir(),'finwise-bills-'));fs.mkdirSync(OUT,{recursive:true});
 const socket=net.createServer();await new Promise(r=>socket.listen(0,'127.0.0.1',r));const port=socket.address().port;await new Promise(r=>socket.close(r));
 const server=spawn('python3',['tests/bills_fixture_server.py','--root',temp,'--port',String(port)],{cwd:ROOT,stdio:['ignore','pipe','pipe']});
 let logs='',browser,page;server.stderr.on('data',b=>logs+=b);const base=`http://127.0.0.1:${port}`,flows=[],errors=[],commands=[];
 const check=async(name,fn)=>{await fn();flows.push(name);console.log('PASS',name);};
 try{
  for(let i=0;i<150;i++){if(server.exitCode!==null)throw Error(logs);try{if((await fetch(base+'/api/v1/health')).ok)break;}catch{}await delay(100);}
  browser=await chromium.launch();page=await browser.newPage({viewport:{width:1440,height:900}});
  page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.url().endsWith('/commands'))commands.push(r.postDataJSON());});
  const g=guided(page),settle=g.settle,click=async action=>{if(action==='material-defer')return g.choose('defer_material_issue');if(action==='material-save-defer')return g.finish();if(action==='bill-resume')return g.resume();await page.locator(`[data-action="${action}"]`).first().click();await settle();};
  await page.goto(base+'/static/operator.html');await page.locator('#username').fill('plan-author');await page.locator('#password').fill('IssuePlanTest!2026');await page.locator('#loginForm button').click();await page.locator('#currentTask').waitFor();
  await page.locator('[data-scope]').filter({hasText:'方案核对甲'}).click();await settle();await click('issues');
  await page.locator('.mat-issue-group').filter({hasText:'确认票据业务与科目'}).getByRole('button',{name:'进入处理'}).click();
  const fill=async(kind='RECEIVED',candidate=false)=>{
   await g.choose('confirm_bill_business');assert(await page.locator('#billKind').isVisible());assert(!await page.locator('#billPeriod').isVisible());
   await page.locator('#billKind').selectOption(kind);await g.next();assert(await page.locator('#billPeriod').isVisible());assert(!await page.locator('#billAccountName').isVisible());
   await page.locator('#billPeriod').fill('2026-01');if(kind==='HELD')await page.locator('#billOriginalPeriod').fill('2025-12');await g.next();
   assert(await page.locator('#billAccount').isVisible());assert(!await page.locator('#billReason').isVisible());
   await page.locator('#billSearch').fill('100');assert(await page.locator('#billAccount option').count()>=1);await page.locator('#billSearch').fill('');
   if(candidate){const option=await page.locator('#billAccount option').nth(1).getAttribute('value');await page.locator('#billAccount').selectOption(option);assert.equal(await page.locator('#billAccountName').count(),0);}
   else await page.locator('#billAccountName').fill('应收票据');
   const before=commands.length;await page.locator(candidate?'#billAccount':'#billAccountName').press('Enter');await settle();assert.equal(commands.length,before);
   if(candidate){assert(await page.locator('#billAccount').isVisible());assert(!await page.locator('#billReason').isVisible());await g.next();}
   assert(await page.locator('#billReason').isVisible());await g.focus();
   await page.locator('#billReason').fill('已向客户核实，本期货款票据；科目待核对。');
  };
  await check('independent bill form has no preconfirmed period or account and preserves source',async()=>{
   assert.equal(await page.locator('#billPeriod').inputValue(),'');assert.equal(await page.locator('#billAccountName').inputValue(),'');
   assert.match(await page.locator('.mat-detail-context').innerText(),/本组共 3 项/);
   assert.notEqual(await page.locator('.decision-source').getAttribute('open'),null);assert(await page.locator('.mat-comparison:visible').isVisible());assert.match(await page.locator('.mat-comparison:visible').innerText(),/未提供/);assert.equal(await page.locator('.decision-summary').count(),0);
   await g.sourceDialog();await g.closeSource();
  });
  await fill();
  await check('draft survives refresh and source navigation; responsive form remains reachable',async()=>{
   await page.reload();await page.locator('#billForm').waitFor();assert.match(await page.locator('#billReason').inputValue(),/已向客户核实/);
   await g.sourceDialog();assert.match(await page.locator('#billReason').inputValue(),/已向客户核实/);await g.closeSource();
   for(const [width,height] of [[1440,900],[1040,900],[390,844]]){await page.setViewportSize({width,height});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.locator('#billForm .primary').scrollIntoViewIfNeeded();assert(await page.locator('#billForm .primary').isVisible());await page.screenshot({path:path.join(OUT,`bill-${width}.png`),fullPage:true});}
   await page.setViewportSize({width:1440,height:900});
  });
  await check('failed confirmation retains text; save without attachment advances exactly one bill',async()=>{
   await page.route('**/api/v1/commands',r=>r.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:{message:'测试保存失败'}})}),{times:1});
   const before=commands.length;await g.review();assert.match(await page.locator('.decision-summary').innerText(),/确认提交摘要/);assert.equal(commands.length,before);assert.match(await page.locator('.decision-answer').allTextContents().then(x=>x.join(' ')),/应收票据/);
   await g.commit();assert.match(await page.locator('#notice').innerText(),/测试保存失败/);assert.match(await page.locator('#billReason').inputValue(),/已向客户核实/);
   await g.commit();assert.match(await page.locator('.focus-head').innerText(),/3,4/);
   const result=await page.evaluate(()=>state.overview);assert.equal(result.bill_review.confirmed_count,1);assert.equal(result.material_review.counts.source_verified,0);assert.equal(result.material_review.counts.accounting_usable,0);
   assert.equal(result.bill_review.confirmations[0].data.account_status,'PROPOSED');
  });
  await check('history holding can select enterprise candidate and uses month precision',async()=>{
   await fill('HELD',true);await g.finish();assert.match(await page.locator('.focus-head').innerText(),/5,6/);
   const c=await page.evaluate(()=>state.overview.bill_review.confirmations.find(c=>c.data.business_kind==='HELD'));
   assert.equal(c.data.current_receipt,false);assert.equal(c.data.date_precision,'MONTH');assert.equal(c.data.account_status,'HISTORICAL');
  });
  await check('defer ends group with separate human and pending totals',async()=>{
   await click('material-defer');await page.locator('#materialReason').fill('尚未联系到经办人');await click('material-save-defer');
   assert.equal(await page.locator('#materialWorkbench').getAttribute('data-screen'),'summary');
   assert.match(await page.locator('.mat-group-totals').innerText(),/人工补充确认/);assert.match(await page.locator('.mat-group-totals').innerText(),/已记录待补/);
   await page.screenshot({path:path.join(OUT,'bill-results.png'),fullPage:true});
  });
  await check('results keep person/reason/source and revocation restores a targeted bill task',async()=>{
   await click('material-return-list');await page.locator('[data-action="material-filter"][data-filter="results"]').first().click();
   assert.equal(await page.locator('.bill-confirmation').count(),2);assert.match(await page.locator('.bill-confirmation').first().innerText(),/确认人/);
   await click('bill-revoke');assert.match(await page.locator('#notice').innerText(),/已撤销/);
   assert.equal(await page.evaluate(()=>state.overview.bill_review.confirmed_count),1);assert.equal(await page.evaluate(()=>state.overview.material_review.tasks.filter(t=>t.kind==='BILL'&&!t.deferred).length),1);
  });
  await check('deferred bill resumes without attachment, OTHER keeps a actionable recorded opinion',async()=>{
   await page.locator('[data-action="material-filter"][data-filter="all"]').first().click();await page.locator('[data-action="material-filter"][data-filter="deferred"]').click();
   await page.locator('.mat-issue-group').filter({hasText:'确认票据业务与科目'}).getByRole('button',{name:'查看处理记录'}).click();
   await click('bill-resume');await fill('OTHER');await g.finish();
   assert.match(await page.locator('.mat-group-totals').innerText(),/意见已记录/);
   await click('material-return-list');await page.locator('.mat-issue-group').filter({hasText:'确认票据业务与科目'}).getByRole('button',{name:'查看处理记录'}).click();
   await click('bill-resume');assert.match(await page.locator('#materialTaskTitle').innerText(),/业务归属仍待确认/);
   await g.source();await click('bill-revoke');await click('material-return-list');await page.locator('.mat-issue-group').filter({hasText:'确认票据业务与科目'}).getByRole('button',{name:'查看处理记录'}).click();
   if(await page.locator('[data-guide="resume"]').count())await click('bill-resume');await fill();await g.finish();
   assert.equal(await page.evaluate(()=>state.overview.material_review.counts.deferred),0);
  });
  assert.equal(commands.filter(c=>/mapping|agent|model/.test(c.action)).length,0);assert.deepEqual(errors,[]);
  fs.writeFileSync(path.join(OUT,'report.json'),JSON.stringify({status:'PASS',flows,errors,commands:commands.map(c=>c.action),fixture:temp},null,2));
 }catch(error){if(page)await page.screenshot({path:path.join(OUT,'failure.png'),fullPage:true});throw error;}finally{if(browser)await browser.close();server.kill('SIGTERM');}
})().catch(error=>{console.error(error);process.exitCode=1;});

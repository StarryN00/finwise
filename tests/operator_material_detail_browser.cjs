// All writes use a new disposable database; the retained Staging is never a target.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),net=require('node:net');
const {spawn}=require('node:child_process'),{chromium}=require('playwright');
const {guided}=require('./operator_guided_helpers_browser.cjs');
const ROOT=path.resolve(__dirname,'..'),OUT=path.join(ROOT,'output/playwright/material-detail');
const delay=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 const temp=fs.mkdtempSync(path.join(os.tmpdir(),'finwise-material-detail-'));fs.mkdirSync(OUT,{recursive:true});
 const socket=net.createServer();await new Promise(r=>socket.listen(0,'127.0.0.1',r));const port=socket.address().port;await new Promise(r=>socket.close(r));
 const server=spawn('python3',['tests/material_detail_fixture_server.py','--root',temp,'--port',String(port)],{cwd:ROOT,stdio:['ignore','pipe','pipe']});
 let logs='',browser;server.stderr.on('data',b=>logs+=b);const base=`http://127.0.0.1:${port}`,flows=[],errors=[],commands=[],modelRequests=[];
 const check=async(name,fn)=>{await fn();flows.push(name);console.log('PASS',name);};
 try{
  for(let i=0;i<150;i++){if(server.exitCode!==null)throw Error(logs);try{if((await fetch(base+'/api/v1/health')).ok)break;}catch{}await delay(100);}
  browser=await chromium.launch();const page=await browser.newPage({viewport:{width:1440,height:900}});
  page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.url().endsWith('/commands')){const c=r.postDataJSON();commands.push(c);if(/mapping|agent|model/.test(c.action))modelRequests.push(c);}});
  const g=guided(page),settle=g.settle,click=async action=>{if(action==='material-defer')return g.choose('defer_material_issue');if(['material-save-defer','material-verify'].includes(action))return g.finish();if(action==='material-cancel-defer')return g.choose('supplement');if(action==='material-supplement'){await g.choose('supplement');await page.locator('[data-guide="open"]').click();return settle();}await page.locator(`[data-action="${action}"]`).first().click();await settle();};
  const counts=()=>page.evaluate(()=>state.overview.material_review.counts);
  await page.goto(base+'/static/operator.html');await page.locator('#username').fill('plan-author');await page.locator('#password').fill('IssuePlanTest!2026');await page.locator('#loginForm button').click();await page.locator('#currentTask').waitFor();
  await page.locator('[data-scope]').filter({hasText:'方案核对甲'}).click();await settle();await click('issues');
  const taxGroup=()=>page.locator('.mat-issue-group').filter({hasText:'3 项待办'}).first();
  await check('overview contains only group list; click opens full detail at top',async()=>{
   assert.equal(await page.locator('.mat-task').count(),0);await taxGroup().getByRole('button',{name:'进入处理'}).click();
   assert.equal(await page.locator('#materialWorkbench').getAttribute('data-screen'),'detail');assert.equal(await page.locator('.mat-overview,.mat-issue-groups').count(),0);
   assert.match(await page.locator('.mat-detail-context').innerText(),/本组共 3 项，涉及 3 份原件/);assert.equal(await page.evaluate(()=>window.scrollY),0);
   assert.equal(await page.locator('#materialWorkbench .primary:visible').count(),1);assert.equal(await page.locator('.decision-summary').count(),0);assert.notEqual(await page.locator('.decision-source').getAttribute('open'),null);assert(await page.locator('.decision-key-table').isVisible());
  });
  await check('back/forward restore list position and selected group',async()=>{
   const selected=await page.evaluate(()=>materialUI.selected);await page.goBack();await page.locator('.mat-issue-groups').waitFor();
   assert.equal(await page.locator('.mat-task').count(),0);await page.goForward();await page.locator('.mat-task').waitFor();assert.equal(await page.evaluate(()=>materialUI.selected),selected);
  });
  await check('desktop, narrow desktop and mobile have one reachable action and no overflow',async()=>{
   for(const [width,height] of [[1440,900],[1040,900],[390,844]]){
    await page.setViewportSize({width,height});await page.evaluate(()=>scrollTo(0,0));assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await page.screenshot({path:path.join(OUT,`detail-${width}.png`),fullPage:true});
    const action=page.locator('#materialWorkbench .primary');await action.scrollIntoViewIfNeeded();assert(await action.isVisible());
   }
   await page.setViewportSize({width:1440,height:900});
  });
  await check('source dialog and list return preserve the draft; failed write keeps input',async()=>{
   await click('material-defer');await page.locator('#materialReason').fill('等待客户补齐税率依据');
   await g.sourceDialog();
   assert.equal(await page.locator('#materialReason').inputValue(),'等待客户补齐税率依据');
   await page.reload();await page.locator('#materialReason').waitFor();assert.equal(await page.locator('#materialReason').inputValue(),'等待客户补齐税率依据');
   await click('material-return-list');await taxGroup().getByRole('button',{name:'进入处理'}).click();assert.equal(await page.locator('#materialReason').inputValue(),'等待客户补齐税率依据');
   await page.route('**/api/v1/commands',route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:{message:'测试保存失败'}})}),{times:1});
   await click('material-save-defer');assert.equal(await page.locator('#materialReason').inputValue(),'等待客户补齐税率依据');assert.match(await page.locator('#notice').innerText(),/测试保存失败/);
  });
  await check('supplement upload keeps the original issue open without counting it as verified',async()=>{
   await click('material-cancel-defer');const before=await counts(),task=await page.evaluate(()=>materialUI.selected);
   await click('material-supplement');await page.locator('#uploadFile').setInputFiles(path.join(temp,'supplement.xlsx'));
   await page.locator('#uploadForm button[type="submit"]').click();await settle();
   // Existing Agent-first upload flow offers structure review, without applying it.
   if(await page.locator('#parsePlanWorkbench').count()){assert.equal(await page.locator('[data-action="parse-plan-apply"]').count(),0);await page.locator('[data-action="parse-plan-return"]').first().click();await settle();}
   assert.equal((await counts()).files,before.files+1);assert.equal((await counts()).source_verified,before.source_verified);
   assert.equal(await page.evaluate(()=>materialUI.selected),task);assert.equal(await page.locator('#materialWorkbench').getAttribute('data-screen'),'detail');
   assert.match(await page.locator('.mat-inline-feedback').innerText(),/原事项仍需核对/);
   await click('material-defer');assert.equal(await page.locator('#materialReason').inputValue(),'等待客户补齐税率依据');
  });
  await check('save targets one task, moves within group, and stops at group summary',async()=>{
   const before=await counts();await click('material-save-defer');assert.equal((await counts()).deferred,before.deferred+1);assert.equal((await counts()).needs_review,before.needs_review);
   assert.match(await page.locator('.mat-detail-context').innerText(),/本组第 2 项/);assert.match(await page.locator('.mat-inline-feedback').innerText(),/仍待补充/);
   await click('material-skip');assert.match(await page.locator('.mat-detail-context').innerText(),/本组第 3 项/);await click('material-skip');
   assert.equal(await page.locator('#materialWorkbench').getAttribute('data-screen'),'summary');assert.match(await page.locator('.mat-group-totals').innerText(),/已记录待补/);assert.match(await page.locator('.mat-group-totals').innerText(),/暂未处理/);
   assert.equal((await counts()).source_verified,0);assert.equal((await counts()).accounting_usable,0);await page.screenshot({path:path.join(OUT,'group-summary-1440.png'),fullPage:true});
   await page.reload();await page.locator('[data-screen="summary"]').waitFor();await click('material-next-group');assert.equal(await page.locator('#materialWorkbench').getAttribute('data-screen'),'detail');
  });
  await check('return and results open verification details; partial confirmation keeps the same original',async()=>{
   await click('material-return-list');await page.getByRole('button',{name:'已有成果',exact:true}).click();
   await page.locator('tr').filter({hasText:'1月发票.xlsx'}).getByRole('button',{name:'查看提取值并核实'}).click();
   assert.equal(await page.locator('.mat-overview').count(),0);assert.equal(await page.locator('[data-material-record]:visible').count(),5);
   // Synthetic read-only UI state in the disposable fixture; no permissions are changed server-side.
   await page.evaluate(()=>{window.savedMaterialCanWrite=materialCanWrite;materialCanWrite=()=>false;render();});
   await g.source();assert.equal(await page.locator('.decision-source .mat-record [data-object]').first().isEnabled(),true);
   await g.sourceDialog();
   await page.locator('[data-guide="record"]').nth(1).click();assert.equal(await page.locator('.decision-source [data-object]').first().isEnabled(),true);assert.equal(await page.locator('[data-guide="record"]').nth(1).getAttribute('aria-pressed'),'true');
   await page.evaluate(()=>{materialCanWrite=window.savedMaterialCanWrite;materialState().page=0;render();});
   await page.locator('[data-material-record]:visible').first().check();
   const commandCount=commands.length;await g.sourceDialog();assert.equal(commands.length,commandCount);assert.equal(await page.locator('[data-material-record]:visible').first().isChecked(),true);
   await g.next();await page.locator('#materialNote').fill('核对当前页第一条');
   await click('material-verify');assert.equal((await counts()).source_verified,1);assert.equal(await page.locator('#materialWorkbench').getAttribute('data-screen'),'detail');
   assert.match(await page.locator('.mat-task').innerText(),/1月发票.xlsx/);assert.equal(await page.locator('#materialNote').inputValue(),'');
   for(let i=0;i<3&&await page.locator('[data-material-record]:visible').count();i++){for(const c of await page.locator('[data-material-record]:visible').all())await c.check();await click('material-verify');}
   assert.equal((await counts()).source_verified,7);assert.equal(await page.locator('#materialWorkbench').getAttribute('data-screen'),'summary');assert.match(await page.locator('.mat-group-totals').innerText(),/资料已核实/);
  });
  await check('verified records and revoke remain accessible from results',async()=>{
   await click('material-return-list');await page.getByRole('button',{name:'已有成果',exact:true}).click();await page.getByRole('button',{name:'查看核实记录',exact:true}).click();
   await click('material-revoke');assert.equal((await counts()).source_verified,6);assert.equal((await counts()).accounting_usable,0);
   await page.goBack();await page.locator('.mat-result-summary').waitFor();assert.equal(await page.evaluate(()=>materialUI.filter),'results');
  });
  await check('bank affiliation opens in detail and confirmation ends with explicit group results',async()=>{
   await click('accounts-open');await page.locator('[data-action="accounts-statement"]').first().click();await page.locator('#bankAccountForm').waitFor();
   assert.equal(await page.locator('.mat-overview').count(),0);await g.next();await page.locator('[name="confirmed"]').check();await g.finish();
   assert.equal(await page.evaluate(()=>state.overview.bank_accounts.statements[0].status),'LINKED');
   assert.equal(await page.evaluate(()=>state.overview.baseline.status),'DRAFT');
   assert.match(await page.locator('#materialWorkbench').innerText(),/其他资料问题仍保留|银行归属已确认/);
  });
  await check('file mode is a list and selects only that original; company changes clear draft',async()=>{
   if(await page.locator('[data-action="material-return-list"]').count())await click('material-return-list');
   await page.locator('[data-action="material-filter"][data-filter="all"]').first().click();await page.locator('[data-mode="files"]').click();
   assert.equal(await page.locator('.mat-task').count(),0);await page.locator('[data-action="material-select-file"]').first().click();
   assert.equal(await page.evaluate(()=>new Set(materialUI.group.entries.map(e=>e.artifact_id)).size),1);
   await click('material-defer');await page.locator('#materialReason').fill('仅属于甲企业的草稿');
   await page.locator('[data-scope]').filter({hasText:'方案核对乙'}).click();await settle();assert.doesNotMatch(await page.locator('#workspace').innerText(),/仅属于甲企业的草稿/);
   await page.goBack();assert.doesNotMatch(await page.locator('#workspace').innerText(),/仅属于甲企业的草稿|1月发票补充/);
  });
  assert.deepEqual(errors,[]);assert.deepEqual(modelRequests,[]);
  const report={status:'PASS',flows,errors,modelRequests,commands:commands.map(c=>c.action),fixture:temp,viewports:[1440,1040,390]};
  fs.writeFileSync(path.join(OUT,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
 }catch(error){if(browser){const pages=browser.contexts().flatMap(c=>c.pages());if(pages[0]){await pages[0].screenshot({path:path.join(OUT,'failure.png'),fullPage:true});console.error((await pages[0].locator('body').innerText()).slice(-4500));}}throw error;}
 finally{if(browser)await browser.close();server.kill('SIGTERM');}
})().catch(error=>{console.error(error);process.exitCode=1;});

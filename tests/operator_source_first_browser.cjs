// Real UI flows against disposable fixtures. No staging or model writes.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),net=require('node:net');
const {spawn}=require('node:child_process'),{chromium}=require('playwright');
const {guided}=require('./operator_guided_helpers_browser.cjs');
const root=path.resolve(__dirname,'..'),out=path.join(root,'output/playwright/source-first');
(async()=>{
 const temp=fs.mkdtempSync(path.join(os.tmpdir(),'finwise-source-first-'));fs.mkdirSync(out,{recursive:true});
 const socket=net.createServer();await new Promise(r=>socket.listen(0,'127.0.0.1',r));const port=socket.address().port;await new Promise(r=>socket.close(r));
 const server=spawn('/usr/bin/python3',['tests/source_first_fixture_server.py','--root',temp,'--port',String(port)],{cwd:root,stdio:['ignore','pipe','pipe']});
 const base=`http://127.0.0.1:${port}`,commands=[],models=[],errors=[],flows=[];let logs='',browser,page;
 server.stderr.on('data',b=>logs+=b);
 try{
  for(let i=0;i<150;i++){if(server.exitCode!==null)throw Error(logs);try{if((await fetch(base+'/api/v1/health')).ok)break;}catch{}await new Promise(r=>setTimeout(r,100));}
  browser=await chromium.launch();page=await browser.newPage({viewport:{width:1440,height:900}});const g=guided(page);
  page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.url().endsWith('/commands'))commands.push(r.postDataJSON());if(r.url().includes('/agent/'))models.push(r.url());});
  await page.goto(base+'/static/operator.html');await page.locator('#username').fill('plan-author');await page.locator('#password').fill('IssuePlanTest!2026');await page.locator('#loginForm button').click();await page.locator('#currentTask').waitFor();
  await page.locator('[data-scope]').filter({hasText:'方案核对甲'}).click();await g.settle();await page.locator('[data-action="issues"]').click();await g.settle();
  await page.locator('.mat-issue-group').filter({hasText:'发票状态'}).getByRole('button',{name:/进入处理/}).click();
  assert.match(await page.locator('#materialTaskTitle').innerText(),/发票状态/);assert.match(await page.locator('.decision-explanation').innerText(),/已红冲-全额/);
  assert.match(await page.locator('.decision-key-table').innerText(),/STATUS-1|STATUS-2/);assert.equal(await page.locator('.decision-key-table tbody tr').count(),5);
  assert.equal(await page.locator('.decision-summary').count(),0);assert.equal(await page.locator('#materialWorkbench h2,#materialWorkbench h3').count(),1);
  assert(await page.locator('.decision-source').getAttribute('open')!==null);assert.match(await page.locator('.decision-source .mat-record:visible').innerText(),/发票基础信息/);
  flows.push('type, quoted original value, filename and row visible before actions; no summary');
  const counts=await page.evaluate(()=>state.overview.material_review.counts);
  await page.locator('[data-guide="record"]').nth(1).press('Enter');const record=await page.locator('[data-guide="record"][aria-pressed="true"]').getAttribute('data-record');
  await g.sourceDialog();assert.equal(await page.locator('[data-guide="record"][aria-pressed="true"]').getAttribute('data-record'),record);
  await page.reload();await page.locator('.decision-key-table').waitFor();assert.equal(await page.locator('[data-guide="record"][aria-pressed="true"]').getAttribute('data-record'),record);
  await page.locator('.decision-evidence [data-action="material-page"]').last().click();await g.settle();assert.equal(await page.locator('.decision-key-table tbody tr').count(),2);
  await page.locator('.decision-evidence [data-action="material-page"]').first().click();await g.settle();assert.deepEqual(await page.evaluate(()=>state.overview.material_review.counts),counts);assert.equal(commands.length,0);
  flows.push('keyboard record selection, source return, refresh and five-row pagination are read-only');
  for(const [width,height] of [[1440,900],[1040,900],[390,844]]){
   await page.setViewportSize({width,height});await page.evaluate(()=>scrollTo(0,0));assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
   assert((await page.locator('.decision-key-table').boundingBox()).y<height);await page.screenshot({path:path.join(out,`detail-${width}.png`),fullPage:true});
  }
  await page.setViewportSize({width:1440,height:900});await page.locator('[data-guide="open"]').click();await page.locator('#uploadForm').waitFor();assert.equal(commands.length,0);await page.keyboard.press('Escape');
  flows.push('supplement opens existing upload dialog without writing');
  await g.choose('defer_material_issue');await page.locator('#materialReason').fill('等待确认业务处理依据');await g.review();assert.equal(commands.length,0);
  await page.route('**/api/v1/commands',r=>r.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:{message:'隔离测试保存失败'}})}),{times:1});
  await g.commit();assert.match(await page.locator('#notice').innerText(),/保存失败/);assert.equal(await page.locator('#materialReason').inputValue(),'等待确认业务处理依据');
  await g.commit();assert.equal(await page.locator('#materialWorkbench').getAttribute('data-screen'),'summary');
  assert.equal(await page.evaluate(()=>state.overview.material_review.counts.source_verified),counts.source_verified);
  assert.equal(await page.evaluate(()=>state.overview.material_review.counts.needs_review),counts.needs_review);
  assert.equal(await page.evaluate(()=>state.overview.material_review.counts.deferred),counts.deferred+1);
  flows.push('explicit defer commit, failed request retains draft, summary does not claim resolution');
  assert(commands.every(c=>c.action==='defer_material_issue'));assert.deepEqual(models,[]);assert.deepEqual(errors,[]);
  fs.writeFileSync(path.join(out,'report.json'),JSON.stringify({status:'PASS',flows,errors,models,commands:commands.map(c=>c.action),fixture:temp},null,2));console.log('PASS',flows);
 }catch(e){if(page)await page.screenshot({path:path.join(out,'failure.png'),fullPage:true});throw e;}finally{if(browser)await browser.close();server.kill('SIGTERM');}
})().catch(e=>{console.error(e);process.exitCode=1;});

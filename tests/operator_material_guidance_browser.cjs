// Browser contract test: synthetic local database; every guidance response is HTTP-mocked.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),net=require('node:net');
const {spawn}=require('node:child_process'),{chromium}=require('playwright');
const {guided}=require('./operator_guided_helpers_browser.cjs');
const ROOT=path.resolve(__dirname,'..'),OUT=path.join(ROOT,'output/playwright/material-guidance');
const delay=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 const temp=fs.mkdtempSync(path.join(os.tmpdir(),'finwise-guidance-browser-'));fs.mkdirSync(OUT,{recursive:true});
 const socket=net.createServer();await new Promise(r=>socket.listen(0,'127.0.0.1',r));const port=socket.address().port;await new Promise(r=>socket.close(r));
 const server=spawn('/usr/bin/python3',['tests/invoice_review_fixture_server.py','--root',temp,'--port',String(port)],{cwd:ROOT,stdio:['ignore','pipe','pipe']});
 let browser,page,logs='',nextResponse,releaseDelayed;const base=`http://127.0.0.1:${port}`,errors=[],commands=[],requests=[],flows=[],outside=[];
 server.stderr.on('data',b=>logs+=b);server.stdout.on('data',b=>logs+=b);
 const check=async(name,fn)=>{await fn();flows.push(name);console.log('PASS',name);};
 const proposed=(hash,overrides={})=>({status:'PROPOSED',suggestion:{option_id:'defer_material_issue',reason:'MOCK建议：补充核对后再决定。',uncertainties:['MOCK不确定：客户尚未确认。'],prefill:{},confidence:0.72},metadata:{mock:true,model_version:'browser-contract-fixture'},descriptor_hash:hash,...overrides});
 try{
  let healthy=false;for(let i=0;i<150;i++){if(server.exitCode!==null)throw Error(logs);try{if((await fetch(base+'/api/v1/health')).ok){healthy=true;break;}}catch{}await delay(100);}assert(healthy,'Temporary fixture did not start');
  browser=await chromium.launch();const context=await browser.newContext({viewport:{width:1440,height:900}});page=await context.newPage();
  await context.route('**/*',async route=>{
   const r=route.request();if(!r.url().startsWith(base+'/')){outside.push(r.url());return route.abort();}
   if(!r.url().endsWith('/api/v1/agent/suggestion'))return route.continue();
   const body=r.postDataJSON();requests.push(body);assert.equal(r.method(),'POST');assert(nextResponse,'Unsolicited Agent request');
   const respond=nextResponse;nextResponse=null;await respond(route,body);
  });
  page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.url().endsWith('/commands'))commands.push(r.postDataJSON());});
  const g=guided(page),agent=()=>page.locator('[data-guide="agent"]'),reanalyze=()=>page.locator('[data-guide="reanalyze"]');
  const ask=async(status='PROPOSED',fresh=false,extra={},keyboard=false)=>{
   const count=requests.length;nextResponse=(r,b)=>r.fulfill({contentType:'application/json',body:JSON.stringify(proposed(b.descriptor_hash,{status,...extra}))});
   const control=fresh?reanalyze():agent();if(keyboard)await control.press('Enter');else await control.click();await page.waitForFunction(()=>!decisionGuide(currentMaterialTask()).agent.busy);assert.equal(requests.length,count+1);
  };
  const snapshot=()=>page.evaluate(()=>({counts:state.overview.material_review.counts,records:state.overview.material_review.records,artifacts:state.overview.artifacts,scope:scope()}));
  await page.goto(base+'/static/operator.html');await page.locator('#username').fill('plan-author');await page.locator('#password').fill('IssuePlanTest!2026');await page.locator('#loginForm button').click();await page.locator('#currentTask').waitFor();
  await page.locator('[data-scope]').filter({hasText:'方案核对甲'}).click();await g.settle();
  await page.locator('[data-action="material-open-task"]').click();await g.settle();
  await page.locator('[data-action="material-return-list"]').click();await g.settle();
  const open=async()=>{await page.locator('.mat-issue-group').filter({hasText:'发票金额待核对'}).getByRole('button',{name:/进入处理|查看状态/}).click();await g.settle();};
  await open();const baseline=await snapshot(),identity=await page.evaluate(()=>({scope:scope(),task_id:currentMaterialTask().id,descriptor_hash:currentMaterialTask().descriptor.fingerprint}));
  await g.choose('confirm_invoice_amount');
  const draft='人工草稿：客户退货依据尚待核对，不自动采用建议。';await page.locator('#materialNote').fill(draft);
  await check('analysis is user initiated, Scope/task/fingerprint-bound and never auto-applies',async()=>{
   assert.equal(requests.length,0);assert.equal(commands.length,0);await ask();const body=requests[0];
   assert.deepEqual(Object.keys(body).sort(),['descriptor_hash','request_id','scope','stage','task_id']);assert.equal(body.stage,'MATERIAL_GUIDANCE');
   for(const key of ['scope','task_id','descriptor_hash'])assert.deepEqual(body[key],identity[key]);assert(body.request_id.length>=8&&body.request_id.length<=128);
   assert.match(await page.locator('.decision-agent').innerText(),/待人工判断/);assert.match(await page.locator('.decision-agent').innerText(),/模拟调用.*browser-contract-fixture/s);
   assert.equal(await page.locator('#materialNote').inputValue(),draft);assert.equal(await page.locator('[data-option="confirm_invoice_amount"]').getAttribute('aria-pressed'),'true');assert.equal(commands.length,0);assert.deepEqual(await snapshot(),baseline);
  });
  await check('collapsed original preserves input; responsive 1440/1040/390 guidance screenshots',async()=>{
   assert.notEqual(await page.locator('.decision-source').getAttribute('open'),null);await g.sourceDialog();assert.equal(await page.locator('#materialNote').inputValue(),draft);assert.equal(commands.length,0);await g.closeSource();
   for(const width of [1440,1040,390]){await page.setViewportSize({width,height:900});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));assert.equal(await page.locator('.decision-chat .primary:visible').count(),1);await page.screenshot({path:path.join(OUT,`guidance-${width}.png`),fullPage:true});}
   await page.setViewportSize({width:1440,height:900});
  });
  await check('manual option choice does not submit; Enter cannot bypass confirmation summary',async()=>{
   await g.choose('defer_material_issue');assert(await page.locator('#materialReason').isVisible());assert.equal(commands.length,0);
   await g.choose('confirm_invoice_amount');assert.equal(await page.locator('#materialNote').inputValue(),draft);
   await page.locator('#materialNote').press('Enter');assert.equal(commands.length,0);assert.equal(await page.locator('.decision-summary:visible').count(),0);
   await page.locator('[data-guide="next"]').press('Enter');assert(await page.locator('.decision-summary').isVisible());assert.equal(commands.length,0);
   await g.edit(0);await page.locator('#materialNote').fill(draft);assert.equal(await page.locator('.decision-summary:visible').count(),0);
  });
  await check('keyboard next, back and edit focus the current question or summary without submitting',async()=>{
   const before=commands.length;await page.locator('[data-guide="next"]').press('Enter');await g.settle();await g.focus();assert(await page.locator('.decision-summary').isVisible());
   await g.back();await g.focus();assert(await page.locator('#materialNote').isVisible());await g.next();await g.edit(0);await g.focus();
   assert.equal(await page.locator('#materialNote').inputValue(),draft);assert.equal(commands.length,before);
  });
  await check('native Enter activates source, disclosure, Agent and option controls without advancing the question',async()=>{
   const step=()=>page.locator('fieldset[data-guide-step]:visible').getAttribute('data-guide-step');assert.equal(await step(),'0');await g.closeSource();
   await page.locator('.decision-source > summary').press('Enter');assert.notEqual(await page.locator('.decision-source').getAttribute('open'),null);assert.equal(await step(),'0');
   await page.locator('.decision-source [data-object]').first().press('Enter');await page.locator('#dialog[open]').waitFor();await page.keyboard.press('Escape');assert.equal(await step(),'0');assert.equal(await page.locator('#materialNote').inputValue(),draft);
   await page.locator('.decision-source > summary').press('Enter');assert.equal(await page.locator('.decision-source').getAttribute('open'),null);assert.equal(await step(),'0');
   await ask('PROPOSED',false,{},true);assert.equal(await step(),'0');
   await page.locator('[data-option="defer_material_issue"]').press('Enter');assert.equal(await page.locator('[data-option="defer_material_issue"]').getAttribute('aria-pressed'),'true');assert(await page.locator('#materialReason').isVisible());assert.equal(await step(),'0');await g.focus();
   await page.locator('[data-option="confirm_invoice_amount"]').press('Enter');assert.equal(await step(),'0');assert.equal(await page.locator('#materialNote').inputValue(),draft);await g.focus();assert.equal(commands.length,0);
  });
  await check('FAILED and HTTP failure preserve draft; retry reuses key, reanalyze uses a fresh key',async()=>{
   const first=requests[0].request_id;await ask('FAILED',false,{message:'MOCK模型失败，可人工继续。',suggestion:null});assert.equal(requests.at(-1).request_id,first);assert.match(await page.locator('.decision-agent').innerText(),/MOCK模型失败/);assert.equal(await page.locator('#materialNote').inputValue(),draft);
   nextResponse=r=>r.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:{message:'MOCK网络失败，请重试'}})});await agent().click();await page.waitForFunction(()=>!decisionGuide(currentMaterialTask()).agent.busy);
   assert.equal(requests.at(-1).request_id,first);assert.match(await page.locator('.decision-agent').innerText(),/MOCK网络失败/);assert.equal(await page.locator('#materialNote').inputValue(),draft);
   await ask('PROPOSED');assert.equal(requests.at(-1).request_id,first);await ask('PROPOSED',true);assert.notEqual(requests.at(-1).request_id,first);assert.equal(commands.length,0);
  });
  await check('RUNNING waits for explicit check; NEEDS_HUMAN and unknown option stay manual',async()=>{
   await ask('RUNNING',true,{suggestion:null});const count=requests.length,key=requests.at(-1).request_id;assert.match(await agent().innerText(),/检查分析结果/);await delay(400);assert.equal(requests.length,count);
   await ask('NEEDS_HUMAN',false,{suggestion:{option_id:null,reason:'MOCK需人工补充依据',uncertainties:['缺少业务说明'],prefill:{},confidence:0}});assert.equal(requests.at(-1).request_id,key);assert.match(await page.locator('.decision-agent').innerText(),/暂未给出可执行选项/);
   await ask('PROPOSED',true,{suggestion:{option_id:'unknown_write',reason:'MOCK未知处理方式',uncertainties:[],prefill:{},confidence:0.99}});
   assert.match(await page.locator('.decision-agent').innerText(),/暂未给出可执行选项/);assert.equal(await page.locator('[data-option="unknown_write"]').count(),0);assert.equal(await page.locator('#materialNote').inputValue(),draft);assert.equal(commands.length,0);
  });
  await check('mismatched evidence and proposed prefills fail closed without replacing draft',async()=>{
   await ask('PROPOSED',true,{descriptor_hash:'stale-fingerprint',suggestion:{option_id:'defer_material_issue',reason:'DO-NOT-DISPLAY-WRONG-HASH',uncertainties:[],prefill:{},confidence:1}});
   assert.match(await page.locator('.decision-agent').innerText(),/依据不匹配/);assert.doesNotMatch(await page.locator('.decision-agent').innerText(),/DO-NOT-DISPLAY/);
   await ask('PROPOSED',true,{suggestion:{option_id:'confirm_invoice_amount',reason:'DO-NOT-DISPLAY-PREFILL',uncertainties:[],prefill:{reason:'模型偷偷填写'},confidence:1}});
   assert.match(await page.locator('.decision-agent').innerText(),/依据不匹配/);assert.doesNotMatch(await page.locator('.decision-agent').innerText(),/DO-NOT-DISPLAY/);assert.equal(await page.locator('#materialNote').inputValue(),draft);assert.equal(commands.length,0);
  });
  await check('late guidance response cannot steal list navigation; refresh restores human draft',async()=>{
   let received;const incoming=new Promise(r=>received=r);nextResponse=async(r,b)=>{received();await new Promise(resolve=>releaseDelayed=resolve);await r.fulfill({contentType:'application/json',body:JSON.stringify(proposed(b.descriptor_hash,{suggestion:{option_id:'defer_material_issue',reason:'DO-NOT-DISPLAY-LATE',uncertainties:[],prefill:{},confidence:1}}))});};
   await reanalyze().click();await incoming;await page.locator('[data-action="material-return-list"]').click();await g.settle();releaseDelayed();await delay(300);
   assert.equal(await page.evaluate(()=>materialState().screen),'list');assert.doesNotMatch(await page.locator('body').innerText(),/DO-NOT-DISPLAY-LATE/);
   await open();assert.equal(await page.locator('#materialNote').inputValue(),draft);await page.reload();await page.locator('#materialNote').waitFor();assert.equal(await page.locator('#materialNote').inputValue(),draft);
   assert.deepEqual(await snapshot(),baseline);assert.equal(commands.length,0);
  });
  assert.deepEqual(errors,[]);assert.deepEqual(outside,[]);
  fs.writeFileSync(path.join(OUT,'report.json'),JSON.stringify({status:'PASS',flows,errors,commands,requests,fixture:temp,guidance:'All responses HTTP-mocked; no real model or business commands',screenshots:[1440,1040,390].map(w=>`guidance-${w}.png`)},null,2));
 }catch(e){if(page)await page.screenshot({path:path.join(OUT,'failure.png'),fullPage:true});throw e;}finally{if(releaseDelayed)releaseDelayed();if(browser)await browser.close();server.kill('SIGTERM');}
})().catch(e=>{console.error(e);process.exitCode=1;});

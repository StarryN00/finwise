// All financial writes in this suite target an isolated, disposable fixture database.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),net=require('node:net');
const {spawn}=require('node:child_process'),{chromium}=require('playwright');
const ROOT=path.resolve(__dirname,'..'),OUT=path.join(ROOT,'output/playwright/historical-plans');
const delay=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
  const temp=fs.mkdtempSync(path.join(os.tmpdir(),'finwise-issue-plans-'));
  fs.mkdirSync(OUT,{recursive:true});
  const socket=net.createServer();await new Promise(r=>socket.listen(0,'127.0.0.1',r));const port=socket.address().port;await new Promise(r=>socket.close(r));
  const server=spawn('python3',['tests/historical_plans_fixture_server.py','--root',temp,'--port',String(port)],{cwd:ROOT,stdio:['ignore','pipe','pipe']});
  let logs='',browser;server.stderr.on('data',b=>logs+=b);
  const report=[],errors=[],commands=[],base=`http://127.0.0.1:${port}`;
  const check=async(name,fn)=>{await fn();report.push({name,status:'PASS'});console.log('PASS',name);};
  const settle=async page=>page.waitForFunction(()=>!state.busy);
  const field=(page,name)=>page.locator(`[data-history-field="${name}"]`);
  const choose=async(page,route)=>page.locator(`[name="historicalRoute"][value="${route}"]`).check();
  const open=async page=>{await page.locator('#currentTask [data-action="historical-details"]').click();await page.locator('#historyCurrentIssue').waitFor();};
  const issue=async(page,index)=>page.locator(`[data-history-index="${index}"]`).click();
  const fill=async(page,text)=>{for(const [name,value] of Object.entries({conclusion:text,action_plan:'核对同张凭证与余额依据，不直接修改金额',owner:'测试责任会计',follow_up:'2026-09-10 与客户复核并跟进'}))await field(page,name).fill(value);};
  const submit=async(page,form='#historicalPlanForm')=>{await page.locator(form+' button[type="submit"]').click();await settle(page);};
  const login=async user=>{
    const context=await browser.newContext({viewport:{width:1440,height:900}}),page=await context.newPage();
    page.on('pageerror',e=>errors.push(e.message));
    page.on('request',r=>{if(r.url().endsWith('/commands'))commands.push(r.postDataJSON());});
    await page.goto(base+'/static/operator.html');await page.locator('#username').fill(user);await page.locator('#password').fill('IssuePlanTest!2026');await page.locator('#loginForm button').click();await page.locator('#currentTask').waitFor();
    await page.locator('[data-scope]').filter({hasText:'方案核对甲'}).click();await page.locator('#currentTask').waitFor();
    return page;
  };
  try {
    let ready=false;for(let i=0;i<100;i++){if(server.exitCode!==null)throw Error(logs);try{if((await fetch(base+'/api/v1/health')).ok){ready=true;break;}}catch{}await delay(100);}assert(ready,logs);
    browser=await chromium.launch({headless:true});
    const page=await login('plan-author');
    await check('one issue-handling entry replaces duplicated historical upload links',async()=>{
      assert.equal(await page.locator('#currentTask .primary').count(),1);
      assert.equal(await page.locator('[data-action="upload-history"]').count(),0);
      await open(page);assert.equal(await page.locator('.history-issue').count(),1);
      assert.equal(await page.locator('[data-history-index]').count(),2);
      assert.equal(await page.locator('[name="historicalRoute"]').count(),3);
      assert.equal(await page.locator('[data-action="confirm-historical"]').count(),0);
      await page.locator('[data-action="history-handling"]').click();assert(await page.locator('#historyHandling').evaluate(el=>el===document.activeElement));
    });
    await check('per-issue drafts survive navigation without leaking to another issue',async()=>{
      await choose(page,'unavailable');
      assert.equal(await page.locator('#historicalPlanForm textarea').count(),1);
      assert.equal(await page.locator('[data-history-field="owner"],[data-history-field="action_plan"],[data-history-field="follow_up"]').count(),0);
      await field(page,'conclusion').fill('没有其他材料，已向原代账会计核对');
      await issue(page,1);await choose(page,'unavailable');assert.equal(await field(page,'conclusion').inputValue(),'');
      await issue(page,0);assert.equal(await field(page,'conclusion').inputValue(),'没有其他材料，已向原代账会计核对');
    });
    await check('unavailable route saves a real server record without an upload or a financial release',async()=>{
      await submit(page);assert.match(await page.locator('.history-processing').innerText(),/已记录，期初阻断仍保留/);
      const saved=await page.evaluate(()=>state.overview.historical_issue_plans[0]);
      assert.equal(saved.status,'UNAVAILABLE_RECORDED');assert.deepEqual(saved.data.evidence,[]);
      assert.equal(saved.data.submitted_by,'plan-author');
      assert.equal(saved.data.owner,'plan-author');assert.equal(saved.data.action_plan,'');assert.equal(saved.data.follow_up,'');
      assert.deepEqual(Object.keys(commands.at(-1).payload).sort(),['conclusion','expected_plan_version','issue_key','route']);
      assert.equal(await page.evaluate(()=>state.overview.baseline.status),'DRAFT');
      assert.equal(await page.evaluate(()=>state.overview.historical_preparation.status),'NEEDS_REVIEW');
      assert.equal(commands.filter(c=>c.action==='save_historical_issue_plan').length,1);
      await page.locator('[data-action="history-next-item"]').click();assert.match(await page.locator('#historyCurrentIssue').innerText(),/第 2 项/);
      await page.reload();await page.locator('#currentTask').waitFor();await open(page);
      assert.match(await page.locator('.history-processing').innerText(),/没有其他材料，已向原代账会计核对/);
    });
    await check('evidence plan validates empty references locally and retains editable notes',async()=>{
      await issue(page,1);await choose(page,'existing_evidence');await fill(page,'已有凭证显示调整，需要复核对应关系');
      await submit(page);assert.match(await page.locator('#historicalPlanForm').innerText(),/请关联至少一处/);
      assert.equal(await field(page,'conclusion').inputValue(),'已有凭证显示调整，需要复核对应关系');
      assert.equal(commands.filter(c=>c.action==='save_historical_issue_plan').length,1);
      await page.locator('[data-history-evidence]').first().check();
      assert.doesNotMatch(await page.locator('#historicalPlanForm [data-history-error]').innerText(),/请关联至少一处/);
      await page.screenshot({path:path.join(OUT,'evidence-plan-1440.png'),fullPage:true});
    });
    await check('duplicate submit is locked while a command is in flight; failure keeps the draft',async()=>{
      let fail=true;
      await page.route('**/api/v1/commands',async route=>{await delay(300);if(fail){fail=false;await route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:{message:'测试临时不可用'}})});}else await route.continue();});
      await submit(page);assert.match(await page.locator('#historicalPlanForm').innerText(),/测试临时不可用/);
      assert.equal(await field(page,'conclusion').inputValue(),'已有凭证显示调整，需要复核对应关系');
      const before=commands.length;
      await page.locator('#historicalPlanForm button[type="submit"]').click();
      assert.equal(await page.locator('#historicalPlanForm button[type="submit"]').isDisabled(),true);
      await settle(page);await page.unroute('**/api/v1/commands');
      assert.equal(commands.length,before+1);
      assert.equal(commands.at(-1).idempotency_key,commands.at(-2).idempotency_key);
      assert.equal(await page.locator('#historicalReviewForm').count(),0);
      assert.match(await page.locator('#historyHandoff').innerText(),/2 \/ 2/);
      assert.equal(await page.locator('#historicalPlanForm').count(),0);
      await issue(page,1);
      assert.match(await page.locator('.history-processing').innerText(),/等待另一位/);
    });
    await check('completed round restores guidance, opens current files, and exposes upload for an empty period',async()=>{
      const before=commands.length;
      await page.reload();await page.locator('#currentTask').waitFor();
      assert.match(await page.locator('#currentTask').innerText(),/本轮处理意见已记录 2 \/ 2/);
      assert.equal(await page.locator('#currentTask .primary').count(),1);
      await page.locator('#currentTask [data-action="history-next-work"]').click();
      await page.locator('#materialWorkbench').waitFor();
      assert.match(await page.locator('#materialWorkbench').innerText(),/本期尚无业务原件/);
      await page.locator('#materialWorkbench [data-action="upload"]').click();await page.locator('#uploadForm').waitFor();
      assert.equal(await page.locator('#uploadPeriod').inputValue(),'2026-01');await page.keyboard.press('Escape');
      await page.locator('[data-action="return-current"]').click();await open(page);
      for(const [width,height] of [[1440,900],[1040,900],[390,844]]){
        await page.setViewportSize({width,height});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
        assert.equal(await page.locator('#historyHandoff .primary').count(),1);
        await page.screenshot({path:path.join(OUT,`next-step-${width}.png`),fullPage:true});
      }
      await page.setViewportSize({width:1440,height:900});assert.equal(commands.length,before);
    });
    const reviewer=await login('plan-reviewer');
    await reviewer.locator('#currentTask [data-action="history-next-work"]').click();await reviewer.locator('#historicalReviewForm').waitFor();
    assert.match(await reviewer.locator('#historyCurrentIssue').innerText(),/第 2 项/);
    await check('another authorized reviewer can return a proposal with a saved explanation',async()=>{
      assert.equal(await reviewer.locator('#historicalPlanForm').count(),0);
      await field(reviewer,'review_decision').selectOption('returned');await field(reviewer,'review_note').fill('请说明余额表缺列原因');
      await submit(reviewer,'#historicalReviewForm');
      assert.match(await reviewer.locator('.history-processing').innerText(),/退回补充说明/);
      assert.match(await reviewer.locator('.history-processing').innerText(),/请说明余额表缺列原因/);
    });
    await check('author revision clears prior review and requires a fresh reviewer decision',async()=>{
      await page.reload();await page.locator('#materialWorkbench').waitFor();await page.locator('[data-action="return-current"]').click();await open(page);await issue(page,1);
      await page.locator('[data-action="edit-history-plan"]').click();await field(page,'conclusion').fill('已补充调整说明，余额依据仍待核对');
      await submit(page);
      const saved=await page.evaluate(()=>state.overview.historical_issue_plans.find(p=>p.data.route==='existing_evidence'));
      assert.equal(saved.status,'SUBMITTED');assert.equal(saved.version,3);assert.equal(saved.data.review,undefined);
      await reviewer.reload();await reviewer.locator('#currentTask').waitFor();await open(reviewer);await issue(reviewer,1);
      await field(reviewer,'review_note').fill('同意处理计划，实际余额仍需原始证据校验');await submit(reviewer,'#historicalReviewForm');
      await issue(reviewer,1);
      assert.match(await reviewer.locator('.history-processing').innerText(),/方案复核通过/);
      assert.equal(await reviewer.evaluate(()=>state.overview.baseline.status),'DRAFT');
      assert.equal(await reviewer.evaluate(()=>state.overview.vouchers.length),0);
      assert.equal(await reviewer.evaluate(()=>state.overview.historical_preparation.data.result.issues.length),2);
      await reviewer.getByRole('button',{name:'查看记录与复核留痕',exact:true}).click();await reviewer.locator('#dialogBody details summary').click();
      assert.match(await reviewer.locator('#dialogBody').innerText(),/plan-author/);
      assert.match(await reviewer.locator('#dialogBody').innerText(),/请说明余额表缺列原因/);
      await reviewer.keyboard.press('Escape');
    });
    const viewer=await login('plan-viewer');await open(viewer);await issue(viewer,1);
    await check('viewer sees records but cannot submit, review, or reveal ungranted companies',async()=>{
      assert.equal(await viewer.locator('#historicalPlanForm,#historicalReviewForm,[data-action="edit-history-plan"]').count(),0);
      assert.match(await viewer.locator('.history-processing').innerText(),/方案复核通过/);
      assert.equal(await viewer.locator('[data-scope]').filter({hasText:'未授权企业'}).count(),0);
    });
    await check('enterprise switching resets issue selection, draft, records, and source bindings',async()=>{
      await page.locator('[data-action="history-current-files"]').click();await page.locator('#receivedFiles').waitFor();
      assert.equal(await page.evaluate(()=>state.filesFilter),'business');
      await page.locator('[data-action="return-files"]').click();await page.locator('#historyCurrentIssue').waitFor();
      await page.locator('[data-scope]').filter({hasText:'方案核对乙'}).click();await page.locator('#currentTask').waitFor();await open(page);
      await choose(page,'unavailable');assert.equal(await field(page,'conclusion').inputValue(),'');
      assert.equal(await page.evaluate(()=>state.overview.historical_issue_plans.length),0);
      assert.doesNotMatch(await page.locator('.history-processing').innerText(),/已补充调整说明/);
      await page.locator('[data-scope]').filter({hasText:'方案核对甲'}).click();await page.locator('#materialWorkbench').waitFor();await page.locator('[data-action="return-current"]').click();await open(page);
      await issue(page,0);
      assert.match(await page.locator('.history-processing').innerText(),/没有其他材料/);
    });
    await check('mobile and narrow desktop support keyboard selection, form editing, and contained tables',async()=>{
      await page.locator('[data-action="edit-history-plan"]').click();
      for(const [width,height] of [[1040,900],[390,844]]) {
        await page.setViewportSize({width,height});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
        await page.locator('[name="historicalRoute"][value="existing_evidence"]').focus();await page.keyboard.press('Space');
        assert(await page.locator('[data-history-evidence]').count()>0);
        await choose(page,'unavailable');await field(page,'conclusion').fill('客户暂时无法提供其他材料');
        await page.locator('#historicalPlanForm button[type="submit"]').scrollIntoViewIfNeeded();
        const box=await page.locator('#historicalPlanForm button[type="submit"]').boundingBox();assert(box.x>=0&&box.x+box.width<=width);
        await page.screenshot({path:path.join(OUT,`unavailable-${width}.png`)});
      }
      await page.setViewportSize({width:1440,height:900});
    });
    await check('upload path uses actual file upload and new source selection invalidates old approval',async()=>{
      await choose(page,'upload');assert.equal(await page.locator('[data-action="upload-history"]').count(),1);
      await page.locator('[data-action="upload-history"]').click();await page.locator('#baselineFile').setInputFiles(path.join(temp,'corrected-journal.xlsx'));await settle(page);
      await page.waitForFunction(()=>state.overview.historical_preparation.status==='NEEDS_SELECTION');
      assert(await page.evaluate(()=>state.overview.historical_issue_plans.every(p=>p.stale)));
      assert.equal(await page.locator('#historicalReviewForm').count(),0);
      await page.locator('#historySource0').waitFor();
      await page.screenshot({path:path.join(OUT,'replacement-selection.png'),fullPage:true});
    });
    assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(OUT,'report.json'),JSON.stringify({status:'PASS',report,errors,retained_data_modified:false,fixture_directory:temp},null,2));
  } catch(error) {
    fs.writeFileSync(path.join(OUT,'failure.json'),JSON.stringify({report,error:String(error),logs},null,2));throw error;
  } finally {if(browser)await browser.close();server.kill('SIGTERM');}
})().catch(e=>{console.error(e);process.exitCode=1;});

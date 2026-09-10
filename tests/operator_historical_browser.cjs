// Real uploads and commands use only this test's disposable local database.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),net=require('node:net');
const {spawn}=require('node:child_process'),{chromium}=require('playwright');
const ROOT=path.resolve(__dirname,'..'),OUT=path.join(ROOT,'output/playwright/historical');
const delay=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
  const temp=fs.mkdtempSync(path.join(os.tmpdir(),'finwise-historical-'));
  fs.mkdirSync(OUT,{recursive:true});
  const socket=net.createServer();await new Promise(r=>socket.listen(0,'127.0.0.1',r));const port=socket.address().port;await new Promise(r=>socket.close(r));
  const server=spawn('python3',['tests/historical_fixture_server.py','--root',temp,'--port',String(port)],{cwd:ROOT,stdio:['ignore','pipe','pipe']});
  let logs='',browser;server.stderr.on('data',b=>logs+=b);
  const report=[],base=`http://127.0.0.1:${port}`;
  const check=async(name,fn)=>{await fn();report.push({name,status:'PASS'});console.log('PASS',name);};
  try {
    for(let i=0;i<80;i++){if(server.exitCode!==null)throw Error(logs);try{if((await fetch(base+'/api/v1/health')).ok)break;}catch{}await delay(100);}
    browser=await chromium.launch({headless:true});
    const context=await browser.newContext({viewport:{width:1440,height:900}}),page=await context.newPage(),errors=[],commands=[];
    page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.url().endsWith('/commands'))commands.push(r.postDataJSON());});
    await page.goto(base+'/static/operator.html');await page.locator('#username').fill('history-tester');await page.locator('#password').fill('HistoricalTest!2026');await page.locator('#loginForm button').click();await page.locator('#currentTask').waitFor();
    await page.locator('[data-scope]').filter({hasText:'历史核对测试'}).click();await page.getByText('接收本期业务资料',{exact:true}).waitFor();
    const upload=async(file)=>{
      await page.locator('[data-action="upload-history"]').click();
      await page.locator('#baselineFile').setInputFiles(path.join(temp,file));
      await page.waitForFunction(()=>!state.busy);await page.locator('#currentTask').waitFor();
    };
    await check('upload automatically queues and waits for the other workbook without claiming completion',async()=>{
      await upload('balance.xlsx');await page.getByText('等待另一份账表',{exact:true}).first().waitFor();
      assert.equal(commands.length,0);assert.equal(await page.locator('[data-action="confirm-historical"]').count(),0);
    });
    await check('second upload automatically cross-checks and updates without clicking start or refresh',async()=>{
      await upload('journal.xlsx');
      await page.locator('.secondary-nav [data-action="upload"]').click();
      await page.locator('#uploadPeriod').fill('2020-08');await delay(2200);
      assert(await page.locator('dialog').isVisible());assert.equal(await page.locator('#uploadPeriod').inputValue(),'2020-08');
      await page.keyboard.press('Escape');await page.locator('[data-action="confirm-historical"]').waitFor();
      assert.equal(commands.length,0);assert.match(await page.locator('#currentTask').innerText(),/已提取 2 条分录、1 张历史凭证/);
      assert(await page.locator('[data-action="confirm-historical"]').isDisabled());
      assert.equal(await page.evaluate(()=>state.overview.counts.facts),0);
      assert.equal(await page.evaluate(()=>state.overview.baseline.status),'DRAFT');
      await page.screenshot({path:path.join(OUT,'desktop-ready.png'),fullPage:true});
    });
    await check('details are a readable page and original downloads remain scope-bound',async()=>{
      await page.locator('[data-action="historical-details"]').click();await page.locator('#historicalTitle').waitFor();
      await page.getByText('期末余额 → 期初候选',{exact:true}).click();
      assert.match(await page.locator('#workspace').innerText(),/原表一级科目期末/);
      await page.locator('#workspace [data-object]').first().click();await page.locator('dialog a[download]').waitFor();
      assert((await context.request.get(new URL(await page.locator('dialog a[download]').getAttribute('href'),base).href)).ok());
      await page.keyboard.press('Escape');await page.locator('[data-action="return-current"]').click();
    });
    await check('refresh restores candidate but does not remember a human approval checkbox',async()=>{
      await page.locator('[data-history-confirm="final_close_confirmed"]').check();await page.reload();await page.locator('[data-action="confirm-historical"]').waitFor();
      assert.equal(await page.locator('[data-history-confirm="final_close_confirmed"]').isChecked(),false);
    });
    await check('narrow desktop and mobile have no page overflow; confirmation remains reachable',async()=>{
      for(const [width,height] of [[1040,900],[390,844]]) {
        await page.setViewportSize({width,height});
        assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
        await page.locator('[data-action="confirm-historical"]').scrollIntoViewIfNeeded();
        const box=await page.locator('[data-action="confirm-historical"]').boundingBox();assert(box.x>=0&&box.x+box.width<=width);
        await page.screenshot({path:path.join(OUT,`ready-${width}.png`),fullPage:true});
      }
      await page.setViewportSize({width:1440,height:900});
    });
    await check('three explicit confirmations submit one scope-bound baseline command then show next task',async()=>{
      for(const flag of ['final_close_confirmed','completeness_confirmed','carry_forward_confirmed'])await page.locator(`[data-history-confirm="${flag}"]`).check();
      await page.locator('[data-action="confirm-historical"]').dblclick();await page.getByText('接收本期业务资料',{exact:true}).waitFor();
      assert.equal(commands.filter(c=>c.action==='confirm_baseline').length,1);
      assert.equal(await page.evaluate(()=>state.overview.baseline_validation.status),'VALID');
      assert.equal(await page.evaluate(()=>state.overview.vouchers.length),0);
    });
    await check('failed job displays reason and retry posts actual command; no hidden successful result',async()=>{
      await page.locator('[data-scope]').filter({hasText:'失败重试测试'}).click();await page.getByText('接收本期业务资料',{exact:true}).waitFor();
      await upload('bad.xlsx');await upload('journal.xlsx');await page.locator('[data-action="retry-historical"]').waitFor();
      assert.match(await page.locator('#currentTask').innerText(),/无法识别 Excel 格式/);
      await page.locator('[data-action="retry-historical"]').click();await page.waitForFunction(()=>!state.busy);await page.waitForFunction(()=>state.overview.historical_preparation.status==='FAILED');
      assert.equal(commands.filter(c=>c.action==='prepare_historical').length,1);
      assert.equal(await page.evaluate(()=>state.overview.baseline.status),'DRAFT');
    });
    await check('scope switches and source pages do not mix previous company candidate',async()=>{
      await page.locator('[data-action="baseline-files"]').click();assert.match(await page.locator('#receivedFiles').innerText(),/处理失败/);
      await page.locator('[data-scope]').filter({hasText:'历史核对测试'}).click();await page.getByText('接收本期业务资料',{exact:true}).waitFor();
      assert.doesNotMatch(await page.locator('#workspace').innerText(),/bad.xlsx|无法识别 Excel/);
      assert.equal(await page.locator('[data-scope]').filter({hasText:'未授权企业'}).count(),0);
    });
    await check('ambiguous originals can be selected explicitly and reprocessed',async()=>{
      await page.locator('[data-scope]').filter({hasText:'失败重试测试'}).click();await page.locator('[data-action="retry-historical"]').waitFor();
      await upload('balance.xlsx');await page.locator('#historySource0').waitFor();
      const ids=await page.evaluate(()=>Object.fromEntries(state.overview.artifacts.map(a=>[a.data.filename,a.object_id])));
      await page.locator('#historySource0').selectOption(ids['balance.xlsx']);await page.locator('#historySource1').selectOption(ids['journal.xlsx']);
      await page.locator('[data-action="select-historical"]').click();await page.waitForFunction(()=>!state.busy);await page.locator('[data-action="confirm-historical"]').waitFor();
      assert.equal(await page.evaluate(()=>state.overview.historical_preparation.data.sources.length),2);
      await page.reload();await page.locator('[data-action="confirm-historical"]').waitFor();assert.equal(await page.locator('#historySource0').count(),0);
    });
    assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(OUT,'report.json'),JSON.stringify({report,errors,retained_data_modified:false},null,2));
  } finally {if(browser)await browser.close();server.kill('SIGTERM');}
})().catch(e=>{console.error(e);process.exitCode=1;});

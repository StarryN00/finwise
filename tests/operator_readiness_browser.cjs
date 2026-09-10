// Authenticated real API flows in a disposable DB; Staging is only inspected read-only.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const net = require('node:net');
const crypto = require('node:crypto');
const {spawn, execFileSync} = require('node:child_process');
const {chromium} = require('playwright');
const ROOT = path.resolve(__dirname,'..'), OUT = path.join(ROOT,'output/playwright/readiness');
const report = [], temp = fs.mkdtempSync(path.join(os.tmpdir(),'finwise-readiness-browser-'));
const delay = ms => new Promise(resolve=>setTimeout(resolve,ms));
async function freePort(){const s=net.createServer();await new Promise(r=>s.listen(0,'127.0.0.1',r));const p=s.address().port;await new Promise(r=>s.close(r));return p;}
async function main(){
  fs.mkdirSync(OUT,{recursive:true});const port=await freePort(),base=`http://127.0.0.1:${port}`;
  const server=spawn('python3',['tests/readiness_fixture_server.py','--root',temp,'--port',String(port)],{cwd:ROOT,stdio:['ignore','pipe','pipe']});
  let logs='';server.stderr.on('data',b=>logs+=b);
  let browser;
  const check=async(name,fn)=>{await fn();report.push({name,status:'PASS'});console.log('PASS',name);};
  try{
    for(let i=0;i<80;i++){if(server.exitCode!==null)throw Error(logs);try{if((await fetch(base+'/api/v1/health')).ok)break;}catch(_){}await delay(100);}
    browser=await chromium.launch({headless:true});
    const context=await browser.newContext({viewport:{width:1440,height:900}}),page=await context.newPage(),errors=[],writes=[];
    page.on('pageerror',e=>errors.push(e.message));
    page.on('request',r=>{if(r.url().endsWith('/commands')||r.url().endsWith('/artifacts'))writes.push(r.postDataJSON());});
    const fixture=JSON.parse(fs.readFileSync(path.join(temp,'fixture.json'),'utf8'));
    async function login(user='readiness-operator'){
      await context.clearCookies();
      await page.goto(base+'/static/operator.html');await page.locator('#username').fill(user);await page.locator('#password').fill('ReadinessTest!2026');await page.locator('#loginForm button').click();await page.locator('#currentTask').waitFor();
      if(!await page.locator('.context').innerText().then(t=>t.includes('校验测试企业'))){await page.locator('[data-scope]').filter({hasText:'校验测试企业'}).click();await page.locator('#currentTask').waitFor();}
    }
    await check('login and first screen show structure, direct task and one action',async()=>{
      await login();assert.match(await page.locator('#workspace').innerText(),/资料结构/);assert.equal(await page.locator('#currentTask .primary').count(),1);
      const box=await page.locator('#currentTask .primary').boundingBox();assert(box.y+box.height<900);
      assert.equal(await page.locator('[data-source-role="balance"]').inputValue(),'');
      assert.equal(await page.locator('[data-source-role="close"]').inputValue(),'');
      assert.match(await page.locator('.result-summary').innerText(),/0 项/);
    });
    await check('category issue to original values, close and focus return',async()=>{
      await page.locator('[data-category="purchase"]').click();await page.locator('[data-issue]').first().click();assert.match(await page.locator('dialog').innerText(),/税率/);
      await page.locator('dialog [data-object]').first().click();await page.getByText('原始值（未经改写）',{exact:true}).waitFor();assert.match(await page.locator('dialog').innerText(),/TEST-INVOICE-001/);
      await page.keyboard.press('Escape');assert.equal(await page.locator('dialog').isVisible(),false);
      await page.locator('[data-action="return-task"]').click();
    });
    await check('same-month prior bill does not pass baseline comparison',async()=>{
      await page.locator('.source-slot summary').first().click();await page.locator('[data-source-role="balance"]').selectOption(fixture.prior_id);
      await page.locator('.source-slot summary').nth(1).click();await page.locator('[data-source-role="close"]').selectOption(fixture.prior_id);
      await page.locator('[data-action="compare-baseline"]').click();await page.locator('#notice.error').waitFor();assert.equal(await page.locator('#baselineConfirmed').count(),0);
    });
    await check('scope switch clears selections, restores selected scope and no phantom history',async()=>{
      await page.locator('[data-scope]').filter({hasText:'空白测试企业'}).click();await page.getByText('接收本期业务资料',{exact:true}).waitFor();assert.match(await page.locator('.overall').innerText(),/0/);
      await page.reload();await page.getByText('接收本期业务资料',{exact:true}).waitFor();assert.match(await page.locator('.context').innerText(),/空白测试企业/);
      await page.locator('[data-action="history"]').click();await page.getByText('没有可查看的往期授权数据。',{exact:true}).waitFor();
      await page.locator('[data-action="return-current"]').click();await page.locator('[data-scope]').filter({hasText:'校验测试企业'}).click();await page.locator('[data-action="upload-baseline"]').waitFor();
      assert.equal(await page.locator('[data-source-role="balance"]').inputValue(),'');
    });
    await check('upload opening and closing sources, compare, explicit confirmation and usable proof',async()=>{
      const countBefore=writes.filter(w=>w?.action==='confirm_baseline').length;
      let chooser=page.waitForEvent('filechooser');await page.locator('[data-action="upload-baseline"]').click();await (await chooser).setFiles(path.join(temp,'opening.xlsx'));
      await page.getByRole('button',{name:'添加上期末余额资料',exact:true}).waitFor();assert.equal(writes.filter(w=>w?.action==='confirm_baseline').length,countBefore);
      chooser=page.waitForEvent('filechooser');await page.locator('[data-action="upload-baseline"]').click();await (await chooser).setFiles(path.join(temp,'closing.xlsx'));
      await page.locator('[data-action="compare-baseline"]').waitFor();await page.locator('[data-action="compare-baseline"]').click();await page.locator('#baselineConfirmed').waitFor();
      assert.equal(await page.locator('[data-action="confirm-baseline"]').isDisabled(),true);assert.match(await page.locator('#comparison').innerText(),/2 \/ 2 行一致/);
      await page.locator('#baselineConfirmed').check();
      const original=fs.readFileSync(path.join(temp,'opening.xlsx')),hash=crypto.createHash('sha256').update(original).digest('hex');
      const stored=path.join(temp,'artifacts',hash.slice(0,2),hash+'.bin');
      // Simulate a temporary source integrity failure only inside this disposable fixture.
      try{fs.writeFileSync(stored,Buffer.from('damaged fixture'));await page.locator('[data-action="confirm-baseline"]').click();await page.locator('#notice.error').waitFor();}
      finally{fs.writeFileSync(stored,original);}
      assert.equal(await page.getByRole('heading',{name:'期初余额已人工核实'}).count(),0);
      await page.locator('[data-action="confirm-baseline"]').dblclick();await page.getByRole('heading',{name:'期初余额已人工核实'}).waitFor();
      const confirmations=writes.filter(w=>w?.action==='confirm_baseline');
      assert.equal(confirmations.length,countBefore+2);assert.notEqual(confirmations.at(-1).idempotency_key,confirmations.at(-2).idempotency_key);
      assert.equal(writes.filter(w=>w?.action==='confirm_baseline').at(-1).payload.completeness_confirmed,true);
      assert.match(await page.locator('#currentTask').innerText(),/核对提取结果与业务期间/);
      await page.locator('.proof [data-object]').click();await page.getByText('用途：本期账务衔接',{exact:true}).waitFor();assert.match(await page.locator('dialog').innerText(),/readiness-operator/);await page.keyboard.press('Escape');
      await page.reload();await page.getByRole('heading',{name:'期初余额已人工核实'}).waitFor();
    });
    await check('supplementary upload parses using real API and deduplicates source',async()=>{
      await page.locator('[data-scope]').filter({hasText:'空白测试企业'}).click();await page.locator('#currentTask [data-action="upload"]').click();
      await page.locator('#uploadFile').setInputFiles(path.join(temp,'invoice.xlsx'));await page.locator('#uploadForm button').click();await page.getByRole('heading',{name:'补充并核对期初余额'}).waitFor();
      const parse=writes.filter(w=>w?.action==='parse_artifact').at(-1);assert.equal(parse.payload.document_kind,'purchase_invoices');
      await page.locator('.secondary-nav [data-action="upload"]').click();await page.locator('#uploadFile').setInputFiles(path.join(temp,'invoice.xlsx'));await page.locator('#uploadForm button').click();await page.getByText('原件已保存（同内容复用既有原件），尚未完成核实。',{exact:true}).waitFor();
      assert.match(await page.locator('.structure .section-title').innerText(),/1 份有效原件/);
    });
    await check('mobile and narrow desktop contain primary action, drawer focus and no page overflow',async()=>{
      for(const size of [{width:1040,height:900},{width:390,height:844}]){
        await page.setViewportSize(size);await page.evaluate(()=>window.scrollTo(0,0));
        const box=await page.locator('#currentTask .primary').boundingBox();assert(box.y+box.height<=size.height,`primary outside ${size.width}: ${JSON.stringify(box)}`);
        assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
        await page.screenshot({path:path.join(OUT,`fixture-${size.width}.png`)});
      }
      await page.locator('#openSidebar').click();assert.equal(await page.locator('#main').evaluate(el=>el.inert),true);
      await page.keyboard.press('Shift+Tab');assert.equal(await page.locator('#sidebar').evaluate(el=>el.contains(document.activeElement)),true);
      await page.keyboard.press('Escape');assert.equal(await page.locator('#main').evaluate(el=>el.inert),false);
      assert.equal(await page.locator('#openSidebar').evaluate(el=>el===document.activeElement),true);
      await page.locator('[data-action="stages"]').click();assert.equal(await page.locator('.stages.expanded').count(),1);await page.locator('[data-action="stages"]').click();
    });
    await check('business parse failure is visible despite HTTP 200 and source stays retained',async()=>{
      await page.setViewportSize({width:1440,height:900});
      await page.locator('.secondary-nav [data-action="upload"]').click();await page.locator('#uploadFile').setInputFiles(path.join(temp,'broken.xlsx'));await page.locator('#uploadForm button').click();
      await page.locator('#notice.error').waitFor();assert.match(await page.locator('#notice').innerText(),/原件已保留.*提取失败/);
      await page.locator('#closeDialog').click();await page.locator('.secondary-nav [data-action="artifacts"]').click();assert.match(await page.locator('#receivedFiles').innerText(),/broken.xlsx/);assert.match(await page.locator('#receivedFiles').innerText(),/处理失败/);await page.locator('[data-action="return-files"]').click();
    });
    await check('incomplete response retries idempotently; candidate approval, voucher review and source proof',async()=>{
      await page.locator('[data-scope]').filter({hasText:'规则测试企业'}).click();await page.locator('#currentTask [data-action="cards"]').click();await page.locator('[data-card]').click();
      assert.equal(await page.locator('[data-execute="approve_rule"]').isDisabled(),true);await page.locator('#ruleConfirmed').check();
      // The real fixture command succeeds, but the client receives a truncated response body.
      await page.route('**/api/v1/commands',async route=>{
        const response=await route.fetch();assert.equal(response.status(),200);
        await route.fulfill({response,body:'{"command":'});
      },{times:1});
      await page.locator('[data-execute="approve_rule"]').click();await page.locator('#notice.error').filter({hasText:'结果尚不确定'}).waitFor();
      assert.match(await page.locator('#notice').innerText(),/结果尚不确定/);assert.equal(await page.locator('dialog').isVisible(),true);
      await page.locator('[data-execute="approve_rule"]').click();
      await page.getByRole('heading',{name:'核对业务归属并继续处理',exact:true}).waitFor();
      const approvals=writes.filter(w=>w?.action==='approve_rule');assert.equal(approvals.length,2);assert.equal(approvals[0].idempotency_key,approvals[1].idempotency_key);
      await page.locator('#currentTask [data-action="groups"]').click();await page.locator('[data-command="generate_draft"]').click();await page.locator('[data-execute="generate_draft"]').click();await page.locator('#currentTask [data-action="vouchers"]').click();
      assert.equal(await page.locator('dialog').isVisible(),false);await page.locator('[data-object]').first().click();await page.getByText('库存商品',{exact:true}).waitFor();assert.match(await page.locator('dialog').innerText(),/银行存款/);await page.keyboard.press('Escape');
      await page.locator('[data-command="validate_draft"]').click();await page.locator('[data-execute="validate_draft"]').click();await page.getByText('本地已复核',{exact:true}).waitFor();await page.locator('[data-action="return-current"]').click();
      await page.getByRole('heading',{name:'凭证已本地复核',exact:true}).waitFor();assert.match(await page.locator('.proof').last().innerText(),/readiness-operator/);
    });
    await check('late portfolio from prior account cannot restore its authorized scopes',async()=>{
      const p=await context.newPage();let received,release,first=true;
      const arrived=new Promise(r=>received=r),held=new Promise(r=>release=r);
      await p.route('**/api/v1/portfolio',async route=>{if(first){first=false;const response=await route.fetch();received();await held;await route.fulfill({response});}else await route.continue();});
      await p.goto(base+'/static/operator.html');await arrived;
      await p.locator('#username').fill('readiness-viewer');await p.locator('#password').fill('ReadinessTest!2026');await p.locator('#loginForm button').click();await p.locator('#currentTask').waitFor();
      release();await delay(150);assert.doesNotMatch(await p.locator('#scopeList').innerText(),/规则测试企业/);assert.match(await p.locator('#authState').innerText(),/只读/);await p.close();
      await login();
    });
    await check('revoked Scope removes stale financial data and reloads allowed scopes',async()=>{
      await page.locator('[data-scope]').filter({hasText:'校验测试企业'}).click();await page.locator('#currentTask').waitFor();
      execFileSync('python3',['-c','import sqlite3,json,sys; c=sqlite3.connect(sys.argv[1]); s=json.dumps(json.loads(sys.argv[2]),ensure_ascii=False,sort_keys=True,separators=(",",":")); c.execute("DELETE FROM auth_scope_grants WHERE user_id=? AND scope_json=?",("readiness-operator",s)); c.commit()',path.join(temp,'test.db'),JSON.stringify(fixture.scopes[0])]);
      await page.locator('[data-action="refresh"]').click();await page.waitForFunction(()=>!document.querySelector('#scopeList').innerText.includes('校验测试企业'));
      await page.locator('#currentTask').waitFor();assert.doesNotMatch(await page.locator('.context').innerText(),/校验测试企业/);assert.equal(await page.locator('dialog').isVisible(),false);
    });
    await check('late history response cannot replace a later visit',async()=>{
      let arrived,release,first=true;const received=new Promise(r=>arrived=r),held=new Promise(r=>release=r);
      await page.route('**/api/v1/history',async route=>{
        if(!first)return route.continue();first=false;const response=await route.fetch(),data=await response.json();
        data.periods.push({scope:{...fixture.scopes[1],accounting_period_id:'1999-01'},counts:{source_artifacts:99,facts:99}});
        arrived();await held;await route.fulfill({response,json:data});
      });
      await page.locator('[data-action="history"]').click();await received;await page.locator('[data-action="return-current"]').click();await page.locator('[data-action="history"]').click();
      await page.getByText('没有可查看的往期授权数据。',{exact:true}).waitFor();release();await delay(150);assert.doesNotMatch(await page.locator('#historyContent').innerText(),/1999/);
      await page.unroute('**/api/v1/history');await page.locator('[data-action="return-current"]').click();
    });
    await check('expired authentication clears all financial content and dialog',async()=>{
      await page.setViewportSize({width:1440,height:900});await context.clearCookies();await page.locator('[data-action="refresh"]').click();await page.locator('#loginForm').waitFor();
      assert.doesNotMatch(await page.locator('#workspace').innerText(),/三月发票|空白测试企业|已核实可用/);assert.equal(await page.locator('dialog').isVisible(),false);
    });
    await check('viewer can inspect sources but cannot submit baseline',async()=>{
      await login('readiness-viewer');await page.locator('[data-scope]').filter({hasText:'空白测试企业'}).click();await page.locator('#currentTask').waitFor();
      assert.equal(await page.locator('#currentTask .primary').isDisabled(),true);
      await page.locator('#sourceStage').click();await page.locator('#receivedFiles [data-object]').first().click();await page.getByRole('link',{name:'下载原始文件'}).waitFor();await page.keyboard.press('Escape');
    });
    await check('unavailable localStorage does not prevent authorized workbench loading',async()=>{
      const p=await context.newPage();await p.addInitScript(()=>{Object.defineProperty(window,'localStorage',{get(){throw Error('storage unavailable');}});});
      await p.goto(base+'/static/operator.html');await p.locator('#currentTask').waitFor();await p.close();
    });
    assert.deepEqual(errors,[]);
    await context.close();
    // The retained real Staging server: only login and read-only endpoint/UI actions.
    if(process.env.FINWISE_STAGING_URL){
      await check('retained Juxianda dataset: desktop/mobile, grouped issues and real AI coverage',async()=>{
        const ctx=await browser.newContext({viewport:{width:1440,height:900}}),p=await ctx.newPage();
        const mutation=[];p.on('request',r=>{if(/\/(commands|artifacts|agent\/)/.test(new URL(r.url()).pathname)&&r.method()!=='GET')mutation.push(r.url());});
        await p.goto(process.env.FINWISE_STAGING_URL);await p.locator('#username').fill('juxianda-staging');await p.locator('#password').fill('FinWiseJuxianda!2026');await p.locator('#loginForm button').click();await p.locator('#currentTask').waitFor();
        const text=await p.locator('#workspace').innerText();for(const token of ['220','157','58','5','11 份','1 次真实调用 · 调用时涉及 2 条事实'])assert(text.includes(token));
        assert.match(text,/0 项/);await p.screenshot({path:path.join(OUT,'juxianda-1440.png')});
        await p.locator('[data-category="purchase"]').click();await p.screenshot({path:path.join(OUT,'juxianda-purchase-issues.png')});await p.locator('[data-issue]').first().click();await p.locator('dialog [data-object]').first().click();await p.getByText('原始值（未经改写）',{exact:true}).waitFor();await p.screenshot({path:path.join(OUT,'juxianda-source-trace.png')});await p.keyboard.press('Escape');await p.locator('[data-action="return-task"]').click();
        for(const size of [{width:1040,height:900},{width:390,height:844}]){await p.setViewportSize(size);await p.evaluate(()=>window.scrollTo(0,0));assert(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));const b=await p.locator('#currentTask .primary').boundingBox();assert(b.y+b.height<=size.height);await p.screenshot({path:path.join(OUT,`juxianda-${size.width}.png`)});}
        assert.deepEqual(mutation,[]);await ctx.close();
      });
    }
    fs.writeFileSync(path.join(OUT,'browser-report.json'),JSON.stringify({status:'PASS',tests:report,fixture_root:temp},null,2));
  } finally {if(browser)await browser.close();server.kill('SIGTERM');}
}
main().catch(error=>{fs.mkdirSync(OUT,{recursive:true});fs.writeFileSync(path.join(OUT,'browser-report.json'),JSON.stringify({status:'FAIL',tests:report,error:error.stack,fixture_root:temp},null,2));console.error(error);process.exitCode=1;});

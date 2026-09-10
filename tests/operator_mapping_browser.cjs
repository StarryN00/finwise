const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),net=require('node:net');
const {spawn}=require('node:child_process'),{chromium}=require('playwright');
(async()=>{
 const root=path.resolve(__dirname,'..'),out=path.join(root,'output/playwright/payroll-mapping');fs.mkdirSync(out,{recursive:true});
 const temp=fs.mkdtempSync(path.join(os.tmpdir(),'finwise-payroll-ui-')),socket=net.createServer();await new Promise(r=>socket.listen(0,'127.0.0.1',r));const port=socket.address().port;await new Promise(r=>socket.close(r));
 const server=spawn('python3',['tests/payroll_mapping_fixture_server.py','--root',temp,'--port',String(port)],{cwd:root,stdio:['ignore','pipe','pipe']});let logs='',browser;server.stderr.on('data',b=>logs+=b);const base=`http://127.0.0.1:${port}`,errors=[],flows=[];
 try{
  for(let i=0;i<120;i++){if(server.exitCode!==null)throw Error(logs);try{if((await fetch(base+'/api/v1/health')).ok)break;}catch{}await new Promise(r=>setTimeout(r,100));}
  browser=await chromium.launch();const page=await browser.newPage({viewport:{width:1440,height:900}});page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+'/static/operator.html');await page.locator('#username').fill('plan-author');await page.locator('#password').fill('IssuePlanTest!2026');await page.locator('#loginForm button').click();await page.locator('#currentTask').waitFor();
  await page.locator('[data-scope]').filter({hasText:'方案核对甲'}).click();await page.waitForFunction(()=>!state.busy);
  await page.locator('[data-action="artifacts"]').first().click();await page.getByRole('button',{name:'AI 识别工资表格式'}).click();await page.locator('#mappingWorkbench').waitFor();await page.locator('#mappingConfirmed').waitFor();flows.push('source list → queued mapping → review');
  assert.match(await page.locator('#mappingWorkbench').innerText(),/字段对应|3500.18|原始样例/);assert.equal(await page.locator('#mappingWorkbench .primary:visible').count(),1);
  for(const [width,height] of [[1440,900],[1040,900],[390,844]]){await page.setViewportSize({width,height});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.screenshot({path:path.join(out,`mapping-${width}.png`),fullPage:true});}flows.push('1440/1040/390 layout');
  await page.setViewportSize({width:1040,height:900});await page.locator('[data-mapping-field="housing_fund"]').selectOption('');await page.locator('[data-mapping-field="employee_housing_fund"]').selectOption('F');assert.match(await page.locator('[data-sample="0-employee_housing_fund"]').innerText(),/80/);flows.push('field correction shows selected source samples');
  assert(await page.locator('#mappingConfirmed').isDisabled());await page.locator('[data-action="mapping-preview"]').click();await page.waitForFunction(()=>!state.busy);assert(await page.locator('#mappingConfirmed').isEnabled());flows.push('changed mapping requires fresh local preview');
  await page.locator('#mappingConfirmed').check();await page.locator('[data-action="mapping-apply"]').click();await page.getByText('已按确认格式提取',{exact:true}).first().waitFor();flows.push('explicit format confirmation and local extraction');
  const counts=await page.evaluate(()=>state.overview.material_review.counts);assert.equal(counts.source_verified,0);assert.equal(counts.accounting_usable,0);assert.equal(counts.records,2);assert.equal(await page.evaluate(()=>state.overview.baseline.status),'DRAFT');
  await page.reload();await page.getByText('已按确认格式提取',{exact:true}).first().waitFor();flows.push('refresh preserves status');
  await page.locator('[data-action="mapping-return"]').first().click();await page.locator('#materialWorkbench').waitFor();flows.push('return to January results');
  await page.locator('[data-scope]').filter({hasText:'方案核对乙'}).click();await page.waitForFunction(()=>!state.busy);assert.doesNotMatch(await page.locator('#workspace').innerText(),/员工秘密|自定义工资表/);flows.push('enterprise isolation');
  const posts=[];page.on('request',r=>{if(r.url().endsWith('/api/v1/commands'))posts.push(r.postDataJSON().action)});
  await page.locator('[data-action="artifacts"]').first().click();await page.locator('[data-action="mapping-open"]').first().click();await page.getByText('测试识别超时，请显式重试').waitFor();assert.equal(posts.length,0);flows.push('opening failure shows reason without another model request');
  await page.locator('[data-action="mapping-retry"]').click();await page.locator('#mappingConfirmed').waitFor();assert.deepEqual(posts,['request_payroll_mapping']);flows.push('explicit retry recovers failed mapping');
  assert.deepEqual(errors,[]);fs.writeFileSync(path.join(out,'report.json'),JSON.stringify({status:'PASS',flows,counts,errors},null,2));console.log(JSON.stringify({status:'PASS',flows,counts}));
 }finally{if(browser)await browser.close();server.kill('SIGTERM');}
})().catch(e=>{console.error(e);process.exitCode=1;});

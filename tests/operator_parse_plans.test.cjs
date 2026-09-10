const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const root=path.resolve(__dirname,'..');
const source=fs.readFileSync(path.join(root,'static/operator-parse-plans.js'),'utf8');
const main=fs.readFileSync(path.join(root,'static/operator.js'),'utf8');
const html=fs.readFileSync(path.join(root,'static/operator.html'),'utf8');
const css=fs.readFileSync(path.join(root,'static/operator.css'),'utf8');
const {chromium}=require('playwright');
const artifact={object_id:'source-1',version:2,status:'ACTIVE',data:{filename:'银行原件.xlsx',sha256:'abc',parse_options:{document_kind:'bank_statement'}}};
const proposal={schema_version:'structure-plan-v1',outcome:'PLAN',sheets:[{sheet_index:0,role:'DATA',header_row:1,fields:{transaction_date:'A',income:'B',expense:'C'},reference_rows:[]},{sheet_index:1,role:'REFERENCE',header_row:0,fields:{},reference_rows:[]}]};
const sample={artifact:{object_id:'source-1',version:2,filename:'银行原件.xlsx',sha256:'abc'},document_kind:'bank_statement',proposal,parse_plans:[],sheets:[{sheet_index:0,name:'流水原表',merged_cells:[],rows:[{row:1,values:['交易日期','收入金额','支出金额','摘要']},{row:2,values:['2026-01-02',100,0,'原始样例 <不可执行>']},{row:70,values:['合计',100,0,'尾部合计']}]},{sheet_index:1,name:'说明',merged_cells:[],rows:[{row:1,values:['此表为原件附注']}]}]};
const commandCode=main.slice(main.indexOf('async function command('),main.indexOf('async function compareBaseline('));
const requestCode=main.slice(main.indexOf('async function request('),main.indexOf('async function exclusive('));
const escapedCode=main.slice(main.indexOf('const esc ='),main.indexOf('const label ='));
const labelsCode=main.slice(main.indexOf('const kindLabels ='),main.indexOf('const esc ='));
const material=fs.readFileSync(path.join(root,'static/operator-materials.js'),'utf8');
const materialLabels=material.slice(material.indexOf('const materialFieldLabels='),material.indexOf('function materialValue('));
const boot=`
const state={epoch:1,sessionEpoch:1,role:'operator',user:{user_id:'test-user'},view:'materials',operations:new Map(),csrf:'',overview:{parse_plans:[],period:{status:'OPEN'},artifacts:[${JSON.stringify(artifact)}]}};
let scopeValue={tenant_id:'tenant',organization_id:'org',legal_entity_id:'company-a',ledger_id:'ledger',accounting_period_id:'2026-01',baseline_id:'baseline'};
const scope=()=>scopeValue,scopeKey=s=>JSON.stringify(s),$=id=>document.getElementById(id),readonly=()=>state.role==='viewer'||state.overview.period.status!=='OPEN';
const actions={},fileById=id=>state.overview.artifacts.find(a=>a.object_id===id);
function objectButton(){return '<button type="button">查看完整原件</button>';} function closeDialog(){} function clearSession(){state.epoch++;resetParsePlanState();} function loadPortfolio(){} function notify(message){document.getElementById('notice').textContent=message;}
async function loadWorkbench(){render();} function currentMaterialTask(){return {artifact_id:'source-1'};} function materialTaskIsCurrent(){return true;}
function render(){document.getElementById('workspace').innerHTML=state.view==='parse-plans'?renderParsePlans():'<button data-action="parse-plan-open" data-artifact="source-1">核对表格结构</button>';}
${escapedCode}${labelsCode}${materialLabels}${requestCode}${commandCode}
`;
async function harness(){
  const browser=await chromium.launch({headless:true}),page=await browser.newPage({viewport:{width:1440,height:900}}),calls=[],errors=[];
  let mode='ok',planVersion=1,held;
  const clone=x=>structuredClone(x);
  const model={object_id:'plan-1',version:1,status:'REVIEW',data:{artifact_id:'source-1',artifact_version:2,sha256:'abc',proposal:clone(proposal)}};
  page.on('pageerror',error=>errors.push(error.message));
  await page.route('**/*',async route=>{
    const url=new URL(route.request().url());
    if(url.pathname==='/'){await route.fulfill({contentType:'text/html',body:'<!doctype html><html lang="zh-CN"><meta name="viewport" content="width=device-width,initial-scale=1"><body><div id="notice"></div><main class="main" style="margin:auto;max-width:1200px"><div id="workspace"></div></main></body></html>'});return;}
    const body=route.request().postDataJSON();calls.push({path:url.pathname,...body});
    if(mode==='hold'){await new Promise(resolve=>held=resolve);mode='ok';}
    if(mode==='fail'){await route.fulfill({status:503,json:{error:{message:'测试网络失败，输入仍保留'}}});return;}
    if(mode==='conflict'){await route.fulfill({status:409,json:{error:{message:'原件版本已变化'}}});return;}
    if(url.pathname==='/api/v1/agent/suggestion'){
      await route.fulfill({json:{object:mode==='abstain'?{...model,status:'NEEDS_INPUT',data:{...model.data,error:'结构无法确定，请人工指认'}}:model}});return;
    }
    assert.equal(url.pathname,'/api/v1/commands','no network access outside the mocked command surface');
    let effect;
    if(body.action==='inspect_parse_plan'){
      effect=clone(sample);
      if(body.payload.row_start){const start=body.payload.row_start;effect.sheets[0].rows=[{row:start,values:start===50?['交易日期','收入金额','支出金额','摘要']:['合计',100,0,'第100行待指认']}];effect.sheets[0].total_rows=150;}
    }
    else if(body.action==='preview_parse_plan')effect={object:{...model,version:++planVersion,data:{...model.data,proposal:body.payload.proposal,preview_token:'token-'+planVersion,impact:{previous_fact_count:5,new_fact_count:1,invalidated_confirmation_count:3},preview:{records:[{original_value:{sheet:'流水原表',row:2},normalized_value:{income:'100'}}],sheets:[{sheet:'流水原表',reference_rows:[{row:1},{row:70}]}],checks:{overall:'UNATTESTED',items:[{status:'NOT_AVAILABLE',message:'原件没有独立合计依据'}]},errors:[],unresolved_rows:mode==='blocked'?[{sheet:'流水原表',row:70,reason:'合计行用途需核对'}]:[],apply_ready:mode!=='blocked'}}}};
    else if(body.action==='apply_parse_plan')effect={object:{...model,status:'APPLIED',version:++planVersion},artifact:{...artifact,version:3}};
    else throw Error('Unexpected command '+body.action);
    if(body.action==='preview_parse_plan'&&mode==='pages')effect.object.data.preview.records=Array.from({length:6},(_,i)=>({original_value:{sheet:'流水原表',row:i+2},normalized_value:{income:String(i+1)},field_sources:{income:{region:'流水原表!B'+(i+2)}}}));
    await route.fulfill({json:{command:{status:'SUCCEEDED'},effect}});
  });
  await page.goto('http://localhost/');await page.addStyleTag({content:css});
  await page.addScriptTag({content:boot+source+`;installParsePlanActions();render();document.addEventListener('click',event=>{const b=event.target.closest('button');if(b&&!b.disabled&&b.dataset.action)Promise.resolve(actions[b.dataset.action]?.(b)).catch(e=>notify(e.message));});`});
  const wait=()=>page.waitForFunction(()=>!parsePlanUI.pending);
  const open=async()=>{await page.getByRole('button',{name:'核对表格结构',exact:true}).click();await wait();};
  return {browser,page,calls,errors,open,wait,mode:value=>mode=value,release:()=>held?.()};
}
test('three source types are routed and standalone assets installed without changing materials',()=>{
  assert(html.indexOf('operator-parse-plans.js')<html.indexOf('src="operator.js'));
  assert.match(main,/state.view==='parse-plans'\)html\+=renderParsePlans\(\)/);
  assert.match(main,/installParsePlanActions\(\)/);assert.match(main,/parsePlanButton\(a\)/);
  assert.match(main,/parsePlanSupported\(artifact,kind\)/);
  assert.match(source,/bank_statement','purchase_invoices','sales_invoices/);
  assert.match(css,/\.pp-sample\{[^}]*overflow:auto/);
  assert.match(source,/表头所在行/);assert.match(source,/原件行号/);assert.match(source,/字段对应/);
});
test('specialized layouts, PDF, and payroll keep their existing parser routes',()=>{
  const context=vm.createContext({});vm.runInContext(source+';globalThis.supported=parsePlanSupported;',context);
  for(const kind of ['bank_statement','purchase_invoices','sales_invoices'])assert.equal(context.supported(artifact,kind),true);
  for(const layout of ['single_amount_bank','boc-text-v1'])assert.equal(context.supported({...artifact,data:{...artifact.data,parse_sheets:[{layout}]}}),false);
  assert.equal(context.supported({...artifact,data:{...artifact.data,filename:'中行.PDF'}}),false);
  assert.equal(context.supported(artifact,'payroll'),false);
  assert.equal(context.supported({...artifact,status:'ARCHIVED'}),false);
});
test('old workbench falls back at every entry; only an array enables the new backend',async()=>{
  for(const capability of [undefined,null,{},[],[{object_id:'plan'}]]){
    const enabled=Array.isArray(capability),calls=[],listeners={};
    const context=vm.createContext({state:{overview:{parse_plans:capability}},esc:String,actions:{'material-parse':()=>calls.push('legacy-material')},
      currentMaterialTask:()=>({artifact_id:artifact.object_id}),materialTaskIsCurrent:()=>true,fileById:()=>artifact,
      document:{addEventListener:(name,fn)=>listeners[name]=fn},openDialog:()=>calls.push('legacy-dialog'),readonly:()=>false,kindLabels:{bank_statement:'银行流水'},
      $:()=>({value:'bank_statement'}),exclusive:fn=>fn(),command:async action=>calls.push(action)});
    vm.runInContext(source+';installParsePlanActions();globalThis.entry={parsePlanButton,openParsePlan};',context);
    assert.equal(Boolean(context.entry.parsePlanButton(artifact)),enabled);
    if(!enabled){await context.entry.openParsePlan(artifact);assert.deepEqual(calls,[]);}
    vm.runInContext('openParsePlan=async()=>{globalThis.opened=true;};',context);
    await context.actions['material-parse']();assert.equal(context.opened===true,enabled);assert.equal(calls.includes('legacy-material'),!enabled);
    calls.length=0;context.opened=false;
    vm.runInContext(main.slice(main.indexOf('function openParseDialog('),main.indexOf('function uploadDialog(')),context);
    await context.openParseDialog(artifact);assert.equal(context.opened===true,enabled);assert.equal(calls.includes('legacy-dialog'),!enabled);
    calls.length=0;context.opened=false;
    vm.runInContext(main.slice(main.indexOf("document.addEventListener('submit',event=>"),main.indexOf("$('search').addEventListener")),context);
    listeners.submit({target:{id:'parseForm',dataset:{artifact:artifact.object_id}},preventDefault(){}});
    await new Promise(resolve=>setImmediate(resolve));assert.equal(context.opened===true,enabled);assert.equal(calls.includes('parse_artifact'),!enabled);
  }
  const routes=main.split('\n').filter(line=>line.includes("typeof parsePlanSupported==='function'"));
  assert.equal(routes.length,4);for(const line of routes)assert.match(line,/Array\.isArray\(state.overview\?\.parse_plans\)/);
});
test('browser: manual flow, source evidence, sheet/header/fields, preview impact explicit apply, responsive',async()=>{
  const h=await harness();try{
    await h.open();assert.equal(h.calls.length,1);assert.equal(h.calls[0].action,'inspect_parse_plan');
    assert.match(await h.page.locator('.pp-source').innerText(),/尾部合计/);
    assert.match(await h.page.locator('.pp-source').innerText(),/原始样例 <不可执行>/);
    const out=path.join(root,'output/playwright/parse-plans');fs.mkdirSync(out,{recursive:true});
    for(const width of [1440,1040,390]){await h.page.setViewportSize({width,height:900});assert(await h.page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await h.page.screenshot({path:path.join(out,`source-${width}.png`),fullPage:true});}
    await h.page.locator('[data-pp="sheet"]').selectOption('1');assert.match(await h.page.locator('.pp-source').innerText(),/此表为原件附注/);
    await h.page.locator('[data-pp="sheet"]').selectOption('0');
    await h.page.locator('[data-pp="header"]').fill('2');await h.page.locator('[data-pp="header"]').press('Tab');assert.match(await h.page.locator('.pp-feedback').innerText(),/旧预览与确认已撤销/);
    await h.page.locator('[data-pp="header"]').fill('1');await h.page.locator('[data-pp="header"]').press('Tab');
    await h.page.locator('[data-field="summary"]').selectOption('D');assert.match(await h.page.locator('[data-field="summary"]').locator('..').innerText(),/原始样例/);
    await h.page.locator('[data-pp="reference"][data-row="70"]').selectOption('TOTAL');
    await h.page.getByRole('button',{name:'检查方案并预览'}).click();await h.wait();
    assert.equal(h.calls.at(-1).target_id,'source-1');assert.equal(h.calls.at(-1).payload.document_kind,'bank_statement');
    assert.equal(await h.page.getByRole('button',{name:'明确应用方案'}).count(),0);
    assert.match(await h.page.locator('.pp-preview').innerText(),/字段名|收入|依据不足|原件没有独立合计依据/);
    assert.doesNotMatch(await h.page.locator('.pp-preview').innerText(),/normalized_value|NOT_AVAILABLE|"income"/);
    await h.page.getByRole('button',{name:'查看应用影响'}).click();assert.match(await h.page.locator('.pp-impact').innerText(),/3 项已有确认/);
    assert(await h.page.getByRole('button',{name:'明确应用方案'}).isDisabled());
    for(const width of [1440,1040,390]){await h.page.setViewportSize({width,height:900});assert(await h.page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await h.page.screenshot({path:path.join(out,`impact-${width}.png`),fullPage:true});}
    await h.page.locator('[data-pp="confirmed"]').check();await h.page.getByRole('button',{name:'明确应用方案'}).click();await h.wait();
    assert.equal(h.calls.at(-1).action,'apply_parse_plan');assert.equal(h.calls.at(-1).payload.plan_confirmed,true);assert(h.calls.at(-1).payload.preview_token);
    assert.match(await h.page.locator('#parsePlanWorkbench').innerText(),/方案已应用/);assert.equal(h.calls.filter(c=>c.path.includes('agent')).length,0);assert.deepEqual(h.errors,[]);
  }finally{await h.browser.close();}
});
test('browser: source windows locate header 50 and issue row 100 without losing the mapping',async()=>{
  const h=await harness();try{
    await h.open();await h.page.locator('[data-pp="window-start"]').fill('50');await h.page.getByRole('button',{name:'读取行范围'}).click();await h.wait();
    assert.equal(h.calls.at(-1).payload.row_start,50);assert.equal(h.calls.at(-1).payload.page_size,40);
    await h.page.locator('[data-pp="header"]').fill('50');await h.page.locator('[data-pp="header"]').press('Tab');assert.match(await h.page.locator('.pp-header-row').innerText(),/50 · 表头/);
    await h.page.locator('[data-pp="window-start"]').fill('100');await h.page.getByRole('button',{name:'读取行范围'}).click();await h.wait();
    assert.equal(await h.page.locator('[data-field="income"]').inputValue(),'B');assert.match(await h.page.locator('.pp-sample').innerText(),/第100行待指认/);
    await h.page.locator('[data-pp="reference"][data-row="100"]').selectOption('TOTAL');await h.page.getByRole('button',{name:'检查方案并预览'}).click();await h.wait();
    assert.equal(h.calls.at(-1).payload.proposal.sheets[0].header_row,50);assert.deepEqual(h.calls.at(-1).payload.proposal.sheets[0].reference_rows,[{row:100,role:'TOTAL'}]);assert.deepEqual(h.errors,[]);
  }finally{await h.browser.close();}
});
test('browser: explicit Gateway request, failure and return preserve inputs, stale consent resets',async()=>{
  const h=await harness();try{
    await h.open();await h.page.locator('[data-field="summary"]').selectOption('D');h.mode('fail');
    await h.page.getByRole('button',{name:'识别表格结构',exact:true}).click();await h.wait();assert.match(await h.page.locator('[role="alert"]').innerText(),/网络失败/);assert.equal(await h.page.locator('[data-field="summary"]').inputValue(),'D');
    const failedKey=h.calls.at(-1).idempotency_key;h.mode('abstain');await h.page.getByRole('button',{name:'识别表格结构',exact:true}).click();await h.wait();assert.equal(h.calls.at(-1).idempotency_key,failedKey);assert.equal(await h.page.locator('[data-field="summary"]').inputValue(),'D');
    await h.page.getByRole('button',{name:'暂不处理，保留输入'}).click();h.mode('ok');await h.open();assert.equal(await h.page.locator('[data-field="summary"]').inputValue(),'D');
    await h.page.getByRole('button',{name:'识别表格结构',exact:true}).click();await h.wait();assert.equal(h.calls.at(-1).stage,'STRUCTURE_PLAN');
    assert.deepEqual(Object.keys(h.calls.at(-1)).sort(),['path','stage','scope','artifact_id','artifact_version','document_kind','idempotency_key'].sort());
    await h.page.getByRole('button',{name:'检查方案并预览'}).click();await h.wait();await h.page.getByRole('button',{name:'查看应用影响'}).click();await h.page.locator('[data-pp="confirmed"]').check();
    await h.page.locator('[data-field="summary"]').selectOption('D');assert.equal(await h.page.locator('[data-pp="confirmed"]').count(),0);assert.equal(await h.page.getByRole('button',{name:'明确应用方案'}).count(),0);
    h.mode('blocked');await h.page.getByRole('button',{name:'检查方案并预览'}).click();await h.wait();assert.equal(await h.page.getByRole('button',{name:'查看应用影响'}).count(),0);assert.match(await h.page.locator('.pp-preview').innerText(),/不满足应用条件/);
    assert.deepEqual(h.errors,[]);
  }finally{await h.browser.close();}
});
test('browser: scope and source version isolate session drafts; late requests cannot reopen old view',async()=>{
  const h=await harness();try{
    await h.open();await h.page.locator('[data-field="summary"]').selectOption('D');
    await h.page.getByRole('button',{name:'暂不处理，保留输入'}).click();await h.page.evaluate(()=>{scopeValue.legal_entity_id='company-b';state.epoch++;resetParsePlanState();render();});await h.open();assert.equal(await h.page.locator('[data-field="summary"]').inputValue(),'');
    await h.page.getByRole('button',{name:'暂不处理，保留输入'}).click();await h.page.evaluate(()=>{scopeValue.legal_entity_id='company-a';state.epoch++;resetParsePlanState();render();});await h.open();assert.equal(await h.page.locator('[data-field="summary"]').inputValue(),'D');
    h.mode('hold');await h.page.getByRole('button',{name:'识别表格结构',exact:true}).click();await h.page.waitForTimeout(50);await h.page.getByRole('button',{name:'暂不处理，保留输入'}).click();h.release();await h.page.waitForTimeout(100);assert.equal(await h.page.locator('#parsePlanWorkbench').count(),0);
    h.mode('ok');await h.open();await h.page.evaluate(()=>{state.overview.artifacts[0].version++;render();});assert.match(await h.page.locator('#parsePlanWorkbench').innerText(),/原件或范围已变化/);assert(await h.page.getByRole('button',{name:'检查方案并预览'}).isDisabled());
    assert.deepEqual(h.errors,[]);
  }finally{h.release();await h.browser.close();}
});
test('browser: preview pagination, conflict retry and readonly cannot apply an obsolete plan',async()=>{
  const h=await harness();try{
    await h.open();h.mode('pages');await h.page.getByRole('button',{name:'检查方案并预览'}).click();await h.wait();
    await h.page.getByRole('button',{name:'下一组记录'}).click();assert.match(await h.page.locator('.pp-preview').innerText(),/第 7 行|流水原表!B7/);
    await h.page.getByRole('button',{name:'上一组记录'}).click();assert.match(await h.page.locator('.pp-preview').innerText(),/流水原表!B2/);
    await h.page.getByRole('button',{name:'查看应用影响'}).click();await h.page.locator('[data-pp="confirmed"]').check();h.mode('conflict');
    await h.page.getByRole('button',{name:'明确应用方案'}).click();await h.wait();assert.match(await h.page.locator('[role="alert"]').innerText(),/原件版本已变化/);
    assert.equal(await h.page.getByRole('button',{name:'明确应用方案'}).count(),0);assert.equal(await h.page.locator('[data-field="income"]').inputValue(),'B');
    h.mode('ok');await h.page.getByRole('button',{name:'重新读取原件与方案'}).click();await h.wait();
    await h.page.evaluate(()=>{state.role='viewer';render();});assert(await h.page.getByRole('button',{name:'检查方案并预览'}).isDisabled());assert(await h.page.getByRole('button',{name:'识别表格结构',exact:true}).isDisabled());
    assert.deepEqual(h.errors,[]);
  }finally{await h.browser.close();}
});

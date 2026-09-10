const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require('playwright');

const ROOT=path.resolve(__dirname,'..');
const STATIC=path.join(ROOT,'static');
const OUTPUT=path.join(ROOT,'output/playwright/task-actions');

function option(id,names){
  const labels={record_judgement:'记录专业判断',suspend:'暂停办理本事项',request_supplement:'请求补充具体材料',mark_out_of_scope:'标记本期不处理',escalate:'转交更高权限复核'};
  const fields=names.map(name=>({name,label:'受控输入 '+name,component:'textarea',required:true,slot:'',placeholder:'请填写具体事实与依据',max_length:2000,properties:[]}));
  return {id,label:labels[id],action_type_version:'action-type-v1',fallback:true,permissions:id==='escalate'?['operator','accountant']:['operator','accountant','admin'],applicability:{op:'TRUTHY',field:'fallback_eligible',value:null,children:[]},required_evidence:['当前任务绑定'],reversibility:{revocable:true,entry:'revoke_task_action'},submit_label:'',execution_type:'COMMAND',confirmation_label:labels[id],success_label:labels[id]+'已记录',post_submit_owner:id==='request_supplement'?'EXTERNAL':id==='suspend'||id==='mark_out_of_scope'?'NONE':'SYSTEM',fields,requires:['任务与原件版本仍有效'],completion:'仅保存受控处置记录',effects:[{kind:'CREATE',target:'Decision',description:'保存受控决定',grants_accounting_usable:false}],not_effects:['不修改原始文件、事实金额、正式凭证或期间状态','不授予账务可用'],available:true,unavailable_reason:'',steps:[{id:'decision',prompt:'请填写当前处置的具体事实与依据',fields:names}]};
}

test('browser: five fallback choices, command next, dialog isolation and mobile layout',async t=>{
  fs.mkdirSync(OUTPUT,{recursive:true});
  const browser=await chromium.launch({headless:true});
  t.after(()=>browser.close());
  const page=await browser.newPage({viewport:{width:1280,height:900}});
  const errors=[],requests=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.route('http://task-action.test/**',async route=>{
    const request=route.request(),url=new URL(request.url());
    if(request.method()==='GET')return route.fulfill({contentType:'text/html',body:'<!doctype html><html lang="zh-CN"><body><div id="notice" role="status"></div><main id="main"><div id="workspace"></div></main><dialog id="dialog"><div class="dialog-head"><h2 id="dialogTitle"></h2><button id="closeDialog" class="secondary">关闭</button></div><div id="dialogBody"></div></dialog></body></html>'});
    if(url.pathname==='/api/v1/commands'){
      const body=request.postDataJSON();requests.push(body);
      const object={object_id:'decision-1',version:body.action==='revoke_task_action'?2:1,status:body.action==='revoke_task_action'?'REVOKED':'CONFIRMED'};
      return route.fulfill({contentType:'application/json',body:JSON.stringify({effect:{object},next:{version:'workbench-next-step-v1',state:'COMPLETED',owner:'NONE',title:'本组已完成',explanation:'当前无需继续处理',task_id:null,action:null}})});
    }
    return route.abort();
  });
  await page.goto('http://task-action.test/');
  await page.addStyleTag({content:fs.readFileSync(path.join(STATIC,'operator.css'),'utf8')});
  await page.addScriptTag({content:`
    const selectedScope={tenant_id:'t',organization_id:'o',legal_entity_id:'e',ledger_id:'l',accounting_period_id:'2026-01',baseline_id:'b'};
    const record={object_id:'r',version:1,source_artifact_id:'a',filename:'合成长尾资料.xlsx',source_anchor:{region:'对账单!A2'},values:{custom_code:'A'},issues:['custom_code：未知业务事项'],comparison:[{field:'custom_code',source_label:'自定义业务标记',source_value:'A',value:'A',state:'DIRECT_MATCH',region:'对账单!A2'}]};
    const binding={...selectedScope,artifact:{id:'a',version:1,sha256:'hash'},records:[{id:'r',version:1,source_anchor:record.source_anchor}]};
    const task={id:'task',kind:'ISSUE',reason:'custom_code：未知业务事项',title:'未知业务事项',filename:'合成长尾资料.xlsx',artifact_id:'a',artifact_version:1,record_ids:['r'],input_token:'token',material_opinions:[],triage:{version:'issue-triage-v1',route:'HUMAN',title:'未知业务事项',explanation:'已绑定到可核验原件，但未匹配专用动作。',next_action:'请选择一种受控处置。',questions:['如何依据已有事实处置？'],checks:[]},descriptor:{version:'decision-v2',stage:'BUSINESS_REVIEW',why_now:'这一项不处理，当前记录不能进入后续业务校验。',title:'未知业务事项',why:{facts:'原件存在未识别业务标记',rule:'安全门禁通过后只允许受控处置',recommendation:'选择一种受控动作',origin:'RULE',evidence:binding.records},scope:binding,options:${JSON.stringify([
      option('record_judgement',['judgement','reason']),option('suspend',['reason']),option('request_supplement',['material','fact_to_verify']),option('mark_out_of_scope',['reason']),option('escalate',['reason'])
    ])},steps:[],fingerprint:'descriptor-fingerprint'}};
    const state={epoch:1,view:'materials',role:'accountant',user:{user_id:'actor'},overview:{artifacts:[{object_id:'a',version:1,status:'ACTIVE',data:{sha256:'hash'}}],material_review:{tasks:[task],records:[record]},bill_review:{candidates:[]},bank_accounts:{accounts:[],statements:[]}}};
    const actions={},fieldLabels={},$=id=>document.getElementById(id),scope=()=>selectedScope,scopeKey=()=>JSON.stringify(selectedScope),storage=(key,value)=>value===undefined?sessionStorage.getItem(key):sessionStorage.setItem(key,value),readonly=()=>false,esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char])),badge=value=>String(value||''),activeArtifacts=()=>state.overview.artifacts,objectButton=()=>'',fileById=id=>state.overview.artifacts.find(item=>item.object_id===id),renderProblemReviewDetail=()=>'',renderProblemSourceAudit=()=>'',renderProblemReviewChecks=()=>'';
    let busy=false;const exclusive=async fn=>{if(busy)return;busy=true;try{return await fn();}finally{busy=false;}};
    function notify(message,error=false){$('notice').textContent=message;$('notice').className=error?'error':'';}
    function openDialog(title,body){$('dialogTitle').textContent=title;$('dialogBody').innerHTML=body;$('dialog').showModal();}
    function closeDialog(){if($('dialog').open)$('dialog').close();}
    async function command(action,id,version,payload){const response=await fetch('/api/v1/commands',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({action,id,version,payload,scope:selectedScope})});return response.json();}
    async function loadWorkbench(){}
    function render(){const ui=materialState();$('workspace').innerHTML=ui.screen==='list'?'<section class="panel pad"><h2>本组已完成</h2></section>':renderDecisionTask(task);}
    $('closeDialog').addEventListener('click',closeDialog);
  `});
  const scripts=['operator-materials.js','operator-material-navigation.js','operator-bank-periods.js','operator-material-guidance.js','operator-decision.js','operator-bills.js','operator-invoice-review.js','operator-accounts.js']
    .map(file=>fs.readFileSync(path.join(STATIC,file),'utf8')).join('\n');
  await page.addScriptTag({content:scripts});
  assert.deepEqual(errors,[]);
  await page.evaluate(()=>{installMaterialActions();const ui=materialState();ui.screen='detail';ui.selected=task.id;render();});

  assert.equal(await page.locator('#workspace .primary').count(),1);
  for(const id of ['record_judgement','suspend','request_supplement','mark_out_of_scope','escalate']){
    await page.locator(`[data-guide="option"][data-option="${id}"]`).click();
    assert.equal(await page.locator('#workspace .primary').count(),1,id);
    assert.equal(await page.locator('[data-task-action-field]').count(),id==='record_judgement'||id==='request_supplement'?2:1,id);
    await page.evaluate(()=>{const draft=materialDraft(task);draft.decision.chosen=false;draft.decision.step=0;draft.decision.reviewed='';render();});
  }

  await page.locator('[data-guide="option"][data-option="record_judgement"]').click();
  await page.locator('[data-task-action-field="judgement"]').fill('保留为特殊合同判断');
  await page.locator('[data-task-action-field="reason"]').fill('已核对合同第 3 条与原件标记');
  await page.locator('[data-guide="next"]').click();
  assert.equal(await page.locator('#workspace .primary').count(),1);
  await page.locator('[data-guide="commit"]').click();
  await page.getByRole('status').filter({hasText:'本组已完成'}).waitFor();
  assert.equal(requests.length,1);
  assert.equal(requests[0].action,'execute_task_action');
  assert.equal(requests[0].payload.action_type_id,'record_judgement');
  assert.deepEqual(requests[0].payload.values,{judgement:'保留为特殊合同判断',reason:'已核对合同第 3 条与原件标记'});
  assert.doesNotMatch(JSON.stringify(requests),/\[object PointerEvent\]/);

  await page.evaluate(()=>{const ui=materialState();ui.screen='detail';task.material_opinions=[];task.handling=undefined;materialDraft(task).decision={key:decisionIdentity(task),option:'record_judgement',step:0,reviewed:'',chosen:true};render();openDialog('辅助确认','<button class="primary">弹窗主动作</button>');});
  assert.equal(await page.locator('dialog[open] .primary').count(),1);
  const background=page.locator('#main .primary');assert.equal(await background.count(),1);assert.equal(await background.evaluate(element=>getComputedStyle(element).visibility),'hidden');assert.equal(await background.evaluate(element=>getComputedStyle(element).pointerEvents),'none');
  await page.locator('#closeDialog').click();

  await page.setViewportSize({width:390,height:844});
  assert.equal(await page.locator('#workspace .primary').count(),1);
  assert.ok(await page.locator('.decision-chat').evaluate(element=>element.scrollWidth<=element.clientWidth));
  await page.screenshot({path:path.join(OUTPUT,'fallback-mobile.png'),fullPage:true});
  assert.deepEqual(errors,[]);
});

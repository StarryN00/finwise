// 进度条就是给新手看"我在整条路的哪一步"的那个东西，所以它的渲染要有东西盯着。
// 步骤的身份和顺序由服务端的 app/main_flow.py 决定，这里只测渲染口径：
// 序号只给主线、主线之外的步骤不占序号、当前步骤要标出来。
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname,'../static/operator.js'),'utf8');

const SIX = [['scope','创建企业'],['history','导入历史资料'],['source','导入当月资料'],
             ['analysis','AI 处理'],['confirmation','人工确认'],['voucher','凭证生成与复核']];

function app({current='source', statuses={}, aside=true}={}) {
  const nodes=new Map();
  const context=vm.createContext({location:{protocol:'file:'},document:{
    addEventListener(){},getElementById(id){
      if(!nodes.has(id))nodes.set(id,{addEventListener(){}});
      return nodes.get(id);
    }
  }});
  vm.runInContext(source+';globalThis.api={state,renderProgress};',context);
  const {state}=context.api;
  const scope={accounting_period_id:'2026-01'};
  state.role='accountant';state.scopes=[{scope}];state.selected=0;
  const stages=SIX.map(([id,name])=>({id,name,main_line:true,
    status:statuses[id]||'WAITING',summary:name+'的说明'}));
  if(aside)stages.push({id:'delivery',name:'交付归档',main_line:false,status:'WAITING',summary:'尚未正式交付'});
  const completed=stages.filter(s=>s.main_line&&s.status==='COMPLETED').length;
  state.overview={scope,period:{status:'OPEN'},artifacts:[],blockers:[],
    progress:{stages,current_stage:current,completed_count:completed,total_count:6,
      overall_percent:Math.floor(completed/6*100)},
    data_readiness:{baseline_sources:{balance:[],close:[]},counts:{files:0},categories:[]}};
  return context.api;
}

test('the progress bar is the six business steps, numbered one to six',()=>{
  const html=app().renderProgress();
  for(const [,name] of SIX)assert.match(html,new RegExp(name),`缺少步骤「${name}」`);
  const markers=[...html.matchAll(/<span class="stage-marker">([^<]*)<\/span>/g)].map(m=>m[1]);
  assert.deepEqual(markers,['1','2','3','4','5','6','·'],'序号只给主线六步，主线之外的不编号');
  assert.match(html,/已完成 0 \/ 6 步/);
});

test('delivery is shown but marked outside the main line',()=>{
  const html=app().renderProgress();
  assert.match(html,/stage stage-aside/);
  assert.match(html,/交付归档<span class="small muted"> · 主线之外<\/span>/);
  assert.doesNotMatch(html,/<span class="stage-marker">7<\/span>/,
    '编成第 7 步会让人以为本月还差一步没做完 —— 它在当前实现里永远 WAITING');
});

test('a month with all six done reads as finished, not stuck at the last sixth',()=>{
  const done=Object.fromEntries(SIX.map(([id])=>[id,'COMPLETED']));
  const html=app({current:'voucher',statuses:done}).renderProgress();
  assert.match(html,/已完成 6 \/ 6 步/);
  assert.match(html,/aria-valuenow="100"/,'交付归档不该把一个做完的月份压在 83%');
});

test('the current step is the only one marked current, and it can be the first two steps',()=>{
  const html=app({current:'history'}).renderProgress();
  assert.equal([...html.matchAll(/class="stage[^"]*current[^"]*"/g)].length,1);
  assert.match(html,/aria-current="step"/);
  // 标在哪一格上要具体查，不能只数个数。
  const marked=[...html.matchAll(/<(?:div|button) class="stage[^"]*"[^>]*>[\s\S]*?<\/(?:div|button)>/g)]
    .map(m=>m[0]).filter(block=>/\bcurrent\b/.test(block));
  assert.equal(marked.length,1);
  assert.match(marked[0],/导入历史资料/,'第 2 步也要能成为当前步骤 —— 新手就卡在这一格');
});

test('only the current-material step is a link into the file list',()=>{
  const html=app().renderProgress();
  assert.match(html,/id="sourceStage" data-action="artifacts" aria-label="导入当月资料：查看已上传资料清单"/,
    'aria-label 原来写死「资料接收」，步骤改名后就对不上了');
  assert.equal([...html.matchAll(/data-action="artifacts"/g)].length,2,'进度条里一个，窄屏那条按钮一个');
});

test('a projection without the aside step still renders',()=>{
  const html=app({aside:false}).renderProgress();
  assert.doesNotMatch(html,/stage-aside/);
  assert.match(html,/凭证生成与复核/);
});

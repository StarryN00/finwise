// Rendering boundaries only; financial state is never mutated by viewing originals.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname,'../static/operator.js'),'utf8');

function app(artifacts=[], baselineIds=[]) {
  const nodes=new Map();
  const context=vm.createContext({location:{protocol:'file:'},document:{
    addEventListener(){},getElementById(id){
      if(!nodes.has(id))nodes.set(id,{addEventListener(){}});
      return nodes.get(id);
    }
  }});
  vm.runInContext(source+';globalThis.api={state,renderBaseline,renderArtifactsPage};',context);
  const {state}=context.api;
  const scope={accounting_period_id:'2026-01'};
  state.role='accountant';state.scopes=[{scope}];state.selected=0;
  state.overview={scope,period:{status:'OPEN'},artifacts,progress:{current_stage:'analysis',stages:[{id:'analysis',name:'资料分析'}]},
    data_readiness:{baseline_sources:{balance:[],close:[]},counts:{files:artifacts.filter(a=>a.status!=='ARCHIVED').length},
      categories:[{id:'baseline',artifact_ids:baselineIds,file_count:baselineIds.length},{id:'unassigned',artifact_ids:artifacts.filter(a=>!baselineIds.includes(a.object_id)).map(a=>a.object_id),file_count:artifacts.length-baselineIds.length}]}};
  return context.api;
}
const history=(id,status='ACTIVE')=>({object_id:id,version:1,status,data:{filename:id+'.xls',observed_period:'2025-12',source_purpose:'historical_reference',parse_status:'RECEIVED'}});

test('received history prompts inspection, not duplicate upload or baseline approval',()=>{
  const a=app([history('journal'),history('balances')],['journal','balances']),before=JSON.stringify(a.state.overview);
  const html=a.renderBaseline();
  assert.match(html,/已接收 2 份历史 \/ 期初资料，待解析与用途核对/);
  assert.match(html,/data-action="baseline-files"/);assert.doesNotMatch(html,/data-action="upload-baseline"|data-action="confirm-baseline"|还缺 2 类/);
  assert.equal(a.state.sources.balance,'');assert.equal(a.state.sources.close,'');assert.equal(JSON.stringify(a.state.overview),before);
});
test('no sources and unrelated prior business still offer upload',()=>{
  for(const a of [app(),app([{...history('bill'),data:{observed_period:'2025-12',filename:'承兑.xls'}}])]) {
    assert.match(a.renderBaseline(),/data-action="upload-baseline"/);
    assert.doesNotMatch(a.renderBaseline(),/data-action="baseline-files"/);
  }
});
test('archived source cannot replace a missing original',()=>{
  const a=app([history('old','ARCHIVED')],['old']);
  assert.match(a.renderBaseline(),/data-action="upload-baseline"/);
});
test('one selected source does not imply the other role is available',()=>{
  const a=app([history('balance')],['balance']);a.state.sources.balance='balance';
  assert.match(a.renderBaseline(),/添加上期末余额资料/);
  a.state.sources.close='balance';
  assert.match(a.renderBaseline(),/data-action="compare-baseline"/);
  assert.doesNotMatch(a.renderBaseline(),/data-action="confirm-baseline"/);
});
test('viewer can inspect received files without writing source selection',()=>{
  const a=app([history('balance')],['balance']);a.state.role='viewer';
  const html=a.renderBaseline();
  assert.match(html,/<button class="primary" data-action="baseline-files" >查看已上传账表/);
  assert.match(html,/data-source-role="balance"[^>]*disabled/);
});
test('failed extraction and untrusted names remain explicit and escaped in list',()=>{
  const file=history('balance');file.data.filename='<script>alert(1)</script>.xls';
  file.data.parse_status='FAILED';file.data.parse_errors=['表头未识别'];
  const a=app([file],['balance']);a.state.filesFilter='baseline';
  const html=a.renderArtifactsPage();
  assert.match(html,/处理失败/);assert.match(html,/表头未识别/);
  assert.match(html,/&lt;script&gt;/);assert.doesNotMatch(html,/<script>/);
  assert.match(html,/历史账表（用途待核对）/);
});

const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const code=fs.readFileSync('static/operator-autonomous.js','utf8');
function fixture(){
 const calls=[];
 const c=vm.createContext({document:{addEventListener(){}},clearTimeout:()=>{},state:{},actions:{},readonly:()=>false,
  esc:x=>String(x).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;'),
  scope:()=>({accounting_period_id:'2026-08'}),$:()=>({value:'claude_code'}),
  request:async(url,payload)=>{calls.push({url,payload});return {run_id:'new-run'};},loadWorkbench:async()=>calls.push('refresh'),
  notify:message=>calls.push(message)});
 vm.runInContext(code,c);return {c,calls};
}
test('selector exposes actual executor labels, current model, and busy/viewer restrictions',()=>{
 const {c}=fixture();
 const w={executor:'claude_code',source_count:2,executors:[{id:'codex',label:'Codex CLI',available:false,message:'服务器凭据尚未配置'},{id:'claude_code',label:'Claude Code',model:'deepseek-v4-pro[1m]',available:true}],job:{data:{runtime:{label:'Claude Code',model:'deepseek-v4-pro[1m]'}}}};
 let html=c.renderAutonomousExecutor(w,false);
 assert.match(html,/value="claude_code" selected/);assert.match(html,/Codex CLI · 未配置/);
 assert.match(html,/Claude Code · deepseek-v4-pro\[1m\]/);assert.match(html,/本轮：Claude Code · deepseek-v4-pro\[1m\]/);assert.match(html,/切换并重新分析/);
 assert.match(c.renderAutonomousExecutor(w,true),/id="autonomousExecutor" disabled/);
 c.readonly=()=>true;assert.match(c.renderAutonomousExecutor(w,false),/data-action="autonomous-executor" disabled/);
 w.executors[1].label='<img onerror=x>';assert.doesNotMatch(c.renderAutonomousExecutor(w,false),/<img/);
});
test('switch action submits backend id, refreshes, and gives visible feedback',async()=>{
 const {c,calls}=fixture();c.installAutonomousActions();await c.actions['autonomous-executor']();
 assert.equal(calls[0].url,'/api/v1/autonomous/executor');assert.equal(calls[0].payload.backend,'claude_code');
 assert.equal(calls[1],'refresh');assert.match(calls[2],/旧结果保留/);
 assert.doesNotMatch(JSON.stringify(calls),/PointerEvent/);
});
test('a rerun shows preserved previous results without offering current confirmation',()=>{
 const {c}=fixture();c.activeArtifacts=()=>[];c.table=()=>'';
 c.state.overview={progress:{stages:[],current_stage:'analysis'},autonomous_workflow:{
  executor:'claude_code',executors:[],status:'ANALYZING',source_count:7,accepted:false,
  job:{object_id:'new-run',data:{revision:17,events:[]}},findings:[],history:[],
  ready_count:0,confirmed_count:0,pending_count:0,blocked_count:0,
  previous_result:{run_id:'old-run',revision:13,candidate_count:40,ready_count:7,pending_count:33}}};
 const html=c.renderAutonomous();
 assert.match(html,/上一轮成果已保留/);assert.match(html,/40 张凭证/);
 assert.match(html,/data-run-id="old-run"/);assert.match(html,/查看上一轮处理记录/);
 assert.match(html,/data-action="vouchers" disabled/);
});

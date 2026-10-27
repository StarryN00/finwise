const test=require('node:test'), assert=require('node:assert/strict'), vm=require('node:vm'),fs=require('node:fs');
const code=fs.readFileSync('static/operator-autonomous.js','utf8');
function setup(){
 const calls=[], listeners={}, elements={bookkeepingMode:{value:'AGENCY_SIMPLE'},bookkeepingCostRatio:{value:'90'},bookkeepingSourceNote:{value:'财务公司确认'},bookkeepingSummary:{}};
 const profile={id:'AGENCY_SIMPLE',version:1,selection_version:2,label:'简易代账',summary:'先记账',cost_ratio:'0.9',source_note:'财务公司确认'};
 const workflow={bookkeeping_profile:profile,bookkeeping_profiles:[{id:'ORIGINAL',label:'原有处理',summary:'原有规则'},{id:'AGENCY_SIMPLE',label:'简易代账',summary:'先记账'}],source_count:1};
 const c=vm.createContext({document:{addEventListener:(type,fn)=>{(listeners[type]??=[]).push(fn);}},clearTimeout:()=>{},actions:{},
 state:{overview:{autonomous_workflow:workflow}},readonly:()=>false,esc:x=>String(x).replaceAll('<','&lt;').replaceAll('"','&quot;'),
 $:id=>elements[id],scope:()=>({accounting_period_id:'2026-03'}),request:async(url,payload)=>{calls.push({url,payload});return {run_id:'new',changed:true};},
 loadWorkbench:async()=>calls.push('refresh'),notify:text=>calls.push(text)});
 vm.runInContext(code,c);return {c,calls,elements,workflow,listeners};
}
test('mode picker shows Chinese defaults, current run and correct read-only states',()=>{
 const {c,workflow}=setup();workflow.applied_bookkeeping_profile={label:'原有处理',version:1};
 const html=c.renderBookkeepingProfile(workflow,false);
 assert.match(html,/简易代账（默认）/);assert.match(html,/value="AGENCY_SIMPLE" selected/);assert.match(html,/本轮采用：原有处理/);
 assert.match(html,/本企业成本比例/);assert.match(html,/value="90"/);assert.match(c.renderBookkeepingProfile(workflow,true),/id="bookkeepingMode" disabled/);
 c.readonly=()=>true;assert.match(c.renderBookkeepingProfile(workflow,false),/data-action="bookkeeping-save" disabled/);
 workflow.applied_bookkeeping_profile={label:'原有处理'};assert.match(c.renderBookkeepingProfile(workflow,false),/本轮采用：原有处理 · 历史运行/);
 workflow.bookkeeping_profile.source_note='<img onerror=x>';assert.doesNotMatch(c.renderBookkeepingProfile(workflow,false),/<img/);
});
test('saving sends mode and version, converts percentage, refreshes and reports new run',async()=>{
 const {c,calls}=setup();c.installAutonomousActions();await c.actions['bookkeeping-save']();
 assert.equal(calls[0].url,'/api/v1/autonomous/bookkeeping-profile');assert.equal(calls[0].payload.cost_ratio,'0.9');
 assert.equal(calls[0].payload.expected_version,2);assert.equal(calls[0].payload.mode,'AGENCY_SIMPLE');
 assert.equal(calls[1],'refresh');assert.match(calls[2],/新建一轮分析/);assert.doesNotMatch(JSON.stringify(calls),/PointerEvent/);
});
test('no-op feedback and missing source or invalid percent never submit',async()=>{
 const {c,elements,calls}=setup();c.installAutonomousActions();elements.bookkeepingSourceNote.value='';
 await assert.rejects(()=>c.actions['bookkeeping-save'](),/确认来源/);assert.equal(calls.length,0);
 elements.bookkeepingCostRatio.value='100.01';await assert.rejects(()=>c.actions['bookkeeping-save'](),/100%/);
 elements.bookkeepingCostRatio.value='';c.request=async()=>({changed:false});await c.actions['bookkeeping-save']();assert.match(calls.at(-1),/选择已确认/);
});
test('selecting original disables only company ratio editing and updates explanation',()=>{
 const {listeners,elements}=setup();for(const fn of listeners.change)fn({target:{id:'bookkeepingMode',value:'ORIGINAL'}});
 assert.equal(elements.bookkeepingSummary.textContent,'原有规则');assert.equal(elements.bookkeepingCostRatio.disabled,true);
});

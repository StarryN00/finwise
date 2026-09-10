const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const root=path.join(__dirname,'../static');
function app(){
 const scope={tenant_id:'t',organization_id:'o',legal_entity_id:'e',ledger_id:'l',accounting_period_id:'2026-01',baseline_id:'b'},source={...scope,accounting_period_id:'2025-12'},calls=[],notes=[],reads=[];
 const binding={fact_id:'fact',fact_version:2,artifact_id:'file',artifact_version:3,source_anchor:{region:'流水!A2'}};
 const incoming={assignment_id:'assignment',assignment_version:1,source_scope:source,source_period:'2025-12',target_period:'2026-01',valid:true,status:'READY',intake:null,binding,filename:'<img>.xls',values:{income:0,expense:null},comparison:[{field:'income',source_value:0,value:0,state:'DIRECT_MATCH',region:'A2'}],original_issues:['<script>'],input_token:'incoming-token'};
 const outgoing={object_id:'out',version:1,status:'CONFIRMED',scope,data:{binding,target_period:'2026-02'},valid:true,handoff_status:'WAITING_PERIOD'};
 const t={id:'task',artifact_id:'file',artifact_version:3,record_ids:['r1','r2','r3','r4','r5','r6'],input_token:'token',bank_period:{record_ids:['r1','r2','r3','r4','r5','r6'],target_period:'2026-02',input_token:'token'}};
 const draft={note:'保留原因',selected:new Set()},ui={page:0},c=vm.createContext({state:{epoch:1,user:{user_id:'u'},role:'operator',overview:{scope,period:{object_id:'period',version:4},bank_periods:{incoming:[incoming],outgoing:[outgoing],counts:{}},material_review:{records:t.record_ids.map(object_id=>({object_id})),tasks:[t]}}},scope:()=>scope,scopeKey:JSON.stringify,esc:v=>String(v??'').replace(/[&<>"']/g,x=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[x])),materialCanWrite:()=>true,decisionReady:()=>true,decisionCanSubmit:()=>true,decisionOption:()=>({id:'confirm_bank_period'}),decisionEvidenceRows:()=>({rows:t.record_ids.slice(ui.page*5,ui.page*5+5).map(object_id=>({object_id}))}),currentMaterialTask:()=>t,materialDraft:()=>draft,materialState:()=>ui,materialSaveDraft(){},materialSaveNavigation(){},render(){},notify:m=>notes.push(m),actions:{},exclusive:fn=>fn(),command:async(...args)=>{calls.push(args);return {effect:args[0]==='confirm_bank_period'?{objects:args[3].record_ids.map(id=>({object_id:id,version:1,status:'CONFIRMED'}))}:{object:{object_id:'saved',version:1,status:args[0].startsWith('revoke')?'REVOKED':'ACCEPTED'}}};},loadWorkbench:async()=>reads.push('wb'),request:async(url,body)=>{reads.push(body);return {object:{object_id:body.object_id,version:body.version,data:{original_value:'SOURCE'}}};},openDialog:(title,body)=>notes.push(body),$:()=>null,materialFieldLabels:{income:'收入'},fieldLabels:{}});
 vm.runInContext(fs.readFileSync(path.join(root,'operator-bank-periods.js'),'utf8'),c);c.installBankPeriodActions();
 return {c,t,draft,ui,calls,reads,notes,incoming,outgoing,scope,button:(item,direction,action)=>({dataset:{periodId:direction==='incoming'?item.assignment_id:item.object_id,periodDirection:direction,periodToken:c.bankPeriodToken(item,direction),periodAction:action},closest:()=>({querySelector:()=>({value:'撤销原因'})})})};
}
test('period confirmation requires explicit current-page selection and preserves exact contract',async()=>{
 const a=app();await a.c.actions['bank-period-confirm']();assert.equal(a.calls.length,0);a.draft.selected.add('r2');await a.c.actions['bank-period-confirm']();assert.deepEqual(JSON.parse(JSON.stringify(a.calls[0])),['confirm_bank_period','file',3,{task_id:'task',input_token:'token',record_ids:['r2'],target_period:'2026-02',reason:'保留原因'},false]);
});
test('off-page, unknown, readonly, SYSTEM and invalid token cannot confirm',async()=>{
 for(const mode of ['page','unknown','readonly','system','token']){const a=app();a.draft.selected.add(mode==='page'?'r6':mode==='unknown'?'outside':'r1');if(mode==='readonly')a.c.materialCanWrite=()=>false;if(mode==='system')a.c.decisionReady=()=>false;if(mode==='token')a.t.bank_period.input_token='changed';await a.c.actions['bank-period-confirm']();assert.equal(a.calls.length,0,mode);}
});
test('incoming/outgoing are separate, escaped and never render financial verification',()=>{
 const a=app(),html=a.c.renderBankPeriods();assert.match(html,/跨期流水归属与接续/);assert.match(html,/等待目标期间建立/);assert.match(html,/&lt;img&gt;/);assert.match(html,/&lt;script&gt;/);assert.match(html,/>0</);assert.match(html,/未提供/);assert.doesNotMatch(html,/<script>|<img>|material-verify|账务已可用/);assert.equal(a.calls.length,0);
});
test('accept only valid READY; stale status, version and scope fail closed',async()=>{
 for(const status of ['STALE','DUPLICATE','AMBIGUOUS','ACCEPTED','ACCEPTED_ELSEWHERE','UNKNOWN']){const a=app();a.incoming.status=status;await a.c.bankPeriodAction(a.button(a.incoming,'incoming','accept'));assert.equal(a.calls.length,0,status);}
 const a=app(),b=a.button(a.incoming,'incoming','accept');a.incoming.assignment_version++;await a.c.bankPeriodAction(b);assert.equal(a.calls.length,0);
 const x=app();await x.c.bankPeriodAction(x.button(x.incoming,'incoming','accept'));assert.deepEqual(JSON.parse(JSON.stringify(x.calls[0])),['accept_bank_period','period',4,{assignment_id:'assignment',assignment_version:1,input_token:'incoming-token'},false]);
 const y=app(),old=y.button(y.incoming,'incoming','accept');y.scope.accounting_period_id='2026-03';await y.c.bankPeriodAction(old);assert.equal(y.calls.length,0);
});
test('revokes target the exact assignment/intake version; failed writes preserve input and skip reload',async()=>{
 const a=app();await a.c.bankPeriodAction(a.button(a.outgoing,'outgoing','revoke'));assert.equal(a.calls[0][0],'revoke_bank_period');assert.equal(a.calls[0][1],'out');
 const b=app();b.incoming.status='ACCEPTED';b.incoming.intake={object_id:'intake',version:7,status:'ACCEPTED'};b.c.command=async(...args)=>{b.calls.push(args);throw Error('依赖阻断');};await b.c.bankPeriodAction(b.button(b.incoming,'incoming','revoke-intake'));assert.equal(b.calls[0][1],'intake');assert.equal(b.calls[0][2],7);assert.equal(b.reads.length,0);assert.match(b.notes.at(-1),/依赖阻断/);
});
test('source lookup uses projected source scope and exact recorded version, never current-scope fallback',async()=>{
 const a=app();await a.c.bankPeriodSource(a.button(a.incoming,'incoming','source'));assert.equal(a.reads[0].scope.accounting_period_id,'2025-12');assert.equal(a.reads[0].object_id,'fact');assert.equal(a.reads[0].version,2);assert.equal(a.calls.length,0);
});

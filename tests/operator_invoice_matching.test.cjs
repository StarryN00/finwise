const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const main=fs.readFileSync('static/operator.js','utf8'),code=fs.readFileSync('static/operator-autonomous.js','utf8');
function fixture(){
 const listeners={},c=vm.createContext({scope:()=>({ledger:'test'}),readonly:()=>false,
  state:{overview:{autonomous_workflow:{job:{object_id:'run1'}}}},document:{addEventListener:(n,fn)=>{(listeners[n]??=[]).push(fn);}},
  amount:x=>Number(x).toFixed(2),badge:s=>s,fileById:()=>null});
 vm.runInContext(main.slice(main.indexOf('const esc ='),main.indexOf('const label ='))+main.slice(main.indexOf('function table('),main.indexOf('function table(')+main.slice(main.indexOf('function table(')).indexOf('\n'))+code,c);
 const invoice=(id,gross)=>({id,gross,number:id,date:'2026-08-03',source:{source_id:'s',sheet:'票据',row:2},used_by:[]});
 const item=(finding_id,party,state='CANDIDATE')=>({finding_id,party,state,payment_total:'266.00',candidate_total:'240.00',confirmed_total:'0.00',difference:null,
  candidate_invoice_ids:state==='CANDIDATE'?['i1','i2']:[],confirmed_invoice_ids:[],payments:[{date:'2026-08-03',expense:'266.00',income:'0.00',memo:'车费'}],affected_vouchers:['001'],evidence:[],reason:'找到候选票据',can_continue:'付款已确认'});
 c.state.overview.autonomous_workflow.invoice_matching={invoices:[invoice('i1','123.00'),invoice('i2','117.00'),invoice('i3','100.00')],items:[item('f1','张三'),item('f2','张三','MISSING'),item('f3','李四')]};
 vm.runInContext("autonomousFinding='f1'",c);
 return c;
}
test('candidate panel groups a person, never preselects, and never asserts a guessed difference',()=>{
 const c=fixture(),html=c.renderInvoiceMatching(c.state.overview.autonomous_workflow);
 assert.match(html,/张三 · 2 笔/);assert.match(html,/李四 · 1 笔/);assert.match(html,/没找到票据/);
 assert.match(html,/table-wrap/);assert.match(html,/开票日期 \/ 票号/);assert.match(html,/价税合计/);
 assert.match(html,/可能相关的票据/);assert.doesNotMatch(html,/ checked|多 <strong>26.00|差额是补贴|CANDIDATE/);
 assert.match(html,/data-action="autonomous-match-submit" disabled/);
 c.readonly=()=>true;assert.match(c.renderInvoiceMatching(c.state.overview.autonomous_workflow),/data-matching-finding="f1"[^>]*disabled/);
});
test('only confirmed ownership exposes a real difference; unsafe text is escaped',()=>{
 const c=fixture(),w=c.state.overview.autonomous_workflow,i=w.invoice_matching.items[0];
 Object.assign(i,{state:'AMOUNT_DIFFERENCE',candidate_invoice_ids:[],confirmed_invoice_ids:['i1','i2'],confirmed_total:'240.00',difference:'26.00',reason:'<script>bad</script>'});
 let html=c.renderInvoiceMatching(w);assert.match(html,/款项比票据多 <strong>26.00/);assert.match(html,/归属已确认/);assert.match(html,/无需重复选票/);assert.doesNotMatch(html,/<script>|data-matching-invoice="i1" data-matching-finding="f1"/);
 w.invoice_matching.invoices[0].used_by=['其他凭证'];html=c.renderInvoiceMatching(w);assert.match(html,/需核查分次付款或重复/);
});
test('submission sends only touched rows in current person and exact invoice ids',async()=>{
 const c=fixture();let payload,notice;
 c.request=async(path,body)=>{assert.equal(path,'/api/v1/autonomous/invoice-matching');payload=body;};c.loadWorkbench=async()=>{};c.notify=s=>notice=s;
 vm.runInContext("autonomousMatchingDrafts.set(matchingDraftKey('f1'),{invoice_ids:['i1','i2'],note:''});autonomousMatchingDrafts.set(matchingDraftKey('f3'),{invoice_ids:['i3'],note:'另一人'});",c);
 assert.match(c.matchingSelectionSummary(c.matchingItems()[0]),/2 张，合计 240.00/);
 await c.submitInvoiceMatching();assert.equal(payload.items.length,1);assert.equal(payload.items[0].finding_id,'f1');assert.equal(payload.acknowledged,true);assert.match(notice,/未填写的项目继续保留/);
 assert.equal(c.matchingDraft('f1').invoice_ids.length,0);assert.equal(c.matchingDraft('f3').invoice_ids.length,1);
});
test('errors retain draft and run or scope changes cannot reuse a selection',async()=>{
 const c=fixture();c.request=async()=>{throw new Error('版本变化');};
 vm.runInContext("autonomousMatchingDrafts.set(matchingDraftKey('f1'),{invoice_ids:['i1'],note:'说明'});",c);
 await assert.rejects(c.submitInvoiceMatching(),/版本变化/);assert.equal(c.matchingDraft('f1').invoice_ids.length,1);
 c.state.overview.autonomous_workflow.job.object_id='run2';assert.equal(c.matchingSubmission().length,0);
 c.state.overview.autonomous_workflow.job.object_id='run1';c.scope=()=>({ledger:'other'});assert.equal(c.matchingSubmission().length,0);
});
test('sidebar separates typed matching from other questions without text guessing',()=>{
 const c=fixture(),w=c.state.overview.autonomous_workflow;
 const html=c.matchingSidebar(w,[{id:'f1',title:'候选票据'},{id:'f2',title:'缺票'},{id:'f3',title:'车票'},{id:'tax',title:'金额已匹配但用途不清'}]);
 assert.match(html,/票款待匹配 · 3 笔/);assert.match(html,/其他记账问题 · 1 项/);assert.match(html,/data-autonomous-finding="tax"/);
});

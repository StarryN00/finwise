const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const main=fs.readFileSync('static/operator.js','utf8'),code=fs.readFileSync('static/operator-autonomous.js','utf8');
function fixture(){
 const c=vm.createContext({state:{overview:{vouchers:[],autonomous_workflow:{entry_previews:[],mode:'JOURNAL_REVIEW',ready_count:0,confirmed_count:0,pending_count:1}}},
  document:{addEventListener(){}},amount:x=>Number(x).toFixed(2),badge:(s)=>s,commandButton:()=>'<button>复核凭证</button>',fileById:()=>null,
  openDialog:(title,body)=>{c.dialog=body;}});
 vm.runInContext(main.slice(main.indexOf('const esc ='),main.indexOf('const label ='))+main.slice(main.indexOf('function table('),main.indexOf('function table(')+main.slice(main.indexOf('function table(')).indexOf('\n'))+code,c);
 const f={id:'q',title:'用途待核实',detail:'需要资料',needs_user:true};
 c.state.overview.autonomous_workflow.entry_previews=[{voucher:'候选002',assessment:{status:'NEEDS_EVIDENCE',reason:'缺用途',evidence:[]},findings:[f],entries:[{code:'1123',name:'预付款',memo:'<img onerror=alert(1)>',date:'2026-08-01',debit:'10.00',credit:'0.00'},{code:'1002',name:'银行',debit:'0.00',credit:'10.00'}]}];
 return c;
}
test('pending entries have scrollable Chinese table and preview but no confirmation action',()=>{
 const c=fixture(),html=c.renderAutonomousVoucherPage();
 assert.match(html,/table-wrap/);assert.match(html,/待补关键依据/);assert.match(html,/科目|凭证 \/ 日期/);
 assert.match(html,/data-action="autonomous-preview"/);assert.doesNotMatch(html,/<button>复核凭证/);
 assert.match(html,/原账复核/);assert.match(html,/不代表独立做账结果/);
 c.showAutonomousPreview('候选002');assert.match(c.dialog,/尚不能确认通过/);assert.match(c.dialog,/data-autonomous-finding="q"/);
 assert.doesNotMatch(c.dialog,/<img/);assert.match(c.dialog,/&lt;img/);
});
test('ready entries expose confirmation only when an admitted native voucher exists',()=>{
 const c=fixture(),p=c.state.overview.autonomous_workflow.entry_previews[0];p.assessment.status='READY_FOR_REVIEW';
 assert.doesNotMatch(c.renderAutonomousVoucherPage(),/<button>复核凭证/);
 c.state.overview.vouchers=[{status:'DRAFT',object_id:'v1',version:1,data:{voucher_number:p.voucher}}];
 assert.match(c.renderAutonomousVoucherPage(),/<button>复核凭证/);
 c.state.overview.vouchers[0].status='LOCALLY_CONFIRMED';assert.doesNotMatch(c.renderAutonomousVoucherPage(),/<button>复核凭证/);
});
test('minimal requests retain full explanation and escape source text',()=>{
 const c=fixture(),html=c.renderFindingRequest({detail:'完整说明',blocks_confirmation:false,request:{question:'<script>用途</script>',why_needed:'分类',can_continue:'已核对付款',evidence_request:'验收记录',scope:'ONBOARDING'}});
 assert.match(html,/可后续处理/);assert.match(html,/不影响已有依据的凭证复核/);assert.doesNotMatch(html,/可选调整/);assert.match(html,/补充这些就可以/);assert.match(html,/核实后供后续期间复用/);
 assert.match(html,/查看详细核对记录/);assert.doesNotMatch(html,/<script>/);
});
test('decision choices escape model text and never default to recommended option',()=>{
 const c=fixture();c.scope=()=>({period:'test'});c.readonly=()=>false;
 const f={decision:{question:'<script>事实</script>',options:[{id:'loan',label:'需要归还',kind:'BUSINESS_FACT',recommended:true,assumptions:['按约定偿还'],basis:'<img onerror=x>',effect:'影响100.00',next_step:'独立核查'}]}};
 const html=c.renderAutonomousDecision(f);
 assert.doesNotMatch(html,/<script>|<img| checked/);assert.match(html,/建议方案/);assert.match(html,/适用情况/);assert.match(html,/这样处理/);
 assert.match(html,/data-action="autonomous-decision" disabled/);
 c.readonly=()=>true;assert.match(c.renderAutonomousDecision(f),/name="reviewOption"[^>]*disabled/);
});
test('decision shows unavailable workflow boundary alongside a usable option',()=>{
 const c=fixture();c.scope=()=>({period:'test'});c.readonly=()=>false;
 const f={decision:{question:'如何处理',unavailable_reason:'重开7月不在本流程内 <script>',options:[
  {id:'current',label:'本期补记',kind:'ACCOUNTING_CHOICE',recommended:false,assumptions:['适用政策允许'],basis:'前期账未见',effect:'本期保留',next_step:'重新审查'}]}};
 const html=c.renderAutonomousDecision(f);
 assert.match(html,/本期补记/);assert.match(html,/重开7月不在本流程内/);
 assert.doesNotMatch(html,/<script>/);assert.match(html,/&lt;script&gt;/);
});
test('revised preview shows effective and preserved original lines separately',()=>{
 const c=fixture(),p=c.state.overview.autonomous_workflow.entry_previews[0];
 p.revision={reason:'按实际业务修订'};p.original_entries=p.entries.map(e=>({...e,name:'原科目'}));
 c.showAutonomousPreview(p.voucher);assert.match(c.dialog,/本轮修订方案/);assert.match(c.dialog,/查看原账分录（未改写）/);assert.match(c.dialog,/原科目/);
});
test('ledger travel policy shows current versus adopted version and escapes provenance',()=>{
 const c=fixture(),w=c.state.overview.autonomous_workflow;
 w.travel_policy={id:'p',version:2,enabled:true,summary:'企业差旅默认处理',confirmed_by:'<img>',confirmed_at:'2026-09-27',source_note:'<script>确认来源</script>'};
 w.travel_policy.rules={meal_default_account_name:'管理费用—业务招待费',gift_default_account_name:'管理费用—福利费'};
 w.applied_travel_policy={id:'p',version:1,enabled:true};
 let html=c.renderTravelPolicy(w);assert.match(html,/第 2 版/);assert.match(html,/待本轮分析采用/);
 assert.match(html,/未设置补贴自动金额限额/);assert.doesNotMatch(html,/<script>|<img>/);
 assert.match(html,/餐费 → 管理费用—业务招待费/);assert.match(html,/礼品 → 管理费用—福利费/);assert.match(html,/按实际用途调整/);
 w.applied_travel_policy.version=2;assert.match(c.renderTravelPolicy(w),/本轮已采用/);
 w.travel_policy.enabled=false;assert.match(c.renderTravelPolicy(w),/已停用/);
});
test('refresh retains an expanded policy only for the same ledger',()=>{
 const c=fixture(),w={travel_policy:{id:'p1',version:1,enabled:true}};
 c.document.querySelector=()=>({dataset:{travelPolicy:'p1'},open:true});
 assert.match(c.renderTravelPolicy(w),/ open aria-label/);
 w.travel_policy={id:'p2',version:1,enabled:true};
 assert.doesNotMatch(c.renderTravelPolicy(w),/ open aria-label/);
});
test('travel preview retains concrete manual reasons and policy version in Chinese',()=>{
 const c=fixture(),w=c.state.overview.autonomous_workflow;
 w.travel_policy_applications=[{id:'a',voucher:'候选002',policy_version:3,kind:'ALLOWANCE',reason:'差旅补贴金额待确认 <script>',manual_reasons:['ALLOWANCE','AMOUNT_GAP']}];
 c.showAutonomousPreview('候选002');
 assert.match(c.dialog,/差旅规则第 3 版/);assert.match(c.dialog,/补贴确认、票款差额/);
 assert.doesNotMatch(c.dialog,/<script>|ALLOWANCE|AMOUNT_GAP/);
});

 test('plain explanation leads with known facts and keeps evidence collapsed',()=>{
 const c=fixture();c.scope=()=>({period:'test'});c.readonly=()=>false;
 const html=c.renderAutonomousDecision({request:{can_continue:'已确认付款630元',why_needed:'决定剩余30元怎么记'},decision:{question:'剩余30元是什么费用？',options:[{id:'explain',label:'可以补充费用说明',kind:'BUSINESS_FACT',recommended:false,assumptions:['确实知道这30元的用途'],basis:'银行第8行；发票第7行',effect:'核对说明后，再处理这30元。',next_step:'重新核对并交复核'}]}});
 assert.ok(html.indexOf('已确认付款630元')<html.indexOf('剩余30元是什么费用'));
 assert.match(html,/<details><summary>查看依据和后续处理<\/summary><p>银行第8行/);
 assert.doesNotMatch(html,/<details open| checked|<dt>/);
 assert.match(html,/适用情况：确实知道这30元的用途/);
 assert.match(html,/会影响什么：决定剩余30元怎么记/);
});

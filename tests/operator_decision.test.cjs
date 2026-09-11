const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const root=path.join(__dirname,'../static');
function option(id='confirm_invoice_amount') {return {id,label:'契约主操作',fields:id==='confirm_invoice_amount'?[{name:'reason',component:'textarea',label:'契约字段',required:true,placeholder:'契约占位',max_length:321}]:[],requires:['契约前置'],completion:'契约完成条件',effects:[{kind:'CREATE',target:'Decision',description:'契约影响',grants_accounting_usable:false}],not_effects:['契约边界'],available:true,unavailable_reason:'',execution_type:['parse','supplement'].includes(id)?'NAVIGATION':'COMMAND',confirmation_label:id==='defer_material_issue'?'记录暂无法确认原因':'确认实际处理结果',success_label:'本项处理完成',post_submit_owner:id==='defer_material_issue'?'EXTERNAL':'NONE'};}
function fallbackOption(id='record_judgement'){
 const fields={record_judgement:['judgement','reason'],suspend:['reason'],request_supplement:['material','fact_to_verify'],mark_out_of_scope:['reason'],escalate:['reason']}[id].map(name=>({name,component:'textarea',label:'受控输入-'+name,required:true,placeholder:'请填写具体依据',max_length:2000}));
 return {...option(id),label:'受控动作-'+id,fallback:true,action_type_version:'action-type-v1',permissions:['operator','accountant','admin'],fields,steps:[{id:'decision',prompt:'请填写具体依据',fields:fields.map(f=>f.name)}],post_submit_owner:id==='request_supplement'?'EXTERNAL':id==='suspend'||id==='mark_out_of_scope'?'NONE':'SYSTEM'};
}
const boundScope={tenant_id:'t',organization_id:'o',legal_entity_id:'e',ledger_id:'l',accounting_period_id:'2026-03',baseline_id:'b'};
const boundRecord={id:'r',version:1,source_anchor:{region:'A1'}};
const triage=route=>({version:'issue-triage-v1',route,title:'分流标题',explanation:'分流解释',next_action:'检查原件字段映射',questions:['真实业务期间是什么？'],checks:[]});
function descriptor(o=option()){o.steps=o.steps||o.fields.map(f=>({id:f.name,prompt:'契约提问-'+f.label,fields:[f.name]}));return {version:'decision-v2',stage:'BUSINESS_REVIEW',why_now:'契约建议',title:'契约标题',why:{facts:'契约事实',rule:'契约规则',recommendation:'契约建议',origin:'RULE',evidence:[structuredClone(boundRecord)]},scope:{...boundScope,artifact:{id:'a',version:1,sha256:'hash'},records:[structuredClone(boundRecord)]},options:[o],steps:[]};}
function app(){
 const saved=new Map();const draft={note:'原草稿',reason:'原原因',taskAction:{},selected:new Set()},ui={page:0,screen:'detail'},listeners={};
 const t={id:'task',kind:'ARBITRARY_KIND',record_ids:['r'],artifact_id:'a',artifact_version:1,descriptor:descriptor()};
 const c=vm.createContext({crypto:require('node:crypto').webcrypto,queueMicrotask,notify(){},sessionStorage:{getItem:k=>saved.get(k)||null,setItem:(k,v)=>saved.set(k,v)},state:{view:'materials',role:'operator',user:{user_id:'actor'},overview:{artifacts:[{object_id:'a',version:1,data:{sha256:'hash'}}],material_review:{records:[{object_id:'r',version:1,source_anchor:{region:'A1'},values:{invoice_no:'i'}}]},bill_review:{candidates:[]},bank_accounts:{accounts:[],statements:[]}}},actions:{},fieldLabels:{amount:'金额',net_pay:'实发工资'},esc:v=>String(v??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch])),materialState:()=>ui,materialDraft:()=>draft,currentMaterialTask:()=>t,materialTaskIsCurrent:()=>true,materialCanWrite:()=>true,materialComparison:(r,s)=>s?'SELECTION':'SOURCE',materialPager:()=>'',objectButton:()=>'',materialSaveDraft(){},render(){},readonly:()=>false,scope:()=>boundScope,scopeKey:()=>'',document:{addEventListener:(event,fn)=>{(listeners[event]??=[]).push(fn);}},activeArtifacts:()=>[],badge:()=>''});
 for(const f of ['operator-decision.js','operator-bank-periods.js','operator-material-guidance.js','operator-bills.js','operator-accounts.js','operator-invoice-review.js'])vm.runInContext(fs.readFileSync(path.join(root,f),'utf8'),c);
 c.installInvoiceAmountActions();
 return {c,t,draft,ui,listeners,saved,render:()=>c.renderDecisionTask(t)};
}
test('descriptor text, field constraints and option drive card independently of kind',()=>{
 const a=app(),html=a.render();for(const text of ['契约标题','契约事实','契约规则','契约建议','契约字段','契约占位','maxlength="321"','invoiceAmountForm','materialNote','原草稿'])assert.ok(html.includes(text),text);
 a.t.kind='VERIFY';assert.equal(a.render(),html);a.c.decisionNext(a.t);for(const text of ['契约完成条件','契约影响','契约边界','确认执行内容','确认实际处理结果'])assert.ok(a.render().includes(text));a.t.descriptor.options[0].label='更改后的按钮';assert.match(a.render(),/更改后的按钮/);
});
test('unknown versions, options, fields, components and malformed contracts fail closed',()=>{
 for(const mutate of [d=>d.version='decision-v999',d=>d.options[0].effects[0].grants_accounting_usable=true,d=>d.options[0].id='eval',d=>d.options[0].fields[0].component='script',d=>d.options[0].fields[0].name='actor',d=>d.options[0].fields=[],d=>d.options=[null],d=>d.options[0].fields[0].slot='unknown']){
  const a=app();mutate(a.t.descriptor);if(a.t.descriptor.options?.[0]?.fields?.[0]?.slot==='unknown')a.t.descriptor.options[0].fields[0].component='slot';const html=a.render();assert.match(html,/任务契约暂不支持/);assert.doesNotMatch(html,/<form|type="submit"|material-supplement/);
 }
});
test('untrusted descriptor labels and draft text are escaped',()=>{
 const a=app(),payload='<img src=x onerror="alert(1)">';a.t.descriptor.title=payload;a.t.descriptor.options[0].label=payload;a.t.descriptor.options[0].fields[0].placeholder=payload;a.draft.note='</textarea><script>bad()</script>';const html=a.render();assert.doesNotMatch(html,/<img|<script>/);assert.match(html,/&lt;img/);assert.match(html,/&lt;\/textarea&gt;/);
});
test('SYSTEM retains evidence and concrete next action but no form or implicit writes',()=>{
 const a=app();a.t.triage=triage('SYSTEM');a.t.triage.title='<img onerror=bad>';const html=a.render();
 assert.match(html,/SOURCE/);assert.match(html,/检查原件字段映射/);assert.match(html,/返回问题列表/);assert.match(html,/&lt;img/);
 assert.doesNotMatch(html,/<form|data-guide="(next|commit|open|agent)"|<img/);assert.equal(a.c.decisionReady(a.t),false);
});
test('HUMAN triage title and explanation override presentation without replacing original form',()=>{
 const a=app();a.t.triage=triage('HUMAN');const html=a.render();assert.match(html,/分流标题/);assert.match(html,/分流解释/);assert.match(html,/invoiceAmountForm/);assert.match(html,/真实业务期间是什么/);
 a.t.triage.version='unknown';assert.doesNotMatch(a.render(),/<form/);
});
test('bank period slot requires explicit page records and original summary before any command',()=>{
 const a=app(),o=option('confirm_bank_period');o.fields=[{name:'records',label:'选择归属流水',component:'slot',slot:'period_record_selection',required:true,properties:[]},{name:'reason',label:'归属原因',component:'textarea',required:false,placeholder:'',max_length:2000}];a.t.descriptor=descriptor(o);a.t.input_token='pt';a.t.bank_period={target_period:'2026-02',record_ids:['r'],input_token:'pt'};
 assert.doesNotMatch(a.render(),/bankPeriodForm/);a.c.decisionChoose(a.t,'confirm_bank_period');assert.match(a.render(),/bankPeriodForm/);assert.match(a.render(),/目标期间/);assert.doesNotMatch(a.render(),/data-material-record="r" checked/);a.c.decisionNext(a.t);assert.equal(a.c.decisionGuide(a.t).step,0);
 a.draft.selected.add('r');a.c.decisionNext(a.t);assert.equal(a.c.decisionCanSubmit(a.t),false);a.c.decisionNext(a.t);assert.equal(a.c.decisionCanSubmit(a.t),true);a.t.bank_period.input_token='changed';assert.equal(a.c.decisionCanSubmit(a.t),false);
});
test('defer and resume share the skeleton and preserve original records',()=>{
 const a=app(),o=option('defer_material_issue');o.confirmation_label='记录原因并继续';o.fields=[{name:'reason',label:'契约暂缓原因',component:'textarea',required:true,max_length:2000,placeholder:''}];o.steps=[{id:'reason',prompt:'暂缓提问',fields:['reason']}];a.t.descriptor.options.push(o);a.c.decisionChoose(a.t,o.id);assert.match(a.render(),/materialDeferForm/);assert.match(a.render(),/materialReason/);a.c.decisionNext(a.t);assert.match(a.render(),/记录原因并继续/);
 a.c.decisionChoose(a.t,'confirm_invoice_amount');a.draft.resume=false;a.t.deferred=true;a.t.response={data:{reason:'保留的原因',actor:'actor'}};assert.match(a.render(),/data-guide="resume"/);a.draft.resume=true;assert.match(a.render(),/invoiceAmountForm/);assert.match(a.render(),/保留的原因/);
});

test('unavailable options show reason and disable main write',()=>{const a=app();a.t.descriptor.options[0].available=false;a.t.descriptor.options[0].unavailable_reason='先核对依据';assert.match(a.render(),/先核对依据/);assert.match(a.render(),/data-guide="next" disabled/);});
test('origin is Chinese; all page keys visible and only one record comparison expanded',()=>{const a=app();a.t.record_ids=['r','r2','r3'];a.c.state.overview.material_review.records.push({object_id:'r2'},{object_id:'r3'});a.t.descriptor.scope.records.push({id:'r2',source_anchor:null},{id:'r3',source_anchor:null});a.t.descriptor.why.evidence=structuredClone(a.t.descriptor.scope.records);const html=a.render();assert.match(html,/系统规则/);assert.doesNotMatch(html,/来源：RULE/);assert.equal((html.match(/data-guide="record"/g)||[]).length,3);assert.equal((html.match(/SOURCE/g)||[]).length,1);assert.match(html,/class="decision-source" open/);});
test('bill properties supply labels, help, choices and keep original DOM IDs',()=>{
 const a=app();const names=['business_kind','business_period','original_receipt_period','business_date','search','account_candidate_id','account_name','account_code','reason','evidence_ids'];const field={name:'business',label:'字段槽',component:'slot',slot:'bill_business',required:true,properties:names.map(name=>({name,label:'来自契约-'+name,required:name==='business_kind',help:'帮助-'+name,placeholder:'占位-'+name,choices:name==='business_kind'?{HELD:'契约持有名称'}:{}}))};const o=option('confirm_bill_business');o.fields=[field];a.t.descriptor=descriptor(o);const html=a.render();assert.match(html,/billForm/);assert.match(html,/billKind/);assert.match(html,/来自契约-business_kind/);assert.match(html,/契约持有名称/);assert.match(html,/帮助-business_kind/);assert.doesNotMatch(html,/本期收到/);
 field.properties[0].choices.INJECT='bad';assert.match(a.render(),/任务契约暂不支持/);
});
test('bank slot uses property descriptions while accounts form stays standalone',()=>{
 const a=app(),names=['account_id','bank_name','account_number','holder','currency','confirmed'];a.c.state.overview.bank_accounts.statements=[{artifact_id:'a',artifact_version:1,identity:{},token:'token',status:'MISSING'}];const o=option('confirm_statement_account');o.fields=[{name:'ownership',label:'银行槽',component:'slot',slot:'bank_ownership',required:true,properties:names.map(name=>({name,label:'契约-'+name,required:name==='confirmed',help:'帮助-'+name,placeholder:'占位-'+name,choices:{}}))}];a.t.descriptor=descriptor(o);const html=a.render();assert.match(html,/bankAccountForm/);assert.match(html,/契约-bank_name/);assert.match(html,/占位-bank_name/);assert.match(html,/帮助-bank_name/);assert.equal((html.match(/<form/g)||[]).length,1);const standalone=a.c.bankForm(null);assert.match(standalone,/bankAccountForm/);assert.match(standalone,/保存银行/);assert.match(standalone,/accounts-cancel/);
});

test('scope, hash, record version and source mismatches fail closed',()=>{for(const change of [d=>d.scope.tenant_id='other',d=>d.scope.accounting_period_id='2026-04',d=>d.scope.artifact.version=2,d=>d.scope.artifact.sha256='other',d=>d.scope.records[0].version=2,d=>d.scope.records[0].source_anchor.region='B1',d=>d.why.evidence=[]]){const a=app();change(a.t.descriptor);assert.match(a.render(),/依据已变化/);assert.doesNotMatch(a.render(),/<form/);}});
test('summary is required, edits invalidate consent, and version changes reset steps',()=>{
 const a=app();assert.equal(a.c.decisionCanSubmit(a.t),false);a.c.decisionNext(a.t);assert.equal(a.c.decisionCanSubmit(a.t),true);a.draft.note='修改后的依据';assert.equal(a.c.decisionCanSubmit(a.t),false);a.render();assert.equal(a.c.decisionGuide(a.t).step,0);a.c.decisionNext(a.t);a.t.input_token='new-version';assert.equal(a.c.decisionCanSubmit(a.t),false);assert.equal(a.c.decisionGuide(a.t).step,0);
});
test('server step prompts and field groups drive order; missing or duplicated fields fail closed',()=>{
 const a=app(),o=option('verify_source_values');o.fields=[{name:'records',label:'逐条核实',component:'slot',slot:'record_selection',required:true,properties:[]},{name:'note',label:'备注',component:'textarea',required:false,placeholder:'',max_length:2000}];o.steps=[{id:'one',prompt:'服务端第一问',fields:['records']},{id:'two',prompt:'服务端第二问',fields:['note']}];a.t.descriptor=descriptor(o);let html=a.render();assert.match(html,/服务端第一问/);assert.match(html,/data-guide-step="1" hidden disabled/);assert.equal(a.c.decisionSteps(a.t,o)[1].title,'服务端第二问');o.steps[1].fields=['records'];assert.match(a.render(),/任务契约暂不支持/);
});
test('submit and Enter cannot dispatch before explicit summary commit',()=>{
 const a=app();let dispatched=0,stopped=0;const card={querySelector:()=>form};const form={closest:()=>card,querySelector:()=>null,requestSubmit(){const event={type:'submit',target:form,preventDefault(){stopped++;},stopImmediatePropagation(){}};a.c.decisionCapture(event);if(!stopped)dispatched++;}};
 const ev=()=>({type:'submit',target:form,preventDefault(){stopped++;},stopImmediatePropagation(){}});a.c.decisionCapture(ev());assert.equal(dispatched,0);assert.equal(stopped,1);a.c.decisionCapture(ev());assert.equal(dispatched,0);stopped=0;a.c.decisionCommit(a.t,form);assert.equal(dispatched,1);
 const b=app(),target={tagName:'INPUT',dataset:{},closest:s=>s==='form'?form:card};b.c.decisionCapture({type:'keydown',key:'Enter',target,preventDefault(){},stopImmediatePropagation(){}});assert.equal(b.c.decisionGuide(b.t).step,1);assert.equal(dispatched,1);
});
test('zero-field options never create consent; explicit entry opens existing dialogs only',()=>{
 for(const id of ['parse','supplement']){const a=app();a.t.descriptor=descriptor(option(id));let writes=0,opened=0;a.c.actions['material-parse']=()=>writes++;a.c.actions['material-supplement']=()=>opened++;a.c.fileById=()=>({});a.c.openParseDialog=()=>opened++;
 const html=a.render();assert.doesNotMatch(html,/decision-summary|data-guide="commit"/);assert.match(html,/data-guide="open"/);assert.equal(a.c.decisionGuide(a.t).reviewed,'');a.c.decisionCommit(a.t);assert.equal(writes,0);assert.equal(opened,0);a.c.decisionOpen(a.t);assert.equal(opened,1);assert.equal(writes,0);assert.equal(a.c.decisionCanSubmit(a.t),false);}
});
test('source evidence precedes actions and presentation uses only bound record fields',()=>{
 const a=app(),r=a.c.state.overview.material_review.records[0];r.comparison=[{field:'invoice_status',source_value:'已红冲-全额',value:'已红冲-全额',state:'DIRECT_MATCH',region:'表!O14'}];
 a.t.descriptor.presentation={type_label:'发票状态核对',explanation:'原件状态为“已红冲-全额”，不是读取错误。',records:[{id:'r',focus_fields:['invoice_status']}]};
 const html=a.render();assert.match(html,/已红冲-全额/);assert.match(html,/表!O14/);assert(html.indexOf('decision-evidence')<html.indexOf('<form'));assert.doesNotMatch(html,/责任人：|确认提交摘要/);
 a.t.descriptor.presentation.records[0].id='outside';assert.equal(a.c.decisionPresentation(a.t),null);
});
test('common amount field uses a business label instead of a generic source placeholder',()=>{
 const a=app(),r=a.c.state.overview.material_review.records[0];r.comparison=[{field:'amount',source_value:'9352.00',value:'9352.00',state:'DIRECT_MATCH',region:'表!R2'}];
 a.t.descriptor.presentation={type_label:'核对电子承兑明细读取结果',explanation:'请核对金额是否与原件一致。',records:[{id:'r',focus_fields:['amount']}]};
 const html=a.render();assert.match(html,/金额：9352\.00/);assert.doesNotMatch(html,/来源字段：9352\.00/);
});
test('all verification focus fields have stable business labels in the workbench',()=>{
 const source=fs.readFileSync(path.join(root,'operator-materials.js'),'utf8');
 const expected={net_pay:'实发工资',income:'收入金额',expense:'支出金额',employer_amount:'单位缴费金额',employee_amount:'个人缴费金额',account:'个人公积金账号',account_code:'科目编码',account_name:'科目名称',opening_debit:'期初借方余额',opening_credit:'期初贷方余额',contract_no:'合同编号',contract_date:'合同日期',supplier:'供应商',stock_in_no:'入库单号',stock_in_date:'入库日期'};
 for(const [field,label] of Object.entries(expected))assert.match(source,new RegExp(`${field}:'${label}'`),`${field} should display as ${label}`);
 const a=app(),r=a.c.state.overview.material_review.records[0];r.comparison=[{field:'net_pay',source_value:'5000.00',value:'5000.00',state:'DIRECT_MATCH',region:'表!R2'}];
 a.t.descriptor.presentation={type_label:'核对工资明细读取结果',explanation:'请核对实发工资是否与原件一致。',records:[{id:'r',focus_fields:['net_pay']}]};
 assert.match(a.render(),/实发工资：5000\.00/);
});
test('verification evidence renders only the actual server-declared comparison fields',()=>{
 const a=app(),r=a.c.state.overview.material_review.records[0];
 r.values={person_name:null,person_id:'P-1',period_ref:'2026-01',employer_amount:'800.00',employee_amount:'400.00'};
 r.comparison=[{field:'person_id',source_value:'P-1',value:'P-1',state:'DIRECT_MATCH',region:'表!A2'}];
 a.c.fieldLabels.person_id='个人编号';
 a.t.descriptor.presentation={type_label:'核对社保明细读取结果',explanation:'请核对个人编号是否与原件一致。',records:[{id:'r',focus_fields:['person_id']}]};
 const html=a.render();assert.match(html,/个人编号：P-1/);assert.doesNotMatch(html,/姓名：/);
});
test('old descriptor can locate translated issue labels without inventing a new explanation',()=>{
 const a=app(),r=a.c.state.overview.material_review.records[0];r.issues=['发票状态：须人工核对'];r.comparison=[{field:'invoice_status',source_label:'发票状态',source_value:'已红冲-全额',state:'DIRECT_MATCH'}];
 const html=a.render();assert.match(html,/已红冲-全额/);assert.match(html,/当前尚未提供具体问题解释/);assert.doesNotMatch(html,/确认提交摘要/);
});
test('verification uses compact current-page choices instead of duplicating full comparisons',()=>{
 const a=app(),o=option('verify_source_values');o.fields=[{name:'records',label:'逐条核实',component:'slot',slot:'record_selection',required:true,properties:[]},{name:'note',label:'备注',component:'textarea',required:false,placeholder:'',max_length:2000}];a.t.descriptor=descriptor(o);
 for(let i=2;i<=7;i++){const id='r'+i;a.t.record_ids.push(id);a.c.state.overview.material_review.records.push({object_id:id,version:1,values:{invoice_no:'INV-'+i},source_anchor:{region:'A'+i}});a.t.descriptor.scope.records.push({id,version:1,source_anchor:{region:'A'+i}});}
 a.t.descriptor.why.evidence=structuredClone(a.t.descriptor.scope.records);let html=a.render();assert.equal((html.match(/data-material-record=/g)||[]).length,5);assert.equal((html.match(/SOURCE/g)||[]).length,1);assert.match(html,/decision-selection/);assert.equal(a.draft.selected.size,0);
 a.draft.selected.add('r');a.ui.page=1;html=a.render();assert.equal((html.match(/data-material-record=/g)||[]).length,2);assert.equal(a.draft.selected.size,0);assert.doesNotMatch(html,/data-material-record="r"/);assert.equal(a.c.decisionCanSubmit(a.t),false);
});
test('guide option clicks select the requested option and source buttons are not intercepted',()=>{
 const a=app(),o=option('defer_material_issue');o.fields=[{name:'reason',component:'textarea',label:'原因',required:true,placeholder:'',max_length:2000}];o.steps=[{id:'reason',prompt:'为什么暂缓',fields:['reason']}];a.t.descriptor.options.push(o);const card={querySelector:()=>null};let stopped=0;const event=b=>({type:'click',target:{closest:s=>s==='.decision-chat'?card:b},preventDefault(){stopped++;},stopImmediatePropagation(){}});a.c.decisionCapture(event({dataset:{guide:'option',option:'defer_material_issue'}}));assert.equal(a.c.decisionOption(a.t).id,'defer_material_issue');assert.equal(stopped,1);a.c.decisionCapture(event({dataset:{object:'r'}}));assert.equal(stopped,1);assert.equal(a.c.decisionGuide(a.t).step,0);
});
test('progress is restored only within the same scoped input version',()=>{
 const a=app();a.c.decisionNext(a.t);delete a.draft.decision;assert.equal(a.c.decisionGuide(a.t).step,1);a.t.input_token='replacement';delete a.draft.decision;assert.equal(a.c.decisionGuide(a.t).step,0);assert.equal(a.draft.note,'原草稿');
});
test('Agent is manual, retries reuse request id, reanalysis creates a new one and never prefills',async()=>{
 const a=app();a.t.descriptor.fingerprint='fp';const calls=[];let fail=true;a.c.api=async(path,body)=>{calls.push({path,body});if(fail){fail=false;throw Error('network');}return {status:'PROPOSED',descriptor_hash:'fp',suggestion:{option_id:'confirm_invoice_amount',reason:'建议核对',uncertainties:['待确认'],prefill:{}}};};a.render();assert.equal(calls.length,0);await a.c.decisionAskAgent(a.t);assert.equal(a.draft.note,'原草稿');await a.c.decisionAskAgent(a.t);assert.equal(calls[0].body.request_id,calls[1].body.request_id);await a.c.decisionAskAgent(a.t,true);assert.notEqual(calls[1].body.request_id,calls[2].body.request_id);assert.equal(calls[0].path,'/agent/suggestion');assert.equal(calls[0].body.stage,'MATERIAL_GUIDANCE');assert.equal(a.draft.note,'原草稿');assert.equal(a.c.decisionGuide(a.t).step,0);
});
test('Agent RUNNING keeps request id and stale task/hash responses are discarded',async()=>{
 const a=app();a.t.descriptor.fingerprint='fp';a.c.api=async()=>({status:'RUNNING',descriptor_hash:'fp'});await a.c.decisionAskAgent(a.t);const id=a.draft.decision.agent.request_id;await a.c.decisionAskAgent(a.t);assert.equal(a.draft.decision.agent.request_id,id);assert.match(a.render(),/检查分析结果/);
 a.c.api=async()=>({status:'FAILED',descriptor_hash:'wrong',message:'stale'});await a.c.decisionAskAgent(a.t,true);assert.equal(a.draft.decision.agent.response,undefined);
 let resolve;a.c.api=()=>new Promise(r=>resolve=r);const pending=a.c.decisionAskAgent(a.t,true);a.c.currentMaterialTask=()=>({...a.t,id:'other'});resolve({status:'PROPOSED',descriptor_hash:'fp',suggestion:{option_id:null,reason:'late',uncertainties:[],prefill:{}}});await pending;assert.equal(a.draft.decision.agent.response,undefined);
});
test('suggestion cards do not select by default, show original effects and only choose an existing option explicitly',()=>{
 const a=app();a.t.descriptor.fingerprint='fp';const g=a.c.decisionGuide(a.t);g.agent={response:{status:'PROPOSED',descriptor_hash:'fp',suggestion:{option_id:'confirm_invoice_amount',reason:'核对原件 <img>',uncertainties:['仍需业务判断'],prefill:{}}}};
 const before=JSON.stringify(a.draft),html=a.c.decisionSuggestionCards(a.t,[g.agent.response.suggestion]);
 assert.match(html,/aria-selected="false"/);assert.match(html,/选择后/);assert.match(html,/不会改变/);assert.match(html,/&lt;img&gt;/);assert.doesNotMatch(html,/<img>|选择此建议|已选择此建议/);assert.equal(JSON.stringify(a.draft),before);
 a.c.decisionUseSuggestion(a.t,'confirm_invoice_amount');assert.equal(g.agent.selected,'confirm_invoice_amount');assert.equal(g.step,0);assert.equal(g.reviewed,'');assert.equal(a.draft.note,'原草稿');assert.equal(a.c.decisionCanSubmit(a.t),false);
 assert.match(a.c.decisionSuggestionCards(a.t,[g.agent.response.suggestion]),/aria-selected="true"/);
});
test('suggestion cards cap at three and never enable unknown, unavailable, readonly, SYSTEM or stale choices',()=>{
 const a=app();a.t.descriptor.fingerprint='fp';const s={option_id:'confirm_invoice_amount',reason:'建议',uncertainties:[],prefill:{}};
 const html=a.c.decisionSuggestionCards(a.t,[s,{...s,option_id:'unknown'}]);assert.equal((html.match(/data-guide="legacy-suggestion-card"/g)||[]).length,1);
 const many=app();many.t.descriptor.options=Array.from({length:4},(_,i)=>({...option(),id:'local-'+i}));many.c.decisionReady=()=>false;
 const capped=many.c.decisionSuggestionCards(many.t,many.t.descriptor.options.map(o=>({...s,option_id:o.id})));assert.equal((capped.match(/data-guide="legacy-suggestion-card"/g)||[]).length,3);assert.doesNotMatch(capped,/data-option="local-3"/);
 for(const mode of ['readonly','system','stale','unavailable']){
  const b=app();b.t.descriptor.fingerprint='fp';const g=b.c.decisionGuide(b.t);g.agent={response:{status:'PROPOSED',descriptor_hash:mode==='stale'?'old':'fp',suggestion:s}};
  if(mode==='readonly')b.c.materialCanWrite=()=>false;if(mode==='system')b.t.triage=triage('SYSTEM');if(mode==='unavailable')b.t.descriptor.options[0].available=false;
  b.c.decisionUseSuggestion(b.t,s.option_id);assert.equal(g.agent.selected,undefined,mode);assert.equal(b.draft.note,'原草稿');assert.equal(g.reviewed,'');
 }
});
test('v2 automatic and personal cards are separate, unselected, bound and never prefill fields',async()=>{
 const a=app();a.t.descriptor.fingerprint='fp';const candidate={option_id:'confirm_invoice_amount',reason:'建议核对',uncertainties:[],prefill:{},confidence:.9,evidence_refs:['record-1'],steps:[{option_id:'confirm_invoice_amount',instruction:'核对原件'}]};
 a.t.material_guidance={status:'PROPOSED',valid:true,job_id:'auto',job_version:2,descriptor_hash:'fp',candidates:[candidate]};a.t.personal_material_guidance={...a.t.material_guidance,job_id:'personal'};
 const html=a.render();assert.match(html,/自动处理建议/);assert.match(html,/我的方案验证/);assert.doesNotMatch(html,/<form|aria-pressed="true"[^>]*>契约主操作/);a.c.decisionNext(a.t);assert.equal(a.c.decisionGuide(a.t).step,0);
 const token=a.c.materialGuidanceToken(a.t,'auto');assert.equal((a.render().match(/data-guide="suggestion-select"/g)||[]).length,0);a.c.materialGuidanceChoose(a.t,'auto',0,token);assert.match(a.render(),/invoiceAmountForm/);assert.doesNotMatch(a.render(),/提交处理建议/);assert.equal(a.draft.note,'原草稿');assert.equal(a.c.decisionCanSubmit(a.t),false);
 a.t.material_guidance.candidates[0].prefill={reason:'invented'};assert.equal(a.c.materialGuidanceCandidates(a.t,a.t.material_guidance).length,0);
});
test('free scheme sends only explicit user_text; same-text retry idempotent, save opinion never requests model',async()=>{
 const a=app();a.t.material_opinions=[];a.t.descriptor.fingerprint='fp';const calls=[];a.c.request=async(url,body)=>{calls.push([url,body]);throw Error('offline');};a.c.command=async(...args)=>{calls.push(args);return {effect:{status:'WAITING_SYSTEM',object:{object_id:'opinion',status:'SAVED_NOT_EXECUTED'},job:{object_id:'job',status:'QUEUED'}}};};a.c.loadWorkbench=async()=>{};
 const g=a.c.decisionGuide(a.t);g.custom={text:'本人方案，尚未执行'};a.render();assert.equal(calls.length,0);await a.c.materialGuidanceCustom(a.t);await a.c.materialGuidanceCustom(a.t);assert.equal(calls[0][1].request_id,calls[1][1].request_id);assert.equal(calls[0][1].user_text,'本人方案，尚未执行');assert.equal(calls[0][1].stage,'MATERIAL_GUIDANCE');assert.equal(a.draft.note,'原草稿');
 await a.c.materialGuidanceSaveOpinion(a.t);assert.deepEqual(JSON.parse(JSON.stringify(calls[2])),['save_material_opinion','a',1,{task_id:'task',descriptor_hash:'fp',reason:'本人方案，尚未执行'},false]);
});
test('direct FAILED retry gets a new request id, unlike uncertain network retry; empty candidate steps are valid',async()=>{
 const a=app();a.t.material_opinions=[];a.t.descriptor.fingerprint='fp';const ids=[];a.c.decisionGuide(a.t).custom={text:'方案'};a.c.request=async(url,body)=>{ids.push(body.request_id);return {status:'FAILED',descriptor_hash:'fp',message:'已终止'};};await a.c.materialGuidanceCustom(a.t);await a.c.materialGuidanceCustom(a.t);assert.notEqual(ids[0],ids[1]);
 const candidate={option_id:'confirm_invoice_amount',reason:'合法无步骤',uncertainties:[],prefill:{},confidence:.9,evidence_refs:['record-1'],steps:[]};const response={status:'PROPOSED',descriptor_hash:'fp',candidates:[candidate]};assert.equal(a.c.materialGuidanceCandidates(a.t,response).length,1);a.t.material_guidance=response;const html=a.render();assert.match(html,/推荐/);assert.match(html,/整理为处理方案/);assert.doesNotMatch(html,/<form/);
});
test('multi-step advice grants only its chosen action; changing choice removes stale followup',()=>{
 const a=app(),entry={};a.c.materialDetailEntry=()=>entry;a.t.descriptor.fingerprint='fp';
 const defer=option('defer_material_issue');defer.fields=[{name:'reason',component:'textarea',label:'原因',required:true,placeholder:'',max_length:2000}];defer.steps=[{id:'reason',prompt:'填写原因',fields:['reason']}];a.t.descriptor.options.push(defer);
 const candidate={option_id:'confirm_invoice_amount',reason:'先核对再处理',uncertainties:[],prefill:{},confidence:.9,evidence_refs:['record-1'],steps:[{option_id:'confirm_invoice_amount',instruction:'核对金额'},{option_id:'defer_material_issue',instruction:'若证据仍不足再记录'}]};
 a.t.material_guidance={status:'PROPOSED',descriptor_hash:'fp',candidates:[candidate]};
 a.c.materialGuidanceChoose(a.t,'auto',0,a.c.materialGuidanceToken(a.t,'auto'));
 assert.equal(a.c.decisionCanSubmit(a.t),false);assert.equal(entry.suggestionPlan.recorded,false);assert.equal(entry.suggestionPlan.pending.length,1);
 const c=vm.createContext({esc:v=>String(v)});vm.runInContext(fs.readFileSync(path.join(root,'operator-material-navigation.js'),'utf8'),c);
 assert.equal(c.materialPlanFollowup(entry),'');entry.suggestionPlan.recorded=true;
 assert.match(c.materialPlanFollowup(entry),/整份建议未执行完成/);assert.match(c.materialPlanFollowup(entry),/未执行/);
 a.c.decisionChoose(a.t,'defer_material_issue');assert.equal(entry.suggestionPlan,undefined);assert.equal(a.c.decisionGuide(a.t).suggestionChoice,undefined);assert.equal(a.c.decisionCanSubmit(a.t),false);
});
test('multiple low-confidence unmapped explanations remain distinct and selectable without financial execution',()=>{
 const a=app();a.t.descriptor.fingerprint='fp';const c={option_id:null,reason:'证据仍需用户判断',uncertainties:['日期意义尚待确认'],prefill:{},confidence:.6,evidence_refs:['record-1'],steps:[]};
 a.t.material_guidance={status:'NEEDS_HUMAN',descriptor_hash:'fp',candidates:[c,{...c,reason:'另一种处理尚待判断'}]};
 assert.equal(a.c.materialGuidanceCandidates(a.t,a.t.material_guidance).length,2);
 const html=a.c.renderMaterialGuidanceChannel(a.t,'auto');assert.match(html,/证据仍需用户判断/);assert.match(html,/另一种处理尚待判断/);assert.equal((html.match(/data-guide="suggestion-select"/g)||[]).length,0);assert.match(html,/建议方案 1/);assert.match(html,/建议方案 2/);assert.doesNotMatch(html,/选择此建议|已选择此建议|data-guide="suggestion-submit"/);a.c.materialGuidanceChoose(a.t,'auto',0,a.c.materialGuidanceToken(a.t,'auto'));assert.match(a.c.renderMaterialGuidanceChannel(a.t,'auto'),/is-selected/);
});
test('unmapped suggestion can be explicitly submitted as an opinion only',async()=>{
 const a=app();a.t.descriptor.fingerprint='fp';a.t.material_opinions=[];a.t.material_guidance={status:'NEEDS_HUMAN',descriptor_hash:'fp',candidates:[{option_id:null,reason:'建议将流水按原交易日期归属二月',uncertainties:['目标期间尚待确认'],prefill:{},confidence:.6,evidence_refs:['record-1'],steps:[]}]};const calls=[];a.c.command=async(...args)=>{calls.push(args);return {effect:{status:'WAITING_SYSTEM',object:{status:'SAVED_NOT_EXECUTED'},job:{object_id:'job',status:'QUEUED'}}};};a.c.loadWorkbench=async()=>{};const token=a.c.materialGuidanceToken(a.t,'auto');a.c.materialGuidanceChoose(a.t,'auto',0,token);assert.match(a.c.renderMaterialGuidanceChannel(a.t,'auto'),/记录意见并交系统处理/);await a.c.materialGuidanceSubmit(a.t,'auto',0,token);assert.equal(calls.length,1);assert.equal(calls[0][0],'save_material_opinion');assert.match(calls[0][3].reason,/确认业务期间归属/);assert.match(calls[0][3].reason,/尚未映射为可执行操作/);assert.equal(a.c.decisionGuide(a.t).suggestionChoice.submitted,true);assert.equal(a.c.decisionGuide(a.t).option,'confirm_invoice_amount');
 const html=a.render();assert.match(html,/意见已记录，系统正在整理/);assert.match(html,/返回问题列表/);assert.match(html,/没有需要你继续确认/);assert.doesNotMatch(html,/请选择处理方式/);assert.doesNotMatch(html,/data-guide="suggestion-submit"/);
 const cards=a.c.renderMaterialGuidanceChannel(a.t,'auto');assert.match(cards,/本次建议已记录，不能重复选择/);assert.equal((cards.match(/data-guide="suggestion-card"/g)||[]).length,0);assert.match(cards,/data-guide="suggestion-card-readonly"/);
});
test('server-recorded opinion restores selected status after refresh without reopening selection',()=>{
 const a=app();a.t.descriptor.fingerprint='fp';a.t.material_opinions=[{valid:true,status:'SAVED_NOT_EXECUTED',text:'按原交易日期归属二月'}];a.t.handling={version:'material-handling-v1',state:'WAITING_SYSTEM',owner:'SYSTEM',label:'等待系统整理',explanation:'意见已记录，系统正在整理可执行方案。',option_id:null,action_label:''};const html=a.render();
 assert.match(html,/等待系统整理/);assert.match(html,/你当前无需操作/);assert.doesNotMatch(html,/请选择处理方式/);assert.doesNotMatch(html,/data-guide="option"/);
});
test('final gate enables all real fields for dispatch and restores them; invalid hidden input returns to its step',()=>{
 const a=app();a.c.decisionNext(a.t);let sent=0,valid=true;const field={disabled:false,checkValidity:()=>valid},section={disabled:true,querySelectorAll:()=>[field]};const form={querySelectorAll:()=>[section],requestSubmit(){assert.equal(section.disabled,false);sent++;}};a.c.decisionCommit(a.t,form);assert.equal(sent,1);assert.equal(section.disabled,true);valid=false;a.c.decisionCommit(a.t,form);assert.equal(sent,1);assert.equal(a.c.decisionGuide(a.t).step,0);assert.equal(section.disabled,true);
});
test('readonly VERIFY keeps source outside disabled editing controls',()=>{
 const a=app(),o=option('verify_source_values');o.fields=[{name:'records',label:'核实',component:'slot',slot:'record_selection',properties:[],required:true},{name:'note',label:'备注',component:'textarea',required:false,max_length:2000,placeholder:''}];a.t.descriptor=descriptor(o);a.c.materialCanWrite=()=>false;const html=a.render();assert.match(html,/data-guide-step="0" >/);assert.doesNotMatch(html,/SELECTION/);assert.match(html,/SOURCE/);assert.match(html,/data-guide="next" disabled/);
});
test('Agent origin is explicit, metadata escaped and nonempty prefill rejected',()=>{
 const a=app();a.render();const g=a.c.decisionGuide(a.t);for(const [mock,label] of [[true,'模拟调用'],[false,'真实调用'],[undefined,'调用方式未知']]){g.agent={response:{metadata:{mock,model_version:'<script>x</script>'}}};const html=a.render();assert.match(html,/Agent建议·待人工判断/);assert.ok(html.includes(label));assert.doesNotMatch(html,/<script>/);}assert.equal(a.c.decisionAgentValid({status:'PROPOSED',descriptor_hash:'fp',suggestion:{option_id:null,reason:'reason',uncertainties:[],prefill:{reason:'fiction'}}},'fp'),false);
});
test('Enter preserves native controls and only guards form text input implicit submission',()=>{
 const a=app(),card={},form={querySelector:()=>null};let stopped=0;
 const press=(tagName,type,inside=true,isComposing=false)=>a.c.decisionCapture({type:'keydown',key:'Enter',isComposing,target:{tagName,type,dataset:{guide:'commit'},closest:s=>s==='form'?(inside?form:null):card},preventDefault(){stopped++;},stopImmediatePropagation(){}});
 for(const tag of ['BUTTON','SUMMARY','A','SELECT','TEXTAREA'])press(tag);
 for(const type of ['checkbox','radio','submit','button','date','file'])press('INPUT',type);
 press('INPUT','text',false);press('INPUT','text',true,true);
 assert.equal(stopped,0);assert.equal(a.c.decisionGuide(a.t).step,0);
 press('INPUT','text');assert.equal(stopped,1);assert.equal(a.c.decisionGuide(a.t).step,1);
 press('INPUT','text');assert.equal(stopped,2);assert.equal(a.c.decisionGuide(a.t).step,1);
});
test('step navigation renders before focusing the current question including back edit resume and invalid fields',()=>{
 const a=app(),calls=[];a.c.render=()=>calls.push('render');a.c.document.querySelector=s=>{assert.equal(s,'.decision-chat [data-current-question]');return {focus(){calls.push('focus');}};};
 const expectFocus=fn=>{calls.length=0;fn();assert.deepEqual(calls,['render','focus']);};
 expectFocus(()=>a.c.decisionNext(a.t));
 const card={querySelector:()=>null};
 for(const guide of ['back','edit','resume'])expectFocus(()=>a.c.decisionCapture({type:'click',target:{closest:s=>s==='.decision-chat'?card:{dataset:{guide,step:'0'}}},preventDefault(){},stopImmediatePropagation(){}}));
 expectFocus(()=>a.c.decisionChoose(a.t,'confirm_invoice_amount'));
 expectFocus(()=>a.c.decisionNext(a.t));
 expectFocus(()=>a.c.decisionCommit(a.t,{querySelectorAll:()=>[{disabled:true,querySelectorAll:()=>[{disabled:false,checkValidity:()=>false}]}]}));
});
test('five fallback actions satisfy decision-v2 and keep one primary action in every live state',()=>{
 const ids=['record_judgement','suspend','request_supplement','mark_out_of_scope','escalate'];
 for(const id of ids){const a=app();a.t.descriptor=descriptor(fallbackOption(id));assert.equal(a.c.decisionValid(a.t.descriptor),true,id);const html=a.render();assert.equal((html.match(/class="primary"/g)||[]).length,1,id);assert.match(html,/业务判断/);assert.match(html,/data-task-action-field/);}
 const choice=app();choice.t.descriptor=descriptor(fallbackOption());choice.t.descriptor.options=ids.map(fallbackOption);choice.t.material_opinions=[];const choiceHtml=choice.render();assert.equal((choiceHtml.match(/class="primary"/g)||[]).length,1);assert.equal((choiceHtml.match(/data-guide="option"/g)||[]).length,5);
});
test('role permissions disable escalation when there is no higher role',()=>{
 const a=app(),ids=['record_judgement','suspend','request_supplement','mark_out_of_scope','escalate'];a.c.state.role='admin';a.t.descriptor=descriptor(fallbackOption());a.t.descriptor.options=ids.map(fallbackOption);a.t.descriptor.options.find(o=>o.id==='escalate').permissions=['operator','accountant'];a.t.material_opinions=[];
 const html=a.render();assert.match(html,/data-option="escalate"[^>]*disabled/);const original=a.c.decisionGuide(a.t).option;a.c.decisionChoose(a.t,'escalate');assert.equal(a.c.decisionGuide(a.t).option,original);
});
test('fallback commit sends an explicit execute_task_action payload and follows server next',async()=>{
 const a=app(),calls=[],messages=[];a.t.descriptor=descriptor(fallbackOption());a.t.descriptor.fingerprint='descriptor-fingerprint';a.draft.taskAction={judgement:'保留为特殊合同判断',reason:'已核对合同第 3 条'};
 let pending=Promise.resolve();a.c.exclusive=fn=>(pending=Promise.resolve().then(fn));a.c.materialDraftRevision=()=>3;a.c.materialDeleteDraft=()=>{};a.c.materialSaveNavigation=()=>{};a.c.loadWorkbench=async()=>{};a.c.notify=m=>messages.push(m);a.c.command=async(...args)=>{calls.push(args);return {next:{version:'workbench-next-step-v1',task_id:null,title:'本组已完成'}};};
 a.c.decisionNext(a.t);assert.equal(a.c.decisionCanSubmit(a.t),true);assert.equal((a.render().match(/class="primary"/g)||[]).length,1);assert.match(a.render(),/<details><summary>执行后/);assert.doesNotMatch(a.render(),/<details[^>]* open[^>]*><summary>执行后/);
 const form={querySelectorAll:()=>[]},card={querySelector:()=>form},button={dataset:{guide:'commit'}};
 a.c.decisionCapture({type:'click',target:{closest:s=>s==='.decision-chat'?card:s==='button'?button:null},preventDefault(){},stopImmediatePropagation(){}});await pending;
 assert.equal(calls.length,1);assert.equal(calls[0][0],'execute_task_action');assert.equal(calls[0][1],'a');assert.equal(calls[0][2],1);assert.deepEqual(JSON.parse(JSON.stringify(calls[0][3])),{task_id:'task',descriptor_hash:'descriptor-fingerprint',action_type_id:'record_judgement',values:{judgement:'保留为特殊合同判断',reason:'已核对合同第 3 条'}});assert.doesNotMatch(JSON.stringify(calls),/\[object PointerEvent\]/);assert.equal(a.ui.screen,'list');assert.match(messages[0],/本组已完成/);
});
test('decision-v1 remains visible but read only',()=>{
 const a=app(),legacy=descriptor();legacy.version='decision-v1';delete legacy.stage;delete legacy.why_now;legacy.options[0].effects=['历史影响'];a.t.descriptor=legacy;const html=a.render();assert.match(html,/历史办理契约（只读）/);assert.match(html,/历史影响/);assert.doesNotMatch(html,/<form|class="primary"|data-guide="commit"/);assert.equal(a.c.decisionReady(a.t),false);
});

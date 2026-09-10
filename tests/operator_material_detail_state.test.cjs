const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const source=['operator-materials.js','operator-material-navigation.js','operator-accounts.js','operator-mapping.js'].map(p=>fs.readFileSync(path.join(__dirname,'../static',p),'utf8')).join('\n');
function app(saved=new Map()){
 const listeners={},messages=[],history={state:null,pushState(value){this.state=structuredClone(value);},replaceState(value){this.state=structuredClone(value);}};
 const records=Array.from({length:7},(_,i)=>({object_id:'r'+i,version:1,state:'NEEDS_REVIEW'}));
 const state={epoch:1,user:{user_id:'operator'},role:'operator',view:'materials',overview:{material_review:{counts:{},records,tasks:[
  {id:'a',kind:'ISSUE',reason:'期间缺失',artifact_id:'f1',artifact_version:1,filename:'甲.xlsx',title:'期间问题',record_ids:records.map(r=>r.object_id)},
  {id:'b',kind:'ISSUE',reason:'期间缺失',artifact_id:'f2',artifact_version:1,filename:'乙.xlsx',title:'期间问题',record_ids:[]}],},bank_accounts:{accounts:[],statements:[]}}};
 const context=vm.createContext({state,scope:()=>({period:'2026-01'}),scopeKey:()=> '甲/2026-01',storage:()=>'',actions:{},render(){},$:()=>null,readonly:()=>false,
  notify:m=>messages.push(m),exclusive:fn=>fn(),closeDialog(){},
  sessionStorage:{getItem:k=>saved.get(k)||null,setItem:(k,v)=>saved.set(k,v),removeItem:k=>saved.delete(k)},
  window:{history,scrollY:420,scrollTo(){},addEventListener:(name,fn)=>listeners[name]=fn},
  document:{addEventListener(name,fn){(listeners['document-'+name]??=[]).push(fn);},querySelectorAll:()=>[]},command:async()=>({})});
 vm.runInContext(source+';installMaterialActions();installBankActions();globalThis.api={actions,materialState,openMaterialDetail,currentMaterialTask,materialDraft,materialSaveDraft,materialEntryStatus,materialAdvance,materialReturnList,bankDraft,bankState,resetBankState,openMapping};',context);
 return {...context.api,state,context,history,listeners,messages,saved};
}
test('a new runtime restores the scoped text draft and detail, but never saved record selections',()=>{
 const a=app();a.openMaterialDetail('a');const d=a.materialDraft(a.currentMaterialTask());d.reason='银行正在核对';d.defer=true;d.selected.add('r0');a.materialSaveDraft(a.currentMaterialTask());
 const b=app(a.saved),ui=b.materialState();assert.equal(ui.screen,'detail');assert.equal(b.currentMaterialTask().id,'a');
 const restored=b.materialDraft(b.currentMaterialTask());assert.equal(restored.reason,'银行正在核对');assert.equal(restored.defer,true);assert.equal(restored.selected.size,0);
 b.state.user.user_id='another-operator';assert.equal(b.materialState().screen,'list');assert.equal(b.materialDraft(b.state.overview.material_review.tasks[0]).reason,'');
});
test('page navigation updates history and popstate preserves the target snapshot filter',()=>{
 const a=app();a.openMaterialDetail('a');a.actions['material-page']({dataset:{page:'1'}});assert.equal(a.history.state.finwiseMaterials.page,1);
 const pageTwo=structuredClone(a.history.state);a.materialReturnList();a.listeners.popstate({state:pageTwo});assert.equal(a.materialState().page,1);
 a.materialReturnList();a.actions['material-filter']({dataset:{filter:'results'}});const results=structuredClone(a.history.state);
 a.actions['material-filter']({dataset:{filter:'verified'}});a.listeners.popstate({state:results});assert.equal(a.materialState().filter,'results');
});
test('a late save after returning to the list persists its result without switching screens',async()=>{
 const a=app();a.openMaterialDetail('a');const t=a.currentMaterialTask();a.materialDraft(t).reason='等待外部资料';
 let finish;a.context.command=()=>new Promise(resolve=>{finish=()=>{t.deferred=true;resolve({});};});
 const pending=a.actions['material-save-defer']();a.materialReturnList();finish();await pending;
 assert.equal(t.deferred,true);assert.equal(a.materialState().screen,'list');assert.match(a.messages.at(-1),/已保存/);
});
test('late completion cannot delete a newer draft written after back and forward navigation',async()=>{
 const a=app();a.openMaterialDetail('a');const t=a.currentMaterialTask();a.materialDraft(t).reason='第一版原因';a.materialDraft(t).defer=true;
 let finish;a.context.command=()=>new Promise(resolve=>{finish=()=>{t.deferred=true;resolve({});};});
 const detail=structuredClone(a.history.state),pending=a.actions['material-save-defer']();a.materialReturnList();a.listeners.popstate({state:detail});
 a.materialDraft(t).reason='新增的第二版说明';a.materialSaveDraft(t);finish();await pending;
 assert.equal(a.materialDraft(t).reason,'新增的第二版说明');
 const fresh=app(a.saved);assert.equal(fresh.materialDraft(fresh.state.overview.material_review.tasks[0]).reason,'新增的第二版说明');
});
test('a late mapping request does not reopen the detail workflow after browser back',async()=>{
 const a=app();a.openMaterialDetail('a');let finish;
 a.context.command=()=>new Promise(resolve=>finish=()=>resolve({effect:{object:{object_id:'saved-mapping'}}}));
 const pending=a.openMapping({object_id:'f1',version:1});a.materialReturnList();finish();await pending;
 assert.equal(a.state.view,'materials');assert.equal(a.materialState().screen,'list');assert.match(a.messages.at(-1),/任务已保存/);
});
test('waiting is derived from actual processing state and remains incomplete after skipping',()=>{
 const a=app();a.state.overview.material_review.tasks.splice(1);a.openMaterialDetail('a');
 const entry=a.materialState().group.entries[0];entry.supplementId='new-file';
 a.state.overview.payroll_mappings=[{status:'RUNNING',data:{artifact_id:'new-file'}}];
 a.actions['material-skip']();assert.equal(a.materialState().screen,'summary');assert.equal(a.materialEntryStatus(entry),'waiting');
 a.state.overview.payroll_mappings[0].status='APPLIED';assert.equal(a.materialEntryStatus(entry),'skipped');
});
test('changed bank candidate token clears consent without destroying typed fields',()=>{
 const a=app(),c={artifact_id:'bank-file',artifact_version:1,token:'before',identity:{}};
 const d=a.bankDraft(c);d.confirmed=true;d.holder='已填写户名';
 const next=a.bankDraft({...c,token:'after'});assert.equal(next.confirmed,false);assert.equal(next.holder,'已填写户名');
});
test('saving one bank keeps drafts for another bank; scope reset clears old consent',async()=>{
 const a=app(),m=a.state.overview.material_review;
 m.tasks=[{id:'a',kind:'ISSUE',reason:'bank_account_ref：确认银行',title:'确认银行',artifact_id:'f1',artifact_version:1,filename:'银行甲.xlsx',record_ids:[]}];
 const first={artifact_id:'f1',artifact_version:1,token:'first',status:'NEW',identity:{}},other={artifact_id:'f2',artifact_version:1,token:'second',status:'NEW',identity:{}};
 a.state.overview.bank_accounts.statements=[first,other];a.openMaterialDetail('a');
 const d=a.bankDraft(first);d.bank_name='中国银行';d.confirmed=true;
 const d2=a.bankDraft(other);d2.holder='其他银行未提交户名';d2.confirmed=true;
 a.context.command=async()=>{first.status='LINKED';m.tasks=[];};
 const form={id:'bankAccountForm',dataset:{artifact:'f1'},reportValidity:()=>true};
 a.listeners['document-submit'].forEach(fn=>fn({target:form,preventDefault(){}}));
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(a.bankDraft(other).holder,'其他银行未提交户名');
 a.resetBankState();assert.equal(a.bankDraft(other).confirmed,false);
});
test('unavailable session storage does not prevent entering or handling a scoped task',()=>{
 const a=app();a.context.sessionStorage={getItem(){throw Error('denied');},setItem(){throw Error('denied');}};
 a.openMaterialDetail('a');a.materialDraft(a.currentMaterialTask()).reason='仅内存保留';a.materialSaveDraft(a.currentMaterialTask());
 assert.equal(a.materialState().screen,'detail');a.actions['material-skip']();assert.equal(a.currentMaterialTask().id,'b');
});

const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../static/operator-autonomous.js'),'utf8');
const main=fs.readFileSync(path.join(__dirname,'../static/operator.js'),'utf8');
const escCode=main.slice(main.indexOf('const esc ='),main.indexOf('const label ='));
function harness(options={}){
 const elements={},events={},calls=[],notices=[];
 const el=id=>elements[id]||(elements[id]={id,disabled:false,open:false,value:'',innerHTML:'',textContent:'',dataset:{},isConnected:true,
  classList:{add(){},remove(){}},setAttribute(){},focus(){},click(){calls.push('choose');}});
 const c=vm.createContext({state:{epoch:1,busy:false,role:'operator',overview:{autonomous_workflow:{status:'WAITING_INPUT'}},scopes:[]},
  $:el,readonly:()=>options.readonly||false,actions:{},setTimeout:()=>0,clearTimeout(){},scope:()=>({accounting_period_id:'2026-08'}),
  document:{addEventListener:(n,fn)=>(events[n]??=[]).push(fn),querySelectorAll:()=>Object.values(elements)},
  openDialog:(title,html)=>{el('dialog').open=true;el('autonomousUploadForm');el('dialogBody').innerHTML=html;},
  closeDialog:()=>{el('dialog').open=false;calls.push('closed');},renderScopes(){},
  loadWorkbench:async()=>calls.push('load'),render(){},notify:(m,e)=>notices.push({m,e}),
  uploadFile:async file=>{calls.push(file.name);return options.upload?options.upload(file,c):{object_id:file.name};},
  request:async(p,b)=>{calls.push(p);return options.request?options.request(p,b):{};},
 });
 vm.runInContext(escCode+source+main.slice(main.indexOf('async function exclusive('),main.indexOf('function renderScopes()')),c);
 c.openAutonomousUpload();
 const emit=(type,event)=>{for(const fn of events[type]||[])fn({preventDefault(){},...event});};
 return {c,elements,el,calls,notices,emit};
}
const file=(name,size=12,lastModified=1)=>({name,size,lastModified});
const select=(h,files)=>h.emit('change',{target:{id:'autonomousFiles',files,value:'chosen'}});
const entries=h=>vm.runInContext('autonomousUpload.files',h.c);
const submit=async h=>{await h.c.exclusive(h.c.submitAutonomousUpload);h.c.renderAutonomousUpload();};
test('drop and repeated selections append, deduplicate, reject oversized files and remove one',()=>{
 const h=harness(),a=file('流水.xlsx'),b=file('发票.xlsx');
 h.emit('drop',{target:{closest:()=>h.el('uploadDropzone')},dataTransfer:{files:[a,b]}});
 select(h,[a,file('余额.xlsx'),file('过大.pdf',17*1024*1024)]);
 assert.equal(entries(h).length,3);assert.match(h.el('uploadSelectionStatus').textContent,/忽略 1 份.*1 份超过 16 MB/);
 assert.deepEqual(h.calls,[]);
 h.emit('click',{target:{closest:()=>({dataset:{uploadIndex:'1'}})}});
 assert.equal(entries(h).length,2);assert.equal(entries(h)[1].file.name,'余额.xlsx');
 // Revisions with identical lengths are not incorrectly dropped.
 select(h,[file('流水.xlsx',12,2)]);assert.equal(entries(h).length,3);
});
test('partial failure continues remaining files and retries only failed files',async()=>{
 let fail=true;const h=harness({upload:async f=>{if(f.name==='坏.xlsx'&&fail)throw Error('连接失败');return {};}});
 select(h,[file('一.xlsx'),file('坏.xlsx'),file('三.xlsx')]);await submit(h);
 assert.equal(h.el('dialog').open,true);assert.deepEqual(h.calls,['一.xlsx','坏.xlsx','三.xlsx','load']);
 assert.match(h.el('uploadSelectionStatus').textContent,/2 份已保存，1 份未保存/);
 assert.equal(h.el('uploadSubmit').disabled,false);fail=false;await submit(h);
 assert.deepEqual(h.calls,['一.xlsx','坏.xlsx','三.xlsx','load','坏.xlsx','closed','load']);
});
test('in-flight submission locks adding and prevents duplicate batches',async()=>{
 let release;const gate=new Promise(r=>release=r),h=harness({upload:async()=>{await gate;return {};}});
 select(h,[file('一.xlsx')]);const running=submit(h);await h.c.exclusive(h.c.submitAutonomousUpload);
 select(h,[file('二.xlsx')]);assert.equal(entries(h).length,1);assert.equal(h.el('uploadSubmit').disabled,true);
 release();await running;assert.equal(h.calls.filter(x=>x==='一.xlsx').length,1);
});
test('scope change or lost dialog stops pending uploads and ignores late completion',async()=>{
 const h=harness({upload:async(f,c)=>{c.state.epoch++;return {};}});
 select(h,[file('一.xlsx'),file('二.xlsx')]);await submit(h);
 assert.deepEqual(h.calls,['一.xlsx']);assert.equal(h.notices.length,0);
});
test('authorization failure stops remaining files; ordinary failures are retryable',async()=>{
 const h=harness({upload:async()=>{const e=Error('权限已撤销');e.status=403;throw e;}});
 select(h,[file('一.xlsx'),file('二.xlsx')]);await submit(h);
 assert.deepEqual(h.calls,['一.xlsx']);assert.match(h.el('uploadSelectionStatus').textContent,/0 份已保存，2 份未保存/);
});
test('readonly users cannot open or populate upload queue, and keyboard can select files',()=>{
 const ro=harness({readonly:true});assert.equal(ro.el('dialog').open,false);
 const h=harness();h.emit('keydown',{target:{id:'uploadDropzone'},key:'Enter'});assert.deepEqual(h.calls,['choose']);
 h.emit('change',{target:{id:'autonomousFiles',files:[file('一.xlsx')],value:''}});assert.equal(entries(h).length,1);
});
test('closing and reopening removes previous local selection',()=>{
 const h=harness();select(h,[file('一.xlsx')]);h.c.closeDialog();h.c.openAutonomousUpload();assert.equal(entries(h).length,0);
});
test('all autonomous writes use existing exclusive click guard',async()=>{
 for(const action of ['autonomous-start','autonomous-retry','autonomous-cancel','autonomous-answer']){
  let release;const gate=new Promise(r=>release=r);const h=harness({request:async()=>gate});
  h.c.installAutonomousActions();h.c.state.overview.autonomous_workflow.job={object_id:'run1'};h.el('autonomousAnswer').value='已有原始依据';
  vm.runInContext(main.slice(main.indexOf("document.addEventListener('click'"),main.indexOf("document.addEventListener('change'")),h.c);
  const target={closest:selector=>selector==='button'?{dataset:{action}}:null};
  h.emit('click',{target});h.emit('click',{target});
  assert.equal(h.calls.filter(x=>x.startsWith('/api/')).length,1,action);assert.equal(h.c.state.busy,true);
  release({});await new Promise(r=>setImmediate(r));assert.equal(h.c.state.busy,false);
 }
});
test('file read finishing after scope change sends no request',async()=>{
 const h=harness();h.c.Uint8Array=Uint8Array;h.c.btoa=x=>Buffer.from(x,'binary').toString('base64');
 vm.runInContext(main.slice(main.indexOf('async function uploadFile('),main.indexOf('function chooseBaselineFile(')),h.c);
 await h.c.uploadFile({name:'stale',size:1,arrayBuffer:async()=>{h.c.state.epoch++;return new Uint8Array([1]).buffer;}},'business','2026-08',null);
 assert.deepEqual(h.calls,[]);
});
test('autonomous upload cannot close mid-save, but session teardown can close it',async()=>{
 const h=harness();vm.runInContext(main.slice(main.indexOf('function closeDialog()'),main.indexOf('function recordTable(')),h.c);
 h.el('dialog').close=()=>h.el('dialog').open=false;
 vm.runInContext('autonomousUpload.busy=true',h.c);h.c.closeDialog();assert.equal(h.el('dialog').open,true);
 h.c.state.epoch++;h.c.closeDialog();assert.equal(h.el('dialog').open,false);
});
test('background polling does not overwrite account forms or historical results',()=>{
 const h=harness();let scheduled=0;h.c.setTimeout=()=>{scheduled++;return 1;};
 h.c.state.overview.autonomous_workflow.status='QUEUED';
 for(const view of ['history','accounts','vouchers']){h.c.state.view=view;h.c.scheduleAutonomousPoll();}
 assert.equal(scheduled,0);h.c.state.view='current';h.c.scheduleAutonomousPoll();assert.equal(scheduled,1);
});
test('autonomous source details retain download without broken legacy record link',async()=>{
 const h=harness({request:async()=>({object:{object_type:'SourceArtifact',status:'ACTIVE',version:1,data:{filename:'凭证.xlsx',sha256:'hash',observed_period:'2026-08'}},relations:[],audits:[]})});
 h.c.state.dialogSequence=0;h.c.statusBadge=()=>'';h.c.purposeLabel=()=>'';h.c.URLSearchParams=URLSearchParams;
 vm.runInContext(main.slice(main.indexOf('async function showObject('),main.indexOf('async function uploadFile(')),h.c);
 await h.c.showObject('source-1');assert.match(h.el('dialogBody').innerHTML,/下载原始文件/);
 assert.doesNotMatch(h.el('dialogBody').innerHTML,/data-file-records/);assert.match(h.el('dialogBody').innerHTML,/本期处理报告及凭证依据/);
});
test('confirmed vouchers are not counted as pending and remain accessible alongside historical entry',()=>{
 const h=harness();Object.assign(h.c,{activeArtifacts:()=>[],table:()=>'',objectButton:()=>''});
 h.c.state.overview.progress={stages:[]};h.c.state.overview.autonomous_workflow={findings:[],history:[],ready_count:3,confirmed_count:3,entry_preview_count:3,source_count:0};
 const html=h.c.renderAutonomous();assert.match(html,/<strong>0<\/strong> 张待复核/);
 assert.match(html,/>查看全部 3 张分录与复核事项<\/button>/);assert.match(html,/data-action="history"/);
});

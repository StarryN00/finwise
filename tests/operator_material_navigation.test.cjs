const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../static/operator-materials.js'),'utf8');
const navigation=fs.readFileSync(path.join(__dirname,'../static/operator-material-navigation.js'),'utf8');
function app(){
 const messages=[],context=vm.createContext({state:{user:{user_id:'operator'},overview:{material_review:{counts:{},records:[],tasks:[{id:'a',kind:'VERIFY',filename:'甲工资.xls',record_ids:[],deferred:false},{id:'b',kind:'VERIFY',filename:'乙发票.xls',record_ids:[],deferred:false}]}}},
  scope:()=>({accounting_period_id:'2026-01'}),scopeKey:()=> '甲企业/2026-01',storage:()=>'',actions:{},render(){},$:()=>null,document:{addEventListener(){}},notify:m=>messages.push(m),esc:v=>String(v??''),badge:v=>String(v??''),primary:(action,label)=>`<button class="primary" data-action="${action}">${label}</button>`});
 vm.runInContext(source+navigation+';installMaterialActions();globalThis.api={actions,materialState,currentMaterialTask,materialIssueGroups,materialTasks,materialRecordedOpinion,openMaterialDetail,materialAdvance,materialEntryStatus,materialReturnList,materialTaskIsCurrent,materialDraft,materialDraftRevision,materialDeleteDraft,materialNavigationSnapshot,restoreMaterialNavigation,materialNextStepPanel,renderMaterialTask,renderActionMetrics};',context);
 return {...context.api,messages,state:context.state};
}
test('explicit result selection restores exactly the skipped file, not the next file',()=>{
 const a=app(),ui=a.materialState();ui.filter='VERIFY';ui.skipped.add('a');
 assert.equal(a.currentMaterialTask().filename,'乙发票.xls');
 a.actions['material-filter']({dataset:{filter:'VERIFY',task:'a'}});
 assert.equal(a.currentMaterialTask().filename,'甲工资.xls');assert(!ui.skipped.has('a'));
});
test('stale result entry gives feedback and never substitutes another file',()=>{
 const a=app(),ui=a.materialState();ui.filter='results';
 a.actions['material-filter']({dataset:{filter:'VERIFY',task:'deleted-task'}});
 assert.equal(ui.filter,'results');assert.equal(a.currentMaterialTask(),undefined);assert.match(a.messages[0],/已变化/);
});
test('normal verification records are not counted as an exception queue',()=>{
 const a=app();a.materialState().filter='all';assert.equal(a.currentMaterialTask(),undefined);
});
test('server next and empty state render exactly one primary action',()=>{
 const a=app(),m=a.state.overview.material_review;m.tasks=[];m.counts.files=0;m.next_step={version:'workbench-next-step-v1',owner:'USER',state:'NEEDS_INPUT',title:'接收本期资料',explanation:'尚无业务原件',task_id:null,action:{kind:'UPLOAD',label:'添加本期资料'}};
 const html=a.materialNextStepPanel()+a.renderMaterialTask();assert.equal((html.match(/class="primary"/g)||[]).length,1);assert.match(html,/data-action="upload"/);
});
test('every action metric number has a drilldown control and secondary sections stay collapsed',()=>{
 const a=app();a.state.overview.material_review.action_metrics={executed_action_count:3,fallback_action_count:2,fallback_ratio:.6667,items:[{action_type_id:'suspend',label:'暂停办理本事项',count:2,fallback:true,drilldown:[{command_id:'c',target_id:'a'}]}]};const html=a.renderActionMetrics();
 assert.match(html,/^<details/);assert.doesNotMatch(html,/^<details[^>]* open/);assert.equal((html.match(/data-action="material-action-metric"/g)||[]).length,3);for(const text of ['已执行动作 3 次','兜底动作 2 次','暂停办理本事项 2 次'])assert.match(html,new RegExp('<button[^>]+>'+text.replace(/[.*+?^${}()|[\\]\\]/g,'\\$&')));
 const workbenchSource=source;assert.match(workbenchSource,/<details class="panel pad mat-history"><summary>/);assert.match(workbenchSource,/<details class="panel pad mat-overview"><summary>/);assert.doesNotMatch(workbenchSource,/mat-overview-status/);
});
test('an edited task-action draft is not deleted by a late successful response',()=>{
 const a=app(),draft=a.materialDraft(a.state.overview.material_review.tasks[0]);draft.taskAction={reason:'第一版依据'};const revision=a.materialDraftRevision(draft);draft.taskAction.reason='请保留的新依据';assert.equal(a.materialDeleteDraft('a',revision),false);assert.equal(a.materialDraft(a.state.overview.material_review.tasks[0]).taskAction.reason,'请保留的新依据');
});
test('saved processing opinions belong to the system queue and leave the issue unresolved',()=>{
 const a=issueApp(),m=a.state.overview.material_review,ui=a.materialState();m.tasks[0].material_opinions=[{valid:true,status:'SAVED_NOT_EXECUTED',text:'按原交易日期归属二月'}];
 m.tasks[0].handling={version:'material-handling-v1',state:'WAITING_SYSTEM',owner:'SYSTEM',label:'等待系统整理',explanation:'意见已记录，系统正在整理可执行方案。',option_id:null,action_label:''};
 ui.filter='all';assert.deepEqual(a.materialTasks(true).map(t=>t.id),['other','b']);
 ui.filter='selected';assert.deepEqual(a.materialTasks(true).map(t=>t.id),['a']);assert.equal(a.materialRecordedOpinion(m.tasks[0]).text,'按原交易日期归属二月');
 a.openMaterialDetail('a');assert.equal(a.materialEntryStatus(a.materialState().group.entries[0]),'system');
});
test('issue grouping is read-only and keeps task, file and unique-record counts separate',()=>{
 const a=app(),m=a.state.overview.material_review;
 m.records=[{object_id:'r1'},{object_id:'r2'},{object_id:'r3'}];
 m.tasks=[
  {id:'i1',kind:'ISSUE',title:'缺少付款依据',reason:'缺少付款依据',artifact_id:'file-a',filename:'银行流水.xlsx',record_ids:['r1','r2'],deferred:false},
  {id:'i2',kind:'ISSUE',title:'缺少付款依据',reason:'缺少付款依据',artifact_id:'file-b',filename:'付款记录.xlsx',record_ids:['r2','r3'],deferred:false},
  {id:'i3',kind:'ISSUE',title:'期间待确认',reason:'交易期间与当前期间不一致',artifact_id:'file-a',filename:'银行流水.xlsx',record_ids:['r1'],deferred:false}
 ];
 const groups=a.materialIssueGroups();
 assert.equal(groups.length,2);
 assert.deepEqual(JSON.parse(JSON.stringify(groups.map(g=>[g.tasks.length,g.fileIds.size,g.recordIds.size]))),[[2,2,3],[1,1,1]]);
});
function issueApp(){
 const a=app(),m=a.state.overview.material_review;
 m.tasks=[
  {id:'a',kind:'ISSUE',reason:'期间缺失',title:'期间待确认',artifact_id:'f1',artifact_version:1,filename:'甲.xlsx',record_ids:['r1'],deferred:false},
  {id:'other',kind:'ISSUE',reason:'税额差异',title:'税额待核对',artifact_id:'f1',artifact_version:1,filename:'甲.xlsx',record_ids:['r1'],deferred:false},
  {id:'b',kind:'ISSUE',reason:'期间缺失',title:'期间待确认',artifact_id:'f2',artifact_version:1,filename:'乙.xlsx',record_ids:['r2'],deferred:false}];
 m.records=[{object_id:'r1',version:1},{object_id:'r2',version:1}];return a;
}
test('triage keeps SYSTEM out of human groups but accessible in system list; deferred remains',()=>{
 const a=issueApp(),ui=a.materialState(),tasks=a.state.overview.material_review.tasks;
 tasks[2].triage={version:'issue-triage-v1',route:'SYSTEM'};
 assert.deepEqual(Array.from(a.materialIssueGroups().flatMap(g=>g.tasks),t=>t.id),['a','other']);
 ui.filter='system';assert.deepEqual(Array.from(a.materialIssueGroups().flatMap(g=>g.tasks),t=>t.id),['b']);a.openMaterialDetail('b');assert.equal(a.currentMaterialTask().id,'b');
 tasks[2].deferred=true;ui.filter='deferred';assert.deepEqual(Array.from(a.materialIssueGroups().flatMap(g=>g.tasks),t=>t.id),['b']);
});
test('a group skips an entry reclassified SYSTEM without counting it completed',()=>{
 const a=issueApp();a.openMaterialDetail('a');a.state.overview.material_review.tasks[2].triage={version:'issue-triage-v1',route:'SYSTEM'};
 a.actions['material-skip']();assert.equal(a.materialState().screen,'summary');assert.equal(a.materialEntryStatus(a.materialState().group.entries[1]),'system');
 a.actions['material-next-group']();assert.equal(a.currentMaterialTask().id,'other');
});
test('record statistics drill retains all issues including SYSTEM and restores system filter',()=>{
 const a=issueApp(),ui=a.materialState();a.state.overview.material_review.tasks[2].triage={version:'issue-triage-v1',route:'SYSTEM'};ui.filter='issues';assert.equal(a.materialIssueGroups().flatMap(g=>g.tasks).length,3);
 ui.filter='system';const snapshot=a.materialNavigationSnapshot();a.restoreMaterialNavigation(ui,snapshot);assert.equal(ui.filter,'system');
});
test('entering a group creates a dedicated detail view; skipping stays in group and ends at summary',()=>{
 const a=issueApp(),ui=a.materialState();a.openMaterialDetail('a');
 assert.equal(ui.screen,'detail');assert.deepEqual(Array.from(ui.group.entries,e=>e.id),['a','b']);
 a.actions['material-skip']();assert.equal(a.currentMaterialTask().id,'b');
 a.actions['material-skip']();assert.equal(ui.screen,'summary');assert.equal(a.currentMaterialTask(),undefined);
 assert.deepEqual(Array.from(ui.group.entries,e=>a.materialEntryStatus(e)),['skipped','skipped']);
 a.actions['material-next-group']();assert.equal(a.currentMaterialTask().id,'other');
});
test('file view constrains the processing scope and returning restores filters and drafts',()=>{
 const a=issueApp(),ui=a.materialState();ui.viewMode='files';ui.filter='period';
 // The period filter is preserved even when entering an explicit task.
 a.openMaterialDetail('a',null,'file');a.materialDraft(a.currentMaterialTask()).reason='等待银行回复';
 a.materialReturnList();assert.equal(ui.screen,'list');assert.equal(ui.viewMode,'files');assert.equal(ui.filter,'period');
 assert.equal(ui.drafts.get('a').reason,'等待银行回复');
 ui.filter='all';a.openMaterialDetail('a',null,'file');assert.deepEqual(Array.from(ui.group.entries,e=>e.id),['a','other']);
});
test('deferred tasks remain outstanding and the group never advances to an unrelated task automatically',()=>{
 const a=issueApp(),ui=a.materialState(),m=a.state.overview.material_review;a.openMaterialDetail('a');
 const t=m.tasks[0];t.deferred=true;t.response={data:{reason:'等待资料'}};a.materialAdvance(t,'deferred');
 assert.equal(a.currentMaterialTask().id,'b');a.actions['material-skip']();
 assert.equal(ui.screen,'summary');assert.equal(a.materialEntryStatus(ui.group.entries[0]),'deferred');
});
test('partial verification follows the server replacement task on the same file',()=>{
 const a=issueApp(),m=a.state.overview.material_review,ui=a.materialState();
 m.tasks=[{id:'v1',kind:'VERIFY',reason:'核实读取',artifact_id:'f1',artifact_version:1,filename:'甲.xlsx',record_ids:['r1','r2']}];
 a.openMaterialDetail('v1',null,'file');const previous=m.tasks[0];
 m.records[0].state='SOURCE_VERIFIED';m.tasks=[{...previous,id:'v2',record_ids:['r2']}];
 a.materialAdvance(previous,'verified');assert.equal(ui.screen,'detail');assert.equal(a.currentMaterialTask().id,'v2');assert.equal(ui.group.entries.length,1);
 m.records[1].state='SOURCE_VERIFIED';const remaining=m.tasks[0];m.tasks=[];a.materialAdvance(remaining,'verified');
 assert.equal(ui.screen,'summary');assert.equal(a.materialEntryStatus(ui.group.entries[0]),'verified');
});
test('partial bank attribution stays in the same issue; complete attribution advances within group only',()=>{
 const a=issueApp(),m=a.state.overview.material_review,ui=a.materialState();m.tasks[0].bank_period={target_period:'2026-02'};m.tasks[2].bank_period={target_period:'2026-02'};a.openMaterialDetail('a');const first=m.tasks[0];
 m.tasks[0]={...first,id:'remaining',record_ids:['r1']};a.materialAdvance(first,'bank_period_confirmed');assert.equal(ui.screen,'detail');assert.equal(ui.selected,'remaining');assert.match(ui.feedback,/剩余记录/);
 const remaining=m.tasks[0];m.records[0].period_assignment={valid:true};m.tasks=m.tasks.filter(t=>t.id!=='remaining');a.materialAdvance(remaining,'bank_period_confirmed');assert.equal(ui.selected,'b');assert.equal(ui.screen,'detail');
 const last=m.tasks.find(t=>t.id==='b');m.records[1].period_assignment={valid:true};m.tasks=m.tasks.filter(t=>t.id!=='b');a.materialAdvance(last,'bank_period_confirmed');assert.equal(ui.screen,'summary');assert.equal(a.materialEntryStatus(ui.group.entries[0]),'bank_period_confirmed');
});
test('refresh restores detail and exact identity; removed or changed tasks never silently substitute',()=>{
 const a=issueApp(),ui=a.materialState(),m=a.state.overview.material_review;a.openMaterialDetail('a');
 a.materialDraft(a.currentMaterialTask()).note='核对到第二列';
 const saved=JSON.parse(JSON.stringify(a.materialNavigationSnapshot()));ui.screen='list';a.restoreMaterialNavigation(ui,saved);
 assert.equal(ui.screen,'detail');assert.equal(a.currentMaterialTask().id,'a');
 m.records[0].version=2;assert.equal(a.materialTaskIsCurrent(a.currentMaterialTask()),false);assert.equal(ui.drafts.get('a').note,'核对到第二列');
 m.tasks=m.tasks.filter(t=>t.id!=='a');assert.equal(a.currentMaterialTask(),undefined);
 a.restoreMaterialNavigation(ui,{...saved,key:'other-company'});assert.equal(ui.screen,'list');assert.equal(ui.group,null);
});

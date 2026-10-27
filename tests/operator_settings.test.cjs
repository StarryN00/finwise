const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

const scripts=['operator-autonomous.js','operator.js'].map(name=>fs.readFileSync(path.join(__dirname,'../static',name),'utf8')).join('\n');
const scopes=['甲公司','乙公司'].map((legal_entity_id,i)=>({tenant_id:'tenant',organization_id:'agency',legal_entity_id,ledger_id:'主账套',accounting_period_id:'2026-08',baseline_id:'baseline-'+i}));
function overview(scope){
  return {scope,display_context:{company_name:scope.legal_entity_id,ledger_name:scope.ledger_id},period:{status:'OPEN'},artifacts:[],blockers:[],bank_accounts:{accounts:[]},
    data_readiness:{baseline_sources:{balance:[],close:[]}},progress:{stages:[],current_stage:'analysis'},
    autonomous_workflow:{status:'CANCELLED',label:'已暂停',source_count:1,findings:[],history:[],ready_count:0,confirmed_count:0,pending_count:0,blocked_count:0,
      executor:'claude_code',executors:[{id:'codex',label:'Codex CLI',available:true},{id:'claude_code',label:'Claude Code',model:'deepseek-flash',available:true}],
      bookkeeping_profile:{id:'AGENCY_SIMPLE',version:4,selection_version:2,label:'简易代账',summary:'已保存规则',cost_ratio:'0.9',source_note:'财务公司确认'},
      bookkeeping_profiles:[{id:'AGENCY_SIMPLE',label:'简易代账',summary:'简易规则'},{id:'ORIGINAL',label:'原有处理',summary:'原有规则'}]}};
}
function app(){
  const elements=new Map(),listeners={},calls=[],timers=new Map(),saved=new Map();
  let timerId=0,respond=async(url,body)=>url==='/api/v1/workbench'?overview(body.scope):{changed:true};
  const document={activeElement:null,hidden:false,addEventListener(name,fn){(listeners[name]??=[]).push(fn);},
    getElementById:id=>element(id),querySelectorAll:()=>[],querySelector:selector=>selector==='.topbar'?element('topbar'):selector==='#settingsTitle'?element('settingsTitle'):null};
  function element(id){
    if(elements.has(id))return elements.get(id);
    const classes=new Set(),attrs=new Map();let html='';
    const node={id,value:'',dataset:{},disabled:false,isConnected:true,open:false,tagName:'BUTTON',textContent:'',inert:false,
      classList:{add:name=>classes.add(name),remove:name=>classes.delete(name),contains:name=>classes.has(name),toggle(name){if(classes.has(name)){classes.delete(name);return false;}classes.add(name);return true;}},
      setAttribute:(name,value)=>attrs.set(name,value),getAttribute:name=>attrs.get(name),removeAttribute:name=>attrs.delete(name),
      addEventListener(name,fn){(listeners[id+':'+name]??=[]).push(fn);},focus(){document.activeElement=node;},
      close(){node.open=false;},showModal(){node.open=true;},getClientRects:()=>[{}],replaceChildren(){node.innerHTML='';},
      querySelectorAll:()=>[],matches:()=>false};
    Object.defineProperty(node,'innerHTML',{get:()=>html,set:value=>{
      html=value;
      if(id!=='workspace')return;
      // Parse only settings controls needed by the action contract; real layout is browser-tested separately.
      for(const match of value.matchAll(/<select\b([^>]*\bid="([^"]+)"[^>]*)>([\s\S]*?)<\/select>/g)){
        const control=element(match[2]),options=[...match[3].matchAll(/<option\s+value="([^"]*)"([^>]*)>/g)];
        control.value=(options.find(option=>/\bselected\b/.test(option[2]))||options[0]||[])[1]||'';control.disabled=/\bdisabled\b/.test(match[1]);
      }
      for(const match of value.matchAll(/<input\b([^>]*\bid="([^"]+)"[^>]*)>/g)){
        const control=element(match[2]);control.value=/\bvalue="([^"]*)"/.exec(match[1])?.[1]||'';control.disabled=/\bdisabled\b/.test(match[1]);
      }
    }});
    elements.set(id,node);return node;
  }
  const nav=[element('nav-workbench'),element('nav-settings')];nav[0].dataset.action='workbench';nav[1].dataset.action='settings';
  element('globalNav').querySelectorAll=()=>nav;
  const context=vm.createContext({document,window:{scrollTo(){}},location:{protocol:'file:',replace(){}},
    localStorage:{getItem:key=>saved.get(key)||null,setItem:(key,value)=>saved.set(key,value)},
    clearTimeout:id=>timers.delete(id),setTimeout:fn=>{timers.set(++timerId,fn);return timerId;},
    fetch:async(url,options)=>{const body=options.body?JSON.parse(options.body):null;calls.push({url,body,headers:options.headers});const result=await respond(url,body);return {ok:!result?.error,status:result?.status||200,json:async()=>result};}});
  vm.runInContext(scripts+'\nglobalThis.api={state,actions,render,renderSettings,selectScope,loadWorkbench,clearSession,loadPortfolio,openSidebar,closeSidebar,sidebarFocusables,scopeKey,settingsDraftKey,currentSettingsDraft,rememberSettingsInput,autonomousSettingsDrafts,scheduleAutonomousPoll};',context);
  const api=context.api;
  api.state.user={user_id:'operator-a'};api.state.role='accountant';api.state.csrf='csrf';api.state.selected=0;
  api.state.scopes=scopes.map(scope=>({scope,display_context:{company_name:scope.legal_entity_id},autonomous_workflow:{label:'已暂停'},blockers:[],pending_confirmation_cards:0}));
  api.state.overview=overview(scopes[0]);api.render();
  return {...api,context,element,document,nav,listeners,calls,timers,saved,
    html:()=>element('workspace').innerHTML,
    respond(fn){respond=fn;},
    input(id,value,event='input'){const target=element(id);target.value=value;for(const fn of listeners[event]||[])fn({target});},
    settings(){api.actions.settings();}};
}

test('global navigation moves the real settings controls away from the main work area',()=>{
  const a=app();assert.doesNotMatch(a.html(),/id="(?:autonomousExecutor|bookkeepingMode)"/);
  a.settings();assert.equal(a.state.view,'settings');assert.match(a.html(),/id="autonomousExecutor"/);assert.match(a.html(),/id="bookkeepingMode"/);
  assert.match(a.html(),/记账方式供本账套各月使用，Agent 用于所选期间/);
  assert.equal(a.nav[1].getAttribute('aria-current'),'page');assert.equal(a.document.activeElement.id,'settingsTitle');
  a.actions.workbench();assert.equal(a.state.view,'current');assert.equal(a.nav[0].getAttribute('aria-current'),'page');assert.doesNotMatch(a.html(),/id="(?:autonomousExecutor|bookkeepingMode)"/);
  assert.equal(a.calls.length,0,'navigation alone never changes accounting or settings');
});

test('changing enterprise stays in settings and isolates drafts by full scope and user',async()=>{
  const a=app();a.settings();a.input('bookkeepingCostRatio','88');a.input('autonomousExecutor','codex','change');
  a.context.materialState=()=>({key:'previous-material'});a.context.mappingState=()=>({key:'previous-mapping'});
  a.saved.set('finwise.material.view.previous-material','materials');a.saved.set('finwise.mapping.view.previous-mapping','old-mapping');
  await a.selectScope(1);assert.equal(a.state.view,'settings');assert.match(a.html(),/乙公司/);assert.equal(a.element('bookkeepingCostRatio').value,'90');assert.equal(a.currentSettingsDraft(),undefined);
  assert.deepEqual(a.calls[0].body.scope,scopes[1]);
  await a.selectScope(0);assert.equal(a.element('bookkeepingCostRatio').value,'88');assert.equal(a.element('autonomousExecutor').value,'codex');
  const originalScope=a.state.scopes[0].scope;
  for(const key of ['tenant_id','organization_id','legal_entity_id','ledger_id','accounting_period_id','baseline_id']){
    a.state.scopes[0].scope={...originalScope,[key]:'different'};assert.equal(a.currentSettingsDraft(),undefined,key);
  }
  a.state.scopes[0].scope=originalScope;a.state.user={user_id:'operator-b'};assert.equal(a.currentSettingsDraft(),undefined);
  a.state.user={user_id:'operator-a'};assert.equal(a.currentSettingsDraft().bookkeeping.ratio,'88');
  a.clearSession();assert.equal(a.autonomousSettingsDrafts.size,0);assert.equal(a.state.user,null);assert.match(a.html(),/请登录/);assert(a.element('globalNav').classList.contains('hidden'));
});

test('manual refresh preserves edited fields and their original optimistic version',async()=>{
  const a=app();a.settings();a.input('bookkeepingCostRatio','88');a.input('bookkeepingSourceNote','新的确认来源');
  a.respond(async(url,body)=>{if(url==='/api/v1/workbench'){const data=overview(body.scope);data.autonomous_workflow.bookkeeping_profile.selection_version=9;return data;}return {changed:true};});
  await a.actions.refresh();assert.equal(a.element('bookkeepingCostRatio').value,'88');assert.equal(a.element('bookkeepingSourceNote').value,'新的确认来源');assert.match(a.element('notice').textContent,/状态已刷新/);
  await a.actions['bookkeeping-save']();const request=a.calls.find(call=>call.url.endsWith('/bookkeeping-profile'));
  assert.equal(request.body.expected_version,2);assert.equal(request.body.cost_ratio,'0.88');assert.equal(request.body.source_note,'新的确认来源');assert.equal(a.currentSettingsDraft().bookkeeping,undefined);
  assert.deepEqual(request.body.scope,scopes[0]);assert.equal(request.headers['X-CSRF-Token'],'csrf');
});

test('saving either section keeps unsaved edits in the other section',async()=>{
  for(const section of ['executor','bookkeeping']){
    const a=app();a.settings();a.input('autonomousExecutor','codex','change');a.input('bookkeepingCostRatio','88');
    await a.actions[section==='executor'?'autonomous-executor':'bookkeeping-save']();
    const draft=a.currentSettingsDraft();assert.equal(draft[section],undefined);
    if(section==='executor'){assert.equal(draft.bookkeeping.ratio,'88');assert.equal(a.element('bookkeepingCostRatio').value,'88');}
    else{assert.equal(draft.executor.backend,'codex');assert.equal(a.element('autonomousExecutor').value,'codex');}
    assert.match(a.html(),/data-settings-dirty/);assert.match(a.element('notice').textContent,/已保存/);
  }
});

test('version conflicts retain typed values and draft version without claiming success',async()=>{
  const a=app();a.settings();a.input('bookkeepingCostRatio','88');
  a.respond(async()=>({error:{message:'对象版本冲突，请刷新后重试',code:'VERSION_CONFLICT'},status:409}));
  await assert.rejects(()=>a.actions['bookkeeping-save'](),/设置版本已变化.*恢复已保存设置/);
  assert.equal(a.currentSettingsDraft().bookkeeping.expectedVersion,2);assert.equal(a.currentSettingsDraft().bookkeeping.ratio,'88');assert.equal(a.element('bookkeepingCostRatio').value,'88');assert.doesNotMatch(a.element('notice').textContent,/已保存/);
});

test('running jobs, viewers and closed periods cannot save or create setting drafts',async()=>{
  for(const restriction of ['QUEUED','ANALYZING','REVIEWING','viewer','CLOSED']){
    const a=app();if(restriction==='viewer')a.state.role='viewer';else if(restriction==='CLOSED')a.state.overview.period.status='CLOSED';else a.state.overview.autonomous_workflow.status=restriction;
    a.settings();assert.equal(a.element('autonomousExecutor').disabled,true);assert.equal(a.element('bookkeepingMode').disabled,true);
    a.input('bookkeepingCostRatio','88');assert.equal(a.currentSettingsDraft(),undefined);
    await assert.rejects(()=>a.actions['bookkeeping-save'](),/当前不能修改设置/);await assert.rejects(()=>a.actions['autonomous-executor'](),/当前不能修改设置/);assert.equal(a.calls.length,0);
    if(['QUEUED','ANALYZING','REVIEWING'].includes(restriction))assert.match(a.html(),/data-action="autonomous-cancel"/);else assert.doesNotMatch(a.html(),/data-action="autonomous-cancel"/);
    assert.equal(a.timers.size,0,'settings does not silently redraw the form on an automatic poll');
  }
});

test('settings reset discards only the current scope draft and reports the result',async()=>{
  const a=app();a.settings();a.input('bookkeepingCostRatio','88');await a.selectScope(1);a.input('bookkeepingCostRatio','80');
  a.actions['settings-reset']();assert.equal(a.currentSettingsDraft(),undefined);assert.equal(a.element('bookkeepingCostRatio').value,'90');assert.match(a.element('notice').textContent,/已恢复服务器上保存的设置/);
  await a.selectScope(0);assert.equal(a.element('bookkeepingCostRatio').value,'88');
});

test('empty scopes, signed-out users and disabled autonomous service have explicit settings states',async()=>{
  const a=app();a.state.overview=null;a.state.scopes=[];a.state.selected=null;a.settings();assert.match(a.html(),/还没有企业时/);assert.doesNotMatch(a.html(),/id="(?:autonomousExecutor|bookkeepingMode)"/);
  a.state.user=null;a.render();assert.match(a.html(),/请先登录，再查看设置/);
  a.state.user={user_id:'operator-a'};a.state.overview=overview(scopes[0]);delete a.state.overview.autonomous_workflow;a.render();assert.match(a.html(),/当前账套尚未启用自主处理/);assert.doesNotMatch(a.html(),/data-action="bookkeeping-save"/);
  a.clearSession();a.respond(async url=>url==='/api/v1/auth/me'?{user_id:'new-user',role:'accountant',csrf_token:'new-token'}:{scopes:[]});
  await a.loadPortfolio();assert.match(a.html(),/新建企业开始办理/);assert.equal(a.state.user.user_id,'new-user');assert(!a.element('globalNav').classList.contains('hidden'));
});

test('mobile sidebar includes global links in its focus cycle and restores the opener',()=>{
  const a=app(),first=a.element('first-menu'),link=a.element('portfolio-link'),last=a.element('last-scope'),hidden=a.element('hidden-login'),disabled=a.element('disabled-item');
  link.tagName='A';hidden.getClientRects=()=>[];disabled.disabled=true;
  a.element('sidebar').querySelectorAll=selector=>{assert.match(selector,/a\[href\]/);return [hidden,first,link,disabled,last];};
  a.openSidebar();assert.equal(a.document.activeElement,first);assert.equal(a.element('main').inert,true);assert.equal(a.element('openSidebar').getAttribute('aria-expanded'),'true');assert(a.sidebarFocusables().includes(link));
  let prevented=0;last.focus();for(const fn of a.listeners.keydown)fn({target:last,key:'Tab',shiftKey:false,preventDefault(){prevented++;}});assert.equal(a.document.activeElement,first);
  for(const fn of a.listeners.keydown)fn({target:first,key:'Tab',shiftKey:true,preventDefault(){prevented++;}});assert.equal(a.document.activeElement,last);assert.equal(prevented,2);
  for(const fn of a.listeners.keydown)fn({target:last,key:'Escape'});assert.equal(a.element('main').inert,false);assert.equal(a.document.activeElement.id,'openSidebar');assert.equal(a.element('openSidebar').getAttribute('aria-expanded'),'false');
});

test('a timer created on the workbench cannot reload after navigating to settings',async()=>{
  const a=app();a.state.overview.autonomous_workflow.status='ANALYZING';a.scheduleAutonomousPoll();const callback=[...a.timers.values()][0];assert.equal(typeof callback,'function');
  a.settings();await callback();assert.equal(a.calls.length,0);assert.equal(a.state.view,'settings');
});

test('settings deep link restores the authorized selected company after login',async()=>{
  const a=app();a.context.location.hash='#settings';
  a.saved.set('finwise.operator.scope',a.scopeKey(scopes[1]));
  a.respond(async(url,body)=>url==='/api/v1/auth/me'?{user_id:'operator-a',role:'accountant'}:url==='/api/v1/portfolio'?{scopes:a.state.scopes}:overview(body.scope));
  await a.loadPortfolio();assert.equal(a.state.view,'settings');assert.equal(a.state.selected,1);
  assert.match(a.html(),/乙公司/);assert.match(a.html(),/id="bookkeepingMode"/);
  a.context.location.protocol='http:';a.context.location.pathname='/static/operator.html';a.context.location.search='';
  const urls=[];a.context.history={replaceState:(_,title,url)=>urls.push(url)};
  a.actions.workbench();assert.equal(urls.at(-1),'/static/operator.html');
  a.actions.settings();assert.equal(urls.at(-1),'/static/operator.html#settings');
});

test('enterprise links override saved selection and reject unauthorized scopes',async()=>{
  const a=app();a.context.URLSearchParams=URLSearchParams;
  a.saved.set('finwise.operator.scope',a.scopeKey(scopes[0]));
  a.context.location.search='?scope='+encodeURIComponent(a.scopeKey(scopes[1]));
  a.respond(async(url,body)=>url==='/api/v1/auth/me'?{user_id:'operator-a',role:'accountant'}:url==='/api/v1/portfolio'?{scopes:a.state.scopes}:overview(body.scope));
  await a.loadPortfolio();assert.equal(a.state.selected,1);
  a.context.location.search='?scope=not-authorized';await a.loadPortfolio();
  assert.equal(a.state.selected,null);assert.equal(a.state.overview,null);assert.match(a.element('notice').textContent,/不可访问/);
});

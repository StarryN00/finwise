const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../static/operator-profile-cards.js'),'utf8');
const main=fs.readFileSync(path.join(__dirname,'../static/operator.js'),'utf8');
const escapedCode=main.slice(main.indexOf('const esc ='),main.indexOf('const label ='));

function card(overrides){
 return Object.assign({
  version:'profile-card-v1', card_type:'SOURCE_PROFILE_CONFIRM', title:'确认这份文件的结构：某行流水.xlsx',
  why:{facts:'交易日期＝交易时间；支出＝借；收入＝贷', rule:'表头行 1；余额连续性通过率 100%（比对 12 次）',
       recommendation:'识别可信，确认后同模板文件不再询问', origin:'AGENT', confidence:95,
       yields:{kind:'SOURCE_PROFILE', key:'fp1', summary:'s', scope_level:'ENTITY'}, evidence:[]},
  options:[{id:'confirm_profile',label:'确认'},{id:'designate_profile_columns',label:'我改一下'}],
  artifact:{id:'source-1',version:2}, sheet:'数据', document_kind:'bank_statement'
 }, overrides||{});
}

function app(options){
 const opts=options||{};
 const requests=[];
 const context=vm.createContext({
  state:{epoch:1,sessionEpoch:1,role:opts.role||'operator',user:{user_id:'u1'},view:'profile-cards',overview:{period:{status:'OPEN'}}},
  scope:()=>({tenant_id:'t',legal_entity_id:'e',accounting_period_id:'2026-01'}),
  scopeKey:s=>JSON.stringify(s),
  readonly:()=>opts.role==='viewer',
  request:async(path,body)=>{requests.push({path,body});if(opts.fail&&path.endsWith('/confirm'))throw new Error('确认失败：版式冲突');return opts.cards!==undefined&&path==='/api/v1/profile-cards'?{cards:opts.cards,count:opts.cards.length}:{};},
  command:async(...args)=>{requests.push({command:args[0],id:args[1]});return opts.parseResult===undefined?{effect:{artifact:{data:{parse_status:'PARSED',parse_counts:{rows:50}}}}}:opts.parseResult;},
  loadWorkbench:async()=>{requests.push({reload:true});},
  fileById:id=>({object_id:id,version:2,data:{parse_options:{document_kind:'bank_statement'}}}),
  exclusive:async fn=>fn(),
  actions:{},
  render:()=>{},
  requests,
 });
 vm.runInContext(escapedCode+source,context);
 return context;
}

test('未加载时显示读取中，不谎称没有待办',()=>{
 const c=app();
 assert.match(c.renderProfileCards(),/正在读取待确认结构/);
});

test('没有卡片时给出明确的空状态而不是空白',()=>{
 const c=app();const ui=c.profileCardState();ui.loaded=true;ui.cards=[];
 const html=c.renderProfileCards();
 assert.match(html,/没有待确认的结构/);
 assert.match(html,/新上传一份陌生格式时/);
});

test('高置信卡片展示列对应关系与余额证据，并提供两个选项',()=>{
 const c=app();const ui=c.profileCardState();ui.loaded=true;ui.cards=[card()];
 const html=c.renderProfileCards();
 assert.match(html,/识别置信度 95%/);
 assert.match(html,/支出＝借/);
 assert.match(html,/余额连续性通过率 100%（比对 12 次）/);
 assert.match(html,/data-action="profile-card-confirm"/);
 assert.match(html,/data-action="profile-card-designate"/);
 assert.match(html,/badge green/);
});

test('低置信卡片用不同的视觉语气并提示先核对',()=>{
 const c=app();const ui=c.profileCardState();ui.loaded=true;
 ui.cards=[card({why:Object.assign({},card().why,{confidence:25,recommendation:'证据偏少，请核对列的对应关系后再确认'})})];
 const html=c.renderProfileCards();
 assert.match(html,/badge yellow/);
 assert.match(html,/请核对列的对应关系/);
});

test('认不出的文件不给确认按钮，只请人工指认',()=>{
 const c=app();const ui=c.profileCardState();ui.loaded=true;
 ui.cards=[card({card_type:'SOURCE_PROFILE_UNKNOWN',why:Object.assign({},card().why,{confidence:0})})];
 const html=c.renderProfileCards();
 assert.equal(/data-action="profile-card-confirm"/.test(html),false);
 assert.match(html,/我来指认各列/);
 assert.match(html,/badge red/);
});

test('只读角色看得到卡片但不能确认',()=>{
 const c=app({role:'viewer'});const ui=c.profileCardState();ui.loaded=true;ui.cards=[card()];
 assert.match(c.renderProfileCards(),/data-action="profile-card-confirm"[^>]*disabled/);
});

test('卡片正文经过转义，原件文件名不能注入标记',()=>{
 const c=app();const ui=c.profileCardState();ui.loaded=true;
 ui.cards=[card({title:'确认结构：<img src=x onerror=alert(1)>.xlsx'})];
 const html=c.renderProfileCards();
 assert.equal(html.includes('<img src=x'),false);
 assert.match(html,/&lt;img/);
});

test('确认后依次调用确认接口、重新解析、刷新工作台',async()=>{
 const c=app();const ui=c.profileCardState();ui.loaded=true;ui.cards=[card()];
 c.installProfileCardActions();
 await c.actions['profile-card-confirm']({dataset:{profileCard:'source-1::数据'}});
 const paths=c.requests.map(r=>r.path||r.command||(r.reload?'reload':''));
 assert.deepEqual(paths.slice(0,3),['/api/v1/profile-cards/confirm','parse_artifact','reload']);
 assert.match(c.profileCardState().feedback,/结构已确认并登记，该原件已按新结构提取 50 条记录/);
});

test('重新解析仍未通过时如实报告，不谎称已识别',async()=>{
 const c=app({parseResult:{effect:{artifact:{data:{parse_status:'RECONCILIATION_FAILED',parse_counts:{rows:0}}}}}});
 const ui=c.profileCardState();ui.loaded=true;ui.cards=[card()];
 c.installProfileCardActions();
 await c.actions['profile-card-confirm']({dataset:{profileCard:'source-1::数据'}});
 assert.match(c.profileCardState().feedback,/仍未通过（RECONCILIATION_FAILED）/);
 assert.equal(/已按新结构提取/.test(c.profileCardState().feedback),false);
});

test('确认失败时展示错误且不留下卡住的进行中状态',async()=>{
 const c=app({fail:true,cards:[]});const ui=c.profileCardState();ui.loaded=true;ui.cards=[card()];
 c.installProfileCardActions();
 await c.actions['profile-card-confirm']({dataset:{profileCard:'source-1::数据'}});
 assert.match(c.profileCardState().error,/确认失败/);
 assert.equal(c.profileCardState().pending,'');
});

test('切换企业或期间会清空卡片状态，不串场',()=>{
 const c=app();const ui=c.profileCardState();ui.loaded=true;ui.cards=[card()];ui.feedback='上一家的提示';
 vm.runInContext("scope=()=>({tenant_id:'t',legal_entity_id:'e2',accounting_period_id:'2026-02'});",c);
 const fresh=c.profileCardState();
 assert.equal(fresh.cards.length,0);
 assert.equal(fresh.loaded,false);
 assert.equal(fresh.feedback,'');
});

test('角标只在有待确认卡片时出现',()=>{
 const c=app();const ui=c.profileCardState();
 assert.equal(c.profileCardBadge(),'');
 ui.loaded=true;ui.cards=[card(),card({sheet:'Sheet2'})];
 assert.match(c.profileCardBadge(),/待确认结构 2/);
});

test('卡片按钮不使用 data-card，避免与既有对象详情分发冲突',()=>{
 const c=app();const ui=c.profileCardState();ui.loaded=true;ui.cards=[card()];
 const html=c.renderProfileCards();
 assert.equal(/\sdata-card=/.test(html),false);
 assert.match(html,/data-profile-card="source-1::数据"/);
});

test('认不出的卡片不承诺"确认后登记版式"，因为没有可确认的东西',()=>{
 const c=app();const ui=c.profileCardState();ui.loaded=true;
 ui.cards=[card({card_type:'SOURCE_PROFILE_UNKNOWN',why:Object.assign({},card().why,{confidence:0,yields:null})})];
 const html=c.renderProfileCards();
 assert.equal(/确认后登记为/.test(html),false);
});

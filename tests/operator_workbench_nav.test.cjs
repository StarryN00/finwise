// 首页原来 8–9 个文字按钮平铺一行，动作和查看入口混在一起。收成
// 「动作在外 + 本期详情折叠」之后要盯住三件事：动作没被折进去、
// 有待办时不会被藏起来、以及 .secondary-nav 仍然是第一个 ——
// installHistoricalActions 靠 querySelector('.secondary-nav') 往里追加按钮。
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../static/operator.js'),'utf8');

function app({badge=0,role='accountant'}={}) {
  const nodes=new Map();
  const context=vm.createContext({location:{protocol:'file:'},document:{
    addEventListener(){},getElementById(id){
      if(!nodes.has(id))nodes.set(id,{addEventListener(){}});
      return nodes.get(id);
    }
  }});
  vm.runInContext(source+';globalThis.api={state,workbenchNav};',context);
  context.profileCardBadgeCount=()=>badge;
  const {state}=context.api;
  state.role=role;state.scopes=[{scope:{accounting_period_id:'2026-08'}}];state.selected=0;
  return context.api;
}
const buttons=html=>[...html.matchAll(/data-action="([a-z-]+)"/g)].map(m=>m[1]);
const inFold=html=>buttons(html.slice(html.indexOf('<details')));
const outside=html=>buttons(html.slice(0,html.indexOf('<details')));

test('actions stay out, the six view entrances fold away',()=>{
  const html=app().workbenchNav();

  assert.deepEqual(outside(html),['upload','refresh'],'补充资料和刷新状态是动作，不该折进去');
  assert.deepEqual(inFold(html),
    ['artifacts','groups','vouchers','voucher-proposals-open','profile-cards-open','history']);
  assert.match(html,/本期详情 · 6 项/);
});

test('the actions nav keeps its class and comes first, so the history button still lands with the actions',()=>{
  const html=app().workbenchNav();

  // installHistoricalActions 做的是 querySelector('.secondary-nav')，取第一个匹配。
  assert.ok(html.indexOf('class="secondary-nav"')<html.indexOf('<details'));
  assert.equal((html.match(/class="secondary-nav"/g)||[]).length,1,'折叠里那个用 .detail-nav，否则会抢走追加位置');
  assert.match(html,/<nav class="secondary-nav"[^>]*>[\s\S]*data-action="upload"/);
});

test('pending work is never silently hidden behind the fold',()=>{
  const html=app({badge:3}).workbenchNav();

  assert.match(html,/<details class="decision-more-options" open>/,'有待办就默认展开');
  assert.match(html,/本期详情 · 6 项 · 待确认 3/,'件数要出现在收起时也看得见的地方');
  assert.match(html,/待确认事项 3</);
});

test('with nothing pending the fold stays shut and says nothing about counts',()=>{
  const html=app({badge:0}).workbenchNav();

  assert.doesNotMatch(html,/ open>/);
  assert.doesNotMatch(html,/待确认 0/);
  assert.match(html,/待确认事项</,'没有件数时仍然是一个入口，只是不带数字');
});

test('a read-only account cannot add material but can still look around',()=>{
  const html=app({role:'viewer'}).workbenchNav();

  assert.match(html,/data-action="upload" disabled/);
  assert.doesNotMatch(html,/data-action="refresh" disabled/);
  for(const action of inFold(html))assert.doesNotMatch(html,new RegExp(`data-action="${action}" disabled`));
});

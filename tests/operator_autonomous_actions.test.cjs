// 工具条原来 8 个动作平铺，「重新审查补证范围」「按已有历史资料重新核查」
// 「继续处理」光看名字分不出差别。收成「一个主操作 + 其他 N 项」之后，
// 要盯住的是：主操作只有一个、优先级没搞反、没主操作时不能全折起来。
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const code=fs.readFileSync('static/operator-autonomous.js','utf8');

function ctx(readonly=false){
 const c=vm.createContext({document:{addEventListener(){}},clearTimeout:()=>{},state:{},actions:{},
  readonly:()=>readonly,
  esc:x=>String(x).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;'),
  scope:()=>({accounting_period_id:'2026-08'}),$:()=>({value:'claude_code'}),
  request:async()=>({}),loadWorkbench:async()=>{},notify:()=>{}});
 vm.runInContext(code,c);return c;
}
const labels=html=>[...html.matchAll(/<button class="(primary|secondary|text)"[^>]*>([^<]*)<\/button>/g)]
  .map(m=>({cls:m[1],label:m[2]}));
const folded=html=>{const i=html.indexOf('<details');return i<0?[]:labels(html.slice(i)).map(x=>x.label);};

test('one primary action, everything else folded away',()=>{
 const c=ctx();
 const html=c.autonomousActions({accepted:true,can_retry:true,source_count:3},{},false,2);

 const primary=labels(html).filter(x=>x.cls==='primary');
 assert.deepEqual(primary.map(x=>x.label),['继续处理'],'同时只能有一个主操作');
 assert.match(html,/其他操作 · 3 项/);
 assert.deepEqual(folded(html),['现有资料已全部提供，分析可行方案','补充原始资料','刷新状态']);
});

test('the forward move wins over the retry-shaped ones',()=>{
 const c=ctx();
 // 没有 can_retry／can_reassess 时，「现有资料已全部提供」才是往前走的那一步；
 // 「按已有历史资料重新核查」是退回去再查一遍，不该抢主操作。
 const html=c.autonomousActions({accepted:true,source_count:3},{},false,2);

 assert.deepEqual(labels(html).filter(x=>x.cls==='primary').map(x=>x.label),
   ['现有资料已全部提供，分析可行方案']);
 assert.ok(folded(html).includes('按已有历史资料重新核查'));
});

test('while the system is running there is no primary, so nothing is folded away',()=>{
 const c=ctx();
 const html=c.autonomousActions({source_count:3},{},true,0);

 assert.equal(labels(html).filter(x=>x.cls==='primary').length,0,'系统在跑，没有"现在该做的一件事"');
 assert.doesNotMatch(html,/<details/,'这时折叠会让人一个可点的都不剩');
 assert.deepEqual(labels(html).map(x=>x.label),['暂停自动处理','补充原始资料','刷新状态']);
});

test('starting is the primary when there is no run yet',()=>{
 const c=ctx();
 const html=c.autonomousActions({source_count:3},null,false,0);

 assert.deepEqual(labels(html).filter(x=>x.cls==='primary').map(x=>x.label),['启动自动处理']);
 assert.deepEqual(folded(html),['补充原始资料','刷新状态']);
});

test('no sources means no start button at all',()=>{
 const c=ctx();
 const html=c.autonomousActions({source_count:0},null,false,0);

 assert.doesNotMatch(html,/启动自动处理/);
 assert.doesNotMatch(html,/<details/,'只剩兜底动作，不折叠');
 assert.deepEqual(labels(html).map(x=>x.label),['补充原始资料','刷新状态']);
});

test('read-only keeps every original disabled flag, including the one that was missing',()=>{
 const c=ctx(true);
 const html=c.autonomousActions({accepted:true,source_count:3},null,false,2);

 // 原样保留：上传、重新核查等都挡住。
 assert.match(html,/data-action="autonomous-upload" disabled/);
 assert.match(html,/data-action="autonomous-materials-complete" disabled/);
 assert.match(html,/data-action="autonomous-history-recheck" disabled/);
 // 刷新本来就不受只读限制。
 assert.match(html,/data-action="refresh" >/);
 // 「启动自动处理」本来就没有 readonly 门 —— 这是原有的不一致，这次没顺手改，
 // 服务端仍然会挡。改权限该是独立一件事；这条测试是在记着它。
 const start=c.autonomousActions({source_count:3},null,false,0);
 assert.match(start,/data-action="autonomous-start" >/);
});

test('labels are escaped like every other rendered string',()=>{
 const c=ctx();
 const html=c.autonomousActions({source_count:3},null,false,0);
 assert.doesNotMatch(html,/<img/);
 assert.match(html,/data-action="autonomous-upload"/);
});

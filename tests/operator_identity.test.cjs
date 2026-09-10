const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
function app(display_context) {
  const nodes=new Map();
  const context=vm.createContext({location:{protocol:'file:'},document:{addEventListener(){},getElementById(id){
    if(!nodes.has(id))nodes.set(id,{value:'',innerHTML:'',addEventListener(){}});return nodes.get(id);
  }}});
  vm.runInContext(fs.readFileSync('static/operator.js','utf8')+';globalThis.api={state,renderScopes,renderContext};',context);
  const item={scope:{legal_entity_id:'kunshan-juxianda',ledger_id:'chengyuan-ledger',accounting_period_id:'2026-01'},display_context,
    blockers:[],baseline:{validation:{status:'DRAFT'}},pending_confirmation_cards:0,period:{status:'OPEN'}};
  context.api.state.scopes=[item];context.api.state.selected=0;context.api.state.overview=item;
  return {...context.api,nodes,item};
}
test('missing license is explicit and default ledger is Chinese',()=>{
  const a=app();a.renderScopes();
  assert.match(a.nodes.get('scopeList').innerHTML,/营业执照编号待补充/);
  assert.doesNotMatch(a.nodes.get('scopeList').innerHTML,/chengyuan-ledger/);
  assert.match(a.renderContext(),/主账套/);
  assert.equal(a.item.scope.ledger_id,'chengyuan-ledger');
  a.nodes.get('search').value='主账套';a.renderScopes();assert.match(a.nodes.get('scopeList').innerHTML,/data-scope="0"/);
});
test('saved license and custom ledger are escaped and searchable',()=>{
  const a=app({business_license_number:'TEST-001',ledger_name:'二账套 <script>',company_name:'企业甲'});
  a.nodes.get('search').value='TEST-001';a.renderScopes();assert.match(a.nodes.get('scopeList').innerHTML,/TEST-001/);
  assert.match(a.renderContext(),/二账套 &lt;script&gt;/);
  a.nodes.get('search').value='二账套';a.renderScopes();assert.match(a.nodes.get('scopeList').innerHTML,/企业甲/);
  a.nodes.get('search').value='不存在';a.renderScopes();assert.match(a.nodes.get('scopeList').innerHTML,/没有匹配/);
});

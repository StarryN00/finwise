const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../static/operator-new-scope.js'),'utf8');
const main=fs.readFileSync(path.join(__dirname,'../static/operator.js'),'utf8');
const escapedCode=main.slice(main.indexOf('const esc ='),main.indexOf('const label ='));

function app(fields,opts){
 const values=Object.assign({newScopeAgency:'',newScopeEntity:'',newScopeLedger:'',newScopePeriod:''},fields||{});
 const options=opts||{};
 const calls=[],elements={};
 const el=id=>elements[id]||(elements[id]={value:values[id]!==undefined?values[id]:'',innerHTML:'',disabled:false,
   addEventListener(){},focus(){}});
 Object.keys(values).forEach(el);
 const c=vm.createContext({
  state:{scopes:options.scopes||[],selected:null},
  $:el, esc:null, actions:{}, calls,
  openDialog:(title,html)=>calls.push({dialog:title,html}),
  closeDialog:()=>calls.push({closed:true}),
  notify:m=>calls.push({notify:m}),
  request:async(p,b)=>{calls.push({path:p,body:b});if(options.fail)throw new Error('该处理范围已存在，请联系管理员授权后使用');return {};},
  loadPortfolio:async()=>{calls.push({portfolio:true});if(options.afterCreate)c.state.scopes=options.afterCreate;},
  selectScope:async i=>{calls.push({selected:i});},
  scopeKey:s=>JSON.stringify(s),
 });
 vm.runInContext(escapedCode+source,c);
 return c;
}

test('六段 Scope 由三个业务字段派生，基线含账套避免不同账套撞键',()=>{
 const c=app();
 const d=c.newScopeDerive('昆山某代账','昆山荣鼎坤机械科技有限公司','2026-06','');
 assert.deepEqual(Object.keys(d).sort(),['accounting_period_id','baseline_id','ledger_id','legal_entity_id','organization_id','tenant_id'].sort());
 assert.equal(d.legal_entity_id,'昆山荣鼎坤机械科技有限公司');
 assert.equal(d.ledger_id,'主账套');
 assert.equal(d.baseline_id,'昆山荣鼎坤机械科技有限公司-主账套-2026-06');
 const second=c.newScopeDerive('昆山某代账','昆山荣鼎坤机械科技有限公司','2026-06','外币账套');
 assert.notEqual(second.baseline_id,d.baseline_id);
});

test('字段不全或期间格式不对时不给出处理范围',()=>{
 const c=app();
 assert.equal(c.newScopeDerive('','企业','2026-06',''),null);
 assert.equal(c.newScopeDerive('机构','','2026-06',''),null);
 assert.equal(c.newScopeDerive('机构','企业','2026年6月',''),null);
 assert.equal(c.newScopeDerive('机构','企业','2026-6',''),null);
 assert.equal(c.newScopeDerive('  ','企业','2026-06',''),null);
});

test('派生结果原样展示，系统实际用的键对操作人可见',()=>{
 const c=app({newScopeAgency:'昆山某代账',newScopeEntity:'昆山荣鼎坤机械科技有限公司',newScopePeriod:'2026-06'});
 c.newScopePreview();
 const html=c.$('newScopePreview').innerHTML;
 assert.match(html,/legal_entity_id/);
 assert.match(html,/昆山荣鼎坤机械科技有限公司-主账套-2026-06/);
 assert.equal(c.$('newScopeSubmit').disabled,false);
});

test('字段不全时提交按钮保持禁用',()=>{
 const c=app({newScopeEntity:'企业'});
 c.newScopePreview();
 assert.equal(c.$('newScopeSubmit').disabled,true);
 assert.match(c.$('newScopePreview').innerHTML,/填齐/);
});

test('企业名称中的标记被转义，不能注入到预览里',()=>{
 const c=app({newScopeAgency:'机构',newScopeEntity:'<img src=x onerror=alert(1)>',newScopePeriod:'2026-06'});
 c.newScopePreview();
 const html=c.$('newScopePreview').innerHTML;
 assert.equal(html.includes('<img src=x'),false);
 assert.match(html,/&lt;img/);
});

test('提交后开设、刷新列表并自动选中新开的范围',async()=>{
 const derived={tenant_id:'机构',organization_id:'机构',legal_entity_id:'企业',ledger_id:'主账套',
                accounting_period_id:'2026-06',baseline_id:'企业-主账套-2026-06'};
 const c=app({newScopeAgency:'机构',newScopeEntity:'企业',newScopePeriod:'2026-06'},
             {afterCreate:[{scope:derived}]});
 await c.submitNewScope();
 assert.equal(c.calls[0].path,'/api/v1/scopes/provision');
 assert.equal(JSON.stringify(c.calls[0].body),JSON.stringify(derived));
 assert.equal(c.calls[1].closed,true);
 assert.equal(c.calls[2].portfolio,true);
 assert.equal(c.calls[3].selected,0);
 assert.match(c.calls[4].notify,/已开设 企业 2026-06/);
});

test('开设失败时不关闭对话框也不谎报成功',async()=>{
 const c=app({newScopeAgency:'机构',newScopeEntity:'企业',newScopePeriod:'2026-06'},{fail:true});
 await assert.rejects(()=>c.submitNewScope(),/已存在/);
 assert.equal(c.calls.some(x=>x.closed),false);
 assert.equal(c.calls.some(x=>x.notify),false);
});

test('机构与期间默认沿用已有范围，少填两次',()=>{
 const c=app({},{scopes:[{scope:{organization_id:'昆山某代账',accounting_period_id:'2026-05'}}]});
 const d=c.newScopeDefaults();
 assert.equal(d.agency,'昆山某代账');
 assert.equal(d.period,'2026-05');
});

test('没有任何已有范围时期间默认当月',()=>{
 const c=app();
 assert.match(c.newScopeDefaults().period,/^\d{4}-\d{2}$/);
 assert.equal(c.newScopeDefaults().agency,'');
});

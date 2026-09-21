const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../static/operator-voucher-proposals.js'),'utf8');
const main=fs.readFileSync(path.join(__dirname,'../static/operator.js'),'utf8');
const escapedCode=main.slice(main.indexOf('const esc ='),main.indexOf('const label ='));

function item(o){
 return Object.assign({
  fact:{id:'fact-1',version:1},
  transaction:{date:'2026-08-03',summary:'购买矿泉水',counterparty:'侯文军',amount:'91.53',direction:'PAYMENT'},
  account_hint:{account_code:'560202',account_name:'办公费',why:'历史上“报销”记过 17 次办公费'},
  proposal:{outcome:'PROPOSAL',confidence:90,reason:'',basis:['学自 33 张历史凭证（记-001、记-014）','经往来科目 224101 过渡'],
    lines:[{account_code:'560202',account_name:'办公费',debit:'91.53',credit:'0.00'},
           {account_code:'224101',account_name:'侯文军',debit:'0.00',credit:'91.53'},
           {account_code:'224101',account_name:'侯文军',debit:'91.53',credit:'0.00'},
           {account_code:'100201',account_name:'江苏银行0758',debit:'0.00',credit:'91.53'}]}
 }, o||{});
}
function abstained(reason,o){
 return item(Object.assign({proposal:{outcome:'ABSTAIN',confidence:0,reason,basis:[],lines:[]}},o||{}));
}
function body(o){
 return Object.assign({
  learned:{artifact:{id:'a'},periods:['2026-01','2026-07'],vouchers:201,templates:42,accounts:32},
  counts:{transactions:35,proposed:18,abstained:17,adoptable:6},
  proposals:[item()], abstained:[abstained('没有“黄鹏飞”的历史做法可循')],
 }, o||{});
}

function app(data,opts){
 const options=opts||{};
 const c=vm.createContext({
  state:{user:{user_id:'u1'},view:'voucher-proposals'},
  scope:()=>({tenant_id:'t',legal_entity_id:'e'}), scopeKey:s=>JSON.stringify(s),
  actions:{}, render:()=>{},
  request:async()=>{if(options.fail)throw new Error('读取失败');return data;},
 });
 vm.runInContext(escapedCode+source,c);
 if(data!==undefined){const ui=c.voucherProposalState();ui.loaded=true;ui.data=data;}
 return c;
}

test('未加载完成时说明正在生成，不谎称没有提案',()=>{
 const c=app();
 assert.match(c.renderVoucherProposals(),/正在按历史做法生成凭证提案/);
});

test('没有历史凭证时说清原因，并说明为什么需要它',()=>{
 const c=app({learned:null,reason:'尚未上传历史凭证，无法参照既有做法'});
 const html=c.renderVoucherProposals();
 assert.match(html,/尚未上传历史凭证/);
 assert.match(html,/照着他们自己的做账习惯/);
});

test('学习来源如实展示，不含糊成"AI 生成"',()=>{
 const c=app(body());
 const html=c.renderVoucherProposals();
 assert.match(html,/学自 201 张历史凭证/);
 assert.match(html,/2026-01 至 2026-07/);
 assert.match(html,/42 个往来对象、32 个在用科目/);
});

test('按置信度分三档，默认停在需核对',()=>{
 const c=app(body({proposals:[item(),item({fact:{id:'f2',version:1},
   proposal:Object.assign({},item().proposal,{confidence:60})})]}));
 const html=c.renderVoucherProposals();
 assert.match(html,/可直接过 1/);
 assert.match(html,/需核对 1/);
 assert.match(html,/提不出 1/);
 assert.match(html,/data-filter="review"[^>]*aria-pressed="true"/);
});

test('提案逐行展示科目与借贷',()=>{
 const c=app(body());
 c.voucherProposalState().filter='auto';
 const html=c.renderVoucherProposals();
 assert.match(html,/560202/); assert.match(html,/224101/); assert.match(html,/100201/);
 assert.match(html,/江苏银行0758/);
 assert.match(html,/置信 90/);
});

test('可直接过的那一档仍然提醒要看一眼',()=>{
 const c=app(body()); c.voucherProposalState().filter='auto';
 assert.match(c.renderVoucherProposals(),/科目记错不会报错，只会成为一条错账/);
});

test('依据默认收起，点开才显示学自哪些凭证',()=>{
 const c=app(body()); c.voucherProposalState().filter='auto';
 c.installVoucherProposalActions();
 assert.equal(/记-001、记-014/.test(c.renderVoucherProposals()),false);
 c.actions['voucher-proposal-basis']({dataset:{proposal:'fact-1'}});
 assert.match(c.renderVoucherProposals(),/学自 33 张历史凭证（记-001、记-014）/);
});

test('提不出的按原因归并，不逐笔追问',()=>{
 const c=app(body({abstained:[
   abstained('没有“待报解预算收入”的历史做法可循',{fact:{id:'a1',version:1}}),
   abstained('没有“待报解预算收入”的历史做法可循',{fact:{id:'a2',version:1}}),
   abstained('这笔流水没有对方户名',{fact:{id:'a3',version:1}})]}));
 c.voucherProposalState().filter='abstained';
 const html=c.renderVoucherProposals();
 assert.match(html,/提不出凭证 3 笔/);
 assert.match(html,/没有“待报解预算收入”的历史做法可循<\/strong> 2 笔/);
 assert.match(html,/同一个原因处理一次，不逐笔追问/);
});

test('切换筛选只改视图，不重新请求',async()=>{
 const c=app(body());
 c.installVoucherProposalActions();
 c.actions['voucher-proposal-filter']({dataset:{filter:'auto'}});
 assert.equal(c.voucherProposalState().filter,'auto');
 assert.equal(c.voucherProposalState().data.counts.transactions,35);
});

test('读取失败时显示错误而不是空白',async()=>{
 const c=app(undefined,{fail:true});
 await c.loadVoucherProposals();
 assert.match(c.voucherProposalState().error,/读取失败/);
 assert.match(c.renderVoucherProposals(),/读取失败/);
});

test('摘要与对方经过转义',()=>{
 const c=app(body({proposals:[item({transaction:{date:'2026-08-03',
   summary:'<img src=x onerror=alert(1)>',counterparty:'甲',amount:'1.00',direction:'PAYMENT'}})]}));
 c.voucherProposalState().filter='auto';
 const html=c.renderVoucherProposals();
 assert.equal(html.includes('<img src=x'),false);
 assert.match(html,/&lt;img/);
});

test('切换企业或期间会清空提案，不串场',()=>{
 const c=app(body());
 vm.runInContext("scope=()=>({tenant_id:'t',legal_entity_id:'e2'});",c);
 const fresh=c.voucherProposalState();
 assert.equal(fresh.data,null); assert.equal(fresh.loaded,false);
});

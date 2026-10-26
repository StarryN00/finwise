const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const src=fs.readFileSync(path.join(__dirname,'../static/operator-material-guidance.js'),'utf8');
function ctx(){const c=vm.createContext({});vm.runInContext(src+';globalThis.api={materialGuidancePlainReason,materialGuidancePlainText};',c);return c.api;}
// agent 的结论必须原样出现在卡片上。拿关键词套模板会让两张不同的建议卡显示同一句话。
test('the card shows what the agent actually said',()=>{
 const {materialGuidancePlainReason}=ctx();
 const own='开票日期与税款所属期不一致，需确认费用归属期间；建议补充归属期间说明或相关凭证。';
 assert.equal(materialGuidancePlainReason({reason:own},'确认业务期间归属'),own);
});
test('two different suggestions do not collapse into the same sentence',()=>{
 const {materialGuidancePlainReason}=ctx();
 const a=materialGuidancePlainReason({reason:'这笔付款缺少银行账户信息，建议先请对方补充账户资料。'},'补充可核验依据');
 const b=materialGuidancePlainReason({reason:'暂时拿不到账户资料，建议先暂缓并保留问题。'},'暂缓并保留问题');
 assert.notEqual(a,b);
});
test('internal wording is still translated out',()=>{
 const {materialGuidancePlainReason}=ctx();
 assert.match(materialGuidancePlainReason({reason:'record-1 的门禁未解除'},''),/这笔记录/);
 assert.doesNotMatch(materialGuidancePlainReason({reason:'record-1 的门禁未解除'},''),/门禁/);
});
test('an over-long or missing reason falls back to the plain house sentence',()=>{
 const {materialGuidancePlainReason}=ctx();
 const long='银行'+'很长的旧式说明'.repeat(20);
 assert.notEqual(materialGuidancePlainReason({reason:long},'银行'),long);
 assert.match(materialGuidancePlainReason({reason:long},'银行'),/银行账户/);
 assert.match(materialGuidancePlainReason({},''),/进一步确认/);
});

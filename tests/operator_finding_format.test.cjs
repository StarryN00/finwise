const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const main=fs.readFileSync(path.join(__dirname,'../static/operator.js'),'utf8');
const code=fs.readFileSync(path.join(__dirname,'../static/operator-autonomous.js'),'utf8');
const c=vm.createContext({});
vm.runInContext(main.slice(main.indexOf('const esc ='),main.indexOf('const label ='))+code.slice(code.indexOf('function findingEmphasis('),code.indexOf('function renderAutonomous(')),c);
const original='OCR与实际目视均为2026-09-03，原账记-033日期2026-08-31。2491.57等于7月个税期末应付，金额链成立不能确定支付期间。保留原日期，请补银行正式回单/更正对账单及完税凭证确认实际扣款日；暂不提出确定改日分录。';
test('formatting preserves every original sentence and caveat in order',()=>{
 const html=c.renderFindingDetail(original);
 const text=[...html.matchAll(/<li>(.*?)<\/li>/gs)].map(m=>m[1].replace(/<[^>]+>/g,'')).join('');
 assert.equal(text,original);
 assert.match(html,/finding-action[^]*请补银行正式回单/);
 assert.match(html,/finding-caution[^]*暂不提出确定改日分录/);
 for(const token of ['2026-09-03','2026-08-31','2491.57','记-033'])assert.ok(html.includes(`class="finding-value">${token}</strong>`));
});
test('untrusted source text cannot inject HTML or executable attributes',()=>{
 const html=c.renderFindingDetail('请补<img src=x onerror=alert(1)>，金额1.00；暂不执行<script>alert(1)</script>。');
 assert.ok(!html.includes('<img'));assert.ok(!html.includes('<script>'));
 assert.match(html,/&lt;img src=x onerror=alert\(1\)&gt;/);
});
test('negated requests are not shown as instructions and unknown prose is retained',()=>{
 const html=c.renderFindingDetail('无需补充流水，不需要用户修改日期。尚不能确认期间。');
 assert.ok(!html.includes('finding-action'));
 assert.match(html,/核查说明/);assert.match(html,/当前处理边界/);
});
test('arithmetic stays intact, including separators and rates',()=>{
 const text='银行33280.00摘要8-9月房租；净額12558.49+19017.14=31575.63，须确认6%/5%业务性质。';
 const html=c.renderFindingDetail(text);
 assert.equal([...html.matchAll(/<li>(.*?)<\/li>/gs)].map(m=>m[1].replace(/<[^>]+>/g,'')).join(''),text);
});

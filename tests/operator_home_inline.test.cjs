const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../static/operator.js'),'utf8');
// 有事要你处理时，首页直接就是那个问题和它的选项卡。
// 原来先给一张"去处理这个问题"的卡片，点进去才看到真正要做的事 —— 这是多余的一层。
test('the home page renders the problem itself, not a teaser with a button',()=>{
 assert.match(source,/inline\?renderProblemQueue\(\):/);
 assert.match(source,/next_step\?\.action\?\.kind==='MATERIAL_TASK'/);
});
test('the inline check never depends on state the home page may not have yet',()=>{
 // currentTask() 会去读 readiness()、progress 等；首页早期渲染时可能还没有。
 const line=source.split('\n').find(l=>l.includes('const inline='));
 assert(!line.includes('currentTask()'),'不能在渲染入口调用依赖完整 overview 的函数');
});
test('the dashboard layout is still used when there is nothing to handle',()=>{
 assert.match(source,/:`<div class="work-grid">/);
});

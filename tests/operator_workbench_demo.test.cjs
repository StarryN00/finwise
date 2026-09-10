const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, '../static/operator-workbench-demo.html'), 'utf8');
const source = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const model = source.split('// Browser view.')[0];

test('only current or populated stages can be viewed; selection cannot advance accounting', () => {
  const a = app(), c = company(a, 'minghe');
  a.changeStep(c, 'upload');
  assert.equal(a.derive(c).active, 1);
  assert.equal(a.canViewStage(a.derive(c), 2), false);
  assert.equal(a.chooseStage(c, 3), false);
  assert.equal(a.chooseStage(c, 4), false);
  assert.equal(a.chooseStage(c, 0), true);
  assert.equal(a.viewedStage(c), 0);
  assert.equal(a.derive(c).active, 1);
  assert.equal(a.derive(c).percent, 20);
  assert.equal(a.chooseStage(c, 1), true);
  assert.equal(a.viewedStage(c), 1);
  const partial = company(a, 'qingsong');
  assert.equal(a.chooseStage(partial, 3), true);
  assert.equal(a.chooseStage(partial, 4), true);
  assert.equal(a.derive(partial).percent, 40);
  assert.equal(a.derive(partial).blockers, 1);
});
test('obsolete detail tabs are discarded without losing notes or selecting empty stages', () => {
  const a = app(), c = company(a, 'huanyu'), r = a.runtime(c);
  r.view.detail = 'objects';
  r.view.stage = 4;
  r.draftNotes['huanyu-rule-1'] = '保留未完成备注';
  a.persist();
  const b = a.reload(), reloaded = company(b, 'huanyu');
  assert.equal('detail' in b.runtime(reloaded).view, false);
  assert.equal(b.viewedStage(reloaded), 2);
  assert.equal(b.runtime(reloaded).draftNotes['huanyu-rule-1'], '保留未完成备注');
});
function app(seed = {}, denied = false) {
  const data = new Map(Object.entries(seed));
  const context = vm.createContext({
    localStorage: {
      getItem(key) { if (denied) throw Error('denied'); return data.get(key) ?? null; },
      setItem(key, value) { if (denied) throw Error('denied'); data.set(key, value); }
    }
  });
  vm.runInContext(model + ';globalThis.api={companies,runtime,derive,recordTask,deferTask,changeStep,currentVouchers,reviewVoucher,archivePeriods,vouchersFor,filterArchiveVouchers,state,persist,scopeKey,canViewStage,viewedStage,chooseStage};', context);
  return { ...context.api, data, reload: () => app(Object.fromEntries(data), denied) };
}
function company(a, id) { return a.companies.find(c => c.id === id); }

test('archived voucher queries combine keyword and inclusive dates without changing accounting', () => {
  const a = app(), c = company(a, 'chengyuan'), p = a.archivePeriods(c)[0];
  const before = JSON.stringify(a.runtime(c));
  for (const [query, count] of [['记-002', 1], ['  管理费用  ', 3], ['费用结转', 3], ['业务组 004', 1], ['不存在', 0]]) {
    assert.equal(a.filterArchiveVouchers(c, p, { query }).length, count);
  }
  const matches = a.filterArchiveVouchers(c, p, { query: '管理费用', start: '2026-02-09', end: '2026-02-12' });
  assert.deepEqual(Array.from(matches, v => v.number), ['记-002', '记-005']);
  assert.equal(matches.reduce((sum, v) => sum + v.amount, 0), 9610000);
  assert.equal(a.filterArchiveVouchers(c, p, { start: '2026-02-15' }).length, 1);
  assert.equal(a.filterArchiveVouchers(c, p, { end: '2026-02-08' }).length, 1);
  assert.equal(a.filterArchiveVouchers(c, p, { start: '2026-01-01', end: '2026-01-31' }).length, 0);
  assert.equal(a.filterArchiveVouchers(c, p, { query: '聚贤达' }).length, 0);
  assert.equal(a.filterArchiveVouchers(c, p).length, 8);
  assert.equal(JSON.stringify(a.runtime(c)), before);
});

test('all five stages use real completion conditions; Juxianda starts at 40%', () => {
  const a = app(), c = company(a, 'juxianda'), d = a.derive(c);
  assert.equal(d.percent, 40); assert.equal(d.completed, 2);
  assert.equal(d.selected.id, 'jx-stock-gap');
  assert.equal(d.stages[2].complete, false); assert.equal(d.blockers, 1);
  assert.equal(d.pending.length, 2);
});
test('recording notes advances items without resolving evidence or accepting duplicate commands', () => {
  const a = app(), c = company(a, 'juxianda'), r = a.runtime(c);
  r.draftNotes['jx-stock-gap'] = '客户正在寻找合同';
  assert.equal(a.recordTask(c, 'jx-stock-gap'), true);
  assert.equal(a.recordTask(c, 'jx-stock-gap'), false);
  assert.equal(a.derive(c).selected.id, 'jx-payment-gap');
  assert.equal(a.recordTask(c, 'jx-payment-gap'), true);
  assert.equal(a.derive(c).recorded, 2); assert.equal(a.derive(c).percent, 40);
  assert.equal(a.derive(c).blockers, 1);
  for (const action of ['validate', 'generate', 'archive']) assert.equal(a.changeStep(c, action), false);
  const reloaded = a.reload();
  assert.equal(reloaded.runtime(company(reloaded, 'juxianda')).records['jx-stock-gap'].note, '客户正在寻找合同');
});
test('deferring does not count as completion and does not loop through deferred tasks', () => {
  const a = app(), c = company(a, 'juxianda');
  a.deferTask(c, 'jx-stock-gap'); assert.equal(a.derive(c).selected.id, 'jx-payment-gap');
  a.deferTask(c, 'jx-payment-gap'); assert.equal(a.derive(c).selected, null);
  assert.equal(a.derive(c).pending.length, 2); assert.equal(a.derive(c).recorded, 0);
});
test('new enterprise has no fictional history and can finish a gated local demo lifecycle', () => {
  const a = app(), c = company(a, 'xinqiyuan');
  assert.equal(a.derive(c).percent, 0); assert.equal(a.archivePeriods(c).length, 0);
  assert.equal(a.changeStep(c, 'analysis'), false);
  assert.equal(a.changeStep(c, 'upload'), true);
  assert.equal(a.derive(c).percent, 20); assert.equal(a.derive(c).active, 1);
  assert.equal(a.changeStep(c, 'upload'), false);
  a.changeStep(c, 'analysis');
  assert.equal(a.derive(c).percent, 40); assert.equal(a.derive(c).pending.length, 1);
  assert.equal(a.changeStep(c, 'generate'), false);
  a.recordTask(c, a.derive(c).selected.id);
  assert.equal(a.derive(c).valid, false);
  a.changeStep(c, 'validate'); assert.equal(a.derive(c).percent, 60);
  a.changeStep(c, 'generate'); assert.equal(a.reviewVoucher(c, 'v0'), true);
  assert.equal(a.reviewVoucher(c, 'v0'), false); assert.equal(a.derive(c).percent, 80);
  a.changeStep(c, 'archive'); assert.equal(a.derive(c).percent, 100);
  assert.equal(a.archivePeriods(c).length, 1);
  assert.equal(a.derive(company(a, 'minghe')).percent, 0);
});
test('partial delivery retains blocked validation and cannot imply whole-period completion', () => {
  const a = app(), c = company(a, 'qingsong'), d = a.derive(c);
  assert.equal(d.delivered, 12); assert.equal(d.blockers, 1); assert.equal(d.percent, 40);
  assert.equal(d.stages[2].complete, false); assert.equal(d.stages[3].complete, false);
  assert.equal(d.stages[4].complete, false); assert.equal(d.archived, false);
  assert.equal(a.changeStep(c, 'archive'), false);
});
test('voucher review has an auxiliary gate, matching totals and current scope only', () => {
  const a = app(), c = company(a, 'chengyuan');
  for (let i = 0; i < 3; i++) assert.equal(a.reviewVoucher(c, 'v' + i), true);
  assert.equal(a.reviewVoucher(c, 'v3'), false);
  a.runtime(c).auxConfirmed = true;
  assert.equal(a.reviewVoucher(c, 'v3'), true);
  const vouchers = a.currentVouchers(c);
  assert.equal(vouchers.reduce((sum, v) => sum + v.amount, 0), c.amount);
  for (const v of vouchers) {
    assert.equal(v.lines.reduce((sum, l) => sum + l.debit - l.credit, 0), 0);
    assert.ok(v.source.includes(c.short));
  }
});
test('legacy selection, confirmation notes and authoritative deleted tags survive migration', () => {
  const a = app({
    'finwise.operator-workbench.selected-company': 'huanyu',
    'finwise.operator-workbench.company-tags': JSON.stringify({ juxianda: [] }),
    'finwise.operator-workbench.task-state': JSON.stringify({ juxianda: { recordedIds: ['jx-stock-gap'], notes: { 'jx-stock-gap': '原有备注' } } })
  });
  assert.equal(a.state.selectedId, 'huanyu');
  assert.equal(company(a, 'juxianda').tags.length, 0);
  assert.equal(a.runtime(company(a, 'juxianda')).records['jx-stock-gap'].note, '原有备注');
  a.persist();
  const reloaded = a.reload();
  assert.equal(company(reloaded, 'juxianda').tags.length, 0);
});
test('denied or malformed storage does not prevent rendering the model or completing actions', () => {
  for (const a of [app({}, true), app({ 'finwise.operator-workbench.v5': 'null' }), app({ 'finwise.operator-workbench.v5': '{broken', 'finwise.operator-workbench.company-tags': '42' })]) {
    const c = company(a, 'juxianda');
    assert.equal(a.derive(c).percent, 40);
    assert.equal(a.recordTask(c, 'jx-stock-gap'), true);
  }
});
test('a new anomaly pauses processing without changing selection or another scope note', () => {
  const a = app(), c = company(a, 'luhai'), j = company(a, 'juxianda');
  a.runtime(j).draftNotes['jx-stock-gap'] = '正在编辑';
  a.runtime(c).alert = true;
  const d = a.derive(c);
  assert.equal(d.status, 'blocked'); assert.equal(d.stages[1].status, 'blocked');
  assert.equal(a.state.selectedId, 'juxianda');
  assert.equal(a.runtime(j).draftNotes['jx-stock-gap'], '正在编辑');
  assert.equal(a.changeStep(c, 'analysis'), false);
});

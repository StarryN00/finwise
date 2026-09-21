'use strict';

// 开设处理范围：界面只问三件业务上的事，六段 Scope 由它们派生。
// 派生结果会原样显示出来 —— 系统内部用什么键，操作人应当看得见。
function newScopeDerive(agency, entity, period, ledger) {
  const organisation = (agency || '').trim();
  const company = (entity || '').trim();
  const book = (ledger || '').trim() || '主账套';
  const month = (period || '').trim();
  if (!organisation || !company || !/^\d{4}-\d{2}$/.test(month)) return null;
  return {
    tenant_id: organisation,
    organization_id: organisation,
    legal_entity_id: company,
    ledger_id: book,
    accounting_period_id: month,
    baseline_id: `${company}-${book}-${month}`,
  };
}

function newScopeDefaults() {
  const existing = (state.scopes || [])[0]?.scope;
  const now = new Date();
  const month = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
  return {agency: existing?.organization_id || '', period: existing?.accounting_period_id || month};
}

function newScopePreview() {
  const derived = newScopeDerive($('newScopeAgency')?.value, $('newScopeEntity')?.value,
                                 $('newScopePeriod')?.value, $('newScopeLedger')?.value);
  const target = $('newScopePreview');
  if (!target) return;
  target.innerHTML = derived
    ? `<dl class="scope-preview">${Object.entries(derived).map(
        ([key, value]) => `<div><dt>${esc(key)}</dt><dd>${esc(value)}</dd></div>`).join('')}</dl>`
    : '<p class="muted small">填齐机构、企业名称和期间后，这里会显示系统实际使用的处理范围。</p>';
  const submit = $('newScopeSubmit');
  if (submit) submit.disabled = !derived;
}

function openNewScope() {
  const defaults = newScopeDefaults();
  openDialog('开设处理范围', `
    <form id="newScopeForm">
      <p class="muted small">开设一个新的企业与期间。已经存在的范围不能在这里开设，需要由管理员授权。</p>
      <label>代账机构<input id="newScopeAgency" required value="${esc(defaults.agency)}" placeholder="例如：昆山某某财务咨询"></label>
      <label>企业名称<input id="newScopeEntity" required placeholder="例如：昆山荣鼎坤机械科技有限公司"></label>
      <label>账套<input id="newScopeLedger" placeholder="留空即主账套"></label>
      <label>会计期间<input id="newScopePeriod" required value="${esc(defaults.period)}" placeholder="YYYY-MM" pattern="\\d{4}-\\d{2}"></label>
      <div id="newScopePreview"></div>
      <div class="row"><button id="newScopeSubmit" class="primary" type="submit" disabled>开设</button></div>
    </form>`);
  ['newScopeAgency', 'newScopeEntity', 'newScopeLedger', 'newScopePeriod'].forEach(id => {
    const field = $(id);
    if (field) field.addEventListener('input', newScopePreview);
  });
  newScopePreview();
  $('newScopeEntity')?.focus();
}

async function submitNewScope() {
  const derived = newScopeDerive($('newScopeAgency').value, $('newScopeEntity').value,
                                 $('newScopePeriod').value, $('newScopeLedger').value);
  if (!derived) return;
  await request('/api/v1/scopes/provision', derived);
  closeDialog();
  await loadPortfolio();
  const index = (state.scopes || []).findIndex(item => scopeKey(item.scope) === scopeKey(derived));
  if (index >= 0) await selectScope(index);
  notify(`已开设 ${derived.legal_entity_id} ${derived.accounting_period_id}，可以开始接收原件。`);
}

function installNewScopeActions() {
  actions['new-scope'] = () => openNewScope();
}

'use strict';

// 凭证提案：按历史做法为本期流水提出凭证。提案不是凭证 ——
// 每一张都要人过一眼，区别只在于"扫一眼就过"还是"得想一下"。
const voucherProposalUI = {key: '', data: null, loaded: false, error: '', open: '', filter: 'review'};

const PROPOSAL_AUTO = 85;
const PROPOSAL_REVIEW = 60;

function voucherProposalState() {
  const key = JSON.stringify([state.user?.user_id, scopeKey(scope())]);
  if (voucherProposalUI.key !== key) {
    Object.assign(voucherProposalUI, {key, data: null, loaded: false, error: '', open: '', filter: 'review'});
  }
  return voucherProposalUI;
}

async function loadVoucherProposals() {
  const ui = voucherProposalState(), key = ui.key;
  try {
    const data = await request('/api/v1/vouchers/propose', {scope: scope()});
    if (voucherProposalState().key !== key) return;
    ui.data = data;
    ui.error = '';
  } catch (error) {
    if (voucherProposalState().key !== key) return;
    ui.data = null;
    ui.error = error.message || '读取凭证提案失败';
  }
  ui.loaded = true;
  render();
}

function proposalBucket(item) {
  const confidence = Number(item.proposal?.confidence || 0);
  if (item.proposal?.outcome !== 'PROPOSAL') return 'abstained';
  return confidence >= PROPOSAL_AUTO ? 'auto' : 'review';
}

function proposalKey(item) {
  return item.fact?.id || '';
}

function renderProposalLines(lines) {
  const row = (line) => {
    const debit = Number(line.debit) ? esc(line.debit) : '';
    const credit = Number(line.credit) ? esc(line.credit) : '';
    return `<tr><td class="vp-code">${esc(line.account_code)}</td>
      <td>${esc(line.account_name)}</td>
      <td class="amount">${debit}</td><td class="amount">${credit}</td></tr>`;
  };
  return `<div class="table-wrap"><table class="vp-lines">
    <thead><tr><th>科目</th><th>名称</th><th>借方</th><th>贷方</th></tr></thead>
    <tbody>${lines.map(row).join('')}</tbody></table></div>`;
}

function renderProposalCard(item) {
  const ui = voucherProposalState();
  const t = item.transaction, p = item.proposal;
  const confidence = Number(p.confidence || 0);
  const tone = confidence >= PROPOSAL_AUTO ? 'green' : (confidence >= PROPOSAL_REVIEW ? 'yellow' : 'red');
  const open = ui.open === proposalKey(item);
  return `<article class="panel pad vp-card">
    <div class="row">
      <div><strong>${esc(t.date || '')}</strong> ${esc(t.summary || '（无摘要）')}
        <span class="muted small">${esc(t.counterparty || '无对方户名')}</span></div>
      <div><span class="amount vp-amount">${esc(t.amount)}</span>
        <span class="badge ${tone}">置信 ${confidence}</span></div>
    </div>
    ${renderProposalLines(p.lines || [])}
    ${item.account_hint?.why ? `<p class="muted small">${esc(item.account_hint.why)}</p>` : ''}
    <button class="text" data-action="voucher-proposal-basis" data-proposal="${esc(proposalKey(item))}">
      ${open ? '收起依据' : '查看依据'}</button>
    ${open ? `<ul class="vp-basis">${(p.basis || []).map(x => `<li>${esc(x)}</li>`).join('')}</ul>` : ''}
  </article>`;
}

function renderAbstained(items) {
  const grouped = new Map();
  items.forEach(item => {
    const reason = item.proposal?.reason || '未说明原因';
    if (!grouped.has(reason)) grouped.set(reason, []);
    grouped.get(reason).push(item);
  });
  const blocks = [...grouped.entries()]
    .sort((a, b) => b[1].length - a[1].length)
    .map(([reason, group]) => `<details class="vp-group">
      <summary><strong>${esc(reason)}</strong> ${group.length} 笔</summary>
      <ul class="vp-rows">${group.map(item => `<li>
        <span class="muted small">${esc(item.transaction.date || '')}</span>
        ${esc(item.transaction.summary || '（无摘要）')}
        <span class="muted small">${esc(item.transaction.counterparty || '')}</span>
        <span class="amount">${esc(item.transaction.amount)}</span></li>`).join('')}</ul>
    </details>`).join('');
  return `<section class="panel pad">
    <h3>提不出凭证 ${items.length} 笔</h3>
    <p class="muted small">按原因归并。同一个原因处理一次，不逐笔追问。</p>
    ${blocks}</section>`;
}

function renderVoucherProposals() {
  const ui = voucherProposalState();
  let html = '<button class="text return-link" data-action="voucher-proposals-return">← 返回本期办理</button>';
  if (ui.error) html += `<div class="notice error">${esc(ui.error)}</div>`;
  if (!ui.loaded) return html + '<section class="panel pad"><p>正在按历史做法生成凭证提案…</p></section>';

  const data = ui.data || {};
  if (!data.learned) {
    return html + `<section class="panel pad"><h2>还不能提出凭证</h2>
      <p class="muted">${esc(data.reason || '尚未上传历史凭证')}</p>
      <p class="muted small">上传这家企业过往的序时账，系统会照着他们自己的做账习惯提凭证，
        而不是套用通用规则。</p></section>`;
  }

  const all = [...(data.proposals || []), ...(data.abstained || [])];
  const auto = all.filter(x => proposalBucket(x) === 'auto');
  const review = all.filter(x => proposalBucket(x) === 'review');
  const abstained = all.filter(x => proposalBucket(x) === 'abstained');
  const learned = data.learned;

  html += `<section class="panel pad">
    <h2>凭证提案 ${data.counts?.transactions || 0} 笔流水</h2>
    <p class="muted small">学自 ${esc(String(learned.vouchers))} 张历史凭证
      （${esc(learned.periods?.[0] || '')} 至 ${esc(learned.periods?.[learned.periods.length - 1] || '')}），
      ${esc(String(learned.templates))} 个往来对象、${esc(String(learned.accounts))} 个在用科目。</p>
    <div class="vp-tabs">
      <button class="text" data-action="voucher-proposal-filter" data-filter="auto"
        aria-pressed="${ui.filter === 'auto'}">可直接过 ${auto.length}</button>
      <button class="text" data-action="voucher-proposal-filter" data-filter="review"
        aria-pressed="${ui.filter === 'review'}">需核对 ${review.length}</button>
      <button class="text" data-action="voucher-proposal-filter" data-filter="abstained"
        aria-pressed="${ui.filter === 'abstained'}">提不出 ${abstained.length}</button>
    </div></section>`;

  if (ui.filter === 'abstained') return html + (abstained.length ? renderAbstained(abstained)
    : '<section class="panel pad"><p class="muted">每一笔都提出了凭证。</p></section>');
  const shown = ui.filter === 'auto' ? auto : review;
  if (!shown.length) {
    return html + `<section class="panel pad"><p class="muted">${
      ui.filter === 'auto' ? '没有可以直接过的提案，都需要核对。' : '没有需要核对的提案。'}</p></section>`;
  }
  if (ui.filter === 'auto') {
    html += `<section class="panel pad"><p class="muted small">
      这些提案的往来对象和做法都有足够多的历史依据。仍然建议扫一眼金额和科目再放行 ——
      科目记错不会报错，只会成为一条错账。</p></section>`;
  }
  return html + shown.map(renderProposalCard).join('');
}

function installVoucherProposalActions() {
  actions['voucher-proposals-open'] = () => {
    state.view = 'voucher-proposals';
    render();
    loadVoucherProposals().catch(() => {});
  };
  actions['voucher-proposals-return'] = () => {state.view = 'current'; render();};
  actions['voucher-proposal-filter'] = (element) => {
    voucherProposalState().filter = element.dataset.filter;
    render();
  };
  actions['voucher-proposal-basis'] = (element) => {
    const ui = voucherProposalState();
    const id = element.dataset.proposal;
    ui.open = ui.open === id ? '' : id;
    render();
  };
}

'use strict';

// 凭证提案：按历史做法为本期流水提出凭证。提案不是凭证 ——
// 每一张都要人过一眼，区别只在于"扫一眼就过"还是"得想一下"。
const voucherProposalUI = {key: '', data: null, loaded: false, error: '', open: '', filter: 'review',
  reconciliation: null, adopting: '', adopted: new Set(), feedback: ''};

const PROPOSAL_AUTO = 85;
const PROPOSAL_REVIEW = 60;

function voucherProposalState() {
  const key = JSON.stringify([state.user?.user_id, scopeKey(scope())]);
  if (voucherProposalUI.key !== key) {
    Object.assign(voucherProposalUI, {key, data: null, loaded: false, error: '', open: '', filter: 'review',
      reconciliation: null, adopting: '', adopted: new Set(), feedback: ''});
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
    ui.reconciliation = await request('/api/v1/vouchers/reconciliation', {scope: scope()});
    if (voucherProposalState().key !== key) return;
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

function renderReconciliation(rec) {
  if (!rec) return '';
  if (rec.status === 'NO_BASELINE' || rec.status === 'NO_BANK_BASELINE') {
    return `<section class="panel pad vp-recon"><p class="muted">${esc(rec.reason || '')}</p></section>`;
  }
  const balanced = rec.status === 'BALANCED';
  const difference = rec.difference;
  return `<section class="panel pad vp-recon ${balanced ? 'ok' : ''}">
    <div class="row"><h3>${esc(rec.bank_account?.name || '银行存款')} 勾稽</h3>
      <span class="badge ${balanced ? 'green' : 'yellow'}">${balanced ? '已对平' : '未对平'}</span></div>
    <dl class="vp-recon-grid">
      <div><dt>期初（基线）</dt><dd>${esc(rec.opening)}</dd></div>
      <div><dt>已采纳凭证发生</dt><dd>${esc(rec.movement)}</dd></div>
      <div><dt>算出的期末</dt><dd>${esc(rec.computed_closing)}</dd></div>
      <div><dt>对账单期末</dt><dd>${esc(rec.statement_closing || '—')}</dd></div>
      ${difference !== undefined ? `<div><dt>差额</dt><dd class="${balanced ? '' : 'vp-gap'}">${esc(difference)}</dd></div>` : ''}
      <div><dt>还没入账</dt><dd>${esc(String(rec.outstanding))} / ${esc(String(rec.transactions))} 笔</dd></div>
    </dl>
    <p class="muted small">${balanced
      ? '每一笔流水都入了账，算出的期末与银行对账单一致。'
      : '对账单期末余额来自银行，不是账上的数。差额指向还没做或做错的那几笔。'}</p>
  </section>`;
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
    <div class="row">
      ${ui.adopted.has(proposalKey(item))
        ? '<span class="badge green">已采纳</span>'
        : `<button class="primary" data-action="voucher-proposal-adopt"
             data-proposal="${esc(proposalKey(item))}"
             ${ui.adopting === proposalKey(item) || readonly() ? 'disabled' : ''}>${
             ui.adopting === proposalKey(item) ? '正在采纳…' : '采纳'}</button>`}
      <button class="text" data-action="voucher-proposal-basis" data-proposal="${esc(proposalKey(item))}">
        ${open ? '收起依据' : '查看依据'}</button>
    </div>
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

  if (ui.feedback) html += `<div class="notice">${esc(ui.feedback)}</div>`;
  html += renderReconciliation(ui.reconciliation);
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
  actions['voucher-proposal-adopt'] = (element) => exclusive(async () => {
    const ui = voucherProposalState();
    const id = element.dataset.proposal;
    const item = [...(ui.data?.proposals || [])].find(x => proposalKey(x) === id);
    if (!item || readonly()) return;
    ui.adopting = id;
    ui.error = '';
    render();
    try {
      await request('/api/v1/vouchers/adopt', {
        scope: scope(), fact_id: item.fact.id, fact_version: item.fact.version,
        lines: item.proposal.lines, summary: item.transaction.summary,
        basis: item.proposal.basis});
      ui.adopted.add(id);
      ui.feedback = '已采纳。凭证仍是草稿，尚未正式入账。';
      // 采纳会改变勾稽结果，重新取一次而不是就地估算。
      ui.reconciliation = await request('/api/v1/vouchers/reconciliation', {scope: scope()});
    } catch (error) {
      ui.error = error.message || '采纳失败';
    } finally {
      ui.adopting = '';
      render();
    }
  });
  actions['voucher-proposal-basis'] = (element) => {
    const ui = voucherProposalState();
    const id = element.dataset.proposal;
    ui.open = ui.open === id ? '' : id;
    render();
  };
}

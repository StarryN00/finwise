'use strict';

// 识别卡：系统认不出一份原件的结构时出一张卡，确认一次之后同模板的文件
// 不再打扰人。卡片只描述，确认动作仍然通过既有命令链路写入。
const profileCardUI = {key: '', cards: [], loaded: false, pending: '', error: '', feedback: ''};

function profileCardState() {
  const key = JSON.stringify([state.user?.user_id, scopeKey(scope())]);
  if (profileCardUI.key !== key) {
    profileCardUI.key = key;
    profileCardUI.cards = [];
    profileCardUI.loaded = false;
    profileCardUI.pending = '';
    profileCardUI.error = '';
    profileCardUI.feedback = '';
  }
  return profileCardUI;
}

async function loadProfileCards() {
  const ui = profileCardState(), key = ui.key;
  try {
    const data = await request('/api/v1/profile-cards', {scope: scope()});
    if (profileCardState().key !== key) return;
    ui.cards = Array.isArray(data.cards) ? data.cards : [];
    ui.error = '';
  } catch (error) {
    if (profileCardState().key !== key) return;
    ui.cards = [];
    ui.error = error.message || '读取待确认结构失败';
  }
  ui.loaded = true;
  render();
}

function profileCardBadgeCount() {
  const ui = profileCardState();
  return ui.loaded ? ui.cards.length : 0;
}

function profileCardBadge() {
  const count = profileCardBadgeCount();
  if (!count) return '';
  return `<button class="text" data-action="profile-cards-open">待确认结构 ${count}</button>`;
}

function profileCardKey(card) {
  return `${card.artifact?.id || ''}::${card.sheet || ''}`;
}

function renderProfileCard(card) {
  const ui = profileCardState();
  const confidence = Number(card.why?.confidence || 0);
  const known = card.card_type === 'SOURCE_PROFILE_CONFIRM';
  const tone = confidence >= 90 ? 'green' : (confidence > 0 ? 'yellow' : 'red');
  const busy = ui.pending === profileCardKey(card);
  const evidence = String(card.why?.rule || '').split('；').filter(Boolean);
  return `<article class="panel pad profile-card">
    <h3>${esc(card.title || '认不出这份文件的结构')}</h3>
    <p class="badge ${tone}">${known ? `识别置信度 ${confidence}%` : '无法自动识别'}</p>
    ${card.why?.facts ? `<p class="facts">${esc(card.why.facts)}</p>` : ''}
    ${evidence.length ? `<ul class="evidence">${evidence.map(x => `<li>${esc(x)}</li>`).join('')}</ul>` : ''}
    <p class="muted small">${esc(card.why?.recommendation || '')}</p>
    ${known ? `<p class="muted small">确认后登记为${card.why?.yields?.scope_level === 'ENTITY' ? '本企业' : '平台'}版式，同模板文件不再询问。</p>` : ''}
    <div class="row">
      ${known ? `<button class="primary" data-action="profile-card-confirm" data-profile-card="${esc(profileCardKey(card))}" ${busy || readonly() ? 'disabled' : ''}>${busy ? '正在确认…' : '确认'}</button>` : ''}
      <button class="secondary" data-action="profile-card-designate" data-profile-card="${esc(profileCardKey(card))}" ${busy ? 'disabled' : ''}>${known ? '我改一下' : '我来指认各列'}</button>
    </div>
  </article>`;
}

function renderProfileCards() {
  const ui = profileCardState();
  let html = '<button class="text return-link" data-action="profile-cards-return">← 返回本期办理</button>';
  if (ui.error) html += `<div class="notice error">${esc(ui.error)}</div>`;
  if (ui.feedback) html += `<div class="notice">${esc(ui.feedback)}</div>`;
  if (!ui.loaded) return html + '<section class="panel pad"><p>正在读取待确认结构…</p></section>';
  if (!ui.cards.length) {
    return html + `<section class="panel pad"><h2>没有待确认的结构</h2>
      <p class="muted">本期原件的表格结构都已识别。新上传一份陌生格式时，这里会出现一张卡片。</p></section>`;
  }
  return html + `<section class="panel pad"><h2>待确认结构 ${ui.cards.length}</h2>
    <p class="muted small">每张卡确认一次，之后所有同模板的文件都直接按该结构解析。</p></section>`
    + ui.cards.map(renderProfileCard).join('');
}

function installProfileCardActions() {
  actions['profile-cards-open'] = () => {
    state.view = 'profile-cards';
    profileCardState().feedback = '';
    render();
    loadProfileCards().catch(() => {});
  };
  actions['profile-cards-return'] = () => {state.view = 'current'; render();};
  actions['profile-card-designate'] = (element) => {
    // 指认各列复用既有的结构方案界面；这里只负责把人送过去。
    const ui = profileCardState();
    const card = ui.cards.find(x => profileCardKey(x) === element.dataset.profileCard);
    const artifact = card && typeof fileById === 'function' ? fileById(card.artifact.id) : null;
    if (artifact && typeof openParsePlan === 'function') {openParsePlan(artifact, card.document_kind); return;}
    ui.feedback = '请在资料列表中打开该原件，使用「核对表格结构」逐列指认。';
    render();
  };
  actions['profile-card-confirm'] = (element) => exclusive(async () => {
    const ui = profileCardState(), epoch = state.epoch;
    const card = ui.cards.find(x => profileCardKey(x) === element.dataset.profileCard);
    if (!card || readonly()) return;
    ui.pending = profileCardKey(card);
    ui.error = '';
    render();
    try {
      await request('/api/v1/profile-cards/confirm', {scope: scope(), card});
      if (epoch !== state.epoch || profileCardState().key !== ui.key) return;
      // 确认之后立刻按新版式重新解析，让人当场看到结果，而不是再点一次。
      const artifact = typeof fileById === 'function' ? fileById(card.artifact.id) : null;
      let outcome = null;
      if (artifact) {
        const result = await command('parse_artifact', artifact.object_id, artifact.version,
                                     artifact.data.parse_options || {document_kind: card.document_kind}, false);
        outcome = result?.effect?.artifact?.data || null;
      }
      if (epoch !== state.epoch) return;
      await loadWorkbench();
      if (epoch !== state.epoch) return;
      // 版式生效不等于这份原件就没问题了：对账校验仍可能拦下它。
      // 如实报告重新解析的结果，不能一律说"已识别"。
      const rows = outcome?.parse_counts?.rows || 0;
      const status = outcome?.parse_status || '';
      ui.feedback = rows
        ? `结构已确认并登记，该原件已按新结构提取 ${rows} 条记录。`
        : (status
            ? `结构已确认并登记，但该原件重新解析仍未通过（${status}），请在资料列表中查看原因。`
            : '结构已确认并登记，请对该原件重新解析。');
      ui.pending = '';
      // 只有确认成功才刷新列表。失败时列表没有变化，重新拉取只会把
      // 操作人需要看到的错误信息冲掉。
      await loadProfileCards().catch(() => {});
      return;
    } catch (error) {
      ui.error = error.message || '确认失败';
    } finally {
      if (profileCardState().key === ui.key) ui.pending = '';
      render();
    }
  });
}

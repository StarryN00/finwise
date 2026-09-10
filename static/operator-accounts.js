'use strict';
const bankUI={key:'',drafts:new Map(),creating:false};
function resetBankState(){bankUI.key='';bankUI.drafts.clear();bankUI.creating=false;}
function bankState(){const key=JSON.stringify([state.user?.user_id,scopeKey(scope())]);if(bankUI.key!==key){bankUI.key=key;bankUI.drafts.clear();bankUI.creating=false;}return bankUI;}
function bankData(){return state.overview.bank_accounts||{accounts:[],statements:[]};}
const bankLabels={account_number:'本方账号',holder:'账户户名',bank_name:'开户银行',currency:'币种'};
const bankStatus={NEW:'确认新增银行',MISSING:'请选择所属银行',MATCHED:'可归入已登记银行',REVIEW:'同一银行存在多个或不同账户，请选择',CONFLICT:'银行信息存在冲突',INVALID:'原件无法核验',LINKED:'已分配银行'};
function bankDraft(c){const ui=bankState(),key=c?c.artifact_id+':'+c.artifact_version:'new';if(!ui.drafts.has(key)){const i=c?.identity||{};ui.drafts.set(key,{account_id:c?.match_id||c?.suggested_id||'',account_number:c?.requires_specific_account?i.account_number||'':'',holder:'',bank_name:i.bank_name||i.bank_hint||'',currency:i.currency||'CNY',note:'',confirmed:false,token:c?.token});}const d=ui.drafts.get(key);if(c&&d.token!==c.token){d.token=c.token;d.confirmed=false;}return d;}
function bankForm(c){
 const d=bankDraft(c),accounts=bankData().accounts,i=c?.identity||{},blocked=c&&['CONFLICT','INVALID'].includes(c.status);
 if(blocked)return `<p class="issue-banner">${esc(c.error||'原件中账号、户名或银行信息存在冲突，不能直接登记或覆盖。请查看来源，核对正确账户或补充银行证明。')}</p><div class="mat-actionbar"><button class="primary" data-action="material-supplement" ${readonly()?'disabled':''}>提供账户更正依据</button><button class="text" data-action="material-defer">暂无法确认</button><button class="text" data-action="material-skip">先看下一项</button></div>`;
 return `<form id="bankAccountForm" class="stack" data-artifact="${esc(c?.artifact_id||'')}">
 ${c?.requires_specific_account?'<p class="issue-banner">该银行已出现多个明确账号。请在下方选择具体账户，或展开选填信息登记本份流水的账号。</p>':''}
 ${c&&accounts.length?`<label>所属银行账户<select name="account_id" id="bankAccountChoice"><option value="">登记新的银行／账户</option>${accounts.map(a=>`<option value="${esc(a.object_id)}" ${d.account_id===a.object_id?'selected':''}>${esc(a.data.bank_name)} · ${esc(a.data.account_number||'默认账户（未填账号）')}</option>`).join('')}</select></label>`:''}
 ${!d.account_id?`<label>所属银行<input name="bank_name" value="${esc(d.bank_name)}" required maxlength="128"><span class="small muted">${i.bank_name?'依据原件银行信息':i.bank_hint?'依据文件名识别，可核对修改':'请选择或填写银行名称'}</span></label><details><summary>补充账号等信息（选填）</summary><div class="form-grid">${['account_number','holder','currency'].map(k=>`<label>${bankLabels[k]}${k==='currency'?'':'（选填）'}<input name="${k}" value="${esc(d[k])}" maxlength="128" ${k==='currency'?'required':''} placeholder="${esc(i[k]||'可留空')}" autocomplete="off"></label>`).join('')}</div></details>`:''}
 <label class="mat-checkbox"><input type="checkbox" name="confirmed" ${d.confirmed?'checked':''} required>确认${c?'本份流水的银行归属':'该银行用于当前企业记账'}</label>
 <p class="small muted">同一企业同一银行默认一个账户，账号可不填。${c?'同时分配本期可明确归属的同银行资料，不确认交易或发票匹配。':'本企业账套跨期共用。'}责任人：${esc(state.user?.display_name||state.user?.user_id||'当前登录用户')}</p>
 <div class="actions"><button type="submit" class="primary" ${readonly()?'disabled':''}>${c?'确认所属银行并继续':'保存银行'}</button>${c?'<button type="button" class="text" data-action="material-defer">暂无法确认</button><button type="button" class="text" data-action="material-skip">先看下一项</button>':'<button type="button" class="text" data-action="accounts-cancel">取消</button>'}</div></form>`;
}
function bankDecisionFields(t,field){
 const c=bankData().statements.find(s=>s.artifact_id===t.artifact_id);if(!c)return '<p>银行来源已变化，请刷新。</p>';
 const d=bankDraft(c),accounts=bankData().accounts;
 const fields=field.properties.map(p=>{
  const k=p.name;if(k==='account_id'&&!accounts.length||['bank_name','account_number','holder','currency'].includes(k)&&d.account_id)return '';
  const attrs=`name="${k}" ${p.required?'required':''} placeholder="${esc(p.placeholder)}"`;
  let control;
  if(k==='account_id')control=`<select id="bankAccountChoice" ${attrs}><option value="">登记新的银行／账户</option>${accounts.map(a=>`<option value="${esc(a.object_id)}" ${d.account_id===a.object_id?'selected':''}>${esc(a.data.bank_name)} · ${esc(a.data.account_number||'默认账户（未填账号）')}</option>`).join('')}</select>`;
  else if(k==='confirmed')control=`<input type="checkbox" ${attrs} ${d.confirmed?'checked':''}>`;
  else control=`<input ${attrs} value="${esc(d[k])}" maxlength="128" autocomplete="off">`;
  return {name:k,html:decisionPropertyLabel(p,control)};
 }).filter(Boolean);
 const optional=new Set(['account_number','holder','currency']);
 const optionalFields=fields.filter(f=>optional.has(f.name)).map(f=>f.html).join('');
 return fields.filter(f=>!optional.has(f.name)&&f.name!=='confirmed').map(f=>f.html).join('')+
  (optionalFields?`<details><summary>补充账号等信息（选填）</summary><div class="form-grid">${optionalFields}</div></details>`:'')+
  fields.filter(f=>f.name==='confirmed').map(f=>f.html).join('');
}
function bankDecisionSource(t,field){
 const c=bankData().statements.find(s=>s.artifact_id===t.artifact_id);if(!c)return '';
 const i=c.identity||{};
 return (Object.keys(i.sources||{}).length?`<details><summary>查看原件已提供的信息（无需重复填写）</summary><div class="table-wrap"><table><thead><tr><th>字段</th><th>原件信息</th><th>来源</th></tr></thead><tbody>${field.properties.filter(p=>i[p.name]).map(p=>`<tr><th>${esc(p.label)}</th><td>${esc(i[p.name])}</td><td>${esc(i.sources?.[p.name]?.region||'—')}</td></tr>`).join('')}</tbody></table></div></details>`:'')+objectButton(c.artifact_id,'查看完整原件');
}
function renderAccounts(){
 const d=bankData(),ui=bankState();
 return `<button class="text return-link" data-action="return-current">← 返回本期办理</button><section class="panel pad"><div class="row"><div><h2 id="bankTitle" tabindex="-1">企业对公银行</h2><p>${d.accounts.length} 个已登记账户 · 账号选填 · 本企业账套跨期共用</p></div>${!ui.creating?`<button class="primary" data-action="accounts-new" ${readonly()?'disabled':''}>添加银行／账户</button>`:''}</div>${ui.creating?bankForm(null):''}<div class="table-wrap bank-account-table" tabindex="0"><table><thead><tr><th>所属银行</th><th>账户户名（选填）</th><th>账号（选填）</th><th>币种</th><th>确认记录</th></tr></thead><tbody>${d.accounts.map(a=>`<tr><td>${esc(a.data.bank_name)}</td><td>${esc(a.data.holder||'未填写')}</td><td class="mono">${esc(a.data.account_number||'未填写 · 按银行记账')}</td><td>${esc(a.data.currency)}</td><td>${esc(a.data.confirmed_by)}<br>${esc(a.data.confirmed_at)}</td></tr>`).join('')||'<tr><td colspan="5">尚未登记银行。添加企业使用的银行即可，无需填写账号；也可以在导入流水后确认新银行。</td></tr>'}</tbody></table></div><h3>本期流水银行分配</h3>${d.statements.map(s=>`<div class="row bank-statement-row"><span>${esc(s.filename)}<br><small>${esc(bankStatus[s.status])} · ${s.record_count} 条交易</small></span>${s.status!=='LINKED'?`<button class="text" data-action="accounts-statement" data-artifact="${esc(s.artifact_id)}">确认所属银行</button>`:objectButton(s.artifact_id,'查看来源')}</div>`).join('')||'<p>本期尚无已识别的银行流水。</p>'}</section>`;
}
function installBankActions(){
 actions['accounts-open']=()=>{bankState();state.view='accounts';render();$('bankTitle')?.focus({preventScroll:true});};
 actions['accounts-new']=()=>{bankState().creating=true;render();document.querySelector('#bankAccountForm input')?.focus();};
 actions['accounts-cancel']=()=>{bankState().creating=false;render();};
 actions['accounts-statement']=b=>{const t=state.overview.material_review.tasks.find(t=>t.artifact_id===b.dataset.artifact&&t.reason.startsWith('bank_account_ref：'));if(t){openMaterialWorkbench();const ui=materialState();ui.filter=t.deferred?'deferred':'all';materialDraft(t).resume=true;materialDraft(t).defer=false;openMaterialDetail(t.id,b,'file');}else{notify('当前没有账户确认待办，请查看原件的最新解析结果。');}};
 document.addEventListener('input',e=>{const f=e.target.closest('#bankAccountForm');if(!f)return;const c=bankData().statements.find(s=>s.artifact_id===f.dataset.artifact),d=bankDraft(c);if(e.target.name in d){d[e.target.name]=e.target.type==='checkbox'?e.target.checked:e.target.value;if(e.target.name!=='confirmed'){d.confirmed=false;f.querySelector('[name="confirmed"]').checked=false;}}});
 document.addEventListener('change',e=>{if(e.target.id!=='bankAccountChoice')return;const c=bankData().statements.find(s=>s.artifact_id===e.target.form.dataset.artifact),d=bankDraft(c);d.account_id=e.target.value;d.confirmed=false;render();$('bankAccountChoice')?.focus({preventScroll:true});});
 document.addEventListener('submit',e=>{if(e.target.id!=='bankAccountForm')return;e.preventDefault();const form=e.target;exclusive(async()=>{
  const c=bankData().statements.find(s=>s.artifact_id===form.dataset.artifact),d=bankDraft(c),epoch=state.epoch,task=c?currentMaterialTask():null,group=materialState().group;
  if(c&&(!task||!materialTaskIsCurrent(task)))throw Error('本项资料版本已变化，请返回列表重新核对。');
  if(!form.reportValidity()||!d.confirmed)throw Error('请先核对账户归属并勾选确认');
  const submittedDraft=JSON.stringify(d);const fields=Object.fromEntries(Object.keys(bankLabels).map(k=>[k,d[k].trim()]));
  if(c)await command('confirm_statement_account',c.artifact_id,c.artifact_version,{token:c.token,ownership_confirmed:true,...(d.account_id?{account_id:d.account_id}:{new_account:fields}),note:d.note});
  else{const p=state.overview.period;await command('register_bank_account',p.object_id,p.version,{...fields,ownership_confirmed:true});}
  if(epoch!==state.epoch)return;const draftKey=c?c.artifact_id+':'+c.artifact_version:'new';if(JSON.stringify(bankState().drafts.get(draftKey))===submittedDraft)bankState().drafts.delete(draftKey);bankUI.creating=false;
  if(c){if(!materialDetailStillOpen(group,task.id)){notify('所属银行已保存，可返回资料列表查看分配结果。');return;}state.view='materials';materialAdvance(task,'linked');}else{render();notify('企业账户已登记，后续流水可匹配该账户。');}
 }).catch(error=>notify(error.message,true));});
}

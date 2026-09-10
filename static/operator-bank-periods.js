'use strict';
// Cross-period references remain separate from FactRecord verification/accounting.
function bankPeriodData(){const p=state.overview?.bank_periods;return state.overview?.scope&&scopeKey(state.overview.scope)===scopeKey(scope())&&p&&Array.isArray(p.incoming)&&Array.isArray(p.outgoing)?p:null;}
function bankPeriodToken(item,direction){return JSON.stringify([state.user?.user_id,state.epoch,scopeKey(scope()),state.overview?.period?.object_id,state.overview?.period?.version,direction,item]);}
function bankPeriodResolve(button){
  const direction=button.dataset.periodDirection,p=bankPeriodData();if(!p||!['incoming','outgoing'].includes(direction))return null;
  const item=p[direction].find(x=>(direction==='incoming'?x.assignment_id:x.object_id)===button.dataset.periodId);
  return item&&button.dataset.periodToken===bankPeriodToken(item,direction)?{item,direction}:null;
}
function bankPeriodButton(item,direction,action,label){return '<button type="button" class="secondary" data-action="bank-period-'+(action==='source'?'source':'action')+'" data-period-action="'+action+'" data-period-direction="'+direction+'" data-period-id="'+esc(direction==='incoming'?item.assignment_id:item.object_id)+'" data-period-token="'+esc(bankPeriodToken(item,direction))+'">'+esc(label)+'</button>';}
function bankPeriodScope(item,direction){
  const source=direction==='incoming'?item.source_scope:item.scope,current=scope();
  const keys=['tenant_id','organization_id','legal_entity_id','ledger_id'];
  if(!source||!keys.every(k=>typeof source[k]==='string'&&source[k]===current[k])||typeof source.baseline_id!=='string'||!/^\d{4}-\d{2}$/.test(source.accounting_period_id))return null;
  if(direction==='incoming'&&(item.target_period!==current.accounting_period_id||item.source_period!==source.accounting_period_id))return null;
  if(direction==='outgoing'&&scopeKey(source)!==scopeKey(current))return null;
  return source;
}
function bankPeriodSelection(t){
  const p=t?.bank_period;if(!p||!/^\d{4}-(0[1-9]|1[0-2])$/.test(p.target_period)||p.target_period===scope().accounting_period_id||typeof p.input_token!=='string'||!p.input_token||p.input_token!==t.input_token||!Array.isArray(p.record_ids))return null;
  const ids=[...materialDraft(t).selected],visible=decisionEvidenceRows(t).rows.map(r=>r.object_id);
  return ids.length>=1&&ids.length<=5&&ids.every(id=>visible.includes(id)&&p.record_ids.includes(id)&&t.record_ids.includes(id))?ids:null;
}
function bankPeriodFields(t,enabled){
  const p=t.bank_period,rows=decisionEvidenceRows(t).rows,d=materialDraft(t);
  return '<p>目标期间：<strong>'+esc(p?.target_period||'依据待检查')+'</strong>，由原件交易日期确定，不可在此修改。仅确认本页明确选择的流水。</p>'+rows.map(r=>'<label class="mat-checkbox"><input type="checkbox" data-material-record="'+esc(r.object_id)+'" '+(d.selected.has(r.object_id)?'checked':'')+' '+(!enabled?'disabled':'')+'>确认本条归属 '+esc(p?.target_period)+' · '+esc(r.values?.transaction_date||r.source_anchor?.region||r.object_id)+'</label>').join('');
}
function bankPeriodEffect(result,action,count){
  const objects=action==='confirm_bank_period'?result?.effect?.objects:[result?.effect?.object],status=action==='confirm_bank_period'?'CONFIRMED':action==='accept_bank_period'?'ACCEPTED':'REVOKED';
  if(!Array.isArray(objects)||objects.length!==(count||1)||objects.some(o=>!o?.object_id||!Number.isInteger(o.version)||o.status!==status))throw Error('未取得完整跨期处理记录，请重试核对；原填写内容仍保留。');
}
async function confirmBankPeriod(){
  const t=currentMaterialTask();if(!t||!materialCanWrite()||!decisionReady(t)||decisionOption(t)?.id!=='confirm_bank_period'||!decisionCanSubmit(t))return;
  const ids=bankPeriodSelection(t);if(!ids){notify('请明确选择当前页一至五条流水；页面或来源变化后需重新选择。',true);return;}
  const d=materialDraft(t),reason=String(d.note||'');if(reason.length>2000)return;
  const epoch=state.epoch,key=scopeKey(scope()),user=state.user?.user_id,overview=state.overview,group=materialState().group;
  materialSaveDraft(t);
  try{
    const result=await command('confirm_bank_period',t.artifact_id,t.artifact_version,{task_id:t.id,input_token:t.bank_period.input_token,record_ids:ids,target_period:t.bank_period.target_period,reason:reason.trim()},false);
    bankPeriodEffect(result,'confirm_bank_period',ids.length);
    if(epoch!==state.epoch||key!==scopeKey(scope())||user!==state.user?.user_id||state.overview!==overview)return;
    await loadWorkbench();
    if(epoch!==state.epoch||key!==scopeKey(scope())||user!==state.user?.user_id)return;
    d.selected.clear();
    if(typeof materialDetailStillOpen==='function'&&materialDetailStillOpen(group,t.id))materialAdvance(t,'bank_period_confirmed');
    notify('所选流水已确认其他期间归属；等待目标期间接续。未核实原件、未入账，其他问题保留。');
  }catch(e){if(epoch===state.epoch&&key===scopeKey(scope())&&user===state.user?.user_id)notify(e.message,true);}
}
function renderBankPeriodValues(item){
  const value=v=>v===null||v===undefined||v===''?'未提供':esc(typeof v==='object'?JSON.stringify(v):v);
  const rows=Array.isArray(item.comparison)?item.comparison:[];
  return '<div class="table-wrap" tabindex="0" role="region" aria-label="跨期流水原值"><table><thead><tr><th>字段</th><th>原件值</th><th>提取值</th><th>来源位置</th></tr></thead><tbody>'+rows.map(r=>'<tr><th>'+esc(materialFieldLabels[r.field]||fieldLabels[r.field]||r.field)+'</th><td>'+value(r.source_value)+'</td><td>'+value(r.value)+'</td><td>'+value(r.region)+'</td></tr>').join('')+'</tbody></table></div><details><summary>查看来源提取字段及原始提示</summary><dl>'+Object.entries(item.values||{}).map(([k,v])=>'<dt>'+esc(materialFieldLabels[k]||fieldLabels[k]||k)+'</dt><dd>'+value(v)+'</dd>').join('')+'</dl><ul>'+(item.original_issues||[]).map(x=>'<li>'+esc(x)+'</li>').join('')+'</ul></details>';
}
function renderBankPeriods(){
  const p=bankPeriodData();if(!p)return '';
  const labels={READY:'待明确接续',ACCEPTED:'已按引用接续',ACCEPTED_ELSEWHERE:'同月其他基线已接续，不能重复接续',STALE:'来源或归属已失效',DUPLICATE:'已存在重复流水，不能接续',AMBIGUOUS:'存在相似流水，需检查重复',WAITING_PERIOD:'等待目标期间建立',WAITING_INTAKE:'等待目标期间接续'};
  const incoming=p.incoming.map(x=>'<details class="bank-period-item"><summary>'+esc(x.filename||'跨期流水')+' · '+esc(x.source_period)+' → '+esc(x.target_period)+' · '+esc(labels[x.status]||'状态待检查')+'</summary><p>这是原始流水的跨期引用，不是新增事实；不计入资料核实或账务可用。</p>'+renderBankPeriodValues(x)+bankPeriodButton(x,'incoming','source','查看源期间依据')+(materialCanWrite()&&x.valid===true&&x.status==='READY'&&bankPeriodScope(x,'incoming')?bankPeriodButton(x,'incoming','accept','明确接续此条来源引用'):'')+(materialCanWrite()&&x.intake?.status==='ACCEPTED'?'<label>撤销说明（可选）<textarea data-period-reason maxlength="2000"></textarea></label>'+bankPeriodButton(x,'incoming','revoke-intake','明确撤销本条接续'):'')+'</details>').join('');
  const outgoing=p.outgoing.map(x=>'<details class="bank-period-item"><summary>'+esc(x.data?.binding?.source_anchor?.region||'流水归属记录')+' → '+esc(x.data?.target_period)+' · '+esc(x.status==='REVOKED'?'已撤销':x.valid===true?(labels[x.handoff_status]||'交接状态待检查'):'归属依据已失效')+'</summary><p>归属记录 v'+esc(x.version)+'；来源事实 v'+esc(x.data?.binding?.fact_version)+'。仅有效归属排除本期发生额；已撤销或失效时重新评估。不代表已入账。</p>'+bankPeriodButton(x,'outgoing','source','查看归属原始依据')+(materialCanWrite()&&x.status==='CONFIRMED'?'<label>撤销说明（可选）<textarea data-period-reason maxlength="2000">'+esc(x.data?.reason||'')+'</textarea></label>'+bankPeriodButton(x,'outgoing','revoke','明确撤销其他期间归属'):'')+'</details>').join('');
  return '<section class="panel pad bank-periods" aria-label="跨期流水归属与接续"><h3 id="bankPeriodsTitle" tabindex="-1">跨期流水归属与接续</h3><p>保留原件与原值；转出和接续分别明确确认，不复制流水、不自动创建期间、不自动入账。</p><h4>本期已确认的其他期间归属</h4>'+(outgoing||'<p>暂无归属记录。</p>')+'<h4>其他期间转来的来源引用</h4>'+(incoming||'<p>暂无待接续来源。</p>')+'<button type="button" class="secondary" data-action="bank-period-refresh">刷新跨期状态</button></section>';
}
async function bankPeriodAction(button){
  const resolved=bankPeriodResolve(button);if(!resolved||!materialCanWrite())return;
  const {item,direction}=resolved;if(!bankPeriodScope(item,direction))return;
  const action=button.dataset.periodAction;let commandName,target,version,payload;
  if(action==='accept'&&direction==='incoming'&&item.valid===true&&item.status==='READY'){
    commandName='accept_bank_period';target=state.overview.period?.object_id;version=state.overview.period?.version;payload={assignment_id:item.assignment_id,assignment_version:item.assignment_version,input_token:item.input_token};
    if(!Number.isInteger(item.assignment_version)||typeof item.input_token!=='string'||!item.input_token)return;
  }else if(action==='revoke'&&direction==='outgoing'&&item.status==='CONFIRMED'){
    commandName='revoke_bank_period';target=item.object_id;version=item.version;
  }else if(action==='revoke-intake'&&direction==='incoming'&&item.intake?.status==='ACCEPTED'){
    commandName='revoke_bank_period_intake';target=item.intake.object_id;version=item.intake.version;
  }else return;
  if(!target||!Number.isInteger(version))return;
  if(!payload){const reason=button.closest('.bank-period-item')?.querySelector('[data-period-reason]')?.value||'';if(reason.length>2000)return;payload={reason:reason.trim()};}
  const epoch=state.epoch,key=scopeKey(scope()),user=state.user?.user_id;
  const current=()=>epoch===state.epoch&&key===scopeKey(scope())&&user===state.user?.user_id;
  try{const result=await command(commandName,target,version,payload,false);bankPeriodEffect(result,commandName);if(!current())return;await loadWorkbench();if(current())notify(action==='accept'?'已按来源引用接续；未核实原件、未入账。':'已撤销；原始流水未修改，其他门禁继续保留。');}catch(e){if(current())notify(e.message,true);}
}
async function bankPeriodSource(button){
  const resolved=bankPeriodResolve(button);if(!resolved)return;
  const {item,direction}=resolved,source=bankPeriodScope(item,direction),binding=direction==='incoming'?item.binding:item.data?.binding;
  if(!source||!binding?.fact_id||!Number.isInteger(binding.fact_version))return;
  const epoch=state.epoch,key=scopeKey(scope()),user=state.user?.user_id,sequence=state.dialogSequence=(state.dialogSequence||0)+1;
  openDialog('跨期来源依据','<p role="status">正在读取源期间授权范围的记录…</p>');
  const current=()=>epoch===state.epoch&&key===scopeKey(scope())&&user===state.user?.user_id&&sequence===state.dialogSequence;
  try{
    const result=await request('/api/v1/objects/detail',{scope:source,object_id:binding.fact_id,version:binding.fact_version});
    if(!current()||($('dialog')&&!$('dialog').open))return;
    if(result.object?.object_id!==binding.fact_id||result.object?.version!==binding.fact_version)throw Error('来源版本不匹配，未使用当前版本替代。');
    openDialog('跨期来源依据', '<p>源期间 '+esc(source.accounting_period_id)+' · 事实版本 '+binding.fact_version+' · '+esc(binding.source_anchor?.region||'原件定位待查')+'</p><pre>'+esc(JSON.stringify(result.object.data,null,2))+'</pre><p class="small muted">仅查看源期间依据，不切换当前办理范围，不代表核实或接续。</p>');
  }catch(e){if(current())openDialog('跨期来源暂不可查看','<p>'+esc(e.message||'需具有源期间查看权限。')+'</p>');}
}
function installBankPeriodActions(){
  actions['bank-period-confirm']=()=>exclusive(confirmBankPeriod);
  actions['bank-period-action']=b=>exclusive(()=>bankPeriodAction(b));
  actions['bank-period-source']=b=>bankPeriodSource(b);
  actions['bank-period-refresh']=()=>exclusive(async()=>{const epoch=state.epoch,key=scopeKey(scope());try{await loadWorkbench();if(epoch===state.epoch&&key===scopeKey(scope()))notify('跨期状态已刷新；未确认归属、未接续或调用模型。');}catch(e){if(epoch===state.epoch&&key===scopeKey(scope()))notify(e.message,true);}});
}

'use strict';
const $=id=>document.getElementById(id);
const state={items:[],filter:'all',period:'latest',busy:false,timer:null,loaded:false};
const activeStatuses=['QUEUED','ANALYZING','REVIEWING','STALE'];
const periodLabels={OPEN:'期间开放',CLOSED:'已关闭',LOCKED:'已锁账',ARCHIVED:'已归档'};
const scopeKey=s=>['tenant_id','organization_id','legal_entity_id','ledger_id','accounting_period_id','baseline_id'].map(k=>s[k]).join('|');
const companyName=item=>item.display_context?.company_name||item.scope.legal_entity_id;
const ledgerName=item=>item.display_context?.ledger_name||item.scope.ledger_id;
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function workbenchLink(item){return 'operator.html?scope='+encodeURIComponent(scopeKey(item.scope));}
function periodItems(items,period){
 if(period==='all')return items;
 if(period!=='latest')return items.filter(i=>i.scope.accounting_period_id===period);
 const latest=new Map(),group=i=>JSON.stringify(['tenant_id','organization_id','legal_entity_id','ledger_id'].map(k=>i.scope[k]));
 for(const i of items){const k=group(i),p=i.scope.accounting_period_id;if(!latest.has(k)||p>latest.get(k))latest.set(k,p);}
 return items.filter(i=>i.scope.accounting_period_id===latest.get(group(i)));
}
function processing(item){return activeStatuses.includes(item.work_summary?.status);}
function needsAttention(item){const s=item.work_summary;return !!s&&item.period.status==='OPEN'&&(s.todo_count>0||s.review_count>0||s.blocked_count>0||['WAITING_INPUT','BLOCKED','CANCELLED','STALE'].includes(s.status));}
function visibleItems(){
 const term=$('search').value.trim().toLowerCase();
 return periodItems(state.items,state.period).filter(i=>[companyName(i),ledgerName(i),i.display_context?.business_license_number||''].join(' ').toLowerCase().includes(term));
}
function statusColor(item){const s=item.work_summary;if(!s)return '';if(s.blocked_count||s.status==='BLOCKED')return 'red';if(processing(item))return 'blue';if(needsAttention(item))return 'yellow';return s.status==='ACCEPTED'?'green':'';}
function row(item){
 const s=item.work_summary,p=item.progress||{},stage=(p.stages||[]).find(x=>x.id===p.current_stage),href=workbenchLink(item),index=state.items.indexOf(item);
 if(!s)return `<tr data-index="${index}"><td><a class="company-name" href="${esc(href)}">${esc(companyName(item))}</a><p class="small muted">${esc(ledgerName(item))}</p></td><td class="period">${esc(item.scope.accounting_period_id)}</td><td colspan="3">尚未读取最新处理状态，请刷新或进入工作台查看。</td><td><a href="${esc(href)}">进入工作台 →</a></td></tr>`;
 return `<tr data-index="${index}"><td><a class="company-name" href="${esc(href)}">${esc(companyName(item))}</a><p class="small muted">${esc(ledgerName(item))}</p></td><td class="period">${esc(item.scope.accounting_period_id)}<p class="small muted">${esc(periodLabels[item.period.status]||'期间待核实')}</p></td><td><span class="badge ${statusColor(item)}">${esc(s.label)}</span><p class="small muted">${s.revision?'第 '+esc(s.revision)+' 轮 · ':''}${esc(s.source_count)} 份原件</p></td><td><span>${esc(stage?.name||'等待处理')}</span>${p.total_count?`<progress max="${Number(p.total_count)}" value="${Number(p.completed_count)||0}" aria-label="已完成 ${Number(p.completed_count)||0} / ${Number(p.total_count)} 个阶段"></progress><span class="small muted">${Number(p.completed_count)||0} / ${Number(p.total_count)} 阶段已完成</span>`:''}</td><td><span class="todo"><b>${Number(s.todo_count)}</b> 项待处理</span><span class="todo"><b>${Number(s.review_count)}</b> 张待复核</span>${s.blocked_count?`<p class="small muted">${Number(s.blocked_count)} 张／项系统受阻</p>`:s.pending_voucher_count?`<p class="small muted">${Number(s.pending_voucher_count)} 张待补证</p>`:processing(item)?'<p class="small muted">本轮结果更新中</p>':`<p class="small muted">${Number(s.confirmed_count)} 张已复核</p>`}</td><td><a href="${esc(href)}">进入工作台 →</a></td></tr>`;
}
function render(){
 const items=visibleItems(),counts={all:items.length,attention:items.filter(needsAttention).length,processing:items.filter(processing).length};
 const names={all:'全部',attention:'需处理',processing:'处理中'};
 for(const button of document.querySelectorAll('[data-filter]')){const key=button.dataset.filter;button.textContent=names[key]+' '+counts[key];button.setAttribute('aria-pressed',String(state.filter===key));}
 const visible=items.filter(i=>state.filter==='all'||(state.filter==='attention'?needsAttention(i):processing(i)));
 $('listCount').textContent=`当前显示 ${visible.length} 个账套期间`;
 $('companies').innerHTML=visible.length?visible.map(row).join(''):`<tr><td colspan="6" class="empty">${state.items.length?'没有符合条件的企业，请调整搜索或筛选条件。':'当前账号暂无已授权企业，可在工作台新建企业或联系管理员授权。'}</td></tr>`;
}
function updatePeriods(){
 const periods=[...new Set(state.items.map(i=>i.scope.accounting_period_id))].sort().reverse();
 if(!['latest','all',...periods].includes(state.period))state.period='latest';
 $('periodFilter').innerHTML='<option value="latest">各账套最近期间</option><option value="all">全部期间</option>'+periods.map(p=>`<option value="${esc(p)}">${esc(p)}</option>`).join('');$('periodFilter').value=state.period;
}
function notice(text,error=false){$('notice').textContent=text;$('notice').className='notice'+(error?' error':'');}
async function request(url,options={}){
 const response=await fetch(url,{credentials:'same-origin',...options});let data={};try{data=await response.json();}catch(_){throw new Error('响应未完整接收，请刷新重试。');}
 if(!response.ok){const error=new Error(data.error?.message||'暂时无法读取，请稍后重试');error.status=response.status;throw error;}return data;
}
function schedule(){clearTimeout(state.timer);if(state.loaded&&state.items.some(processing))state.timer=setTimeout(()=>{if(document.hidden){schedule();return;}load();},10000);}
async function load(manual=false){
 if(state.busy)return;clearTimeout(state.timer);state.busy=true;$('refresh').disabled=true;$('refresh').textContent='正在刷新…';
 try{
  const session=await request('/api/v1/auth/me');
  const result=await request('/api/v1/portfolio');state.items=result.scopes||[];state.loaded=true;
  $('authState').textContent=session.role==='viewer'?'只读账号':'已读取授权范围';$('loginForm').classList.add('hidden');$('overview').classList.remove('hidden');
  updatePeriods();render();$('updatedAt').textContent='更新于 '+new Date().toLocaleTimeString('zh-CN')+(state.items.some(processing)?' · 处理中自动刷新':'');
  if(manual)notice('企业进度与待办已刷新。');else $('notice').classList.add('hidden');schedule();
 }catch(error){
  if(error.status===401){state.items=[];state.loaded=false;render();$('updatedAt').textContent='';$('overview').classList.add('hidden');$('loginForm').classList.remove('hidden');$('authState').textContent='需要登录';notice('请先登录，再查看授权企业。');}
  else{notice(error.message+(state.loaded?'；以下保留上次读取的结果。':''),true);if(!state.loaded)$('companies').innerHTML='<tr><td colspan="6" class="empty">暂时无法读取企业列表，请点击“刷新状态”重试。</td></tr>';state.timer=setTimeout(()=>{if(!document.hidden)load();else schedule();},10000);}
 }finally{state.busy=false;$('refresh').disabled=false;$('refresh').textContent='刷新状态';}
}
$('refresh').addEventListener('click',()=>load(true));
$('search').addEventListener('input',render);
$('periodFilter').addEventListener('change',event=>{state.period=event.target.value;render();});
document.querySelectorAll('[data-filter]').forEach(button=>button.addEventListener('click',()=>{state.filter=button.dataset.filter;render();}));
$('companies').addEventListener('click',event=>{
 const tr=event.target.closest('tr[data-index]');if(!tr)return;const item=state.items[Number(tr.dataset.index)];if(!item)return;
 try{localStorage.setItem('finwise.operator.scope',scopeKey(item.scope));}catch(_){}
 if(!event.target.closest('a'))tr.querySelector('a').click();
});
$('loginForm').addEventListener('submit',async event=>{
 event.preventDefault();const button=event.target.querySelector('button');button.disabled=true;
 try{await request('/api/v1/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:$('username').value,password:$('password').value})});$('password').value='';await load();}catch(error){notice(error.message,true);}finally{button.disabled=false;}
});
document.addEventListener('visibilitychange',()=>{if(!document.hidden&&state.loaded)load();});
load();

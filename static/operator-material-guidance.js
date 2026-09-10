'use strict';
// Candidate-only UI. No queue, model request or financial command during rendering.
function materialGuidanceResponse(t,channel){const custom=decisionGuide(t).custom;return channel==='auto'?t.material_guidance:custom?.dirty?custom.response:custom?.response||t.personal_material_guidance;}
function materialGuidanceToken(t,channel){return JSON.stringify([decisionIdentity(t),channel,materialGuidanceResponse(t,channel)]);}
function materialGuidanceCandidates(t,r){
  if(!r||r.valid===false||r.descriptor_hash!==t.descriptor.fingerprint||!['PROPOSED','NEEDS_HUMAN'].includes(r.status)||!Array.isArray(r.candidates)||r.candidates.length<1||r.candidates.length>3)return [];
  const ids=t.descriptor.options.filter(o=>o.available).map(o=>o.id),refs=new Set(['task',...t.record_ids.map((_,i)=>'record-'+(i+1))]),seen=new Set();
  for(const c of r.candidates){
    if(!c||c.option_id!==null&&!ids.includes(c.option_id)||c.option_id!==null&&seen.has(c.option_id)||typeof c.reason!=='string'||c.title!==undefined&&(!['string'].includes(typeof c.title)||c.title.length>80)||!Array.isArray(c.uncertainties)||!c.uncertainties.every(s=>typeof s==='string')||!c.prefill||Array.isArray(c.prefill)||typeof c.prefill!=='object'||Object.keys(c.prefill).length||!Number.isFinite(c.confidence)||c.confidence<0||c.confidence>1||c.option_id!==null&&c.confidence<.7||!Array.isArray(c.evidence_refs)||!c.evidence_refs.every(ref=>refs.has(ref))||!Array.isArray(c.steps)||!c.steps.every(s=>s&&ids.includes(s.option_id)&&typeof s.instruction==='string'))return [];
    if(c.legacy!==true&&!c.evidence_refs.length)return [];
    seen.add(c.option_id);
  }
  return r.candidates;
}
function materialGuidanceLabel(c,o,index,labels){
  const raw=String(c?.title||c?.label||'').trim();
  let label=raw||o?.label||'';
  if(!label){
    const reason=String(c?.reason||'');
    label=/暂缓|等待/.test(reason)?'暂缓并保留问题':/补充|附件|依据|资料/.test(reason)?'补充可核验依据':/归属|期间|月份|交易日期/.test(reason)?'确认业务期间归属':/核对|人工|确认/.test(reason)?'人工核对后记录意见':`建议方案 ${index+1}`;
  }
  if(labels){const count=labels[label]||0;labels[label]=count+1;if(count){const reason=String(c?.reason||'');const alternative=/暂缓|等待/.test(reason)?'先暂缓，等信息确认':/补充|附件|依据|资料/.test(reason)?'补充依据后再处理':/归属|期间|月份|交易日期/.test(reason)?'按实际业务月份归属':/核对|人工|确认/.test(reason)?'人工核对后记录':`建议方案 ${index+1}`;label=alternative===label?`${label}（方案 ${index+1}）`:alternative;}}
  return label;
}
function materialGuidancePlainReason(c,label){
  const reason=String(c?.reason||'');
  if(/期间|归属|月份|交易日期|period|date/i.test(reason)||/期间|归属/.test(label))return '这几笔流水的日期已经读出，但所属月份还需要确认。请结合原始流水和实际业务，确认应该计入哪个期间。';
  if(/发票状态|状态/.test(reason)||/状态/.test(label))return '原件里的发票状态已读出，但还需要确认它对应的实际业务。请结合原始发票和相关依据判断。';
  if(/格式|format|无法读取|无效/i.test(reason))return '系统读取这项数据时发现格式异常。请先对照原始表格，确认原表中的内容是否正常；原表正常时再提交，系统会继续检查。';
  if(/红冲|红字|零金额|金额|正负/.test(reason)||/金额/.test(label))return '原件中的金额需要结合实际业务确认，例如退货、折让或红冲。请先核对原件，再说明原因。';
  if(/银行|账户/.test(reason)||/银行/.test(label))return '系统已识别到银行信息，但还需要确认这笔流水属于哪家银行账户。';
  if(/票据|科目/.test(reason)||/票据|科目/.test(label))return '请根据已掌握的票据情况，确认业务性质、所属期间和拟用科目。';
  if(/补充|资料|依据/.test(reason)||/依据/.test(label))return '当前资料还不足以完成判断，请补充可以核对的依据，或先记录暂缓原因。';
  return '系统发现这项资料需要进一步确认，请对照原件后选择合适的处理方式。';
}
function materialGuidancePlainText(value){
  return String(value||'').replace(/记录record-\d+/g,'这笔记录').replace(/record-\d+/g,'这笔记录').replace(/period字段为DERIVED/gi,'所属月份是系统推算的').replace(/标准化匹配|格式化后匹配/g,'日期格式已统一').replace(/映射/g,'对应').replace(/业务动作/g,'账务处理').replace(/门禁/g,'后续审核条件').replace(/用户/g,'你');
}
function materialGuidanceImpact(o){
  const effects=(o?.effects||[]).map(materialGuidancePlainText).join('；');
  const notEffects=(o?.not_effects||[]).map(materialGuidancePlainText).join('；');
  return {effects,notEffects};
}
function materialGuidanceChoice(t,channel,index,token){
  const g=decisionGuide(t);return g.suggestionChoice?.token===token&&g.suggestionChoice?.index===index&&g.suggestionChoice?.channel===channel;
}
function materialGuidanceChoose(t,channel,index,token){
  if(!decisionReady(t)||!['auto','personal'].includes(channel)||token!==materialGuidanceToken(t,channel))return;
  const c=materialGuidanceCandidates(t,materialGuidanceResponse(t,channel))[index];if(!c)return;
  const g=decisionGuide(t);g.suggestionChoice={channel,index,token,submitted:false};
  const entry=typeof materialDetailEntry==='function'?materialDetailEntry():null;
  if(entry)entry.suggestionPlan={option_id:c.option_id,pending:c.steps.filter(s=>s.option_id!==c.option_id).map(s=>({label:t.descriptor.options.find(o=>o.id===s.option_id)?.label||'后续事项',instruction:s.instruction})),recorded:false};
  decisionRemember(t);render();
}
function materialGuidanceApplySelection(t,channel,index,token){
  if(!decisionReady(t)||!materialGuidanceChoice(t,channel,index,token))return;
  const c=materialGuidanceCandidates(t,materialGuidanceResponse(t,channel))[index];if(!c?.option_id)return;
  const label=materialGuidanceLabel(c,t.descriptor.options.find(o=>o.id===c.option_id),index);
  const entry=typeof materialDetailEntry==='function'?materialDetailEntry():null;
  if(entry)entry.suggestionPlan={option_id:c.option_id,pending:c.steps.filter(s=>s.option_id!==c.option_id).map(s=>({label:t.descriptor.options.find(o=>o.id===s.option_id)?.label||'后续事项',instruction:s.instruction})),recorded:false};
  decisionChoose(t,c.option_id,true);notify(`已选择“${label}”，请继续核对并明确提交；尚未执行处理。`);
}
function materialGuidanceCandidateNote(c,label){
  const uncertain=Array.isArray(c.uncertainties)&&c.uncertainties.length?`\n待确认：${c.uncertainties.join('；')}`:'';
  return `已选择处理建议：${label}\n建议说明：${String(c.reason||'未提供说明')}${uncertain}\n处理状态：尚未映射为可执行操作，仅记录建议。`.slice(0,2000);
}
async function materialGuidanceSubmit(t,channel,index,token){
  if(!decisionReady(t)||!materialGuidanceChoice(t,channel,index,token))return;
  const c=materialGuidanceCandidates(t,materialGuidanceResponse(t,channel))[index];if(!c)return;
  if(c.option_id)return materialGuidanceApplySelection(t,channel,index,token);
  const g=decisionGuide(t),choice=g.suggestionChoice;
  if(choice.submitting||choice.submitted)return;
  const label=materialGuidanceLabel(c,null,index),identity=decisionIdentity(t),epoch=state.epoch;
  choice.submitting=true;choice.message='正在保存所选处理建议；不会执行财务处理。';decisionRemember(t);render();
  const current=()=>state.epoch===epoch&&currentMaterialTask()?.id===t.id&&decisionIdentity(currentMaterialTask())===identity&&decisionGuide(currentMaterialTask())===g&&g.suggestionChoice===choice;
  try{
    const result=await command('save_material_opinion',t.artifact_id,t.artifact_version,{task_id:t.id,descriptor_hash:t.descriptor.fingerprint,reason:materialGuidanceCandidateNote(c,label)},false);
    if(result?.effect?.object?.status!=='SAVED_NOT_EXECUTED')throw Error('未取得完整建议保存记录，请重试核对。');
    if(!current())return;
    choice.submitted=true;choice.submitting=false;choice.message='处理建议已提交并记录，尚未执行；原问题和后续门禁仍保留。';decisionRemember(t);await loadWorkbench();
  }catch(e){if(current()){choice.submitting=false;choice.message=e.message||'处理建议保存失败，未执行任何处理。';decisionRemember(t);render();}}
  finally{if(current()){choice.submitting=false;decisionRemember(t);render();}}
}
function renderMaterialGuidanceChannel(t,channel){
  const r=materialGuidanceResponse(t,channel),g=decisionGuide(t),cs=materialGuidanceCandidates(t,r);
  const labels={QUEUED:'等待分析',RUNNING:'正在分析',PROPOSED:'待选择，尚未执行',NEEDS_HUMAN:'未映射到可执行方案',LOCAL_ONLY:'意见仅保存在本地',FAILED:'分析失败',STALE:'依据已变化'};
  const token=materialGuidanceToken(t,channel),recommended=cs.findIndex(c=>c.option_id!==null),origin=r?.metadata?.mock===true?'模拟调用':r?.metadata?.mock===false?'真实调用':'调用方式未知',usedLabels={},submittedChannel=g.suggestionChoice?.submitted===true&&g.suggestionChoice?.channel===channel;
  return '<section class="decision-suggestions" aria-label="'+(channel==='auto'?'自动处理建议':'我的方案验证')+'"><h4>'+(channel==='auto'?'自动处理建议':'我的方案验证')+'</h4><p class="small muted">'+esc(r?(labels[r.status]||'建议状态待检查'):'暂无建议')+' · '+origin+(submittedChannel?'。本次建议已记录，不能重复选择。':'。请点击一张卡片选择处理方式，提交前仍需你确认，系统不会直接改动账务。')+'</p>'+(r?.message?'<p>'+esc(r.message)+'</p>':'')+cs.map((c,i)=>{
    const o=t.descriptor.options.find(o=>o.id===c.option_id),chosen=materialGuidanceChoice(t,channel,i,token),label=materialGuidanceLabel(c,o,i,usedLabels),submitted=chosen&&submittedChannel,impact=materialGuidanceImpact(o),plainReason=materialGuidancePlainReason(c,label),plainUncertainties=c.uncertainties.map(materialGuidancePlainText),cardGuide=submittedChannel?'suggestion-card-readonly':'suggestion-card',cardTab=submittedChannel?'':' tabindex="0"';
    const submit=o?(chosen&&!submitted?'<button type="button" class="primary" data-guide="suggestion-submit" data-channel="'+channel+'" data-index="'+i+'" data-guidance-token="'+esc(token)+'">提交处理建议，继续核对</button>':''):(chosen&&!submitted?'<button type="button" class="primary" data-guide="suggestion-submit" data-channel="'+channel+'" data-index="'+i+'" data-guidance-token="'+esc(token)+'">提交处理建议（仅记录）</button>':'');
    return '<article class="decision-suggestion'+(chosen?' is-selected':'')+'" data-guide="'+cardGuide+'" data-channel="'+channel+'" data-index="'+i+'" data-guidance-token="'+esc(token)+'"'+cardTab+' role="group" aria-label="'+esc(label)+'" aria-selected="'+chosen+'"><div class="suggestion-heading"><h4>'+esc(label)+(i===recommended?' <small class="badge">推荐</small>':'')+'</h4><span class="suggestion-state">'+(submitted?'已记录，尚未执行':submittedChannel?'本次未选择':chosen?'已选中，待提交':'点击卡片选择')+'</span></div><p class="small muted">'+(o?'系统可以按此方式继续：'+esc(o.label):'目前还不能直接执行，提交后只记录你的处理意见')+'</p><p>'+esc(plainReason)+'</p>'+(plainUncertainties.length?'<ul>'+plainUncertainties.map(s=>'<li>还需要确认：'+esc(s)+'</li>').join('')+'</ul>':'')+(o?'<p>选择后：'+esc(impact.effects)+'</p><p class="small muted">不会改变：'+esc(impact.notEffects)+'</p>':'')+'<details><summary>查看依据</summary><p>系统判断：'+esc(materialGuidancePlainText(c.reason))+'</p><p>依据位置：'+c.evidence_refs.map(ref=>ref==='task'?'当前事项':esc(t.descriptor.scope.records[Number(ref.slice(7))-1]?.source_anchor?.region||'来源定位待查')).join('；')+'</p>'+(c.steps.length?'<ol>'+c.steps.map(s=>'<li>'+esc(t.descriptor.options.find(o=>o.id===s.option_id)?.label)+'：'+esc(materialGuidancePlainText(s.instruction))+'</li>').join('')+'</ol>':'')+'</details><div class="suggestion-actions">'+submit+'</div>'+(chosen&&g.suggestionChoice?.message?'<p class="small" role="status">'+esc(g.suggestionChoice.message)+'</p>':'')+'</article>';
  }).join('')+(r?.status==='FAILED'&&r.valid===true&&Number.isInteger(r.job_version)&&r.job_id&&decisionReady(t)?'<button type="button" class="secondary" data-guide="guidance-retry" data-channel="'+channel+'" data-guidance-token="'+esc(token)+'">明确重试本项建议</button>':'')+'</section>';
}
function renderMaterialGuidance(t){
  if(decisionSystemTask(t))return '';
  const g=decisionGuide(t),custom=g.custom||{},disabled=!decisionReady(t)||custom.busy;
  return '<section class="decision-agent" aria-label="处理建议与自由方案">'+renderMaterialGuidanceChannel(t,'auto')+(t.personal_material_guidance||custom.response?renderMaterialGuidanceChannel(t,'personal'):'')+'<label for="materialCustomText">我的处理方案（可自由填写）<textarea id="materialCustomText" maxlength="2000" '+(disabled?'disabled':'')+' placeholder="描述你的处理意图；不会直接修改日期、金额或科目。">'+esc(custom.text||'')+'</textarea></label><p class="small muted">验证由服务端脱敏后判断能否映射为现有选项；无法可靠脱敏时仅本地保存。选择建议后仍需填写必填事实并核对摘要。</p><button type="button" class="secondary" data-guide="custom-validate" '+(disabled||!t.descriptor.fingerprint?'disabled':'')+'>整理为处理方案</button><button type="button" class="text" data-guide="opinion-save" '+(disabled||!t.descriptor.fingerprint?'disabled':'')+'>仅保存意见，尚未执行</button><button type="button" class="text" data-guide="guidance-refresh">刷新建议状态（只读取）</button>'+(custom.message?'<p role="status">'+esc(custom.message)+'</p>':'')+(Array.isArray(t.material_opinions)&&t.material_opinions.length?'<details><summary>我的已保存意见（均未执行）</summary>'+t.material_opinions.filter(x=>x.actor_id===state.user?.user_id).map(x=>'<p>'+esc(x.text)+' · '+(x.valid?'当前依据':'依据已变化')+'</p>').join('')+'</details>':'')+'</section>';
}
async function materialGuidanceCustom(t){
  if(!decisionReady(t)||!t.descriptor.fingerprint)return;
  const g=decisionGuide(t),custom=g.custom||(g.custom={text:''});if(custom.busy)return;
  const text=String(custom.text||'').trim();if(!text||text.length>2000){notify('请填写一至2000字的处理方案。',true);return;}
  if(custom.requestText!==text||custom.response?.status==='FAILED'){custom.requestText=text;custom.request_id=crypto.randomUUID();delete custom.response;}
  const identity=decisionIdentity(t),epoch=state.epoch;custom.busy=true;custom.message='正在验证方案；尚未执行任何处理。';decisionRemember(t);render();
  const current=()=>state.epoch===epoch&&currentMaterialTask()?.id===t.id&&decisionIdentity(currentMaterialTask())===identity&&decisionGuide(currentMaterialTask())===g&&g.custom===custom&&String(custom.text||'').trim()===text;
  try{
    const response=await request('/api/v1/agent/suggestion',{scope:scope(),stage:'MATERIAL_GUIDANCE',task_id:t.id,descriptor_hash:t.descriptor.fingerprint,request_id:custom.request_id,user_text:text});
    if(!current())return;
    if(response?.descriptor_hash!==t.descriptor.fingerprint||!['PROPOSED','NEEDS_HUMAN','LOCAL_ONLY','RUNNING','FAILED'].includes(response.status)||['PROPOSED','NEEDS_HUMAN'].includes(response.status)&&!materialGuidanceCandidates(t,response).length)throw Error('方案响应与当前契约不匹配，未采用。');
    custom.response=response;custom.dirty=false;custom.message=response.message||'方案已验证，尚未执行。';delete g.suggestionChoice;
  }catch(e){if(current())custom.message=e.message||'验证失败，可明确重试同一请求。';}
  finally{custom.busy=false;if(current()){decisionRemember(t);render();}}
}
async function materialGuidanceSaveOpinion(t){
  if(!decisionReady(t)||!t.descriptor.fingerprint)return;
  const g=decisionGuide(t),custom=g.custom||(g.custom={text:''}),reason=String(custom.text||'').trim();if(custom.busy||!reason||reason.length>2000)return;
  const identity=decisionIdentity(t),epoch=state.epoch;custom.busy=true;
  const current=()=>state.epoch===epoch&&currentMaterialTask()?.id===t.id&&decisionIdentity(currentMaterialTask())===identity&&decisionGuide(currentMaterialTask())===g;
  try{const result=await command('save_material_opinion',t.artifact_id,t.artifact_version,{task_id:t.id,descriptor_hash:t.descriptor.fingerprint,reason},false);if(result?.effect?.object?.status!=='SAVED_NOT_EXECUTED')throw Error('未取得完整意见保存记录，请重试核对。');if(!current())return;custom.message='意见已保存，尚未执行；未排队、未调用模型，原问题和门禁保留。';await loadWorkbench();}
  catch(e){if(current())custom.message=e.message||'意见保存失败，原文已保留。';}
  finally{custom.busy=false;if(current()){decisionRemember(t);render();}}
}
async function materialGuidanceRetry(t,channel,token){
  if(!decisionReady(t)||!['auto','personal'].includes(channel)||token!==materialGuidanceToken(t,channel))return;
  const r=materialGuidanceResponse(t,channel);if(r?.valid!==true||r.status!=='FAILED'||!r.job_id||!Number.isInteger(r.job_version))return;
  const epoch=state.epoch,identity=decisionIdentity(t);
  try{await command('retry_material_guidance',r.job_id,r.job_version,{},false);if(epoch===state.epoch&&currentMaterialTask()?.id===t.id&&decisionIdentity(currentMaterialTask())===identity){await loadWorkbench();notify('建议已明确重试；尚未执行任何业务处理。');}}catch(e){if(epoch===state.epoch)notify(e.message,true);}
}
function materialGuidancePeriodToken(){return JSON.stringify([state.user?.user_id,state.epoch,scopeKey(scope()),state.overview?.period]);}
function renderMaterialGuidanceOverview(){
  if(!Array.isArray(state.overview?.material_review?.tasks))return '';
  return '<section class="panel pad"><h3>资料处理建议</h3><p class="small muted">解析等后台事件可自动排队；打开页面和刷新只读取结果。明确发起可能调用模型，但不执行业务方案。</p>'+(materialCanWrite()?'<button type="button" class="secondary" data-action="material-guidance-request" data-guidance-token="'+esc(materialGuidancePeriodToken())+'">明确生成本期处理建议</button>':'')+'</section>';
}
function installMaterialGuidanceActions(){
  actions['material-guidance-request']=b=>exclusive(async()=>{const p=state.overview?.period,token=materialGuidancePeriodToken();if(!materialCanWrite()||b.dataset.guidanceToken!==token||!p?.object_id||!Number.isInteger(p.version))return;try{await command('request_material_guidance',p.object_id,p.version,{},false);if(token===materialGuidancePeriodToken()){await loadWorkbench();notify('本期建议已明确请求，未执行财务处理。');}}catch(e){if(token===materialGuidancePeriodToken())notify(e.message,true);}});
}

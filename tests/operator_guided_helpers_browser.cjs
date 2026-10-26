// Shared user-visible navigation only. Never invokes product handlers or mutates guided state.
const assert=require('node:assert/strict');
function guided(page){
 const button=name=>page.locator(`.decision-chat [data-guide="${name}"]:visible`);
 const settle=()=>page.waitForFunction(()=>!state.busy);
 const focus=async()=>assert(await page.evaluate(()=>{
  const card=document.querySelector('.decision-chat'),active=document.activeElement;
  const summary=card?.querySelector('.decision-summary');
  if(summary)return active===summary.querySelector('h4');
  const current=card?.querySelector('fieldset[data-guide-step]:not([hidden])');
  return current?current.contains(active)&&(active.tagName==='LEGEND'||active.matches('input,select,textarea')):active===card?.querySelector('.decision-handling>h4');
 }),'Guide focus must land on the current question/field, or the confirmation summary heading');
 const next=async()=>{const before=await page.locator('fieldset[data-guide-step]:visible').getAttribute('data-guide-step');await button('next').click();await settle();if(await page.locator('.decision-summary:visible').count()||await page.locator('fieldset[data-guide-step]:visible').getAttribute('data-guide-step')!==before)await focus();};
 const review=async()=>{
  for(let i=0;i<7;i++){
   if(await page.locator('.decision-summary:visible').count())return;
   const before=await page.locator('fieldset[data-guide-step]:visible').getAttribute('data-guide-step');
   await next();
   if(!await page.locator('.decision-summary:visible').count())assert.notEqual(await page.locator('fieldset[data-guide-step]:visible').getAttribute('data-guide-step'),before,'Guide did not advance: fill the visible required answer first');
  }
  throw Error('Guide did not reach confirmation summary');
 };
 const commit=async()=>{assert(await page.locator('.decision-summary').isVisible());assert.equal(await button('commit').count(),1);await button('commit').click();await settle();};
 const choose=async id=>{await page.locator(`[data-guide="option"][data-option="${id}"]`).click();await settle();await focus();};
 const source=async()=>{const outer=page.locator('.decision-evidence-disclosure');if(await outer.count()&&await outer.getAttribute('open')===null)await outer.locator(':scope > summary').click();const d=page.locator('.decision-source');if(await d.getAttribute('open')===null)await d.locator(':scope > summary').click();};
 const closeSource=async()=>{const d=page.locator('.decision-source');if(await d.getAttribute('open')!==null)await d.locator(':scope > summary').click();};
 const sourceDialog=async()=>{await source();await page.locator('.decision-source [data-object]').first().click();await page.locator('#dialog[open]').waitFor();await page.keyboard.press('Escape');};
 return {next,review,commit,choose,source,closeSource,sourceDialog,settle,focus,
  finish:async()=>{await review();await commit();},
  resume:async()=>{await button('resume').click();await settle();await focus();},
  edit:async step=>{await page.locator(`[data-guide="edit"][data-step="${step}"]`).click();await settle();await focus();},
  back:async()=>{await button('back').click();await settle();await focus();}
 };
}
module.exports={guided};

if(location.protocol!=='file:'){
const subject=document.getElementById('set-subject'),topic=document.getElementById('set-topic'),start=document.getElementById('start-set'),count=document.getElementById('set-count');let bank=[],categories=[],caseProgress={};
function fill(select,values,label){select.replaceChildren(new Option(label,''),...values.map(v=>new Option(v,v)));}
const collection=document.getElementById('set-collection');
function refreshCollections(){try{const old=collection.value;collection.replaceChildren(new Option('All questions',''),...Collections.read().map(c=>new Option(c.name+' ('+bank.filter(q=>c.questions.includes(q.id)).length+')',c.id)));collection.value=old;update()}catch(e){count.textContent=e.message;start.disabled=true}}
collection.onchange=update;window.addEventListener('collections-changed',refreshCollections);window.addEventListener('storage',refreshCollections);
document.getElementById('new-collection-form').onsubmit=async e=>{e.preventDefault();try{const id=await Collections.create(document.getElementById('new-collection-name').value);collection.value=id;document.getElementById('new-collection-name').value='';document.getElementById('new-collection-state').textContent='Collection created. Add questions while taking a quiz.';update()}catch(err){document.getElementById('new-collection-state').textContent=err.message}};
const mode=document.getElementById('session-mode'),grid=document.getElementById('case-grid');let selectedCases=new Set(),visibleCases=[],anchor=null,drag=null;
function eligible(){return bank.filter(q=>mode.value!=='case_scenarios'||q.case_id)}
function selection(){return eligible().filter(q=>Collections.contains(collection.value,q.id)&&(!subject.value||q.subject===subject.value)&&(!topic.value||q.topic===topic.value))}
function update(){
 const scenario=mode.value==='case_scenarios',selected=selection();
 document.getElementById('case-picker').hidden=!scenario;
 document.getElementById('mode-description').textContent=scenario?'Only linked case scenarios. Submit each answer for feedback, then continue to the next step. Answers lock after submission. Results are separate from Exam scores.':mode.value==='reviewer'?'Standalone questions give immediate feedback; linked cases show answers after the case is complete.':'Answers appear after submitting the whole exam.';
 visibleCases=[...new Set(selected.map(q=>q.case_id).filter(Boolean))].sort();
 selectedCases=new Set([...selectedCases].filter(id=>visibleCases.includes(id)));
 grid.replaceChildren(...visibleCases.map(id=>{const b=document.createElement('button');b.type='button';b.className='scenario-box';b.dataset.id=id;b.setAttribute('aria-pressed',String(selectedCases.has(id)));const title=document.createElement('strong');title.textContent=id;const detail=document.createElement('small');detail.textContent=bank.filter(q=>q.case_id===id).length+' questions';const status=document.createElement('small');const progress=caseProgress?.[id];status.textContent=progress?progress.status+' · '+progress.confirmed+'/'+progress.questions:caseProgress===null?'Progress unavailable':'Not started';b.append(title,detail,status);b.setAttribute('aria-label','Scenario '+id+', '+detail.textContent+', '+status.textContent);return b}));
 refreshSelection();window.dispatchEvent(new Event('learning-selection-changed'));
}
function refreshSelection(){
 const scenario=mode.value==='case_scenarios';
 for(const b of grid.children)b.setAttribute('aria-pressed',String(selectedCases.has(b.dataset.id)));
 const chosen=scenario?eligible().filter(q=>selectedCases.has(q.case_id)):selection();
 count.textContent=(scenario?`${selectedCases.size} scenarios · `:'')+`${chosen.length} questions · ${chosen.reduce((n,q)=>n+q.maximum,0)} points`;
 start.disabled=!chosen.length;start.textContent=scenario?'Start selected scenarios →':mode.value==='reviewer'?'Start review →':'Start exam →';
 if(scenario&&!visibleCases.length)count.textContent='No case scenarios match these filters.';
 else if(scenario&&!selectedCases.size)count.textContent='Select one or more scenarios to begin.';
 document.getElementById('select-all-cases').disabled=!visibleCases.length;document.getElementById('clear-cases').disabled=!selectedCases.size;
}
function range(from,to){const a=visibleCases.indexOf(from),b=visibleCases.indexOf(to);return visibleCases.slice(Math.min(a,b),Math.max(a,b)+1)}
function choose(id,extend,add){
 if(extend&&visibleCases.includes(anchor)){selectedCases=new Set([...(add?selectedCases:[]),...range(anchor,id)])}
 else if(add){if(selectedCases.has(id))selectedCases.delete(id);else selectedCases.add(id);anchor=id}
 else{selectedCases=new Set([id]);anchor=id}
 refreshSelection();
}
grid.onpointerdown=e=>{const box=e.target.closest('.scenario-box');if(!box||e.button!==0)return;e.preventDefault();const base=new Set(selectedCases),id=box.dataset.id;choose(id,e.shiftKey,e.ctrlKey||e.metaKey);box.focus();drag={pointer:e.pointerId,start:e.shiftKey&&visibleCases.includes(anchor)?anchor:id,base:e.ctrlKey||e.metaKey?base:new Set(),remove:(e.ctrlKey||e.metaKey)&&base.has(id)};grid.setPointerCapture(e.pointerId)};
grid.onpointermove=e=>{if(!drag||e.pointerId!==drag.pointer)return;const box=document.elementFromPoint(e.clientX,e.clientY)?.closest('.scenario-box');if(!box||!grid.contains(box))return;const ids=range(drag.start,box.dataset.id);selectedCases=new Set(drag.base);for(const id of ids){if(drag.remove)selectedCases.delete(id);else selectedCases.add(id)}refreshSelection()};
function endDrag(){drag=null}grid.onpointerup=endDrag;grid.onpointercancel=endDrag;grid.onlostpointercapture=endDrag;
grid.onclick=e=>{if(e.detail!==0)return;const box=e.target.closest('.scenario-box');if(box)choose(box.dataset.id,e.shiftKey,e.ctrlKey||e.metaKey)};
grid.onkeydown=e=>{const box=e.target.closest('.scenario-box');if(!box)return;const index=visibleCases.indexOf(box.dataset.id);let next=index;const columns=[...grid.children].filter(b=>b.offsetTop===grid.firstElementChild.offsetTop).length;
 if(e.key==='ArrowRight')next++;else if(e.key==='ArrowLeft')next--;else if(e.key==='ArrowDown')next+=columns;else if(e.key==='ArrowUp')next-=columns;else if(e.key==='Home')next=0;else if(e.key==='End')next=visibleCases.length-1;else if(e.key===' '||e.key==='Enter'){e.preventDefault();choose(box.dataset.id,e.shiftKey,e.ctrlKey||e.metaKey);return}else return;
 e.preventDefault();next=Math.max(0,Math.min(visibleCases.length-1,next));grid.children[next].focus();if(e.shiftKey){if(!anchor)anchor=box.dataset.id;choose(visibleCases[next],true,e.ctrlKey||e.metaKey)}
};
document.getElementById('select-all-cases').onclick=()=>{selectedCases=new Set(visibleCases);anchor=visibleCases[0]||null;refreshSelection()};document.getElementById('clear-cases').onclick=()=>{selectedCases.clear();anchor=null;refreshSelection()};
function compatible(q,m=mode.value){return m!=='case_scenarios'||!!q.case_id}
function refreshModes(){for(const option of mode.options){option.disabled=!bank.some(q=>(!subject.value||q.subject===subject.value)&&(!topic.value||q.topic===topic.value)&&compatible(q,option.value));option.title=option.disabled?'No questions available for this subject and topic.':'';}}
function topics(preserve=false){const old=topic.value;fill(topic,[...new Set(eligible().filter(q=>!subject.value||q.subject===subject.value).map(q=>q.topic).filter(Boolean))].sort(),'All topics');if(preserve&&[...topic.options].some(o=>o.value===old))topic.value=old;refreshModes();update()}
let previousMode=mode.value;
mode.onchange=()=>{if(!bank.some(q=>(!subject.value||q.subject===subject.value)&&(!topic.value||q.topic===topic.value)&&compatible(q))){mode.value=previousMode;count.textContent='This mode has no questions for your selected topic. Choose another topic first.';return;}previousMode=mode.value;const old=subject.value;fill(subject,[...new Set(eligible().map(q=>q.subject))].sort(),'All subjects');if([...subject.options].some(o=>o.value===old))subject.value=old;topics(true)};
subject.onchange=()=>topics();topic.onchange=()=>{refreshModes();update()};
start.onclick=()=>{const p=new URLSearchParams({set:'1',mode:document.getElementById('session-mode').value});if(mode.value==='case_scenarios')p.set('cases',visibleCases.filter(id=>selectedCases.has(id)).join(','));if(collection.value)p.set('collection',collection.value);p.set('v','accounts1');if(subject.value)p.set('subject',subject.value);if(topic.value)p.set('topic',topic.value);location.href='/?'+p};
Promise.all([fetch('/api/questions').then(r=>{if(!r.ok)throw Error();return r.json()}),fetch('/api/organization').then(r=>{if(!r.ok)throw Error();return r.json()}),Account.request('/api/scenario-progress').catch(()=>{document.getElementById('scenario-progress-status').textContent='Progress could not be loaded. Refresh to try again.';return null})]).then(([qs,org,progress])=>{bank=qs;categories=org;caseProgress=progress;fill(subject,[...new Set(org.map(c=>c.subject))].sort(),'All subjects');subject.onchange();refreshCollections();}).catch(()=>{count.textContent='Could not load the question bank. Start the local server and refresh.'});
}

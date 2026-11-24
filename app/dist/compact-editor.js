(()=>{
const nav=document.querySelector('nav[aria-label="Question bank workflows"]');
if(nav){nav.removeAttribute('style');nav.classList.add('workflow-tabs');nav.children[1].href='/admin?workflow=scenario';[...nav.children].forEach((a,i)=>{const icon=document.createElement('span');icon.textContent=['▤','▥','▦'][i];icon.setAttribute('aria-hidden','true');a.prepend(icon)});}
let built=false;
function update(){
 const standalone=document.body.dataset.questionWorkflow==='standalone';
 if(nav)[...nav.children].forEach((a,i)=>{if(i===(standalone?0:1))a.setAttribute('aria-current','page');else a.removeAttribute('aria-current')});
 if(!standalone||built)return;built=true;
 const list=document.getElementById('list');list.classList.add('tile-library');
 const toolbar=document.createElement('div');toolbar.className='library-view';toolbar.innerHTML='<strong>Questions</strong><div role="group" aria-label="Question display"><button type="button" aria-pressed="true">Grid</button><button type="button" aria-pressed="false">List</button></div>';
 list.before(toolbar);
 toolbar.querySelectorAll('button').forEach((b,i)=>b.onclick=()=>{list.classList.toggle('tile-library',i===0);toolbar.querySelectorAll('button').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));});
 const legend=document.createElement('div');legend.className='tile-legend';legend.innerHTML=['Published','Draft','Reviewed','Archived'].map(s=>'<span><i data-status="'+s+'"></i>'+s+'</span>').join('');list.after(legend);
 const preview=document.createElement('div');preview.className='tile-preview';preview.hidden=true;legend.after(preview);
 function decorate(){list.querySelectorAll('.question-item').forEach(b=>{const status=b.querySelector('.list-status')?.textContent||'Draft',code=b.querySelector('strong')?.textContent||'';b.dataset.status=status;b.setAttribute('aria-label',code+', '+status);b.setAttribute('aria-pressed',String(b.classList.contains('active')));b.title=code+' · '+status+'\n'+(b.querySelector('span')?.textContent||'');});preview.hidden=true;}
 function show(e){const b=e.target.closest('.question-item');if(!b)return;preview.replaceChildren();for(const selector of ['strong','span','small']){const source=b.querySelector(selector);if(source){const line=document.createElement(selector==='strong'?'strong':'p');line.textContent=source.textContent;preview.append(line)}}preview.hidden=false;}
 list.addEventListener('pointerover',show);list.addEventListener('focusin',show);
 list.addEventListener('pointerleave',()=>{if(!list.contains(document.activeElement))preview.hidden=true});
 list.addEventListener('focusout',e=>{if(!list.contains(e.relatedTarget))preview.hidden=true});
 new MutationObserver(decorate).observe(list,{childList:true});decorate();
}
window.addEventListener('question-workflow',update);if(document.body.dataset.questionWorkflow)update();
})();

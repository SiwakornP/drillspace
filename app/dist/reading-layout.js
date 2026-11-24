(()=>{
 document.body.classList.add('reading-layout');
 const workspace=document.querySelector('.workspace'),nav=document.getElementById('navigator');if(!workspace||!nav)return;
 const controls=document.createElement('div');controls.className='reading-controls';controls.setAttribute('role','group');controls.setAttribute('aria-label','Reading text size');controls.innerHTML='<span>Text size</span><button type="button" data-size="standard">Standard</button><button type="button" data-size="large">Large</button>';workspace.before(controls);workspace.prepend(controls);
 const key='drillspace-reading-size';function setSize(size){document.body.classList.toggle('large-text',size==='large');controls.querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.size===size)));try{localStorage.setItem(key,size)}catch{}}
 let size='standard';try{size=localStorage.getItem(key)==='large'?'large':'standard'}catch{}setSize(size);controls.querySelectorAll('button').forEach(b=>b.onclick=()=>setSize(b.dataset.size));
 const toggle=document.createElement('button');toggle.type='button';toggle.className='navigator-heading';toggle.setAttribute('aria-controls','navigator');toggle.setAttribute('aria-expanded','true');toggle.textContent='Questions ▴';nav.before(toggle);toggle.onclick=()=>{nav.hidden=!nav.hidden;toggle.setAttribute('aria-expanded',String(!nav.hidden));toggle.textContent=nav.hidden?'Questions ▾':'Questions ▴'};
 function compact(){const status=document.getElementById('save-progress');if(status){const bar=status.parentElement;bar.classList.add('session-toolbar');const a=bar.querySelector('a');if(a&&a.textContent!=='My attempts')a.textContent='My attempts';if(controls.previousElementSibling!==bar)bar.after(controls);}}
 const observer=new MutationObserver(compact);observer.observe(workspace,{childList:true,subtree:true});compact();
})();

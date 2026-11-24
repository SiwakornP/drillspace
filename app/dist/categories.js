Account.ready.then(async user=>{
 if(user.role!=='admin'){location.replace('/sets.html');return;}
 const $=id=>document.getElementById(id);let org=[],pending=null,saving=false;
 function options(id,values){const old=$(id).value;$(id).replaceChildren(...values.map(x=>new Option(x,x)));if(values.includes(old))$(id).value=old;}
 function render(){const topic=$('scope').value==='topic',action=$('action').value;
 options('topic',[...new Set(org.filter(x=>x.subject===$('subject').value).map(x=>x.topic).filter(Boolean))].sort());
 $('topic-label').hidden=!topic;const source=topic?$('topic').value:$('subject').value;
 options('target-existing',[...new Set(org.filter(x=>!topic||x.subject===$('subject').value).map(x=>topic?x.topic:x.subject).filter(x=>x&&x!==source))].sort());
 $('name-label').hidden=action!=='rename';$('merge-label').hidden=action!=='merge';
 $('target-name').required=action==='rename';$('target-existing').required=action==='merge';$('topic').required=topic;
 $('guidance').textContent=action==='delete'?'Only categories with no questions or scenarios can be deleted.':action==='merge'?'All associated questions and scenarios move to the selected category. Matching topics are combined when merging subjects.':'The new name applies to all associated questions and scenarios.';
 $('preview').disabled=!source||(action==='merge'&&!$('target-existing').value);
 }
 async function load(){org=await Account.request('/api/organization');options('subject',[...new Set(org.map(x=>x.subject))].sort());render();}
 for(const id of ['scope','subject','topic','action'])$(id).onchange=render;
 $('category-form').onsubmit=async e=>{e.preventDefault();$('preview').disabled=true;try{pending={scope:$('scope').value,action:$('action').value,subject:$('subject').value,topic:$('topic').value,target:$('action').value==='merge'?$('target-existing').value:$('target-name').value};const p=await Account.request('/api/admin/categories-preview',pending);pending.token=p.token;$('summary').textContent=p.action.toUpperCase()+': '+p.source+(p.target?' → '+p.target:'')+'. '+p.questions+' questions and '+p.scenarios+' scenarios affected.';$('items').replaceChildren(...p.items.map(x=>{const li=document.createElement('li');li.textContent=x.kind+': '+x.label;return li}));$('save-message').textContent='';$('review').showModal();}catch(e){$('message').textContent=e.message}finally{render()}};
 $('cancel').onclick=()=>{if(!saving)$('review').close()};$('review').addEventListener('cancel',e=>{if(saving)e.preventDefault()});
 $('save').onclick=async()=>{saving=true;$('save').disabled=$('cancel').disabled=true;$('save-message').textContent='Creating backup and saving…';try{await Account.request('/api/admin/categories-commit',pending);$('review').close();await load();$('message').textContent='Saved. Backup verified and changes recorded. Download a fresh Master Excel before your next workbook edit.';}catch(e){$('save-message').textContent=e.message}finally{saving=false;$('save').disabled=$('cancel').disabled=false}};
 try{await load()}catch(e){$('message').textContent=e.message;$('preview').disabled=true;}
}).catch(()=>{});

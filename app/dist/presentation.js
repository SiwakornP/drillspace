(()=>{
const esc=v=>String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
window.presentQuestion=text=>{
 if(/[\n\r*]/.test(String(text))){
  const parts=String(text).replace(/\r\n?/g,'\n').split('\n');
  let first=parts.findIndex(s=>s.trim()),last=parts.length-1;while(last>=0&&!parts[last].trim())last--;
  let title='',prompt='';
  if(first>=0&&/^(?:\*\*)?Case\s+[A-Za-z0-9_-]+(?:\*\*)?\s*$/i.test(parts[first].trim())){title=parts[first];parts[first]='';}
  if(last>=0&&last!==first&&/\?(?:\*\*)?\s*$/.test(parts[last])){prompt=parts[last];parts[last]='';}
  return `${title?`<h2 class="case-reading-title">${RichText.inline(title)}</h2>`:''}<div class="question-prompt" style="font-weight:normal">${RichText.render(parts.join('\n').trim())}</div>${prompt?`<h2 class="clinical-question">${RichText.inline(prompt)}</h2>`:''}`;
 }

 const lines=String(text).split(/\r?\n/).map(x=>x.trim()).filter(Boolean);
 const marker=/^(History|Physical examination(?: reveals)?|Laboratory findings|Radiograph findings|Imaging findings|Investigations):?$/i;
 if(!lines.some(x=>marker.test(x)))return `<h2 class="question-prompt">${esc(text).replace(/\n/g,'<br>')}</h2>`;
 const groups=[];let group={title:'History',lines:[]};let prompt='';
 lines.forEach((line,i)=>{const match=line.match(marker);if(match){if(group.lines.length)groups.push(group);group={title:match[1].replace(/ reveals$/i,''),lines:[]}}else if(i===lines.length-1&&line.endsWith('?')){prompt=line}else group.lines.push(line)});
 if(group.lines.length)groups.push(group);
 return `<div class="clinical-case">${groups.map(g=>`<section class="case-section"><h3>${esc(g.title)}</h3>${g.title.toLowerCase()==='history'?g.lines.map(x=>`<p>${esc(x)}</p>`).join(''):`<ul>${g.lines.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`}</section>`).join('')}</div>${prompt?`<h2 class="question-prompt">${esc(prompt)}</h2>`:''}`;
};
})();

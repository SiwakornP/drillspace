"""Previewed, atomic category maintenance; historical attempts remain untouched."""
import sqlite3,json,hashlib,datetime
import cases

def state(db):
 return {t:list(db.execute('SELECT '+cols+' FROM '+t+' ORDER BY 1,2')) for t,cols in [('organization','subject,topic'),('questions','id,body,revision'),('cases','id,body,revision')]}
def plan(db,data):
 s=state(db); digest=hashlib.sha256(json.dumps(s,sort_keys=True).encode()).hexdigest()
 scope=data.get('scope');action=data.get('action')
 if scope not in ['subject','topic'] or action not in ['rename','merge','delete']:raise ValueError('Choose a valid category action.')
 def name(key):
  v=data.get(key,'')
  if not isinstance(v,str) or not v.strip() or len(v.strip())>100:raise ValueError('Names must contain 1–100 characters.')
  return v.strip()
 subject=name('subject');topic=name('topic') if scope=='topic' else ''
 org=set(map(tuple,s['organization']))
 for table in ['questions','cases']:
  for _,b,_ in s[table]:
   q=json.loads(b);org.add((q.get('subject',''),q.get('topic','')))
 org={p for p in org if p[0]}
 if subject not in {p[0] for p in org} or (scope=='topic' and (subject,topic) not in org):raise ValueError('Category no longer exists. Reload and try again.')
 target=name('target') if action!='delete' else ''
 existing={p[0] for p in org} if scope=='subject' else {t for a,t in org if a==subject}
 source=subject if scope=='subject' else topic
 if target==source:raise ValueError('Choose a different name.')
 matches=[n for n in existing if n.casefold()==target.casefold()]
 if action=='merge':
  if not matches or matches[0]==source:raise ValueError('Choose another existing category to merge into.')
  target=matches[0]
 if action=='rename' and any(n!=source for n in matches):raise ValueError('That name already exists. Use Merge instead.')
 def match(a,b):return a==subject and (scope=='subject' or b==topic)
 def destination(a,b):
  if scope=='topic':return (a,target)
  canonical=next((t for a,t in sorted(org) if a==target and t.casefold()==b.casefold()),b) if action=='merge' else b
  return (target,canonical)
 updates={};items=[]
 for table in ['questions','cases']:
  updates[table]=[]
  for ident,body,rev in s[table]:
   q=json.loads(body)
   if match(q.get('subject'),q.get('topic')):
    if action=='delete':raise ValueError('This category contains questions or scenarios (including archived questions). Move them to another category first.')
    new=dict(q);new['subject'],new['topic']=destination(q['subject'],q['topic'])
    updates[table].append((ident,body,rev,json.dumps(new)))
    items.append({'kind':'Question' if table=='questions' else 'Scenario','label':q.get('display_code') or ident})
 result=set()
 for a,b in org:
  if match(a,b):
   if action!='delete':result.add(destination(a,b))
  else:result.add((a,b))
 if scope=='topic' and not any(a==subject for a,b in result):result.add((subject,''))
 bank={i:json.loads(b) for i,b,r in s['questions']};cb=cases.load(db)
 for i,_,_,b in updates['questions']:bank[i]=json.loads(b)
 for i,_,_,b in updates['cases']:cb[i]=json.loads(b)
 cases.graph(bank,cb)
 summary={'token':digest,'scope':scope,'action':action,'source':subject+(' / '+topic if scope=='topic' else ''),'target':target,'questions':len(updates['questions']),'scenarios':len(updates['cases']),'items':items}
 return summary,updates,sorted(result)

def preview(path,data):
 with sqlite3.connect(path) as db:return plan(db,data)[0]

def commit(path,data,backup,actor):
 def prepare(db):
  p=plan(db,data)
  if p[0]['token']!=data.get('token'):raise ValueError('The bank changed after your preview. Preview again before saving.')
  return p
 with sqlite3.connect(path) as db:prepare(db)
 saved=backup()
 if not saved.get('verified'):raise ValueError('Backup verification failed. Nothing was saved.')
 with sqlite3.connect(path,timeout=15) as db:
  db.execute('BEGIN IMMEDIATE');summary,updates,org=prepare(db)
  before=state(db);stamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
  for table,rows in updates.items():
   for ident,old,rev,new in rows:
    db.execute('UPDATE '+table+' SET body=?,revision=revision+1 WHERE id=?',(new,ident))
    history='question_edit_history' if table=='questions' else 'case_edit_history';key='question_id' if table=='questions' else 'case_id'
    db.execute('INSERT INTO '+history+'('+key+',actor_id,created,old_revision,new_revision,before_body,after_body) VALUES (?,?,?,?,?,?,?)',(ident,actor,stamp,rev,rev+1,old,new))
  db.execute('DELETE FROM organization');db.executemany('INSERT INTO organization VALUES (?,?)',org)
  db.execute('CREATE TABLE IF NOT EXISTS category_edit_history(id INTEGER PRIMARY KEY,actor_id INTEGER,created TEXT,action TEXT,before_body TEXT,after_body TEXT,backup TEXT)')
  db.execute('INSERT INTO category_edit_history(actor_id,created,action,before_body,after_body,backup) VALUES (?,?,?,?,?,?)',(actor,stamp,json.dumps(summary),json.dumps(before),json.dumps(state(db)),saved['archive']))
 return dict(summary,backup=saved['archive'])

"""Shared cases, link validation and immutable attempt presentation."""
import json,re,sqlite3
FIELDS=['id','title','history','examination','laboratory','subject','topic']
LEGACY_HEADERS=['Case ID','Revision','Title','History','Physical examination','Laboratory findings']
HEADERS=LEGACY_HEADERS+['Subject','Topic']
def initialize(path):
 with sqlite3.connect(path) as db:db.execute('CREATE TABLE IF NOT EXISTS cases(id TEXT PRIMARY KEY,body TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1)')
def load(db):
 result={i:dict(json.loads(b),revision=r) for i,b,r in db.execute('SELECT id,body,revision FROM cases')}
 for c in result.values():
  if 'subject' not in c or 'topic' not in c:
   row=db.execute("SELECT body FROM questions WHERE json_extract(body,'$.case_id')=? ORDER BY id LIMIT 1",(c['id'],)).fetchone()
   q=json.loads(row[0]) if row else {}
   c.setdefault('subject',q.get('subject',''));c.setdefault('topic',q.get('topic',''))
 return result

def validate(c):
 if not isinstance(c,dict) or not re.fullmatch(r'[A-Za-z0-9_-]{1,50}',str(c.get('id',''))):raise ValueError('Case ID needs 1–50 letters, numbers, underscores or hyphens.')
 out={k:c.get(k,'') for k in FIELDS}
 for k,v in out.items():
  if not isinstance(v,str) or len(v)>20000:raise ValueError('Case fields must be text under 20,000 characters.')
  out[k]=v.strip()
 if any(not out[k] or len(out[k])>100 for k in ['subject','topic']):raise ValueError('Enter the shared scenario subject and topic (up to 100 characters each).')
 if not out['title'] or not out['history']:raise ValueError('Enter a case title and history.')
 return out
def link(q,result):
 cid=q.get('case_id') or None;order=q.get('case_order')
 if cid:
  if not isinstance(cid,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,50}',cid):raise ValueError('Invalid Case ID.')
  if type(order) not in (int,float) or order!=int(order) or not 1<=order<=26:raise ValueError('Case order must be a whole number from 1 to 26 (A–Z).')
  result.update(case_id=cid,case_order=int(order))
 elif order not in (None,''):raise ValueError('Case order requires a Case ID.')
 findings=q.get('additional_findings') or ''
 if not isinstance(findings,str) or len(findings)>20000:raise ValueError('Additional findings must be text under 20,000 characters.')
 if findings.strip():
  if not cid:raise ValueError('Additional findings require a linked case.')
  result['additional_findings']=findings.strip()
 return result
def graph(bank,casebank):
 seen=set();categories={}
 for q in bank.values():
  cid=q.get('case_id')
  if not cid:continue
  if cid not in casebank:raise ValueError('Unknown Case ID: '+cid)
  c=casebank[cid]
  if c.get('subject') and c.get('topic') and (q['subject'],q['topic'])!=(c['subject'],c['topic']):raise ValueError('Subject and topic are managed in the shared scenario: '+cid)
  if q.get('status')=='Archived':continue
  key=(cid,q['case_order'])
  if key in seen:raise ValueError('Each active question in a case needs a unique order: '+cid)
  seen.add(key)
  category=(q['subject'],q['topic'])
  if cid in categories and categories[cid]!=category:raise ValueError('Questions in '+cid+' must share subject and topic.')
  categories[cid]=category
 # Every write path using graph must preserve whole-case publication.
 for cid in categories:
  qs=members(bank,cid)
  if any(q['status']=='Published' for q in qs) and not released(bank,cid):
   raise ValueError('Publish or return all questions in '+cid+' to Draft together using the Case scenarios. Check question order for gaps.')

def snapshot(bank,ids,casebank,admin):
 # Expand any selected member to the full eligible case, including collection practice.
 expanded=[];groups=set()
 for ident in ids:
  q=bank[ident];cid=q.get('case_id')
  if cid and not admin and not released(bank,cid):raise ValueError('This case is not fully published. Choose another case.')
  key=('case',cid) if cid else ('question',ident)
  if key in groups:continue
  groups.add(key)
  members=[x for x in bank.values() if x.get('case_id')==cid and x.get('status')!='Archived' and (admin or x.get('status')=='Published')] if cid else [q]
  for member in sorted(members,key=lambda x:(x.get('case_order',0),x['id'])):
   item=dict(member)
   if cid:
    item['case']=casebank[cid]
    if any(x.get('additional_findings') for x in members):item['staged_case']=True
   item['display_label']=(cid+chr(64+item['case_order'])) if cid else str(len(groups))
   expanded.append(item)
 if len(expanded)>1000:raise ValueError('Choose fewer cases; maximum 1,000 questions per attempt.')
 return expanded

def members(bank,cid):return sorted([q for q in bank.values() if q.get('case_id')==cid and q.get('status')!='Archived'],key=lambda q:(q['case_order'],q['id']))
def issues(qs):
 if not qs:return ['No active questions linked to this case.']
 orders=[q['case_order'] for q in qs];out=[]
 if sorted(orders)!=list(range(1,len(qs)+1)):out.append('Question orders must run consecutively from 1 (A), without gaps or duplicates.')
 if len({(q['subject'],q['topic']) for q in qs})>1:out.append('Linked questions have different subjects or topics.')
 return out
def released(bank,cid):
 qs=members(bank,cid)
 return bool(qs) and not issues(qs) and all(q['status']=='Published' for q in qs)
def overview(path):
 with sqlite3.connect(path) as db:
  bank={i:dict(json.loads(b),revision=r) for i,b,r in db.execute('SELECT id,body,revision FROM questions')};cb=load(db)
 result=[]
 for cid,c in sorted(cb.items()):
  qs=members(bank,cid);states={q['status'] for q in qs};warnings=issues(qs)
  if len(states)>1:warnings.append('Mixed question statuses. Publish or return the whole case to Draft together.')
  result.append(dict(c,questions=qs,total_points=sum(q['maximum'] for q in qs),status=next(iter(states)) if len(states)==1 else 'Mixed' if states else 'Empty',warnings=warnings,can_publish=bool(qs) and not issues(qs),released=released(bank,cid),archived=sum(q.get('case_id')==cid and q['status']=='Archived' for q in bank.values())))
 return result

def publish(path,data,validate_question,backup,actor):
 import datetime
 target=data.get('status')
 if target not in ['Published','Draft']:raise ValueError('Choose Published or Draft.')
 def prepare(db):
  cb=load(db);cid=data.get('id')
  if cid not in cb or cb[cid]['revision']!=data.get('case_revision'):raise ValueError('Case changed. Refresh and review it again.')
  bank={i:dict(json.loads(b),revision=r) for i,b,r in db.execute('SELECT id,body,revision FROM questions')}
  qs=members(bank,cid)
  if not qs:raise ValueError('Link at least one active question first.')
  if data.get('revisions')!={q['id']:q['revision'] for q in qs}:raise ValueError('Case questions changed. Refresh and review the whole case again.')
  if target=='Published' and issues(qs):raise ValueError(' '.join(issues(qs)))
  updates=[(q,validate_question(dict(q,status=target))) for q in qs if q['status']!=target]
  proposed=dict(bank)
  for old,new in updates:proposed[new['id']]=new
  graph(proposed,cb)
  return updates
 with sqlite3.connect(path) as db:prepare(db)
 saved=backup()
 if not saved.get('verified'):raise ValueError('Backup verification failed. Nothing was changed.')
 with sqlite3.connect(path,timeout=15) as db:
  db.execute('BEGIN IMMEDIATE');updates=prepare(db)
  db.execute('CREATE TABLE IF NOT EXISTS question_edit_history(id INTEGER PRIMARY KEY,question_id TEXT NOT NULL,actor_id INTEGER NOT NULL,created TEXT NOT NULL,old_revision INTEGER NOT NULL,new_revision INTEGER NOT NULL,before_body TEXT NOT NULL,after_body TEXT NOT NULL)')
  stamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
  for old,new in updates:
   rev=old.pop('revision');body=json.dumps(new)
   db.execute('UPDATE questions SET body=?,revision=revision+1 WHERE id=?',(body,new['id']))
   db.execute('INSERT INTO question_edit_history(question_id,actor_id,created,old_revision,new_revision,before_body,after_body) VALUES (?,?,?,?,?,?,?)',(new['id'],actor,stamp,rev,rev+1,json.dumps(old),body))
 return {'updated':len(updates),'status':target,'backup':saved['archive']}


def save(path,data,validate_question,backup,actor):
 """Save the scenario and all category changes in one revision-checked transaction."""
 import datetime
 c=validate(data)
 def prepare(db):
  cb=load(db);old=cb.get(c['id'])
  if old and data.get('revision')!=old['revision']:raise ValueError('Scenario changed. Reload before saving.')
  if not old and data.get('revision') is not None:raise ValueError('Scenario no longer exists. Reload.')
  bank={i:dict(json.loads(b),revision=r) for i,b,r in db.execute('SELECT id,body,revision FROM questions')}
  linked=[q for q in bank.values() if q.get('case_id')==c['id']]
  if data.get('question_revisions',{})!={q['id']:q['revision'] for q in linked}:raise ValueError('Linked questions changed. Reload the scenario before saving.')
  updates=[(q,validate_question(dict(q,subject=c['subject'],topic=c['topic']))) for q in linked if (q['subject'],q['topic'])!=(c['subject'],c['topic'])]
  proposed=dict(bank)
  for before,after in updates:proposed[after['id']]=after
  cb[c['id']]=c;graph(proposed,cb)
  return old,updates
 with sqlite3.connect(path) as db:prepare(db)
 saved=backup()
 if not saved.get('verified'):raise ValueError('Backup verification failed. Nothing was saved.')
 with sqlite3.connect(path,timeout=10) as db:
  db.execute('BEGIN IMMEDIATE');old,updates=prepare(db);stamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
  revision=(old['revision'] if old else 0)+1
  db.execute('INSERT INTO cases(id,body,revision) VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body,revision=excluded.revision',(c['id'],json.dumps(c),revision))
  db.execute('INSERT INTO case_edit_history(case_id,actor_id,created,old_revision,new_revision,before_body,after_body) VALUES (?,?,?,?,?,?,?)',(c['id'],actor,stamp,revision-1,revision,json.dumps(old),json.dumps(c)))
  for before,after in updates:
   db.execute('UPDATE questions SET body=?,revision=revision+1 WHERE id=?',(json.dumps(after),after['id']))
   db.execute('INSERT INTO question_edit_history(question_id,actor_id,created,old_revision,new_revision,before_body,after_body) VALUES (?,?,?,?,?,?,?)',(after['id'],actor,stamp,before['revision'],before['revision']+1,json.dumps(before),json.dumps(after)))
  db.execute('INSERT OR IGNORE INTO organization VALUES (?,?)',(c['subject'],c['topic']))
 return {'saved':c['id'],'updated_questions':len(updates)}

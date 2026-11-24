"""Restricted content proposals with revision-checked administrator approval."""
import sqlite3,json,datetime

def initialize(db):
 db.execute('CREATE TABLE IF NOT EXISTS editor_proposals(id INTEGER PRIMARY KEY,kind TEXT,target_id TEXT,author_id INTEGER,base_revision INTEGER,before_body TEXT,after_body TEXT,status TEXT DEFAULT "Pending",created TEXT,reviewer_id INTEGER,reviewed TEXT,review_note TEXT)')
 db.execute('CREATE TABLE IF NOT EXISTS role_history(id INTEGER PRIMARY KEY,actor_id INTEGER,target_id INTEGER,before_role TEXT,after_role TEXT,created TEXT)')
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def role(path,actor,data):
 if actor['role']!='admin':raise ValueError('Administrator access required.')
 if data.get('role') not in ['learner','editor']:raise ValueError('Choose Learner or Editor.')
 with sqlite3.connect(path) as db:
  db.execute('BEGIN IMMEDIATE');initialize(db)
  old=db.execute('SELECT role FROM users WHERE id=?',(data.get('id'),)).fetchone()
  if not old or old[0] not in ['learner','editor']:raise ValueError('Administrator accounts cannot be changed here.')
  if old[0]!=data.get('previous_role'):raise ValueError('Account role changed. Refresh accounts.')
  db.execute('UPDATE users SET role=? WHERE id=?',(data['role'],data['id']))
  db.execute('INSERT INTO role_history(actor_id,target_id,before_role,after_role,created) VALUES (?,?,?,?,?)',(actor['id'],data['id'],old[0],data['role'],now()))
 return {'saved':True}
def target(db,kind,ident):
 if kind not in ['question','case']:raise ValueError('Invalid content type.')
 table='questions' if kind=='question' else 'cases'
 row=db.execute('SELECT body,revision FROM '+table+' WHERE id=?',(ident,)).fetchone()
 if not row:raise ValueError('Content no longer exists.')
 return json.loads(row[0]),row[1]
def read(path,actor,kind,ident):
 if actor['role'] not in ['editor','admin']:raise ValueError('Editor access required.')
 with sqlite3.connect(path) as db:
  body,revision=target(db,kind,ident)
 return {'body':body,'revision':revision}
def propose(path,actor,data):
 if actor['role'] not in ['editor','admin']:raise ValueError('Editor access required.')
 kind=data.get('kind');ident=data.get('id');fields=data.get('fields')
 allowed={'text','choices','explanation'} if kind=='question' else {'title','history','examination','laboratory'}
 if not isinstance(fields,dict) or not fields or set(fields)-allowed:raise ValueError('Only question text, existing choice wording and explanation, or shared scenario text can be edited.')
 with sqlite3.connect(path) as db:
  db.execute('BEGIN IMMEDIATE');initialize(db);old,rev=target(db,kind,ident)
  if rev!=data.get('revision'):raise ValueError('Content changed. Close and reopen the editor before submitting.')
  new=dict(old)
  for key,value in fields.items():
   if key=='choices':
    original=old.get('choices',[])
    if not isinstance(value,list) or len(value)!=len(original):raise ValueError('Choices cannot be added or removed.')
    for a,b in zip(original,value):
     if not isinstance(b,dict) or set(b)!= {'id','text'} or a['id']!=b['id'] or not isinstance(b['text'],str) or not b['text'].strip() or len(b['text'])>5000:raise ValueError('Keep existing choice IDs and enter valid choice text.')
   elif not isinstance(value,str) or len(value)>20000 or (key in ['text','title','history'] and not value.strip()):raise ValueError('Enter valid text (up to 20,000 characters).')
   new[key]=value
  if new==old:raise ValueError('No changes to submit.')
  if db.execute("SELECT 1 FROM editor_proposals WHERE kind=? AND target_id=? AND author_id=? AND status='Pending'",(kind,ident,actor['id'])).fetchone():raise ValueError('You already have a pending proposal for this item. Ask an admin to review it before submitting another.')
  pid=db.execute('INSERT INTO editor_proposals(kind,target_id,author_id,base_revision,before_body,after_body,created) VALUES (?,?,?,?,?,?,?)',(kind,ident,actor['id'],rev,json.dumps(old),json.dumps(new),now())).lastrowid
 return {'saved':pid}
def listing(path,actor):
 if actor['role']!='admin':raise ValueError('Administrator access required.')
 with sqlite3.connect(path) as db:
  initialize(db);db.row_factory=sqlite3.Row
  rows=db.execute('SELECT p.*,u.name AS author FROM editor_proposals p JOIN users u ON u.id=p.author_id ORDER BY p.id DESC').fetchall()
 return [dict(r,before_body=json.loads(r['before_body']),after_body=json.loads(r['after_body'])) for r in rows]
def review(path,actor,data,backup):
 if actor['role']!='admin':raise ValueError('Administrator access required.')
 decision=data.get('decision');note=data.get('note','')
 if decision not in ['Approved','Rejected'] or not isinstance(note,str) or len(note)>2000:raise ValueError('Invalid review.')
 def prepare(db):
  row=db.execute('SELECT kind,target_id,base_revision,before_body,after_body,status FROM editor_proposals WHERE id=?',(data.get('id'),)).fetchone()
  if not row or row[5]!='Pending':raise ValueError('Proposal already reviewed or missing.')
  if decision=='Approved':
   body,revision=target(db,row[0],row[1])
   if revision!=row[2] or body!=json.loads(row[3]):raise ValueError('Content changed since this proposal. Reject it and request a new proposal; nothing was overwritten.')
  return row
 with sqlite3.connect(path) as db:initialize(db);prepare(db)
 saved=backup()
 if not saved.get('verified'):raise ValueError('Backup verification failed. Nothing was changed.')
 with sqlite3.connect(path) as db:
  db.execute('BEGIN IMMEDIATE');kind,ident,rev,before,after,_=prepare(db);stamp=now()
  if decision=='Approved':
   table='questions' if kind=='question' else 'cases';hist='question_edit_history' if kind=='question' else 'case_edit_history';key='question_id' if kind=='question' else 'case_id'
   db.execute('UPDATE '+table+' SET body=?,revision=revision+1 WHERE id=?',(after,ident))
   db.execute('INSERT INTO '+hist+'('+key+',actor_id,created,old_revision,new_revision,before_body,after_body) VALUES (?,?,?,?,?,?,?)',(ident,actor['id'],stamp,rev,rev+1,before,after))
  db.execute('UPDATE editor_proposals SET status=?,reviewer_id=?,reviewed=?,review_note=? WHERE id=?',(decision,actor['id'],stamp,note,data['id']))
 return {'status':decision,'backup':saved['archive']}

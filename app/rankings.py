"""Fixed ranked exams and learner-only leaderboards."""
import sqlite3,json,uuid,datetime
from fractions import Fraction
import cases,attempts

def initialize(path):
 with sqlite3.connect(path) as db:
  db.execute('CREATE TABLE IF NOT EXISTS ranked_exams(id TEXT PRIMARY KEY,title TEXT NOT NULL,subject TEXT NOT NULL,topic TEXT NOT NULL,snapshot TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 0,created TEXT NOT NULL)')
  if 'ranked_exam_id' not in {r[1] for r in db.execute('PRAGMA table_info(attempts)')}:db.execute('ALTER TABLE attempts ADD COLUMN ranked_exam_id TEXT')

def catalog(path,admin=False):
 with sqlite3.connect(path) as db:rows=db.execute('SELECT id,title,subject,topic,snapshot,active,created FROM ranked_exams'+('' if admin else ' WHERE active=1')+' ORDER BY subject,topic,created').fetchall()
 return [dict(id=i,title=t,subject=s,topic=p,questions=len(json.loads(q)),maximum=sum(x['maximum'] for x in json.loads(q)),active=bool(a),created=c) for i,t,s,p,q,a,c in rows]

def manage(path,data,backup):
 action=data.get('action')
 if action not in ['create','activate','deactivate']:raise ValueError('Invalid action.')
 def prepare(db):
  if action!='create':
   row=db.execute('SELECT subject,topic FROM ranked_exams WHERE id=?',(data.get('id'),)).fetchone()
   if not row:raise ValueError('Ranked exam not found.')
   if action=='activate' and db.execute('SELECT 1 FROM ranked_exams WHERE active=1 AND subject=? AND topic=? AND id!=?',(*row,data['id'])).fetchone():raise ValueError('Deactivate the current ranked exam for this topic first.')
   return None
  title=data.get('title','').strip();ids=data.get('question_ids')
  if not title or len(title)>120:raise ValueError('Enter a title of up to 120 characters.')
  if not isinstance(ids,list) or not ids or len(ids)>1000 or any(not isinstance(i,str) for i in ids) or len(ids)!=len(set(ids)):raise ValueError('Select unique questions.')
  bank={i:dict(json.loads(b),revision=r) for i,b,r in db.execute('SELECT id,body,revision FROM questions')}
  if any(i not in bank or bank[i]['status']!='Published' for i in ids):raise ValueError('Choose published questions only.')
  qs=cases.snapshot(bank,ids,cases.load(db),False)
  if len({(q['subject'],q['topic']) for q in qs})!=1:raise ValueError('A ranked exam must contain one subject and topic only.')
  if sum(q['maximum'] for q in qs)<=0:raise ValueError('Maximum score must be positive.')
  return title,qs
 with sqlite3.connect(path) as db:prepare(db)
 saved=backup()
 if not saved.get('verified'):raise ValueError('Backup verification failed.')
 with sqlite3.connect(path) as db:
  db.execute('BEGIN IMMEDIATE');prepared=prepare(db)
  if action=='create':
   title,qs=prepared;ident=str(uuid.uuid4());db.execute('INSERT INTO ranked_exams VALUES (?,?,?,?,?,0,?)',(ident,title,qs[0]['subject'],qs[0]['topic'],json.dumps(qs),attempts.now()))
  else:
   ident=data['id'];db.execute('UPDATE ranked_exams SET active=? WHERE id=?',(int(action=='activate'),ident))
 return {'id':ident,'backup':saved['archive']}

def start(path,user_id,data):
 with sqlite3.connect(path) as db:
  db.execute('BEGIN IMMEDIATE')
  role=db.execute('SELECT role FROM users WHERE id=?',(user_id,)).fetchone()
  if not role or role[0]!='learner':raise ValueError('Only learner accounts can take ranked exams.')
  row=db.execute('SELECT snapshot FROM ranked_exams WHERE id=? AND active=1',(data.get('exam_id'),)).fetchone()
  if not row:raise ValueError('This ranked exam is no longer active.')
  ident=str(uuid.uuid4());db.execute('INSERT INTO attempts(id,user_id,mode,started,snapshot,ranked_exam_id) VALUES (?,?,?,?,?,?)',(ident,user_id,'exam',attempts.now(),row[0],data['exam_id']))
 return {'id':ident}

def board(path,user,scope,subject='',topic=''):
 if scope not in ['overall','subject','topic']:raise ValueError('Invalid ranking scope.')
 exams=catalog(path);chosen=[e for e in exams if (scope=='overall' or e['subject']==subject) and (scope!='topic' or e['topic']==topic)]
 ids={e['id'] for e in chosen};admin=user['role']=='admin'
 with sqlite3.connect(path) as db:
  learners=db.execute("SELECT id,name FROM users WHERE role='learner' AND disabled=0").fetchall()
  rows=db.execute("SELECT a.user_id,a.ranked_exam_id,a.id,a.submitted,a.result FROM attempts a JOIN users u ON u.id=a.user_id WHERE u.role='learner' AND a.mode='exam' AND a.submitted IS NOT NULL AND a.result IS NOT NULL AND a.ranked_exam_id IS NOT NULL").fetchall()
 scores={};counts={};hist={}
 for uid,eid,aid,stamp,result in rows:
  if eid not in ids:continue
  r=json.loads(result);score=Fraction(str(r['total']))/Fraction(str(r['maximum']))*100;key=(uid,eid)
  scores[key]=max(scores.get(key,score),score);counts[key]=counts.get(key,0)+1
  if admin:hist.setdefault(uid,[]).append({'attempt_id':aid,'exam_id':eid,'submitted':stamp,'score':round(float(score),2)})
 eligible=[];ineligible=[]
 for uid,name in learners:
  done=sum((uid,eid) in scores for eid in ids)
  if not ids or done<len(ids):
   if admin or uid==user['id']:ineligible.append({'name':name,'completed_exams':done,'required_exams':len(ids),'is_you':uid==user['id']})
   continue
  by_subject={}
  for e in chosen:by_subject.setdefault(e['subject'],[]).append(scores[(uid,e['id'])])
  score=sum(sum(v)/len(v) for v in by_subject.values())/len(by_subject)
  count=sum(counts[(uid,eid)] for eid in ids);eligible.append((score,count,uid,name))
 eligible.sort(key=lambda x:(-x[0],x[1],x[3].lower(),x[2]));result=[];last=None;rank=0
 for pos,(score,count,uid,name) in enumerate(eligible,1):
  if last!=(score,count):rank=pos;last=(score,count)
  row={'rank':rank,'name':name,'score':round(float(score),2),'is_you':uid==user['id']}
  if admin:row.update(attempts=count,history=hist.get(uid,[]))
  result.append(row)
 return {'rows':result,'ineligible':ineligible,'required_exams':len(ids),'exams':chosen}

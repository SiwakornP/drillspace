"""One-time, transactional migration. Run while the app server is stopped."""
import sqlite3,json,sys,datetime
from pathlib import Path
import identity

def migrate(path):
 with sqlite3.connect(path) as db:
  db.execute('BEGIN IMMEDIATE')
  if db.execute("SELECT 1 FROM metadata WHERE key='permanent_ids_v2'").fetchone():raise RuntimeError('Already migrated')
  rows=db.execute('SELECT id,body,revision FROM questions ORDER BY id').fetchall();reserved=set();mapping={}
  for old,body,rev in rows:
   new=identity.new_id(reserved);reserved.add(new);mapping[old]=new
  db.execute('CREATE TABLE question_id_mapping(old_id TEXT PRIMARY KEY,new_id TEXT UNIQUE NOT NULL,migrated_at TEXT NOT NULL)')
  stamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
  for old,body,rev in rows:
   q=json.loads(body);q.update(id=mapping[old],display_code=old)
   db.execute('UPDATE questions SET id=?,body=? WHERE id=?',(q['id'],json.dumps(q),old))
   db.execute('INSERT INTO question_id_mapping VALUES (?,?,?)',(old,q['id'],stamp))
  for old,new in mapping.items():
   db.execute('UPDATE feedback SET question_id=? WHERE question_id=?',(new,old))
   db.execute('UPDATE question_edit_history SET question_id=? WHERE question_id=?',(new,old))
  for ident,before,after in db.execute('SELECT id,before_body,after_body FROM question_edit_history').fetchall():
   def body(raw):
    q=json.loads(raw)
    if isinstance(q,dict) and q.get('id') in mapping:
     old=q['id'];q.update(id=mapping[old],display_code=old)
    return json.dumps(q)
   db.execute('UPDATE question_edit_history SET before_body=?,after_body=? WHERE id=?',(body(before),body(after),ident))
  for user,key,value in db.execute('SELECT user_id,key,value FROM study_data').fetchall():
   newkey=key;data=json.loads(value)
   if key.startswith('note:') and key[5:] in mapping:newkey='note:'+mapping[key[5:]]
   if key=='collections':
    for collection in data:collection['questions']=[mapping.get(i,i) for i in collection.get('questions',[])]
   db.execute('UPDATE study_data SET key=?,value=?,revision=revision+1 WHERE user_id=? AND key=?',(newkey,json.dumps(data),user,key))
  removed=db.execute('SELECT count(*) FROM attempts').fetchone()[0]
  for table in ['attempts','excel_exports','excel_previews','sessions']:db.execute('DELETE FROM '+table)
  db.execute("INSERT INTO metadata VALUES ('permanent_ids_v2',?)",(stamp,))
  identity.unique({i:json.loads(b) for i,b in db.execute('SELECT id,body FROM questions')});identity.install_constraints(db)
  assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
 return {'questions':len(rows),'attempts_removed':removed,'mapping':mapping}
if __name__=='__main__':
 result=migrate(sys.argv[1]);print(json.dumps({k:v for k,v in result.items() if k!='mapping'}))

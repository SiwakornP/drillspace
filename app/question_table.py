"""Atomic metadata edits using the question editor's validator and revisions."""
import cases
import sqlite3,json,datetime

def update(path,data,validate,backup,actor):
    changes=data.get('changes')
    if not isinstance(changes,list) or not 1<=len(changes)<=1000:raise ValueError('Select 1–1000 questions.')
    ids=[c.get('id') for c in changes if isinstance(c,dict)]
    if len(ids)!=len(changes) or any(not isinstance(i,str) for i in ids) or len(set(ids))!=len(ids):raise ValueError('Question IDs must be unique.')
    def prepare(db):
        result=[]
        for c in changes:
            fields=c.get('fields')
            if not isinstance(fields,dict) or not fields or set(fields)-{'subject','topic','status','case_order','discussion_enabled'}:raise ValueError('Edits support subject, topic, status, public discussion and order within case only.')
            if 'discussion_enabled' in fields and type(fields['discussion_enabled']) is not bool:raise ValueError('Discussion setting must be true or false.')
            row=db.execute('SELECT body,revision FROM questions WHERE id=?',(c['id'],)).fetchone()
            if not row or row[1]!=c.get('revision'):raise ValueError('A selected question changed. Refresh the table and review your changes again. Nothing was saved.')
            old=json.loads(row[0])
            if 'case_order' in fields:
                if set(fields)!={'case_order'} or not old.get('case_id') or old.get('status')=='Archived':raise ValueError('Reordering requires an active linked question.')
                if type(fields['case_order']) is not int or not 1<=fields['case_order']<=26:raise ValueError('Order must be an integer from 1 to 26.')
            new=validate(dict(old,**fields))
            if new!=old:result.append((c['id'],row[0],row[1],json.dumps(new),new))
        proposed={i:json.loads(b) for i,b in db.execute('SELECT id,body FROM questions')}
        for ident,_,_,_,q in result:proposed[ident]=q
        cases.graph(proposed,cases.load(db))
        return result
    with sqlite3.connect(path,timeout=10) as db:prepare(db)
    saved=backup()
    if not saved.get('verified'):raise ValueError('Backup verification failed. Nothing was changed.')
    with sqlite3.connect(path,timeout=10) as db:
        db.execute('BEGIN IMMEDIATE');rows=prepare(db)
        db.execute('CREATE TABLE IF NOT EXISTS question_edit_history(id INTEGER PRIMARY KEY,question_id TEXT NOT NULL,actor_id INTEGER NOT NULL,created TEXT NOT NULL,old_revision INTEGER NOT NULL,new_revision INTEGER NOT NULL,before_body TEXT NOT NULL,after_body TEXT NOT NULL)')
        stamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
        for ident,before,rev,after,q in rows:
            db.execute('INSERT INTO question_edit_history(question_id,actor_id,created,old_revision,new_revision,before_body,after_body) VALUES (?,?,?,?,?,?,?)',(ident,actor,stamp,rev,rev+1,before,after))
            db.execute('UPDATE questions SET body=?,revision=revision+1 WHERE id=?',(after,ident))
            db.execute('INSERT OR IGNORE INTO organization VALUES (?,?)',(q['subject'],q['topic']))
    return {'updated':len(rows),'backup':saved['archive']}

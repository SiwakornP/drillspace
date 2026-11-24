"""Immutable attempt snapshots, authoritative scoring and learner analytics."""
import cases
import datetime,json,math,re,sqlite3
from decimal import Decimal,ROUND_HALF_UP
from collections import defaultdict,Counter

def initialize(path):
    with sqlite3.connect(path) as db:
        db.execute('''CREATE TABLE IF NOT EXISTS attempts(
          id TEXT PRIMARY KEY,user_id INTEGER NOT NULL,mode TEXT NOT NULL,
          started TEXT NOT NULL,submitted TEXT,snapshot TEXT NOT NULL,result TEXT)''')
        columns={row[1] for row in db.execute('PRAGMA table_info(attempts)')}
        for name,definition in [('discarded_at','TEXT'),('discard_token','TEXT'),('last_activity','TEXT'),('draft','TEXT'),('draft_revision','INTEGER NOT NULL DEFAULT 0')]:
            if name not in columns:db.execute(f'ALTER TABLE attempts ADD COLUMN {name} {definition}')
        db.execute('CREATE INDEX IF NOT EXISTS attempts_user ON attempts(user_id,started)')

def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def start(path,user_id,data):
    ident=data.get('id');mode=data.get('mode');ids=data.get('question_ids')
    if not isinstance(ident,str) or not re.fullmatch(r'[a-zA-Z0-9-]{20,64}',ident):raise ValueError('Invalid attempt ID.')
    if mode not in ['exam','reviewer','case_scenarios']:raise ValueError('Choose Exam, Reviewer or Case scenarios mode.')
    if not isinstance(ids,list) or not 1<=len(ids)<=1000 or any(not isinstance(i,str) for i in ids) or len(set(ids))!=len(ids):raise ValueError('Choose a valid question set.')
    with sqlite3.connect(path,timeout=10) as db:
        db.execute('BEGIN IMMEDIATE')
        existing=db.execute('SELECT user_id,mode,snapshot FROM attempts WHERE id=?',(ident,)).fetchone()
        if existing:
            if existing[0]!=user_id or existing[1]!=mode or not set(ids)<=set(q['id'] for q in json.loads(existing[2])):raise ValueError('Attempt ID is already in use.')
            return detail(path,user_id,ident)
        bank={i:dict(json.loads(b),revision=r) for i,b,r in db.execute('SELECT id,body,revision FROM questions')}
        if any(i not in bank for i in ids):raise ValueError('The question set changed. Reload before starting.')
        role=db.execute('SELECT role FROM users WHERE id=?',(user_id,)).fetchone()
        if not role or (role[0] not in ['admin','editor'] and any(bank[i].get('status')!='Published' for i in ids)):raise ValueError('Only published questions can be started. Choose a new question set.')
        if mode=='case_scenarios' and any(not bank[i].get('case_id') for i in ids):raise ValueError('Case scenarios includes linked cases only.')
        snapshot=cases.snapshot(bank,ids,cases.load(db),role[0] in ['admin','editor'])
        if mode=='case_scenarios':
            for q in snapshot:q.update(staged_case=True,scenario_mode=True)
        db.execute('INSERT INTO attempts(id,user_id,mode,started,snapshot) VALUES (?,?,?,?,?)',(ident,user_id,mode,now(),json.dumps(snapshot)))
    return detail(path,user_id,ident)

def score(q,answer):
    if q['type']=='range':
        if not isinstance(answer,str):raise ValueError('Numerical answers must be text.')
        answer=answer.strip();blank=not answer
        if not blank:
            try:n=float(answer)
            except ValueError:raise ValueError('Enter a valid numerical answer.')
            if not math.isfinite(n) or (not q['decimals'] and not n.is_integer()):raise ValueError('Enter a valid number with the permitted precision.')
            correct=q['lower']<=n<=q['upper'];raw=q['correct'] if correct else q['incorrect']
    else:
        ids={c['id'] for c in q['choices']}
        if not isinstance(answer,list) or any(not isinstance(a,str) or a not in ids for a in answer) or len(answer)!=len(set(answer)) or (q['type']=='single' and len(answer)>1):raise ValueError('Invalid answer choices.')
        blank=not answer;correct=not blank and set(answer)==set(q['accepted'])
        if q['method'] in ['per_choice','sum_choices']:
            raw=sum(q['choice_scores'][a] for a in answer)
            correct=not blank and (raw>=q['maximum'] if q['method']=='per_choice' else set(answer)==set(q['accepted']))
        else:raw=(q['correct'] if correct else q['incorrect']) if q['method']=='exact_match' else sum(q['correct'] if a in q['accepted'] else q['incorrect'] for a in answer)
    if blank:raw=q['blank'];correct=False
    else:raw=max(q['minimum'],min(q['maximum'],raw))
    return {'id':q['id'],'revision':q.get('revision',1),'answer':answer,'blank':blank,'correct':correct,'score':float(Decimal(str(raw)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)),'maximum':q['maximum']}

def submit(path,user_id,data):
    with sqlite3.connect(path,timeout=10) as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT snapshot,result,draft_revision,draft FROM attempts WHERE id=? AND user_id=? AND discarded_at IS NULL',(data.get('id'),user_id)).fetchone()
        if not row:raise ValueError('Attempt not found for your account.')
        if row[1]:return json.loads(row[1]) # Retrying a submitted request never duplicates or changes results.
        if 'revision' in data and data['revision']!=row[2]:raise ValueError('This attempt changed in another tab. Resume the latest saved version.')
        qs=json.loads(row[0]);answers=data.get('answers')
        if not isinstance(answers,list) or len(answers)!=len(qs):raise ValueError('Submit one response for each question, including blanks.')
        confirmed=check_stages(qs,answers,json.loads(row[3]) if row[3] else {})
        if any(q.get('scenario_mode') and q['id'] not in confirmed for q in qs):raise ValueError('Submit each case answer before finishing the session.')
        items=[score(q,a) for q,a in zip(qs,answers)]
        result={'id':data['id'],'items':items,'total':round(sum(i['score'] for i in items),2),'maximum':sum(i['maximum'] for i in items)}
        db.execute('UPDATE attempts SET submitted=?,result=? WHERE id=?',(now(),json.dumps(result),data['id']))
    return result

def discard(path,user_id,data):
    token=data.get('token')
    if not isinstance(token,str) or not re.fullmatch(r'[a-zA-Z0-9-]{32,80}',token):raise ValueError('Invalid undo token.')
    action=data.get('action')
    if action not in ['discard','undo','finalize']:raise ValueError('Invalid discard action.')
    with sqlite3.connect(path,timeout=10) as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT submitted,result,discarded_at,discard_token FROM attempts WHERE id=? AND user_id=?',(data.get('id'),user_id)).fetchone()
        if not row:
            if action=='finalize':return {'discarded':True}
            raise ValueError('Attempt not found for your account.')
        if row[0] or row[1]:raise ValueError('Completed attempts cannot be discarded.')
        if action=='discard':
            if row[2] and row[3]!=token:raise ValueError('This attempt was discarded in another window.')
            db.execute('UPDATE attempts SET discarded_at=?,discard_token=? WHERE id=?',(now(),token,data['id']))
        else:
            if not row[2] or row[3]!=token:raise ValueError('This discard can no longer be undone from this page.')
            if action=='undo':db.execute('UPDATE attempts SET discarded_at=NULL,discard_token=NULL WHERE id=?',(data['id'],))
            else:db.execute('DELETE FROM attempts WHERE id=?',(data['id'],))
    return {'discarded':action!='undo'}

def history(path,user_id):
    with sqlite3.connect(path) as db:
        rows=db.execute('SELECT id,mode,started,submitted,snapshot,result,draft,last_activity FROM attempts WHERE user_id=? AND discarded_at IS NULL ORDER BY COALESCE(last_activity,submitted,started) DESC LIMIT 200',(user_id,)).fetchall()
    result=[]
    for i,m,s,done,q,r,draft,activity in rows:
        qs=json.loads(q);d=json.loads(draft) if draft else {};answers=d.get('answers',[])
        answered=len(d.get('confirmed',[])) if m=='case_scenarios' else sum(bool(a.strip()) if isinstance(a,str) else bool(a) for a in answers)
        result.append({'id':i,'mode':m,'started':s,'submitted':done,'last_activity':activity or done or s,'questions':len(qs),'answered':answered,'subjects':sorted(set(x.get('subject','') for x in qs)),'topics':sorted(set(x.get('topic','') for x in qs)),'scenario_count':len(set(x['case_id'] for x in qs if x.get('case_id'))),'result':json.loads(r) if r else None})
    return result

def detail(path,user_id,ident):
    with sqlite3.connect(path) as db:row=db.execute('SELECT mode,started,submitted,snapshot,result,draft,draft_revision,ranked_exam_id FROM attempts WHERE id=? AND user_id=? AND discarded_at IS NULL',(ident,user_id)).fetchone()
    if not row:raise ValueError('Attempt not found for your account.')
    return {'id':ident,'mode':row[0],'started':row[1],'submitted':row[2],'questions':visible_snapshot(json.loads(row[3]),json.loads(row[5]) if row[5] else {},bool(row[2])),'result':json.loads(row[4]) if row[4] else None,'draft':json.loads(row[5]) if row[5] else None,'draft_revision':row[6],'ranked_exam_id':row[7]}

def dashboard(path,filters):
    mode=filters.get('mode','exam');basis=filters.get('basis','first');subject=filters.get('subject','');topic=filters.get('topic','')
    if mode not in ['exam','reviewer','case_scenarios'] or basis not in ['first','latest']:raise ValueError('Invalid dashboard filter.')
    for key in ['from','to']:
        if filters.get(key):datetime.date.fromisoformat(filters[key])
    if filters.get('from') and filters.get('to') and filters['from']>filters['to']:raise ValueError('Start date must be before end date.')
    def in_date(timestamp):
        date=datetime.datetime.fromisoformat(timestamp).astimezone(datetime.timezone(datetime.timedelta(hours=7))).date().isoformat()
        return (not filters.get('from') or date>=filters['from']) and (not filters.get('to') or date<=filters['to'])
    def matches(q):return (not subject or q.get('subject')==subject) and (not topic or q.get('topic')==topic)
    with sqlite3.connect(path) as db:
        learners=[dict(zip(['id','name','username','disabled'],r)) for r in db.execute("SELECT id,name,username,disabled FROM users WHERE role='learner' ORDER BY name,id")]
        raw=db.execute("SELECT a.user_id,a.started,a.submitted,a.snapshot,a.result FROM attempts a JOIN users u ON a.user_id=u.id WHERE u.role='learner' AND a.mode=? ORDER BY a.submitted,a.id",(mode,)).fetchall()
        current=[dict(json.loads(b),revision=r) for b,r in db.execute('SELECT body,revision FROM questions ORDER BY id')]
        feedback=dict(db.execute("SELECT question_id,count(*) FROM feedback WHERE kind='admin' GROUP BY question_id"))
    questions={(q['id'],q['revision']):q for q in current if matches(q)}
    candidates=defaultdict(list);started=completed=0
    for uid,began,done,snapshot,result in raw:
        qs=json.loads(snapshot)
        if any(matches(q) for q in qs) and in_date(began):started+=1;completed+=bool(done)
        if not done:continue
        for q,item in zip(qs,json.loads(result)['items']):
            if matches(q):
                k=(q['id'],q.get('revision',1));questions[k]=q
                candidates[(uid,*k)].append(dict(item,submitted=done))
    rows=[];all_selected=[];learner_values=defaultdict(list);topics=defaultdict(list);trends=defaultdict(list)
    for (qid,revision),q in sorted(questions.items()):
        cells={};items=[];wrong=Counter()
        for learner in learners:
            entries=candidates.get((learner['id'],qid,revision),[])
            if not entries:continue
            selected=entries[0 if basis=='first' else -1]
            if not in_date(selected['submitted']):continue
            cell={**selected,'percent':round(100*selected['score']/selected['maximum'],1),'attempt_count':len(entries)}
            cells[str(learner['id'])]=cell;items.append(cell);all_selected.append(cell);learner_values[learner['id']].append(cell);topics[(q.get('subject',''),q.get('topic',''))].append(cell)
            if not selected['correct'] and isinstance(selected['answer'],list):wrong.update(a for a in selected['answer'] if a not in q['accepted'])
            if len(entries)>1:trends[learner['id']].append(100*(entries[-1]['score']-entries[0]['score'])/selected['maximum'])
        rows.append({'id':qid,'display_code':q.get('display_code',qid),'revision':revision,'text':q['text'],'subject':q.get('subject'),'topic':q.get('topic'),'cells':cells,'n':len(items),'accuracy':round(100*sum(x['correct'] for x in items)/len(items),1) if items else None,'unanswered':sum(x['blank'] for x in items),'wrong_choices':[{'choice':a,'text':next((c['text'] for c in q['choices'] if c['id']==a),a),'count':n} for a,n in wrong.most_common(3)],'admin_feedback':feedback.get(qid,0)})
    def summary(items):
        maximum=sum(x['maximum'] for x in items)
        return {'n':len(items),'percent':round(100*sum(x['score'] for x in items)/maximum,1) if maximum else None,'unanswered':sum(x['blank'] for x in items)}
    for learner in learners:
        learner.update(summary(learner_values[learner['id']]))
        changes=trends[learner['id']];learner['improvement']=round(sum(changes)/len(changes),1) if changes else None;learner['repeated_questions']=len(changes)
    return {'mode':mode,'basis':basis,'learners':learners,'rows':rows,'topics':[{'subject':s,'topic':t,**summary(v)} for (s,t),v in sorted(topics.items())],'summary':{**summary(all_selected),'started':started,'completed':completed},'definitions':'Cells use the first/latest submitted response per learner and question revision across all time, then the submission-date filter (Bangkok). Accuracy is the exact correct-answer rate including blanks. Scores include partial credit and penalties. Started/completed sessions use the start-date filter. Improvement compares first versus latest on repeated question revisions represented in this view; different dates and practice exposure can affect it. Admin feedback counts cover all dates and versions. Administrator practice is excluded.'}


def save_progress(path,user_id,data):
    with sqlite3.connect(path,timeout=10) as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT snapshot,result,draft_revision,draft FROM attempts WHERE id=? AND user_id=? AND discarded_at IS NULL',(data.get('id'),user_id)).fetchone()
        if not row:raise ValueError('Attempt not found for your account.')
        if row[1]:raise ValueError('This attempt is already submitted. Open My attempts to view it.')
        if data.get('revision')!=row[2]:raise ValueError('This attempt changed in another tab. Open My attempts and resume the latest saved version.')
        qs=json.loads(row[0]);answers=data.get('answers');position=data.get('current')
        if not isinstance(answers,list) or len(answers)!=len(qs):raise ValueError('Invalid saved answers.')
        if type(position)!=int or not 0<=position<len(qs):raise ValueError('Invalid question position.')
        for q,a in zip(qs,answers):
            if q['type']=='range':
                if not isinstance(a,str) or len(a)>100:raise ValueError('Invalid numerical draft.')
            else:score(q,a)
        old=json.loads(row[3]) if row[3] else {}
        confirmed=check_stages(qs,answers,old,data.get('confirm_question'))
        if not stage_open(qs,position,confirmed):raise ValueError('Confirm the previous question before opening this stage.')
        reviewed=data.get('reviewed_cases',[])
        if not isinstance(reviewed,list) or any(not isinstance(cid,str) for cid in reviewed):raise ValueError('Invalid reviewed cases.')
        for cid in reviewed:
            members=[(q,a) for q,a in zip(qs,answers) if q.get('case_id')==cid]
            if not members or any(score(q,a)['blank'] for q,a in members):raise ValueError('Complete all case questions before reviewing.')
        if any(q.get('staged_case') and q.get('case_id') in reviewed and q['id'] not in confirmed for q in qs):raise ValueError('Confirm every stage before reviewing this case.')
        draft={'answers':answers,'current':position,'reviewed_cases':reviewed,'confirmed':confirmed}
        db.execute('UPDATE attempts SET draft=?,draft_revision=draft_revision+1,last_activity=? WHERE id=?',(json.dumps(draft),now(),data['id']))
        return {'revision':row[2]+1,'confirmed':confirmed,'findings':{q['id']:q.get('additional_findings','') for q in visible_snapshot(qs,draft)}}


def stage_open(qs,index,confirmed):
    q=qs[index]
    return not q.get('staged_case') or all(x['id'] in confirmed for x in qs[:index] if x.get('case_id')==q.get('case_id'))

def check_stages(qs,answers,old,confirm=None):
    confirmed=list(old.get('confirmed',[]))
    previous=old.get('answers',[])
    for i,(q,a) in enumerate(zip(qs,answers)):
        if not q.get('staged_case'):continue
        if q['id'] in confirmed and (i>=len(previous) or a!=previous[i]):raise ValueError('Confirmed answers cannot be changed.')
        if not stage_open(qs,i,confirmed) and a:raise ValueError('Confirm the previous question before answering this stage.')
    if confirm is not None:
        index=next((i for i,q in enumerate(qs) if q['id']==confirm and q.get('staged_case')),None)
        if index is None or not stage_open(qs,index,confirmed):raise ValueError('This stage is not available.')
        if score(qs[index],answers[index])['blank']:raise ValueError('Answer this question before confirming.')
        if confirm not in confirmed:confirmed.append(confirm)
    return confirmed


def visible_snapshot(qs,draft,submitted=False):
    confirmed=draft.get('confirmed',[])
    return [dict(q) if submitted or stage_open(qs,i,confirmed) else {k:v for k,v in q.items() if k!='additional_findings'} for i,q in enumerate(qs)]


def scenario_progress(path,user_id):
    result={}
    with sqlite3.connect(path) as db:
        rows=db.execute("SELECT id,started,submitted,snapshot,draft,result FROM attempts WHERE user_id=? AND discarded_at IS NULL AND mode='case_scenarios' ORDER BY started DESC,id DESC",(user_id,)).fetchall()
    for ident,started,submitted,snapshot,draft,scores in rows:
        qs=json.loads(snapshot);draft=json.loads(draft) if draft else {};confirmed=set(draft.get('confirmed',[]))
        grouped={}
        for q in qs:grouped.setdefault(q.get('case_id'),[]).append(q)
        for cid,members in grouped.items():
            if not cid or cid in result:continue
            done=len(members) if submitted else sum(q['id'] in confirmed for q in members)
            result[cid]={'status':'Completed' if submitted else 'In progress','confirmed':done,'questions':len(members),'attempt_id':ident,'resume':not bool(submitted),'started':started}
    return result

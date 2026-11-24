"""Local question-bank editor. Bind to loopback only; no public authentication."""
import identity
import cases
import attempts
import rankings
from datetime import datetime
from zoneinfo import ZoneInfo
import choice_scoring
import master_sync
import question_table
import category_manager
import editor_workflow
import feedback_workflow
from accounts import AccountMixin, initialize as initialize_accounts
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlsplit, parse_qs, unquote
import posixpath
import base64, csv, io, json, math, os, re, sqlite3, subprocess, tempfile, uuid

ROOT = Path(__file__).resolve().parent
DIST = ROOT / 'dist'
DB = Path(os.environ.get('QUIZ_DB', str(ROOT / 'data' / 'questions.sqlite3')))
import sys
NODE = Path(sys.executable)
PORT = int(os.environ.get('PORT', '8766'))
HEADERS = ['questionID','Subject','Topic','question_text','question_image','question_type',*[f'option_{c}' for c in 'ABCDEF'],'Accepted answer','Answer notes','Correct score','Incorrect score','Unanswered','Max score','Scoring method','Minimum score','numeric_min','numeric_max','allow_decimals','Status','Explanation']

def connection():
    return sqlite3.connect(DB, timeout=10)

def initialize():
    DB.parent.mkdir(parents=True, exist_ok=True)
    cases.initialize(DB)
    with connection() as db:
        db.execute('CREATE TABLE IF NOT EXISTS questions (id TEXT PRIMARY KEY, body TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1)')
        db.execute('CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        if not db.execute("SELECT 1 FROM metadata WHERE key='seeded'").fetchone():
            seed=json.loads((DIST/'questions.js').read_text().split('=',1)[1].strip().rstrip(';'))
            # Preserve reference notes from the workbook where available.
            import openpyxl
            sheet=openpyxl.load_workbook(ROOT.parent/'Master_excel.xlsx', data_only=True).worksheets[0]
            headers=[c.value for c in sheet[1]]
            notes={r[0]:r[headers.index('Answer notes')] for r in sheet.iter_rows(min_row=2,max_row=21,values_only=True) if r[0]}
            for q in seed:
                q.update(status='Draft', explanation='', notes=str(notes.get(q['id']) or ''))
                db.execute('INSERT INTO questions(id,body) VALUES (?,?)',(q['id'],json.dumps(q)))
            db.execute("INSERT INTO metadata VALUES ('seeded','yes')")

def initialize_feedback():
    with connection() as db:
        db.execute("CREATE TABLE IF NOT EXISTS feedback (id INTEGER PRIMARY KEY, question_id TEXT NOT NULL, kind TEXT NOT NULL, body TEXT NOT NULL, created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        if 'user_id' not in [r[1] for r in db.execute('PRAGMA table_info(feedback)')]:db.execute('ALTER TABLE feedback ADD COLUMN user_id INTEGER')

    feedback_workflow.initialize(DB)

def feedback_items(question_id=None, public=False):
    return feedback_workflow.items(DB,question_id,public)

def organization():
    with connection() as db:
        return [{'subject':s,'topic':t} for s,t in db.execute('SELECT subject,topic FROM organization ORDER BY subject,topic')]

def organize_name(value):
    if not isinstance(value,str) or not value.strip() or len(value.strip())>100:
        raise ValueError('Enter a subject or topic of 1–100 characters.')
    return value.strip()

def migrate_organization():
    with connection() as db:
        db.execute('CREATE TABLE IF NOT EXISTS organization (subject TEXT NOT NULL COLLATE NOCASE, topic TEXT NOT NULL COLLATE NOCASE, PRIMARY KEY(subject,topic))')
        if not db.execute("SELECT 1 FROM metadata WHERE key='organization_v1'").fetchone():
            import openpyxl
            sh=openpyxl.load_workbook(ROOT.parent/'Master_excel.xlsx',data_only=True).worksheets[0]
            headers=[c.value for c in sh[1]]
            mapping={}
            for values in sh.iter_rows(min_row=2,values_only=True):
                row=dict(zip(headers,values))
                if row.get('questionID') and row.get('question_text'):
                    mapping[row['questionID']]=(row.get('Subject') or 'Unassigned',row.get('Topic') or 'Unassigned')
            for ident,body in db.execute('SELECT id,body FROM questions').fetchall():
                q=json.loads(body)
                q['subject'],q['topic']=mapping.get(ident,(q.get('subject','Unassigned'),q.get('topic','Unassigned')))
                db.execute('UPDATE questions SET body=?,revision=revision+1 WHERE id=?',(json.dumps(q),ident))
                db.execute('INSERT OR IGNORE INTO organization VALUES (?,?)',(q['subject'],q['topic']))
            db.execute("INSERT INTO metadata VALUES ('organization_v1','yes')")

def all_questions():
    with connection() as db:
        return [dict(json.loads(body),revision=rev) for body,rev in db.execute('SELECT body,revision FROM questions ORDER BY id')]

def validate_legacy(q):
    if not isinstance(q,dict): raise ValueError('Question must be an object.')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,50}',str(q.get('id',''))): raise ValueError('Use 1–50 letters, numbers, underscores or hyphens for the question ID.')
    for k in ['text','notes','explanation']:
        if not isinstance(q.get(k,''),str) or len(q.get(k,''))>20000: raise ValueError('Question text or explanation is too long.')
    q['subject']=organize_name(q.get('subject'))
    q['topic']=organize_name(q.get('topic'))
    if not q.get('text','').strip(): raise ValueError('Enter the question text.')
    if q.get('type') not in ['single','multi','range']: raise ValueError('Choose a valid question type.')
    if q.get('method') not in ['exact_match','partial_credit']: raise ValueError('Choose a scoring method.')
    if q.get('status') not in ['Draft','Reviewed','Published','Archived']: raise ValueError('Choose a valid status.')
    for k in ['correct','incorrect','blank','maximum','minimum']:
        if type(q.get(k)) not in (int,float) or not math.isfinite(q[k]): raise ValueError(f'Enter a number for {k}.')
    if q['correct']<=0 or q['maximum']<=0 or q['incorrect']>0 or q['minimum']>0: raise ValueError('Correct and maximum scores must be positive; incorrect and minimum scores must be zero or negative.')
    if not q['minimum']<=q['blank']<=q['maximum']: raise ValueError('Unanswered score must fall between minimum and maximum.')
    if q['type']!='multi' and q['method']!='exact_match': raise ValueError('Partial credit is only available for multiple-choice questions.')
    if q['method']=='exact_match' and q['correct']!=q['maximum']: raise ValueError('For exact match, Correct score must equal Max score.')
    if q['type']=='range':
        if any(type(q.get(k)) not in (int,float) or not math.isfinite(q[k]) for k in ['lower','upper']) or q['lower']>q['upper']: raise ValueError('Enter a valid minimum and maximum accepted answer.')
        if type(q.get('decimals')) is not bool: raise ValueError('Choose whether decimals are allowed.')
        if not q['decimals'] and math.ceil(q['lower'])>math.floor(q['upper']): raise ValueError('The accepted range must contain a whole number.')
        q['choices']=[];q['accepted']=[]
    else:
        choices=q.get('choices');accepted=q.get('accepted')
        if not isinstance(choices,list) or not 2<=len(choices)<=6: raise ValueError('Enter between two and six choices.')
        if any(not isinstance(c,dict) or c.get('id') not in 'ABCDEF' or len(c.get('id',''))!=1 or not isinstance(c.get('text'),str) or not c['text'].strip() or len(c['text'])>5000 for c in choices): raise ValueError('Each choice needs a letter A–F and text.')
        ids=[c['id'] for c in choices]
        if len(set(ids))!=len(ids): raise ValueError('Choice letters must be unique.')
        if not isinstance(accepted,list) or any(not isinstance(x,str) for x in accepted) or len(accepted)!=len(set(accepted)) or not set(accepted)<=set(ids): raise ValueError('Accepted answers must refer to populated choices.')
        if (q['type']=='single' and len(accepted)!=1) or (q['type']=='multi' and len(accepted)<2): raise ValueError('Mark one correct choice for single choice, or at least two for multiple choice.')
        if len(accepted)>=len(ids): raise ValueError('Include at least one incorrect choice.')
        if q['method']=='partial_credit' and not math.isclose(q['correct']*len(accepted),q['maximum'],abs_tol=1e-9): raise ValueError('Max score must equal Correct score × number of correct choices.')
        q['lower']=None;q['upper']=None;q['decimals']=False
    q['explanation_image']=q.get('explanation_image') or None
    q['explanation_caption']=q.get('explanation_caption') or ''
    if not isinstance(q['explanation_caption'],str) or len(q['explanation_caption'])>1000:raise ValueError('Use a caption of up to 1000 characters.')
    if q['explanation_image']:
        path=q['explanation_image']
        if not isinstance(path,str) or not re.fullmatch(r'question_image/[A-Za-z0-9_.-]+\.(png|jpg|jpeg)',path,re.I) or not (DIST/path).is_file():raise ValueError('Explanation picture is missing. Upload it again.')
    if q.get('image'):
        if not isinstance(q['image'],str) or not re.fullmatch(r'question_image/[A-Za-z0-9_.-]+\.(png|jpg|jpeg)',q['image'],re.I) or not (DIST/q['image']).is_file(): raise ValueError('The selected picture is missing. Upload it again.')
    if type(q.get('discussion_enabled',False)) is not bool: raise ValueError('Discussion setting must be true or false.')
    q['discussion_enabled']=q.get('discussion_enabled',False)
    return {k:q.get(k) for k in ['display_code','discussion_enabled','id','subject','topic','text','image','type','choices','accepted','correct','incorrect','blank','maximum','method','minimum','lower','upper','decimals','status','notes','explanation','explanation_image','explanation_caption']}

def validate(q):
    return identity.validate(cases.link(q,choice_scoring.validate(q,validate_legacy)))

def export_rows():
    rows=[]
    for q in all_questions():
        choices={c['id']:c['text'] for c in q['choices']}
        answer=f"{q['lower']:g}-{q['upper']:g}" if q['type']=='range' else ','.join(q['accepted'])
        rows.append([q['id'],q.get('subject'),q.get('topic'),q['text'],q.get('image'),q['type'],*[choices.get(c) for c in 'ABCDEF'],answer,q.get('notes'),q['correct'],q['incorrect'],q['blank'],q['maximum'],q['method'],q['minimum'],q.get('lower'),q.get('upper'),('Yes' if q['decimals'] else 'No') if q['type']=='range' else None,q['status'],q.get('explanation')])
    return rows

class Handler(AccountMixin, SimpleHTTPRequestHandler):
    account_db_path=DB
    account_port=PORT
    def end_headers(self):
        self.send_header("Cache-Control","no-store")
        super().end_headers()
    def __init__(self,*a,**kw): super().__init__(*a,directory=str(DIST),**kw)
    def send_data(self,code,data,kind='application/json',filename=None):
        if kind=='application/json': data=json.dumps(data).encode()
        self.send_response(code);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
        if filename:self.send_header('Content-Disposition',f'attachment; filename="{filename}"')
        self.end_headers();self.wfile.write(data)
    def allowed(self):
        return self.headers.get('Host') in [f'127.0.0.1:{PORT}',f'localhost:{PORT}']
    def visible_questions(self):
        questions=all_questions()
        bank={q['id']:q for q in questions}
        return questions if self.current_user()['role'] in ['admin','editor'] else [{k:v for k,v in q.items() if k!='additional_findings'} for q in questions if q.get('status')=='Published' and (not q.get('case_id') or cases.released(bank,q['case_id']))]
    def do_HEAD(self):
        if not self.allowed():return self.send_data(403,{"error":"Local access only."})
        if self.handle_account_get(urlsplit(self.path).path):return
        return super().do_HEAD()
    def do_GET(self):
        if not self.allowed():return self.send_data(403,{'error':'Local access only.'})
        parts=urlsplit(self.path);path=posixpath.normpath('/'+unquote(parts.path).lstrip('/'));self.path=path+('?' + parts.query if parts.query else '')
        if self.handle_account_get(path):return
        try:
            if path=='/api/editor/content':
                query=parse_qs(urlsplit(self.path).query)
                return self.send_data(200,editor_workflow.read(DB,self.current_user(),query.get('kind',['question'])[0],query.get('id',[''])[0]))
            if path=='/api/admin/editor-proposals':return self.send_data(200,editor_workflow.listing(DB,self.current_user()))
            if path=='/api/admin/case-overview':return self.send_data(200,cases.overview(DB))
            if path=='/api/admin/cases':
                with connection() as db:return self.send_data(200,list(cases.load(db).values()))
            if path=='/api/admin/excel-status':return self.send_data(200,master_sync.status(DB))
            if path=='/api/admin/master.xlsx':
                payload=master_sync.export_data(DB,validate)
                filename='Master_excel_'+datetime.now(ZoneInfo('Asia/Bangkok')).strftime('%y%m%d_%H%M')+'.xlsx'
                with tempfile.TemporaryDirectory() as tmp:
                    source=Path(tmp)/'payload.json';output=Path(tmp)/filename;source.write_text(json.dumps(payload))
                    subprocess.run([str(NODE),str(ROOT/'export_master.py'),str(source),str(output)],check=True,capture_output=True,timeout=120)
                    return self.send_data(200,output.read_bytes(),'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',filename)
            if path in ['/api/ranked-exams','/api/admin/ranked-exams']:return self.send_data(200,rankings.catalog(DB,path.startswith('/api/admin/')))
            if path=='/api/rankings':
                query=parse_qs(urlsplit(self.path).query)
                return self.send_data(200,rankings.board(DB,self.current_user(),query.get('scope',['overall'])[0],query.get('subject',[''])[0],query.get('topic',[''])[0]))
            if path=='/api/scenario-progress':return self.send_data(200,attempts.scenario_progress(DB,self.current_user()['id']))
            if path=='/api/attempts':return self.send_data(200,attempts.history(DB,self.current_user()['id']))
            if path=='/api/attempt':return self.send_data(200,attempts.detail(DB,self.current_user()['id'],parse_qs(urlsplit(self.path).query).get('id',[''])[0]))
            if path=='/api/admin/dashboard':return self.send_data(200,attempts.dashboard(DB,{k:v[0] for k,v in parse_qs(urlsplit(self.path).query).items()}))
            if path=='/api/my-feedback':return self.send_data(200,feedback_workflow.items(DB,parse_qs(urlsplit(self.path).query).get('question',[None])[0],owner=self.current_user()['id']))
            if path=='/api/feedback':
                ident=parse_qs(urlsplit(self.path).query).get('question',[''])[0]
                if not ident:return self.send_data(400,{'error':'Choose a question.'})
                q=next((q for q in all_questions() if q['id']==ident),None)
                return self.send_data(200,feedback_items(ident,True) if q and q.get('discussion_enabled') else [])
            if path=='/api/backup-status':
                status=ROOT/'backups/data/latest.json'
                return self.send_data(200,json.loads(status.read_text()) if status.exists() else {})
            if path=='/api/admin/feedback':return self.send_data(200,feedback_items())
            if path=='/api/organization':return self.send_data(200,organization() if self.current_user()['role']=='admin' else [dict(subject=s,topic=t) for s,t in sorted({(q['subject'],q['topic']) for q in self.visible_questions()})])
            if path=='/api/questions':return self.send_data(200,self.visible_questions())
            if path=='/questions.js':return self.send_data(200,('window.QUESTIONS = '+json.dumps(self.visible_questions())+';').encode(),'application/javascript')
            if path in ['/api/export.csv','/api/export.xlsx']:
                master=master_sync.export_data(DB,validate);headers=master['rows'][0];rows=master['rows'][1:]
                if path.endswith('.csv'):
                    stream=io.StringIO();writer=csv.writer(stream)
                    # Spreadsheet formula injection protection; text stays text when opened in Excel.
                    clean=lambda v: "'"+v if isinstance(v,str) and v.lstrip().startswith(('=','+','-','@','\t','\r')) else v
                    writer.writerow(headers);writer.writerows([[clean(v) for v in r] for r in rows])
                    return self.send_data(200,stream.getvalue().encode('utf-8-sig'),'text/csv; charset=utf-8','QuestionBank.csv')
                with tempfile.TemporaryDirectory() as tmp:
                    payload=Path(tmp)/'bank.json';output=Path(tmp)/'QuestionBank.xlsx'
                    payload.write_text(json.dumps(master))
                    subprocess.run([str(NODE),str(ROOT/'export_master.py'),str(payload),str(output)],check=True,capture_output=True,timeout=60)
                    return self.send_data(200,output.read_bytes(),'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','QuestionBank.xlsx')
            if path=='/admin':self.path='/admin.html'
            return super().do_GET()
        except ValueError as e:return self.send_data(400,{'error':str(e)})
        except Exception as e:
            print(type(e).__name__,str(e));self.send_data(500,{'error':'Could not load or export the question bank. Your saved questions are unchanged.'})
    def do_POST(self): self.write_question(False)
    def do_PUT(self): self.write_question(True)
    def write_question(self,updating):
        if self.handle_account_post(urlsplit(self.path).path):return
        if not self.allowed() or self.headers.get('X-Quiz-Admin')!='1' or self.headers.get('Content-Type')!='application/json':return self.send_data(403,{'error':'Use the local admin page to save.'})
        origin=self.headers.get('Origin')
        if origin and origin not in [f'http://127.0.0.1:{PORT}',f'http://localhost:{PORT}']:return self.send_data(403,{'error':'Request origin not allowed.'})
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=12000000:raise ValueError('Request is empty or too large. Use an image smaller than 8 MB.')
            data=json.loads(self.rfile.read(size));path=urlsplit(self.path).path
            if path in ['/api/ranked-exams/start','/api/admin/ranked-exams'] and not updating:
                user=self.current_user()
                if data.get('account_id')!=user['id']:return self.send_data(409,{'error':'Account changed. Reload.'})
                return self.send_data(200,rankings.start(DB,user['id'],data) if path.endswith('/start') else rankings.manage(DB,data,lambda:backup(ROOT)))
            if path=='/api/attempts/discard' and not updating:
                user=self.current_user()
                if data.get('account_id')!=user['id']:return self.send_data(409,{'error':'The signed-in account changed. Reload before continuing.'})
                return self.send_data(200,attempts.discard(DB,user['id'],data))
            if path in ['/api/attempts/start','/api/attempts/submit','/api/attempts/progress'] and not updating:
                user=self.current_user()
                if data.get('account_id')!=user['id']:return self.send_data(409,{'error':'The signed-in account changed. Reload before continuing.'})
                action=attempts.start if path.endswith('/start') else attempts.save_progress if path.endswith('/progress') else attempts.submit
                return self.send_data(200,action(DB,user['id'],data))
            if path in ['/api/admin/excel-preview','/api/admin/excel-commit'] and not updating:
                user=self.current_user()
                if data.get('account_id')!=user['id']:return self.send_data(409,{'error':'The signed-in account changed. Reload before continuing.'})
                if path.endswith('/excel-preview'):
                    try:blob=base64.b64decode(data.get('file',''),validate=True)
                    except Exception:raise ValueError('Invalid workbook upload.')
                    return self.send_data(200,master_sync.preview(DB,user['id'],blob,validate))
                from backup_bank import backup
                return self.send_data(200,master_sync.commit(DB,user['id'],data.get('preview_id'),validate,lambda:backup(ROOT)))
            if path in ['/api/editor/propose','/api/admin/editor-review','/api/admin/user-role']:
                user=self.current_user()
                if data.get('account_id')!=user['id']:raise ValueError('Signed-in account changed. Reload before saving.')
                if path=='/api/editor/propose':return self.send_data(200,editor_workflow.propose(DB,user,data))
                if path=='/api/admin/user-role':return self.send_data(200,editor_workflow.role(DB,user,data))
                from backup_bank import backup
                return self.send_data(200,editor_workflow.review(DB,user,data,lambda:backup(ROOT)))
            if path in ['/api/admin/categories-preview','/api/admin/categories-commit'] and not updating:
                user=self.current_user()
                if data.get('account_id')!=user['id']:raise ValueError('Signed-in account changed. Reload before saving.')
                if path.endswith('-preview'):return self.send_data(200,category_manager.preview(DB,data))
                from backup_bank import backup
                return self.send_data(200,category_manager.commit(DB,data,lambda:backup(ROOT),user['id']))
            if path=='/api/admin/questions-bulk' and not updating:
                from backup_bank import backup
                user=self.current_user()
                if data.get('account_id')!=user['id']:return self.send_data(409,{'error':'The signed-in account changed. Reload before saving.'})
                return self.send_data(200,question_table.update(DB,data,validate,lambda:backup(ROOT),user['id']))
            if path=='/api/admin/feedback-review' and not updating:
                return self.send_data(200,feedback_workflow.review(DB,self.current_user(),data))
            if path=='/api/backup' and not updating:
                from backup_bank import backup
                return self.send_data(200,backup(ROOT))
            if path=='/api/feedback' and not updating:
                ident=data.get('question_id');kind=data.get('kind');body=data.get('body')
                q=next((q for q in all_questions() if q['id']==ident),None)
                if not q:raise ValueError('Question not found.')
                if kind not in ['public','admin']:raise ValueError('Choose a feedback type.')
                if kind=='public' and not q.get('discussion_enabled'):raise ValueError('Public discussion is closed for this question.')
                if not isinstance(body,str) or not body.strip() or len(body)>5000:raise ValueError('Enter a comment of 1–5000 characters.')
                with connection() as db:db.execute('INSERT INTO feedback(question_id,kind,body,user_id,question_revision) VALUES (?,?,?,?,?)',(ident,kind,body.strip(),self.current_user()['id'],q['revision']))
                return self.send_data(201,{'saved':True})
            if path=='/api/images' and not updating:
                blob=base64.b64decode(data['data'],validate=True)
                if len(blob)>8*1024*1024:raise ValueError('Use an image smaller than 8 MB.')
                ext='png' if blob.startswith(b'\x89PNG\r\n\x1a\n') else 'jpg' if blob.startswith(b'\xff\xd8\xff') else None
                if not ext:raise ValueError('Choose a PNG or JPEG image.')
                name='question_image/'+uuid.uuid4().hex+'.'+ext;(DIST/name).write_bytes(blob)
                return self.send_data(201,{'image':name})
            if path=='/api/organization' and not updating:
                subject=organize_name(data.get('subject'))
                topic=organize_name(data.get('topic')) if data.get('topic') else ''
                with connection() as db:db.execute('INSERT OR IGNORE INTO organization VALUES (?,?)',(subject,topic))
                return self.send_data(200,organization())
            if path=='/api/admin/case-publication':
                from backup_bank import backup
                user=self.current_user()
                if data.get('account_id')!=user['id']:raise ValueError('Signed-in account changed. Reload before saving.')
                return self.send_data(200,cases.publish(DB,data,validate,lambda:backup(ROOT),user['id']))
            if path=='/api/admin/cases':
                from backup_bank import backup
                return self.send_data(200,cases.save(DB,data,validate,lambda:backup(ROOT),self.current_user()['id']))
            if path!='/api/questions':return self.send_data(404,{'error':'Not found.'})
            with connection() as db:
                db.execute('BEGIN IMMEDIATE')
                if not updating:data['id']=identity.new_id({r[0] for r in db.execute('SELECT id FROM questions')})
                if data.get('case_id'):
                    c=cases.load(db).get(data['case_id'])
                    if not c:raise ValueError('Choose an existing shared scenario.')
                    data.update(subject=c['subject'],topic=c['topic'])
                q=validate(data)
                proposed={i:json.loads(b) for i,b in db.execute('SELECT id,body FROM questions')}
                proposed[q['id']]=q;identity.unique(proposed);cases.graph(proposed,cases.load(db))
                if updating:
                    cur=db.execute('UPDATE questions SET body=?,revision=revision+1 WHERE id=? AND revision=?',(json.dumps(q),q['id'],data.get('revision')))
                    if cur.rowcount!=1:return self.send_data(409,{'error':'This question changed in another window. Reload the page before editing again.'})
                else:db.execute('INSERT INTO questions(id,body) VALUES (?,?)',(q['id'],json.dumps(q)))
                db.execute('INSERT OR IGNORE INTO organization VALUES (?,?)',(q['subject'],q['topic']))
            return self.send_data(200,{'saved':q['id']})
        except sqlite3.IntegrityError:return self.send_data(409,{'error':'That display code already exists, or its permanent ID is invalid. Reload and choose a unique display code.'})
        except (ValueError,KeyError,TypeError) as e:return self.send_data(400,{'error':str(e)})
        except Exception as e:
            print(type(e).__name__,str(e));return self.send_data(500,{'error':'Could not save. Your previous saved question is unchanged.'})

if __name__=='__main__':
    initialize();migrate_organization();initialize_feedback();initialize_accounts(DB);attempts.initialize(DB);rankings.initialize(DB);print(f'Quiz: http://127.0.0.1:{PORT}/\nAdmin: http://127.0.0.1:{PORT}/admin',flush=True)
    ThreadingHTTPServer(('127.0.0.1',PORT),Handler).serve_forever()

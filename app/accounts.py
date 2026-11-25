import profiles
"""Local account/session and per-user study-data endpoints."""
import hashlib,hmac,json,re,secrets,time,sqlite3,os
from http.cookies import SimpleCookie
from urllib.parse import urlsplit

def initialize(db):
    with sqlite3.connect(db) as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,username TEXT UNIQUE COLLATE NOCASE NOT NULL,name TEXT NOT NULL,password TEXT NOT NULL,role TEXT NOT NULL,created TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user_id INTEGER NOT NULL,expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS password_resets(token TEXT PRIMARY KEY,user_id INTEGER NOT NULL,expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS login_attempts(bucket TEXT,created REAL);
        CREATE TABLE IF NOT EXISTS study_data(user_id INTEGER NOT NULL,key TEXT NOT NULL,value TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1,PRIMARY KEY(user_id,key));
        ''')
        if 'disabled' not in [r[1] for r in c.execute('PRAGMA table_info(users)')]:c.execute('ALTER TABLE users ADD COLUMN disabled INTEGER NOT NULL DEFAULT 0')

def password_hash(password,salt=None):
    salt=salt or secrets.token_hex(16)
    digest=hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=131072,r=8,p=1,maxmem=256*1024*1024).hex()
    return salt+':'+digest

def check_password(password,stored):
    return hmac.compare_digest(password_hash(password,stored.split(':')[0]),stored)

def valid_password(p):
    if not isinstance(p,str) or not 12<=len(p)<=128:raise ValueError('Use a password of 12–128 characters.')

class AccountMixin:
    def account_db(self):return sqlite3.connect(self.account_db_path,timeout=10)
    def current_user(self):
        try:
            cookie=SimpleCookie();cookie.load(self.headers.get('Cookie',''));token=cookie['shee_session'].value
        except (KeyError,ValueError):return None
        with self.account_db() as c:
            row=c.execute('SELECT u.id,u.username,u.name,u.role FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=? AND s.expires>? AND u.disabled=0',(hashlib.sha256(token.encode()).hexdigest(),time.time())).fetchone()
        return dict(zip(['id','username','name','role'],row)) if row else None
    def reply_account(self,code,data,cookie=None):
        blob=json.dumps(data).encode();self.send_response(code);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(blob)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
        if cookie:self.send_header('Set-Cookie',cookie)
        self.end_headers();self.wfile.write(blob)
    def session_cookie(self,user_id):
        token=secrets.token_urlsafe(32)
        with self.account_db() as c:
            c.execute('DELETE FROM sessions WHERE expires<=?',(time.time(),))
            c.execute('INSERT INTO sessions VALUES (?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),user_id,time.time()+8*3600))
        return f'shee_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800'
    def handle_account_get(self,path):
        user=self.current_user()
        if path=='/api/account':
            with self.account_db() as c:setup=c.execute('SELECT count(*) FROM users').fetchone()[0]==0
            self.reply_account(200,{'user':user,'setup':setup});return True
        if path=='/api/profile':
            if not user:self.reply_account(401,{'error':'Please sign in.'});return True
            self.reply_account(200,profiles.read(self.account_db_path,user['id']));return True
        if path=='/api/study':
            if not user:self.reply_account(401,{'error':'Please sign in.'});return True
            with self.account_db() as c:rows=c.execute('SELECT key,value,revision FROM study_data WHERE user_id=?',(user['id'],)).fetchall()
            self.reply_account(200,{k:{'value':json.loads(v),'revision':r} for k,v,r in rows});return True
        if path=='/api/admin/users':
            if not user or user['role']!='admin':self.reply_account(403,{'error':'Administrator access required.'});return True
            with self.account_db() as c:rows=c.execute('SELECT id,username,name,role,created,disabled FROM users ORDER BY id').fetchall()
            self.reply_account(200,[dict(zip(['id','username','name','role','created','disabled'],r)) for r in rows]);return True
        if path.startswith('/api/editor/') and (not user or user['role'] not in ['editor','admin']):
            self.reply_account(403,{'error':'Editor access required.'});return True
        if path in ['/login.html','/login.js','/account.html','/account.js','/accounts-client.js','/style.css','/admin.css','/local-access.js']:return False
        if not user:
            if path.startswith('/api/') or path=='/questions.js':self.reply_account(401,{'error':'Please sign in.'})
            else:self.send_response(302);self.send_header('Location','/login.html');self.send_header('Cache-Control','no-store');self.end_headers()
            return True
        if (path.startswith('/api/admin/') or path.startswith('/api/export') or path=='/api/backup-status' or path in ['/admin','/admin.html','/admin.js','/backup-ui.js','/dashboard.html','/dashboard.js','/admin-home.html','/admin-home.js','/feedback-ui.js','/table.html','/table.js','/sync.html','/sync.js','/cases.html','/cases-ui.js','/categories.html','/categories.js','/users.html','/users-ui.js','/editor-review.html','/editor-review.js']) and user['role']!='admin':
            self.reply_account(403,{'error':'Administrator access required.'});return True
        return False
    def handle_account_post(self,path):
        # All browser mutations require same-origin JSON + custom header, before parsing.
        if not self.allowed() or self.headers.get('Content-Type')!='application/json' or self.headers.get('X-Quiz-Admin')!='1' or self.headers.get('Origin','') not in ['',f'http://127.0.0.1:{self.account_port}',f'http://localhost:{self.account_port}']:
            self.reply_account(403,{'error':'Request not allowed.'});return True
        user=self.current_user()
        if path not in ['/api/profile','/api/login','/api/register','/api/logout','/api/study','/api/import-browser','/api/password','/api/admin/user-status','/api/admin/password-reset','/api/password-reset']:
            if not user:self.reply_account(401,{'error':'Please sign in.'});return True
            if path=='/api/editor/propose' and user['role'] in ['editor','admin']:return False
            if path not in ['/api/feedback','/api/attempts/start','/api/attempts/submit','/api/attempts/progress','/api/attempts/discard','/api/ranked-exams/start'] and user['role']!='admin':self.reply_account(403,{'error':'Administrator access required.'});return True
            return False
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=1000000:raise ValueError('Request is too large or empty.')
            data=json.loads(self.rfile.read(size))
            if not isinstance(data,dict):raise ValueError('Invalid request.')
            if path in ['/api/login','/api/register']:
                bucket=self.client_address[0];now=time.time()
                with self.account_db() as c:
                    c.execute('DELETE FROM login_attempts WHERE created<?',(now-900,))
                    if c.execute('SELECT count(*) FROM login_attempts WHERE bucket=?',(bucket,)).fetchone()[0]>=10:
                        self.reply_account(429,{'error':'Too many attempts. Try again in 15 minutes.'});return True
                    c.execute('INSERT INTO login_attempts VALUES (?,?)',(bucket,now))
                username=data.get('username','');password=data.get('password','')
                if not isinstance(username,str) or not re.fullmatch(r'[a-zA-Z0-9_.-]{3,50}',username):raise ValueError('Use a username of 3–50 letters, numbers, dots, underscores or hyphens.')
                if not isinstance(password,str) or len(password)>128:raise ValueError('Invalid username or password.')
                username=username.lower()
                if path=='/api/register':
                    valid_password(password);name=data.get('name','')
                    if not isinstance(name,str) or not 1<=len(name.strip())<=100:raise ValueError('Enter a display name of 1–100 characters.')
                    hashed=password_hash(password)
                    with self.account_db() as c:
                        c.execute('BEGIN IMMEDIATE')
                        role='learner' if os.environ.get('RENDER')=='true' else ('admin' if c.execute('SELECT count(*) FROM users').fetchone()[0]==0 else 'learner')
                        try:uid=c.execute('INSERT INTO users(username,name,password,role) VALUES (?,?,?,?)',(username,name.strip(),hashed,role)).lastrowid
                        except sqlite3.IntegrityError:raise ValueError('This username is unavailable.')
                else:
                    with self.account_db() as c:row=c.execute('SELECT id,password FROM users WHERE username=? AND disabled=0',(username,)).fetchone()
                    # Keep the expensive derivation even when the username does not exist.
                    stored=row[1] if row else '00'*16+':'+'00'*64
                    valid=check_password(password,stored)
                    if not row or not valid:raise ValueError('Invalid username or password.')
                    uid=row[0]
                with self.account_db() as c:c.execute('DELETE FROM login_attempts WHERE bucket=?',(bucket,))
                self.reply_account(200,{'ok':True},self.session_cookie(uid));return True
            if path=='/api/password-reset':
                token=data.get('token','');new=data.get('password','');valid_password(new)
                if not isinstance(token,str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}',token):raise ValueError('Reset link is invalid or expired.')
                digest=hashlib.sha256(token.encode()).hexdigest()
                with self.account_db() as c:
                    c.execute('BEGIN IMMEDIATE')
                    row=c.execute('SELECT r.user_id FROM password_resets r JOIN users u ON u.id=r.user_id WHERE r.token=? AND r.expires>? AND u.disabled=0',(digest,time.time())).fetchone()
                    if not row:raise ValueError('Reset link is invalid or expired.')
                    c.execute('UPDATE users SET password=? WHERE id=?',(password_hash(new),row[0]))
                    c.execute('DELETE FROM password_resets WHERE user_id=?',(row[0],))
                    c.execute('DELETE FROM sessions WHERE user_id=?',(row[0],))
                self.reply_account(200,{'ok':True});return True
            if path=='/api/admin/password-reset':
                if not user or user['role']!='admin':self.reply_account(403,{'error':'Administrator access required.'});return True
                ident=data.get('id')
                if type(ident) is not int:raise ValueError('Choose an account.')
                token=secrets.token_urlsafe(32)
                with self.account_db() as c:
                    c.execute('BEGIN IMMEDIATE')
                    target=c.execute('SELECT role,disabled FROM users WHERE id=?',(ident,)).fetchone()
                    if not target or target[1] or target[0]=='admin':raise ValueError('Choose an active learner or editor account. Admin recovery requires server-owner assistance.')
                    c.execute('DELETE FROM password_resets WHERE user_id=? OR expires<=?',(ident,time.time()))
                    c.execute('INSERT INTO password_resets VALUES (?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),ident,time.time()+1800))
                self.reply_account(200,{'token':token,'expires_minutes':30});return True
            if not user:self.reply_account(401,{'error':'Please sign in.'});return True
            if path in ['/api/profile','/api/study','/api/import-browser','/api/password'] and data.get('account_id')!=user['id']:
                self.reply_account(409,{'error':'The signed-in account changed. Reload this page before continuing.'});return True
            if path=='/api/profile':
                self.reply_account(200,profiles.save(self.account_db_path,user['id'],data));return True
            if path=='/api/password':
                current=data.get('current','');new=data.get('password','');valid_password(new)
                if not isinstance(current,str) or len(current)>128:raise ValueError('Current password is incorrect.')
                with self.account_db() as c:stored=c.execute('SELECT password FROM users WHERE id=?',(user['id'],)).fetchone()[0]
                if not check_password(current,stored):raise ValueError('Current password is incorrect.')
                hashed=password_hash(new)
                with self.account_db() as c:
                    c.execute('UPDATE users SET password=? WHERE id=?',(hashed,user['id']))
                    c.execute('DELETE FROM sessions WHERE user_id=?',(user['id'],))
                self.reply_account(200,{'ok':True},self.session_cookie(user['id']));return True
            if path=='/api/admin/user-status':
                if user['role']!='admin':self.reply_account(403,{'error':'Administrator access required.'});return True
                ident=data.get('id');disabled=data.get('disabled')
                if type(ident) is not int or type(disabled) is not bool:raise ValueError('Invalid account selection.')
                with self.account_db() as c:
                    target=c.execute('SELECT role FROM users WHERE id=?',(ident,)).fetchone()
                    if not target or target[0]=='admin':raise ValueError('Administrator accounts cannot be disabled here.')
                    c.execute('UPDATE users SET disabled=? WHERE id=?',(int(disabled),ident))
                    if disabled:c.execute('DELETE FROM sessions WHERE user_id=?',(ident,))
                self.reply_account(200,{'ok':True});return True
            if path=='/api/logout':
                cookie=SimpleCookie();cookie.load(self.headers.get('Cookie',''));token=cookie.get('shee_session')
                if token:
                    with self.account_db() as c:c.execute('DELETE FROM sessions WHERE token=?',(hashlib.sha256(token.value.encode()).hexdigest(),))
                self.reply_account(200,{'ok':True},'shee_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0');return True
            if path=='/api/study':
                key=data.get('key','');value=data.get('value');revision=data.get('revision',0)
                self.validate_study(key,value)
                with self.account_db() as c:
                    c.execute('BEGIN IMMEDIATE');old=c.execute('SELECT revision FROM study_data WHERE user_id=? AND key=?',(user['id'],key)).fetchone()
                    if (old[0] if old else 0)!=revision:self.reply_account(409,{'error':'This data changed in another tab. Reload before saving again.'});return True
                    rev=revision+1;c.execute('INSERT INTO study_data VALUES (?,?,?,?) ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value,revision=excluded.revision',(user['id'],key,json.dumps(value),rev))
                self.reply_account(200,{'revision':rev});return True
            if path=='/api/import-browser':
                notes=data.get('notes',{});collections=data.get('collections',[])
                if not isinstance(notes,dict) or len(notes)>10000:raise ValueError('Invalid notes.')
                self.validate_study('collections',collections)
                for ident,text in notes.items():self.validate_study('note:'+ident,text)
                with self.account_db() as c:
                    c.execute('BEGIN IMMEDIATE');added=0
                    if c.execute("SELECT 1 FROM sqlite_master WHERE name='question_id_mapping'").fetchone():
                        mapping=dict(c.execute('SELECT old_id,new_id FROM question_id_mapping'))
                        notes={mapping.get(ident,ident):text for ident,text in notes.items()}
                        collections=[dict(item,questions=[mapping.get(ident,ident) for ident in item['questions']]) for item in collections]
                    for ident,text in notes.items():
                        added+=c.execute('INSERT OR IGNORE INTO study_data(user_id,key,value) VALUES (?,?,?)',(user['id'],'note:'+ident,json.dumps(text))).rowcount
                    row=c.execute("SELECT value,revision FROM study_data WHERE user_id=? AND key='collections'",(user['id'],)).fetchone()
                    merged=json.loads(row[0]) if row else [{'id':'favorite','name':'Favorite','questions':[]}]
                    for collection in collections:
                        match=next((x for x in merged if x['name'].casefold()==collection['name'].casefold()),None)
                        if match:match['questions']=list(dict.fromkeys(match['questions']+collection['questions']))
                        else:merged.append(dict(collection,id=secrets.token_hex(16)))
                    c.execute("INSERT INTO study_data VALUES (?,'collections',?,?) ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value,revision=excluded.revision",(user['id'],json.dumps(merged),(row[1] if row else 0)+1))
                self.reply_account(200,{'notes_added':added,'collections':len(merged)});return True
        except (ValueError,TypeError,KeyError) as e:self.reply_account(400,{'error':str(e)})
        return True
    def validate_study(self,key,value):
        if not isinstance(key,str):raise ValueError('Invalid study data.')
        if key.startswith('note:'):
            if not re.fullmatch(r'note:[A-Za-z0-9_-]{1,50}',key) or not isinstance(value,str) or len(value)>20000:raise ValueError('Invalid note or note exceeds 20,000 characters.')
        elif key=='collections':
            if not isinstance(value,list) or len(value)>200:raise ValueError('Use at most 200 collections.')
            ids=[];names=[]
            for x in value:
                if not isinstance(x,dict) or not isinstance(x.get('id'),str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',x['id']) or not isinstance(x.get('name'),str) or not 1<=len(x['name'].strip())<=80 or not isinstance(x.get('questions'),list) or len(x['questions'])>10000 or any(not isinstance(q,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,50}',q) for q in x['questions']):raise ValueError('Invalid collection.')
                ids.append(x['id']);names.append(x['name'].casefold())
            if len(ids)!=len(set(ids)) or len(names)!=len(set(names)):raise ValueError('Duplicate collection.')
        else:raise ValueError('Invalid study data key.')

"""Private, revision-checked account profiles. Education is learner-confirmed."""
import sqlite3,json,datetime,base64,io,re
from zoneinfo import ZoneInfo
FIELDS=['real_name','programme','entry_year','stage','institution','specialty','status','photo']
def today():return datetime.datetime.now(ZoneInfo('Asia/Bangkok')).date()
def initialize(path):
 with sqlite3.connect(path) as db:db.execute('CREATE TABLE IF NOT EXISTS profiles(user_id INTEGER PRIMARY KEY,body TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1)')
def read(path,uid):
 initialize(path)
 with sqlite3.connect(path) as db:
  name=db.execute('SELECT name FROM users WHERE id=?',(uid,)).fetchone()[0]
  row=db.execute('SELECT body,revision FROM profiles WHERE user_id=?',(uid,)).fetchone()
 p=json.loads(row[0]) if row else {};p.update(name=name,revision=row[1] if row else 0)
 confirmed=p.get('confirmed_on');due=datetime.date.fromisoformat(confirmed)+datetime.timedelta(days=365) if confirmed else None
 p['review_due']=bool(any(p.get(k) for k in ['programme','entry_year','stage']) and (not due or due<=today()));p['next_review']=due.isoformat() if due else None
 return p

def photo(value):
 if not value:return ''
 if not isinstance(value,str) or len(value)>500000:raise ValueError('Choose a smaller profile photo.')
 match=re.fullmatch(r'data:image/(png|jpeg);base64,([A-Za-z0-9+/=]+)',value)
 if not match:raise ValueError('Use a JPEG or PNG profile photo.')
 from PIL import Image,ImageOps
 try:
  raw=base64.b64decode(match[2],validate=True)
  with Image.open(io.BytesIO(raw)) as im:
   if im.format not in ['PNG','JPEG'] or im.width*im.height>16000000:raise ValueError('Photo is too large.')
   im=ImageOps.exif_transpose(im);im.thumbnail((256,256));im=im.convert('RGB');out=io.BytesIO();im.save(out,format='JPEG',quality=85)
  return 'data:image/jpeg;base64,'+base64.b64encode(out.getvalue()).decode()
 except Exception:raise ValueError('Could not read the photo. Choose a valid JPEG or PNG.')

def save(path,uid,data):
 initialize(path)
 if set(data)-set(FIELDS+['name','revision','account_id','confirm_stage']):raise ValueError('Unsupported profile field.')
 name=data.get('name','')
 if not isinstance(name,str) or not 1<=len(name.strip())<=100:raise ValueError('Enter a display name of 1–100 characters.')
 p={}
 for key in ['real_name','programme','stage','institution','specialty','status']:
  value=data.get(key,'')
  if not isinstance(value,str) or len(value)>150:raise ValueError('Profile fields must be text up to 150 characters.')
  p[key]=value.strip()
 if p['status'] not in ['','Studying','On leave','Completed']:raise ValueError('Choose a valid programme status.')
 year=data.get('entry_year')
 if year not in [None,''] and (type(year) is not int or not 1900<=year<=today().year+1):raise ValueError('Enter an entry year in CE, such as 2024.')
 p['entry_year']=year or None;p['photo']=photo(data.get('photo',''))
 if type(data.get('confirm_stage',False)) is not bool:raise ValueError('Invalid confirmation.')
 with sqlite3.connect(path,timeout=10) as db:
  db.execute('BEGIN IMMEDIATE');old=db.execute('SELECT body,revision FROM profiles WHERE user_id=?',(uid,)).fetchone()
  if data.get('revision')!=(old[1] if old else 0):raise ValueError('Your profile changed in another tab. Reload before saving.')
  previous=json.loads(old[0]) if old else {}
  if 'real_name' not in data:p['real_name']=previous.get('real_name','')
  p['confirmed_on']=today().isoformat() if data.get('confirm_stage') else previous.get('confirmed_on')
  revision=(old[1] if old else 0)+1
  db.execute('INSERT INTO profiles VALUES (?,?,?) ON CONFLICT(user_id) DO UPDATE SET body=excluded.body,revision=excluded.revision',(uid,json.dumps(p),revision))
  db.execute('UPDATE users SET name=? WHERE id=?',(name.strip(),uid))
 return read(path,uid)

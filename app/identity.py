"""Immutable record identities and editable, unique display codes."""
import datetime,re,json
from zoneinfo import ZoneInfo

def new_id(reserved):
 prefix=datetime.datetime.now(ZoneInfo('Asia/Bangkok')).strftime('Q%Y%m%d_%H%M%S_')
 n=1
 while prefix+f'{n:03d}' in reserved:n+=1
 return prefix+f'{n:03d}'

def validate(q):
 code=q.get('display_code')
 if not isinstance(code,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,50}',code):raise ValueError('Enter a display code with 1–50 letters, numbers, underscores or hyphens.')
 return q

def unique(bank):
 seen=set()
 for q in bank.values():
  validate(q);code=q['display_code'].casefold()
  if code in seen:raise ValueError('Display code already exists. Choose a unique code.')
  seen.add(code)

def install_constraints(db):
 db.execute("CREATE UNIQUE INDEX IF NOT EXISTS unique_display_code ON questions(lower(json_extract(body,'$.display_code')))")
 db.execute("CREATE TRIGGER IF NOT EXISTS immutable_question_id BEFORE UPDATE OF id ON questions WHEN NEW.id != OLD.id BEGIN SELECT RAISE(ABORT,'Permanent IDs cannot change'); END")
 db.execute("CREATE TRIGGER IF NOT EXISTS question_identity_insert BEFORE INSERT ON questions WHEN json_extract(NEW.body,'$.id') IS NOT NEW.id OR coalesce(json_extract(NEW.body,'$.display_code'),'')='' BEGIN SELECT RAISE(ABORT,'Question identity is missing or inconsistent'); END")
 db.execute("CREATE TRIGGER IF NOT EXISTS question_identity_update BEFORE UPDATE OF body ON questions WHEN json_extract(NEW.body,'$.id') IS NOT NEW.id OR coalesce(json_extract(NEW.body,'$.display_code'),'')='' BEGIN SELECT RAISE(ABORT,'Question identity is missing or inconsistent'); END")

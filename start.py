"""Refresh code on the persistent runtime without replacing any live data."""
from pathlib import Path
import os,shutil,sqlite3,sys
source=Path(__file__).parent/'app';target=Path(os.environ.get('DATA_DIR','/var/data'))/'runtime'
target.mkdir(parents=True,exist_ok=True)
for p in source.rglob('*'):
 if p.is_file() and '__pycache__' not in p.parts:
  dest=target/p.relative_to(source);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
db=target/'data/questions.sqlite3'
if not db.exists():raise SystemExit('Import a verified backup first with restore_seed.py. No empty public database will be created.')
with sqlite3.connect(db) as c:
 if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise SystemExit('Database integrity failure')
 if not c.execute("SELECT 1 FROM users WHERE role='admin' AND disabled=0").fetchone():raise SystemExit('An existing administrator is required')
os.chdir(target);sys.path.insert(0,str(target));os.environ['QUIZ_DB']=str(db)
import server
server.initialize();server.migrate_organization();server.initialize_feedback();server.initialize_accounts(db);server.attempts.initialize(db);server.rankings.initialize(db)
os.execvp('gunicorn',['gunicorn','--bind','0.0.0.0:'+os.environ.get('PORT','10000'),'--workers','1','--threads','2','--timeout','180','--access-logfile','-','wsgi:application'])

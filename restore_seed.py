"""One-time import: never overwrite an existing cloud database."""
import hashlib,json,os,sqlite3,sys,tempfile,zipfile
from pathlib import Path
root=Path(os.environ.get('DATA_DIR','/var/data'))/'runtime';db=root/'data/questions.sqlite3'
if db.exists():raise SystemExit('Database already exists; refusing to overwrite it.')
with zipfile.ZipFile(sys.argv[1]) as z:
 m=json.loads(z.read('manifest.json'))
 for name,digest in m['files'].items():
  if hashlib.sha256(z.read(name)).hexdigest()!=digest:raise SystemExit('Backup verification failed: '+name)
 names=['data/questions.sqlite3']+[n for n in m['files'] if n.startswith('dist/question_image/')]
 for name in names:
  dest=(root/name).resolve()
  if not dest.is_relative_to(root.resolve()):raise SystemExit('Invalid archive path')
  dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(z.read(name))
with sqlite3.connect(db) as c:
 assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
 c.execute('DELETE FROM sessions')
print('Imported verified database and images. Sign in again with an existing administrator account.')

"""Consistent database snapshot and verified, dated application backup."""
from pathlib import Path
import argparse,csv,datetime,hashlib,io,json,os,sqlite3,tempfile,zipfile,fcntl

ROOT=Path(__file__).resolve().parent

def backup(root=ROOT):
    root=Path(root);dest=root/'backups'/'data';dest.mkdir(parents=True,exist_ok=True)
    with (dest/'.backup.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('Another backup is already running. Try again shortly.')
        stamp=datetime.datetime.now().astimezone().strftime('%Y%m%d-%H%M%S-%f')
        target=dest/f'DrillSpace-{stamp}.zip'
        with tempfile.TemporaryDirectory(dir=dest) as tmp:
            tmp=Path(tmp);snapshot=tmp/'questions.sqlite3'
            with sqlite3.connect('file:'+str(root/'data/questions.sqlite3')+'?mode=ro',uri=True) as src,sqlite3.connect(snapshot) as copy:
                src.backup(copy)
                if copy.execute("SELECT 1 FROM sqlite_master WHERE name='sessions'").fetchone():copy.execute('DELETE FROM sessions');copy.commit()
                assert copy.execute('PRAGMA integrity_check').fetchone()[0]=='ok','Database integrity check failed.'
                questions=[json.loads(r[0]) for r in copy.execute('SELECT body FROM questions ORDER BY id')]
                feedback=copy.execute('SELECT count(*) FROM feedback').fetchone()[0] if copy.execute("SELECT 1 FROM sqlite_master WHERE name='feedback'").fetchone() else 0
            manifest={'sessions':'Active sessions omitted; sign in again after restoring.','created':datetime.datetime.now().astimezone().isoformat(),'questions':len(questions),'feedback':feedback,'files':{},'excludes':'Browser-only private notes and collections. Export these separately from each browser.'}
            staged=tmp/'backup.zip'
            with zipfile.ZipFile(staged,'w',zipfile.ZIP_DEFLATED) as z:
                def add(name,data):
                    z.writestr(name,data);manifest['files'][name]=hashlib.sha256(data).hexdigest()
                add('data/questions.sqlite3',snapshot.read_bytes())
                master=root.parent/'Master_excel.xlsx'
                if master.is_file():add('Master_excel.xlsx',master.read_bytes())
                add('questions.json',json.dumps(questions,ensure_ascii=False,indent=2).encode())
                for path in sorted(root.iterdir()):
                    if path.is_file() and path.suffix in ['.py','.mjs','.md','.command']:add(path.name,path.read_bytes())
                for path in sorted((root/'dist').rglob('*')):
                    if path.is_file() and not path.is_symlink():add(str(path.relative_to(root)),path.read_bytes())
                add('RESTORE.txt',b'Restore into a separate folder first. Extract this archive, then verify data/questions.sqlite3 with PRAGMA integrity_check. Stop the quiz server before replacing its database or app files. Keep a fresh backup of the current installation before replacement. questions.json is a readable export. Browser notes and collections require their separate browser export.\n')
                z.writestr('manifest.json',json.dumps(manifest,indent=2))
            with zipfile.ZipFile(staged) as z:
                assert z.testzip() is None,'Archive integrity check failed.'
                for name,digest in manifest['files'].items():assert hashlib.sha256(z.read(name)).hexdigest()==digest,name
            os.replace(staged,target)
            target.chmod(0o600)
            status={'created':manifest['created'],'questions':len(questions),'feedback':feedback,'archive':str(target),'bytes':target.stat().st_size,'verified':True}
            tempstatus=dest/'latest.tmp';tempstatus.write_text(json.dumps(status,indent=2));os.replace(tempstatus,dest/'latest.json')
            return status

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=ROOT);args=parser.parse_args()
    print(json.dumps(backup(args.root),indent=2))

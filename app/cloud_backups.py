"""Daily verified backups while the single application worker is running."""
import json,logging,threading,time
from pathlib import Path
from backup_bank import backup,ROOT
from datetime import datetime

def run():
 while True:
  try:
   latest=ROOT/'backups/data/latest.json'
   age=time.time()-datetime.fromisoformat(json.loads(latest.read_text())['created']).timestamp() if latest.exists() else 86401
   if age>=86400:logging.info('Verified backup: %s',backup(ROOT))
  except Exception:logging.exception('Daily backup failed; administrator action required')
  time.sleep(3600)
def start():threading.Thread(target=run,daemon=True,name='verified-backup').start()

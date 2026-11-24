"""Explicit Excel export, validated preview, and atomic revision-checked sync."""
import identity
import cases
import sqlite3,json,uuid,datetime,io,zipfile,hashlib,base64
from openpyxl import load_workbook
COLS=[('Question ID','id'),('Revision','revision'),('Action','action'),('Subject','subject'),('Topic','topic'),('Question text','text'),('Image path','image'),('Question type','type')]+[(f'Option {c}',c) for c in 'ABCDEF']+[(h,k) for h,k in [('Accepted answers','accepted'),('Correct score','correct'),('Incorrect score','incorrect'),('Unanswered score','blank'),('Maximum score','maximum'),('Minimum score','minimum'),('Scoring method','method'),('Numeric minimum','lower'),('Numeric maximum','upper'),('Allow decimals','decimals'),('Status','status'),('Explanation','explanation'),('Answer notes','notes'),('Public discussion','discussion_enabled')]]
LEGACY_COLS=COLS[:]
COLS=COLS[:8]+[(h,k) for c in 'ABCDEF' for h,k in [('Option '+c,c),('Score '+c,'score_'+c)]]+[(('Required choices (exact match only)' if k=='accepted' else 'Correct score (exact match / numeric)' if k=='correct' else 'Incorrect score (exact match / numeric)' if k=='incorrect' else h),k) for h,k in COLS[14:]]
SCORE_COLS=COLS[:]
COLS += [('Case ID','case_id'),('Case order','case_order')]
CASE_COLS=COLS[:]
COLS += [('Additional findings before this question','additional_findings')]
COLS[0]=('Permanent ID','id')
COLS += [('Display code','display_code')]
PRE_IMAGE_COLS=COLS[:]
COLS += [('Explanation image path','explanation_image'),('Explanation image caption','explanation_caption')]
HEADERS=[h for h,k in COLS]
NUMBERS={'correct','incorrect','blank','maximum','minimum','lower','upper'}
def now():return datetime.datetime.now(datetime.timezone.utc)
def initialize(path):
 cases.initialize(path)
 with sqlite3.connect(path) as db:
  db.execute('CREATE TABLE IF NOT EXISTS excel_exports(id TEXT PRIMARY KEY,created TEXT NOT NULL,snapshot TEXT NOT NULL)')
  db.execute('CREATE TABLE IF NOT EXISTS excel_previews(id TEXT PRIMARY KEY,user_id INTEGER NOT NULL,created TEXT NOT NULL,changes TEXT NOT NULL,result TEXT)')

def export_data(path,validate):
 initialize(path)
 with sqlite3.connect(path) as db:
  bank={i:dict(validate(json.loads(b)),revision=r) for i,b,r in db.execute('SELECT id,body,revision FROM questions ORDER BY id')}
  casebank=cases.load(db)
  ident=str(uuid.uuid4());stamp=now().isoformat();db.execute('INSERT INTO excel_exports VALUES (?,?,?)',(ident,stamp,json.dumps(dict(bank,__cases__=casebank))))
 rows=[HEADERS]
 for q in bank.values():
  values=dict(q,action='Update');values.update({c['id']:c['text'] for c in q['choices']});values['accepted']=','.join(q['accepted']) if q['method']=='exact_match' else None
  if q['method'] in ['per_choice','sum_choices']:
   values['correct']=None;values['incorrect']=None
   values.update({'score_'+c:score for c,score in q['choice_scores'].items()})
  for k in ['decimals','discussion_enabled']:values[k]='Yes' if q.get(k) else 'No'
  rows.append([values.get(k) for h,k in COLS])
 return {'rows':rows,'batch':ident,'created':stamp,'cases':[cases.HEADERS]+[[c['id'],c['revision'],c['title'],c['history'],c['examination'],c['laboratory'],c['subject'],c['topic']] for c in casebank.values()]}

def parse_file(blob):
 if len(blob)>8*1024*1024:raise ValueError('Use an .xlsx file under 8 MB.')
 try:
  with zipfile.ZipFile(io.BytesIO(blob)) as z:
   if sum(i.file_size for i in z.infolist())>40*1024*1024 or len(z.infolist())>1000:raise ValueError('Workbook is too large when unpacked.')
  book=load_workbook(io.BytesIO(blob),read_only=True,data_only=False,keep_links=False)
 except ValueError:raise
 except Exception:raise ValueError('Could not read this .xlsx workbook.')
 try:
  if 'Questions' not in book.sheetnames or 'SyncInfo' not in book.sheetnames:raise ValueError('Download the latest sync workbook first. Older exports do not contain sync revisions.')
  batch=book['SyncInfo']['B1'].value
  if not isinstance(batch,str):raise ValueError('Sync identity is missing. Download a fresh workbook.')
  sheet=book['Questions'];sheet.calculate_dimension(force=True)
  if sheet.max_row>10001 or sheet.max_column>len(HEADERS):raise ValueError('Maximum 10,000 question rows; keep the original columns.')
  headers=[c.value for c in next(sheet.iter_rows(min_row=1,max_row=1))]
  columns=COLS if headers==HEADERS else PRE_IMAGE_COLS if headers==[h for h,k in PRE_IMAGE_COLS] else CASE_COLS if headers==[h for h,k in CASE_COLS] else SCORE_COLS if headers==[h for h,k in SCORE_COLS] else LEGACY_COLS if headers==[h for h,k in LEGACY_COLS] else None
  if columns is None:raise ValueError('Column headings changed. Download the latest workbook and keep its headings.')
  rows=[]
  for number,cells in enumerate(sheet.iter_rows(min_row=2,max_col=len(columns)),2):
   if all(c.value is None for c in cells):continue
   if any(c.data_type in ['f','e'] for c in cells):raise ValueError(f'Row {number}: formulas and Excel errors are not allowed; paste values instead.')
   rows.append((number,{k:c.value for (h,k),c in zip(columns,cells)}))
  case_rows=[]
  if 'Cases' in book.sheetnames:
   cs=book['Cases'];cs.calculate_dimension(force=True)
   if cs.max_row>10001 or cs.max_column>8:raise ValueError('Keep the original Cases columns; maximum 10,000 cases.')
   case_headers=[c.value for c in next(cs.iter_rows(min_row=1,max_row=1))]
   if case_headers not in [cases.HEADERS,cases.LEGACY_HEADERS]:raise ValueError('Cases headings changed.')
   for number,cells in enumerate(cs.iter_rows(min_row=2,max_col=len(case_headers)),2):
    if all(c.value is None for c in cells):continue
    if any(c.data_type in ['f','e'] for c in cells):raise ValueError(f'Cases row {number}: paste values, not formulas or errors.')
    case_rows.append((number,{k:c.value for k,c in zip(['id','revision','title','history','examination','laboratory','subject','topic'],cells)}))
  return batch,rows,case_rows
 finally:book.close()

def preview(path,user_id,blob,validate):
 initialize(path);batch,rows,case_rows=parse_file(blob)
 with sqlite3.connect(path) as db:
  row=db.execute('SELECT snapshot FROM excel_exports WHERE id=?',(batch,)).fetchone()
  if not row:raise ValueError('This workbook belongs to a different bank or an unavailable export. Download the latest workbook.')
  baseline=json.loads(row[0]);casebase=baseline.pop('__cases__',{});casecurrent=cases.load(db);current={i:(json.loads(b),r) for i,b,r in db.execute('SELECT id,body,revision FROM questions')}
 changes=[];errors=[];seen=set();reserved=set(current);unchanged=0
 case_seen=set()
 for number,c in case_rows:
  try:
   ident=c.get('id')
   if ident in case_seen:raise ValueError('Duplicate Case ID.')
   case_seen.add(ident)
   for key in ['subject','topic']:
    if key not in c:c[key]=casebase.get(ident,casecurrent.get(ident,{})).get(key) or next((q[0].get(key,'') for q in current.values() if q[0].get('case_id')==ident),'')
   for key in cases.FIELDS:
    if c.get(key) is None:c[key]=''
   after=cases.validate(c)
   if ident in casebase:
    if c.get('revision')!=casebase[ident]['revision']:raise ValueError('Case revision changed or removed.')
    before={k:v for k,v in casebase[ident].items() if k!='revision'}
    for key in ['subject','topic']:before.setdefault(key,casecurrent.get(ident,{}).get(key,''))
    if before==after:continue
    if ident not in casecurrent or casecurrent[ident]['revision']!=casebase[ident]['revision']:raise ValueError('Case changed in the app; download a fresh workbook.')
    revision=c['revision']
   else:
    if ident in casecurrent or c.get('revision') is not None:raise ValueError('For a new case use a unique Case ID and blank Revision.')
    before=None;revision=None
   changes.append({'kind':'case','id':ident,'row':number,'action':'Add' if before is None else 'Update','revision':revision,'before':before,'after':after})
  except (ValueError,TypeError) as e:errors.append({'row':'Cases '+str(number),'id':c.get('id'),'message':str(e)})
 for number,v in rows:
  try:
   action=str(v.get('action') or 'Update').strip().lower()
   if action not in ['update','add','archive','delete']:raise ValueError('Action must be Update, Add, or Archive (Delete also archives).')
   ident=str(v.get('id') or '').strip()
   if ident:
    if ident in seen:raise ValueError('Duplicate Question ID.')
    seen.add(ident)
   if action=='add':
    if ident or v.get('revision') is not None:raise ValueError('For Add, leave Question ID and Revision blank. The system assigns a new ID.')
    ident=identity.new_id(reserved);reserved.add(ident)
   else:
    if ident not in baseline or ident not in current:raise ValueError('Unknown or changed Question ID. Use Add with a blank ID for a new question.')
    if v.get('revision')!=baseline[ident]['revision']:raise ValueError('Revision was changed or removed. Download the latest workbook.')
   q={k:v.get(k) for h,k in COLS if k not in ['revision','action',*'ABCDEF']}
   if 'additional_findings' not in v and ident in baseline:q['additional_findings']=baseline[ident].get('additional_findings')
   for key in ['explanation_image','explanation_caption']:
    if key not in v and ident in baseline:q[key]=baseline[ident].get(key)
   q['id']=ident
   if 'case_id' not in v and ident in baseline:
    q['case_id']=baseline[ident].get('case_id');q['case_order']=baseline[ident].get('case_order')
   for k in ['subject','topic','text','type','method','status','explanation','notes']:
    q[k]='' if q[k] is None else str(q[k])
   q['image']=q.get('image') or None
   for k in NUMBERS:
    val=q.get(k)
    if val is None or val=='':q[k]=None
    else:
     if isinstance(val,bool):raise ValueError(k+' must be a number.')
     try:q[k]=float(val)
     except (ValueError,TypeError):raise ValueError(k+' must be a number.')
   for k in ['decimals','discussion_enabled']:
    val=str(q.get(k) or 'No').strip().lower()
    if val not in ['yes','no']:raise ValueError(k+' must be Yes or No.')
    q[k]=val=='yes'
   q['choices']=[{'id':c,'text':str(v[c])} for c in 'ABCDEF' if v.get(c) is not None and str(v[c]).strip()]
   if q['method'] in ['per_choice','sum_choices']:
    q['choice_scores']={}
    for c in q['choices']:
     val=v.get('score_'+c['id'])
     if val is None or val=='':raise ValueError('Enter Score '+c['id']+'; blank is not zero.')
     try:q['choice_scores'][c['id']]=float(val)
     except (ValueError,TypeError):raise ValueError('Score '+c['id']+' must be numeric.')
   q['accepted']=[a.strip() for a in str(v.get('accepted') or '').split(',') if a.strip()]
   if action=='add':q['status']='Draft'
   if action in ['archive','delete']:
    # Archive never applies unrelated workbook edits.
    q={k:value for k,value in baseline[ident].items() if k!='revision'};q['status']='Archived'
   if q.get('case_id'):
    shared=next((c['after'] for c in changes if c.get('kind')=='case' and c['id']==q['case_id']),casecurrent.get(q['case_id']))
    if shared and action=='add':q.update(subject=shared['subject'],topic=shared['topic'])
   q=validate(q)
   old={k:value for k,value in baseline.get(ident,{}).items() if k!='revision'}
   if action!='add' and q==old:unchanged+=1;continue
   if action!='add' and current[ident][1]!=baseline[ident]['revision']:raise ValueError('Conflict: this question changed in the app. Download the latest workbook and reapply this edit.')
   changes.append({'id':ident,'row':number,'action':'Add' if action=='add' else 'Archive' if action in ['archive','delete'] else 'Update','revision':None if action=='add' else baseline[ident]['revision'],'before':current[ident][0] if action!='add' else None,'after':q})
  except (ValueError,TypeError,KeyError) as e:errors.append({'row':number,'id':v.get('id') or '(new)','message':str(e)})
 if not errors:
  try:
   for change in list(changes):
    if change.get('kind')!='case':continue
    c=change['after'];prior=casecurrent.get(c['id'],{})
    if (c['subject'],c['topic'])==(prior.get('subject'),prior.get('topic')):continue
    for qid,(q,revision) in current.items():
     if q.get('case_id')!=c['id']:continue
     if qid not in baseline or baseline[qid]['revision']!=revision:raise ValueError('A linked question changed. Download a fresh workbook before changing scenario categories.')
     member=next((x for x in changes if x.get('kind')!='case' and x['id']==qid),None)
     if member is None:
      member={'id':qid,'row':'Cases '+c['id'],'action':'Update','revision':revision,'before':q,'after':dict(q)};changes.append(member)
     if member['after'].get('case_id')==c['id']:member['after']=validate(dict(member['after'],subject=c['subject'],topic=c['topic']))
  except ValueError as e:errors.append({'row':'Cases','id':'','message':str(e)})
 if not errors:
  try:
   proposed={i:q for i,(q,r) in current.items()};proposed_cases=dict(casecurrent)
   for c in changes:(proposed_cases if c.get('kind')=='case' else proposed)[c['id']]=c['after']
   identity.unique(proposed);cases.graph(proposed,proposed_cases)
  except ValueError as e:errors.append({'row':'Links','id':'','message':str(e)})
 unchanged=max(0,unchanged-sum(str(c.get('row','')).startswith('Cases ') and c.get('kind')!='case' for c in changes))
 result={'errors':errors,'unchanged':unchanged,'changes':changes,'preview_id':None}
 if not errors and changes:
  ident=str(uuid.uuid4())
  with sqlite3.connect(path) as db:db.execute('INSERT INTO excel_previews VALUES (?,?,?,?,NULL)',(ident,user_id,now().isoformat(),json.dumps(changes)))
  result['preview_id']=ident
 return result

def commit(path,user_id,ident,validate,backup):
 def get(db):
  row=db.execute('SELECT created,changes,result FROM excel_previews WHERE id=? AND user_id=?',(ident,user_id)).fetchone()
  if not row:raise ValueError('Preview not found for your account.')
  if row[2]:return row,json.loads(row[2])
  if (now()-datetime.datetime.fromisoformat(row[0])).total_seconds()>3600:raise ValueError('Preview expired. Upload again.')
  for c in json.loads(row[1]):
   table='cases' if c.get('kind')=='case' else 'questions'
   current=db.execute('SELECT revision FROM '+table+' WHERE id=?',(c['id'],)).fetchone()
   if (c['revision'] is None and current) or (c['revision'] is not None and (not current or current[0]!=c['revision'])):raise ValueError('A question changed after preview. Upload again; nothing was saved.')
   (cases.validate if c.get('kind')=='case' else validate)(c['after'])
  proposed={i:json.loads(b) for i,b in db.execute('SELECT id,body FROM questions')};proposed_cases=cases.load(db)
  for c in json.loads(row[1]):(proposed_cases if c.get('kind')=='case' else proposed)[c['id']]=c['after']
  identity.unique(proposed);cases.graph(proposed,proposed_cases)
  return row,None
 with sqlite3.connect(path) as db:
  row,result=get(db)
  if result:return result
 saved=backup()
 if not saved.get('verified'):raise ValueError('Backup verification failed. Nothing was saved.')
 with sqlite3.connect(path,timeout=10) as db:
  db.execute('BEGIN IMMEDIATE');row,result=get(db)
  if result:return result
  db.execute('CREATE TABLE IF NOT EXISTS question_edit_history(id INTEGER PRIMARY KEY,question_id TEXT NOT NULL,actor_id INTEGER NOT NULL,created TEXT NOT NULL,old_revision INTEGER NOT NULL,new_revision INTEGER NOT NULL,before_body TEXT NOT NULL,after_body TEXT NOT NULL)')
  stamp=now().isoformat();changes=json.loads(row[1]);counts={'Add':0,'Update':0,'Archive':0}
  for c in changes:
   q=c['after'];body=json.dumps(q);revision=(c['revision'] or 0)+1
   if c.get('kind')=='case':
    if c['revision'] is None:db.execute('INSERT INTO cases(id,body,revision) VALUES (?,?,?)',(c['id'],body,revision))
    else:db.execute('UPDATE cases SET body=?,revision=? WHERE id=?',(body,revision,c['id']))
    counts[c['action']]+=1
    continue
   if c['revision'] is None:db.execute('INSERT INTO questions(id,body,revision) VALUES (?,?,?)',(c['id'],body,revision))
   else:db.execute('UPDATE questions SET body=?,revision=? WHERE id=?',(body,revision,c['id']))
   db.execute('INSERT INTO question_edit_history(question_id,actor_id,created,old_revision,new_revision,before_body,after_body) VALUES (?,?,?,?,?,?,?)',(c['id'],user_id,stamp,c['revision'] or 0,revision,json.dumps(c['before']),body))
   db.execute('INSERT OR IGNORE INTO organization VALUES (?,?)',(q['subject'],q['topic']));counts[c['action']]+=1
  result={'created':stamp,'counts':counts,'backup':saved['archive']};db.execute('UPDATE excel_previews SET result=? WHERE id=?',(json.dumps(result),ident))
 return result

def status(path):
 initialize(path)
 with sqlite3.connect(path) as db:row=db.execute('SELECT result FROM excel_previews WHERE result IS NOT NULL ORDER BY json_extract(result,\'$.created\') DESC LIMIT 1').fetchone()
 return json.loads(row[0]) if row else {}

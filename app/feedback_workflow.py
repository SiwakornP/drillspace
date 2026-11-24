"""Review state and append-only decisions for learner feedback."""
import json,sqlite3,datetime
STATES=('New','Under review','Resolved')
def initialize(path):
    with sqlite3.connect(path) as db:
        columns={r[1] for r in db.execute('PRAGMA table_info(feedback)')}
        for key,sql in [('status',"TEXT NOT NULL DEFAULT 'New'"),('decision',"TEXT NOT NULL DEFAULT ''"),('review_revision','INTEGER NOT NULL DEFAULT 0'),('reviewed_at','TEXT'),('question_revision','INTEGER')]:
            if key not in columns:db.execute(f'ALTER TABLE feedback ADD COLUMN {key} {sql}')
        db.execute('CREATE TABLE IF NOT EXISTS feedback_reviews(id INTEGER PRIMARY KEY,feedback_id INTEGER NOT NULL,actor_id INTEGER NOT NULL,status TEXT NOT NULL,decision TEXT NOT NULL,created TEXT NOT NULL)')

def items(path,question_id=None,public=False,owner=None):
    with sqlite3.connect(path) as db:
        db.row_factory=sqlite3.Row
        sql="SELECT f.*,COALESCE(u.name,'Earlier local comment') AS author FROM feedback f LEFT JOIN users u ON u.id=f.user_id WHERE 1=1";args=[]
        if question_id:sql+=' AND f.question_id=?';args.append(question_id)
        if public:sql+=" AND f.kind='public'"
        if owner is not None:sql+=' AND f.user_id=?';args.append(owner)
        result=[]
        for row in db.execute(sql+' ORDER BY f.id DESC',args):
            item=dict(row);item.pop('user_id',None)
            item['reviews']=[dict(x) for x in db.execute('SELECT r.status,r.decision,r.created FROM feedback_reviews r WHERE feedback_id=? ORDER BY id',(item['id'],))]
            result.append(item)
        return result

def review(path,actor,data):
    if actor['role']!='admin':raise ValueError('Administrator access required.')
    state=data.get('status');decision=data.get('decision')
    if state not in STATES:raise ValueError('Choose New, Under review, or Resolved.')
    if not isinstance(decision,str) or len(decision)>5000:raise ValueError('Decision must be at most 5000 characters.')
    decision=decision.strip()
    if state=='Resolved' and not decision:raise ValueError('Explain the decision before resolving this feedback.')
    with sqlite3.connect(path,timeout=10) as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT review_revision FROM feedback WHERE id=?',(data.get('id'),)).fetchone()
        if not row:raise ValueError('Feedback not found.')
        if data.get('revision')!=row[0]:raise ValueError('This feedback changed. Refresh before saving your review.')
        stamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
        db.execute('UPDATE feedback SET status=?,decision=?,review_revision=review_revision+1,reviewed_at=? WHERE id=?',(state,decision,stamp,data['id']))
        db.execute('INSERT INTO feedback_reviews(feedback_id,actor_id,status,decision,created) VALUES (?,?,?,?,?)',(data['id'],actor['id'],state,decision,stamp))
    return {'saved':True}

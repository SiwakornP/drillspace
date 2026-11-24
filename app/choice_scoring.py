"""Per-option grading with compatibility for saved legacy attempts."""
import math,copy

def modernize(question):
 q=copy.deepcopy(question)
 if q['type']=='single' and q['method']=='exact_match' or q['method']=='partial_credit':
  q['choice_scores']={c['id']:q['correct'] if c['id'] in q['accepted'] else q['incorrect'] for c in q['choices']}
  q['method']='per_choice' if q['type']=='single' else 'sum_choices'
 return q

def validate(q,legacy):
 method=q.get('method')
 if method not in ['per_choice','sum_choices']:return legacy(q)
 kind='single' if method=='per_choice' else 'multi'
 if q.get('type')!=kind:raise ValueError('Per-choice scoring requires single choice; sum-of-choices requires multiple selection.')
 choices=q.get('choices')
 if not isinstance(choices,list):raise ValueError('Enter answer choices.')
 scores=q.get('choice_scores')
 ids=[c.get('id') for c in choices if isinstance(c,dict)]
 if not isinstance(scores,dict) or set(scores)!=set(ids):raise ValueError('Enter a score for every populated option; blank is not zero.')
 if any(type(v) not in (int,float) or not math.isfinite(v) for v in scores.values()):raise ValueError('Option scores must be finite numbers.')
 for key in ['minimum','maximum','blank']:
  if type(q.get(key)) not in (int,float) or not math.isfinite(q[key]):raise ValueError('Enter valid minimum, maximum and unanswered scores.')
 if any(v<q['minimum'] or v>q['maximum'] for v in scores.values()):
  if method=='per_choice':raise ValueError('Every option score must fall within the minimum and maximum.')
 if method=='per_choice':
  if not scores or not math.isclose(max(scores.values()),q['maximum'],abs_tol=1e-9):raise ValueError('At least one option must earn the maximum score.')
  accepted=[c for c,v in scores.items() if math.isclose(v,q['maximum'],abs_tol=1e-9)]
 else:
  accepted=[c for c,v in scores.items() if v>0]
  if len(accepted)<2:raise ValueError('Summed multiple selection needs at least two positive-scoring options.')
  if not math.isclose(sum(max(0,v) for v in scores.values()),q['maximum'],abs_tol=1e-9):raise ValueError('Maximum score must equal the sum of positive option scores.')
 # Reuse the established text, choice, image, status and numeric validation.
 check=copy.deepcopy(q);check.update(method='exact_match',correct=q['maximum'],incorrect=0,accepted=accepted if kind=='multi' else accepted[:1])
 result=legacy(check);result.update(method=method,choice_scores=scores,accepted=accepted,correct=q['maximum'],incorrect=0)
 return result

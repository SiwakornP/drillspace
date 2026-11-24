from pathlib import Path
import json
import openpyxl

root = Path(__file__).resolve().parent
sheet = openpyxl.load_workbook(root.parent / 'Master_excel.xlsx', data_only=True).worksheets[0]
questions = []
headers = [cell.value for cell in sheet[1]]
legacy = ["questionID","question_text","question_image","question_type",*["option_"+c for c in "ABCDEF"],"Accepted answer","Answer notes","Correct score","Incorrect score","Unanswered","Max score","Scoring method","Minimum score","numeric_min","numeric_max","allow_decimals"]
for row in sheet.iter_rows(min_row=2, max_row=21, values_only=True):
    record = dict(zip(headers,row))
    row = [record.get(key) for key in legacy]
    if not row[1]:
        continue
    q = dict(subject=record.get("Subject") or "Unassigned", topic=record.get("Topic") or "Unassigned", id=row[0], text=row[1], image=row[2], type=row[3],
             choices=[dict(id=chr(65+i), text=str(v)) for i,v in enumerate(row[4:10]) if v is not None],
             accepted=str(row[10]).replace(' ', '').split(',') if row[3]!='range' else [],
             correct=row[12], incorrect=row[13], blank=row[14], maximum=row[15],
             method=row[16], minimum=row[17], lower=row[18], upper=row[19], decimals=row[20]=='Yes')
    assert all(isinstance(q[k], (int,float)) for k in ['correct','incorrect','blank','maximum','minimum']), q['id']
    if q['image']:
        assert (root/'dist'/q['image']).is_file(), q['image']
    if q['type']=='range':
        assert q['lower'] <= q['upper']
    else:
        assert set(q['accepted']) <= {c['id'] for c in q['choices']}
    questions.append(q)
assert len({q['id'] for q in questions}) == len(questions)
(root/'dist/questions.js').write_text('window.QUESTIONS = '+json.dumps(questions,ensure_ascii=False)+';\n')
print(f'Imported {len(questions)} questions; maximum score {sum(q["maximum"] for q in questions):g}.')

"""Portable Excel export; no desktop-only Node libraries."""
import sys,json
from openpyxl import Workbook
from openpyxl.styles import Font,PatternFill,Alignment
from openpyxl.utils import get_column_letter
p=json.load(open(sys.argv[1]));w=Workbook();w.remove(w.active)
for name,rows in [('Questions',p['rows']),('Cases',p['cases']),('SyncInfo',[['Sync batch',p['batch']],['Exported',p['created']],['Instructions','Keep IDs, revisions and headings unchanged. Add uses blank Permanent ID and Revision. Archive is reversible. Upload on Sync Master Excel for validation before applying.']])]:
 s=w.create_sheet(name)
 for row in rows:
  s.append(row)
  for c in s[s.max_row]:
   if isinstance(c.value,str):c.data_type='s'
   c.alignment=Alignment(vertical='top',wrap_text=True)
 for c in s[1]:c.font=Font(bold=True,color='FFFFFF');c.fill=PatternFill('solid',fgColor='243C5A')
 s.freeze_panes='A2';s.auto_filter.ref=s.dimensions if name!='SyncInfo' else 'A1:B1'
 for i in range(1,s.max_column+1):s.column_dimensions[get_column_letter(i)].width=24
 for c in s[1]:
  if c.value in ['Question text','Explanation','History','Laboratory findings']:s.column_dimensions[c.column_letter].width=65
w.save(sys.argv[2])

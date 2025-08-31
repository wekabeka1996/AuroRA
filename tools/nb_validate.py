import json, sys
from pathlib import Path

p = Path('notebooks/aurora_colab/Aurora_SSOT_XAI_Optuna.ipynb')
try:
    data = json.loads(p.read_text(encoding='utf-8'))
    print('OK nbformat=', data.get('nbformat'), 'cells=', len(data.get('cells', [])))
except Exception as e:
    txt = p.read_text(encoding='utf-8')
    print('ERROR:', e)
    # Extract error position if available
    import re
    m = re.search(r'char (\d+)', str(e))
    if m:
        pos = int(m.group(1))
        lo = max(0, pos-120)
        hi = min(len(txt), pos+120)
        snippet = txt[lo:hi]
        print('--- snippet ---')
        print(snippet)
        print('---------------')
    import traceback
    traceback.print_exc()

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import List

CLI = Path('tools/aci_proxy_eval.py')


def test_aci_proxy_cli_synthetic_only(tmp_path):
  """Smoke test the ACI proxy evaluation CLI with synthetic data only.

  Validates:
    - CLI exits with code 0
    - JSON + Markdown report files are created
    - Synthetic correlation rows present (expected 4 for provided sigma grid)
    - Median correlation meets minimum stability threshold (>= 0.6)
    - Markdown table header contains expected columns
  """
  out_json = tmp_path / 'report.json'
  out_md = tmp_path / 'summary.md'
  cmd = [
    sys.executable,
    str(CLI),
    '--synthetic', '240',
    '--sigma-grid', '0.1,0.2,0.4,0.8',
    '--out-json', str(out_json),
    '--out-md', str(out_md),
  ]
  env = dict(**os.environ)
  # Ensure root path on PYTHONPATH so 'living_latent' package is importable
  root = str(Path(__file__).resolve().parents[2])
  env['PYTHONPATH'] = root + (os.pathsep + env['PYTHONPATH'] if 'PYTHONPATH' in env else '')
  cp = subprocess.run(cmd, capture_output=True, text=True, env=env)
  assert cp.returncode == 0, (
    f"non-zero exit: {cp.returncode}\nstdout:\n{cp.stdout}\nstderr:\n{cp.stderr}"
  )
  assert out_json.exists(), 'report.json not created'
  assert out_md.exists(), 'summary.md not created'

  rep = json.loads(out_json.read_text(encoding='utf-8'))
  assert 'synthetic' in rep and isinstance(rep['synthetic'], list) and rep['synthetic'], 'synthetic block missing'
  corrs: List[float] = []
  for r in rep['synthetic']:
    if isinstance(r, dict):
      v = r.get('corr')
      if isinstance(v, (int, float)):
        corrs.append(float(v))
  assert len(corrs) == 4, f"unexpected synthetic rows: {rep['synthetic']}"

  sc = sorted(corrs)
  median_corr = 0.5 * (sc[1] + sc[2]) if len(sc) == 4 else sc[len(sc)//2]
  assert median_corr >= 0.6, f"median corr too low: {median_corr} (corrs={corrs})"

  md_txt = out_md.read_text(encoding='utf-8')
  assert '| sigma | corr |' in md_txt, 'markdown header not found'

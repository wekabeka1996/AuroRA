$ErrorActionPreference = 'Stop'

New-Item -ItemType Directory -Force -Path artifacts\release | Out-Null

Write-Host "Freezing requirements"
pip freeze | Out-File -FilePath artifacts\release\requirements.freeze.txt -Encoding ascii

Write-Host "Generating minimal SBOM"
python -c "import sys,pkgutil,json;print(json.dumps(sorted([m.name for m in pkgutil.iter_modules()]), indent=2))" | Out-File -FilePath artifacts\release\sbom.json -Encoding ascii

Write-Host "Validating and snapshotting configs"
python tools\validate_config.py --strict --fail-unknown configs\*.yaml
New-Item -ItemType Directory -Force -Path artifacts\config_snapshots | Out-Null
Copy-Item -Recurse -Force configs artifacts\config_snapshots\

Write-Host "Done"

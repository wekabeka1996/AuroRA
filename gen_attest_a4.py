import json,hashlib as H,os,platform
from datetime import datetime,timezone

STAGE = 'A4'
ENV_SNAPSHOT = 'A2_env_snapshot.json'
FILES = [
    'A2_env_snapshot.json',       # posture linkage
    'A4_bot_dryrun.log',          # raw runner stdout/stderr capture
    'A4_api_access.log',          # filtered pretrade/policy events
]

def hash_file(path: str):
    b = open(path,'rb').read()
    return {
        'file': path,
        'bytes': len(b),
        'sha256': H.sha256(b).hexdigest(),
        'sha1': H.sha1(b).hexdigest(),
        'md5': H.md5(b).hexdigest(),
    }

def main():
    arts = []
    for f in FILES:
        if os.path.exists(f):
            arts.append(hash_file(f))
    att = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'stage': STAGE,
        'posture_source': ENV_SNAPSHOT,
        'posture_asserted': None,
        'artifacts': arts,
        'tooling': {
            'python': platform.python_version(),
            'platform': platform.system()+ '-' + platform.release()+ '-' + platform.machine(),
        },
        'integrity': {
            'artifact_count': len(arts),
            'all_present': len(arts) == len(FILES),
            'expected_files': FILES,
        }
    }
    try:
        att['posture_asserted'] = json.load(open(ENV_SNAPSHOT,'r',encoding='utf-8')).get('posture')
    except Exception:
        pass
    out_file = f'{STAGE}_attestation.json'
    open(out_file,'w',encoding='utf-8').write(json.dumps(att,indent=2))
    print('OK', out_file)

if __name__ == '__main__':
    main()

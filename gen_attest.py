import json,hashlib as H,os,platform
from datetime import timezone,datetime
files=['A2_env_snapshot.json','A3_metrics.txt','A3_pretrade_response.json']
arts=[]
for f in files:
    if not os.path.exists(f):
        continue
    b=open(f,'rb').read()
    arts.append({'file':f,'bytes':len(b),'sha256':H.sha256(b).hexdigest(),'sha1':H.sha1(b).hexdigest(),'md5':H.md5(b).hexdigest()})
att={'generated_at':datetime.now(timezone.utc).isoformat(),'stage':'A3','posture_source':'A2_env_snapshot.json','posture_asserted':None,'artifacts':arts,'tooling':{'python':platform.python_version(),'platform':platform.system()+'-'+platform.release()+'-'+platform.machine()},'integrity':{'artifact_count':len(arts),'all_present':len(arts)==len(files)}}
try:
    att['posture_asserted']=json.load(open('A2_env_snapshot.json','r',encoding='utf-8')).get('posture')
except Exception:
    pass
open('A3_attestation.json','w',encoding='utf-8').write(json.dumps(att,indent=2))
print('OK A3_attestation.json')

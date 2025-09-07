import json, requests
payload = {"account":{"mode":"prod"},"order":{"symbol":"BTCUSDT","side":"buy","qty":0.001,"price":25000},"market":{}}
resp = requests.post('http://127.0.0.1:8037/pretrade/check', json=payload, timeout=5)
print('Status', resp.status_code)
print(resp.text)
open('A3_pretrade_response.json','w').write(resp.text)

"""Explicit real-model pickup-choice smoke; creates synthetic proposals, never a payment."""
import json
import time
import uuid
from pathlib import Path
from urllib.request import Request, urlopen


def api(path, body=None):
    request = Request('http://127.0.0.1:8000/api/'+path, data=None if body is None else json.dumps(body).encode(), headers={'Content-Type':'application/json'})
    with urlopen(request,timeout=30) as response: return json.load(response)


if __name__ == '__main__':
    start=time.perf_counter()
    session=api('flex/sessions',{})
    job=api('flex/sessions/'+session['id']+'/agent',{'cart_id':uuid.uuid4().hex,'item':'don','latest_pickup_minute':70,'minimum_saving_cents':200})
    for _ in range(130):
        result=api('rush/jobs/'+job['id'])
        if result['status']!='running': break
        time.sleep(1)
    Path('.local/flex-live-smoke.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    data=result.get('result',{})
    print(json.dumps({'status':result['status'],'seconds':round(time.perf_counter()-start,2),'model':data.get('model'),
                      'tools':data.get('tool_sequence'),'options':[(o['pickup_clock'],o['discount_cents'],o['released_cook_minutes']) for o in data.get('quote',{}).get('options',[])],
                      'bookings_created':len(data.get('session',{}).get('bookings',[])),'error':result.get('error')},indent=2))
    if result['status']!='done': raise SystemExit(1)

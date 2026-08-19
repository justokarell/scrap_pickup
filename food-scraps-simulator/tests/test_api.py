from fastapi.testclient import TestClient
from main import app
import json
from pathlib import Path

client=TestClient(app)

def payload(): return json.loads((Path(__file__).parents[1]/'reference_request.json').read_text())

def test_health():
    r=client.get('/health'); assert r.status_code==200; assert r.json()['status']=='ok'

def test_reference():
    r=client.post('/simulate',json=payload()); assert r.status_code==200,r.text
    out=r.json(); assert out['valid'] is True
    assert out['validation']['mass_balance_passed'] is True
    assert abs(out['validation']['mass_balance_residual_lbs'])<1e-6
    assert out['summary']['routes_executed']==2
    assert out['summary']['total_arrivals_lbs']>0
    assert out['summary']['total_collected_lbs']>0

def test_reproducible_except_run_id():
    p=payload(); a=client.post('/simulate',json=p).json(); b=client.post('/simulate',json=p).json()
    for k in ('summary','locations','trucks','processing_sites','failures','time_series'):
        assert a[k]==b[k]

def test_threshold_policy():
    p=payload(); p['scenario']['policy']={'type':'threshold','threshold':0.20,'weekdays':[]}
    r=client.post('/simulate',json=p); assert r.status_code==200; assert r.json()['valid'] is True

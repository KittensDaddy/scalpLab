from fastapi.testclient import TestClient
from scalp.web.app import app

def test_dashboard_loads():
    c=TestClient(app); r=c.get('/')
    assert r.status_code==200
    assert 'ScalpLab' in r.text
    assert 'Binance USD' in r.text

def test_health():
    assert TestClient(app).get('/api/health').json()['ok'] is True

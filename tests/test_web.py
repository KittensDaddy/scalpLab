from fastapi.testclient import TestClient
from scalp.web.app import app

def test_dashboard_loads():
    c=TestClient(app); r=c.get('/')
    assert r.status_code==200
    assert 'ScalpLab' in r.text
    assert 'Binance USD' in r.text

def test_health():
    payload=TestClient(app).get('/api/health').json()
    assert payload['ok'] is True
    assert payload['version']=='0.2.2'
    assert 'runtime' in payload
    assert 'open_fds' in payload['runtime']


def test_runtime_endpoint():
    r=TestClient(app).get('/api/runtime')
    assert r.status_code==200
    assert r.json()['state'] in {'OK','WARNING','CRITICAL'}


def test_web_polling_is_single_flight():
    from pathlib import Path
    js=(Path(__file__).parents[1]/'src/scalp/web/static/app.js').read_text()
    assert 'jobPollGeneration' in js
    assert 'AbortController' in js
    assert 'setInterval(async' not in js

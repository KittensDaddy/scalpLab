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


def test_backtest_uses_ranked_universe_selector():
    from pathlib import Path
    root=Path(__file__).parents[1]/'src/scalp/web'
    html=(root/'templates/index.html').read_text()
    js=(root/'static/app.js').read_text()
    assert 'id="universeGroups"' in html
    assert 'id="universeSearch"' in html
    assert 'id="manualSymbol"' in html
    assert 'btSymbols' not in html
    assert 'universe_snapshot_id:universeSnapshotId' in js
    assert "data-universe-group" in js


def test_data_inspector_ui_is_wired():
    from pathlib import Path
    root=Path(__file__).parents[1]/'src/scalp/web'
    html=(root/'templates/index.html').read_text(); js=(root/'static/app.js').read_text()
    assert 'data-page="inspector"' in html
    assert 'id="coverageRail"' in html
    assert 'id="inspectEnd"' in html
    assert '/api/data-inspector' in js


def test_strategy_editor_is_visual_not_json():
    from pathlib import Path
    root=Path(__file__).parents[1]/'src/scalp/web'
    html=(root/'templates/index.html').read_text(); editor=(root/'static/strategy-editor.js').read_text()
    assert 'id="visualRuleEditor"' in html
    assert 'id="indicatorGuide"' in html
    assert 'draftDefinition' not in html
    assert 'data-add-group' in editor

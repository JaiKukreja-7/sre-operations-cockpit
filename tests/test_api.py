from fastapi.testclient import TestClient
from cockpit.api import create_app
from cockpit.demo import create_app as create_demo


def test_configuration_docs_results_summary(tmp_path):
    with TestClient(create_app(tmp_path / 'api.db')) as client:
        assert client.get('/health').json() == {'status': 'ok'}
        assert client.get('/docs').status_code == 200
        assert client.get('/openapi.json').json()['info']['title'] == 'SRE Operations Cockpit'
        config = client.get('/api/checks').json()[0]
        assert config['interval_seconds'] == 5
        config.pop('id')
        assert client.post('/api/checks', json=config).status_code == 201
        config['latency_threshold_ms'] = 200
        assert client.put('/api/checks/1', json=config).status_code == 200
        assert client.get('/api/checks/1/results').json() == []
        values = client.get('/api/checks/1/summary').json()
        assert values['summary']['sli'] is None
        assert values['summary']['burn_rate'] is None
        assert 'window_start' in values['summary']
        assert values['generated_at'].endswith('+00:00')
        assert client.get('/api/checks/1/summary?policy=thirty_day').status_code == 200
        assert client.get('/api/checks/999/results').status_code == 404
        assert client.get('/api/checks/1/results?limit=0').status_code == 422


def test_arbitrary_targets_rejected(tmp_path):
    with TestClient(create_app(tmp_path / 'api.db')) as client:
        for url in ('http://example.com', 'http://localhost:8001/probe', 'http://127.0.0.1:8001/other'):
            assert client.post('/api/checks', json={'url': url}).status_code == 422
        assert client.post('/api/checks', json={'timeout_seconds': 6}).status_code == 422
        assert client.post('/api/checks', json={'interval_seconds': 0}).status_code == 422


def test_policy_configuration_validation(tmp_path):
    with TestClient(create_app(tmp_path / 'api.db')) as client:
        policy = client.get('/api/policies').json()['demo']
        policy['short_min_samples'] = 5
        assert client.put('/api/policies/demo', json=policy).status_code == 200
        assert client.get('/api/policies').json()['demo']['short_min_samples'] == 5
        report = client.get('/api/policies').json()['thirty_day']
        report['window_seconds'] = 86400
        assert client.put('/api/policies/thirty_day', json=report).status_code == 422
        policy['slo_target'] = 1
        assert client.put('/api/policies/demo', json=policy).status_code == 422
        policy['slo_target'] = .95
        policy['short_window_seconds'] = 200
        assert client.put('/api/policies/demo', json=policy).status_code == 422


def test_demo_modes():
    with TestClient(create_demo()) as client:
        assert client.get('/mode').json()['mode'] == 'Healthy'
        assert client.get('/probe').text == 'synthetic demo OK'
        assert client.put('/mode', json={'mode': 'Slow', 'delay_seconds': .01}).status_code == 200
        assert client.get('/probe').status_code == 200
        assert client.put('/mode', json={'mode': 'Failing'}).status_code == 200
        assert client.get('/probe').status_code == 500
        assert client.put('/mode', json={'mode': 'Healthy'}).status_code == 200
        assert client.get('/probe').status_code == 200
        assert client.put('/mode', json={'mode': 'Other'}).status_code == 422

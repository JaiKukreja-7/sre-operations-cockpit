import re
from pathlib import Path
from fastapi.testclient import TestClient
from cockpit.api import create_app


def test_production_dashboard_assets_and_api_routes(tmp_path):
    with TestClient(create_app(tmp_path / 'dashboard.db')) as client:
        response = client.get('/')
        assert response.status_code == 200
        assert 'text/html' in response.headers['content-type']
        assert '<div id="root"></div>' in response.text
        assets = re.findall(r'(?:src|href)="(/assets/[^\"]+)"', response.text)
        assert len(assets) >= 2
        for asset in assets:
            result = client.get(asset)
            assert result.status_code == 200
            assert len(result.content) > 100
        assert client.get('/api/checks').json()[0]['url'] == 'http://127.0.0.1:8001/probe'
        assert client.get('/docs').status_code == 200
        assert client.get('/openapi.json').status_code == 200
        assert client.get('/api/missing-route').status_code == 404
        assert client.get('/assets/missing.js').status_code == 404
        assert client.get('/%2e%2e/requirements.txt').status_code == 404


def test_missing_bundle_keeps_api_available(tmp_path):
    with TestClient(create_app(tmp_path / 'api.db', dashboard_dir=tmp_path / 'missing')) as client:
        response = client.get('/')
        assert response.status_code == 503
        assert 'Dashboard build missing' in response.text
        assert client.get('/api/checks').status_code == 200
        assert client.get('/docs').status_code == 200

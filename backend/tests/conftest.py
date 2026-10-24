"""Isolated real application fixtures; no production paths or fixed credentials."""
from __future__ import annotations

import secrets
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image


@pytest.fixture
def settings(tmp_path):
    from backend.app.config import Settings
    return Settings(data_dir=tmp_path / 'archive', public_origin='http://testserver')


@pytest.fixture
def app(settings):
    from backend.app.main import create_app
    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app) as value:
        yield value


@pytest.fixture
def web(client, settings):
    username = 'test-admin'
    password = secrets.token_urlsafe(24)
    token = settings.bootstrap_token_file.read_text().strip()
    result = client.post('/api/auth/bootstrap', json={'username': username, 'password': password, 'bootstrap_token': token},
                         headers={'Origin': 'http://testserver'})
    assert result.status_code == 200, result.text
    status = client.get('/api/auth/status').json()
    if not status.get('authenticated'):
        result = client.post('/api/auth/login', json={'username': username, 'password': password}, headers={'Origin': 'http://testserver'})
        assert result.status_code == 200, result.text
        status = client.get('/api/auth/status').json()
    client.headers.update({'Origin': 'http://testserver', 'X-CSRF-Token': status['csrf_token']})
    client.test_username = username
    client.test_password = password
    return client


@pytest.fixture
def image_bytes():
    stream = BytesIO()
    Image.new('RGB', (240, 320), color=(240, 242, 245)).save(stream, format='PNG')
    return stream.getvalue()


@pytest.fixture
def asset(web, image_bytes):
    result = web.post('/api/assets', files={'file': ('test-original.png', image_bytes, 'image/png')})
    assert result.status_code == 200, result.text
    return result.json()


@pytest.fixture
def submission(web, asset):
    result = web.post('/api/submissions', json={
        'prompt': {'title': 'An original observation', 'language': 'en', 'instructions': 'Describe a place you know.'},
        'pages': [{'page_id': page['page_id'], 'rotation': 0} for page in asset['pages']],
    })
    assert result.status_code == 200, result.text
    return result.json()


@pytest.fixture
def credential(web):
    result = web.post('/api/credentials', json={'name': 'Independent test client', 'scopes': ['archive.read', 'media.read', 'proposals.write']})
    assert result.status_code == 200, result.text
    return result.json()

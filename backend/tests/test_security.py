"""Web/MCP authentication boundaries and output safety."""
from __future__ import annotations

import json

import pytest
from sqlalchemy import select


@pytest.mark.parametrize('path', ['/api/categories', '/api/prompts', '/api/reviews', '/api/credentials', '/api/settings'])
def test_anonymous_cannot_read_business(client, path):
    result = client.get(path)
    assert result.status_code in (401, 403), result.text


def test_health_exposes_no_private_storage(client):
    result = client.get('/api/health')
    assert result.status_code == 200
    assert set(result.json()) == {'status', 'version'}


def test_bootstrap_rejects_wrong_token(client):
    result = client.post('/api/auth/bootstrap', json={'username': 'bad-admin', 'password': 'sufficient-long-secret', 'bootstrap_token': 'wrong'},
                         headers={'Origin': 'http://testserver'})
    assert result.status_code in (401, 403)
    assert client.get('/api/auth/status').json()['initialized'] is False


def test_write_requires_both_origin_and_csrf(web):
    payload = {'name': 'must not exist'}
    csrf = web.headers.pop('X-CSRF-Token')
    assert web.post('/api/categories', json=payload).status_code == 403
    web.headers['X-CSRF-Token'] = csrf
    assert web.post('/api/categories', json=payload, headers={'Origin': 'https://evil.example'}).status_code == 403
    assert web.get('/api/categories').json()['items'] == []


def test_bearer_cannot_impersonate_web_or_manage_keys(client, web, credential):
    token = credential['secret']
    # Remove all Web session authority while keeping a legitimate MCP key.
    client.cookies.clear()
    client.headers.pop('X-CSRF-Token', None)
    client.headers['Authorization'] = 'Bearer ' + token
    assert client.get('/api/credentials').status_code in (401, 403)
    assert client.post('/api/categories', json={'name': 'forged actor', 'actor': 'web:admin'}).status_code in (401, 403)
    assert client.post('/api/reviews/not-a-real-id/decide', json={'expected_revision': 1, 'expected_digest': 'x', 'decision': 'approve'}).status_code in (401, 403)


def test_secret_only_returned_once_and_not_in_audit(web, credential, app):
    from backend.app.db.models import AuditEvent, Credential
    secret = credential['secret']
    listing = web.get('/api/credentials').json()
    assert secret not in json.dumps(listing)
    assert 'secret_hash' not in json.dumps(listing)
    with app.state.db.read() as session:
        key = session.get(Credential, credential['id'])
        assert key.secret_hash != secret
        logs = [event.result for event in session.scalars(select(AuditEvent))]
        assert secret not in json.dumps(logs)


def test_no_admin_or_approval_scope(web):
    for scope in ('admin', 'review.approve', 'filesystem.read', 'sql.execute'):
        result = web.post('/api/credentials', json={'name': 'forbidden', 'scopes': [scope]})
        assert result.status_code in (400, 422), result.text


def test_session_cookie_security(client, web):
    # HttpOnly / SameSite must be set during login; secure depends on deployment config.
    result = web.post('/api/auth/login', json={'username': web.test_username, 'password': web.test_password})
    cookie = result.headers.get('set-cookie', '').lower()
    assert 'httponly' in cookie and 'samesite=' in cookie


def test_strict_input_rejects_privileged_extra_fields(web):
    result = web.post('/api/categories', json={'name': 'Allowed name', 'approved': True, 'actor': 'web:admin'})
    assert result.status_code in (400, 422)
    assert web.get('/api/categories').json()['items'] == []


def test_user_strings_are_data_and_json_has_nosniff(web):
    title = '<img src=x onerror=window.__xss=1>'
    result = web.post('/api/prompts', json={'title': title, 'language': 'zh', 'instructions': '<script>alert(1)</script>'})
    assert result.status_code == 200, result.text
    response = web.get('/api/prompts/' + result.json()['id'])
    assert response.json()['title'] == title
    assert response.headers.get('x-content-type-options') == 'nosniff'


@pytest.mark.parametrize('old_path', ['/api/state', '/api/session/start', '/api/ai/config', '/api/drafts', '/api/assistant', '/api/essay/ocr'])
def test_legacy_api_does_not_execute_old_business(web, old_path):
    assert web.get(old_path).status_code == 404
    assert web.post(old_path, json={}).status_code in (404, 405)


def test_bootstrap_cannot_be_reused_and_logout_revokes_session(web, settings):
    result = web.post('/api/auth/bootstrap', json={'username': 'replacement-admin', 'password': 'not-a-production-secret',
                                                 'bootstrap_token': settings.bootstrap_token_file.read_text().strip()})
    assert result.status_code == 409
    assert web.get('/api/auth/status').json()['username'] == web.test_username
    assert web.post('/api/auth/logout', json={}).status_code == 200
    assert web.get('/api/categories').status_code == 401


def test_wrong_password_and_repeated_attempts_are_rate_limited_in_one_app(web):
    # Limit remains enabled; successful fixture authentication consumes one attempt.
    for _ in range(9):
        result = web.post('/api/auth/login', json={'username': web.test_username, 'password': 'incorrect-password'})
        assert result.status_code == 401
    result = web.post('/api/auth/login', json={'username': web.test_username, 'password': web.test_password})
    assert result.status_code == 429


def test_chunked_upload_is_bounded_before_multipart_spooling(tmp_path):
    import secrets
    import socket
    import threading
    import time

    import httpx
    import uvicorn

    from backend.app.config import Settings
    from backend.app.db.models import Asset
    from backend.app.main import create_app
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    origin = 'http://127.0.0.1:' + str(sock.getsockname()[1])
    settings = Settings(data_dir=tmp_path / 'bounded-upload', public_origin=origin, image_max_bytes=16, pdf_max_bytes=16)
    app = create_app(settings)
    server = uvicorn.Server(uvicorn.Config(app, log_level='error'))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started
        with httpx.Client(base_url=origin, headers={'Origin': origin}, trust_env=False, timeout=10) as client:
            result = client.post('/api/auth/bootstrap', json={'username': 'bounded-admin', 'password': secrets.token_urlsafe(24),
                                 'bootstrap_token': settings.bootstrap_token_file.read_text().strip()})
            assert result.status_code == 200
            csrf = client.get('/api/auth/status').json()['csrf_token']
            headers = {'X-CSRF-Token': csrf, 'Content-Type': 'multipart/form-data; boundary=CLMStest'}
            def chunks():
                yield b'--CLMStest\r\nContent-Disposition: form-data; name="file"; filename="bounded.png"\r\nContent-Type: image/png\r\n\r\n'
                for _ in range(18):
                    yield b'x' * 65536
                yield b'\r\n--CLMStest--\r\n'
            response = client.post('/api/assets', headers=headers, content=chunks())
            assert response.request.headers['Transfer-Encoding'] == 'chunked'
            assert 'Content-Length' not in response.request.headers
            assert response.status_code == 413, response.text
            assert response.json()['error']['code'] == 'media_limit_exceeded'
        with app.state.db.read() as session:
            assert session.scalars(select(Asset)).all() == []
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
        assert not thread.is_alive()

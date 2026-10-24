"""Core archive remains usable with all external network connections rejected."""
import socket
from dataclasses import fields
from pathlib import Path


def test_no_external_network_or_model_configuration_required(web, image_bytes, monkeypatch):
    attempted_external = []
    connect = socket.socket.connect
    def local_only(sock, address):
        if isinstance(address, tuple) and address[0] not in ('127.0.0.1', '::1', 'localhost'):
            attempted_external.append(address[0])
            raise AssertionError('Runtime attempted an external network connection')
        return connect(sock, address)
    monkeypatch.setattr(socket.socket, 'connect', local_only)
    upload = web.post('/api/assets', files={'file': ('only-original.png', image_bytes, 'image/png')})
    assert upload.status_code == 200, upload.text
    asset = upload.json()
    result = web.post('/api/submissions', json={'prompt': {'language': 'zh', 'instructions': '观察身边的一处地方。'},
                                              'pages': [{'page_id': asset['pages'][0]['page_id'], 'rotation': 0}]})
    assert result.status_code == 200, result.text
    archived = result.json()
    version = web.get('/api/versions/' + archived['version_id']).json()
    evaluation = web.post('/api/evaluations', json={'version_id': version['id'], 'expected_manifest_hash': version['manifest_hash'],
        'expected_prompt_snapshot_hash': version['prompt_snapshot_hash'], 'coverage': {'reviewed_page_ids': [asset['pages'][0]['page_id']], 'scope': 'full', 'limitations': []},
        'summary': '人工评价，在拒绝外部连接的环境中保存。', 'score': None})
    assert evaluation.status_code == 200, evaluation.text
    assert web.get('/api/assets/' + asset['id'] + '/original').content == image_bytes
    assert not attempted_external


def test_runtime_dependency_and_settings_have_no_ocr_or_model_providers():
    import tomllib

    from backend.app.config import Settings
    root = Path(__file__).resolve().parents[2]
    dependencies = tomllib.loads((root / 'pyproject.toml').read_text())['project']['dependencies']
    forbidden = ('openai', 'anthropic', 'pytesseract', 'easyocr', 'ocrmypdf', 'paddleocr')
    assert not any(dependency.lower().startswith(forbidden) for dependency in dependencies)
    assert not {'model_api_key', 'model_provider', 'ocr_provider', 'ocr_api_key'} & {f.name for f in fields(Settings)}
    for path in (root / 'backend/app').rglob('*.py'):
        source = path.read_text()
        assert not any('import ' + name in source or 'from ' + name in source for name in forbidden), path

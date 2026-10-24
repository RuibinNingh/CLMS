#!/usr/bin/env python3
"""Install locks into a fresh directory, migrate, build, start, restart and verify."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
from io import BytesIO
from pathlib import Path

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.test_server import server  # noqa: E402


def command(argv, cwd, log):
    with log.open('w') as output:
        result = subprocess.run(argv, cwd=cwd, stdout=output, stderr=subprocess.STDOUT, check=False)
    if result.returncode:
        raise RuntimeError(f'clean install command failed ({result.returncode}): {argv}; see {log}')
    return {'command': argv, 'exit_code': result.returncode, 'evidence': str(log)}


def post(client, path, payload):
    result = client.post('/api' + path, json=payload)
    if result.status_code != 200:
        raise RuntimeError(f'{path} returned {result.status_code}: {result.text}')
    return result.json()


async def pending(origin, secret):
    async with httpx.AsyncClient(headers={'Authorization': 'Bearer ' + secret}, trust_env=False) as http:
        async with streamable_http_client(origin + '/mcp/', http_client=http) as (read, write, _):
            async with ClientSession(read, write) as client:
                await client.initialize()
                result = await client.call_tool('propose_category_change', {'request_id': 'clean-deploy-pending', 'payload': {'action': 'create', 'name': 'Remain pending'}})
                assert not result.isError
                return result.structuredContent


def main():
    evidence = Path(os.getenv('CLMS_VERIFY_ARTIFACTS', ROOT / 'artifacts')) / 'clean-deployment'
    evidence.mkdir(parents=True, exist_ok=True)
    report = {'type': 'disposable-clean-install', 'production_deployed': False, 'steps': []}
    with tempfile.TemporaryDirectory(prefix='clms-clean-deploy-') as temporary:
        target = Path(temporary) / 'application'
        target.mkdir()
        for name in ('pyproject.toml', 'uv.lock', 'alembic.ini'):
            shutil.copy2(ROOT / name, target / name)
        shutil.copytree(ROOT / 'backend', target / 'backend', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        shutil.copytree(ROOT / 'frontend', target / 'frontend', ignore=shutil.ignore_patterns('node_modules', 'dist', 'test-results', 'playwright-report'))
        python = str(target / '.venv/bin/python')
        report['steps'].append(command(['uv', 'sync', '--frozen', '--no-dev', '--no-install-project', '--python', sys.executable], target, evidence / 'uv-install.log'))
        report['steps'].append(command(['npm', 'ci'], target / 'frontend', evidence / 'npm-install.log'))
        report['steps'].append(command(['npm', 'run', 'build'], target / 'frontend', evidence / 'frontend-build.log'))
        data = Path(temporary) / 'fresh-data'
        password = secrets.token_urlsafe(24)
        with server(target, python, data, evidence / 'first-start.log') as (origin, _):
            with httpx.Client(base_url=origin, headers={'Origin': origin}, trust_env=False) as client:
                assert client.get('/').status_code == 200
                token = (data / 'bootstrap.token').read_text().strip()
                post(client, '/auth/bootstrap', {'username': 'clean-admin', 'password': password, 'bootstrap_token': token})
                client.headers['X-CSRF-Token'] = client.get('/api/auth/status').json()['csrf_token']
                assert client.get('/api/categories').json()['items'] == []
                category = post(client, '/categories', {'name': 'Personal observation', 'language_scope': 'en'})
                blob = BytesIO()
                Image.new('RGB', (300, 420), '#eef3f8').save(blob, format='PNG')
                original = blob.getvalue()
                upload = client.post('/api/assets', files={'file': ('clean-original.png', original, 'image/png')})
                assert upload.status_code == 200, upload.text
                asset = upload.json()
                submission = post(client, '/submissions', {'prompt': {'title': 'Fresh install essay', 'language': 'en', 'instructions': 'Describe a place.', 'category_ids': [category['id']]},
                    'pages': [{'page_id': asset['pages'][0]['page_id'], 'rotation': 0}], 'reflection': 'Persist across restart'})
                version = client.get('/api/versions/' + submission['version_id']).json()
                payload = {'schema_version': 1, 'version_id': version['id'], 'expected_manifest_hash': version['manifest_hash'],
                    'expected_prompt_snapshot_hash': version['prompt_snapshot_hash'], 'coverage': {'reviewed_page_ids': [asset['pages'][0]['page_id']], 'scope': 'full', 'limitations': []},
                    'summary': 'Manual clean deployment feedback', 'strengths': [], 'score': None, 'issues': [], 'next_actions': []}
                evaluation = post(client, '/evaluations', payload)
                key = post(client, '/credentials', {'name': 'Clean pending client', 'scopes': ['archive.read', 'proposals.write']})
                proposal = asyncio.run(pending(origin, key['secret']))
                assert proposal['status'] == 'pending'
                digest = hashlib.sha256(original).hexdigest()
                assert hashlib.sha256(client.get('/api/assets/' + asset['id'] + '/original').content).hexdigest() == digest
                report['first_run'] = {'category_id': category['id'], **submission, 'evaluation_id': evaluation['evaluation_id'],
                                       'pending_operation_id': proposal['id'], 'original_sha256': digest}
        # The old process has stopped; a new process binds a new TCP port and reloads disk.
        with server(target, python, data, evidence / 'restart.log') as (origin, _):
            with httpx.Client(base_url=origin, headers={'Origin': origin}, trust_env=False) as client:
                post(client, '/auth/login', {'username': 'clean-admin', 'password': password})
                assert len(client.get('/api/categories').json()['items']) == 1
                version_after = client.get('/api/versions/' + submission['version_id']).json()
                assert version_after['manifest_hash'] == version['manifest_hash']
                assert len(version_after['evaluations']) == 1
                assert version_after['evaluations'][0]['id'] == evaluation['evaluation_id']
                assert client.get('/api/attempts/' + submission['attempt_id']).json()['reflection'] == 'Persist across restart'
                assert client.get('/api/reviews/' + proposal['id']).json()['status'] == 'pending'
                assert hashlib.sha256(client.get('/api/assets/' + asset['id'] + '/original').content).hexdigest() == digest
                report['restart'] = {'healthy': client.get('/api/health').json(), 'original_hash_matches': True, 'relationships_match': True,
                                     'evaluation_match': True, 'pending_remains_pending': True}
    report['status'] = 'pass'
    (evidence / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print('Clean lock installation, migrations, build, upload, restart and persistence passed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

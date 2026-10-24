#!/usr/bin/env python3
"""Build/run a disposable production image with private persistent data."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import secrets
import subprocess
import sys
import time
import uuid
from io import BytesIO
from pathlib import Path

import httpx
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.test_server import unused_port  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', action='store_true')
    parser.add_argument('--image', default='clms-archive:0.9.0')
    args = parser.parse_args()
    evidence = ROOT / 'artifacts/docker'
    evidence.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if k not in {'DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_TLS', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH'}}
    docker = ['docker', '--host=unix:///var/run/docker.sock']
    def git(*arguments):
        result = subprocess.run(['git', *arguments], cwd=ROOT, capture_output=True, text=True, check=False)
        return result.stdout.strip() if result.returncode == 0 else None
    report = {'kind': 'disposable-container-verification', 'production_deployed': False,
              'delivery_commit': git('rev-parse', 'HEAD'), 'branch': git('branch', '--show-current'),
              'working_tree_dirty': bool(git('status', '--porcelain')),
              'started_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'commands': []}
    def run(arguments, *, capture=True):
        result = subprocess.run(docker + arguments, cwd=ROOT, env=env, capture_output=capture, text=True, check=False)
        report['commands'].append({'command': docker + arguments, 'exit_code': result.returncode})
        if result.returncode:
            raise RuntimeError('Docker command failed: ' + ' '.join(arguments) + '\n' + (result.stderr or ''))
        return result.stdout.strip() if capture else ''
    run(['info', '--format', '{{.ServerVersion}}'])
    if args.build:
        # Public system CA extends the inner tool's trust; never disable TLS.
        build = docker + ['build', '--secret', 'id=proxy_ca,src=/etc/ssl/certs/ca-certificates.crt', '--secret', 'id=system_ca,src=/etc/ssl/certs/ca-certificates.crt',
                          '-f', 'deploy/Dockerfile', '-t', args.image, '.']
        with (evidence / 'build.log').open('w') as output:
            result = subprocess.run(build, cwd=ROOT, env=env, stdout=output, stderr=subprocess.STDOUT, check=False)
        report['commands'].append({'command': build, 'exit_code': result.returncode})
        if result.returncode:
            raise RuntimeError('Docker build failed; see artifacts/docker/build.log')
    identity = 'clms-verify-' + uuid.uuid4().hex[:12]
    volume = identity + '-data'
    port = unused_port()
    origin = f'http://127.0.0.1:{port}'
    try:
        run(['run', '--detach', '--name', identity, '--read-only', '--tmpfs', '/tmp:rw,size=128m,mode=1777',
             '--security-opt', 'no-new-privileges', '--cap-drop', 'ALL', '-p', f'127.0.0.1:{port}:8472',
             '-e', 'CLMS_PUBLIC_ORIGIN=' + origin, '-v', volume + ':/var/lib/clms-archive', args.image])
        def wait():
            for _ in range(300):
                try:
                    if httpx.get(origin + '/api/health', trust_env=False, timeout=0.5).status_code == 200:
                        return
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            raise RuntimeError('Docker health did not become ready')
        wait()
        # Only the operator reads the local token; its value is never recorded.
        token = subprocess.check_output(docker + ['exec', identity, 'python', '-c', "from pathlib import Path; print(Path('/var/lib/clms-archive/bootstrap.token').read_text())"], env=env, text=True).strip()
        password = secrets.token_urlsafe(24)
        with httpx.Client(base_url=origin, headers={'Origin': origin}, trust_env=False) as client:
            response = client.post('/api/auth/bootstrap', json={'username': 'container-admin', 'password': password, 'bootstrap_token': token})
            assert response.status_code == 200, response.text
            csrf = client.get('/api/auth/status').json()['csrf_token']
            client.headers['X-CSRF-Token'] = csrf
            category = client.post('/api/categories', json={'name': 'Container persistence'}).json()
            assert 'id' in category
            blob = BytesIO()
            Image.new('RGB', (120, 180), '#faf8f3').save(blob, format='PNG')
            original = blob.getvalue()
            asset = client.post('/api/assets', files={'file': ('container.png', original, 'image/png')}).json()
            submission = client.post('/api/submissions', json={'prompt': {'title': 'Container original', 'language': 'zh', 'instructions': 'Write about a memory.', 'category_ids': [category['id']]},
                'pages': [{'page_id': asset['pages'][0]['page_id'], 'rotation': 0}]}).json()
            assert 'version_id' in submission
            expected_hash = hashlib.sha256(original).hexdigest()
            assert hashlib.sha256(client.get('/api/assets/' + asset['id'] + '/original').content).hexdigest() == expected_hash
        run(['restart', identity])
        wait()
        with httpx.Client(base_url=origin, headers={'Origin': origin}, trust_env=False) as client:
            response = client.post('/api/auth/login', json={'username': 'container-admin', 'password': password})
            assert response.status_code == 200
            version = client.get('/api/versions/' + submission['version_id']).json()
            assert version['manifest'][0]['asset_id'] == asset['id']
            assert hashlib.sha256(client.get('/api/assets/' + asset['id'] + '/original').content).hexdigest() == expected_hash
        inspect = json.loads(run(['inspect', '--format', '{{json .Config.User}}', identity]))
        assert inspect == '10001:10001'
        report.update(status='pass', image=args.image, image_id=run(['image', 'inspect', '--format', '{{.Id}}', args.image]),
                      non_root_user=inspect, restart_persistent=True, original_hash=expected_hash)
        return 0
    finally:
        logs = subprocess.run(docker + ['logs', identity], env=env, capture_output=True, text=True, check=False)
        (evidence / 'container.log').write_text(logs.stdout + logs.stderr)
        subprocess.run(docker + ['rm', '--force', identity], env=env, capture_output=True, check=False)
        subprocess.run(docker + ['volume', 'rm', volume], env=env, capture_output=True, check=False)
        report['finished_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
        (evidence / 'report.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())

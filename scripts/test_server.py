"""Utilities for disposable real-port verification processes."""
from __future__ import annotations

import os
import socket
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

import httpx


def unused_port() -> int:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


@contextmanager
def server(root: Path, python: str, data: Path, log: Path, *, port: int | None = None):
    port = port or unused_port()
    origin = f'http://127.0.0.1:{port}'
    env = {**os.environ, 'CLMS_DATA_DIR': str(data), 'CLMS_PUBLIC_ORIGIN': origin,
           'CLMS_SECURE_COOKIE': 'false', 'PYTHONPATH': str(root)}
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open('w') as output:
        process = subprocess.Popen([python, '-m', 'uvicorn', 'backend.app.main:app', '--host', '127.0.0.1', '--port', str(port)],
                                   cwd=root, env=env, stdout=output, stderr=subprocess.STDOUT)
        try:
            for _ in range(300):
                if process.poll() is not None:
                    raise RuntimeError(f'application exited {process.returncode}; see {log}')
                try:
                    health = httpx.get(origin + '/api/health', timeout=0.5, trust_env=False)
                    if health.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            else:
                raise RuntimeError('application did not become healthy; see ' + str(log))
            yield origin, env
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

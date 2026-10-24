"""Independent CAS, idempotency, fault, concurrency and persistence checks."""
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import func, select

from backend.app.db.models import Category, ReviewDecision, ReviewOperation
from backend.app.domain import reviews
from backend.app.errors import DomainError


def propose(app, credential, name='Pending category', request_id='request-1'):
    with app.state.db.transaction() as session:
        return reviews.propose(session, 'category', {'action': 'create', 'name': name, 'language_scope': 'en'}, 'mcp:' + credential['id'], request_id)


def decide(web, proposal, **changes):
    return web.post('/api/reviews/' + proposal['id'] + '/decide', json={
        'expected_revision': proposal['revision'], 'expected_digest': proposal['effective_digest'], 'decision': 'approve', **changes})


def count(app, model):
    with app.state.db.read() as session:
        return session.scalar(select(func.count()).select_from(model))


def test_pending_never_writes_formal_and_rejection_keeps_empty(web, app, credential):
    proposal = propose(app, credential)
    assert proposal['status'] == 'pending' and proposal['requires_human_review'] is True
    assert count(app, Category) == 0
    result = decide(web, proposal, decision='reject')
    assert result.status_code == 200 and result.json()['status'] == 'rejected'
    assert count(app, Category) == 0


def test_request_idempotency_survives_manual_revision(web, app, credential):
    first = propose(app, credential)
    result = web.post('/api/reviews/' + first['id'] + '/revise', json={'expected_revision': 1, 'changes': {'name': 'Human correction'}})
    assert result.status_code == 200, result.text
    retry = propose(app, credential)
    assert retry['id'] == first['id'] and retry['payload']['name'] == 'Human correction'
    assert retry['revision'] == 2
    with pytest.raises(DomainError) as conflict:
        propose(app, credential, name='Different request content')
    assert conflict.value.code == 'idempotency_conflict'
    assert count(app, ReviewOperation) == 1


def test_cas_and_identity_fields_cannot_replace_human_revision(web, app, credential):
    first = propose(app, credential)
    current = web.post('/api/reviews/' + first['id'] + '/revise', json={'expected_revision': 1, 'changes': {'name': 'Edited'}}).json()
    assert decide(web, first).status_code == 409
    stale = web.post('/api/reviews/' + first['id'] + '/revise', json={'expected_revision': 1, 'changes': {'name': 'Overwrite'}})
    assert stale.status_code == 409
    for field in ('source_actor', 'request_id', 'category_id', 'expected_revision', 'action'):
        result = web.post('/api/reviews/' + first['id'] + '/revise', json={'expected_revision': 2, 'changes': {field: 'forged'}})
        assert result.status_code in (403, 422), result.text
    assert web.get('/api/reviews/' + first['id']).json()['payload']['name'] == 'Edited'
    result = decide(web, current)
    assert result.status_code == 200 and result.json()['status'] == 'applied'


def test_approval_retry_returns_same_receipt_once(web, app, credential):
    proposal = propose(app, credential)
    first, retry = decide(web, proposal), decide(web, proposal)
    assert first.status_code == retry.status_code == 200
    assert first.json()['result'] == retry.json()['result']
    assert count(app, Category) == count(app, ReviewDecision) == 1


def test_two_concurrent_decisions_apply_once(web, app, credential):
    proposal = propose(app, credential)
    def worker(_):
        with app.state.db.transaction() as session:
            return reviews.decide(session, proposal['id'], proposal['revision'], proposal['effective_digest'], 'approve', 'web:concurrency-test')
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(worker, range(2)))
    assert outcomes[0]['result'] == outcomes[1]['result']
    assert count(app, Category) == count(app, ReviewDecision) == 1


def test_formal_write_failure_rolls_back_then_records_failed(web, app, credential, monkeypatch):
    proposal = propose(app, credential)
    real = reviews.dispatch.apply
    def injected(session, kind, payload, actor):
        real(session, kind, payload, actor)
        session.flush()
        raise RuntimeError('fault after domain flush before review receipt')
    monkeypatch.setattr(reviews.dispatch, 'apply', injected)
    result = decide(web, proposal)
    assert result.status_code == 200, result.text
    assert result.json()['status'] == 'failed'
    assert count(app, Category) == count(app, ReviewDecision) == 0
    assert web.get('/api/reviews/' + proposal['id']).json()['status'] == 'failed'


def test_composite_invalid_page_does_not_create_inline_business(web, app):
    before = count(app, Category)
    result = web.post('/api/submissions', json={'inline_categories': [{'name': 'Should rollback'}],
        'prompt': {'title': 'Should rollback', 'language': 'en', 'instructions': 'Write.'},
        'pages': [{'page_id': 'pg_missing', 'rotation': 0}]})
    assert result.status_code in (400, 404, 422), result.text
    assert count(app, Category) == before
    assert web.get('/api/prompts').json()['items'] == []


def test_revoked_credential_pending_cannot_apply(web, app, credential):
    proposal = propose(app, credential)
    assert web.post('/api/credentials/' + credential['id'] + '/revoke', json={}).status_code == 200
    result = decide(web, proposal)
    assert result.status_code in (200, 409), result.text
    assert web.get('/api/reviews/' + proposal['id']).json()['status'] in ('pending', 'conflict')
    assert count(app, Category) == 0


def test_foreign_credential_cannot_view_or_revise_proposal(web, app, credential):
    proposal = propose(app, credential)
    other = web.post('/api/credentials', json={'name': 'Other account', 'scopes': ['archive.read', 'proposals.write']}).json()
    with app.state.db.read() as session:
        with pytest.raises(DomainError) as denied:
            reviews.get_item(session, proposal['id'], 'mcp:' + other['id'])
        assert denied.value.code == 'permission_denied'
    with app.state.db.transaction() as session:
        with pytest.raises(DomainError):
            reviews.revise(session, proposal['id'], {'name': 'stolen'}, 1, 'mcp:' + other['id'])


def test_restart_preserves_pending_and_applied_without_get_replay(web, app, credential, settings):
    from fastapi.testclient import TestClient

    from backend.app.main import create_app
    pending = propose(app, credential, name='Remain pending', request_id='pending')
    applied = propose(app, credential, name='Applied once', request_id='applied')
    assert decide(web, applied).json()['status'] == 'applied'
    replacement = create_app(settings)
    with TestClient(replacement) as restarted:
        response = restarted.post('/api/auth/login', json={'username': web.test_username, 'password': web.test_password}, headers={'Origin': 'http://testserver'})
        assert response.status_code == 200
        for _ in range(3):
            assert restarted.get('/api/reviews/' + pending['id']).json()['status'] == 'pending'
            assert restarted.get('/api/reviews/' + applied['id']).json()['status'] == 'applied'
    assert count(app, Category) == count(app, ReviewDecision) == 1


def test_process_crash_before_commit_leaves_no_partial_formal_or_decision(web, app, credential, settings):
    proposal = propose(app, credential)
    code = '''
import os, json
from pathlib import Path
from backend.app.config import Settings
from backend.app.db.base import Database
from backend.app.domain.reviews import decide
settings=Settings(data_dir=Path(os.environ['FAULT_DATA']),public_origin='http://testserver')
db=Database(settings)
p=json.loads(os.environ['FAULT_PROPOSAL'])
with db.transaction() as s:
    decide(s,p['id'],p['revision'],p['effective_digest'],'approve','web:crash-test')
    s.flush()
    os._exit(71)
'''
    env = {**os.environ, 'FAULT_DATA': str(settings.data_dir), 'FAULT_PROPOSAL': json.dumps(proposal)}
    result = subprocess.run([sys.executable, '-c', code], env=env, check=False, capture_output=True, text=True)
    assert result.returncode == 71, result.stderr
    assert count(app, Category) == count(app, ReviewDecision) == 0
    assert web.get('/api/reviews/' + proposal['id']).json()['status'] == 'pending'
    assert decide(web, proposal).json()['status'] == 'applied'
    assert count(app, Category) == 1


def test_concurrent_versions_allocate_unique_numbers(web, app, submission, asset):
    from backend.app.domain import dispatch
    payload = {'attempt_id': submission['attempt_id'], 'parent_version_id': submission['version_id'],
               'pages': [{'page_id': asset['pages'][0]['page_id'], 'rotation': 0}], 'change_note': 'Concurrent revision'}
    def worker(_):
        with app.state.db.transaction() as session:
            return dispatch.apply(session, 'revision', payload, 'web:concurrent-revision')
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(worker, range(2)))
    assert outcomes[0]['version_id'] != outcomes[1]['version_id']
    versions = web.get('/api/attempts/' + submission['attempt_id']).json()['versions']
    assert [v['version_no'] for v in versions] == [1, 2, 3]
    assert all(v['parent_version_id'] == submission['version_id'] for v in versions[1:])


def test_process_crash_after_commit_retry_does_not_duplicate(web, app, credential, settings):
    proposal = propose(app, credential)
    code = '''
import os,json
from pathlib import Path
from backend.app.config import Settings
from backend.app.db.base import Database
from backend.app.domain.reviews import decide
settings=Settings(data_dir=Path(os.environ['FAULT_DATA']),public_origin='http://testserver')
db=Database(settings)
p=json.loads(os.environ['FAULT_PROPOSAL'])
with db.transaction() as s:
    decide(s,p['id'],p['revision'],p['effective_digest'],'approve','web:crash-after-commit')
os._exit(72)
'''
    result = subprocess.run([sys.executable, '-c', code], env={**os.environ, 'FAULT_DATA': str(settings.data_dir),
                            'FAULT_PROPOSAL': json.dumps(proposal)}, capture_output=True, text=True, check=False)
    assert result.returncode == 72, result.stderr
    assert decide(web, proposal).json()['status'] == 'applied'
    assert count(app, Category) == count(app, ReviewDecision) == 1

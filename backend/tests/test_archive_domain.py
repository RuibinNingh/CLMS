"""Archive identity, snapshots, evaluation rules and bounded reads."""
from copy import deepcopy


def evaluation(web, version_id, **changes):
    version = web.get('/api/versions/' + version_id).json()
    payload = {
        'schema_version': 1, 'version_id': version_id,
        'expected_manifest_hash': version['manifest_hash'],
        'expected_prompt_snapshot_hash': version['prompt_snapshot_hash'],
        'coverage': {'reviewed_page_ids': [p['page_id'] for p in version['manifest']], 'scope': 'full', 'limitations': []},
        'summary': 'Specific test feedback', 'strengths': ['Clear observation'], 'score': None,
        'issues': [], 'next_actions': [], 'commentary_markdown': '', 'declared_model': None,
    }
    return {**payload, **changes}


def test_empty_database_has_no_predefined_categories(web):
    assert web.get('/api/categories').json()['items'] == []
    assert web.get('/api/prompts').json()['items'] == []


def test_user_categories_normalization_scope_and_archive(web):
    first = web.post('/api/categories', json={'name': '  Ｅssay  ', 'language_scope': 'en', 'sort_order': 4})
    assert first.status_code == 200, first.text
    category = first.json()
    duplicate = web.post('/api/categories', json={'name': 'essay', 'language_scope': 'en'})
    assert duplicate.status_code == 409
    other = web.post('/api/categories', json={'name': 'essay', 'language_scope': 'zh'})
    assert other.status_code == 200
    result = web.post('/api/categories/' + category['id'], json={'expected_revision': 1, 'name': 'Observation', 'sort_order': -1})
    assert result.status_code == 200, result.text
    result = web.post('/api/categories/' + category['id'], json={'expected_revision': 2, 'archived': True})
    assert result.status_code == 200
    assert category['id'] not in {c['id'] for c in web.get('/api/categories?language=en').json()['items']}
    assert category['id'] in {c['id'] for c in web.get('/api/categories?include_archived=true').json()['items']}
    invalid = web.post('/api/prompts', json={'language': 'en', 'instructions': 'Write.', 'category_ids': [category['id']]})
    assert invalid.status_code in (400, 409, 422)


def test_attachment_only_prompt_without_transcription(web, asset):
    result = web.post('/api/prompts', json={'title': 'Attached prompt', 'language': 'zh', 'instructions': '',
        'materials': [{'page_id': asset['pages'][0]['page_id'], 'rotation': 0}]})
    assert result.status_code == 200, result.text
    assert result.json()['materials'][0]['asset_id'] == asset['id']


def test_rewriting_starts_new_attempt_and_revision_preserves_first(web, submission, asset):
    page = {'page_id': asset['pages'][0]['page_id'], 'rotation': 90}
    second = web.post('/api/submissions', json={'prompt_id': submission['prompt_id'], 'pages': [page]}).json()
    revised = web.post('/api/attempts/' + submission['attempt_id'] + '/versions', json={
        'parent_version_id': submission['version_id'], 'pages': [page], 'change_note': 'new draft'})
    assert revised.status_code == 200, revised.text
    attempt = web.get('/api/attempts/' + submission['attempt_id']).json()
    assert [v['version_no'] for v in attempt['versions']] == [1, 2]
    assert attempt['versions'][0]['manifest'][0]['rotation'] == 0
    assert attempt['versions'][1]['parent_version_id'] == submission['version_id']
    assert web.get('/api/attempts/' + second['attempt_id']).json()['versions'][0]['version_no'] == 1
    assert second['attempt_id'] != submission['attempt_id']


def test_prompt_change_does_not_change_attempt_snapshot(web, submission):
    before = web.get('/api/attempts/' + submission['attempt_id']).json()
    prompt = web.get('/api/prompts/' + submission['prompt_id']).json()
    result = web.post('/api/prompts/' + submission['prompt_id'], json={'expected_revision': prompt['revision'], 'instructions': 'Changed later',
        'rubric': {'max_score': 25, 'criteria': 'New rubric', 'aggregation': 'none', 'dimensions': []}})
    assert result.status_code == 200, result.text
    after = web.get('/api/attempts/' + submission['attempt_id']).json()
    assert after['snapshot_hash'] == before['snapshot_hash']
    assert after['prompt_snapshot'] == before['prompt_snapshot']


def test_manifest_cannot_be_overwritten(web, submission, asset):
    result = web.post('/api/versions/' + submission['version_id'], json={'manifest': []})
    assert result.status_code in (404, 405)
    before = web.get('/api/versions/' + submission['version_id']).json()
    assert len(before['manifest']) == 1
    assert web.put('/api/assets/' + asset['id'] + '/original', json={'bytes': 'overwrite'}).status_code in (404, 405)


def test_evaluation_null_score_and_structured_issue_kinds(web, submission):
    payload = evaluation(web, submission['version_id'])
    page_id = payload['coverage']['reviewed_page_ids'][0]
    payload['issues'] = [{'kind': kind, 'dimension': 'Clarity', 'location': {'page_id': page_id, 'description': 'Middle', 'bbox': None},
        'quote': None, 'reason': 'Evidence-based test reason', 'suggestion': 'Specific next step'} for kind in ('error', 'improvement', 'uncertain')]
    result = web.post('/api/evaluations', json=payload)
    assert result.status_code == 200, result.text
    record = web.get('/api/evaluations/' + result.json()['evaluation_id']).json()
    assert record['payload']['score'] is None
    assert {i['kind'] for i in record['payload']['issues']} == {'error', 'improvement', 'uncertain'}
    assert record['source'].startswith('web:')


def test_wrong_hash_page_and_full_coverage_rejected(web, submission):
    payload = evaluation(web, submission['version_id'])
    for changes in ({'expected_manifest_hash': '0' * 64}, {'expected_prompt_snapshot_hash': '0' * 64},
                    {'coverage': {'scope': 'full', 'reviewed_page_ids': ['pg_not_this_version'], 'limitations': []}}):
        result = web.post('/api/evaluations', json={**payload, **changes})
        assert result.status_code in (400, 409, 422), result.text
    assert web.get('/api/versions/' + submission['version_id']).json()['evaluations'] == []


def test_invalid_score_without_rubric_does_not_default_to_60(web, submission):
    payload = evaluation(web, submission['version_id'])
    payload['score'] = {'value': 26, 'max_value': 25, 'rubric_snapshot': {'max_score': 25, 'criteria': 'test', 'aggregation': 'none', 'dimensions': []}, 'dimensions': []}
    assert web.post('/api/evaluations', json=payload).status_code in (400, 409, 422)
    assert web.get('/api/versions/' + submission['version_id']).json()['evaluations'] == []


def test_evaluation_revision_keeps_historical_payload(web, submission):
    first = web.post('/api/evaluations', json=evaluation(web, submission['version_id'])).json()
    next_payload = evaluation(web, submission['version_id'], summary='Revised explicit feedback', supersedes_id=first['evaluation_id'])
    second = web.post('/api/evaluations', json=next_payload)
    assert second.status_code == 200, second.text
    records = web.get('/api/versions/' + submission['version_id']).json()['evaluations']
    assert len(records) == 2
    assert records[0]['payload']['summary'] == 'Specific test feedback'
    assert records[1]['supersedes_id'] == first['evaluation_id']


def test_partial_evaluation_does_not_complete_manuscript(web, submission):
    version = web.get('/api/versions/' + submission['version_id']).json()
    payload = evaluation(web, submission['version_id'], coverage={'reviewed_page_ids': [version['manifest'][0]['page_id']], 'scope': 'partial', 'limitations': ['Only partial review']})
    assert web.post('/api/evaluations', json=payload).status_code == 200
    pending = web.get('/api/prompts?status=pending').json()['items']
    assert submission['prompt_id'] in {p['id'] for p in pending}
    assert submission['prompt_id'] not in {p['id'] for p in web.get('/api/prompts?status=evaluated').json()['items']}


def test_paginated_listing_stays_bounded(web):
    ids = set()
    for i in range(135):
        result = web.post('/api/prompts', json={'title': f'Paged {i:03d}', 'language': 'en', 'instructions': 'Write about a place.'})
        assert result.status_code == 200, result.text
        ids.add(result.json()['id'])
    seen, cursor = set(), None
    while True:
        response = web.get('/api/prompts', params={'limit': 17, **({'cursor': cursor} if cursor else {})}).json()
        assert 1 <= len(response['items']) <= 17
        for item in response['items']:
            assert 'attempts' not in item and 'materials' not in item and 'evaluations' not in item
            assert item['id'] not in seen
            seen.add(item['id'])
        cursor = response['next_cursor']
        if cursor is None:
            break
    assert seen == ids
    assert web.get('/api/prompts?limit=100000').status_code in (400, 422)


def test_scores_use_frozen_rubric_and_explicit_sum(web, asset):
    rubric = {'max_score': 10, 'criteria': 'Two explicit dimensions', 'aggregation': 'sum',
              'dimensions': [{'name': 'Content', 'max_score': 6}, {'name': 'Language', 'max_score': 4}]}
    created = web.post('/api/submissions', json={'prompt': {'language': 'en', 'instructions': 'Write.', 'rubric': rubric},
                         'pages': [{'page_id': asset['pages'][0]['page_id'], 'rotation': 0}]}).json()
    score = {'value': 8, 'max_value': 10, 'rubric_snapshot': rubric,
             'dimensions': [{'name': 'Content', 'value': 5, 'max_value': 6}, {'name': 'Language', 'value': 3, 'max_value': 4}]}
    payload = evaluation(web, created['version_id'], score=score)
    invalid = deepcopy(payload)
    invalid['score']['value'] = 7
    assert web.post('/api/evaluations', json=invalid).status_code in (400, 409, 422)
    invalid = deepcopy(payload)
    invalid['score']['max_value'] = 60
    assert web.post('/api/evaluations', json=invalid).status_code in (400, 409, 422)
    valid = web.post('/api/evaluations', json=payload)
    assert valid.status_code == 200, valid.text


def test_issue_location_bbox_and_foreign_version_page_rejected(web, submission, asset, image_bytes):
    new_upload = web.post('/api/assets', files={'file': ('different.png', image_bytes, 'image/png')}).json()
    second = web.post('/api/submissions', json={'prompt_id': submission['prompt_id'],
                    'pages': [{'page_id': new_upload['pages'][0]['page_id'], 'rotation': 0}]}).json()
    assert second['version_id'] != submission['version_id']
    payload = evaluation(web, submission['version_id'])
    base_issue = {'kind': 'error', 'dimension': 'Reference', 'location': {'page_id': asset['pages'][0]['page_id'], 'description': 'Middle', 'bbox': None},
                  'reason': 'A test reason', 'suggestion': 'A test suggestion'}
    invalid = deepcopy(base_issue)
    invalid['location']['bbox'] = [-0.1, 0, 1.1, 1]
    assert web.post('/api/evaluations', json={**payload, 'issues': [invalid]}).status_code in (400, 409, 422)
    invalid = deepcopy(base_issue)
    invalid['location']['page_id'] = new_upload['pages'][0]['page_id']
    assert web.post('/api/evaluations', json={**payload, 'issues': [invalid]}).status_code in (400, 409, 422)
    assert web.get('/api/versions/' + submission['version_id']).json()['evaluations'] == []


def test_list_summaries_do_not_expand_full_documents_or_materials(web, asset):
    result = web.post('/api/prompts', json={'language': 'en', 'instructions': 'long instruction ' * 1000,
        'requirements': 'Private detailed requirements', 'source_note': 'Private source note',
        'rubric': {'max_score': 20, 'criteria': 'Full scoring rubric', 'aggregation': 'none', 'dimensions': []},
        'materials': [{'page_id': asset['pages'][0]['page_id'], 'rotation': 0}]})
    assert result.status_code == 200, result.text
    summary = web.get('/api/prompts').json()['items'][0]
    assert len(summary['instructions']) <= 240
    assert not {'requirements', 'source_note', 'rubric', 'materials', 'attempts', 'evaluations'} & summary.keys()
    full = web.get('/api/prompts/' + result.json()['id']).json()
    assert len(full['instructions']) > 240
    assert full['materials']

"""Official ClientSession over actual Streamable HTTP, human review, and essay workflow."""
import asyncio
import base64
import io
import json
import os
import shutil
import sys
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(__file__))
from clms import creation, essays, ledger, runtime_history, sessions  # noqa: E402
from clms.mcp import keys  # noqa: E402
from clms.mcp.server import start_background  # noqa: E402
from clms.server import make_server  # noqa: E402
from test_core import _group_a, seed_types  # noqa: E402


def image_bytes(index):
    from PIL import Image
    buffer = io.BytesIO()
    Image.new('RGB', (80, 120), (240 - index * 10, 245, 220)).save(buffer, format='PNG')
    return buffer.getvalue()


async def exercise(vault, service, web, fixtures):
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    writer = keys.create_key(vault, "ChatGPT 开发测试", scopes=list(keys.SCOPES))
    reader = keys.create_key(vault, "只读", scopes=["clms:read"])
    essay_reader = keys.create_key(vault, "仅正文", scopes=["essay:read"])
    ids, prompt, attempt, version, images = fixtures

    def value(result):
        assert not result.isError, [getattr(content, 'text', '') for content in result.content]
        return result.structuredContent or json.loads(result.content[0].text)

    async with httpx.AsyncClient(headers={"Authorization": "Bearer " + writer["secret"]}, timeout=20) as client:
        async with streamable_http_client(service.url, http_client=client) as (read, write, _):
            async with ClientSession(read, write) as session:
                initialized = await session.initialize()
                assert initialized.serverInfo.name == 'CLMS'
                discovered = await session.list_tools()
                names = {tool.name for tool in discovered.tools}
                assert 'create_review_session' in names and 'get_essay_image' in names
                assert not any('approve' in name or 'delete' in name or 'read_file' == name for name in names)
                assert all(tool.inputSchema.get('additionalProperties') is False for tool in discovered.tools)
                for tool in discovered.tools:
                    if not tool.annotations.readOnlyHint:
                        assert 'request_id' in tool.inputSchema['required']

                taxonomy = value(await session.call_tool('list_taxonomy', {}))
                assert 'modern' in taxonomy['qtypes']
                found = value(await session.call_tool('search_items', {'query': '灯'}))
                assert found['total'] >= 1
                item = value(await session.call_tool('get_item', {'item_id': ids[0]}))
                assert item['answer']
                material = value(await session.call_tool('get_material', {'material_id': item['material_id']}))
                assert material['text']
                value(await session.call_tool('get_overview', {}))
                recommendation = value(await session.call_tool('get_recommendations', {'minutes': 30, 'genres': ['modern']}))
                assert recommendation['items']

                # Proposal stays pending until an actual human Web request approves.
                request = {'item_ids': ids, 'minutes': 30, 'title': 'MCP现代文复习', 'request_id': 'same-id'}
                pending = value(await session.call_tool('create_review_session', request))
                assert pending['status'] == 'pending_confirmation'
                assert not sessions.list_sessions(vault)
                repeated = value(await session.call_tool('create_review_session', request))
                assert repeated['id'] == pending['id']
                conflict = await session.call_tool('create_review_session', dict(request, minutes=31))
                assert conflict.isError and 'request_conflict' in conflict.content[0].text
                assert (await session.call_tool('approve_operation', {'operation_id': pending['id']})).isError
                async with httpx.AsyncClient(headers={'Origin': web}) as human:
                    response = await human.post(web + '/api/ai-review/decide', json={'id': pending['id'], 'expected_revision': 1, 'decision': 'approve'})
                    response.raise_for_status(); applied = response.json()['item']
                    response = await human.post(web + '/api/ai-review/decide', json={'id': pending['id'], 'expected_revision': 1, 'decision': 'approve'})
                    response.raise_for_status()
                assert len(sessions.list_sessions(vault)) == 1
                sid = applied['result']['id']
                state = value(await session.call_tool('get_operation', {'operation_id': pending['id']}))
                assert state['result']['id'] == sid
                assert value(await session.call_tool('get_session', {'session_id': sid}))['id'] == sid

                # Same ID is independently valid for another tool; item/material writes remain proposals.
                question = value(await session.call_tool('propose_item_update', {'item_id': ids[0], 'changes': {'blank_lines': 9}, 'request_id': 'same-id'}))
                assert question['status'] == 'pending_confirmation' and question['id'] != pending['id']
                material_op = value(await session.call_tool('propose_material_update', {'material_id': item['material_id'], 'changes': {'title': '另一个标题'}, 'request_id': 'material-one'}))
                assert material_op['status'] == 'pending_confirmation'

                draft_op = value(await session.call_tool('create_draft', {'genre': 'modern', 'name': 'MCP暂存草稿', 'request_id': 'draft-one'}))
                assert draft_op['status'] == 'applied'
                did = draft_op['result']['id']
                draft = value(await session.call_tool('get_draft', {'draft_id': did}))
                patched = value(await session.call_tool('update_draft', {'draft_id': did, 'expected_revision': draft['revision'],
                    'groups': [{'genre': 'modern', 'material': {'title': '手工暂存', 'text': '这份材料仅保存在未入库草稿里。'},
                                'items': [{'stem': '概括材料', 'answer': '略', 'blank_lines': 3}]}], 'request_id': 'draft-edit'}))
                assert patched['status'] == 'applied'

                # ChatGPT essay workflow consumes formal text and a version-bound native image.
                prompts = value(await session.call_tool('list_essay_prompts', {'query': '成长'}))
                assert prompts['prompts'][0]['id'] == prompt['id']
                assert value(await session.call_tool('get_essay_prompt', {'prompt_id': prompt['id']}))['attempt_count'] == 1
                current_attempt = value(await session.call_tool('get_essay_attempt', {'attempt_id': attempt['id']}))
                assert current_attempt['version_count'] == 1 and current_attempt['modification_count'] == 0
                formal = value(await session.call_tool('get_essay_version', {'version_id': version['id']}))
                assert formal['text'] == '我以经长大。第二段转折太突然。下一稿要把结尾写清楚。'
                native = await session.call_tool('get_essay_image', {'version_id': version['id'], 'image_index': 1})
                assert not native.isError and len(native.content) == 1 and native.content[0].type == 'image'
                assert base64.b64decode(native.content[0].data) == images[1]

                evaluation_args = {'version_id': version['id'], 'total_score': 47, 'summary': '有细节，结构仍需调整。',
                    'strengths': ['描写具体'], 'issues': ['第二段转折太突然'], 'suggestions': ['重点处理第二段和结尾'],
                    'evaluator': 'ChatGPT', 'model': 'external-test', 'request_id': 'essay-evaluate'}
                evaluation = value(await session.call_tool('append_essay_evaluation', evaluation_args))
                assert evaluation['status'] == 'applied'
                again = value(await session.call_tool('append_essay_evaluation', evaluation_args))
                assert again['id'] == evaluation['id']
                bad = await session.call_tool('append_essay_evaluation', dict(evaluation_args, total_score=61, request_id='bad-score'))
                assert bad.isError
                note = value(await session.call_tool('append_essay_note', {'attempt_id': attempt['id'], 'version_id': version['id'],
                    'text': '第二段转折太突然，下一稿重点处理第二段和结尾。', 'request_id': 'essay-note'}))
                assert note['status'] == 'applied'
                classification = value(await session.call_tool('create_essay_classification', {'name': '结尾突兀', 'request_id': 'free-class'}))
                assert classification['status'] == 'applied'
                tagged = value(await session.call_tool('set_essay_classifications', {'target_type': 'version', 'target_id': version['id'],
                    'names': ['成长', '细节描写'], 'request_id': 'free-tag'}))
                assert tagged['status'] == 'applied'
                historical = value(await session.call_tool('list_essay_evaluations', {'version_id': version['id']}))
                assert len(historical['evaluations']) == 1 and historical['evaluations'][0]['total_score'] == 47
                assert len(essays.attempt_detail(vault, attempt['id'])['notes']) == 1
                second = essays.create_version(vault, attempt['id'], [{'data': base64.b64encode(images[0]).decode()}])
                refreshed = value(await session.call_tool('get_essay_attempt', {'attempt_id': attempt['id']}))
                assert refreshed['version_count'] == 2 and refreshed['modification_count'] == 1
                assert len(essays.version_detail(vault, version['id'])['evaluations']) == 1
                assert essays.version_detail(vault, second['id'])['evaluations'] == []
                assert value(await session.call_tool('get_essay_version', {'version_id': second['id']}))['text'] == ''
                unconfirmed = await session.call_tool('append_essay_evaluation', dict(evaluation_args, version_id=second['id'], request_id='unconfirmed-score'))
                assert unconfirmed.isError and essays.version_detail(vault, second['id'])['evaluations'] == []

                # Web refuses MCP credentials before lifecycle or approval routes.
                async with httpx.AsyncClient(headers={'Authorization': 'Bearer ' + writer['secret'], 'Origin': web}) as outsider:
                    response = await outsider.post(web + '/api/ai-review/decide', json={'id': question['id'], 'expected_revision': 1, 'decision': 'approve'})
                    assert response.status_code == 403
                    response = await outsider.get(web + '/api/mcp/keys')
                    assert response.status_code == 403

    for identity, expected, denied in ((reader, 'get_item', 'create_review_session'), (essay_reader, 'get_essay_version', 'get_essay_image')):
        async with httpx.AsyncClient(headers={'Authorization': 'Bearer ' + identity['secret']}, timeout=10) as client:
            async with streamable_http_client(service.url, http_client=client) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize(); tools = {tool.name for tool in (await session.list_tools()).tools}
                    assert expected in tools and denied not in tools
                    arguments = {'item_ids': ids, 'request_id': 'denied'} if denied == 'create_review_session' else {'version_id': version['id']}
                    rejected = await session.call_tool(denied, arguments)
                    assert rejected.isError and 'forbidden' in rejected.content[0].text

    # Every protocol request reauthenticates; revoke also invalidates initialized sessions.
    async with httpx.AsyncClient(headers={'Authorization': 'Bearer ' + reader['secret']}, timeout=10) as client:
        async with streamable_http_client(service.url, http_client=client) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                await session.list_tools()
                keys.revoke_key(vault, reader['key_id'])
                response = await client.post(service.url, json={'jsonrpc': '2.0', 'id': 99, 'method': 'tools/list'})
                assert response.status_code == 401
    async with httpx.AsyncClient() as unauthenticated:
        assert (await unauthenticated.post(service.url, json={})).status_code == 401
        assert (await unauthenticated.post(service.url + '?key=forbidden-url-credential', json={})).status_code == 404
        response = await unauthenticated.post(service.url, headers={'Authorization': 'Bearer ' + writer['secret'], 'Host': 'evil.example'}, json={})
        assert response.status_code == 421

    rows = runtime_history.list_records(vault, {'source': 'mcp', 'limit': 100})['items']
    encoded = json.dumps(rows, ensure_ascii=False)
    assert writer['secret'] not in encoded and '第二段转折太突然' not in encoded and 'data:image' not in encoded
    assert any(row['result'].get('operation_id') or row['result'].get('id', '').startswith('op_') for row in rows)
    assert ledger.verify_ledger(vault)['ok']


def run():
    vault = tempfile.mkdtemp(prefix='clms-mcp-e2e-')
    seed_types(vault)
    ids = creation.commit_draft(vault, {'id': 'D-protocol', 'images': []}, _group_a())['item_ids']
    prompt = essays.create_prompt(vault, '在成长中学会珍惜', '请写一篇完整作文。', '不少于600字。')
    attempt = essays.create_attempt(vault, prompt['id'])
    images = [image_bytes(index) for index in range(3)]
    version = essays.create_version(vault, attempt['id'], [{'data': base64.b64encode(data).decode()} for data in images])
    version = essays.correct_version(vault, version['id'], '我以经长大。第二段转折太突然。下一稿要把结尾写清楚。', version['revision'])
    version = essays.confirm_version(vault, version['id'], revision=version['revision'])
    webserver = make_server(vault, '127.0.0.1', 0)
    threading.Thread(target=webserver.serve_forever, daemon=True).start()
    web = f'http://127.0.0.1:{webserver.server_address[1]}'
    service = None
    try:
        service = start_background(vault, 0, web_url=web)
        asyncio.run(exercise(vault, service, web, (ids, prompt, attempt, version, images)))
        print('e2e_mcp: 官方SDK真实协议 / Key发现与实时授权 / 幂等冲突 / 网页审核仅创建一次 / 草稿 / 作文图文与47分评价笔记分类 / 旧稿保留 / 脱敏全部通过')
    finally:
        if service:
            service.stop()
        webserver.shutdown(); webserver.server_close(); shutil.rmtree(vault, ignore_errors=True)


if __name__ == '__main__':
    run()

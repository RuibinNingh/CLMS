"""Real browser integration: shared review, MCP results, historical links and settings."""
import asyncio
import base64
import concurrent.futures
import io
import json
import os
import shutil
import sys
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.dirname(__file__)]
from clms import ai_review, creation, essays, ledger, sessions
from clms.mcp import keys
from clms.mcp.server import start_background
from clms.server import make_server
from test_core import _group_a, seed_types


async def external(vault, service, ids, attempt_id, version_id):
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    key = keys.create_key(vault, '外部验收', list(keys.SCOPES))
    async with httpx.AsyncClient(headers={'Authorization': 'Bearer ' + key['secret']}) as client:
        async with streamable_http_client(service.url, http_client=client) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                def value(result):
                    assert not result.isError, result
                    return result.structuredContent or json.loads(result.content[0].text)
                pending = value(await session.call_tool('create_review_session', {
                    'item_ids': ids, 'minutes': 30, 'title': 'MCP30分钟现代文复习', 'request_id': 'browser-session'}))
                assert pending['status'] == 'pending_confirmation' and not sessions.list_sessions(vault)
                assert (await session.call_tool('approve_operation', {'operation_id': pending['id']})).isError
                formal = value(await session.call_tool('get_essay_version', {'version_id': version_id}))
                assert formal['text'] == '我以经长大。转折太突然，结尾需要呼应。'
                value(await session.call_tool('append_essay_evaluation', {'version_id': version_id,
                    'total_score': 47, 'summary': '描写细致，结构需要调整。', 'issues': ['转折太突然'],
                    'suggestions': ['处理第二段和结尾'], 'request_id': 'browser-47', 'evaluator': 'ChatGPT'}))
                value(await session.call_tool('append_essay_note', {'attempt_id': attempt_id, 'version_id': version_id,
                    'text': '下一稿重点处理第二段和结尾。', 'request_id': 'browser-note'}))
                return pending['id'], key['secret']


async def operation_result(service, secret, operation_id):
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    async with httpx.AsyncClient(headers={'Authorization': 'Bearer ' + secret}) as client:
        async with streamable_http_client(service.url, http_client=client) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool('get_operation', {'operation_id': operation_id})
                assert not result.isError
                return result.structuredContent or json.loads(result.content[0].text)


def run():
    from PIL import Image
    from playwright.sync_api import sync_playwright
    vault = tempfile.mkdtemp(prefix='clms-upgrade-browser-')
    shots = '/tmp/clms-upgrade-shots'
    os.makedirs(shots, exist_ok=True)
    seed_types(vault)
    ids = creation.commit_draft(vault, {'id': 'D-upgrade', 'images': []}, _group_a())['item_ids']
    prompt = essays.create_prompt(vault, '那一刻，我长大了', '写一篇完整作文。')
    attempt = essays.create_attempt(vault, prompt['id'])
    image = io.BytesIO(); Image.new('RGB', (100, 150), 'white').save(image, format='PNG')
    image_data = base64.b64encode(image.getvalue()).decode()
    version = essays.create_version(vault, attempt['id'], [{'data': image_data}] * 3)
    version = essays.correct_version(vault, version['id'], '我以经长大。转折太突然，结尾需要呼应。', version['revision'])
    version = essays.confirm_version(vault, version['id'], revision=version['revision'])
    server = make_server(vault, port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{server.server_address[1]}'
    service = None
    errors = []
    try:
        service = start_background(vault, 0, web_url=base)
        operation_id, external_key = asyncio.run(external(vault, service, ids, attempt['id'], version['id']))
        with sync_playwright() as p:
            browser = p.chromium.launch()
            pg = browser.new_page(viewport={'width': 1600, 'height': 1000})
            pg.on('pageerror', lambda e: errors.append(str(e)))
            pg.goto(base + '/#/audit?id=' + operation_id)
            pg.wait_for_selector('.workspace__detail')
            assert pg.locator('#panel-audit .workspace__detail').inner_text().find('MCP') >= 0
            assert pg.locator('.audit__question').count() == len(ids)
            assert '30 分钟' in pg.locator('#panel-audit .workspace__detail').inner_text()
            pg.locator('[data-action="audit.decide"][data-arg="approve"]').click()
            pg.wait_for_selector('.workspace__detail:has-text("已完成")')
            assert len(sessions.list_sessions(vault)) == 1
            sid = sessions.list_sessions(vault)[0]['id']
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                observed = executor.submit(lambda: asyncio.run(operation_result(service, external_key, operation_id))).result(timeout=20)
            assert observed['status'] == 'applied' and observed['result']['id'] == sid
            pg.screenshot(path=shots + '/audit-session.png', full_page=True)
            pg.get_by_role('link', name='打开已创建复习').click()
            pg.wait_for_selector('.rv-print-stage')
            assert sid in pg.url

            # Human revision retains request scope and applies once.
            proposal = ai_review.propose(vault, 'assistant', 'item.update', 'browser-edit', {
                'item_id': ids[0], 'changes': {'answer': '拟修改答案'}})
            pg.goto(base + '/#/audit?id=' + proposal['id'])
            pg.wait_for_selector('textarea[name="answer"]')
            pg.fill('textarea[name="answer"]', '人工修订后的参考答案')
            pg.get_by_role('button', name='保存修订').click()
            pg.wait_for_function("document.querySelector('.workspace__detail').textContent.includes('revision 2')")
            pg.click('[data-action="audit.decide"][data-arg="approve"]')
            pg.wait_for_selector('.workspace__detail:has-text("已完成")')
            assert sessions.view(vault, sid)['items'][0]['answer'] == '人工修订后的参考答案'
            assert ai_review.get(vault, proposal['id'])['status'] == 'applied'
            rejected = ai_review.propose(vault, 'assistant', 'material.update', 'browser-reject', {
                'material_id': sessions.view(vault, sid)['items'][0]['material_id'], 'changes': {'title': '不采用的标题'}})
            pg.goto(base + '/#/audit?id=' + rejected['id'])
            pg.wait_for_selector('[data-action="audit.decide"][data-arg="reject"]')
            pg.click('[data-action="audit.decide"][data-arg="reject"]')
            pg.wait_for_selector('.workspace__detail:has-text("已拒绝")')
            assert ai_review.get(vault, rejected['id'])['status'] == 'rejected'

            # MCP append-only evaluation/note displayed on their original version.
            pg.goto(base + '/#/essays?version=' + version['id'])
            pg.wait_for_selector('.es-final')
            assert '47' in pg.locator('#panel-essays').inner_text()
            assert '下一稿重点处理第二段和结尾' in pg.locator('#panel-essays').inner_text()
            second = essays.create_version(vault, attempt['id'], [{'data': image_data}])
            pg.reload()
            pg.wait_for_function("document.querySelector('#panel-essays').textContent.includes('修改 1 次')")
            assert len(essays.version_detail(vault, version['id'])['evaluations']) == 1
            assert essays.version_detail(vault, second['id'])['evaluations'] == []

            pg.goto(base + '/#/history')
            pg.wait_for_selector('[data-action="hist.open"]')
            pg.fill('[aria-label="操作类型"]', 'essay.evaluation.add')
            pg.press('[aria-label="操作类型"]', 'Tab')
            pg.wait_for_function("document.querySelectorAll('[data-action=\"hist.open\"]').length === 1")
            pg.click('[data-action="hist.open"]')
            pg.wait_for_selector('a:has-text("打开作文版本")')
            link = pg.get_by_role('link', name='打开作文版本')
            assert version['id'] in link.get_attribute('href')
            link.click(); pg.wait_for_selector('.es-final')
            assert version['id'] in pg.url and '47' in pg.locator('#panel-essays').inner_text()

            pg.goto(base + '/#/history')
            pg.click('[data-action="hist.tab"][data-arg="runtime"]')
            pg.select_option('[aria-label="来源"]', 'mcp')
            pg.fill('[aria-label="操作类型"]', 'session.create')
            pg.press('[aria-label="操作类型"]', 'Tab')
            pg.wait_for_selector('[data-action="hist.open"]')
            rows = pg.locator('[data-action="hist.open"]')
            found = False
            for n in range(rows.count()):
                rows.nth(n).click()
                pg.wait_for_selector('.workspace__detail')
                if pg.get_by_role('link', name='打开审核').count():
                    assert operation_id in pg.get_by_role('link', name='打开审核').get_attribute('href')
                    session_link = pg.get_by_role('link', name='打开已创建复习')
                    if session_link.count():
                        assert sid in session_link.get_attribute('href')
                    found = True; break
            assert found
            pg.screenshot(path=shots + '/history-runtime.png', full_page=True)
            pg.get_by_role('link', name='打开审核').click()
            pg.wait_for_selector('.workspace__detail:has-text("已完成")')
            assert sid in pg.locator('#panel-audit .workspace__detail').inner_text()

            # Partition keyboard navigation and single-display keys.
            pg.goto(base + '/#/settings')
            first = pg.locator('[data-setting-tab="appearance"]'); first.click(); first.focus()
            pg.keyboard.press('ArrowRight')
            assert pg.locator('[data-setting-tab="review"]').get_attribute('aria-selected') == 'true'
            pg.keyboard.press('End')
            assert pg.locator('[data-setting-tab="service"]').get_attribute('aria-selected') == 'true'
            pg.click('[data-setting-tab="mcp"]')
            pg.fill('form[data-submit="set.createMcpKey"] input[name="name"]', '浏览器只读Key')
            pg.click('form[data-submit="set.createMcpKey"] button.btn--primary')
            pg.wait_for_selector('[data-mcp-secret]')
            secret = pg.input_value('[data-mcp-secret]')
            assert secret.startswith('clms_mcp_')
            pg.get_by_role('button', name='我已保存，关闭').click()
            assert pg.locator('[data-mcp-secret]').count() == 0
            key_row = pg.locator('.set__key:has-text("浏览器只读Key")')
            key_row.get_by_role('button', name='编辑权限').click()
            form = key_row.locator('form[data-submit="set.updateMcp"]')
            form.locator('input[value="session:create"]').check()
            form.get_by_role('button', name='保存权限').click()
            pg.wait_for_function("document.querySelector('#panel-settings').textContent.includes('session:create')")
            metadata = next(k for k in keys.list_keys(vault) if k['name'] == '浏览器只读Key')
            assert 'session:create' in metadata['scopes']
            assert 'secret' not in metadata
            key_row.get_by_role('button', name='吊销').click()
            pg.wait_for_selector('.set__key:has-text("浏览器只读Key"):has-text("已吊销")')
            assert next(k for k in keys.list_keys(vault) if k['key_id'] == metadata['key_id'])['revoked_at']
            pg.screenshot(path=shots + '/settings-mcp.png', full_page=True)
            pg.set_viewport_size({'width': 390, 'height': 844})
            pg.screenshot(path=shots + '/settings-mobile.png', full_page=True)
            assert pg.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
            pg.goto(base + '/#/history')
            pg.wait_for_selector('[data-action="hist.open"]')
            pg.screenshot(path=shots + '/history-mobile.png', full_page=True)
            assert pg.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')

            # Delayed responses must not repaint a page after unmount.
            def delay(route):
                import time
                time.sleep(0.4); route.continue_()
            pg.route('**/api/history*', delay)
            pg.goto(base + '/#/dashboard')
            pg.evaluate("location.hash = '#/history'")
            pg.wait_for_timeout(50)
            pg.evaluate("location.hash = '#/settings'")
            pg.wait_for_selector('[data-setting-tab]')
            before = pg.locator('#panel-history').inner_html()
            pg.wait_for_timeout(600)
            assert pg.locator('#panel-history').inner_html() == before
            assert not errors, errors
            browser.close()
        assert ledger.verify_ledger(vault)['ok']
        print('e2e_upgrade: MCP提案→浏览器审核/Session、修订/拒绝、47分旧版本评价与笔记、分轨历史跳转、Key创建/权限/吊销、键盘、390px、卸载后回包全部通过')
    finally:
        if service: service.stop()
        server.shutdown(); server.server_close(); shutil.rmtree(vault, ignore_errors=True)


if __name__ == '__main__':
    run()

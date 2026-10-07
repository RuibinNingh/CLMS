"""Real HTTP + Chromium global assistant review, persistence and mobile/unmount checks."""

import argparse
import json
import os
import shutil
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(__file__))

import fake_ai
from clms import ai_review, assistant, assistant_store, creation, draft_schema, projections
from clms.common import save_config
from clms.server import make_server


def run(shots=None):
    from playwright.sync_api import sync_playwright
    vault = tempfile.mkdtemp(prefix="clms-assistant-browser-")
    ai = fake_ai.start(0)
    save_config(vault, {"assistant_enabled": True, "ai_base_url": f"http://127.0.0.1:{ai.server_address[1]}/v1",
                       "ai_api_key": "fake-secret", "ai_model": "fake"})
    seeded = creation.commit_draft(vault, {"id": "D-e2e", "images": []}, draft_schema.normalize_groups([{
        "genre": "modern", "material": {"title": "街灯", "text": "旧街的灯光照亮放学回家的孩子们。"},
        "items": [{"stem": "灯光的作用是什么？", "answer": "象征温情。"}, {"stem": "结尾如何照应开头？", "answer": "灯光首尾照应。"}]}]))
    server = make_server(vault, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    errors = []
    if shots:
        os.makedirs(shots, exist_ok=True)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(base + "/#/assistant")
            page.wait_for_selector('#global-assistant-input')
            page.fill('#global-assistant-input', "给我创建一份 30 分钟的现代文复习")
            page.press('#global-assistant-input', 'Enter')
            page.wait_for_selector('.ga-review [data-action="ga.decide"]', timeout=20000)
            assert len(projections.get_state(vault).sessions) == 0
            assert page.locator('.ga-think').count() > 0
            assert page.locator('.ga-tool[data-tool="get_recommendations"]').count() == 1
            if shots:
                page.screenshot(path=os.path.join(shots, 'assistant-desktop-pending.png'))
            operation_id = page.locator('.ga-review').get_attribute('data-operation')
            # The center revises the same operation while the original assistant waits.
            page.goto(base + f"/#/audit?id={operation_id}")
            page.wait_for_selector('textarea[name="minutes"]')
            page.fill('textarea[name="minutes"]', '35')
            page.click('[data-submit="audit.revise"] button')
            page.wait_for_function("document.querySelector('.workspace__detail')?.innerText.includes('revision 2')")
            page.click('[data-action="audit.decide"][data-arg="approve"]')
            page.wait_for_function("document.querySelector('.workspace__detail')?.innerText.includes('已执行')")
            assert len(projections.get_state(vault).sessions) == 1
            conversation_id = ai_review.get(vault, operation_id)["actor"]["conversation_id"]
            page.goto(base + f"/#/assistant?conversation={conversation_id}")
            page.wait_for_selector('.ga-message:has-text("已创建 35 分钟")', timeout=20000)
            page.reload()
            page.wait_for_selector('.ga-message:has-text("已创建 35 分钟")')
            assert len(projections.get_state(vault).sessions) == 1
            page.set_viewport_size({"width": 375, "height": 812})
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            page.click('[data-action="ga.rail"]')
            page.wait_for_selector('.ga[data-rail="open"]')
            page.keyboard.press('Escape')
            page.wait_for_selector('.ga[data-rail="closed"]')
            if shots:
                page.screenshot(path=os.path.join(shots, 'assistant-mobile-completed.png'))
            page.click('[data-action="ga.rail"]')
            page.click('[data-action="ga.new"]')
            message = '[tool:propose_item_update] ' + json.dumps({"item_id": seeded["item_ids"][0], "changes": {"answer": "人工批准后的新答案"}}, ensure_ascii=False)
            page.fill('#global-assistant-input', message)
            page.press('#global-assistant-input', 'Enter')
            page.wait_for_selector('.ga-review [data-action="ga.decide"]', timeout=20000)
            operation_id = page.locator('.ga-review').get_attribute('data-operation')
            # Move away with an HTTP event poll outstanding, then approve directly.
            page.goto(base + '/#/history')
            page.wait_for_selector('#panel-history.is-active .workspace')
            frozen = page.locator('#panel-assistant').inner_html()
            row = ai_review.get(vault, operation_id)
            ai_review.decide(vault, operation_id, row["revision"], 'approve', {"kind": "human", "channel": "center"})
            page.wait_for_timeout(1000)
            assert not page.locator('#panel-assistant').is_visible()
            assert page.locator('#panel-assistant').inner_html() == frozen
            assert page.locator('#panel-history.is-active .workspace').count() == 1
            assert projections.get_state(vault).items[seeded["item_ids"][0]]["answer"] == "人工批准后的新答案"
            assert not errors, errors
            browser.close()
        print('assistant e2e：桌面审核修订/批准、Session仅一次、重开持久化、手机、键盘与卸载后回包均通过')
    finally:
        runtime = assistant.get_runtime(vault)
        if runtime.active:
            runtime.stop(runtime.active.id)
            end = time.monotonic() + 5
            while runtime.active and time.monotonic() < end:
                time.sleep(0.02)
        server.shutdown()
        server.server_close()
        ai.shutdown()
        ai.server_close()
        assistant._RUNTIMES.pop(os.path.abspath(vault), None)
        projections.reset_state(vault)
        shutil.rmtree(vault, ignore_errors=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--shots')
    run(parser.parse_args().shots)

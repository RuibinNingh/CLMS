"""真实浏览器与真实本机 HTTP：完整作文、多页一稿、OCR失败重试、校对、版本评价。"""

import argparse
import http.server
import json
import os
import shutil
import sys
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from clms import essays, ledger, projections  # noqa: E402
from clms.common import save_config  # noqa: E402
from clms.server import make_server  # noqa: E402

OCR_TEXT = "成长的路上\n那天，母亲陪我走过长街，我在路边看到【存疑：树/术】。\n我终于懂得，成涨不只是年龄的增加。"


class OCRModel(http.server.BaseHTTPRequestHandler):
    fail_once = True
    requests = []

    def log_message(self, *_):
        pass

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).requests.append(request)
        if type(self).fail_once:
            type(self).fail_once = False
            self.send_response(503)
            self.end_headers()
            self.wfile.write(b'fake OCR unavailable; retry')
            return
        content = json.dumps({"text": OCR_TEXT, "uncertainties": [{"page": 2, "text": "树/术", "reason": "字迹不清"}]}, ensure_ascii=False)
        response = json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": content}}],
                               "usage": {"prompt_tokens": 200, "completion_tokens": 100}}, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)


def run(shots=None):
    from playwright.sync_api import sync_playwright
    vault = tempfile.mkdtemp(prefix="clms-essay-ui-")
    OCRModel.fail_once, OCRModel.requests = True, []
    model = http.server.ThreadingHTTPServer(("127.0.0.1", 0), OCRModel)
    threading.Thread(target=model.serve_forever, daemon=True).start()
    save_config(vault, {"ai_base_url": f"http://127.0.0.1:{model.server_address[1]}/v1",
                        "ai_api_key": "test-essay-vision", "ai_model": "essay-vision-fake"})
    server = make_server(vault, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    errors = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            context = browser.new_context(viewport={"width": 1600, "height": 1100})
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            # 生成清楚可见的模拟稿纸原图；识别服务返回确定性全文，不依赖外网模型。
            images = []
            sample = context.new_page()
            sample.set_viewport_size({"width": 720, "height": 960})
            for n in range(3):
                sample.set_content(f"""<html lang="zh"><style>body{{margin:56px;background:#fffdf7;color:#263953;font:24px/2.5 cursive}}
                  h1{{text-align:center;font-size:32px}}p{{background:repeating-linear-gradient(transparent,transparent 59px,#bbc9b0 60px);min-height:720px}}
                  small{{font:16px sans-serif}}</style><h1>成长的路上</h1><small>第 {n + 1} 页 · 模拟作文原图</small>
                  <p>那天，母亲陪我走过长街。<br>我在路边看到一棵树。<br>风轻轻吹过，心中有些暖意。<br>成长不只是年龄的增加。<br>我愿意把每一份温柔记在心里。</p></html>""")
                path = os.path.join(vault, f"essay-page-{n + 1}.png")
                sample.screenshot(path=path)
                images.append(path)
            sample.close()
            page.goto(base + "/#/essays")
            page.wait_for_selector('.es')
            page.click('.es-library [data-action="es.newPrompt"]')
            page.get_by_label('作文题名称', exact=True).fill('成长的路上')
            page.get_by_label('作文题正文', exact=True).fill('请以“成长的路上”为题，写一篇完整作文。')
            page.get_by_label('作文写作要求').fill('不少于 800 字，文体不限。')
            page.get_by_label('作文题出处').fill('模拟周练')
            page.get_by_role('button', name='创建作文题', exact=True).click()
            page.wait_for_selector('[data-submit="es.createAttempt"]')
            page.locator('[data-submit="es.classify"] input').fill('成长、亲情')
            page.locator('[data-submit="es.classify"] button').click()
            page.wait_for_selector('.es-classify .chip:text-is("亲情")')
            page.get_by_label('练习名称').fill('第一次完整作文练习')
            page.get_by_role('button', name='新建一次练习').click()
            page.wait_for_selector('[data-change="es.files"]')
            attempt_id = page.evaluate("new URLSearchParams(location.hash.split('?')[1]).get('attempt')")
            page.get_by_label('选择作文图片').set_input_files(images)
            page.get_by_role('button', name='上传 3 页为第 1 版').click()
            page.wait_for_selector('[data-action="es.ocr"]')
            version_id = page.evaluate("new URLSearchParams(location.hash.split('?')[1]).get('version')")
            assert len(essays.version_detail(vault, version_id)["images"]) == 3
            assert essays.attempt_detail(vault, attempt_id)["modification_count"] == 0

            # 真实 HTTP 模型失败，然后同一Version重试；不会增加版本数。
            page.get_by_role('button', name='开始原样转写').click()
            page.get_by_role('button', name='重试原样转写').wait_for(timeout=10000)
            page.get_by_role('button', name='重试原样转写').click()
            page.wait_for_function("document.querySelector('[data-input=\"es.text\"]')?.value.includes('成涨')", timeout=10000)
            assert len(OCRModel.requests) == 2
            parts = OCRModel.requests[-1]["messages"][0]["content"]
            assert sum(p["type"] == "image_url" for p in parts) == 3
            page.get_by_role('button', name='下一页原图').click()
            assert page.locator('.es-original img').get_attribute('alt').endswith('第 2 页原图')
            if shots:
                os.makedirs(shots, exist_ok=True)
                page.evaluate('window.scrollTo(0, 0)')
                page.screenshot(path=os.path.join(shots, 'essay-proof-desktop.png'), full_page=True)
            corrected_text = OCR_TEXT.replace('【存疑：树/术】', '树')
            editor = page.get_by_label('校对后的作文全文')
            editor.fill(corrected_text)
            editor.press('End')
            assert editor.input_value() == corrected_text
            page.get_by_role('button', name='保存校对', exact=True).click()
            page.wait_for_function("document.querySelector('[data-action=\"es.saveText\"]').disabled")
            page.get_by_role('button', name='确认正式转写', exact=True).click()
            page.wait_for_selector('.es-final')
            formal = essays.version_detail(vault, version_id)
            assert formal["raw_ocr_text"] == OCR_TEXT
            assert formal["text"] == corrected_text
            assert essays.attempt_detail(vault, attempt_id)["modification_count"] == 0

            # 外部 append-only 工作流通过共享领域服务保存；MCP端口由专门MCP E2E覆盖。
            first = essays.add_evaluation(vault, version_id, 47, '结构完整，第二段转折较突然。', strengths=['细节有温度'],
                                          issues=['转折突兀'], suggestions=['下一稿改善第二段过渡'],
                                          evaluator='ChatGPT', source='mcp', model='fake-external')
            essays.add_note(vault, attempt_id, '下一稿重点处理第二段和结尾。', version_id, source='mcp')
            page.get_by_role('button', name='刷新评价').click()
            page.wait_for_selector('.es-evaluation')
            assert page.locator('.es-score strong').inner_text() == '47'
            page.get_by_role('button', name='采用这份评价').click()
            page.get_by_role('button', name='当前采用').wait_for()
            assert essays.version_detail(vault, version_id)["adopted_evaluation_id"] == first["id"]
            assert page.locator('.es-notes').inner_text().find('下一稿重点处理第二段和结尾。') >= 0
            page.locator('.es-evaluation-form summary').click()
            page.get_by_label('作文评价总分').fill('49')
            page.get_by_label('作文评价摘要').fill('另一份评价，原评价保留。')
            page.get_by_role('button', name='保存评价', exact=True).click()
            page.wait_for_function("document.querySelectorAll('.es-evaluation').length === 2")
            if shots:
                os.makedirs(shots, exist_ok=True)
                page.locator('.toast').last.wait_for(state='hidden', timeout=7000)
                page.evaluate('window.scrollTo(0, 0)')
                page.screenshot(path=os.path.join(shots, 'essay-desktop.png'), full_page=True)

            # 下一稿属于原Attempt，旧评价不会被移动或覆盖。
            page.get_by_role('button', name='上传下一稿', exact=True).click()
            page.get_by_label('选择作文图片').set_input_files(images[:2])
            page.get_by_role('button', name='上传 2 页为第 2 版').click()
            page.wait_for_selector('[data-action="es.ocr"]')
            second_id = page.evaluate("new URLSearchParams(location.hash.split('?')[1]).get('version')")
            assert second_id != version_id
            assert page.locator('.es-count').inner_text() == '2 版\n修改 1 次'
            page.get_by_label('校对后的作文全文').fill(corrected_text + '\n我轻轻握住母亲的手，把新的理解写在下一段里。')
            page.get_by_role('button', name='确认正式转写').click()
            page.wait_for_selector('.es-final')
            page.get_by_role('button', name='与上一稿对比').click()
            page.wait_for_selector('.es-diff ins')
            assert page.locator('.es-diff ins').inner_text().find('握住母亲的手') >= 0
            assert len(essays.version_detail(vault, version_id)["evaluations"]) == 2
            assert len(essays.version_detail(vault, second_id)["evaluations"]) == 0

            page.set_viewport_size({"width": 390, "height": 844})
            assert not page.locator('.es-library').is_visible()
            page.get_by_role('button', name='作文题 1', exact=True).click()
            assert page.locator('.es-library').is_visible()
            page.get_by_label('搜索作文题').fill('不存在')
            page.wait_for_selector('.es-library .empty:text-is("没有匹配的作文题")')
            page.get_by_label('搜索作文题').fill('亲情')
            page.wait_for_selector('.es-prompt')
            page.get_by_role('button', name='作文题 1', exact=True).click()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.get_by_label('作文讨论笔记').fill('手机键盘记录修改重点。')
            page.get_by_label('作文讨论笔记').press('Tab')
            page.get_by_role('button', name='保存笔记', exact=True).click()
            page.wait_for_selector('.es-notes p:text-is("手机键盘记录修改重点。")')
            if shots:
                page.locator('.toast').last.wait_for(state='hidden', timeout=7000)
                page.evaluate('window.scrollTo(0, 0)')
                page.screenshot(path=os.path.join(shots, 'essay-mobile.png'), full_page=True)

            # 刷新深链接仍打开原版本，原文和评价保留。
            page.goto(base + f'/#/essays?version={version_id}')
            page.wait_for_selector('.es-final')
            assert page.locator('.es-final .es-reading').inner_text() == corrected_text
            assert page.locator('.es-evaluation').count() == 2
            before = len(ledger.read_commits(vault))
            page.reload()
            page.wait_for_selector('.es-final')
            assert len(ledger.read_commits(vault)) == before

            # 卸载后晚到的异步回包不得重绘作文页。
            held = []
            page.route('**/api/essay/attempt?*', lambda route: held.append(route))
            page.get_by_role('button', name='刷新评价').click()
            page.locator('#nav a[data-page="dashboard"]').click()
            page.wait_for_selector('#panel-dashboard.is-active')
            assert held, '专项必须实际截住作文页未完成请求'
            late = essays.attempt_detail(vault, attempt_id)
            late['title'] = '晚到旧回复不应绘制'
            held[0].fulfill(status=200, content_type='application/json', body=json.dumps(late, ensure_ascii=False))
            page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
            assert '晚到旧回复不应绘制' not in page.locator('#panel-essays').text_content()
            assert not page.locator('#panel-essays').is_visible()
            assert not errors, errors
            assert ledger.verify_ledger(vault)["ok"]
            browser.close()
        print('e2e_essays: 作文题/自由分类/多页一稿/OCR真实HTTP失败重试/校对/确认/评价/采用/笔记/下一稿/diff/手机/深链接全部通过')
    finally:
        server.shutdown(); server.server_close(); model.shutdown(); model.server_close()
        projections.reset_state(vault); shutil.rmtree(vault, ignore_errors=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--shots')
    run(parser.parse_args().shots)

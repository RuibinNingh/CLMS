"""真实浏览器：A4、真实答案排版、跨页、短防抖持久化、刷新与手机。"""
import argparse
import os
import re
import shutil
import sys
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(__file__))
from clms import creation, draft_schema, ledger, sessions  # noqa: E402
from clms.server import make_server  # noqa: E402
from test_core import seed_types  # noqa: E402


def run(shots=None):
    from playwright.sync_api import sync_playwright
    vault = tempfile.mkdtemp(prefix="clms-print-")
    seed_types(vault)
    answers = ["通过对灯火和街巷的描写，作者表达了对故乡的思念与珍惜。" * 75,
               "第一点\n\n第二点\n第三点\n\n第四点",
               "\n".join(f"第{i}个采分点：保留作文原来的细节，具体分析人物的心情与变化。" for i in range(135))]
    groups = draft_schema.normalize_groups([{"genre": "modern", "material": {
        "title": "真实版面与长答案", "text": "老街的灯火照亮归途。" * 350 + "\n第二段保留独立换行。"}, "items": [
        {"no": str(i + 1), "qtype": "意象作用题", "stem": f"请分析第{i + 1}处景物描写的作用。", "answer": answer, "blank_lines": 2}
        for i, answer in enumerate(answers)]}, {"genre": "dictation", "dictation": [
            {"template": "{书写区域1}，{书写区域2}。", "blanks": {"1": "床前明月光", "2": "疑是地上霜"}}]}])
    ids = creation.commit_draft(vault, {"id": "D-print", "images": []}, groups)["item_ids"]
    server = make_server(vault, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    errors = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            context = browser.new_context(viewport={"width": 1600, "height": 1000})
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(base + "/#/review")
            page.wait_for_selector('.pl__row')
            page.wait_for_function("!document.querySelector('.pl__list.is-busy')")
            page.click('[data-action="rv.create"]')
            page.wait_for_selector('#review-print-frame')
            iframe = page.frame_locator('#review-print-frame')
            iframe.locator('.print-page').first.wait_for()
            page.wait_for_function("document.querySelector('#review-print-frame').contentWindow.clmsPrint?.ready")
            frame = page.locator('#review-print-frame').content_frame
            session_id = page.evaluate("JSON.parse(document.querySelector('#review-print-frame').contentDocument.querySelector('#print-data').textContent).session.id")
            before = len(ledger.read_commits(vault))
            assert page.locator('.rv[data-mode="preview"]').count() == 1
            assert page.locator('.rv-q').count() == 0
            assert len(ledger.read_commits(vault)) == before, "打开预览必须只读"
            geometry = frame.locator('.print-page').first.evaluate("el => ({ width: el.offsetWidth, height: el.offsetHeight })")
            assert abs(geometry["width"] - 210 * 96 / 25.4) < 1
            assert abs(geometry["height"] - 297 * 96 / 25.4) < 1
            assert frame.locator('.print-page .dictation .blank').count() == 2

            # 明确动作：单题真实换行测量，长中文答案不能仍然两行。
            page.click(f'[data-action="rv.printAuto"][data-arg="{ids[0]}"]')
            long_count = int(page.locator(f'[data-input="rv.printLines"][data-arg="{ids[0]}"]').input_value())
            assert long_count > 24, long_count
            page.wait_for_function("!document.querySelector('.rv-print-controls__status').innerText.includes('保存…')")

            page.click('[data-action="rv.printAutoAll"]')
            counts = {qid: int(page.locator(f'[data-input="rv.printLines"][data-arg="{qid}"]').input_value()) for qid in ids[:3]}
            assert counts[ids[1]] == 6, counts
            assert counts[ids[2]] >= 135, counts
            metrics = frame.locator('body').evaluate("""() => {
              const p = window.clmsPrint; const data = JSON.parse(document.querySelector('#print-data').textContent);
              p.fitAnswer(data.session.items[0].id);
              const a = document.querySelector('.answer-measure');
              const q = document.querySelector('.print-page .lines');
              const ac = getComputedStyle(a), qc = getComputedStyle(q);
              return { aw: a.offsetWidth, qw: q.offsetWidth, font: ac.font, qfont: qc.font,
                whitespace: ac.whiteSpace, qwhitespace: qc.whiteSpace, wrap: ac.overflowWrap, qwrap: qc.overflowWrap };
            }""")
            assert metrics["aw"] == metrics["qw"], metrics
            assert metrics["font"] == metrics["qfont"], metrics
            assert metrics["whitespace"] == metrics["qwhitespace"] and metrics["wrap"] == metrics["qwrap"], metrics

            # 同一题的留白可以跨多张 A4；分页内容没有溢出。
            assert frame.locator(f'.print-page .q[data-item="{ids[2]}"]').count() > 4
            overflow = frame.locator('.print-content').evaluate_all("els => els.filter(el => el.scrollHeight > el.clientHeight + 1).length")
            assert overflow == 0, overflow
            page_count = frame.locator('.print-page').count()
            page.locator(f'[data-input="rv.printLines"][data-arg="{ids[0]}"]').fill("1")
            assert frame.locator('.print-page').count() < page_count, "数值输入后同步重新分页"
            page.click(f'[data-action="rv.printAuto"][data-arg="{ids[0]}"]')
            page.wait_for_function("!document.querySelector('.rv-print-controls__status').innerText.includes('保存…')")
            settled = len(ledger.read_commits(vault))
            for _ in range(3):
                page.click(f'[data-action="rv.printStep"][data-arg="{ids[0]}:1"]')
            assert int(page.locator(f'[data-input="rv.printLines"][data-arg="{ids[0]}"]').input_value()) == long_count + 3
            page.wait_for_function("document.querySelector('.rv-print-controls__status').innerText.includes('默认留白已保存')")
            assert len(ledger.read_commits(vault)) == settled + 1, "连续点击应只有最后值的一条提交"
            if shots:
                os.makedirs(shots, exist_ok=True)
                page.screenshot(path=os.path.join(shots, "print-preview-desktop.png"))

            # 刷新保留预览及正式题目默认值，不产生第二次写入。
            settled = len(ledger.read_commits(vault))
            page.reload()
            page.wait_for_selector('#review-print-frame')
            page.wait_for_function("document.querySelector('#review-print-frame').contentWindow.clmsPrint?.ready")
            assert int(page.locator(f'[data-input="rv.printLines"][data-arg="{ids[0]}"]').input_value()) == long_count + 3
            assert len(ledger.read_commits(vault)) == settled
            # 不等待450ms防抖就刷新，pagehide仍提交最后的人工值。
            page.locator(f'[data-input="rv.printLines"][data-arg="{ids[1]}"]').fill('7')
            page.reload()
            page.wait_for_function("document.querySelector('#review-print-frame')?.contentWindow.clmsPrint?.ready")
            assert page.locator(f'[data-input="rv.printLines"][data-arg="{ids[1]}"]').input_value() == '7'
            assert sessions.view(vault, session_id)['items'][1]['blank_lines'] == 7
            newer = sessions.create(vault, ids)
            assert newer['items'][0]['blank_lines'] == long_count + 3

            # 独立打印与嵌入预览来自同一个模板/CSS，并在 print 媒体保持同样分页。
            standalone = context.new_page()
            standalone.on("pageerror", lambda error: errors.append(str(error)))
            standalone.goto(base + f'/print/session?id={session_id}')
            standalone.wait_for_function('window.clmsPrint?.ready')
            assert standalone.locator('#print-css').text_content() == page.frame_locator('#review-print-frame').locator('#print-css').text_content()
            assert standalone.locator('.print-page').count() == page.frame_locator('#review-print-frame').locator('.print-page').count()
            original_pages = standalone.locator('.print-page').count()
            standalone.emulate_media(media='print')
            assert standalone.locator('.print-page').count() == original_pages
            assert standalone.locator('.lines').first.evaluate('el => getComputedStyle(el).lineHeight') == '34.0157px'
            pdf = standalone.pdf(path=os.path.join(shots or vault, 'print-preview.pdf'), format='A4', prefer_css_page_size=True)
            pdf_counts = [int(count) for count in re.findall(rb'/Count\s+(\d+)\b', pdf)]
            assert pdf_counts and max(pdf_counts) == original_pages, (pdf_counts, original_pages)
            if shots:
                standalone.screenshot(path=os.path.join(shots, "print-document.png"), full_page=True)

            # 手机仍能打开设置、键盘改值、开始旧评分流程。
            page.set_viewport_size({"width": 390, "height": 844})
            page.click('.rv-top [data-action="rv.rail"]')
            page.wait_for_function("document.querySelector('.rv__rail').getBoundingClientRect().left >= 0")
            field = page.locator(f'[data-input="rv.printLines"][data-arg="{ids[1]}"]')
            field.fill('7'); field.press('ArrowUp')
            assert field.input_value() == '8'
            if shots:
                page.screenshot(path=os.path.join(shots, 'print-preview-mobile.png'))
            page.click('.rv-print-controls [data-action="rv.rail"]')
            page.click('[data-action="rv.printStart"]')
            page.wait_for_selector('.rv-q')
            assert sessions.view(vault, session_id)['items'][1]['blank_lines'] == 8
            page.click('[data-action="rv.reveal"]')
            page.click('.rv-score [data-grade="2"]')
            page.wait_for_selector('.rv-score__opt[aria-pressed="true"][data-grade="2"]')

            # 卸载时继续完成已授权保存，但异步回复不能重画新的页面。
            page.click('[data-action="rv.printPreview"]')
            page.wait_for_function("document.querySelector('#review-print-frame').contentWindow.clmsPrint?.ready")
            page.click('.rv-top [data-action="rv.rail"]')
            page.locator(f'[data-input="rv.printLines"][data-arg="{ids[1]}"]').fill('9')
            page.evaluate("""() => {
              const fetchOriginal = window.fetch;
              window.fetch = (...args) => fetchOriginal(...args).then(response =>
                String(args[0]).includes('/api/session/blank-lines')
                  ? new Promise(resolve => setTimeout(() => resolve(response), 700)) : response);
            }""")
            page.click('.nav a[href="#/dashboard"]')
            page.wait_for_selector('.dash')
            hidden_review = page.locator('#panel-review').inner_html()
            page.wait_for_timeout(900)
            assert page.locator('#panel-review').inner_html() == hidden_review
            assert not page.locator('#panel-review').is_visible()
            assert sessions.view(vault, session_id)['items'][1]['blank_lines'] == 9

            # 字体等待期间离开页面，旧 iframe 处于隐藏 panel：不测零高度，不报排版错误。
            page.set_viewport_size({"width": 1600, "height": 1000})
            page.add_init_script("""if (location.pathname === '/print/session') {
              Object.defineProperty(document.fonts, 'ready', { value: new Promise(resolve => setTimeout(resolve, 1200)) });
            }""")
            page.click('.nav a[href="#/review"]')
            page.wait_for_selector('#review-print-frame')
            page.wait_for_function("document.querySelector('#review-print-frame').contentWindow.clmsPrint")
            assert not page.evaluate("document.querySelector('#review-print-frame').contentWindow.clmsPrint.ready")
            page.click('.nav a[href="#/dashboard"]')
            page.wait_for_selector('.dash')
            page.wait_for_timeout(1500)
            assert not page.evaluate("document.querySelector('#review-print-frame').contentWindow.clmsPrint.ready")
            page.click('.nav a[href="#/review"]')
            page.wait_for_selector('#review-print-frame')
            page.wait_for_function("document.querySelector('#review-print-frame').contentWindow.clmsPrint?.ready")
            assert page.frame_locator('#review-print-frame').locator('.print-page').count() > 1
            assert not errors, errors
            browser.close()
        print('e2e_print: A4 / 真排版 / 自动 / 手动 / 防抖 / 跨页 / 刷新 / 打印一致 / 手机 / 评分全部通过')
    finally:
        server.shutdown(); server.server_close(); shutil.rmtree(vault, ignore_errors=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--shots')
    run(parser.parse_args().shots)

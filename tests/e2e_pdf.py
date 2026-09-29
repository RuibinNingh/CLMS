"""真 PDF.js + 浏览器：逐卡进度、爆炸、重复页、失败重试、取消、混合上传、移动端和减少动效。

可单独运行 python tests/e2e_pdf.py --shots <目录>；也由 e2e_main.py 调用。
PDF 由标准库写出（文字 PDF）和 Pillow 生成（扫描 PDF），不用外部试卷或真实模型。
"""
import argparse
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def make_pdf(folder, count=3, name='试卷.pdf'):
    text = b'BT /F1 24 Tf 60 760 Td (CLMS Reading Practice) Tj 0 -45 Td /F1 14 Tf (Read the passage and answer the questions.) Tj ET\n'
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'', b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    pages = []
    for n in range(count):
        page_id = len(objects) + 1
        pages.append(page_id)
        rotation = b' /Rotate 90' if n == 2 else b''
        objects.append(b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> >> /Contents '
                       + str(page_id + 1).encode() + b' 0 R' + rotation + b' >>')
        objects.append(b'<< /Length ' + str(len(text)).encode() + b' >>\nstream\n' + text + b'endstream')
    objects[1] = b'<< /Type /Pages /Count ' + str(count).encode() + b' /Kids [' + b' '.join(f'{p} 0 R'.encode() for p in pages) + b'] >>'
    data = bytearray(b'%PDF-1.4\n')
    offsets = [0]
    for n, body in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f'{n} 0 obj\n'.encode() + body + b'\nendobj\n')
    xref = len(data)
    data.extend(f'xref\n0 {len(offsets)}\n0000000000 65535 f \n'.encode())
    data.extend(b''.join(f'{x:010d} 00000 n \n'.encode() for x in offsets[1:]))
    data.extend(f'trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode())
    path = Path(folder) / name
    path.write_bytes(data)
    return str(path)


def make_scan(folder):
    from PIL import Image, ImageDraw, ImageFont
    pages = []
    font_path = Path('C:/Windows/Fonts/msyh.ttc')
    font = ImageFont.truetype(str(font_path), 28) if font_path.exists() else ImageFont.load_default()
    for n in range(3):
        im = Image.new('RGB', (900, 1200), (253, 253, 251))
        draw = ImageDraw.Draw(im)
        lines = ['语文阅读练习', '一、阅读下面的文字，完成各题。', '老街的灯',
                 '傍晚，老街的灯一盏接着一盏亮了。', '行人慢慢走过，熟悉的声音又回到巷口。',
                 '1. 请结合全文，分析“灯”的作用。', '2. 赏析文中画线的句子。'] if font_path.exists() else ['Reading practice', 'Read and answer', 'The lights of the old street']
        for index, line in enumerate(lines):
            draw.text((65, 65 + index * 78), line, font=font, fill=(27, 33, 48))
        draw.text((65, 1080), str(n + 1), font=font, fill=(77, 85, 102))
        pages.append(im)
    path = str(Path(folder) / '语文扫描卷.pdf')
    pages[0].save(path, save_all=True, append_images=pages[1:])
    for im in pages:
        im.close()
    return path


def check_pdf(browser, base, folder, images, shots=None):
    from playwright.sync_api import expect
    context = browser.new_context(viewport={'width': 1440, 'height': 1000})
    pg = context.new_page()
    errors = []
    pg.on('pageerror', lambda error: errors.append(str(error)))
    pdf = make_pdf(folder)
    scan = make_scan(folder)
    broken = Path(folder) / '损坏.pdf'
    broken.write_bytes(b'%PDF-1.4\nnot a pdf')

    def shot(name):
        if shots:
            pg.screenshot(path=str(Path(shots) / name))

    def new_entry():
        pg.goto(base + '/#/entry')
        pg.wait_for_selector('.launch, .chat')
        if pg.locator('.hist [data-action="entry.fresh"]').is_visible():
            pg.click('.hist [data-action="entry.fresh"]')
        else:
            pg.click('.hist-toggle')
            pg.click('.hist [data-action="entry.fresh"]')
        pg.wait_for_selector('.launch:not(:has(.launch__pages))')

    # 放慢真正的逐页上传，让观察窗口稳定；转换本身没有用假数据代替。
    def slow_upload(route):
        if route.request.method == 'POST':
            time.sleep(.25)
        route.continue_()
    pg.route('**/api/image', slow_upload)
    new_entry()
    pg.fill('#composer', '只录阅读题')
    pg.set_input_files('.launch input[data-change="entry.files"]', [scan, pdf])
    expect(pg.locator('.file-card')).to_have_count(2)
    pg.wait_for_function("document.querySelector('.file-card progress')?.value > 0")
    assert pg.locator('progress:not(.file-card progress)').count() == 0
    expect(pg.locator('.launch .composer__send')).to_be_disabled()
    assert '拆分中' in pg.locator('.file-card').first.inner_text()
    shot('11-pdf-splitting.png')
    pg.wait_for_selector('.file-card[data-state="burst"]', timeout=30000)
    assert pg.locator('.file-card__burst i').count() == 8
    shot('12-pdf-burst.png')
    pg.wait_for_function("document.querySelectorAll('.page[data-page]').length === 6 && !document.querySelector('.file-card')", timeout=30000)
    assert pg.input_value('#composer') == '只录阅读题'
    expect(pg.locator('.launch .composer__send')).to_be_enabled()
    keys = pg.locator('.page[data-page]').evaluate_all('els => els.map(e => e.dataset.key)')
    assert len(set(keys)) == 6
    srcs = pg.locator('.page[data-page] img').evaluate_all("els => els.map(e => e.getAttribute('src'))")
    assert srcs[3] == srcs[4] and srcs[4] != srcs[5], srcs
    pg.wait_for_function("[...document.querySelectorAll('.page[data-page] img')].every(im => im.complete && im.naturalWidth > 0)")
    pg.wait_for_function("[...document.querySelectorAll('.page[data-page]')].every(el => el.getAnimations().every(a => a.playState === 'finished'))")
    shot('13-pdf-pages.png')
    # 溢出后展开管理器，调节网格、拖动排序、单页放大，收起后保留编辑。
    pg.click('[data-action="entry.managerOpen"]')
    pg.wait_for_selector('.page-manager:modal')
    expect(pg.locator('.page-manager .page[data-page]')).to_have_count(6)
    width = pg.locator('.page-manager .page[data-page]').first.bounding_box()['width']
    pg.locator('[data-input="entry.managerSize"]').evaluate("el => { el.value = 260; el.dispatchEvent(new Event('input', {bubbles:true})); }")
    pg.wait_for_function("w => document.querySelector('.page-manager .page[data-page]').getBoundingClientRect().width > w", arg=width)
    shot('17-page-manager-grid.png')
    # 回归：拖动换序那次保存的回复故意晚到 800ms（比填说明那次还晚）。以前晚到的旧回复会把刚填的说明冲掉，
    # 下一次保存（旋转）再把丢了说明的页面存回去；现在保存排队、只认最后一次的回复。
    pg.evaluate("""() => { const orig = window.fetch; let n = 0;
      window.fetch = async (url, opts) => { const res = await orig(url, opts);
        if (String(url).includes('/api/draft/pages') && n++ === 0) await new Promise(r => setTimeout(r, 800));
        return res; }; }""")
    pg.drag_and_drop('.page-manager .page[data-page="1"]', '.page-manager .page[data-page="0"]')
    pg.wait_for_function("key => document.querySelector('.page-manager .page[data-page]')?.dataset.key === key", arg=keys[1])
    pg.fill('.page-manager .page[data-page="0"] .page__note', '阅读题目页')
    pg.press('.page-manager .page[data-page="0"] .page__note', 'Tab')
    pg.click('.page-manager .page[data-page="0"] .page__preview')
    pg.wait_for_function("document.querySelector('.page-manager__paper')?.clientWidth > 10")
    fit = pg.locator('.page-manager__paper').bounding_box()['width']
    pg.locator('[data-input="entry.managerZoom"]').evaluate("el => { el.value = 200; el.dispatchEvent(new Event('input', {bubbles:true})); }")
    pg.wait_for_function("w => document.querySelector('.page-manager__paper').clientWidth > w * 1.8", arg=fit)
    shot('18-page-manager-zoom.png')
    pg.click('[data-action="entry.managerFit"]')
    pg.click('.page-manager [data-action="entry.pageRotate"]')
    pg.wait_for_selector('.page-manager__paper[data-rotate="90"]')
    pg.keyboard.press('Escape')
    pg.wait_for_selector('.page-manager__grid')
    pg.click('.page-manager__head [data-action="entry.managerClose"]')
    expect(pg.locator('.page-manager')).to_have_count(0)
    assert pg.locator('.page[data-page="0"]').get_attribute('data-key') == keys[1]
    pg.wait_for_timeout(900)                                   # 等晚到的那次回复也回来
    assert pg.locator('.page[data-page="0"] .page__note').input_value() == '阅读题目页'
    # 旋转、移动、保存说明后刷新，来源和重复页仍然存在。
    pg.click('[data-action="entry.pageRotate"][data-arg="0"]')
    pg.wait_for_selector('.page[data-page="0"] .page__img[data-rotate="180"]')
    pg.fill('.page[data-page="0"] .page__note', '题目页')
    pg.press('.page[data-page="0"] .page__note', 'Tab')
    pg.click('[data-action="entry.pageMove"][data-arg="1:-1"]')
    pg.wait_for_function("key => document.querySelector('.page[data-page]')?.dataset.key === key", arg=keys[0])
    if not pg.locator('.hist .hrow.is-active .hrow__main').is_visible():
        pg.click('.launch .hist-toggle')
    pg.click('.hist .hrow.is-active .hrow__main')
    assert pg.locator('.page[data-page]').count() == 6
    assert '第 1 页' in pg.locator('.page[data-page="0"]').get_attribute('title')
    # PDF 进入现有 Agent 路径；重复图片不能让原图区或对话模板崩溃。
    pg.click('[data-action="entry.start"]')
    pg.wait_for_selector('.chat')
    pg.wait_for_selector('.blk--run[data-status="done"]', timeout=60000)
    assert pg.locator('.msg__imgs img').count() >= 6
    pg.click('.sheet__bar [data-action="entry.pane"][data-arg="image"]')
    assert pg.locator('.shot').count() == 6
    pg.click('[data-action="entry.commit"]')
    pg.wait_for_selector('.sheet__foot.is-done')

    new_entry()
    pg.set_input_files('.launch input[data-change="entry.files"]', str(broken))
    pg.wait_for_selector('.file-card[data-state="error"]')
    assert 'PDF' in pg.locator('.file-card__error').inner_text()
    shot('14-pdf-error.png')
    pg.click('[data-action="entry.importRemove"]')
    expect(pg.locator('.file-card')).to_have_count(0)

    # 网络失败后重试：已经完成的页继续复用，不插入半份草稿。
    pg.unroute('**/api/image', slow_upload)
    attempts = [0]
    def fail_once(route):
        attempts[0] += 1
        if attempts[0] == 2:
            route.fulfill(status=503, content_type='application/json', body='{"msg":"测试上传暂时失败"}')
        else:
            route.continue_()
    pg.route('**/api/image', fail_once)
    pg.set_input_files('.launch input[data-change="entry.files"]', pdf)
    pg.wait_for_selector('.file-card[data-state="error"]')
    assert pg.locator('.page[data-page]').count() == 0
    pg.click('[data-action="entry.importRetry"]')
    pg.wait_for_function("document.querySelectorAll('.page[data-page]').length === 3 && !document.querySelector('.file-card')")
    assert attempts[0] == 4, attempts
    pg.unroute('**/api/image', fail_once)
    # 已有页面继续加 PDF 和普通图片，顺序正确。
    pg.set_input_files('.launch input[data-change="entry.pageAdd"]', [images[0], pdf])
    pg.wait_for_function("document.querySelectorAll('.page[data-page]').length === 7 && !document.querySelector('.file-card')")

    new_entry()
    pg.route('**/api/image', slow_upload)
    pg.set_input_files('.launch input[data-change="entry.files"]', scan)
    pg.wait_for_selector('.file-card[data-state="splitting"]')
    pg.click('[data-action="entry.importRemove"]')
    expect(pg.locator('.file-card')).to_have_count(0)
    pg.wait_for_timeout(500)
    assert pg.locator('.page[data-page]').count() == 0
    # 手机 / 深色 / 减少动态效果：进度仍在卡片内，完成后可操作。
    pg.click('[data-action="app.theme"]')              # 先切深色：≤ 760 时侧栏底部（含主题按钮）是隐藏的
    pg.set_viewport_size({'width': 390, 'height': 844})
    pg.emulate_media(reduced_motion='reduce')
    pg.set_input_files('.launch input[data-change="entry.files"]', scan)
    pg.wait_for_function("document.querySelector('.file-card progress')?.value > 0")
    shot('15-pdf-mobile-dark-progress.png')
    pg.wait_for_function("document.querySelectorAll('.page[data-page]').length === 3 && !document.querySelector('.file-card')")
    assert pg.evaluate('document.documentElement.scrollWidth') <= 390
    assert pg.locator('.page[data-page]').evaluate_all('els => els.every(e => e.getAnimations().length === 0)')
    shot('16-pdf-mobile-dark-pages.png')
    pg.click('[data-action="entry.managerOpen"]')
    pg.wait_for_selector('.page-manager:modal')
    pg.locator('[data-input="entry.managerSize"]').evaluate("el => { el.value = 140; el.dispatchEvent(new Event('input', {bubbles:true})); }")
    shot('19-page-manager-mobile.png')
    assert pg.locator('.page-manager').evaluate('el => el.scrollWidth <= el.clientWidth')
    pg.click('.page-manager .page[data-page="0"] .page__preview')
    pg.wait_for_function("document.querySelector('.page-manager__paper')?.clientWidth > 10")
    pg.keyboard.press('Escape')
    pg.keyboard.press('Escape')
    expect(pg.locator('.page-manager')).to_have_count(0)
    assert not errors, errors
    context.close()
    print('PDF 浏览器路径通过')


def run(shots=None):
    import shutil
    from playwright.sync_api import sync_playwright
    import fake_ai
    from clms.common import save_config
    from clms.server import make_server
    from e2e_main import make_images
    vault = tempfile.mkdtemp(prefix='clms-pdf-e2e-')
    ai = fake_ai.start(0)
    save_config(vault, {'ai_base_url': f'http://127.0.0.1:{ai.server_address[1]}/v1', 'ai_api_key': 'k', 'ai_model': 'fake'})
    server = make_server(vault, '127.0.0.1', 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            check_pdf(browser, f'http://127.0.0.1:{server.server_address[1]}', vault, make_images(vault), shots)
            browser.close()
    finally:
        server.shutdown(); server.server_close()
        ai.shutdown(); ai.server_close()
        shutil.rmtree(vault, ignore_errors=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--shots')
    args = parser.parse_args()
    if args.shots:
        Path(args.shots).mkdir(parents=True, exist_ok=True)
    run(args.shots)

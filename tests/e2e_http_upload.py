"""真实非安全 HTTP origin 的录入上传回归；只写临时 vault，不调用模型。

Chromium 将 clms-upload.test 解析到本机随机端口，不把 localhost 的安全
上下文特例当成内网 HTTP。所有输入由 Pillow/标准库自建。
"""
import argparse
import base64
from contextlib import contextmanager
import json
from pathlib import Path
import re
import sys
import tempfile
import threading
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from clms.server import make_server  # noqa: E402


@contextmanager
def fixture(browser, secure=False):
    from PIL import Image
    with tempfile.TemporaryDirectory(prefix='clms-http-upload-') as folder:
        image = Path(folder) / '练习.png'
        for n in range(6):
            target = image if n == 0 else Path(folder) / f'练习-{n}.png'
            Image.new('RGB', (320, 440), (250 - n * 15, 248, 242)).save(target)
        server = make_server(folder, '127.0.0.1', 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        host = '127.0.0.1' if secure else 'clms-upload.test'
        base = f'http://{host}:{server.server_address[1]}'
        context = browser.new_context(viewport={'width': 1440, 'height': 900})
        context.add_init_script("""window.uploadRejections = [];
          addEventListener('unhandledrejection', e => uploadRejections.push(String(e.reason)));""")
        page = context.new_page()
        errors, writes = [], []
        page.on('pageerror', lambda error: errors.append(str(error)))

        def request_seen(request):
            if request.method == 'POST':
                writes.append({'path': urlsplit(request.url).path, 'body': request.post_data_json})
        page.on('request', request_seen)
        try:
            page.goto(base + '/#/entry')
            page.wait_for_selector('.launch')
            capabilities = page.evaluate("""({secure: isSecureContext,
              uuid: typeof crypto.randomUUID, random: typeof crypto.getRandomValues})""")
            print('origin capabilities:', json.dumps(capabilities), flush=True)
            assert capabilities == {'secure': secure, 'uuid': 'function' if secure else 'undefined',
                                    'random': 'function'}, capabilities
            yield page, folder, str(image), writes, errors
        finally:
            context.close()
            server.shutdown()
            server.server_close()
            thread.join()


def staged(page, count, errors):
    try:
        page.wait_for_function("""n => document.querySelectorAll('.page[data-page]').length === n
          && !document.querySelector('.file-card')""", arg=count, timeout=10000)
    except Exception as error:
        raise AssertionError(f'上传未生成 {count} 页 staged 草稿；pageerrors={errors}; '
                             f'unhandled={page.evaluate("uploadRejections")}') from error
    draft_id = page.locator('.hrow.is-active').get_attribute('data-key')
    result = page.evaluate("""async id => (await fetch('/api/draft?id=' + encodeURIComponent(id))).json()""",
                           draft_id)
    assert result['status'] == 'staged', result
    assert len(result['pages']) == count, result
    return result


def assert_clean(page, errors):
    page.wait_for_timeout(100)
    assert not errors, errors
    assert page.evaluate('uploadRejections') == [], page.evaluate('uploadRejections')


def check_image(browser, secure=False):
    with fixture(browser, secure=secure) as (page, folder, image, writes, errors):
        page.evaluate("""() => { const random = crypto.getRandomValues.bind(crypto);
          window.randomSizes = [];
          crypto.getRandomValues = bytes => { randomSizes.push(bytes.byteLength); return random(bytes); };
          Math.random = () => { throw new Error('禁止弱随机'); };
          if (isSecureContext) crypto.randomUUID = () => { throw new Error('不得依赖 randomUUID'); };
        }""")
        page.set_input_files('.launch input[data-change="entry.files"]', image)
        draft = staged(page, 1, errors)
        creates = [w['body'] for w in writes if w['path'] == '/api/drafts']
        assert len(creates) == 1, writes
        assert re.fullmatch('[0-9a-f]{32}', creates[0]['upload_id']), creates
        assert len([w for w in writes if w['path'] == '/api/image']) == 1, writes
        assert draft['id'] == 'D-upload-' + creates[0]['upload_id'], draft
        assert page.evaluate('randomSizes') == [16], page.evaluate('randomSizes')
        page.wait_for_function("[...document.querySelectorAll('.page[data-page] img')].every(im => im.complete && im.naturalWidth > 0)")
        assert_clean(page, errors)
        print(('安全上下文' if secure else 'HTTP') + ' PNG 真上传/staged/32hex 通过', flush=True)


def check_no_random(browser):
    from playwright.sync_api import expect
    with fixture(browser) as (page, folder, image, writes, errors):
        page.evaluate("Object.defineProperty(crypto, 'getRandomValues', {value: undefined, configurable: true})")
        page.set_input_files('.launch input[data-change="entry.files"]', image)
        try:
            expect(page.locator('.toast--bad')).to_contain_text('文件准备失败', timeout=2000)
        except AssertionError as error:
            raise AssertionError(f'初始化失败没有中文提示；pageerrors={errors}; '
                                 f'unhandled={page.evaluate("uploadRejections")}') from error
        assert page.locator('.file-card').count() == 0
        assert writes == [], writes
        assert_clean(page, errors)
        page.evaluate("Object.defineProperty(window, 'crypto', {value: undefined, configurable: true})")
        page.set_input_files('.launch input[data-change="entry.files"]', image)
        expect(page.locator('.toast--bad')).to_have_count(2)
        expect(page.locator('.toast--bad').last).to_contain_text('无法生成安全的上传编号')
        assert writes == [] and page.locator('.file-card').count() == 0, writes
        assert_clean(page, errors)
        print('随机来源缺失：中文提示/零写请求/零未处理拒绝 通过', flush=True)


def dispatch_file(page, image, event):
    # 合成浏览器 File/DataTransfer，但事件进入真实页面监听器与上传代码。
    page.evaluate("""({data, event}) => {
      const bytes = Uint8Array.from(atob(data), ch => ch.charCodeAt(0));
      const transfer = new DataTransfer();
      transfer.items.add(new File([bytes], '练习.png', {type: 'image/png'}));
      const target = event === 'paste' ? document.querySelector('#composer') : document.querySelector('.entry');
      target.dispatchEvent(event === 'paste'
        ? new ClipboardEvent('paste', {bubbles: true, cancelable: true, clipboardData: transfer})
        : new DragEvent('drop', {bubbles: true, cancelable: true, dataTransfer: transfer}));
    }""", {'data': base64.b64encode(Path(image).read_bytes()).decode(), 'event': event})


def check_preserve_before_fresh(browser):
    from playwright.sync_api import expect
    with fixture(browser) as (page, folder, image, writes, errors):
        draft = page.evaluate("""async () => (await fetch('/api/drafts', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({manual: 'modern'})})).json()""")['drafts'][0]
        page.goto(page.url.split('#')[0] + '#/entry?draft=' + draft['id'])
        page.wait_for_selector('.chat')
        page.wait_for_selector('.hrow.is-active', state='attached')
        writes.clear()
        page.evaluate("Object.defineProperty(crypto, 'getRandomValues', {value: undefined, configurable: true})")
        dispatch_file(page, image, 'drop')
        expect(page.locator('.toast--bad')).to_contain_text('文件准备失败')
        expect(page.locator('.hrow.is-active')).to_have_attribute('data-key', draft['id'], timeout=2000)
        expect(page.locator('.chat')).to_be_visible()
        assert writes == [], writes
        assert_clean(page, errors)
        print('入队初始化失败不会先清理当前草稿 通过', flush=True)


def wait_pending(page, pending):
    for _ in range(200):
        if pending:
            return
        page.wait_for_timeout(25)
    raise AssertionError('等待真实上传请求超时')


def check_pdf(browser):
    from e2e_pdf import make_pdf
    from playwright.sync_api import expect
    with fixture(browser) as (page, folder, image, writes, errors):
        pdf = make_pdf(folder)
        pending = []
        gate = [True]
        workers = []
        page.on('worker', lambda worker: workers.append(worker.url))
        def hold_upload(route):
            if gate[0]:
                pending.append(route)
            else:
                route.continue_()
        page.route('**/api/image', hold_upload)
        page.fill('#composer', '保留这段说明')
        page.set_input_files('.launch input[data-change="entry.files"]', pdf)
        expect(page.locator('.file-card')).to_have_count(1)
        expect(page.locator('.composer__send')).to_be_disabled()
        expect(page.locator('.file-card')).to_contain_text('0 / 3 页')
        assert page.locator('.file-card progress').get_attribute('max') == '100'
        wait_pending(page, pending)
        assert len(pending) == 1, pending
        assert page.locator('.page[data-page]').count() == 0
        first_id = page.locator('.file-card').get_attribute('data-import')
        assert re.fullmatch('[0-9a-f]{32}', first_id), first_id
        pending.pop(0).continue_()
        page.wait_for_function("document.querySelector('.file-card progress')?.value === 33")
        expect(page.locator('.file-card')).to_contain_text('1 / 3 页')
        expect(page.locator('.file-card')).to_contain_text('拆分中')
        # 第二页暂停时进度可见；随后放行真正的 POST，不替代 PDF.js 转图。
        wait_pending(page, pending)
        assert len(pending) == 1, pending
        gate[0] = False
        pending.pop(0).continue_()
        draft = staged(page, 3, errors)
        assert page.input_value('#composer') == '保留这段说明'
        assert [p['source']['page'] for p in draft['pages']] == [1, 2, 3], draft
        assert {p['source']['import_id'] for p in draft['pages']} == {first_id}, draft
        assert any('/assets/vendor/pdfjs/build/pdf.worker.min.mjs' in url for url in workers), workers
        # 已有 staged 再选 PNG+PDF，两个队列卡片、新的 PDF 页身份与原草稿均保留。
        gate[0] = True
        page.set_input_files('.launch input[data-change="entry.pageAdd"]', [image, pdf])
        expect(page.locator('.file-card')).to_have_count(2)
        new_ids = page.locator('.file-card').evaluate_all('els => els.map(e => e.dataset.import)')
        assert len(set(new_ids + [first_id])) == 3, new_ids
        assert all(re.fullmatch('[0-9a-f]{32}', token) for token in new_ids), new_ids
        wait_pending(page, pending)
        assert len(pending) == 1, pending
        gate[0] = False
        pending.pop(0).continue_()
        added = staged(page, 7, errors)
        assert added['id'] == draft['id'], added
        assert {p['source']['import_id'] for p in added['pages'] if 'source' in p} == {first_id, new_ids[1]}
        assert len([w for w in writes if w['path'] == '/api/image']) == 7, writes
        assert_clean(page, errors)
        print('HTTP 真 PDF.js 拆页/慢 POST 卡片进度/混合多文件/再次加页 通过', flush=True)


def check_queue_errors(browser):
    from playwright.sync_api import expect
    with fixture(browser) as (page, folder, image, writes, errors):
        extras = [str(Path(folder) / f'练习-{n}.png') for n in range(1, 6)]
        def fail_upload(route):
            route.fulfill(status=503, content_type='application/json', body='{"msg":"测试上传暂时失败"}')
        page.route('**/api/image', fail_upload)
        page.set_input_files('.launch input[data-change="entry.files"]', [image, extras[0]])
        page.wait_for_selector('.file-card[data-state="error"]')
        expect(page.locator('.file-card__error')).to_contain_text('测试上传暂时失败')
        expect(page.locator('[data-action="entry.importRetry"]')).to_be_visible()
        ids = page.locator('.file-card').evaluate_all('els => els.map(e => e.dataset.import)')
        assert len(ids) == 2 and len(set(ids)) == 2, ids
        assert page.locator('.page[data-page]').count() == 0
        page.evaluate('() => { window.originalRandom = crypto.getRandomValues.bind(crypto); }')
        # 批次中第二次随机生成失败：新批次原子丢弃，不部分入队、不丢已有卡片。
        for entry in ('files', 'pageAdd', 'paste', 'drop'):
            writes.clear()
            page.evaluate("""() => { let count = 0;
              crypto.getRandomValues = bytes => {
                if (++count === 2 || !['files', 'pageAdd'].includes(window.failureEntry))
                  throw new Error('测试安全随机来源失效');
                return originalRandom(bytes);
              }; }""")
            page.evaluate('value => window.failureEntry = value', entry)
            if entry in ('files', 'pageAdd'):
                page.set_input_files(f'.launch input[data-change="entry.{entry}"]', extras[1:3])
            else:
                dispatch_file(page, extras[1], entry)
            expect(page.locator('.toast--bad').last).to_contain_text('文件准备失败：测试安全随机来源失效')
            assert page.locator('.file-card').evaluate_all('els => els.map(e => e.dataset.import)') == ids
            assert writes == [], writes
            assert_clean(page, errors)
        page.evaluate('() => { crypto.getRandomValues = originalRandom; }')
        page.unroute('**/api/image', fail_upload)
        page.click('[data-action="entry.importRetry"]')
        draft = staged(page, 2, errors)
        assert draft['id'] == 'D-upload-' + ids[0], draft
        # 粘贴和拖入成功也必须走同一队列，真正上传并加到当前 staged。
        dispatch_file(page, extras[1], 'paste')
        staged(page, 3, errors)
        dispatch_file(page, extras[2], 'drop')
        final = staged(page, 4, errors)
        assert final['id'] == draft['id'], final
        assert_clean(page, errors)
        print('四种入口初始化异常/批次原子性/保留队列/上传失败重试/粘贴拖入真上传 通过', flush=True)


def check_finish_retry(browser):
    from playwright.sync_api import expect
    with fixture(browser) as (page, folder, image, writes, errors):
        def fail_create(route):
            route.fulfill(status=503, content_type='application/json', body='{"msg":"测试草稿暂存失败"}')
        page.route('**/api/drafts', fail_create)
        page.set_input_files('.launch input[data-change="entry.files"]', image)
        page.wait_for_selector('.file-card[data-state="error"]')
        expect(page.locator('.file-card__error')).to_contain_text('测试草稿暂存失败')
        token = page.locator('.file-card').get_attribute('data-import')
        page.unroute('**/api/drafts', fail_create)
        page.click('[data-action="entry.importRetry"]')
        draft = staged(page, 1, errors)
        creates = [w['body'] for w in writes if w['path'] == '/api/drafts']
        assert len(creates) == 2 and all(w['upload_id'] == token for w in creates), writes
        assert len([w for w in writes if w['path'] == '/api/image']) == 1, writes
        assert draft['id'] == 'D-upload-' + token, draft
        assert_clean(page, errors)
        print('暂存失败重试复用上传图片与 32hex 幂等编号 通过', flush=True)


def run(case='all'):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        # 保留 Chromium 原生共享内存，避免受限 HOME 下 renderer 无权写 TMPDIR。
        browser = playwright.chromium.launch(ignore_default_args=['--disable-dev-shm-usage'], args=[
            '--no-proxy-server', '--host-resolver-rules=MAP clms-upload.test 127.0.0.1',
        ])
        try:
            checks = {'image': check_image, 'no-random': check_no_random,
                      'preserve': check_preserve_before_fresh, 'pdf': check_pdf,
                      'queue': check_queue_errors, 'finish-retry': check_finish_retry,
                      'secure': lambda browser: check_image(browser, secure=True)}
            for name, check in checks.items():
                if case in ('all', name):
                    check(browser)
        finally:
            browser.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--case', default='all', choices=[
        'all', 'image', 'no-random', 'preserve', 'pdf', 'queue', 'finish-retry', 'secure'])
    run(parser.parse_args().case)

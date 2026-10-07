"""真浏览器 + 独立 CLI：设置重启、取消、失败/超时/离页、丢失回包与手机布局。"""
import argparse
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from clms.common import save_config  # noqa: E402
from test_service import CLIService, call  # noqa: E402


def run(shots):
    from playwright.sync_api import expect, sync_playwright
    os.makedirs(shots, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="clms-e2e-service-") as vault:
        save_config(vault, {"session_minutes": 57})
        service = CLIService(vault)
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page(viewport={"width": 1600, "height": 900})
                errors, posts, polls = [], [], []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("request", lambda r: posts.append(r) if r.url.endswith('/api/service/restart') else
                        polls.append(r) if r.url.endswith('/api/status') else None)

                def open_settings():
                    page.goto(service.base + '/#/settings')
                    page.click('[data-action="set.section"][data-arg="service"]')
                    expect(page.locator('[data-action="set.restart"]')).to_be_enabled()

                def confirm():
                    page.click('[data-action="set.restart"]')
                    expect(page.locator('dialog')).to_be_visible()
                    page.locator('dialog').get_by_role('button', name='重启程序', exact=True).click()

                open_settings()
                page.screenshot(path=os.path.join(shots, 'service-desktop.png'), full_page=True)
                page.click('[data-action="set.restart"]')
                page.screenshot(path=os.path.join(shots, 'service-confirm.png'), full_page=True)
                page.locator('dialog').get_by_role('button', name='取消').click()
                expect(page.locator('[data-action="set.restart"]')).to_be_enabled()
                assert not posts
                assert service.wait_status()['instance_id'] == service.initial['instance_id']

                # 完整点击真实端点，等待新进程加载与自动刷新，设置分区保留。
                with page.expect_navigation(wait_until='domcontentloaded', timeout=20000):
                    confirm()
                expect(page.locator('[data-action="set.restart"]')).to_be_enabled()
                expect(page.get_by_text('程序已重启', exact=True)).to_be_visible()
                assert len(posts) == 1
                fresh = service.wait_status(service.initial['instance_id'])
                assert fresh['pid'] == service.initial['pid'] and fresh['port'] == service.port
                assert call(service.base, '/api/config')[1]['session_minutes'] == 57
                page.screenshot(path=os.path.join(shots, 'service-restarted.png'), full_page=True)

                page.set_viewport_size({'width': 390, 'height': 844})
                page.screenshot(path=os.path.join(shots, 'service-mobile.png'), full_page=True)
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')

                # 明确失败保留页面并展示原因，允许用户纠正后操作。
                page.route('**/api/service/restart', lambda route: route.fulfill(status=500,
                           json={'error': 'server', 'msg': '测试：暂时无法重启'}))
                confirm()
                expect(page.get_by_text('测试：暂时无法重启', exact=True)).to_be_visible()
                expect(page.locator('[data-action="set.restart"]')).to_be_enabled()
                assert service.wait_status()['instance_id'] == fresh['instance_id']
                page.unroute('**/api/service/restart')

                # 只模拟接受但未完成的请求，用浏览器虚拟时间验证45秒截止和复查。
                page.route('**/api/service/restart', lambda route: route.fulfill(
                           json={'restarting': True, 'instance_id': fresh['instance_id']}))
                page.clock.install()
                confirm()
                expect(page.get_by_text('正在等待程序重新上线，完成后页面会自动刷新…', exact=True)).to_be_visible()
                page.clock.fast_forward(46000)
                expect(page.get_by_text('暂未确认程序重新上线。可以检查运行状态，或刷新页面查看。', exact=True)).to_be_visible(timeout=5000)
                expect(page.locator('[data-action="set.restart"]')).to_be_disabled()
                sent = len(posts)
                page.click('[data-action="set.checkRestart"]')
                expect(page.locator('[data-action="set.restart"]')).to_be_disabled()
                assert len(posts) == sent
                page.screenshot(path=os.path.join(shots, 'service-waiting.png'), full_page=True)

                # 离页取消轮询；旧的等待不能重新导航或刷新当前页面。
                page.click('#nav a[data-page="dashboard"]')
                page.wait_for_selector('#panel-dashboard.is-active')
                count = len(polls)
                page.clock.fast_forward(50000)
                page.wait_for_timeout(100)
                assert len(polls) == count and page.url.endswith('#/dashboard')
                page.unroute('**/api/service/restart')

                # 真请求已被接受，但客户端收不到回包；只查询状态也能确认重启。
                def lose_reply(route):
                    route.fetch()
                    route.abort()
                page.route('**/api/service/restart', lose_reply)
                open_settings()
                with page.expect_navigation(wait_until='domcontentloaded', timeout=20000):
                    confirm()
                expect(page.locator('[data-action="set.restart"]')).to_be_enabled()
                assert len(posts) == sent + 1
                assert service.wait_status()['instance_id'] != fresh['instance_id']
                assert not errors, errors
                browser.close()
            print('PASS：设置取消/确认、真实重启与持久配置、手机布局、失败/超时/复查、离页取消和丢失回包')
        finally:
            service.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--shots', default='/tmp/clms-e2e-service')
    run(parser.parse_args().shots)

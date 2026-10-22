import os
import pytest
from test_browser import live_server
pytestmark=pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS')!='1',reason='Opt-in browser test')

@pytest.mark.parametrize('width',[1365,390])
def test_bulk_approval_preview_confirm_and_audit(live_server,width):
    from playwright.sync_api import sync_playwright,expect
    with sync_playwright() as p:
        browser=p.chromium.launch(channel=os.getenv('BROWSER_CHANNEL','chromium'),headless=True)
        page=browser.new_page(viewport={'width':width,'height':844})
        page.goto(live_server+'/login')
        page.locator('[name=email]').fill('admin@example.com')
        page.locator('[name=password]').fill('Testing123')
        page.get_by_role('button',name='登录',exact=True).click()
        page.wait_for_url(lambda url:'/login' not in str(url))
        page.goto(live_server+'/admin/enrollments')
        page.locator('#bulk-all').check()
        page.locator('#bulk-preview').click()
        expect(page.locator('#bulk-confirm')).to_be_visible()
        expect(page.locator('#bulk-summary')).to_contain_text('共 1 条')
        page.locator('#bulk-confirm').click()
        expect(page.locator('#bulk-summary')).to_contain_text('完成 1 条')
        page.goto(live_server+'/admin/audit?event_type=bulk.approve')
        expect(page.get_by_text('批量操作完成',exact=False).filter(visible=True).first).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        browser.close()

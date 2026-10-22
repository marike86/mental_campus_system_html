import os
from pathlib import Path
import pytest
from test_browser import live_server
pytestmark=pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS')!='1',reason='Opt-in browser acceptance')

@pytest.mark.parametrize('width',[320,390,768,1440])
def test_responsive_navigation_and_pages(live_server,width):
    from playwright.sync_api import sync_playwright,expect
    with sync_playwright() as p:
        browser=p.chromium.launch(channel=os.getenv('BROWSER_CHANNEL','chromium'),headless=True)
        page=browser.new_page(viewport={'width':width,'height':900})
        page.goto(live_server+'/login');page.locator('[name=email]').fill('admin@example.com');page.locator('[name=password]').fill('Testing123');page.get_by_role('button',name='登录',exact=True).click();page.wait_for_url(lambda url:'/login' not in str(url))
        errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        for path in ['/admin/operations','/admin/users','/admin/audit','/admin/enrollments','/review/pending']:
            page.goto(live_server+path)
            expect(page.locator('main')).to_be_visible()
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),path
        if width<768:
            button=page.locator('#mobile-menu-btn');button.click()
            expect(button).to_have_attribute('aria-expanded','true')
            expect(page.locator('#mobile-close')).to_be_focused()
            page.keyboard.press('Escape');expect(button).to_have_attribute('aria-expanded','false');expect(button).to_be_focused()
            page.set_viewport_size({'width':1024,'height':900});page.set_viewport_size({'width':width,'height':900})
            expect(page.locator('#sidebar')).to_have_js_property('inert',True)
        page.goto(live_server+'/admin/operations')
        output=Path(os.getenv('BROWSER_ARTIFACTS','../../outputs'));output.mkdir(parents=True,exist_ok=True)
        page.screenshot(path=str(output/f'interface-admin-{width}.png'),full_page=True)
        assert not errors
        browser.close()

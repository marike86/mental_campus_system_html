"""Real browser acceptance. RUN_BROWSER_TESTS=1 python -m pytest test_browser.py -v."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
import pytest

pytestmark=pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS')!='1',reason='Opt-in real-browser acceptance')
ROOT=Path(__file__).parent

SEED='''
from database import SessionLocal
from models.user import User
from models.bootcamp import Bootcamp
from models.enrollment import Enrollment
from models.day_form import DayForm
from auth import get_password_hash
from services.versions import publish
from services.clock import local_date
from datetime import timedelta
with SessionLocal() as db:
    people=[]
    hashed=get_password_hash('Testing123')
    for role in ('admin','reviewer','user'):
        person=User(email=role+'@example.com',nickname=role,role=role,hashed_password=hashed,is_active=True,max_concurrent_tasks=10)
        db.add(person);people.append(person)
    db.flush()
    camp=Bootcamp(name='浏览器验收训练营',days=2,is_active=True,created_by=people[0].id)
    db.add(camp);db.flush()
    reading=[dict(id='reading',type='reading',label='阅读材料',content='觉察今天的感受。'),dict(id='reflection',type='text',label='今天的感受',required=True),dict(id='choice',type='single',label='是否完成阅读',options=['是','否'],correct='是')]
    for day,questions in [(1,reading),(2,[dict(id='text',type='text',label='收获',required=True),dict(id='score',type='likert',label='程度',min=0,max=5,required=True)])]:
        form=DayForm(bootcamp_id=camp.id,day_number=day,questions=questions)
        db.add(form);db.flush();publish(db,form,people[0].id)
    db.add(Enrollment(user_id=people[2].id,bootcamp_id=camp.id,start_date=local_date()-timedelta(days=1),status='approved'))
    db.commit()
'''


@pytest.fixture
def live_server(tmp_path):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    env=dict(os.environ,DATABASE_URL='sqlite:///'+(tmp_path/'browser.db').as_posix(),DEBUG='True',ADMIN_EMAIL='admin@example.com',PYTHONDONTWRITEBYTECODE='1',PYTHONIOENCODING='utf-8')
    for args in [('migrate.py',),('-c',SEED)]:
        result=subprocess.run([sys.executable,*args],cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace')
        assert result.returncode==0,result.stderr
    log=(tmp_path/'server.log').open('w',encoding='utf-8')
    server=subprocess.Popen([sys.executable,'-m','uvicorn','main:app','--host','127.0.0.1','--port',str(port)],cwd=ROOT,env=env,stdout=log,stderr=log,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    url=f'http://127.0.0.1:{port}'
    try:
        for _ in range(100):
            if server.poll() is not None:
                pytest.fail((tmp_path/'server.log').read_text(encoding='utf-8'))
            try:
                urllib.request.urlopen(url,timeout=.5).close();break
            except OSError:time.sleep(.1)
        else:pytest.fail('Server did not start')
        yield url
    finally:
        server.terminate();server.wait(timeout=10);log.close()


@pytest.mark.parametrize('viewport',[dict(width=1365,height=900),dict(width=390,height=844)],ids=['desktop','mobile'])
def test_three_role_learning_review_and_operations(live_server,viewport,tmp_path):
    from playwright.sync_api import sync_playwright,expect
    with sync_playwright() as p:
        browser=p.chromium.launch(channel=os.getenv('BROWSER_CHANNEL','msedge'),headless=True)
        contexts=[browser.new_context(viewport=viewport) for _ in range(3)]
        student,reviewer,admin=[context.new_page() for context in contexts]
        local_errors=[]
        for page in (student,reviewer,admin):
            page.on('response',lambda response:local_errors.append(response.url) if response.url.startswith(live_server) and response.status>=500 else None)
        def login(page,role):
            page.goto(live_server+'/login')
            page.locator('[name=email]').fill(role+'@example.com')
            page.locator('[name=password]').fill('Testing123')
            page.get_by_role('button',name='登录',exact=True).click()
            page.wait_for_url(lambda url:'/login' not in str(url))
        login(student,'user');login(reviewer,'reviewer');login(admin,'admin')
        student.goto(live_server+'/user/form/1/1')
        student.get_by_role('button',name='开始学习',exact=True).click()
        student.locator('textarea').fill('浏览器草稿')
        student.reload();expect(student.locator('textarea')).to_have_value('浏览器草稿')
        student.locator('input[value="是"]').check()
        student.get_by_role('button',name='验证答案',exact=True).click()
        student.get_by_role('button',name='完成并提交').click()
        student.get_by_role('button',name='提交表单',exact=True).click()
        expect(student).to_have_url(__import__('re').compile('.*/user/history/1.*'))
        reviewer.goto(live_server+'/review/pending')
        reviewer.get_by_role('button',name='领取任务',exact=True).click()
        expect(reviewer.get_by_text('浏览器草稿',exact=True)).to_be_visible()
        reviewer.locator('[name=comment]').fill('请补充一个具体例子')
        reviewer.get_by_role('button',name='审核不通过',exact=True).click()
        student.goto(live_server+'/user/notifications')
        student.get_by_role('link',name='修改后重提',exact=True).click()
        expect(student.locator('textarea')).to_have_value('浏览器草稿')
        student.locator('textarea').fill('具体例子：今天散步后更轻松')
        student.get_by_role('button',name='验证答案',exact=True).click()
        student.get_by_role('button',name='完成并提交').click()
        student.get_by_role('button',name='提交表单',exact=True).click()
        admin.goto(live_server+'/admin/assignments?view=all')
        admin.get_by_role('link',name='查看 / 审核',exact=True).click()
        admin.get_by_role('button',name='审核通过',exact=True).click()
        student.goto(live_server+'/user/course/1')
        expect(student.get_by_text('已完成',exact=True)).to_be_visible()
        student.goto(live_server+'/user/form/1/2')
        student.get_by_role('button',name='开始学习',exact=True).click()
        student.locator('[name=q_text]').fill('普通表单也保存草稿')
        student.locator('[for=likert_score_0]').click()
        student.reload();expect(student.locator('[name=q_text]')).to_have_value('普通表单也保存草稿')
        expect(student.locator('#likert_score_0')).to_be_checked()
        student.goto(live_server+'/user/history/1')
        expect(student.get_by_text('浏览器草稿',exact=True)).to_be_visible()
        expect(student.get_by_text('具体例子：今天散步后更轻松',exact=True)).to_be_visible()
        admin.goto(live_server+'/admin/operations?camp=&batch=')
        expect(admin.get_by_role('heading',name='训练营运营',exact=True)).to_be_visible()
        admin.get_by_role('button',name='查看',exact=True).click()
        expect(admin.get_by_role('heading',name='训练营运营',exact=True)).to_be_visible()
        folder=Path(os.environ.get('BROWSER_ARTIFACTS',str(tmp_path)))
        folder.mkdir(parents=True,exist_ok=True)
        for name,page in [('student',student),('reviewer',reviewer),('admin',admin)]:
            page.screenshot(path=str(folder/f'{name}-{viewport["width"]}.png'),full_page=True)
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'),name
        assert not local_errors,local_errors
        browser.close()

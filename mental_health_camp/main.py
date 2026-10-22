import os
import importlib
import pkgutil
import threading
import logging
from datetime import time
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from database import init_db, get_db
from config import APP_NAME, APP_DESCRIPTION, ADMIN_EMAIL, ADMIN_PASSWORD, ADMIN_NICKNAME, NOTIFICATION_HOUR, NOTIFICATION_MINUTE, DEBUG
from templates_config import templates
from passlib.context import CryptContext
from sqlalchemy.orm import Session

logging.basicConfig(
    level=logging.DEBUG if DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title=APP_NAME)

static_dir = os.path.join(os.path.dirname(__file__), "static")

app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://unpkg.com; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "font-src 'self'; "
        "connect-src 'self'; "
        "frame-ancestors 'none';"
    )
    # 确保每个响应都设置CSRF cookie
    from utils.csrf import CSRF_COOKIE_NAME, get_or_create_csrf_token
    if CSRF_COOKIE_NAME not in request.cookies:
        token = get_or_create_csrf_token(request)
        response.set_cookie(
            CSRF_COOKIE_NAME, token,
            httponly=False,
            secure=not DEBUG,
            samesite="strict",
            max_age=86400,
        )
    return response


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if 300 <= exc.status_code < 400 and exc.headers and exc.headers.get("Location"):
        return RedirectResponse(exc.headers["Location"], status_code=exc.status_code, headers=exc.headers)
    if exc.status_code == 404:
        return templates.TemplateResponse("index.html", {
            "request": request,
            "app_name": APP_NAME,
            "app_description": APP_DESCRIPTION,
            "error": "页面不存在",
        }, status_code=404)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers)


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.exception("未处理的异常 [%s %s]: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "服务器内部错误，请稍后重试"},
    )


def register_routes():
    import routes
    package = routes
    registered = 0
    for importer, modname, ispkg in pkgutil.iter_modules(package.__path__):
        if modname.startswith("_"):
            continue
        try:
            module = importlib.import_module(f"routes.{modname}")
            if hasattr(module, "router"):
                app.include_router(module.router)
                registered += 1
        except Exception as e:
            logger.error("加载路由模块 '%s' 失败: %s", modname, e)
    logger.info("成功注册 %d 个路由模块", registered)


@app.on_event("startup")
def startup():
    try:
        init_db()
    except Exception as e:
        logger.error("数据库初始化失败: %s", e)
        raise
    try:
        _migrate_database()
    except Exception as e:
        logger.error("数据库迁移失败: %s", e)
    try:
        _create_admin_if_needed()
    except Exception as e:
        logger.error("管理员账号创建失败: %s", e)
    try:
        _init_default_badges()
    except Exception as e:
        logger.error("默认徽章初始化失败: %s", e)
    try:
        register_routes()
    except Exception as e:
        logger.error("路由注册失败: %s", e)
        raise
    _start_notification_scheduler()


def _migrate_database():
    """添加新字段到现有表"""
    from sqlalchemy import text
    db = next(get_db())
    try:
        # 检查 submissions 表是否有 review_status 列
        result = db.execute(text("PRAGMA table_info(submissions)"))
        columns = [row[1] for row in result]
        if 'review_status' not in columns:
            db.execute(text("ALTER TABLE submissions ADD COLUMN review_status VARCHAR DEFAULT 'approved' NOT NULL"))
            logger.info("已添加 submissions.review_status 列")
        if 'reviewer_id' not in columns:
            db.execute(text("ALTER TABLE submissions ADD COLUMN reviewer_id INTEGER"))
            logger.info("已添加 submissions.reviewer_id 列")
        if 'review_comment' not in columns:
            db.execute(text("ALTER TABLE submissions ADD COLUMN review_comment TEXT"))
            logger.info("已添加 submissions.review_comment 列")
        if 'reviewed_at' not in columns:
            db.execute(text("ALTER TABLE submissions ADD COLUMN reviewed_at DATETIME"))
            logger.info("已添加 submissions.reviewed_at 列")
        # 检查 enrollments 表是否有 status 列
        result2 = db.execute(text("PRAGMA table_info(enrollments)"))
        columns2 = [row[1] for row in result2]
        if 'status' not in columns2:
            db.execute(text("ALTER TABLE enrollments ADD COLUMN status VARCHAR DEFAULT 'approved' NOT NULL"))
            logger.info("已添加 enrollments.status 列")
        # 检查 users 表是否有审核员相关字段
        result3 = db.execute(text("PRAGMA table_info(users)"))
        columns3 = [row[1] for row in result3]
        if 'specialty' not in columns3:
            db.execute(text("ALTER TABLE users ADD COLUMN specialty VARCHAR"))
            logger.info("已添加 users.specialty 列")
        if 'is_active' not in columns3:
            db.execute(text("ALTER TABLE users ADD COLUMN is_active BOOLEAN DEFAULT 1"))
            logger.info("已添加 users.is_active 列")
        if 'max_concurrent_tasks' not in columns3:
            db.execute(text("ALTER TABLE users ADD COLUMN max_concurrent_tasks INTEGER DEFAULT 10"))
            logger.info("已添加 users.max_concurrent_tasks 列")
        # 创建 review_assignments 表（如果不存在）
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS review_assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                submission_id INTEGER NOT NULL,
                reviewer_id INTEGER NOT NULL,
                assigned_by INTEGER,
                assignment_type VARCHAR DEFAULT 'auto' NOT NULL,
                status VARCHAR DEFAULT 'pending' NOT NULL,
                assigned_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                completed_at DATETIME,
                FOREIGN KEY (submission_id) REFERENCES submissions(id),
                FOREIGN KEY (reviewer_id) REFERENCES users(id),
                FOREIGN KEY (assigned_by) REFERENCES users(id)
            )
        """))
        logger.info("已创建 review_assignments 表")
        db.commit()
    except Exception as e:
        logger.warning("数据库迁移检查: %s", e)
        db.rollback()
    finally:
        db.close()

def _create_admin_if_needed():
    from models.user import User
    db = next(get_db())
    try:
        existing = db.query(User).filter(User.email == ADMIN_EMAIL).first()
        if not existing:
            pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
            admin = User(
                email=ADMIN_EMAIL,
                nickname=ADMIN_NICKNAME,
                hashed_password=pwd_context.hash(ADMIN_PASSWORD),
                role="admin"
            )
            db.add(admin)
            db.commit()
    finally:
        db.close()

def _init_default_badges():
    from models.badge import Badge
    db = next(get_db())
    try:
        default_badges = [
            {"name": "初次打卡", "description": "首次完成表单提交", "icon": "🎉", "criteria": {"type": "first_submission"}},
            {"name": "连续3天", "description": "连续打卡3天", "icon": "🔥", "criteria": {"type": "streak", "days": 3}},
            {"name": "连续7天", "description": "连续打卡7天", "icon": "⚡", "criteria": {"type": "streak", "days": 7}},
            {"name": "训练营毕业", "description": "完成整个训练营", "icon": "🎓", "criteria": {"type": "bootcamp_complete"}},
        ]
        for bdata in default_badges:
            existing = db.query(Badge).filter(Badge.name == bdata["name"]).first()
            if not existing:
                badge = Badge(**bdata)
                db.add(badge)
        db.commit()
    finally:
        db.close()

def _start_notification_scheduler():
    def scheduler_loop():
        import time as _time
        from datetime import datetime
        while True:
            now = datetime.now()
            target = now.replace(hour=NOTIFICATION_HOUR, minute=NOTIFICATION_MINUTE, second=0, microsecond=0)
            if now >= target:
                from datetime import timedelta
                target += timedelta(days=1)
            wait_seconds = (target - now).total_seconds()
            if wait_seconds > 0:
                _time.sleep(wait_seconds)
            try:
                from routes.notification import check_and_send_reminders
                db = next(get_db())
                try:
                    count = check_and_send_reminders(db)
                    logger.info(f"提醒邮件发送完毕，共 {count} 封")
                finally:
                    db.close()
            except Exception as e:
                logger.error(f"通知调度出错: {e}")
    t = threading.Thread(target=scheduler_loop, daemon=True)
    t.start()

@app.get("/", include_in_schema=False)
async def root(request: Request):
    return templates.TemplateResponse("index.html", {
        "request": request,
        "app_name": APP_NAME,
        "app_description": APP_DESCRIPTION,
    })

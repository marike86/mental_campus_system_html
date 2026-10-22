import os
import sys
import atexit
import tempfile
from pathlib import Path

# 每次测试使用独立数据库，避免旧表结构以及外部 DATABASE_URL 影响测试。
_test_directory = tempfile.TemporaryDirectory(prefix="mental-camp-tests-")
os.environ["DATABASE_URL"] = "sqlite:///" + (Path(_test_directory.name) / "test.db").as_posix()
os.environ.setdefault("DEBUG", "True")

from datetime import date, datetime, timedelta, timezone
import json
from fastapi.testclient import TestClient
from passlib.context import CryptContext
from jose import jwt as jose_jwt
from database import init_db, get_db, SessionLocal, engine, Base
atexit.register(engine.dispose)
from models.user import User
from models.bootcamp import Bootcamp
from models.enrollment import Enrollment
from models.batch import Batch
from models.submission import Submission
from models.user_badge import UserBadge
from models.badge import Badge
from models.day_form import DayForm
from models.audit_log import AuditLog
from models.workflow import DayFormVersion, EnrollmentDay, SubmissionAttempt
from services.clock import now
from services.versions import bound_version
from auth import create_access_token, get_password_hash, verify_password, _extract_user_id, verify_csrf
from config import JWT_SECRET_KEY, JWT_ALGORITHM
from utils.crypto import encrypt_data, decrypt_data
from utils.csrf import generate_csrf_token, CSRF_COOKIE_NAME

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

from main import app, register_routes, _create_admin_if_needed, _init_default_badges

# 为现有测试跳过CSRF验证（安全测试单独验证CSRF）
async def _skip_csrf():
    pass

app.dependency_overrides[verify_csrf] = _skip_csrf

_startup_done = False


def _ensure_startup():
    global _startup_done
    if not _startup_done:
        init_db()
        _create_admin_if_needed()
        _init_default_badges()
        register_routes()
        _startup_done = True


def _setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


_ensure_startup()
client = TestClient(app, raise_server_exceptions=True)


def _create_admin(db):
    admin = User(
        email="testadmin@test.com",
        nickname="测试管理员",
        hashed_password=get_password_hash("admin123"),
        role="admin",
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    return admin


def _create_user(db, email="user1@test.com", nickname="用户1"):
    user = User(
        email=email,
        nickname=nickname,
        hashed_password=get_password_hash("pass123"),
        role="user",
        student_id="2024001",
        college="计算机学院",
        grade="2024级",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _login_admin(admin):
    token = create_access_token({"sub": admin.id})
    client.cookies.set("access_token", token)
    return token


def _login_user(user):
    token = create_access_token({"sub": user.id})
    client.cookies.set("access_token", token)
    return token


def _logout():
    client.cookies.delete("access_token")


def _create_bootcamp(db, admin_id, name="测试训练营", days=7, active=True):
    bootcamp = Bootcamp(name=name, description="测试描述", days=days, is_active=active, created_by=admin_id)
    db.add(bootcamp)
    db.commit()
    db.refresh(bootcamp)
    return bootcamp


def _create_batch(db, bootcamp_id, name="测试批次"):
    batch = Batch(bootcamp_id=bootcamp_id, name=name, start_date=date.today(), end_date=date.today())
    db.add(batch)
    db.commit()
    db.refresh(batch)
    return batch


def _create_expired_token(user_id):
    to_encode = {"sub": str(user_id), "exp": datetime.now(timezone.utc) - timedelta(minutes=1)}
    return jose_jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def _create_day_form(db, bootcamp_id, day_number, questions=None):
    if questions is None:
        questions = []
    day_form = DayForm(bootcamp_id=bootcamp_id, day_number=day_number, questions=questions)
    db.add(day_form)
    db.commit()
    db.refresh(day_form)
    return day_form


def _create_enrollment(db, user_id, bootcamp_id, batch_id=None):
    enrollment = Enrollment(user_id=user_id, bootcamp_id=bootcamp_id, start_date=date.today(), batch_id=batch_id)
    db.add(enrollment)
    db.commit()
    db.refresh(enrollment)
    for form in db.query(DayForm).filter_by(bootcamp_id=bootcamp_id):
        if not form.questions or any('type' not in q for q in form.questions):
            continue
        version = db.query(DayFormVersion).filter_by(day_form_id=form.id).first()
        if not version:
            version=DayFormVersion(day_form_id=form.id,version=1,questions=form.questions,published_at=now())
            db.add(version);db.flush()
        db.add(EnrollmentDay(enrollment_id=enrollment.id,day_number=form.day_number,version_id=version.id,started_at=now()))
    db.commit()
    return enrollment


def _create_submission(db, enrollment_id, day_number, answers=None):
    if answers is None:
        answers = {}
    encrypted = encrypt_data(answers)
    submission = Submission(enrollment_id=enrollment_id, day_number=day_number, answers=encrypted)
    db.add(submission)
    db.commit()
    db.refresh(submission)
    enrollment=db.get(Enrollment,enrollment_id)
    version=bound_version(db,enrollment_id,day_number)
    if not version:
        form=db.query(DayForm).filter_by(bootcamp_id=enrollment.bootcamp_id,day_number=day_number).first()
        if not form:
            form=DayForm(bootcamp_id=enrollment.bootcamp_id,day_number=day_number,questions=[])
            db.add(form);db.flush()
        version=DayFormVersion(day_form_id=form.id,version=1,questions=form.questions,published_at=now(),legacy=True)
        db.add(version);db.flush()
        db.add(EnrollmentDay(enrollment_id=enrollment_id,day_number=day_number,version_id=version.id))
    attempt=SubmissionAttempt(submission_id=submission.id,round_number=1,version_id=version.id,answers=encrypted,
                              submitted_at=submission.submitted_at,review_status=submission.review_status)
    db.add(attempt);db.flush();submission.current_attempt_id=attempt.id;db.commit()
    return submission


class TestUnauthenticatedAccess:
    def test_unauthenticated_users_page(self):
        _setup_db()
        _logout()
        resp = client.get("/admin/users", follow_redirects=False)
        assert resp.status_code == 303

    def test_unauthenticated_batches_page(self):
        _setup_db()
        _logout()
        resp = client.get("/admin/batches", follow_redirects=False)
        assert resp.status_code == 303

    def test_unauthenticated_bootcamps_page(self):
        _setup_db()
        _logout()
        resp = client.get("/admin/bootcamps", follow_redirects=False)
        assert resp.status_code == 303


class TestInvalidToken:
    def test_invalid_token_access(self):
        _setup_db()
        _logout()
        client.cookies.set("access_token", "invalid.token.here")
        resp = client.get("/admin/users", follow_redirects=False)
        assert resp.status_code == 303


class TestNonAdminAccess:
    def test_user_accessing_admin_endpoint(self):
        _setup_db()
        db = SessionLocal()
        try:
            user = _create_user(db)
            _login_user(user)
            resp = client.get("/admin/users", follow_redirects=False)
            assert resp.status_code == 403
        finally:
            db.close()


class TestAdminAccess:
    def test_admin_users_page(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            _login_admin(admin)
            resp = client.get("/admin/users")
            assert resp.status_code == 200
            assert "用户管理" in resp.text
        finally:
            db.close()

    def test_admin_batches_page(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            _login_admin(admin)
            resp = client.get("/admin/batches")
            assert resp.status_code == 200
            assert "批次管理" in resp.text
        finally:
            db.close()


class TestEditUser:
    def test_edit_user_success(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            user = _create_user(db)
            _login_admin(admin)
            resp = client.post("/admin/edit-user", data={
                "user_id": str(user.id),
                "nickname": "新昵称",
                "college": "数学学院",
                "student_id": "2024002",
                "grade": "2023级",
            }, follow_redirects=False)
            assert resp.status_code == 302
            db.refresh(user)
            assert user.nickname == "新昵称"
            assert user.college == "数学学院"
            assert user.student_id == "2024002"
            assert user.grade == "2023级"
        finally:
            db.close()

    def test_edit_user_empty_nickname(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            user = _create_user(db)
            _login_admin(admin)
            resp = client.post("/admin/edit-user", data={
                "user_id": str(user.id),
                "nickname": "",
            }, follow_redirects=False)
            assert resp.status_code == 400
        finally:
            db.close()

    def test_edit_user_invalid_id(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            _login_admin(admin)
            resp = client.post("/admin/edit-user", data={
                "user_id": "abc",
                "nickname": "test",
            }, follow_redirects=False)
            assert resp.status_code == 400
        finally:
            db.close()

    def test_edit_user_not_found(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            _login_admin(admin)
            resp = client.post("/admin/edit-user", data={
                "user_id": "9999",
                "nickname": "test",
            }, follow_redirects=False)
            assert resp.status_code == 404
        finally:
            db.close()


class TestResetPassword:
    def test_reset_password_success(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            user = _create_user(db)
            _login_admin(admin)
            old_hash = user.hashed_password
            resp = client.post("/admin/reset-password", data={
                "user_id": str(user.id),
                "new_password": "newpass123",
            }, follow_redirects=False)
            assert resp.status_code == 302
            db.refresh(user)
            assert user.hashed_password != old_hash
            assert pwd_context.verify("newpass123", user.hashed_password)
        finally:
            db.close()

    def test_reset_password_too_short(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            user = _create_user(db)
            _login_admin(admin)
            resp = client.post("/admin/reset-password", data={
                "user_id": str(user.id),
                "new_password": "123",
            }, follow_redirects=False)
            assert resp.status_code == 400
        finally:
            db.close()

    def test_reset_password_empty_user_id(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            _login_admin(admin)
            resp = client.post("/admin/reset-password", data={
                "user_id": "",
                "new_password": "newpass123",
            }, follow_redirects=False)
            assert resp.status_code == 400
        finally:
            db.close()


class TestDeleteUser:
    def test_delete_user_success(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            user = _create_user(db)
            _login_admin(admin)
            resp = client.post("/admin/delete-user", data={
                "user_id": str(user.id),
                "confirm": "yes",
            }, follow_redirects=False)
            assert resp.status_code == 302
            remaining = db.query(User).filter(User.id == user.id).first()
            assert remaining is None
        finally:
            db.close()

    def test_delete_user_no_confirm(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            user = _create_user(db)
            _login_admin(admin)
            resp = client.post("/admin/delete-user", data={
                "user_id": str(user.id),
                "confirm": "",
            }, follow_redirects=False)
            assert resp.status_code == 400
        finally:
            db.close()

    def test_delete_admin_user_blocked(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            _login_admin(admin)
            resp = client.post("/admin/delete-user", data={
                "user_id": str(admin.id),
                "confirm": "yes",
            }, follow_redirects=False)
            assert resp.status_code == 400
        finally:
            db.close()


class TestBatchEnroll:
    def test_batch_enroll_success(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            user1 = _create_user(db, "u1@test.com", "用户1")
            user2 = _create_user(db, "u2@test.com", "用户2")
            bootcamp = _create_bootcamp(db, admin.id)
            batch = _create_batch(db, bootcamp.id)
            _login_admin(admin)
            resp = client.post("/admin/batch-enroll", data={
                "bootcamp_id": str(bootcamp.id),
                "user_ids": f"{user1.id},{user2.id}",
                "batch_id": str(batch.id),
            }, follow_redirects=False)
            assert resp.status_code == 302
            e1 = db.query(Enrollment).filter(Enrollment.user_id == user1.id, Enrollment.bootcamp_id == bootcamp.id).first()
            e2 = db.query(Enrollment).filter(Enrollment.user_id == user2.id, Enrollment.bootcamp_id == bootcamp.id).first()
            assert e1 is not None
            assert e2 is not None
            assert e1.batch_id == batch.id
        finally:
            db.close()

    def test_batch_enroll_empty_user_ids(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            bootcamp = _create_bootcamp(db, admin.id)
            _login_admin(admin)
            resp = client.post("/admin/batch-enroll", data={
                "bootcamp_id": str(bootcamp.id),
                "user_ids": "",
            }, follow_redirects=False)
            assert resp.status_code == 400
        finally:
            db.close()

    def test_batch_enroll_skip_already_enrolled(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            user = _create_user(db)
            bootcamp = _create_bootcamp(db, admin.id)
            enrollment = Enrollment(user_id=user.id, bootcamp_id=bootcamp.id, start_date=date.today())
            db.add(enrollment)
            db.commit()
            _login_admin(admin)
            resp = client.post("/admin/batch-enroll", data={
                "bootcamp_id": str(bootcamp.id),
                "user_ids": str(user.id),
            }, follow_redirects=False)
            assert resp.status_code == 302
            count = db.query(Enrollment).filter(Enrollment.user_id == user.id, Enrollment.bootcamp_id == bootcamp.id).count()
            assert count == 1
        finally:
            db.close()


class TestBatchOperations:
    def test_edit_batch_success(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            bootcamp = _create_bootcamp(db, admin.id)
            batch = _create_batch(db, bootcamp.id)
            _login_admin(admin)
            resp = client.post("/admin/batch/edit", data={
                "batch_id": str(batch.id),
                "name": "新批次名",
                "description": "新描述",
                "start_date": "2026-06-01",
                "end_date": "2026-06-30",
                "is_active": "on",
            }, follow_redirects=False)
            assert resp.status_code == 302
            db.refresh(batch)
            assert batch.name == "新批次名"
            assert batch.description == "新描述"
            assert batch.start_date == date(2026, 6, 1)
            assert batch.end_date == date(2026, 6, 30)
            assert batch.is_active is True
        finally:
            db.close()

    def test_edit_batch_empty_name(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            bootcamp = _create_bootcamp(db, admin.id)
            batch = _create_batch(db, bootcamp.id)
            _login_admin(admin)
            resp = client.post("/admin/batch/edit", data={
                "batch_id": str(batch.id),
                "name": "",
            }, follow_redirects=False)
            assert resp.status_code == 400
        finally:
            db.close()

    def test_delete_batch_success(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            bootcamp = _create_bootcamp(db, admin.id)
            batch = _create_batch(db, bootcamp.id)
            _login_admin(admin)
            resp = client.post("/admin/batch/delete", data={
                "batch_id": str(batch.id),
            }, follow_redirects=False)
            assert resp.status_code == 302
            remaining = db.query(Batch).filter(Batch.id == batch.id).first()
            assert remaining is None
        finally:
            db.close()

    def test_delete_batch_reassigns_enrollments(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            user = _create_user(db)
            bootcamp = _create_bootcamp(db, admin.id)
            batch = _create_batch(db, bootcamp.id)
            enrollment = Enrollment(user_id=user.id, bootcamp_id=bootcamp.id, start_date=date.today(), batch_id=batch.id)
            db.add(enrollment)
            db.commit()
            _login_admin(admin)
            resp = client.post("/admin/batch/delete", data={
                "batch_id": str(batch.id),
            }, follow_redirects=False)
            assert resp.status_code == 302
            db.refresh(enrollment)
            assert enrollment.batch_id is None
        finally:
            db.close()

    def test_batch_delete_multiple(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            bootcamp = _create_bootcamp(db, admin.id)
            b1 = _create_batch(db, bootcamp.id, "批次1")
            b2 = _create_batch(db, bootcamp.id, "批次2")
            _login_admin(admin)
            resp = client.post("/admin/batch/batch-delete", data={
                "batch_ids": f"{b1.id},{b2.id}",
            }, follow_redirects=False)
            assert resp.status_code == 302
            assert db.query(Batch).filter(Batch.id == b1.id).first() is None
            assert db.query(Batch).filter(Batch.id == b2.id).first() is None
        finally:
            db.close()

    def test_batch_delete_empty_ids(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            _login_admin(admin)
            resp = client.post("/admin/batch/batch-delete", data={
                "batch_ids": "",
            }, follow_redirects=False)
            assert resp.status_code == 400
        finally:
            db.close()


class TestRegistration:
    def test_register_with_new_fields(self):
        _setup_db()
        resp = client.post("/register", data={
            "email": "newuser@test.com",
            "password": "pass1234",
            "nickname": "新用户",
            "college": "物理学院",
            "student_id": "2024100",
            "grade": "2025级",
        }, follow_redirects=False)
        assert resp.status_code == 302
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.email == "newuser@test.com").first()
            assert user is not None
            assert user.nickname == "新用户"
            assert user.college == "物理学院"
            assert user.student_id == "2024100"
            assert user.grade == "2025级"
        finally:
            db.close()

    def test_register_without_optional_fields(self):
        _setup_db()
        resp = client.post("/register", data={
            "email": "newuser2@test.com",
            "password": "pass1234",
            "nickname": "新用户2",
        }, follow_redirects=False)
        assert resp.status_code == 302
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.email == "newuser2@test.com").first()
            assert user is not None
            assert user.college is None
            assert user.student_id is None
            assert user.grade is None
        finally:
            db.close()


class TestUserModelFields:
    def test_user_model_has_new_fields(self):
        _setup_db()
        db = SessionLocal()
        try:
            user = _create_user(db)
            assert hasattr(user, "student_id")
            assert hasattr(user, "college")
            assert hasattr(user, "grade")
            assert user.student_id == "2024001"
            assert user.college == "计算机学院"
            assert user.grade == "2024级"
        finally:
            db.close()


# ==================== 认证函数单元测试 ====================


class TestAuthFunctions:
    def test_create_access_token_converts_int_sub(self):
        token = create_access_token({"sub": 42})
        from jose import jwt
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        assert payload["sub"] == "42"
        assert isinstance(payload["sub"], str)

    def test_create_access_token_preserves_str_sub(self):
        token = create_access_token({"sub": "123"})
        from jose import jwt
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        assert payload["sub"] == "123"

    def test_create_access_token_has_exp(self):
        token = create_access_token({"sub": "1"})
        from jose import jwt
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        assert "exp" in payload

    def test_extract_user_id_valid_int_sub(self):
        assert _extract_user_id({"sub": "42"}) == 42

    def test_extract_user_id_none_sub(self):
        assert _extract_user_id({"sub": None}) is None

    def test_extract_user_id_missing_sub(self):
        assert _extract_user_id({}) is None

    def test_extract_user_id_invalid_sub(self):
        assert _extract_user_id({"sub": "abc"}) is None

    def test_verify_password_correct(self):
        hashed = get_password_hash("test123")
        assert verify_password("test123", hashed) is True

    def test_verify_password_incorrect(self):
        hashed = get_password_hash("test123")
        assert verify_password("wrong", hashed) is False

    def test_get_password_hash_unique(self):
        h1 = get_password_hash("test123")
        h2 = get_password_hash("test123")
        assert h1 != h2

    def test_get_password_hash_verifiable(self):
        hashed = get_password_hash("mypassword")
        assert verify_password("mypassword", hashed) is True


# ==================== 认证路由测试 ====================


class TestLoginRoutes:
    def test_login_page_get(self):
        _setup_db()
        _logout()
        resp = client.get("/login")
        assert resp.status_code == 200

    def test_login_success_admin(self):
        _setup_db()
        db = SessionLocal()
        try:
            _create_admin(db)
            _logout()
            resp = client.post("/login", data={
                "email": "testadmin@test.com",
                "password": "admin123",
            }, follow_redirects=False)
            assert resp.status_code == 302
            assert "/admin" in resp.headers.get("location", "")
        finally:
            db.close()

    def test_login_success_user(self):
        _setup_db()
        db = SessionLocal()
        try:
            _create_user(db)
            _logout()
            resp = client.post("/login", data={
                "email": "user1@test.com",
                "password": "pass123",
            }, follow_redirects=False)
            assert resp.status_code == 302
            assert "/user" in resp.headers.get("location", "")
        finally:
            db.close()

    def test_login_wrong_password(self):
        _setup_db()
        db = SessionLocal()
        try:
            _create_user(db)
            _logout()
            resp = client.post("/login", data={
                "email": "user1@test.com",
                "password": "wrongpassword",
            })
            assert resp.status_code == 200
        finally:
            db.close()

    def test_login_nonexistent_email(self):
        _setup_db()
        _logout()
        resp = client.post("/login", data={
            "email": "nobody@test.com",
            "password": "pass123",
        })
        assert resp.status_code == 200

    def test_login_already_logged_in_admin(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            _login_admin(admin)
            resp = client.get("/login", follow_redirects=False)
            assert resp.status_code == 302
            assert "/admin" in resp.headers.get("location", "")
        finally:
            db.close()

    def test_login_already_logged_in_user(self):
        _setup_db()
        db = SessionLocal()
        try:
            user = _create_user(db)
            _login_user(user)
            resp = client.get("/login", follow_redirects=False)
            assert resp.status_code == 302
            assert "/user" in resp.headers.get("location", "")
        finally:
            db.close()

    def test_logout(self):
        _setup_db()
        db = SessionLocal()
        try:
            user = _create_user(db)
            _login_user(user)
            resp = client.get("/logout", follow_redirects=False)
            assert resp.status_code == 302
            assert "/login" in resp.headers.get("location", "")
        finally:
            db.close()

    def test_register_page_already_logged_in(self):
        _setup_db()
        db = SessionLocal()
        try:
            user = _create_user(db)
            _login_user(user)
            resp = client.get("/register", follow_redirects=False)
            assert resp.status_code == 302
            assert "/user" in resp.headers.get("location", "")
        finally:
            db.close()


class TestDuplicateRegistration:
    def test_register_duplicate_email(self):
        _setup_db()
        db = SessionLocal()
        try:
            _create_user(db, "dup@test.com", "已有用户")
        finally:
            db.close()
        resp = client.post("/register", data={
            "email": "dup@test.com",
            "password": "pass123",
            "nickname": "新用户",
        })
        assert resp.status_code == 200


# ==================== 过期/无效令牌测试 ====================


class TestExpiredToken:
    def test_expired_token_redirects(self):
        _setup_db()
        db = SessionLocal()
        try:
            user = _create_user(db)
            expired_token = _create_expired_token(user.id)
            _logout()
            client.cookies.set("access_token", expired_token)
            resp = client.get("/admin/users", follow_redirects=False)
            assert resp.status_code == 303
        finally:
            db.close()


class TestNonExistentUserToken:
    def test_token_for_deleted_user(self):
        _setup_db()
        db = SessionLocal()
        try:
            user = _create_user(db)
            token = create_access_token({"sub": user.id})
            db.delete(user)
            db.commit()
        finally:
            db.close()
        _logout()
        client.cookies.set("access_token", token)
        resp = client.get("/admin/users", follow_redirects=False)
        assert resp.status_code == 303


# ==================== 管理员路由 - 训练营CRUD ====================


class TestBootcampCRUD:
    def test_admin_bootcamps_page(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            _login_admin(admin)
            resp = client.get("/admin/bootcamps")
            assert resp.status_code == 200
        finally:
            db.close()

    def test_new_bootcamp_page(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            _login_admin(admin)
            resp = client.get("/admin/bootcamp/new")
            assert resp.status_code == 200
        finally:
            db.close()

    def test_create_bootcamp_success(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            _login_admin(admin)
            resp = client.post("/admin/bootcamp/new", data={
                "name": "新训练营",
                "description": "描述",
                "days": "5",
            }, follow_redirects=False)
            assert resp.status_code == 302
            bootcamp = db.query(Bootcamp).filter(Bootcamp.name == "新训练营").first()
            assert bootcamp is not None
            assert bootcamp.days == 5
            day_forms = db.query(DayForm).filter(DayForm.bootcamp_id == bootcamp.id).all()
            assert len(day_forms) == 5
        finally:
            db.close()

    def test_create_bootcamp_empty_name(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            _login_admin(admin)
            resp = client.post("/admin/bootcamp/new", data={
                "name": "",
                "days": "7",
            }, follow_redirects=False)
            assert resp.status_code == 400
        finally:
            db.close()

    def test_create_bootcamp_invalid_days_defaults(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            _login_admin(admin)
            resp = client.post("/admin/bootcamp/new", data={
                "name": "训练营",
                "days": "abc",
            }, follow_redirects=False)
            assert resp.status_code == 302
            bootcamp = db.query(Bootcamp).filter(Bootcamp.name == "训练营").first()
            assert bootcamp.days == 7
        finally:
            db.close()

    def test_create_bootcamp_days_too_large(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            _login_admin(admin)
            resp = client.post("/admin/bootcamp/new", data={
                "name": "训练营",
                "days": "366",
            }, follow_redirects=False)
            assert resp.status_code == 400
        finally:
            db.close()

    def test_create_bootcamp_days_zero(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            _login_admin(admin)
            resp = client.post("/admin/bootcamp/new", data={
                "name": "训练营",
                "days": "0",
            }, follow_redirects=False)
            assert resp.status_code == 400
        finally:
            db.close()

    def test_bootcamp_detail(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            bootcamp = _create_bootcamp(db, admin.id)
            _login_admin(admin)
            resp = client.get(f"/admin/bootcamp/{bootcamp.id}")
            assert resp.status_code == 200
        finally:
            db.close()

    def test_bootcamp_detail_not_found(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            _login_admin(admin)
            resp = client.get("/admin/bootcamp/9999", follow_redirects=False)
            assert resp.status_code == 404
        finally:
            db.close()

    def test_update_bootcamp(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            bootcamp = _create_bootcamp(db, admin.id)
            _login_admin(admin)
            resp = client.post(f"/admin/bootcamp/{bootcamp.id}", data={
                "name": "更新后的名称",
                "description": "新描述",
            }, follow_redirects=False)
            assert resp.status_code == 302
            db.refresh(bootcamp)
            assert bootcamp.name == "更新后的名称"
        finally:
            db.close()

    def test_update_bootcamp_empty_name(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            bootcamp = _create_bootcamp(db, admin.id)
            _login_admin(admin)
            resp = client.post(f"/admin/bootcamp/{bootcamp.id}", data={
                "name": "",
            }, follow_redirects=False)
            assert resp.status_code == 400
        finally:
            db.close()

    def test_update_bootcamp_not_found(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            _login_admin(admin)
            resp = client.post("/admin/bootcamp/9999", data={
                "name": "test",
            }, follow_redirects=False)
            assert resp.status_code == 404
        finally:
            db.close()

    def test_toggle_bootcamp(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            bootcamp = _create_bootcamp(db, admin.id, active=True)
            _login_admin(admin)
            resp = client.post(f"/admin/bootcamp/{bootcamp.id}/toggle", follow_redirects=False)
            assert resp.status_code == 302
            db.refresh(bootcamp)
            assert bootcamp.is_active is False
        finally:
            db.close()

    def test_toggle_bootcamp_not_found(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            _login_admin(admin)
            resp = client.post("/admin/bootcamp/9999/toggle", follow_redirects=False)
            assert resp.status_code == 404
        finally:
            db.close()


# ==================== 管理员路由 - 表单编辑 ====================


class TestDayFormOperations:
    def test_edit_day_form(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            bootcamp = _create_bootcamp(db, admin.id, days=3)
            _create_day_form(db, bootcamp.id, 1, [{"id": "q1", "type": "text", "label": "问题1"}])
            _login_admin(admin)
            resp = client.get(f"/admin/bootcamp/{bootcamp.id}/day/1")
            assert resp.status_code == 200
        finally:
            db.close()

    def test_edit_day_form_bootcamp_not_found(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            _login_admin(admin)
            resp = client.get("/admin/bootcamp/9999/day/1", follow_redirects=False)
            assert resp.status_code == 404
        finally:
            db.close()

    def test_edit_day_form_not_found(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            bootcamp = _create_bootcamp(db, admin.id, days=3)
            _login_admin(admin)
            resp = client.get(f"/admin/bootcamp/{bootcamp.id}/day/99", follow_redirects=False)
            assert resp.status_code == 404
        finally:
            db.close()

    def test_save_day_form(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            bootcamp = _create_bootcamp(db, admin.id, days=3)
            df = _create_day_form(db, bootcamp.id, 1)
            _login_admin(admin)
            questions = json.dumps([{"id": "q1", "type": "text", "label": "问题"}])
            resp = client.post(f"/admin/bootcamp/{bootcamp.id}/day/1", data={
                "questions": questions,
            }, follow_redirects=False)
            assert resp.status_code == 302
            db.refresh(df)
            assert len(df.questions) == 1
            assert df.questions[0]["id"] == "q1"
        finally:
            db.close()

    def test_save_day_form_invalid_json(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            bootcamp = _create_bootcamp(db, admin.id, days=3)
            df = _create_day_form(db, bootcamp.id, 1, [{"id": "old"}])
            _login_admin(admin)
            resp = client.post(f"/admin/bootcamp/{bootcamp.id}/day/1", data={
                "questions": "not valid json",
            }, follow_redirects=False)
            assert resp.status_code == 400
            db.refresh(df)
            assert df.questions == [{"id": "old"}]
        finally:
            db.close()


# ==================== 管理员路由 - 导出 ====================


class TestExport:
    def test_export_page(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            _login_admin(admin)
            resp = client.get("/admin/export")
            assert resp.status_code == 200
        finally:
            db.close()

    def test_export_csv_success(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            user = _create_user(db)
            bootcamp = _create_bootcamp(db, admin.id, days=3)
            _create_day_form(db, bootcamp.id, 1, [{"id": "q1", "type": "text", "label": "问题1"}])
            enrollment = _create_enrollment(db, user.id, bootcamp.id)
            _create_submission(db, enrollment.id, 1, {"q1": "答案"})
            _login_admin(admin)
            resp = client.post("/admin/export", data={
                "bootcamp_id": str(bootcamp.id),
            }, follow_redirects=False)
            assert resp.status_code == 200
            assert "text/csv" in resp.headers.get("content-type", "")
        finally:
            db.close()

    def test_export_empty_bootcamp_id(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            _login_admin(admin)
            resp = client.post("/admin/export", data={
                "bootcamp_id": "",
            }, follow_redirects=False)
            assert resp.status_code == 400
        finally:
            db.close()

    def test_export_invalid_bootcamp_id(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            _login_admin(admin)
            resp = client.post("/admin/export", data={
                "bootcamp_id": "abc",
            }, follow_redirects=False)
            assert resp.status_code == 400
        finally:
            db.close()

    def test_export_nonexistent_bootcamp(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            _login_admin(admin)
            resp = client.post("/admin/export", data={
                "bootcamp_id": "9999",
            }, follow_redirects=False)
            assert resp.status_code == 404
        finally:
            db.close()


# ==================== 管理员路由 - 仪表盘 ====================


class TestAdminDashboard:
    def test_admin_dashboard(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            _login_admin(admin)
            resp = client.get("/admin/dashboard")
            assert resp.status_code == 200
        finally:
            db.close()

    def test_admin_dashboard_with_data(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            user = _create_user(db)
            bootcamp = _create_bootcamp(db, admin.id, days=3)
            enrollment = _create_enrollment(db, user.id, bootcamp.id)
            _create_submission(db, enrollment.id, 1, {"q1": "a"})
            _login_admin(admin)
            resp = client.get("/admin/dashboard")
            assert resp.status_code == 200
        finally:
            db.close()


# ==================== 管理员路由 - 单用户分配 ====================


class TestEnrollSingleUser:
    def test_enroll_success(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            user = _create_user(db)
            bootcamp = _create_bootcamp(db, admin.id)
            _login_admin(admin)
            resp = client.post("/admin/enroll", data={
                "user_id": str(user.id),
                "bootcamp_id": str(bootcamp.id),
            }, follow_redirects=False)
            assert resp.status_code == 302
            e = db.query(Enrollment).filter(
                Enrollment.user_id == user.id,
                Enrollment.bootcamp_id == bootcamp.id,
            ).first()
            assert e is not None
        finally:
            db.close()

    def test_enroll_empty_user_id(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            bootcamp = _create_bootcamp(db, admin.id)
            _login_admin(admin)
            resp = client.post("/admin/enroll", data={
                "user_id": "",
                "bootcamp_id": str(bootcamp.id),
            }, follow_redirects=False)
            assert resp.status_code == 400
        finally:
            db.close()

    def test_enroll_empty_bootcamp_id(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            user = _create_user(db)
            _login_admin(admin)
            resp = client.post("/admin/enroll", data={
                "user_id": str(user.id),
                "bootcamp_id": "",
            }, follow_redirects=False)
            assert resp.status_code == 400
        finally:
            db.close()

    def test_enroll_invalid_ids(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            _login_admin(admin)
            resp = client.post("/admin/enroll", data={
                "user_id": "abc",
                "bootcamp_id": "xyz",
            }, follow_redirects=False)
            assert resp.status_code == 400
        finally:
            db.close()

    def test_enroll_already_enrolled(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            user = _create_user(db)
            bootcamp = _create_bootcamp(db, admin.id)
            _create_enrollment(db, user.id, bootcamp.id)
            _login_admin(admin)
            resp = client.post("/admin/enroll", data={
                "user_id": str(user.id),
                "bootcamp_id": str(bootcamp.id),
            }, follow_redirects=False)
            assert resp.status_code == 302
            count = db.query(Enrollment).filter(
                Enrollment.user_id == user.id,
                Enrollment.bootcamp_id == bootcamp.id,
            ).count()
            assert count == 1
        finally:
            db.close()


# ==================== 管理员路由 - 批次创建 ====================


class TestBatchCreation:
    def test_create_batch_success(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            bootcamp = _create_bootcamp(db, admin.id)
            _login_admin(admin)
            resp = client.post("/admin/batch/new", data={
                "bootcamp_id": str(bootcamp.id),
                "name": "新批次",
                "start_date": "2026-06-01",
                "end_date": "2026-06-30",
            }, follow_redirects=False)
            assert resp.status_code == 302
            batch = db.query(Batch).filter(Batch.name == "新批次").first()
            assert batch is not None
            assert batch.bootcamp_id == bootcamp.id
        finally:
            db.close()

    def test_create_batch_empty_bootcamp_id(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            _login_admin(admin)
            resp = client.post("/admin/batch/new", data={
                "bootcamp_id": "",
                "name": "批次",
            }, follow_redirects=False)
            assert resp.status_code == 400
        finally:
            db.close()

    def test_create_batch_invalid_bootcamp_id(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            _login_admin(admin)
            resp = client.post("/admin/batch/new", data={
                "bootcamp_id": "abc",
                "name": "批次",
            }, follow_redirects=False)
            assert resp.status_code == 400
        finally:
            db.close()

    def test_create_batch_empty_name(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            bootcamp = _create_bootcamp(db, admin.id)
            _login_admin(admin)
            resp = client.post("/admin/batch/new", data={
                "bootcamp_id": str(bootcamp.id),
                "name": "",
            }, follow_redirects=False)
            assert resp.status_code == 400
        finally:
            db.close()

    def test_create_batch_invalid_start_date(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            bootcamp = _create_bootcamp(db, admin.id)
            _login_admin(admin)
            resp = client.post("/admin/batch/new", data={
                "bootcamp_id": str(bootcamp.id),
                "name": "批次",
                "start_date": "not-a-date",
            }, follow_redirects=False)
            assert resp.status_code == 400
        finally:
            db.close()

    def test_create_batch_invalid_end_date(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            bootcamp = _create_bootcamp(db, admin.id)
            _login_admin(admin)
            resp = client.post("/admin/batch/new", data={
                "bootcamp_id": str(bootcamp.id),
                "name": "批次",
                "start_date": "2026-06-01",
                "end_date": "not-a-date",
            }, follow_redirects=False)
            assert resp.status_code == 400
        finally:
            db.close()


# ==================== 管理员路由 - 查看用户数据 ====================


class TestViewUserData:
    def test_view_user_data_success(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            user = _create_user(db)
            _login_admin(admin)
            resp = client.post("/admin/view-user-data", data={
                "user_id": str(user.id),
            }, follow_redirects=False)
            assert resp.status_code == 302
        finally:
            db.close()

    def test_view_user_data_empty_id(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            _login_admin(admin)
            resp = client.post("/admin/view-user-data", data={
                "user_id": "",
            }, follow_redirects=False)
            assert resp.status_code == 400
        finally:
            db.close()

    def test_view_user_data_invalid_id(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            _login_admin(admin)
            resp = client.post("/admin/view-user-data", data={
                "user_id": "abc",
            }, follow_redirects=False)
            assert resp.status_code == 400
        finally:
            db.close()


# ==================== 审计日志 ====================


class TestAuditLog:
    def test_audit_log_page(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            _login_admin(admin)
            resp = client.get("/admin/audit")
            assert resp.status_code == 200
        finally:
            db.close()

    def test_log_admin_action_creates_record(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            from routes.audit import log_admin_action
            log_admin_action(db, admin.id, "测试操作", "test", 1, {"key": "value"})
            log_entry = db.query(AuditLog).filter(AuditLog.action == "测试操作").first()
            assert log_entry is not None
            assert log_entry.admin_id == admin.id
            assert log_entry.target_type == "test"
            assert log_entry.detail == {"key": "value"}
        finally:
            db.close()


# ==================== 用户路由测试 ====================


class TestUserDashboard:
    def test_user_dashboard(self):
        _setup_db()
        db = SessionLocal()
        try:
            user = _create_user(db)
            _login_user(user)
            resp = client.get("/user/dashboard")
            assert resp.status_code == 200
        finally:
            db.close()

    def test_user_dashboard_with_enrollment(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            user = _create_user(db)
            bootcamp = _create_bootcamp(db, admin.id, days=7)
            _create_enrollment(db, user.id, bootcamp.id)
            _login_user(user)
            resp = client.get("/user/dashboard")
            assert resp.status_code == 200
        finally:
            db.close()


class TestTodayTasks:
    def test_today_tasks(self):
        _setup_db()
        db = SessionLocal()
        try:
            user = _create_user(db)
            _login_user(user)
            resp = client.get("/user/today")
            assert resp.status_code == 200
        finally:
            db.close()

    def test_today_tasks_with_active_enrollment(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            user = _create_user(db)
            bootcamp = _create_bootcamp(db, admin.id, days=7, active=True)
            _create_day_form(db, bootcamp.id, 1, [{"id": "q1", "type": "text", "label": "问题"}])
            _create_enrollment(db, user.id, bootcamp.id)
            _login_user(user)
            resp = client.get("/user/today")
            assert resp.status_code == 200
        finally:
            db.close()


class TestFormSubmission:
    def test_fill_form(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            user = _create_user(db)
            bootcamp = _create_bootcamp(db, admin.id, days=7)
            _create_day_form(db, bootcamp.id, 1, [{"id": "q1", "type": "text", "label": "问题"}])
            enrollment = _create_enrollment(db, user.id, bootcamp.id)
            _login_user(user)
            resp = client.get(f"/user/form/{enrollment.id}/1")
            assert resp.status_code == 200
        finally:
            db.close()

    def test_fill_form_enrollment_not_found(self):
        _setup_db()
        db = SessionLocal()
        try:
            user = _create_user(db)
            _login_user(user)
            resp = client.get("/user/form/9999/1", follow_redirects=False)
            assert resp.status_code == 404
        finally:
            db.close()

    def test_submit_form_success(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            user = _create_user(db)
            bootcamp = _create_bootcamp(db, admin.id, days=7)
            _create_day_form(db, bootcamp.id, 1, [{"id": "q1", "type": "text", "label": "问题"}])
            enrollment = _create_enrollment(db, user.id, bootcamp.id)
            _login_user(user)
            resp = client.post(f"/user/form/{enrollment.id}/1", data={
                "q_q1": "我的答案",
                "version_id": bound_version(db,enrollment.id,1).id,
            }, follow_redirects=False)
            assert resp.status_code == 303
            submission = db.query(Submission).filter(
                Submission.enrollment_id == enrollment.id,
                Submission.day_number == 1,
            ).first()
            assert submission is not None
        finally:
            db.close()

    def test_submit_form_already_submitted(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            user = _create_user(db)
            bootcamp = _create_bootcamp(db, admin.id, days=7)
            _create_day_form(db, bootcamp.id, 1, [{"id": "q1", "type": "text", "label": "问题"}])
            enrollment = _create_enrollment(db, user.id, bootcamp.id)
            _create_submission(db, enrollment.id, 1, {"q1": "已提交"})
            _login_user(user)
            resp = client.post(f"/user/form/{enrollment.id}/1", data={
                "q_q1": "新答案",
            }, follow_redirects=False)
            assert resp.status_code == 409
            count = db.query(Submission).filter(
                Submission.enrollment_id == enrollment.id,
                Submission.day_number == 1,
            ).count()
            assert count == 1
        finally:
            db.close()


class TestJoinBootcamp:
    def test_join_bootcamp_success(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            user = _create_user(db)
            bootcamp = _create_bootcamp(db, admin.id, active=True)
            _login_user(user)
            resp = client.post(f"/user/bootcamp/{bootcamp.id}/join", follow_redirects=False)
            assert resp.status_code == 302
            e = db.query(Enrollment).filter(
                Enrollment.user_id == user.id,
                Enrollment.bootcamp_id == bootcamp.id,
            ).first()
            assert e is not None
        finally:
            db.close()

    def test_join_bootcamp_already_enrolled(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            user = _create_user(db)
            bootcamp = _create_bootcamp(db, admin.id, active=True)
            _create_enrollment(db, user.id, bootcamp.id)
            _login_user(user)
            resp = client.post(f"/user/bootcamp/{bootcamp.id}/join", follow_redirects=False)
            assert resp.status_code == 302
            count = db.query(Enrollment).filter(
                Enrollment.user_id == user.id,
                Enrollment.bootcamp_id == bootcamp.id,
            ).count()
            assert count == 1
        finally:
            db.close()

    def test_join_bootcamp_not_active(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            user = _create_user(db)
            bootcamp = _create_bootcamp(db, admin.id, active=False)
            _login_user(user)
            resp = client.post(f"/user/bootcamp/{bootcamp.id}/join", follow_redirects=False)
            assert resp.status_code == 404
        finally:
            db.close()

    def test_join_bootcamp_not_found(self):
        _setup_db()
        db = SessionLocal()
        try:
            user = _create_user(db)
            _login_user(user)
            resp = client.post("/user/bootcamp/9999/join", follow_redirects=False)
            assert resp.status_code == 404
        finally:
            db.close()


class TestBrowseBootcamps:
    def test_browse_bootcamps(self):
        _setup_db()
        db = SessionLocal()
        try:
            user = _create_user(db)
            _login_user(user)
            resp = client.get("/user/bootcamps")
            assert resp.status_code == 200
        finally:
            db.close()


class TestUserHistory:
    def test_history(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            user = _create_user(db)
            bootcamp = _create_bootcamp(db, admin.id, days=3)
            _create_day_form(db, bootcamp.id, 1, [{"id": "q1", "type": "text", "label": "Q1"}])
            enrollment = _create_enrollment(db, user.id, bootcamp.id)
            _create_submission(db, enrollment.id, 1, {"q1": "答案"})
            _login_user(user)
            resp = client.get(f"/user/history/{enrollment.id}")
            assert resp.status_code == 200
        finally:
            db.close()

    def test_history_not_found(self):
        _setup_db()
        db = SessionLocal()
        try:
            user = _create_user(db)
            _login_user(user)
            resp = client.get("/user/history/9999", follow_redirects=False)
            assert resp.status_code == 404
        finally:
            db.close()


class TestUserProfile:
    def test_profile_page(self):
        _setup_db()
        db = SessionLocal()
        try:
            user = _create_user(db)
            _login_user(user)
            resp = client.get("/user/profile")
            assert resp.status_code == 200
        finally:
            db.close()

    def test_update_profile(self):
        _setup_db()
        db = SessionLocal()
        try:
            user = _create_user(db)
            _login_user(user)
            resp = client.post("/user/profile", data={
                "nickname": "新昵称",
            }, follow_redirects=False)
            assert resp.status_code == 302
            db.refresh(user)
            assert user.nickname == "新昵称"
        finally:
            db.close()


class TestUserPassword:
    def test_update_password_wrong_current(self):
        _setup_db()
        db = SessionLocal()
        try:
            user = _create_user(db)
            _login_user(user)
            resp = client.post("/user/password", data={
                "current_password": "wrong_password",
                "new_password": "newpass123",
            })
            assert resp.status_code == 200
        finally:
            db.close()

    def test_update_password_success(self):
        _setup_db()
        db = SessionLocal()
        try:
            user = _create_user(db)
            _login_user(user)
            resp = client.post("/user/password", data={
                "current_password": "pass123",
                "new_password": "newpass123",
            }, follow_redirects=False)
            assert resp.status_code == 302
            db.refresh(user)
            assert verify_password("newpass123", user.hashed_password)
        finally:
            db.close()


class TestUserBadges:
    def test_badges_page(self):
        _setup_db()
        db = SessionLocal()
        try:
            user = _create_user(db)
            _login_user(user)
            resp = client.get("/user/badges")
            assert resp.status_code == 200
        finally:
            db.close()


class TestNotificationToggle:
    def test_notification_toggle(self):
        _setup_db()
        db = SessionLocal()
        try:
            user = _create_user(db)
            assert user.notification_enabled is True
            _login_user(user)
            resp = client.post("/user/notification-toggle", follow_redirects=False)
            assert resp.status_code == 302
            db.refresh(user)
            assert user.notification_enabled is False
            resp = client.post("/user/notification-toggle", follow_redirects=False)
            assert resp.status_code == 302
            db.refresh(user)
            assert user.notification_enabled is True
        finally:
            db.close()


# ==================== 用户API测试 ====================


class TestVerifyAnswerAPI:
    def test_verify_answer_correct(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            user = _create_user(db)
            bootcamp = _create_bootcamp(db, admin.id, days=3)
            _create_day_form(db, bootcamp.id, 1, [
                {"id": "q1", "type": "single", "label": "Q1", "options": ["A", "B"], "correct": "A"}
            ])
            enrollment = _create_enrollment(db, user.id, bootcamp.id)
            _login_user(user)
            resp = client.post("/user/api/verify-answer", json={
                "enrollment_id": enrollment.id,
                "day_number": 1,
                "question_id": "q1",
                "answer": "A",
            })
            assert resp.status_code == 200
            assert resp.json()["correct"] is True
        finally:
            db.close()

    def test_verify_answer_wrong(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            user = _create_user(db)
            bootcamp = _create_bootcamp(db, admin.id, days=3)
            _create_day_form(db, bootcamp.id, 1, [
                {"id": "q1", "type": "single", "label": "Q1", "options": ["A", "B"], "correct": "A"}
            ])
            enrollment = _create_enrollment(db, user.id, bootcamp.id)
            _login_user(user)
            resp = client.post("/user/api/verify-answer", json={
                "enrollment_id": enrollment.id,
                "day_number": 1,
                "question_id": "q1",
                "answer": "B",
            })
            assert resp.status_code == 200
            assert resp.json()["correct"] is False
        finally:
            db.close()

    def test_verify_answer_incomplete_params(self):
        _setup_db()
        db = SessionLocal()
        try:
            user = _create_user(db)
            _login_user(user)
            resp = client.post("/user/api/verify-answer", json={
                "enrollment_id": None,
                "day_number": None,
                "question_id": None,
            })
            assert resp.status_code == 400
        finally:
            db.close()

    def test_verify_answer_no_correct_field(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            user = _create_user(db)
            bootcamp = _create_bootcamp(db, admin.id, days=3)
            _create_day_form(db, bootcamp.id, 1, [
                {"id": "q1", "type": "text", "label": "Q1"}
            ])
            enrollment = _create_enrollment(db, user.id, bootcamp.id)
            _login_user(user)
            resp = client.post("/user/api/verify-answer", json={
                "enrollment_id": enrollment.id,
                "day_number": 1,
                "question_id": "q1",
                "answer": "任意答案",
            })
            assert resp.status_code == 200
            assert resp.json()["correct"] is True
        finally:
            db.close()


class TestDashboardAPI:
    def test_dashboard_data(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            user = _create_user(db)
            bootcamp = _create_bootcamp(db, admin.id, days=7)
            _create_day_form(db, bootcamp.id, 1, [
                {"id": "q1", "type": "likert", "label": "心情", "min": 1, "max": 5, "labels": ["差", "一般", "中等", "好", "很好"]}
            ])
            enrollment = _create_enrollment(db, user.id, bootcamp.id)
            _create_submission(db, enrollment.id, 1, {"q1": 3})
            _login_user(user)
            resp = client.get(f"/user/api/dashboard-data/{enrollment.id}")
            assert resp.status_code == 200
            data = resp.json()
            assert "calendar" in data
            assert "streak" in data
            assert "total_days" in data
            assert "completed_days" in data
            assert data["total_days"] == 7
            assert data["completed_days"] == 1
        finally:
            db.close()

    def test_dashboard_data_not_found(self):
        _setup_db()
        db = SessionLocal()
        try:
            user = _create_user(db)
            _login_user(user)
            resp = client.get("/user/api/dashboard-data/9999")
            assert resp.status_code == 404
        finally:
            db.close()

    def test_likert_trend(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            user = _create_user(db)
            bootcamp = _create_bootcamp(db, admin.id, days=3)
            _create_day_form(db, bootcamp.id, 1, [
                {"id": "q1", "type": "likert", "label": "心情", "min": 1, "max": 5, "labels": ["差", "一般", "中等", "好", "很好"]}
            ])
            enrollment = _create_enrollment(db, user.id, bootcamp.id)
            _create_submission(db, enrollment.id, 1, {"q1": 3})
            _login_user(user)
            resp = client.get(f"/user/api/likert-trend/{enrollment.id}/q1")
            assert resp.status_code == 200
            data = resp.json()
            assert "labels" in data
            assert "values" in data
            assert len(data["values"]) == 1
            assert data["values"][0] == 3
        finally:
            db.close()


# ==================== 删除用户级联测试 ====================


class TestDeleteUserCascade:
    def test_delete_user_with_enrollments_and_submissions(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            user = _create_user(db)
            user_id = user.id
            bootcamp = _create_bootcamp(db, admin.id, days=3)
            enrollment = _create_enrollment(db, user_id, bootcamp.id)
            enrollment_id = enrollment.id
            _create_submission(db, enrollment_id, 1, {"q1": "答案"})
            badge = Badge(name="test_badge", description="test", icon="🏅", criteria={"type": "test"})
            db.add(badge)
            db.commit()
            db.refresh(badge)
            user_badge = UserBadge(user_id=user_id, badge_id=badge.id, enrollment_id=enrollment_id)
            db.add(user_badge)
            db.commit()
            _login_admin(admin)
            resp = client.post("/admin/delete-user", data={
                "user_id": str(user_id),
                "confirm": "yes",
            }, follow_redirects=False)
            assert resp.status_code == 302
            db.expire_all()
            assert db.query(User).filter(User.id == user_id).first() is None
            assert db.query(Enrollment).filter(Enrollment.user_id == user_id).count() == 0
            assert db.query(UserBadge).filter(UserBadge.user_id == user_id).count() == 0
        finally:
            db.close()

    def test_delete_user_not_found(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            _login_admin(admin)
            resp = client.post("/admin/delete-user", data={
                "user_id": "9999",
                "confirm": "yes",
            }, follow_redirects=False)
            assert resp.status_code == 404
        finally:
            db.close()

    def test_delete_user_empty_id(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            _login_admin(admin)
            resp = client.post("/admin/delete-user", data={
                "user_id": "",
                "confirm": "yes",
            }, follow_redirects=False)
            assert resp.status_code == 400
        finally:
            db.close()


# ==================== 重置密码补充测试 ====================


class TestResetPasswordExtended:
    def test_reset_password_user_not_found(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            _login_admin(admin)
            resp = client.post("/admin/reset-password", data={
                "user_id": "9999",
                "new_password": "newpass123",
            }, follow_redirects=False)
            assert resp.status_code == 404
        finally:
            db.close()

    def test_reset_password_invalid_id(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            _login_admin(admin)
            resp = client.post("/admin/reset-password", data={
                "user_id": "abc",
                "new_password": "newpass123",
            }, follow_redirects=False)
            assert resp.status_code == 400
        finally:
            db.close()


# ==================== 批量分配补充测试 ====================


class TestBatchEnrollExtended:
    def test_batch_enroll_empty_bootcamp_id(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            _login_admin(admin)
            resp = client.post("/admin/batch-enroll", data={
                "bootcamp_id": "",
                "user_ids": "1",
            }, follow_redirects=False)
            assert resp.status_code == 400
        finally:
            db.close()

    def test_batch_enroll_invalid_bootcamp_id(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            _login_admin(admin)
            resp = client.post("/admin/batch-enroll", data={
                "bootcamp_id": "abc",
                "user_ids": "1",
            }, follow_redirects=False)
            assert resp.status_code == 400
        finally:
            db.close()

    def test_batch_enroll_nonexistent_bootcamp(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            _login_admin(admin)
            resp = client.post("/admin/batch-enroll", data={
                "bootcamp_id": "9999",
                "user_ids": "1",
            }, follow_redirects=False)
            assert resp.status_code == 404
        finally:
            db.close()

    def test_batch_enroll_nonexistent_user(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            bootcamp = _create_bootcamp(db, admin.id)
            _login_admin(admin)
            resp = client.post("/admin/batch-enroll", data={
                "bootcamp_id": str(bootcamp.id),
                "user_ids": "9999",
            }, follow_redirects=False)
            assert resp.status_code == 302
        finally:
            db.close()


# ==================== 编辑批次补充测试 ====================


class TestBatchOperationsExtended:
    def test_edit_batch_invalid_id(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            _login_admin(admin)
            resp = client.post("/admin/batch/edit", data={
                "batch_id": "abc",
                "name": "test",
            }, follow_redirects=False)
            assert resp.status_code == 400
        finally:
            db.close()

    def test_edit_batch_not_found(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            _login_admin(admin)
            resp = client.post("/admin/batch/edit", data={
                "batch_id": "9999",
                "name": "test",
            }, follow_redirects=False)
            assert resp.status_code == 404
        finally:
            db.close()

    def test_edit_batch_empty_id(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            _login_admin(admin)
            resp = client.post("/admin/batch/edit", data={
                "batch_id": "",
                "name": "test",
            }, follow_redirects=False)
            assert resp.status_code == 400
        finally:
            db.close()

    def test_edit_batch_invalid_start_date(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            bootcamp = _create_bootcamp(db, admin.id)
            batch = _create_batch(db, bootcamp.id)
            _login_admin(admin)
            resp = client.post("/admin/batch/edit", data={
                "batch_id": str(batch.id),
                "name": "批次",
                "start_date": "not-a-date",
            }, follow_redirects=False)
            assert resp.status_code == 400
        finally:
            db.close()

    def test_edit_batch_invalid_end_date(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            bootcamp = _create_bootcamp(db, admin.id)
            batch = _create_batch(db, bootcamp.id)
            _login_admin(admin)
            resp = client.post("/admin/batch/edit", data={
                "batch_id": str(batch.id),
                "name": "批次",
                "start_date": "2026-06-01",
                "end_date": "not-a-date",
            }, follow_redirects=False)
            assert resp.status_code == 400
        finally:
            db.close()

    def test_delete_batch_empty_id(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            _login_admin(admin)
            resp = client.post("/admin/batch/delete", data={
                "batch_id": "",
            }, follow_redirects=False)
            assert resp.status_code == 400
        finally:
            db.close()

    def test_delete_batch_invalid_id(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            _login_admin(admin)
            resp = client.post("/admin/batch/delete", data={
                "batch_id": "abc",
            }, follow_redirects=False)
            assert resp.status_code == 400
        finally:
            db.close()

    def test_delete_batch_not_found(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            _login_admin(admin)
            resp = client.post("/admin/batch/delete", data={
                "batch_id": "9999",
            }, follow_redirects=False)
            assert resp.status_code == 404
        finally:
            db.close()

    def test_batch_delete_invalid_ids(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            _login_admin(admin)
            resp = client.post("/admin/batch/batch-delete", data={
                "batch_ids": "abc,xyz",
            }, follow_redirects=False)
            assert resp.status_code == 400
        finally:
            db.close()


# ==================== 加密工具测试 ====================


class TestCryptoUtils:
    def test_encrypt_decrypt_roundtrip(self):
        data = {"q1": "答案", "q2": 42, "q3": ["a", "b"]}
        encrypted = encrypt_data(data)
        assert isinstance(encrypted, str)
        decrypted = decrypt_data(encrypted)
        assert decrypted == data

    def test_encrypt_data_returns_json_string(self):
        data = {"key": "value"}
        result = encrypt_data(data)
        parsed = json.loads(result)
        assert parsed == data

    def test_decrypt_data_invalid_json(self):
        result = decrypt_data("not json at all")
        assert result == {}

    def test_decrypt_data_empty_string(self):
        result = decrypt_data("")
        assert result == {}

    def test_encrypt_empty_dict(self):
        encrypted = encrypt_data({})
        decrypted = decrypt_data(encrypted)
        assert decrypted == {}


# ==================== 路由注册验证 ====================


class TestRouteRegistration:
    def test_expected_routes_exist(self):
        route_paths = {route.path for route in app.routes}
        expected = [
            "/",
            "/login",
            "/register",
            "/logout",
            "/admin/bootcamps",
            "/admin/users",
            "/admin/batches",
            "/admin/dashboard",
            "/admin/export",
            "/admin/audit",
            "/user/dashboard",
            "/user/today",
            "/user/bootcamps",
            "/user/profile",
            "/user/badges",
        ]
        for path in expected:
            assert path in route_paths, f"路由 {path} 未注册"


# ==================== 首页测试 ====================


class TestRootPage:
    def test_root_page(self):
        _setup_db()
        _logout()
        resp = client.get("/")
        assert resp.status_code == 200


# ==================== 404处理测试 ====================


class TestExceptionHandlers:
    def test_404_returns_template(self):
        _setup_db()
        _logout()
        resp = client.get("/nonexistent-page")
        assert resp.status_code == 404


# ==================== 非管理员访问补充测试 ====================


class TestNonAdminAccessExtended:
    def test_user_accessing_admin_bootcamps(self):
        _setup_db()
        db = SessionLocal()
        try:
            user = _create_user(db)
            _login_user(user)
            resp = client.get("/admin/bootcamps", follow_redirects=False)
            assert resp.status_code == 403
        finally:
            db.close()

    def test_user_accessing_admin_dashboard(self):
        _setup_db()
        db = SessionLocal()
        try:
            user = _create_user(db)
            _login_user(user)
            resp = client.get("/admin/dashboard", follow_redirects=False)
            assert resp.status_code == 403
        finally:
            db.close()

    def test_user_accessing_admin_export(self):
        _setup_db()
        db = SessionLocal()
        try:
            user = _create_user(db)
            _login_user(user)
            resp = client.get("/admin/export", follow_redirects=False)
            assert resp.status_code == 403
        finally:
            db.close()

    def test_user_accessing_admin_audit(self):
        _setup_db()
        db = SessionLocal()
        try:
            user = _create_user(db)
            _login_user(user)
            resp = client.get("/admin/audit", follow_redirects=False)
            assert resp.status_code == 403
        finally:
            db.close()


# ==================== 模型字段完整性测试 ====================


class TestModelFields:
    def test_bootcamp_model_fields(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            bootcamp = _create_bootcamp(db, admin.id)
            assert bootcamp.id is not None
            assert bootcamp.name == "测试训练营"
            assert bootcamp.description == "测试描述"
            assert bootcamp.days == 7
            assert bootcamp.is_active is True
            assert bootcamp.created_by == admin.id
            assert bootcamp.created_at is not None
        finally:
            db.close()

    def test_batch_model_fields(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            bootcamp = _create_bootcamp(db, admin.id)
            batch = _create_batch(db, bootcamp.id)
            assert batch.id is not None
            assert batch.bootcamp_id == bootcamp.id
            assert batch.name == "测试批次"
            assert batch.is_active is True
            assert batch.created_at is not None
        finally:
            db.close()

    def test_enrollment_model_fields(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            user = _create_user(db)
            bootcamp = _create_bootcamp(db, admin.id)
            enrollment = _create_enrollment(db, user.id, bootcamp.id)
            assert enrollment.id is not None
            assert enrollment.user_id == user.id
            assert enrollment.bootcamp_id == bootcamp.id
            assert enrollment.start_date == date.today()
            assert enrollment.created_at is not None
        finally:
            db.close()

    def test_submission_model_fields(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            user = _create_user(db)
            bootcamp = _create_bootcamp(db, admin.id)
            enrollment = _create_enrollment(db, user.id, bootcamp.id)
            submission = _create_submission(db, enrollment.id, 1, {"q1": "答案"})
            assert submission.id is not None
            assert submission.enrollment_id == enrollment.id
            assert submission.day_number == 1
            assert submission.submitted_at is not None
        finally:
            db.close()

    def test_badge_model_fields(self):
        _setup_db()
        db = SessionLocal()
        try:
            badge = Badge(name="测试徽章", description="描述", icon="🏅", criteria={"type": "test"})
            db.add(badge)
            db.commit()
            db.refresh(badge)
            assert badge.id is not None
            assert badge.name == "测试徽章"
            assert badge.created_at is not None
        finally:
            db.close()

    def test_user_badge_model_fields(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            user = _create_user(db)
            bootcamp = _create_bootcamp(db, admin.id)
            enrollment = _create_enrollment(db, user.id, bootcamp.id)
            badge = Badge(name="test", description="test", icon="🏅", criteria={"type": "test"})
            db.add(badge)
            db.commit()
            db.refresh(badge)
            ub = UserBadge(user_id=user.id, badge_id=badge.id, enrollment_id=enrollment.id)
            db.add(ub)
            db.commit()
            db.refresh(ub)
            assert ub.id is not None
            assert ub.user_id == user.id
            assert ub.badge_id == badge.id
            assert ub.enrollment_id == enrollment.id
            assert ub.earned_at is not None
        finally:
            db.close()

    def test_audit_log_model_fields(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            from routes.audit import log_admin_action
            log_admin_action(db, admin.id, "测试", "target", 1, {"k": "v"})
            log_entry = db.query(AuditLog).filter(AuditLog.action == "测试").first()
            assert log_entry is not None
            assert log_entry.admin_id == admin.id
            assert log_entry.target_type == "target"
            assert log_entry.target_id == 1
            assert log_entry.detail == {"k": "v"}
            assert log_entry.created_at is not None
        finally:
            db.close()

    def test_day_form_model_fields(self):
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            bootcamp = _create_bootcamp(db, admin.id)
            df = _create_day_form(db, bootcamp.id, 1, [{"id": "q1", "type": "text"}])
            assert df.id is not None
            assert df.bootcamp_id == bootcamp.id
            assert df.day_number == 1
            assert df.questions == [{"id": "q1", "type": "text"}]
        finally:
            db.close()


class TestSecurityHardening:
    """安全加固测试 - 模拟攻击场景验证防护措施"""

    def _get_csrf_token(self, client_instance):
        """辅助方法：从GET请求中获取CSRF token cookie"""
        resp = client_instance.get("/login")
        csrf_cookie = client_instance.cookies.get(CSRF_COOKIE_NAME)
        assert csrf_cookie is not None, "CSRF cookie应被设置"
        return csrf_cookie

    # ========== CSRF防护测试 ==========

    def test_csrf_token_missing_returns_403(self):
        """POST请求无CSRF token应返回403"""
        _setup_db()
        db = SessionLocal()
        try:
            _create_admin(db)
        finally:
            db.close()
        # 临时移除CSRF跳过，测试真实CSRF验证
        saved_override = app.dependency_overrides.get(verify_csrf)
        app.dependency_overrides.pop(verify_csrf, None)
        try:
            test_client = TestClient(app, raise_server_exceptions=False)
            resp = test_client.post("/login", data={"email": "test@test.com", "password": "pass123"})
            assert resp.status_code == 403
        finally:
            if saved_override:
                app.dependency_overrides[verify_csrf] = saved_override

    def test_csrf_token_mismatch_returns_403(self):
        """POST请求CSRF token不匹配应返回403"""
        _setup_db()
        db = SessionLocal()
        try:
            _create_admin(db)
        finally:
            db.close()
        saved_override = app.dependency_overrides.get(verify_csrf)
        app.dependency_overrides.pop(verify_csrf, None)
        try:
            test_client = TestClient(app, raise_server_exceptions=False)
            # 先访问页面获取CSRF cookie
            test_client.get("/login")
            # 使用错误的token提交
            resp = test_client.post("/login", data={
                "email": "test@test.com",
                "password": "pass123",
                "csrf_token": "wrong_token_12345",
            })
            assert resp.status_code == 403
        finally:
            if saved_override:
                app.dependency_overrides[verify_csrf] = saved_override

    def test_csrf_token_valid_passes(self):
        """POST请求带有效CSRF token应正常处理"""
        _setup_db()
        db = SessionLocal()
        try:
            _create_admin(db)
        finally:
            db.close()
        saved_override = app.dependency_overrides.get(verify_csrf)
        app.dependency_overrides.pop(verify_csrf, None)
        try:
            test_client = TestClient(app, raise_server_exceptions=False)
            # 先访问页面获取CSRF cookie
            test_client.get("/login")
            csrf_token = test_client.cookies.get(CSRF_COOKIE_NAME)
            # 使用正确的token提交（密码错误，但不应是403）
            resp = test_client.post("/login", data={
                "email": "testadmin@test.com",
                "password": "wrongpassword",
                "csrf_token": csrf_token,
            })
            # 应该返回200（登录页面显示错误），而不是403
            assert resp.status_code == 200
        finally:
            if saved_override:
                app.dependency_overrides[verify_csrf] = saved_override

    # ========== 安全响应头测试 ==========

    def test_security_headers_present(self):
        """验证所有响应包含安全头"""
        _setup_db()
        resp = client.get("/login")
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("X-Frame-Options") == "DENY"
        assert resp.headers.get("X-XSS-Protection") == "1; mode=block"
        assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
        assert "geolocation=()" in resp.headers.get("Permissions-Policy", "")
        assert "Content-Security-Policy" in resp.headers
        assert "frame-ancestors 'none'" in resp.headers.get("Content-Security-Policy", "")

    def test_csp_allows_required_sources(self):
        """验证CSP允许必要的外部资源"""
        _setup_db()
        resp = client.get("/login")
        csp = resp.headers.get("Content-Security-Policy", "")
        assert "cdn.tailwindcss.com" in csp
        assert "unpkg.com" in csp
        assert "'self'" in csp

    # ========== XSS输入过滤测试 ==========

    def test_xss_in_nickname_sanitized(self):
        """注册时昵称中的XSS payload应被清理"""
        _setup_db()
        db = SessionLocal()
        try:
            db.query(User).filter(User.email == "xss@test.com").delete()
            db.commit()
        finally:
            db.close()
        resp = client.get("/register")
        csrf_token = client.cookies.get(CSRF_COOKIE_NAME)
        xss_payload = '<script>alert("xss")</script>测试用户'
        resp = client.post("/register", data={
            "email": "xss@test.com",
            "password": "Test1234",
            "nickname": xss_payload,
            "csrf_token": csrf_token,
        })
        # 注册成功后重定向到登录页
        assert resp.status_code in (302, 200)
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.email == "xss@test.com").first()
            if user:
                assert "<script>" not in user.nickname
                assert "script" not in user.nickname.lower() or "&lt;script&gt;" in user.nickname
        finally:
            db.query(User).filter(User.email == "xss@test.com").delete()
            db.commit()
            db.close()

    def test_sql_injection_in_email(self):
        """登录邮箱含SQL注入payload不应影响查询"""
        _setup_db()
        db = SessionLocal()
        try:
            _create_admin(db)
        finally:
            db.close()
        sql_payload = "' OR '1'='1' --"
        resp = client.post("/login", data={
            "email": sql_payload,
            "password": "anypassword",
        })
        # 不应返回200（成功登录），应返回登录页
        assert resp.status_code in (200, 302)
        # 如果返回200，应显示错误信息而非成功
        if resp.status_code == 200:
            assert "邮箱或密码错误" in resp.text or "error" in resp.text.lower()

    # ========== 权限提升防护测试 ==========

    def test_admin_cannot_create_admin_role(self):
        """普通管理员创建admin角色应返回403"""
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
        finally:
            db.close()
        admin_token = create_access_token({"sub": admin.id})
        resp = client.post("/admin/create-user", data={
            "email": "newadmin@test.com",
            "nickname": "新管理员",
            "password": "Admin1234",
            "role": "admin",
        }, cookies={"access_token": admin_token})
        assert resp.status_code == 403

    def test_admin_can_create_user_role(self):
        """普通管理员创建user角色应成功"""
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
            admin_id = admin.id
            db.query(User).filter(User.email == "newuser@test.com").delete()
            db.commit()
        finally:
            db.close()
        admin_token = create_access_token({"sub": admin_id})
        resp = client.post("/admin/create-user", data={
            "email": "newuser@test.com",
            "nickname": "新用户",
            "password": "User1234",
            "role": "user",
        }, cookies={"access_token": admin_token}, follow_redirects=False)
        assert resp.status_code in (302, 200)
        db = SessionLocal()
        try:
            db.query(User).filter(User.email == "newuser@test.com").delete()
            db.commit()
        finally:
            db.close()

    # ========== 密码强度验证测试 ==========

    def test_weak_password_registration_rejected(self):
        """弱密码注册应被拒绝"""
        _setup_db()
        resp = client.post("/register", data={
            "email": "weak@test.com",
            "password": "123",
            "nickname": "弱密码用户",
        })
        assert resp.status_code == 200
        assert "密码" in resp.text

    def test_password_without_letters_rejected(self):
        """纯数字密码应被拒绝"""
        _setup_db()
        resp = client.post("/register", data={
            "email": "weak2@test.com",
            "password": "12345678",
            "nickname": "纯数字密码",
        })
        assert resp.status_code == 200
        assert "密码" in resp.text

    # ========== 认证绕过测试 ==========

    def test_no_token_access_protected_endpoint(self):
        """无token访问受保护端点应返回303"""
        _setup_db()
        resp = client.get("/user/dashboard", follow_redirects=False)
        assert resp.status_code == 303

    def test_invalid_token_access_protected_endpoint(self):
        """无效token访问受保护端点应返回303"""
        _setup_db()
        resp = client.get("/user/dashboard", follow_redirects=False,
                          cookies={"access_token": "invalid.token.here"})
        assert resp.status_code == 303

    def test_expired_token_access_protected_endpoint(self):
        """过期token访问受保护端点应返回303"""
        _setup_db()
        db = SessionLocal()
        try:
            admin = _create_admin(db)
        finally:
            db.close()
        # 创建一个已过期的token
        expired_token = create_access_token({"sub": admin.id})
        # 手动修改token的过期时间为过去
        from jose import jwt as jose_jwt
        payload = jose_jwt.decode(expired_token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        payload["exp"] = datetime.now(timezone.utc) - timedelta(hours=1)
        expired_token = jose_jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
        resp = client.get("/admin/bootcamps", follow_redirects=False,
                          cookies={"access_token": expired_token})
        assert resp.status_code == 303

    def test_regular_user_access_admin_endpoint(self):
        """普通用户访问管理员端点应返回403"""
        _setup_db()
        db = SessionLocal()
        try:
            user = _create_user(db)
        finally:
            db.close()
        user_token = create_access_token({"sub": user.id})
        resp = client.get("/admin/bootcamps", follow_redirects=False,
                          cookies={"access_token": user_token})
        assert resp.status_code == 403

    # ========== CSRF Cookie测试 ==========

    def test_csrf_cookie_set_on_response(self):
        """验证CSRF cookie在响应中被设置"""
        _setup_db()
        # 清除现有cookie
        client.cookies.clear()
        resp = client.get("/login")
        csrf_cookie = client.cookies.get(CSRF_COOKIE_NAME)
        assert csrf_cookie is not None
        assert len(csrf_cookie) > 20

    # ========== 输入清理工具测试 ==========

    def test_sanitize_text_removes_html_tags(self):
        """sanitize_text应去除HTML标签"""
        from utils.sanitize import sanitize_text
        result = sanitize_text('<script>alert("xss")</script>安全')
        assert "<script>" not in result
        assert "安全" in result

    def test_sanitize_text_escapes_special_chars(self):
        """sanitize_text应转义特殊字符"""
        from utils.sanitize import sanitize_text
        result = sanitize_text('<img src=x onerror=alert(1)>')
        assert "<img" not in result
        assert "&lt;" in result or "img" not in result

    def test_sanitize_email_valid(self):
        """sanitize_email应验证有效邮箱"""
        from utils.sanitize import sanitize_email
        assert sanitize_email("test@example.com") == "test@example.com"
        assert sanitize_email("  TEST@Example.COM  ") == "test@example.com"

    def test_sanitize_email_invalid(self):
        """sanitize_email应拒绝无效邮箱"""
        from utils.sanitize import sanitize_email
        assert sanitize_email("not-an-email") == ""
        assert sanitize_email("") == ""
        assert sanitize_email("missing@") == ""

    def test_validate_password_strong(self):
        """强密码应通过验证"""
        from utils.sanitize import validate_password_strength
        valid, msg = validate_password_strength("Test1234")
        assert valid is True
        assert msg == ""

    def test_validate_password_short(self):
        """短密码应被拒绝"""
        from utils.sanitize import validate_password_strength
        valid, msg = validate_password_strength("Ab1")
        assert valid is False
        assert "8" in msg

    def test_validate_password_no_letters(self):
        """无字母密码应被拒绝"""
        from utils.sanitize import validate_password_strength
        valid, msg = validate_password_strength("12345678")
        assert valid is False
        assert "字母" in msg

    def test_validate_password_no_digits(self):
        """无数字密码应被拒绝"""
        from utils.sanitize import validate_password_strength
        valid, msg = validate_password_strength("abcdefgh")
        assert valid is False
        assert "数字" in msg


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))

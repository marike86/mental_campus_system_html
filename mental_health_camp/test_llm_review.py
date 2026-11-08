"""每日提交限额与大模型自动审核的自动化测试。"""
import json
from datetime import timedelta

import pytest
from fastapi import HTTPException
from starlette.datastructures import FormData

import tests as helpers
from models.llm_review import LLMReviewLog
from models.submission import Submission
from models.user import User
from models.workflow import SubmissionAttempt
from services import courses, llm, reviews
from services.clock import local_date, now
from utils.crypto import encrypt_secret, decrypt_secret

QUESTIONS = [
    dict(id="answer", type="text", label="感受", required=True),
    dict(id="scale", type="likert", label="评分", min=0, max=5, required=True),
]


def _world():
    helpers._setup_db()
    db = helpers.SessionLocal()
    admin = helpers._create_admin(db)
    super_admin = User(email="root@test.com", nickname="超管",
                       hashed_password=helpers.get_password_hash("pass123"), role="super_admin")
    db.add(super_admin)
    db.commit()
    user = helpers._create_user(db)
    camp = helpers._create_bootcamp(db, admin.id, days=3)
    for day in (1, 2, 3):
        helpers._create_day_form(db, camp.id, day, QUESTIONS)
    enrollment = helpers._create_enrollment(db, user.id, camp.id)
    enrollment.start_date = local_date() - timedelta(days=1)  # 第 1、2 天都已到计划日期
    db.commit()
    return db, admin, super_admin, user, camp, enrollment


def _submit(db, enrollment, day, answer="记录"):
    version = courses.start(db, enrollment, day)
    submission = courses.submit(db, enrollment, day, FormData(
        dict(version_id=str(version.id), q_answer=answer, q_scale="1")))
    db.commit()
    return submission


def _enable_llm(db, enabled=True, api_key="sk-test-key", auto_decision=True):
    cfg = llm.get_config(db)
    cfg.enabled = enabled
    cfg.base_url = "https://api.example.com/v1"
    cfg.model = "gpt-4o-mini"
    cfg.api_key_encrypted = encrypt_secret(api_key)
    cfg.prompt_template = "课程 {bootcamp} 第 {day} 天\n{content}"
    cfg.auto_decision = auto_decision
    db.commit()
    return cfg


# ==================== 每日提交限额 ====================

def test_daily_limit_blocks_second_content_same_day():
    db, admin, super_admin, user, camp, enrollment = _world()
    try:
        sub = _submit(db, enrollment, 1)
        reviews.decide(db, sub.id, sub.current_attempt_id, admin, "approved")
        db.commit()
        with pytest.raises(HTTPException) as exc:
            _submit(db, enrollment, 2, answer="第二天")
        assert exc.value.status_code == 409
        assert "每天最多完成" in str(exc.value.detail)
    finally:
        db.close()


def test_daily_limit_resets_next_day():
    db, admin, super_admin, user, camp, enrollment = _world()
    try:
        sub = _submit(db, enrollment, 1)
        reviews.decide(db, sub.id, sub.current_attempt_id, admin, "approved")
        db.commit()
        attempt = db.get(SubmissionAttempt, sub.current_attempt_id)
        attempt.submitted_at = now() - timedelta(days=1)  # 模拟跨到下一个自然日
        db.commit()
        assert courses.daily_state_for_user(db, user.id)["used"] == 0
        assert _submit(db, enrollment, 2, answer="第二天") is not None
    finally:
        db.close()


def test_daily_limit_allows_resubmitting_same_content():
    db, admin, super_admin, user, camp, enrollment = _world()
    try:
        sub = _submit(db, enrollment, 1)
        first_attempt = sub.current_attempt_id
        reviews.decide(db, sub.id, sub.current_attempt_id, admin, "rejected", "请补充细节")
        db.commit()
        # 同一份内容被驳回后当天重提，不占用新的名额
        version = courses.start(db, enrollment, 1)
        again = courses.submit(db, enrollment, 1, FormData(
            dict(version_id=str(version.id), q_answer="补充说明", q_scale="2")))
        db.commit()
        assert again.current_attempt_id != first_attempt
    finally:
        db.close()


def test_course_page_shows_daily_counter():
    db, admin, super_admin, user, camp, enrollment = _world()
    try:
        sub = _submit(db, enrollment, 1)
        reviews.decide(db, sub.id, sub.current_attempt_id, admin, "approved")
        db.commit()
        helpers._login_user(user)
        try:
            page = helpers.client.get("/user/today")
            assert page.status_code == 200
            assert "今日已完成" in page.text and "明天再来" in page.text
        finally:
            helpers._logout()
    finally:
        db.close()


def test_submit_page_reports_quota_error():
    db, admin, super_admin, user, camp, enrollment = _world()
    try:
        sub = _submit(db, enrollment, 1)
        reviews.decide(db, sub.id, sub.current_attempt_id, admin, "approved")
        db.commit()
        helpers._login_user(user)
        try:
            version = courses.bound_version(db, enrollment.id, 2)
            response = helpers.client.post(f"/user/form/{enrollment.id}/2", data=dict(
                version_id=version.id, q_answer="第二天", q_scale="1"))
            assert response.status_code == 409
            assert "每天最多完成" in response.text
        finally:
            helpers._logout()
    finally:
        db.close()


# ==================== 大模型自动审核 ====================

def test_auto_review_approves_and_records_log(monkeypatch):
    db, admin, super_admin, user, camp, enrollment = _world()
    try:
        _enable_llm(db)
        captured = {}

        def fake_call(cfg, prompt, timeout=None, retries=None):
            captured["prompt"] = prompt
            captured["cfg"] = cfg
            return {"choices": [{"message": {"content": json.dumps(
                {"passed": True, "reason": "内容完整", "risk_level": "low"})}}]}

        monkeypatch.setattr(llm, "call_chat", fake_call)
        sub = _submit(db, enrollment, 1)
        llm.review_attempt_background(sub.id, sub.current_attempt_id)
        db.expire_all()
        attempt = db.get(SubmissionAttempt, sub.current_attempt_id)
        assert attempt.review_status == "approved"
        assert "内容完整" in attempt.review_comment
        assert "【AI 自动审核】" in attempt.review_comment
        assert db.get(Submission, sub.id).review_status == "approved"
        log = db.query(LLMReviewLog).one()
        assert log.status == "approved" and log.passed is True and log.risk_level == "low"
        assert "第 1 天" in captured["prompt"] and "测试训练营" in captured["prompt"]
    finally:
        db.close()


def test_auto_review_rejects_with_reason(monkeypatch):
    db, admin, super_admin, user, camp, enrollment = _world()
    try:
        _enable_llm(db)
        monkeypatch.setattr(llm, "call_chat", lambda *a, **k: {"choices": [{"message": {"content": json.dumps(
            {"passed": False, "reason": "内容包含不友善表达", "risk_level": "medium"})}}]})
        sub = _submit(db, enrollment, 1)
        llm.review_attempt_background(sub.id, sub.current_attempt_id)
        db.expire_all()
        attempt = db.get(SubmissionAttempt, sub.current_attempt_id)
        assert attempt.review_status == "rejected"
        assert "不友善" in attempt.review_comment
        assert db.query(LLMReviewLog).one().status == "rejected"
    finally:
        db.close()


def test_auto_review_high_risk_goes_to_human(monkeypatch):
    db, admin, super_admin, user, camp, enrollment = _world()
    try:
        _enable_llm(db)
        monkeypatch.setattr(llm, "call_chat", lambda *a, **k: {"choices": [{"message": {"content": json.dumps(
            {"passed": True, "reason": "出现需要关注的表述", "risk_level": "high"})}}]})
        sub = _submit(db, enrollment, 1)
        llm.review_attempt_background(sub.id, sub.current_attempt_id)
        db.expire_all()
        attempt = db.get(SubmissionAttempt, sub.current_attempt_id)
        assert attempt.review_status == "pending"  # 高风险内容不自动通过
        assert db.query(LLMReviewLog).one().status == "manual"
    finally:
        db.close()


def test_auto_review_api_failure_degrades_to_manual(monkeypatch):
    db, admin, super_admin, user, camp, enrollment = _world()
    try:
        _enable_llm(db)

        def failing(*args, **kwargs):
            raise llm.LLMUnavailable("无法连接接口")

        monkeypatch.setattr(llm, "call_chat", failing)
        sub = _submit(db, enrollment, 1)
        llm.review_attempt_background(sub.id, sub.current_attempt_id)
        db.expire_all()
        attempt = db.get(SubmissionAttempt, sub.current_attempt_id)
        assert attempt.review_status == "pending"  # 降级为人工审核
        log = db.query(LLMReviewLog).one()
        assert log.status == "error" and "无法连接" in log.error
    finally:
        db.close()


def test_auto_review_invalid_response_degrades_to_manual(monkeypatch):
    db, admin, super_admin, user, camp, enrollment = _world()
    try:
        _enable_llm(db)
        monkeypatch.setattr(llm, "call_chat", lambda *a, **k: {"choices": [{"message": {"content": "我觉得还行吧"}}]})
        sub = _submit(db, enrollment, 1)
        llm.review_attempt_background(sub.id, sub.current_attempt_id)
        db.expire_all()
        assert db.get(SubmissionAttempt, sub.current_attempt_id).review_status == "pending"
        log = db.query(LLMReviewLog).one()
        assert log.status == "error" and log.error
    finally:
        db.close()


def test_auto_review_disabled_leaves_submission_pending():
    db, admin, super_admin, user, camp, enrollment = _world()
    try:
        _enable_llm(db, enabled=False)
        sub = _submit(db, enrollment, 1)
        llm.review_attempt_background(sub.id, sub.current_attempt_id)
        db.expire_all()
        assert db.get(SubmissionAttempt, sub.current_attempt_id).review_status == "pending"
        assert db.query(LLMReviewLog).one().status == "disabled"
    finally:
        db.close()


def test_parse_review_handles_various_shapes():
    assert llm.parse_review('{"passed": true, "reason": "ok", "risk_level": "low"}') == {
        "passed": True, "reason": "ok", "risk_level": "low"}
    assert llm.parse_review('```json\n{"passed": false, "reason": "bad", "risk_level": "高"}\n```') == {
        "passed": False, "reason": "bad", "risk_level": "high"}
    assert llm.parse_review('前缀 {"passed": "yes", "reason": "x"} 后缀')["passed"] is True
    with pytest.raises(llm.LLMInvalidResponse):
        llm.parse_review("没有 JSON")
    with pytest.raises(llm.LLMInvalidResponse):
        llm.parse_review('{"reason": "缺少 passed"}')


def test_render_prompt_keeps_unknown_placeholders():
    rendered = llm.render_prompt("训练营 {bootcamp}，{unknown}", {"bootcamp": "成长营"})
    assert "成长营" in rendered and "{unknown}" in rendered


# ==================== 配置页面与权限 ====================

def test_settings_page_requires_super_admin():
    db, admin, super_admin, user, camp, enrollment = _world()
    try:
        helpers._login_user(user)
        assert helpers.client.get("/super-admin/ai-settings").status_code == 403
        helpers._logout()
        helpers._login_admin(admin)
        assert helpers.client.get("/super-admin/ai-settings").status_code == 403
        helpers._logout()
        helpers._login_user(super_admin)
        assert helpers.client.get("/super-admin/ai-settings").status_code == 200
        helpers._logout()
    finally:
        db.close()


def test_settings_page_stores_encrypted_key():
    db, admin, super_admin, user, camp, enrollment = _world()
    try:
        helpers._login_user(super_admin)
        try:
            response = helpers.client.post("/super-admin/ai-settings", data=dict(
                enabled="1", base_url="https://api.example.com/v1", model="gpt-4o-mini",
                api_key="sk-super-secret-key", timeout="20", retries="2", temperature="0.2",
                max_tokens="600", auto_decision="1", prompt_template="审核 {content}"),
                follow_redirects=False)
            assert response.status_code == 303
            cfg = llm.get_config(db)
            assert cfg.enabled is True
            assert "sk-super-secret-key" not in (cfg.api_key_encrypted or "")
            assert decrypt_secret(cfg.api_key_encrypted) == "sk-super-secret-key"
            page = helpers.client.get("/super-admin/ai-settings")
            assert "sk-super-secret-key" not in page.text
            assert "sk-s" in page.text  # 仅展示脱敏后的密钥
        finally:
            helpers._logout()
    finally:
        db.close()


def test_settings_page_rejects_invalid_parameters():
    db, admin, super_admin, user, camp, enrollment = _world()
    try:
        helpers._login_user(super_admin)
        try:
            response = helpers.client.post("/super-admin/ai-settings", data=dict(
                base_url="ftp://bad", model="gpt-4o-mini", prompt_template="审核"))
            assert response.status_code == 400
            response = helpers.client.post("/super-admin/ai-settings", data=dict(
                base_url="https://api.example.com/v1", model="gpt-4o-mini", timeout="9999",
                prompt_template="审核"))
            assert response.status_code == 400
        finally:
            helpers._logout()
    finally:
        db.close()


# ==================== 每日提醒 ====================

def test_reminder_defers_tasks_after_daily_quota_used(monkeypatch):
    db, admin, super_admin, user, camp, enrollment = _world()
    try:
        captured = {}

        def fake_send(to_email, nickname, pending, deferred=None, note=""):
            captured["pending"] = pending
            captured["deferred"] = deferred or []
            captured["note"] = note
            return True

        monkeypatch.setattr("routes.notification.send_daily_reminder", fake_send)
        sub = _submit(db, enrollment, 1)
        reviews.decide(db, sub.id, sub.current_attempt_id, admin, "approved")
        db.commit()
        from routes.notification import check_and_send_reminders
        assert check_and_send_reminders(db) == 1
        assert captured["pending"] == []          # 今日份额已用完
        assert len(captured["deferred"]) == 1     # 第 2 天顺延到明天
        assert "明天继续" in captured["note"]
    finally:
        db.close()


def test_reminder_email_escapes_untrusted_text(monkeypatch):
    from utils import email as email_util
    captured = {}

    def fake_send(to_email, subject, html_body):
        captured["body"] = html_body
        return True

    monkeypatch.setattr(email_util, "send_email", fake_send)
    email_util.send_daily_reminder(
        "a@example.com", "<b>昵称</b>",
        [dict(bootcamp_name="<script>alert(1)</script>", day_number=1, form_url='/user/form/1/1')])
    body = captured["body"]
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body
    assert "<b>昵称</b>" not in body

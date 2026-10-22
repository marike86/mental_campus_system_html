"""Regression coverage for authentication and submission failures."""
import re

import pytest
from fastapi.testclient import TestClient

import tests as helpers
from auth import verify_csrf
from main import app
from models.submission import Submission
from models.workflow import SubmissionAttempt
from services.versions import bound_version
from models.review_assignment import ReviewAssignment
from utils.crypto import decrypt_data


@pytest.fixture
def real_client():
    saved = app.dependency_overrides.pop(verify_csrf, None)
    try:
        yield TestClient(app)
    finally:
        if saved is not None:
            app.dependency_overrides[verify_csrf] = saved


@pytest.fixture
def enrollment():
    helpers._setup_db()
    db = helpers.SessionLocal()
    admin = helpers._create_admin(db)
    user = helpers._create_user(db)
    camp = helpers._create_bootcamp(db, admin.id)
    helpers._create_day_form(db, camp.id, 1, [
        {"id": "q1", "type": "text", "label": "回答", "required": True},
        {"id": "scale", "type": "likert", "label": "评分", "min": 0, "max": 5, "required": True},
    ])
    enrolled = helpers._create_enrollment(db, user.id, camp.id)
    helpers._login_user(user)
    try:
        yield db, user, enrolled
    finally:
        helpers._logout()
        db.close()


def test_unauthenticated_redirect_has_destination(real_client):
    response = real_client.get("/user/today", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"
    assert real_client.get("/user/today").status_code == 200


def test_first_visit_form_token_matches_cookie_and_submits(real_client):
    response = real_client.get("/login")
    tokens = re.findall(r'name="csrf_token" value="([^"]+)"', response.text)
    assert tokens
    assert all(token == real_client.cookies.get("csrf_token") for token in tokens)
    response = real_client.post("/login", data={
        "email": "unknown@example.com", "password": "wrong", "csrf_token": tokens[0],
    })
    assert response.status_code == 200


def test_json_answer_verification_accepts_matching_header(enrollment, real_client):
    _, user, enrolled = enrollment
    real_client.cookies.set("access_token", helpers.create_access_token({"sub": user.id}))
    real_client.get("/user/today")
    payload = {"enrollment_id": enrolled.id, "day_number": 1, "question_id": "q1", "answer": "hello"}
    assert real_client.post("/user/api/verify-answer", json=payload).status_code == 403
    assert real_client.post("/user/api/verify-answer", json=payload,
                            headers={"X-CSRF-Token": "wrong"}).status_code == 403
    response = real_client.post("/user/api/verify-answer", json=payload,
                               headers={"X-CSRF-Token": real_client.cookies.get("csrf_token")})
    assert response.status_code == 200
    assert response.json()["correct"] is True


@pytest.mark.parametrize("answer,status", [("bad", 400), ("6", 400), ("0", 303)])
def test_likert_validation(enrollment, answer, status):
    db, _, enrolled = enrollment
    response = helpers.client.post(f"/user/form/{enrolled.id}/1",
                                   data={"version_id": bound_version(db,enrolled.id,1).id,"q_q1": "回答", "q_scale": answer}, follow_redirects=False)
    assert response.status_code == status
    assert db.query(Submission).count() == (1 if status == 303 else 0)


def test_nonexistent_form_cannot_create_submission(enrollment):
    db, _, enrolled = enrollment
    response = helpers.client.post(f"/user/form/{enrolled.id}/99", data={}, follow_redirects=False)
    assert response.status_code == 404
    assert db.query(Submission).count() == 0


def test_failed_resubmission_keeps_rejected_answers(enrollment):
    db, _, enrolled = enrollment
    old = helpers._create_submission(db, enrolled.id, 1, {"q1": "旧答案"})
    old.review_status = "rejected"
    old.review_comment = "请补充"
    db.commit()
    response = helpers.client.post(f"/user/form/{enrolled.id}/1", data={"version_id": bound_version(db,enrolled.id,1).id,"q_scale": "2"})
    assert response.status_code == 400
    db.expire_all()
    saved = db.get(Submission, old.id)
    assert saved.review_status == "rejected"
    assert saved.review_comment == "请补充"
    assert decrypt_data(saved.answers) == {"q1": "旧答案"}


def test_valid_resubmission_preserves_id_and_clears_review(enrollment):
    db, user, enrolled = enrollment
    old = helpers._create_submission(db, enrolled.id, 1, {"q1": "旧答案"})
    old.review_status = "rejected"
    old.reviewer_id = user.id
    old.review_comment = "请补充"
    assignment = ReviewAssignment(submission_id=old.id, reviewer_id=user.id, status="completed")
    db.add(assignment)
    db.commit()
    old_id = old.id
    response = helpers.client.post(f"/user/form/{enrolled.id}/1",
                                   data={"version_id": bound_version(db,enrolled.id,1).id,"q_q1": "新答案", "q_scale": "2"}, follow_redirects=False)
    assert response.status_code == 303
    db.expire_all()
    saved = db.get(Submission, old_id)
    assert db.query(Submission).count() == 1
    assert saved.review_status == "pending"
    assert saved.reviewer_id is None and saved.review_comment is None and saved.reviewed_at is None
    assert decrypt_data(saved.answers) == {"q1": "新答案", "scale": 2}
    assert db.get(ReviewAssignment, assignment.id).submission_id == old_id


@pytest.mark.parametrize("status,label", [("approved", "已通过"), ("rejected", "未通过"), ("pending", "待审核")])
def test_history_displays_review_status_and_comment(enrollment, status, label):
    db, _, enrolled = enrollment
    submission = helpers._create_submission(db, enrolled.id, 1, {"q1": "回答"})
    submission.review_status = status
    submission.review_comment = "请补充说明"
    attempt=db.get(SubmissionAttempt,submission.current_attempt_id)
    attempt.review_status=status
    attempt.review_comment=submission.review_comment
    db.commit()
    response = helpers.client.get(f"/user/history/{enrolled.id}")
    assert response.status_code == 200
    assert label in response.text
    if status == "rejected":
        assert "请补充说明" in response.text

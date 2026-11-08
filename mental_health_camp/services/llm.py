"""大模型自动审核：OpenAI 兼容接口调用、结构化结果解析与失败降级。

设计要点：
- 密钥只在服务端解密，请求由服务端转发，前端永远拿不到 API Key。
- 任何调用异常（超时、连接失败、返回格式异常）都不会阻塞学员提交，
  而是记录日志后把该轮次留给人工审核。
"""
import json
import logging
import re
import socket
import time
import urllib.error
import urllib.request

from models.bootcamp import Bootcamp
from models.enrollment import Enrollment
from models.llm_review import LLMConfig, LLMReviewLog
from models.submission import Submission
from models.workflow import DayFormVersion, SubmissionAttempt
from config import LLM_PROMPT_TEMPLATE, LLM_MAX_PROMPT_LENGTH
from services.clock import now
from utils.crypto import decrypt_data, decrypt_secret, encrypt_secret

logger = logging.getLogger(__name__)

CONFIG_ID = 1
RISK_ALIASES = {
    "low": "low", "低": "low", "none": "low", "无": "low",
    "medium": "medium", "mid": "medium", "中": "medium",
    "high": "high", "高": "high", "严重": "high",
}


class LLMError(Exception):
    """大模型调用相关错误的基类。"""


class LLMUnavailable(LLMError):
    """接口不可用（连接失败、鉴权失败、返回错误状态）。"""


class LLMTimeout(LLMError):
    """请求超时。"""


class LLMInvalidResponse(LLMError):
    """返回内容无法解析为结构化审核结果。"""


# ===== 配置读写 =====

def get_config(db):
    """读取全局配置；没有记录时创建一行默认值。"""
    cfg = db.get(LLMConfig, CONFIG_ID)
    if cfg is None:
        cfg = LLMConfig(id=CONFIG_ID, prompt_template=LLM_PROMPT_TEMPLATE)
        db.add(cfg)
        db.flush()
    return cfg


def masked_api_key(cfg):
    """给页面展示用的脱敏密钥。"""
    key = decrypt_secret(cfg.api_key_encrypted or "")
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}{'*' * 6}{key[-4:]}"


def apply_config(db, admin_id, data):
    """把页面提交的表单写入配置；api_key 为空表示保留原值。"""
    cfg = get_config(db)
    if "enabled" in data:
        cfg.enabled = bool(data["enabled"])
    if "base_url" in data:
        cfg.base_url = (data["base_url"] or "").strip()
    if "model" in data:
        cfg.model = (data["model"] or "").strip()
    if "api_key" in data and data["api_key"]:
        cfg.api_key_encrypted = encrypt_secret(data["api_key"].strip())
    if "timeout" in data:
        cfg.timeout = int(data["timeout"])
    if "retries" in data:
        cfg.retries = int(data["retries"])
    if "temperature" in data:
        cfg.temperature = float(data["temperature"])
    if "max_tokens" in data:
        cfg.max_tokens = int(data["max_tokens"])
    if "auto_decision" in data:
        cfg.auto_decision = bool(data["auto_decision"])
    if "prompt_template" in data:
        cfg.prompt_template = data["prompt_template"] or ""
    cfg.updated_by = admin_id
    cfg.updated_at = now()
    db.flush()
    return cfg


# ===== 提示词组装 =====

def render_prompt(template, context):
    """替换模板中的 {key} 占位符；未知占位符原样保留，避免因模板笔误导致审核中断。"""
    def replace(match):
        key = match.group(1)
        if key in context:
            return str(context[key])
        return match.group(0)
    return re.sub(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", replace, template or "")


def build_content(db, attempt):
    """把题目与作答整理成可读文本。"""
    version = db.get(DayFormVersion, attempt.version_id)
    answers = decrypt_data(attempt.answers)
    lines = []
    for question in (version.questions if version else []) or []:
        if not isinstance(question, dict) or question.get("type") == "reading":
            continue
        answer = answers.get(question.get("id"))
        if isinstance(answer, list):
            answer = "、".join(str(item) for item in answer)
        lines.append(f"题目：{question.get('label', '')}\n作答：{'' if answer in (None, '') else answer}")
    return "\n".join(lines)


def build_prompt(db, cfg, sub, attempt):
    template = cfg.prompt_template or LLM_PROMPT_TEMPLATE
    enrollment = db.get(Enrollment, sub.enrollment_id)
    bootcamp = db.get(Bootcamp, enrollment.bootcamp_id) if enrollment else None
    content = build_content(db, attempt)
    if len(content) > LLM_MAX_PROMPT_LENGTH:
        content = content[:LLM_MAX_PROMPT_LENGTH] + "\n（内容过长，已截断）"
    return render_prompt(template, {
        "bootcamp": bootcamp.name if bootcamp else "",
        "day": sub.day_number,
        "content": content,
    })


# ===== 接口调用 =====

def chat_endpoint(base_url):
    base = (base_url or "").strip().rstrip("/")
    if not base:
        raise LLMUnavailable("未配置 API 地址")
    if base.endswith("/chat/completions"):
        return base
    return base + "/chat/completions"


def call_chat(cfg, prompt, timeout=None, retries=None):
    """调用 OpenAI 兼容的 chat/completions 接口，返回解析后的 JSON。"""
    timeout = int(timeout if timeout is not None else (cfg.timeout or 30))
    retries = int(retries if retries is not None else (cfg.retries or 0))
    url = chat_endpoint(cfg.base_url)
    api_key = decrypt_secret(cfg.api_key_encrypted or "")
    if not api_key:
        raise LLMUnavailable("未配置 API Key")
    if not (cfg.model or "").strip():
        raise LLMUnavailable("未配置模型名称")
    payload = {
        "model": cfg.model,
        "messages": [
            {"role": "system", "content": "你是内容审核助手，只输出 JSON 对象，不要输出多余文字。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": float(cfg.temperature or 0),
        "max_tokens": int(cfg.max_tokens or 800),
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    last_error = None
    for attempt in range(max(1, retries + 1)):
        request = urllib.request.Request(
            url, data=body, method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
            return json.loads(raw)
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                pass
            last_error = LLMUnavailable(f"接口返回 {exc.code}：{detail or exc.reason}")
            if exc.code in (400, 401, 403, 404):
                break  # 参数或鉴权问题重试无意义
        except (socket.timeout, TimeoutError):
            last_error = LLMTimeout(f"请求超时（{timeout} 秒）")
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, (socket.timeout, TimeoutError)):
                last_error = LLMTimeout(f"请求超时（{timeout} 秒）")
            else:
                last_error = LLMUnavailable(f"无法连接接口：{reason}")
        except json.JSONDecodeError:
            last_error = LLMInvalidResponse("接口返回的不是合法 JSON")
        except Exception as exc:
            last_error = LLMUnavailable(f"调用失败：{exc}")
        if attempt < retries:
            time.sleep(min(2 ** attempt, 5))
    raise last_error or LLMUnavailable("调用失败")


# ===== 结果解析 =====

def extract_content(payload):
    """从兼容响应中取出模型文本。"""
    if not isinstance(payload, dict):
        raise LLMInvalidResponse("接口返回内容不是 JSON 对象")
    choices = payload.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        first = choices[0]
        message = first.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if content is None:
            content = first.get("text")
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        if isinstance(content, str):
            return content
    for key in ("output_text", "content", "text"):
        value = payload.get(key)
        if isinstance(value, str):
            return value
    raise LLMInvalidResponse("接口返回内容缺少 choices/message")


def parse_review(text):
    """把模型输出解析为 {passed, reason, risk_level}。"""
    if not isinstance(text, str) or not text.strip():
        raise LLMInvalidResponse("模型没有返回内容")
    candidate = text.strip()
    match = re.search(r"\{.*\}", candidate, re.S)
    if match:
        candidate = match.group(0)
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        raise LLMInvalidResponse("模型返回内容不是合法 JSON")
    if not isinstance(data, dict):
        raise LLMInvalidResponse("模型返回内容不是 JSON 对象")
    if "passed" not in data:
        raise LLMInvalidResponse("模型返回内容缺少 passed 字段")
    passed = data["passed"]
    if isinstance(passed, str):
        passed = passed.strip().lower() in ("true", "yes", "1", "通过")
    if not isinstance(passed, bool):
        raise LLMInvalidResponse("passed 字段不是布尔值")
    reason = str(data.get("reason") or "").strip()[:500] or "模型未给出审核理由"
    risk = str(data.get("risk_level") or "").strip().lower()
    risk = RISK_ALIASES.get(risk, "medium" if risk else "low")
    return {"passed": passed, "reason": reason, "risk_level": risk}


# ===== 结论落库 =====

def apply_auto_decision(db, attempt, passed, reason, risk_level):
    """把模型结论写入审核状态，并同步通知、徽章与操作日志。"""
    sub = db.get(Submission, attempt.submission_id)
    if sub is None:
        return None
    stamp = now()
    comment = f"【AI 自动审核】{reason}"
    result = "approved" if passed else "rejected"
    attempt.review_status = result
    attempt.reviewer_id = None
    attempt.review_comment = comment
    attempt.reviewed_at = stamp
    sub.review_status = result
    sub.reviewer_id = None
    sub.review_comment = comment
    sub.reviewed_at = stamp
    from models.review_assignment import ReviewAssignment
    for assignment in db.query(ReviewAssignment).filter_by(attempt_id=attempt.id, status="pending").all():
        assignment.status = "expired"
        assignment.completed_at = stamp
    db.flush()
    if result == "approved":
        from models.user import User
        from routes.user_routes import _check_and_award_badges
        enrollment = db.get(Enrollment, sub.enrollment_id)
        if enrollment:
            _check_and_award_badges(db, db.get(User, enrollment.user_id), enrollment)
    db.flush()
    from services.inbox import review_result
    review_result(db, sub, attempt, result, comment)
    from services.metrics import capture
    capture(db)
    db.flush()
    from services.audit import record
    record(db, None, "大模型自动审核", "submission", sub.id,
           {"attempt_id": attempt.id, "after": result}, event_type="review.auto_decide")
    db.flush()
    return sub


def _write_log(db, attempt, status, passed=None, risk_level=None, reason=None,
               error=None, latency_ms=None, model=None, raw_response=None):
    entry = LLMReviewLog(
        submission_id=attempt.submission_id, attempt_id=attempt.id, status=status,
        passed=passed, risk_level=risk_level, reason=reason, error=error,
        latency_ms=latency_ms, model=model, raw_response=raw_response,
    )
    db.add(entry)
    db.flush()
    return entry


def review_attempt(db, attempt_id):
    """对一次提交执行大模型审核；异常一律降级为人工审核。"""
    attempt = db.get(SubmissionAttempt, attempt_id)
    if attempt is None:
        return None
    cfg = get_config(db)
    if not cfg.enabled:
        return _write_log(db, attempt, status="disabled", error="大模型自动审核未启用")
    if not (cfg.base_url or "").strip() or not (cfg.model or "").strip() or not decrypt_secret(cfg.api_key_encrypted or ""):
        return _write_log(db, attempt, status="disabled", error="接口配置不完整")
    sub = db.get(Submission, attempt.submission_id)
    if sub is None:
        return _write_log(db, attempt, status="error", error="提交记录不存在")
    prompt = build_prompt(db, cfg, sub, attempt)
    started = time.monotonic()
    try:
        payload = call_chat(cfg, prompt)
    except LLMError as exc:
        latency = int((time.monotonic() - started) * 1000)
        logger.warning("大模型审核失败，转人工审核（attempt=%s）：%s", attempt_id, exc)
        return _write_log(db, attempt, status="error", error=str(exc), latency_ms=latency)
    except Exception as exc:  # 兜底：任何未预期异常都不影响学员提交
        latency = int((time.monotonic() - started) * 1000)
        logger.exception("大模型审核异常，转人工审核（attempt=%s）", attempt_id)
        return _write_log(db, attempt, status="error", error=f"调用异常：{exc}", latency_ms=latency)
    latency = int((time.monotonic() - started) * 1000)
    try:
        content = extract_content(payload)
        result = parse_review(content)
    except LLMError as exc:
        logger.warning("大模型返回格式异常，转人工审核（attempt=%s）：%s", attempt_id, exc)
        return _write_log(db, attempt, status="error", error=str(exc), latency_ms=latency,
                          model=cfg.model, raw_response=str(payload)[:2000])
    status = "manual"
    if cfg.auto_decision:
        if not result["passed"]:
            apply_auto_decision(db, attempt, False, result["reason"], result["risk_level"])
            status = "rejected"
        elif result["risk_level"] == "high":
            status = "manual"  # 高风险内容转人工复核，不自动通过
        else:
            apply_auto_decision(db, attempt, True, result["reason"], result["risk_level"])
            status = "approved"
    entry = _write_log(db, attempt, status=status, passed=result["passed"],
                       risk_level=result["risk_level"], reason=result["reason"],
                       latency_ms=latency, model=cfg.model, raw_response=content[:2000])
    db.flush()
    return entry


def review_attempt_background(submission_id, attempt_id):
    """后台任务入口：使用独立数据库会话，避免阻塞学员提交。"""
    from database import SessionLocal
    db = SessionLocal()
    try:
        review_attempt(db, attempt_id)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("大模型自动审核后台任务失败（submission=%s）", submission_id)
    finally:
        db.close()


def test_connection(cfg):
    """用最小请求验证配置是否可用，返回 (是否成功, 说明文字)。"""
    payload = {
        "model": cfg.model,
        "messages": [{"role": "user", "content": "ping"}],
        "temperature": float(cfg.temperature or 0),
        "max_tokens": 16,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    api_key = decrypt_secret(cfg.api_key_encrypted or "")
    if not api_key:
        return False, "尚未配置 API Key"
    if not (cfg.base_url or "").strip():
        return False, "尚未配置 API 地址"
    request = urllib.request.Request(
        chat_endpoint(cfg.base_url), data=body, method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json",
                 "Authorization": f"Bearer {api_key}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=int(cfg.timeout or 30)) as response:
            raw = response.read().decode("utf-8", errors="replace")
        json.loads(raw)
        return True, "连接成功，接口可用"
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            pass
        return False, f"接口返回 {exc.code}：{detail or exc.reason}"
    except (socket.timeout, TimeoutError):
        return False, "请求超时，请检查网络或调大超时时间"
    except urllib.error.URLError as exc:
        return False, f"无法连接接口：{getattr(exc, 'reason', exc)}"
    except Exception as exc:
        return False, f"连接失败：{exc}"

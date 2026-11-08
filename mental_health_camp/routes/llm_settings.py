"""超级管理员的大模型自动审核配置。"""
import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from auth import require_super_admin, verify_csrf
from config import (APP_NAME, LLM_DEFAULT_MAX_TOKENS, LLM_DEFAULT_MODEL, LLM_DEFAULT_RETRIES,
                    LLM_DEFAULT_TEMPERATURE, LLM_DEFAULT_TIMEOUT, LLM_PROMPT_TEMPLATE)
from database import get_db
from models.llm_review import LLMReviewLog
from models.user import User
from services import llm
from templates_config import templates

logger = logging.getLogger(__name__)

router = APIRouter(tags=["llm_settings"])

MAX_PROMPT_LENGTH = 20000


def _redirect(message="", kind="ok"):
    query = f"?message={quote(message)}&kind={kind}" if message else ""
    return RedirectResponse(f"/super-admin/ai-settings{query}", status_code=303)


def _parse_int(value, field, low, high, default):
    if value in (None, ""):
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise HTTPException(400, f"{field}必须为整数")
    if not low <= number <= high:
        raise HTTPException(400, f"{field}必须在 {low} 到 {high} 之间")
    return number


def _parse_float(value, field, low, high, default):
    if value in (None, ""):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise HTTPException(400, f"{field}必须为数字")
    if not low <= number <= high:
        raise HTTPException(400, f"{field}必须在 {low} 到 {high} 之间")
    return number


@router.get("/super-admin/ai-settings")
async def ai_settings_page(request: Request, admin: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    """大模型自动审核配置页。"""
    cfg = llm.get_config(db)
    logs = db.query(LLMReviewLog).order_by(LLMReviewLog.id.desc()).limit(20).all()
    return templates.TemplateResponse("super_admin/ai_settings.html", {
        "request": request, "user": admin, "app_name": APP_NAME,
        "config": cfg,
        "masked_key": llm.masked_api_key(cfg),
        "logs": logs,
        "defaults": {
            "model": LLM_DEFAULT_MODEL,
            "timeout": LLM_DEFAULT_TIMEOUT,
            "retries": LLM_DEFAULT_RETRIES,
            "temperature": LLM_DEFAULT_TEMPERATURE,
            "max_tokens": LLM_DEFAULT_MAX_TOKENS,
        },
        "default_prompt": LLM_PROMPT_TEMPLATE,
        "message": request.query_params.get("message", ""),
        "kind": request.query_params.get("kind", "ok"),
    })


@router.post("/super-admin/ai-settings")
async def save_ai_settings(request: Request, admin: User = Depends(require_super_admin), db: Session = Depends(get_db), _csrf: None = Depends(verify_csrf)):
    """保存大模型接口参数与审核提示词。"""
    form = await request.form()
    base_url = (form.get("base_url") or "").strip()
    if base_url and not (base_url.startswith("http://") or base_url.startswith("https://")):
        raise HTTPException(400, "API 地址必须以 http:// 或 https:// 开头")
    model = (form.get("model") or "").strip()
    prompt = form.get("prompt_template") or ""
    if len(prompt) > MAX_PROMPT_LENGTH:
        raise HTTPException(400, f"提示词长度不能超过 {MAX_PROMPT_LENGTH} 字符")
    enabled = form.get("enabled") is not None
    if enabled and not (base_url and model and prompt.strip()):
        raise HTTPException(400, "启用自动审核前请填写 API 地址、模型名称与审核提示词")
    values = {
        "enabled": enabled,
        "base_url": base_url,
        "model": model,
        "api_key": (form.get("api_key") or "").strip(),
        "timeout": _parse_int(form.get("timeout"), "超时时间", 1, 300, LLM_DEFAULT_TIMEOUT),
        "retries": _parse_int(form.get("retries"), "重试次数", 0, 5, LLM_DEFAULT_RETRIES),
        "temperature": _parse_float(form.get("temperature"), "温度", 0, 2, LLM_DEFAULT_TEMPERATURE),
        "max_tokens": _parse_int(form.get("max_tokens"), "最大 token 数", 16, 32768, LLM_DEFAULT_MAX_TOKENS),
        "auto_decision": form.get("auto_decision") is not None,
        "prompt_template": prompt,
    }
    cfg = llm.apply_config(db, admin.id, values)
    from services.audit import record
    record(db, admin.id, "更新大模型审核配置", "llm_config", cfg.id,
           {"after": "enabled" if cfg.enabled else "disabled"}, event_type="llm.config.update")
    db.commit()
    return _redirect("配置已保存")


@router.post("/super-admin/ai-settings/test")
async def test_ai_settings(request: Request, admin: User = Depends(require_super_admin), db: Session = Depends(get_db), _csrf: None = Depends(verify_csrf)):
    """用当前配置发送一次最小请求，验证接口可用性。"""
    cfg = llm.get_config(db)
    ok, message = llm.test_connection(cfg)
    if not ok:
        logger.warning("大模型接口连通性测试失败：%s", message)
    return _redirect(message, "ok" if ok else "error")


@router.post("/super-admin/ai-settings/retry/{attempt_id}")
async def retry_auto_review(request: Request, attempt_id: int, admin: User = Depends(require_super_admin), db: Session = Depends(get_db), _csrf: None = Depends(verify_csrf)):
    """对仍处于待审核状态的轮次手动触发一次大模型复审。"""
    from models.workflow import SubmissionAttempt
    attempt = db.get(SubmissionAttempt, attempt_id)
    if attempt is None:
        raise HTTPException(404, "提交轮次不存在")
    if attempt.review_status != "pending":
        raise HTTPException(409, "该轮次已完成审核，无需复审")
    entry = llm.review_attempt(db, attempt_id)
    db.commit()
    status = entry.status if entry else "unknown"
    if status == "error":
        return _redirect(f"复审失败，已转人工审核：{entry.error if entry else '未知错误'}", "error")
    if status == "manual":
        return _redirect("复审完成：结果需人工复核", "ok")
    return _redirect(f"复审完成：{status}", "ok")

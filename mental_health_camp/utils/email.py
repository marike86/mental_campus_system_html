import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from config import SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_USE_SSL, EMAIL_SENDER_NAME, APP_NAME

logger = logging.getLogger(__name__)


def send_email(to_email: str, subject: str, html_body: str) -> bool:
    if not SMTP_HOST or not SMTP_USER or not SMTP_PASSWORD:
        logger.warning("SMTP未配置，跳过邮件发送")
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = f"{EMAIL_SENDER_NAME} <{SMTP_USER}>"
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(html_body, "html", "utf-8"))
        if SMTP_USE_SSL:
            server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=10)
        else:
            server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10)
            server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_USER, [to_email], msg.as_string())
        server.quit()
        logger.info(f"邮件发送成功: {to_email}")
        return True
    except Exception as e:
        logger.error(f"邮件发送失败: {to_email}, 错误: {e}")
        return False


def send_daily_reminder(to_email: str, nickname: str, pending_tasks: list) -> bool:
    task_html = ""
    for task in pending_tasks:
        task_html += f"""
        <tr>
            <td style="padding:8px 12px;border-bottom:1px solid #eee;">{task['bootcamp_name']}</td>
            <td style="padding:8px 12px;border-bottom:1px solid #eee;">第 {task['day_number']} 天</td>
            <td style="padding:8px 12px;border-bottom:1px solid #eee;">
                <a href="{task['form_url']}" style="color:#6366f1;text-decoration:none;font-weight:bold;">去填写</a>
            </td>
        </tr>
        """
    html = f"""
    <div style="font-family:sans-serif;max-width:600px;margin:0 auto;">
        <div style="background:#6366f1;color:white;padding:20px;text-align:center;border-radius:12px 12px 0 0;">
            <h1 style="margin:0;font-size:20px;">{APP_NAME}</h1>
            <p style="margin:8px 0 0;opacity:0.9;">每日打卡提醒</p>
        </div>
        <div style="background:#f9fafb;padding:24px;">
            <p>Hi {nickname}，</p>
            <p>你还有 <strong>{len(pending_tasks)}</strong> 个训练营表单未完成，快来打卡吧！</p>
            <table style="width:100%;border-collapse:collapse;background:white;border-radius:8px;overflow:hidden;margin:16px 0;">
                <tr style="background:#f3f4f6;">
                    <td style="padding:8px 12px;font-weight:bold;font-size:13px;">训练营</td>
                    <td style="padding:8px 12px;font-weight:bold;font-size:13px;">天数</td>
                    <td style="padding:8px 12px;font-weight:bold;font-size:13px;">操作</td>
                </tr>
                {task_html}
            </table>
        </div>
        <div style="text-align:center;padding:16px;color:#9ca3af;font-size:12px;">
            此邮件由系统自动发送，请勿直接回复
        </div>
    </div>
    """
    subject = f"【{APP_NAME}】今日还有未完成的打卡任务"
    return send_email(to_email, subject, html)

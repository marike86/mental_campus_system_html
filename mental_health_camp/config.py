import os
import secrets

# ===== 应用基础配置 =====
APP_NAME = "心理健康训练营"          # 应用/品牌名称，显示在页面标题和导航栏
APP_DESCRIPTION = "每日心理评估，记录你的成长旅程"  # 应用描述，显示在首页
DEBUG = os.getenv("DEBUG", "True").lower() == "true"  # 调试模式开关


def _load_or_generate_key(env_var: str, key_file: str) -> str:
    """加载或生成密钥，优先使用环境变量，其次从文件读取，最后自动生成并保存"""
    key = os.getenv(env_var)
    if key:
        return key
    if os.path.exists(key_file):
        with open(key_file, "r") as f:
            return f.read().strip()
    key = secrets.token_hex(32)
    with open(key_file, "w") as f:
        f.write(key)
    return key


SECRET_KEY = _load_or_generate_key("SECRET_KEY", ".secret_key")  # FastAPI安全密钥

# ===== 数据库配置 =====
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./mental_health_camp.db")  # 数据库连接URL

# ===== JWT认证配置 =====
JWT_SECRET_KEY = _load_or_generate_key("JWT_SECRET_KEY", ".jwt_secret_key")  # JWT签名密钥
JWT_ALGORITHM = "HS256"              # JWT加密算法
JWT_ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "1440"))  # JWT令牌过期时间

# ===== 管理员预设账号 =====
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@camp.com")  # 初始管理员邮箱
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")   # 初始管理员密码
ADMIN_NICKNAME = os.getenv("ADMIN_NICKNAME", "管理员")     # 初始管理员昵称
DEFAULT_ADMIN_PASSWORD = "admin123"                       # 默认口令，仅用于检测未改动的弱口令

# ===== 前端主题配置 =====
PRIMARY_COLOR = "#9c0c13"            # 主色调（山大红）
SECONDARY_COLOR = "#cc293b"          # 辅助色（brand-600）
ACCENT_COLOR = "#06b6d4"             # 强调色（cyan-500）
PRIMARY_BG = "bg-brand-50"           # 主要背景色Tailwind类
PRIMARY_TEXT = "text-brand-800"       # 主要文字颜色Tailwind类
PRIMARY_BTN = "bg-brand-800 hover:bg-brand-700"  # 主要按钮Tailwind类
NAV_BG = "bg-white shadow"           # 导航栏背景Tailwind类

# ===== 表单配置 =====
LIKERT_DEFAULT_MIN = 1               # Likert量表默认最小值
LIKERT_DEFAULT_MAX = 5               # Likert量表默认最大值
LIKERT_DEFAULT_LABELS = ["完全不", "轻微", "中等", "明显", "严重"]  # Likert量表默认标签

# ===== 分页配置 =====
ITEMS_PER_PAGE = 20                  # 列表页每页显示条数

# ===== 阶段二：邮件通知配置 =====
SMTP_HOST = ""                       # SMTP服务器地址，例如 smtp.qq.com
SMTP_PORT = 465                      # SMTP端口号，465为SSL，587为TLS
SMTP_USER = ""                       # SMTP发件人邮箱账号
SMTP_PASSWORD = ""                   # SMTP发件人邮箱密码或授权码
SMTP_USE_SSL = True                  # 是否使用SSL连接SMTP服务器
EMAIL_SENDER_NAME = "心理健康训练营"  # 邮件发件人显示名称
NOTIFICATION_HOUR = 9                # 每日提醒邮件发送时间（小时，24小时制）
NOTIFICATION_MINUTE = 0              # 每日提醒邮件发送时间（分钟）

# ===== 阶段二：数据加密配置 =====
ENCRYPTION_KEY = ""                  # Fernet对称加密密钥（base64编码），留空则使用自动生成密钥
ENCRYPTION_ENABLED = os.getenv("ENCRYPTION_ENABLED", "True").lower() == "true"  # 是否启用答案数据加密

# ===== 每日提交限额 =====
# 每个自然日（北京时间）最多可完成的内容份数；0 表示不限制。
DAILY_SUBMISSION_LIMIT = int(os.getenv("DAILY_SUBMISSION_LIMIT", "1"))

# ===== 大模型自动审核（OpenAI 兼容接口）默认参数 =====
LLM_DEFAULT_MODEL = os.getenv("LLM_DEFAULT_MODEL", "gpt-4o-mini")
LLM_DEFAULT_TIMEOUT = 30             # 单次请求超时（秒）
LLM_DEFAULT_RETRIES = 1              # 失败重试次数
LLM_DEFAULT_TEMPERATURE = 0.0        # 采样温度
LLM_DEFAULT_MAX_TOKENS = 800         # 单次最大生成 token 数
LLM_MAX_PROMPT_LENGTH = 12000        # 送审文本长度上限，超出截断
LLM_PROMPT_TEMPLATE = """你是一名心理健康训练营的内容审核助手。请阅读学员提交的表单内容，判断内容是否合适通过，并给出理由。

请只输出一个 JSON 对象，不要输出其他文字，字段如下：
{"passed": true 或 false, "reason": "审核理由，不超过200字", "risk_level": "low 或 medium 或 high"}

判定标准：
1. 内容完整、有实质回应，没有空泛敷衍或明显复制粘贴痕迹的，passed 为 true。
2. 出现明显不友善、攻击、歧视、色情、政治敏感、违法违规内容的，passed 为 false。
3. 出现自伤、伤人、绝望等高风险表达时，passed 仍为 true，但 risk_level 必须为 high，以便转交人工复核。
4. risk_level 表示内容风险高低，与是否通过无关；无风险时为 low。

课程：{bootcamp}
第 {day} 天题目与作答：
{content}"""            # 审核提示词模板，可在超级管理员页面修改

# ===== 敏感接口限流 =====
LOGIN_RATE_LIMIT = int(os.getenv("LOGIN_RATE_LIMIT", "10"))       # 单窗口内允许的登录尝试次数
LOGIN_RATE_WINDOW = int(os.getenv("LOGIN_RATE_WINDOW", "300"))    # 限流窗口（秒）
REGISTER_RATE_LIMIT = int(os.getenv("REGISTER_RATE_LIMIT", "5"))   # 单窗口内允许的注册次数
REGISTER_RATE_WINDOW = int(os.getenv("REGISTER_RATE_WINDOW", "3600"))

# ===== 阶段二：成就徽章连续打卡阈值 =====
BADGE_STREAK_3_DAYS = 3              # 获得"连续3天"徽章所需连续打卡天数
BADGE_STREAK_7_DAYS = 7              # 获得"连续7天"徽章所需连续打卡天数

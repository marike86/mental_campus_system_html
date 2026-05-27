import os
import secrets

# ===== 应用基础配置 =====
APP_NAME = "心理健康训练营"          # 应用/品牌名称，显示在页面标题和导航栏
APP_DESCRIPTION = "每日心理评估，记录你的成长旅程"  # 应用描述，显示在首页
SECRET_KEY = os.getenv("SECRET_KEY", secrets.token_hex(32))  # FastAPI安全密钥
DEBUG = os.getenv("DEBUG", "True").lower() == "true"  # 调试模式开关

# ===== 数据库配置 =====
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./mental_health_camp.db")  # 数据库连接URL

# ===== JWT认证配置 =====
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", secrets.token_hex(32))  # JWT签名密钥
JWT_ALGORITHM = "HS256"              # JWT加密算法
JWT_ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "1440"))  # JWT令牌过期时间

# ===== 管理员预设账号 =====
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@camp.com")  # 初始管理员邮箱
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")   # 初始管理员密码
ADMIN_NICKNAME = os.getenv("ADMIN_NICKNAME", "管理员")     # 初始管理员昵称

# ===== 前端主题配置 =====
PRIMARY_COLOR = "#6366f1"            # 主色调（indigo-500）
SECONDARY_COLOR = "#8b5cf6"          # 辅助色（violet-500）
ACCENT_COLOR = "#06b6d4"             # 强调色（cyan-500）
PRIMARY_BG = "bg-indigo-50"          # 主要背景色Tailwind类
PRIMARY_TEXT = "text-indigo-600"      # 主要文字颜色Tailwind类
PRIMARY_BTN = "bg-indigo-600 hover:bg-indigo-700"  # 主要按钮Tailwind类
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
ENCRYPTION_ENABLED = False           # 是否启用答案数据加密（生产环境建议开启）

# ===== 阶段二：成就徽章连续打卡阈值 =====
BADGE_STREAK_3_DAYS = 3              # 获得"连续3天"徽章所需连续打卡天数
BADGE_STREAK_7_DAYS = 7              # 获得"连续7天"徽章所需连续打卡天数

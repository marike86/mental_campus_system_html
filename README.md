# 心理健康训练营

**每日心理评估，记录你的成长旅程**

一个基于 FastAPI 的 Web 应用，为心理健康训练营提供完整的管理平台，支持用户注册登录、每日心理评估表单填写、训练营管理、成就徽章系统、邮件提醒等功能。

---

## 目录

- [功能特性](#功能特性)
- [技术栈](#技术栈)
- [环境要求](#环境要求)
- [安装指南](#安装指南)
- [配置说明](#配置说明)
- [使用说明](#使用说明)
- [项目结构](#项目结构)
- [开发指南](#开发指南)
- [测试](#测试)
- [部署指南](#部署指南)
- [安全建议](#安全建议)
- [常见问题](#常见问题)
- [许可证](#许可证)
- [联系方式](#联系方式)

---

详细的课程版本、审核领取、通知、运营及升级说明见 [WORKFLOWS.md](mental_health_camp/WORKFLOWS.md)。

## 功能特性

### 用户端功能

| 功能 | 说明 |
|------|------|
| 注册/登录 | 邮箱注册，JWT Cookie 认证，支持用户信息管理 |
| 训练营浏览 | 查看可参加的训练营列表，支持一键加入 |
| 每日打卡 | 填写 Likert 量表心理评估表单，支持多种题型 |
| 打卡历史 | 查看历史提交记录，追踪个人成长轨迹 |
| 成就徽章 | 根据打卡行为自动获得徽章（首次打卡、连续3天、连续7天、训练营毕业） |
| 数据仪表盘 | 可视化展示打卡数据、连续天数、Likert 趋势图 |
| 通知设置 | 开关每日邮件提醒功能 |

### 管理端功能

| 功能 | 说明 |
|------|------|
| 仪表盘 | 查看整体数据统计（用户数、训练营数、提交数等） |
| 训练营管理 | 创建/编辑/激活/停用训练营，支持自定义天数 |
| 用户管理 | 查看/编辑用户信息，重置密码，删除用户（级联删除关联数据） |
| 表单编辑器 | 可视化编辑每日评估表单，支持文本、单选、Likert 量表等题型 |
| 批次管理 | 创建/编辑/删除批次，支持按时间段分组管理 |
| 批量分配 | 批量将用户分配到训练营，自动跳过已报名用户 |
| 审计日志 | 记录所有管理员操作，支持查看详情 |
| 数据导出 | 按训练营导出用户提交数据为 CSV 格式 |
| 审核员管理 | 创建/管理审核员账号，支持审核任务分配和统计 |

### 审核员功能

| 功能 | 说明 |
|------|------|
| 待审核列表 | 查看待审核的提交记录 |
| 审核操作 | 批准/驳回提交，添加审核意见 |
| 审核详情 | 查看提交详情和审核历史 |

---

## 技术栈

| 组件 | 技术 | 版本要求 |
|------|------|----------|
| 后端框架 | FastAPI | >= 0.104.1 |
| ASGI 服务器 | Uvicorn | >= 0.24.0 |
| 数据库 | SQLite (SQLAlchemy ORM) | >= 2.0.40 |
| 模板引擎 | Jinja2 | >= 3.1.2 |
| 前端样式 | Tailwind CSS (CDN) | - |
| 认证方式 | JWT (python-jose) | >= 3.3.0 |
| 密码加密 | bcrypt (passlib) | >= 1.7.4 |
| 数据加密 | Fernet (cryptography) | >= 41.0.0 |
| 表单解析 | python-multipart | >= 0.0.6 |

---

## 环境要求

- **Python** >= 3.10
- **pip** (Python 包管理器)
- **操作系统**：Windows / Linux / macOS

---

## 安装指南

### 1. 克隆项目

```bash
git clone <repository-url>
cd jianxin_system/mental_health_camp
```

### 2. 创建虚拟环境（推荐）

```bash
# Windows
python -m venv venv
venv\Scripts\activate

# Linux / macOS
python3 -m venv venv
source venv/bin/activate
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

### 4. 配置环境变量

复制示例配置并修改（详见[配置说明](#配置说明)）：

```bash
# 设置必要的环境变量
export SECRET_KEY="your-random-secret-key"
export JWT_SECRET_KEY="your-random-jwt-secret"
export ADMIN_PASSWORD="your-strong-password"
```

### 5. 启动应用

```bash
# 首次安装与升级均先执行显式迁移
python migrate.py

# 开发模式（自动重载）
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# 生产模式
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
```

### 6. 访问应用

启动成功后访问：`http://localhost:8000`

---

## 配置说明

### 环境变量

应用通过环境变量进行配置，可在 `config.py` 中查看所有配置项。

#### 必须配置（生产环境）

| 环境变量 | 说明 | 默认值 |
|----------|------|--------|
| `SECRET_KEY` | FastAPI 安全密钥 | 自动生成随机密钥 |
| `JWT_SECRET_KEY` | JWT 签名密钥 | 自动生成随机密钥 |
| `ADMIN_PASSWORD` | 初始管理员密码 | `admin123` |
| `DEBUG` | 调试模式开关 | `True` |

#### 管理员账号配置

| 环境变量 | 说明 | 默认值 |
|----------|------|--------|
| `ADMIN_EMAIL` | 初始管理员邮箱 | `admin@camp.com` |
| `ADMIN_PASSWORD` | 初始管理员密码 | `admin123` |
| `ADMIN_NICKNAME` | 初始管理员昵称 | `管理员` |

#### JWT 认证配置

| 环境变量 | 说明 | 默认值 |
|----------|------|--------|
| `JWT_SECRET_KEY` | JWT 签名密钥 | 自动生成 |
| `JWT_ALGORITHM` | JWT 加密算法 | `HS256` |
| `JWT_EXPIRE_MINUTES` | JWT 令牌过期时间（分钟） | `1440`（24小时） |

#### 邮件通知配置

| 环境变量 | 说明 | 默认值 |
|----------|------|--------|
| `SMTP_HOST` | SMTP 服务器地址 | 空（禁用） |
| `SMTP_PORT` | SMTP 端口号 | `465` |
| `SMTP_USER` | SMTP 发件人邮箱 | 空 |
| `SMTP_PASSWORD` | SMTP 邮箱密码/授权码 | 空 |
| `SMTP_USE_SSL` | 是否使用 SSL | `True` |
| `NOTIFICATION_HOUR` | 每日提醒时间（小时） | `9` |
| `NOTIFICATION_MINUTE` | 每日提醒时间（分钟） | `0` |

#### 数据加密配置

| 环境变量 | 说明 | 默认值 |
|----------|------|--------|
| `ENCRYPTION_ENABLED` | 是否启用数据加密 | `False` |
| `ENCRYPTION_KEY` | Fernet 加密密钥 | 自动生成 |

### 生成密钥

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

---

## 使用说明

### 用户端使用流程

1. **注册账号**
   - 访问 `/register` 页面
   - 填写邮箱、密码、昵称（必填）
   - 可选填写学院、学号、年级

2. **登录系统**
   - 访问 `/login` 页面
   - 输入邮箱和密码
   - 系统根据角色自动跳转到对应页面

3. **加入训练营**
   - 访问 `/user/bootcamps` 查看可参加的训练营
   - 点击"加入"按钮报名

4. **每日打卡**
   - 访问 `/user/today` 查看今日任务
   - 填写心理评估表单
   - 提交后获得打卡记录

5. **查看成就**
   - 访问 `/user/badges` 查看已获得的徽章
   - 系统自动根据打卡行为颁发徽章

### 管理端使用流程

1. **登录管理后台**
   - 使用管理员账号登录
   - 自动跳转到 `/admin/dashboard`

2. **创建训练营**
   - 访问 `/admin/bootcamps`
   - 点击"新建训练营"
   - 填写名称、描述、天数
   - 为每天配置评估表单

3. **管理用户**
   - 访问 `/admin/users` 查看用户列表
   - 支持编辑信息、重置密码、删除用户

4. **批量分配**
   - 在训练营详情页选择用户
   - 批量分配到指定批次

5. **数据导出**
   - 访问 `/admin/export`
   - 选择训练营，导出 CSV 数据

### 题型说明

表单编辑器支持以下题型：

| 题型 | 说明 | 配置参数 |
|------|------|----------|
| `text` | 文本输入 | `label`（标签）、`placeholder`（占位符） |
| `single` | 单选题 | `label`、`options`（选项列表）、`correct`（正确答案，可选） |
| `likert` | Likert 量表 | `label`、`min`（最小值）、`max`（最大值）、`labels`（等级标签） |

---

## 项目结构

```
jianxin_system/
├── README.md                    # 项目说明文档
├── 部署说明.md                   # 部署指南
└── mental_health_camp/          # 应用主目录
    ├── main.py                  # FastAPI 应用入口
    ├── config.py                # 全局配置文件
    ├── database.py              # 数据库初始化与会话管理
    ├── auth.py                  # JWT 认证逻辑
    ├── templates_config.py      # 模板配置
    ├── requirements.txt         # Python 依赖清单
    ├── tests.py                 # 测试文件
    ├── models/                  # 数据模型（SQLAlchemy ORM）
    │   ├── __init__.py
    │   ├── user.py              # 用户模型
    │   ├── bootcamp.py          # 训练营模型
    │   ├── day_form.py          # 每日表单模型
    │   ├── enrollment.py        # 报名模型
    │   ├── submission.py        # 提交记录模型
    │   ├── batch.py             # 批次模型
    │   ├── badge.py             # 徽章模型
    │   ├── user_badge.py        # 用户徽章模型
    │   ├── audit_log.py         # 审计日志模型
    │   └── review_assignment.py # 审核任务分配模型
    ├── routes/                  # 路由模块
    │   ├── __init__.py
    │   ├── auth_routes.py       # 登录/注册路由
    │   ├── user_routes.py       # 用户端路由
    │   ├── admin_routes.py      # 管理后台路由
    │   ├── dashboard.py         # 仪表盘数据接口
    │   ├── audit.py             # 审计日志路由
    │   ├── notification.py      # 邮件通知路由
    │   ├── review.py            # 审核路由
    │   └── reviewer_management.py # 审核员管理路由
    ├── utils/                   # 工具模块
    │   ├── __init__.py
    │   ├── email.py             # 邮件发送工具
    │   └── crypto.py            # 数据加密工具
    ├── templates/               # HTML 模板
    │   ├── base.html            # 基础布局模板
    │   ├── index.html           # 首页
    │   ├── login.html           # 登录页
    │   ├── register.html        # 注册页
    │   ├── admin/               # 管理后台页面
    │   ├── user/                # 用户端页面
    │   ├── review/              # 审核页面
    │   └── super_admin/         # 超级管理员页面
    └── static/                  # 静态资源
        └── js/                  # JavaScript 文件
```

---

## 开发指南

### 代码规范

#### 命名规范

- 路由函数：`动词_名词` 格式，如 `admin_bootcamps`、`create_bootcamp`
- 模型类：`PascalCase`，如 `Bootcamp`、`DayForm`
- 配置常量：`UPPER_SNAKE_CASE`，如 `APP_NAME`、`JWT_SECRET_KEY`
- 内部辅助函数：以 `_` 开头，如 `_extract_user_id`、`_create_admin_if_needed`

#### 依赖管理

- `requirements.txt` 中所有依赖使用精确版本号（`==`）
- 新增依赖前确认与现有依赖的兼容性

#### 错误处理

- 每个路由函数须有顶层 `try/except`
- 表单输入必须进行空值检查、类型转换安全处理
- 认证失败返回 303 重定向到登录页
- 权限不足返回 403 Forbidden

#### 数据库操作

- 使用依赖注入（`Depends(get_db)`）获取会话
- 写操作后调用 `db.commit()`
- 使用 `server_default=func.now()` 设置时间字段

### 添加新路由模块

1. 在 `routes/` 目录创建新文件
2. 定义 `router` 对象
3. 应用启动时自动扫描并注册

```python
# routes/example.py
from fastapi import APIRouter

router = APIRouter()

@router.get("/example")
async def example():
    return {"message": "Hello"}
```

---

## 测试

### 运行测试

```bash
# 进入项目目录
cd mental_health_camp

# 安装测试依赖
python -m pip install -r requirements-dev.txt

# 使用 pytest 运行（推荐）
python -m pytest tests.py test_regressions.py test_workflows.py test_migrations.py -v

# 验证课程前端的令牌传递（需要 Node.js）
node --test test_camp_content.js test_draft.js

# 运行特定测试类
pytest tests.py::TestLoginRoutes -v

# 运行特定测试方法
pytest tests.py::TestLoginRoutes::test_login_success_admin -v
```

### 测试覆盖范围

测试文件 `tests.py` 包含以下测试类别：

| 测试类别 | 说明 |
|----------|------|
| 认证测试 | 登录、注册、JWT 令牌验证 |
| 权限测试 | 未认证访问、无效令牌、过期令牌、权限不足 |
| CRUD 测试 | 训练营、批次、用户的增删改查 |
| 表单测试 | 表单填写、提交、重复提交处理 |
| 导出测试 | CSV 数据导出功能 |
| 审计日志测试 | 日志记录和查询 |
| 模型测试 | 数据模型字段完整性 |
| 加密测试 | 数据加密解密功能 |
| 路由注册测试 | 验证所有预期路由存在 |

### 测试场景覆盖

- 未认证访问受保护端点 → 303 重定向到 /login
- 无效/过期 token 访问 → 303 重定向到 /login
- 普通用户访问管理员端点 → 403
- 管理员正常访问所有端点 → 200
- 表单提交空值/非法类型参数 → 400
- 应用启动后路由注册完整 → 验证所有预期路由存在

---

## 部署指南

### 开发环境部署

```bash
cd mental_health_camp
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 生产环境部署

#### 1. 配置环境变量

```bash
export SECRET_KEY="your-strong-secret-key"
export JWT_SECRET_KEY="your-strong-jwt-secret"
export ADMIN_PASSWORD="your-strong-admin-password"
export DEBUG="False"
```

#### 2. 启动应用

```bash
uvicorn main:app --host 127.0.0.1 --port 8000 --workers 4
```

#### 3. 使用 Nginx 反向代理（推荐）

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location /static/ {
        alias /path/to/mental_health_camp/static/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

#### 4. 配置 HTTPS（Let's Encrypt）

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

#### 5. 使用 systemd 守护进程（Linux）

创建服务文件 `/etc/systemd/system/mental-health-camp.service`：

```ini
[Unit]
Description=Mental Health Camp FastAPI App
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/path/to/mental_health_camp
ExecStart=/path/to/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000 --workers 4
Restart=always
RestartSec=5
Environment="PYTHONUNBUFFERED=1"

[Install]
WantedBy=multi-user.target
```

启动并设置开机自启：

```bash
sudo systemctl daemon-reload
sudo systemctl enable mental-health-camp
sudo systemctl start mental-health-camp
sudo systemctl status mental-health-camp
```

### 数据备份

```bash
# 备份数据库
cp mental_health_camp.db mental_health_camp.db.bak.$(date +%Y%m%d)

# 备份加密密钥（如已启用）
cp .encryption_key .encryption_key.bak
```

建议使用 crontab 设置每日自动备份：

```bash
# 每天凌晨 3 点备份
0 3 * * * cp /path/to/mental_health_camp.db /backup/mental_health_camp.db.$(date +\%Y\%m\%d)
```

---

## 安全建议

1. **修改默认密钥**：`SECRET_KEY` 和 `JWT_SECRET_KEY` 必须替换为随机强密钥
2. **修改默认管理员密码**：部署后立即修改 `ADMIN_PASSWORD`
3. **关闭 DEBUG 模式**：生产环境设置 `DEBUG=False`
4. **启用 HTTPS**：通过 Nginx + Let's Encrypt 配置 SSL
5. **启用数据加密**：设置 `ENCRYPTION_ENABLED=True`
6. **定期备份**：备份数据库文件和加密密钥
7. **限制访问端口**：仅开放 80/443 端口
8. **配置防火墙**：限制不必要的网络访问

---

## 常见问题

### Q: 数据库文件在哪里？

数据库文件自动生成在 `mental_health_camp/` 目录下，文件名为 `mental_health_camp.db`。

### Q: 如何重置管理员密码？

在 `config.py` 中修改 `ADMIN_PASSWORD`，重启应用。应用会检测管理员账号是否存在，但不会覆盖已有账号。如需重置，可手动删除数据库中的管理员记录后重启。

### Q: 邮件发送不了？

检查 `config.py` 中的 SMTP 配置是否正确。如果 SMTP 信息为空，系统会跳过邮件发送并在日志中输出警告，不影响其他功能。

### Q: 如何修改应用端口？

启动命令中修改 `--port` 参数，或者修改 Nginx 反向代理配置。

### Q: 加密密钥丢失怎么办？

如果 `ENCRYPTION_KEY` 为空且 `.encryption_key` 文件丢失，系统会自动生成新密钥，但之前加密的数据将无法解密。**务必妥善备份加密密钥**。

### Q: 如何查看应用日志？

应用日志默认输出到控制台。生产环境建议配置日志文件：

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --log-config logging.ini
```

### Q: 如何扩展更多题型？

在 `templates/admin/form_editor.html` 中添加新题型的表单组件，并在 `routes/user_routes.py` 中处理对应的提交逻辑。

---

## 许可证

本项目为内部项目，未经授权不得复制或分发。

---

## 联系方式

如有问题或建议，请通过以下方式联系：

- **项目维护者**：[维护者姓名]
- **邮箱**：[联系邮箱]
- **问题反馈**：[Issue 链接]

---

## 更新日志

### v1.0.0 (2026-06-06)

- 初始版本发布
- 用户注册登录系统
- 训练营管理功能
- 每日打卡系统
- 成就徽章系统
- 邮件通知功能
- 数据导出功能
- 审计日志系统
- 审核员管理系统

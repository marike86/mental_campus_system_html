# 心理健康训练营Web系统 - 阶段一 MVP 规格

## Why
构建一个心理健康训练营管理系统，让管理员可以创建训练营并配置每日表单，让用户参与训练营、每日填写心理评估表单并追踪个人进度。采用"拼图式编码"架构，支持模块化扩展。

## 技术栈
- **后端**：Python + FastAPI + SQLAlchemy + SQLite（开发用，后续可换PostgreSQL）
- **前端**：Jinja2模板 + HTMX + TailwindCSS CDN
- **图表**：Chart.js CDN
- **认证**：JWT（python-jose）+ bcrypt

## What Changes
- 新建完整项目骨架：config.py、main.py、database.py、auth.py
- 新建5个SQLAlchemy数据模型：User、Bootcamp、DayForm、Enrollment、Submission
- 实现自动路由扫描机制（遍历routes目录自动include_router）
- 实现JWT认证系统（注册、登录、权限校验依赖）
- 实现公共页面：首页、登录页、注册页
- 实现用户端页面：今日任务、表单填写、我的进度、个人信息
- 实现管理员端页面：训练营管理、表单编辑器、用户管理、数据导出
- 表单题目采用JSON字段存储，支持文本框、单选、多选、1-5分Likert量表
- 响应式设计，PC端和移动端自适应

## Impact
- **Affected specs**: 全新项目，无影响现有规格
- **Affected code**: 全部新建文件，遵循拼图式编码原则（新增功能只需新增文件，不修改现有文件）

## 项目结构

```
mental_health_camp/
├── config.py              # 配置集中：颜色主题、JWT密钥、品牌名等
├── main.py                # FastAPI应用入口，自动扫描注册路由
├── database.py            # 数据库连接和模型基类
├── auth.py                # JWT认证和权限校验依赖
├── models/                # SQLAlchemy模型
│   ├── __init__.py
│   ├── user.py
│   ├── bootcamp.py
│   ├── day_form.py
│   ├── enrollment.py
│   └── submission.py
├── routes/                # 路由模块（main.py自动扫描）
│   ├── __init__.py
│   ├── auth_routes.py
│   ├── user_routes.py
│   ├── admin_routes.py
│   └── bootcamp_routes.py
├── templates/             # Jinja2模板
│   ├── base.html
│   ├── index.html
│   ├── login.html
│   ├── register.html
│   ├── user/
│   │   ├── dashboard.html
│   │   ├── today.html
│   │   ├── form.html
│   │   └── history.html
│   └── admin/
│       ├── bootcamps.html
│       ├── form_editor.html
│       ├── users.html
│       └── export.html
└── static/
    └── js/
        └── draft.js       # 自动保存草稿逻辑
```

## ADDED Requirements

### Requirement: 配置管理
系统 SHALL 提供集中配置文件 `config.py`，所有用户可配置参数均在此文件中定义，并附带详细中文注释说明每个配置项的用途。其他文件仅通过 `from config import XXX` 引用，不得自行定义配置值。

#### config.py 配置项清单（每个变量必须附带中文注释）

**应用基础配置：**
- `APP_NAME` — 应用/品牌名称，显示在页面标题和导航栏
- `APP_DESCRIPTION` — 应用描述，显示在首页
- `SECRET_KEY` — Flask/FastAPI安全密钥，用于签名session等
- `DEBUG` — 调试模式开关，生产环境设为False

**数据库配置：**
- `DATABASE_URL` — 数据库连接URL，开发用sqlite:///./mental_health_camp.db，生产可换PostgreSQL

**JWT认证配置：**
- `JWT_SECRET_KEY` — JWT签名密钥，生产环境必须更换
- `JWT_ALGORITHM` — JWT加密算法，默认HS256
- `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` — JWT令牌过期时间（分钟），默认1440（24小时）

**管理员预设账号：**
- `ADMIN_EMAIL` — 初始管理员邮箱
- `ADMIN_PASSWORD` — 初始管理员密码
- `ADMIN_NICKNAME` — 初始管理员昵称

**前端主题配置：**
- `PRIMARY_COLOR` — 主色调（TailwindCSS类名或HEX值）
- `SECONDARY_COLOR` — 辅助色
- `ACCENT_COLOR` — 强调色
- `BG_COLOR` — 页面背景色
- `TEXT_COLOR` — 主要文字颜色

**表单配置：**
- `LIKERT_DEFAULT_MIN` — Likert量表默认最小值
- `LIKERT_DEFAULT_MAX` — Likert量表默认最大值
- `LIKERT_DEFAULT_LABELS` — Likert量表默认标签列表

**分页配置：**
- `ITEMS_PER_PAGE` — 列表页每页显示条数

#### Scenario: 配置修改
- **WHEN** 开发者修改 `config.py` 中的配置
- **THEN** 全局配置生效，无需修改其他文件

### Requirement: 自动路由扫描
系统 SHALL 在 `main.py` 启动时自动扫描 `routes/` 目录下的所有路由模块并注册。

#### Scenario: 新增路由模块
- **WHEN** 开发者在 `routes/` 目录下新增一个包含 `router` 对象的Python文件
- **THEN** 应用启动时自动发现并注册该路由，无需修改 `main.py`

### Requirement: 用户认证
系统 SHALL 提供基于JWT的用户认证系统。

#### Scenario: 用户注册
- **WHEN** 未注册用户提交邮箱、密码、昵称
- **THEN** 系统创建用户账号（默认角色为user），返回登录页

#### Scenario: 用户登录
- **WHEN** 已注册用户提交正确的邮箱和密码
- **THEN** 系统生成JWT令牌，设置cookie，重定向到用户仪表板

#### Scenario: 未认证访问
- **WHEN** 未登录用户尝试访问需要认证的页面
- **THEN** 系统重定向到登录页

#### Scenario: 权限不足
- **WHEN** 普通用户尝试访问管理员页面
- **THEN** 系统返回403错误

### Requirement: 用户今日任务
系统 SHALL 为已登录用户显示今日待填表单。

#### Scenario: 显示今日任务
- **WHEN** 用户访问今日任务页
- **THEN** 系统显示该用户参与的训练营中今日需要填写的表单列表

#### Scenario: 填写表单
- **WHEN** 用户点击某个表单进入填写页
- **THEN** 系统显示该日的表单题目，支持文本框、单选、多选、1-5分Likert量表

#### Scenario: 自动保存草稿
- **WHEN** 用户在填写过程中
- **THEN** 系统通过localStorage自动保存草稿，刷新页面后可恢复

#### Scenario: 提交表单
- **WHEN** 用户提交表单
- **THEN** 系统保存答案到Submission表，显示"已完成今日任务"

#### Scenario: 重复提交
- **WHEN** 用户尝试提交已完成的表单
- **THEN** 系统提示已提交，显示历史答案

### Requirement: 用户进度追踪
系统 SHALL 为已登录用户显示参与训练营的进度。

#### Scenario: 查看训练营列表
- **WHEN** 用户访问我的进度页
- **THEN** 显示用户参与的所有训练营及完成百分比（已完成天数/总天数）

#### Scenario: 查看历史记录
- **WHEN** 用户点击某个训练营
- **THEN** 显示该训练营的历史填写记录列表

### Requirement: 个人信息管理
系统 SHALL 允许用户修改个人信息。

#### Scenario: 修改昵称
- **WHEN** 用户在个人信息页提交新昵称
- **THEN** 系统更新用户昵称

#### Scenario: 修改密码
- **WHEN** 用户提交当前密码和新密码
- **THEN** 系统验证旧密码后更新为新密码

### Requirement: 管理员训练营管理
系统 SHALL 允许管理员创建和管理训练营。

#### Scenario: 创建训练营
- **WHEN** 管理员提交训练营名称、描述、天数
- **THEN** 系统创建训练营并进入表单配置页面

#### Scenario: 配置每日表单
- **WHEN** 管理员为某天配置表单题目
- **THEN** 系统支持添加/编辑/删除题目，题目类型支持文本框、单选、多选、Likert量表

#### Scenario: 发布训练营
- **WHEN** 管理员将训练营状态设为发布
- **THEN** 训练营变为活跃状态，可被分配给用户

#### Scenario: 下线训练营
- **WHEN** 管理员将训练营状态设为下线
- **THEN** 训练营变为非活跃状态，新用户无法加入

### Requirement: 管理员用户管理
系统 SHALL 允许管理员管理用户与训练营的分配关系。

#### Scenario: 查看用户列表
- **WHEN** 管理员访问用户管理页
- **THEN** 显示所有用户列表

#### Scenario: 分配用户到训练营
- **WHEN** 管理员选择用户和训练营
- **THEN** 系统创建Enrollment记录，用户可在今日任务中看到该训练营

### Requirement: 数据导出
系统 SHALL 允许管理员导出训练营的填写数据。

#### Scenario: 导出CSV
- **WHEN** 管理员选择某个训练营并点击导出
- **THEN** 系统生成CSV文件，包含用户昵称、日期、题目、答案

## MODIFIED Requirements
无（全新项目）

## REMOVED Requirements
无

## 数据库模型

### User
| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer, PK | 用户ID |
| email | String, unique | 邮箱 |
| nickname | String | 昵称 |
| hashed_password | String | 加密密码 |
| role | String (user/admin) | 角色，默认user |
| created_at | DateTime | 创建时间 |

### Bootcamp
| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer, PK | 训练营ID |
| name | String | 训练营名称 |
| description | Text | 描述 |
| days | Integer | 总天数 |
| is_active | Boolean | 是否活跃 |
| created_by | Integer, FK(User.id) | 创建者 |
| created_at | DateTime | 创建时间 |

### DayForm
| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer, PK | 表单ID |
| bootcamp_id | Integer, FK(Bootcamp.id) | 所属训练营 |
| day_number | Integer | 第几天 |
| questions | JSON | 题目配置JSON |

questions JSON格式：
```json
[
  {"id": "q1", "type": "text", "label": "今天心情如何？"},
  {"id": "q2", "type": "single", "label": "睡眠质量", "options": ["很好","一般","较差"]},
  {"id": "q3", "type": "multiple", "label": "今日活动", "options": ["运动","阅读","冥想","其他"]},
  {"id": "q4", "type": "likert", "label": "焦虑程度", "min": 1, "max": 5, "labels": ["完全不","轻微","中等","明显","严重"]}
]
```

### Enrollment
| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer, PK | 报名ID |
| user_id | Integer, FK(User.id) | 用户ID |
| bootcamp_id | Integer, FK(Bootcamp.id) | 训练营ID |
| start_date | Date | 开始日期 |
| created_at | DateTime | 创建时间 |

### Submission
| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer, PK | 提交ID |
| enrollment_id | Integer, FK(Enrollment.id) | 报名ID |
| day_number | Integer | 第几天 |
| answers | JSON | 答案JSON |
| submitted_at | DateTime | 提交时间 |

## API路由设计

### 公共路由
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 首页 |
| GET | `/login` | 登录页 |
| POST | `/login` | 登录处理 |
| GET | `/register` | 注册页 |
| POST | `/register` | 注册处理 |
| GET | `/logout` | 退出登录 |

### 用户路由
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/user/dashboard` | 用户仪表板 |
| GET | `/user/today` | 今日任务 |
| GET | `/user/form/{enrollment_id}/{day}` | 填写表单页 |
| POST | `/user/form/{enrollment_id}/{day}` | 提交表单 |
| GET | `/user/progress` | 我的进度 |
| GET | `/user/history/{enrollment_id}` | 历史记录 |
| GET | `/user/profile` | 个人信息页 |
| POST | `/user/profile` | 更新个人信息 |
| POST | `/user/password` | 修改密码 |

### 管理员路由
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/admin/bootcamps` | 训练营列表 |
| GET | `/admin/bootcamp/new` | 创建训练营页 |
| POST | `/admin/bootcamp/new` | 创建训练营处理 |
| GET | `/admin/bootcamp/{id}` | 训练营详情/编辑 |
| POST | `/admin/bootcamp/{id}` | 更新训练营 |
| GET | `/admin/bootcamp/{id}/day/{day}` | 配置某天表单 |
| POST | `/admin/bootcamp/{id}/day/{day}` | 保存某天表单 |
| POST | `/admin/bootcamp/{id}/toggle` | 发布/下线训练营 |
| GET | `/admin/users` | 用户列表 |
| POST | `/admin/enroll` | 分配用户到训练营 |
| GET | `/admin/export` | 数据导出页 |
| POST | `/admin/export` | 生成CSV下载 |

# Tasks

- [ ] Task 1: 项目初始化和基础设施搭建
  - [ ] SubTask 1.1: 创建项目目录结构（mental_health_camp/ 下所有子目录）
  - [ ] SubTask 1.2: 编写 config.py — 集中管理所有配置项（颜色主题、JWT密钥、数据库URL、品牌名等）
  - [ ] SubTask 1.3: 编写 database.py — SQLAlchemy引擎、会话管理、Base基类
  - [ ] SubTask 1.4: 编写 main.py — FastAPI应用入口，自动扫描routes/目录注册路由，挂载静态文件和模板
  - [ ] SubTask 1.5: 编写 requirements.txt — 列出所有Python依赖

- [ ] Task 2: 数据模型层
  - [ ] SubTask 2.1: 编写 models/user.py — User模型（id, email, nickname, hashed_password, role, created_at）
  - [ ] SubTask 2.2: 编写 models/bootcamp.py — Bootcamp模型（id, name, description, days, is_active, created_by, created_at）
  - [ ] SubTask 2.3: 编写 models/day_form.py — DayForm模型（id, bootcamp_id, day_number, questions JSON）
  - [ ] SubTask 2.4: 编写 models/enrollment.py — Enrollment模型（id, user_id, bootcamp_id, start_date, created_at）
  - [ ] SubTask 2.5: 编写 models/submission.py — Submission模型（id, enrollment_id, day_number, answers JSON, submitted_at）
  - [ ] SubTask 2.6: 编写 models/__init__.py — 导出所有模型，确保自动建表

- [ ] Task 3: 认证系统
  - [ ] SubTask 3.1: 编写 auth.py — JWT令牌创建/验证函数，get_current_user依赖，require_admin依赖
  - [ ] SubTask 3.2: 编写 routes/auth_routes.py — 注册、登录、退出登录路由（GET/POST）
  - [ ] SubTask 3.3: 创建初始管理员账号（首次启动时自动创建）

- [x] Task 4: 基础模板和静态资源
  - [ ] SubTask 4.1: 创建 static/js/draft.js — localStorage自动保存/恢复草稿逻辑
  - [ ] SubTask 4.2: 编写 templates/base.html — 基础模板，引入TailwindCSS CDN、HTMX CDN、Chart.js CDN，包含导航栏框架
  - [ ] SubTask 4.3: 编写 templates/index.html — 首页（训练营介绍，登录/注册入口）
  - [ ] SubTask 4.4: 编写 templates/login.html — 登录页
  - [ ] SubTask 4.5: 编写 templates/register.html — 注册页

- [ ] Task 5: 用户端路由和页面
  - [ ] SubTask 5.1: 编写 routes/user_routes.py — 用户仪表板、今日任务、表单填写/提交、进度、历史、个人信息路由
  - [ ] SubTask 5.2: 编写 templates/user/dashboard.html — 用户仪表板
  - [ ] SubTask 5.3: 编写 templates/user/today.html — 今日任务页，显示待填表单列表
  - [ ] SubTask 5.4: 编写 templates/user/form.html — 表单填写页，支持4种题型，集成HTMX提交和自动保存草稿
  - [ ] SubTask 5.5: 编写 templates/user/history.html — 历史填写记录页

- [x] Task 6: 管理员端路由和页面
  - [ ] SubTask 6.1: 编写 routes/admin_routes.py — 训练营CRUD、表单配置、用户管理、数据导出路由
  - [ ] SubTask 6.2: 编写 templates/admin/bootcamps.html — 训练营列表页
  - [ ] SubTask 6.3: 编写 templates/admin/form_editor.html — 表单题目编辑器（增删改查题目，支持4种题型配置）
  - [ ] SubTask 6.4: 编写 templates/admin/users.html — 用户列表和训练营分配页
  - [ ] SubTask 6.5: 编写 templates/admin/export.html — 数据导出页（选择训练营，生成CSV下载）

- [ ] Task 7: 端到端测试和验证
  - [ ] SubTask 7.1: 验证项目可正常启动（python main.py）
  - [ ] SubTask 7.2: 验证自动路由扫描机制正常工作
  - [ ] SubTask 7.3: 验证注册/登录/退出流程
  - [ ] SubTask 7.4: 验证管理员创建训练营、配置表单、发布流程
  - [ ] SubTask 7.5: 验证用户参与训练营、填写表单、查看进度流程
  - [ ] SubTask 7.6: 验证数据导出CSV功能
  - [ ] SubTask 7.7: 验证响应式设计（移动端和PC端）

# Task Dependencies
- Task 2（数据模型）依赖 Task 1（项目初始化）
- Task 3（认证系统）依赖 Task 2（数据模型）
- Task 4（基础模板）无强依赖，可与 Task 2、Task 3 并行
- Task 5（用户端）依赖 Task 3（认证系统）和 Task 4（基础模板）
- Task 6（管理员端）依赖 Task 3（认证系统）和 Task 4（基础模板）
- Task 7（测试验证）依赖 Task 5 和 Task 6 全部完成

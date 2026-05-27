# 心理健康训练营 - 开发规范

> 基于线上事故复盘形成，适用于本项目全生命周期开发。

---

## 一、依赖管理规范

### 1.1 版本锁定

- `requirements.txt` 中 **所有依赖必须使用精确版本号（`==`）**，禁止使用 `>=` 或 `>=x.y`。
- 新增或升级依赖前，须确认目标版本与现有依赖的兼容性。
- 记录每次依赖变更的原因（安全修复、功能需求等）。

```
# 正确
fastapi==0.104.1
python-jose[cryptography]==3.3.0
sqlalchemy==2.0.40

# 错误
fastapi>=0.104.1
python-jose[cryptography]>=3.3.0
```

### 1.2 依赖升级流程

- 升级前在开发环境执行 `pip install --dry-run <pkg>` 检查冲突。
- 升级后必须运行完整测试套件。
- 记录升级前后的 API 行为差异，重点关注废弃接口和类型变更。

### 1.3 第三方库 API 使用原则

- **不要凭记忆使用框架/库的 API**，查阅官方文档确认常量名、函数签名、参数类型。
- 使用框架提供的类型常量（如 `status.HTTP_303_SEE_OTHER`），不要手动硬编码数字。
- 对于 JWT、密码哈希等安全相关操作，确认库版本的默认行为是否发生变化。

---

## 二、认证与授权规范

### 2.1 JWT 令牌

- JWT `sub` (subject) claim **必须使用字符串类型**，存入时转 `str()`，取出时转 `int()`。
- 提取用户 ID 的逻辑须封装为独立函数，统一处理类型转换异常。
- 令牌创建和验证必须在同一个模块中定义，避免分散实现。

```python
# 存入
create_access_token({"sub": str(user.id)})

# 取出
user_id = int(payload.get("sub", 0))
```

### 2.2 认证依赖

- 认证失败（无 token、token 过期、用户不存在）必须返回 **303 See Other** 重定向到登录页，不要使用 307。
- 权限不足返回 **403 Forbidden**。
- 所有认证异常必须记录警告日志（含请求路径和失败原因）。

### 2.3 密码安全

- 管理员初始密码禁止使用弱密码（如 `admin123`），生产环境必须通过环境变量设置。
- `SECRET_KEY` 和 `JWT_SECRET_KEY` 生产环境禁止使用默认值。

---

## 三、路由与启动规范

### 3.1 路由注册

- 路由模块采用自动扫描机制（`pkgutil.iter_modules`），每个模块必须导出 `router` 对象。
- 每个路由模块的加载须独立 `try/except`，单个模块失败不影响其他模块注册。
- 启动后记录成功注册的路由模块数量。

### 3.2 启动流程

- `startup` 事件中的每个初始化步骤须独立异常处理。
- **关键步骤**（数据库初始化、路由注册）失败时必须传播异常，阻止应用启动。
- **非关键步骤**（管理员账号创建、徽章初始化）失败时记录日志但不阻塞启动。

```python
@app.on_event("startup")
def startup():
    try:
        init_db()
    except Exception as e:
        logger.error("数据库初始化失败: %s", e)
        raise  # 关键步骤，阻止启动
    try:
        _create_admin_if_needed()
    except Exception as e:
        logger.error("管理员账号创建失败: %s", e)  # 非关键，继续
    try:
        register_routes()
    except Exception as e:
        logger.error("路由注册失败: %s", e)
        raise  # 关键步骤，阻止启动
```

### 3.3 路由函数

- 每个路由函数须有顶层 `try/except`，捕获异常后记录日志并返回有意义的错误。
- 表单输入参数必须进行空值检查、类型转换安全处理和范围验证。
- 禁止直接 `int(form_data.get("id"))`，必须先检查是否为 `None` 和是否可转换为 `int`。

```python
# 正确
id_str = form_data.get("id", "")
if not id_str:
    raise HTTPException(status_code=400, detail="ID 不能为空")
try:
    item_id = int(id_str)
except (TypeError, ValueError):
    raise HTTPException(status_code=400, detail="ID 必须为数字")

# 错误
item_id = int(form_data.get("id"))  # None 时抛 TypeError
```

---

## 四、错误处理规范

### 4.1 全局异常处理器

- 必须注册全局 `Exception` 处理器，记录完整堆栈并返回友好的 JSON 错误响应。
- 必须注册 `HTTPException` 处理器，为 404 等常见错误提供模板化页面。
- 生产环境禁止向客户端暴露内部异常详情。

```python
@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.exception("未处理的异常 [%s %s]: %s", request.method, request.url.path, exc)
    return JSONResponse(status_code=500, content={"detail": "服务器内部错误，请稍后重试"})
```

### 4.2 日志规范

- **ERROR** 级别：系统级错误（数据库初始化失败、路由加载失败）。
- **WARNING** 级别：可恢复的异常（JWT 验证失败、用户不存在）。
- **INFO** 级别：关键业务操作（路由注册成功、邮件发送完毕）。
- **DEBUG** 级别：调试信息（请求详情、SQL 查询）。
- 日志格式统一：`%(asctime)s [%(levelname)s] %(name)s: %(message)s`。
- 日志级别根据 `DEBUG` 配置自动切换。

### 4.3 异常传播原则

- 基础设施异常（数据库、路由注册）向上抛出，由全局处理器兜底。
- 业务逻辑异常（权限不足、参数错误）在路由层捕获并转换为 HTTP 错误响应。
- 认证异常统一重定向到登录页，不要暴露具体的失败原因（防止信息泄露）。

---

## 五、数据库规范

### 5.1 会话管理

- 数据库会话使用依赖注入（`Depends(get_db)`），不得在路由函数中手动创建。
- `get_db()` 必须使用 `try/finally` 确保会话关闭。
- 写操作后必须调用 `db.commit()`，查询操作不需要。

### 5.2 数据完整性

- 所有外键字段必须设置 `ForeignKey` 和 `nullable` 约束。
- `created_at` 使用 `server_default=func.now()` 而非 Python 默认值。
- 批量操作使用 `db.flush()` 确保 ID 分配后再进行关联操作。

---

## 六、测试规范

### 6.1 必须覆盖的测试场景

| 场景 | 说明 |
|------|------|
| 未认证访问受保护端点 | 应返回 303 重定向到 /login |
| 无效 token 访问 | 应返回 303 重定向到 /login |
| 过期 token 访问 | 应返回 303 重定向到 /login |
| 普通用户访问管理员端点 | 应返回 403 |
| 管理员正常访问所有端点 | 应返回 200 |
| 表单提交空值参数 | 应返回 400 |
| 表单提交非法类型参数 | 应返回 400 |
| 应用启动后路由注册完整 | 须验证所有预期路由存在 |

### 6.2 测试方法

- 使用 `TestClient(app, raise_server_exceptions=True)` 进行单元测试，确保异常不被吞掉。
- 使用真实 HTTP 客户端（如 `httpx`）进行端到端测试，验证完整链路。
- 测试认证链路时，必须执行"登录获取 token → 使用 token 访问"的完整流程。

### 6.3 启动验证

- 应用启动后自动打印注册的路由数量。
- 建议增加 `/health` 端点，返回 200 表示应用正常。

---

## 七、编码规范

### 7.1 代码组织

- 每个路由模块一个文件，文件内按功能分组（CRUD 操作放在一起）。
- 公共函数（如 `_extract_user_id`）提取到独立位置，避免重复实现。
- 配置项集中在 `config.py`，其他文件仅通过 `from config import XXX` 引用。

### 7.2 命名规范

- 路由函数：`动词_名词` 格式，如 `admin_bootcamps`、`create_bootcamp`。
- 模型类：`PascalCase`，如 `Bootcamp`、`DayForm`。
- 配置常量：`UPPER_SNAKE_CASE`，如 `APP_NAME`、`JWT_SECRET_KEY`。
- 内部辅助函数：以 `_` 开头，如 `_extract_user_id`、`_create_admin_if_needed`。

### 7.3 注释与文档

- 所有 `config.py` 配置项必须附带中文注释说明用途。
- 路由函数不需要注释（函数名即文档），特殊情况除外。
- 异常日志必须包含足够的上下文信息（请求路径、用户 ID、操作名称）。

---

## 八、部署规范

### 8.1 环境变量

- 所有敏感配置（数据库密码、JWT 密钥、SMTP 密码）必须通过环境变量注入。
- `DEBUG` 默认为 `True`（开发环境），生产环境必须设为 `False`。
- 禁止将 `.env` 文件提交到版本控制。

### 8.2 启动检查

- 启动时检查必要环境变量是否已设置。
- 数据库初始化使用 `create_all()`，确保表结构与模型同步。
- 首次启动自动创建管理员账号，后续启动跳过。

### 8.3 错误恢复

- 通知调度器等后台线程的异常不能影响主应用。
- 数据库连接失败时应记录日志并提示运维检查，而非静默忽略。

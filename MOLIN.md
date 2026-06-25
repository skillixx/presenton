# 墨灵二开补丁清单（fork: skillixx/presenton）

> 本 fork 在 upstream presenton 基础上做墨灵平台接入二开。为降低跟 upstream 升级的合并成本，
> 所有墨灵改动集中、可枚举，记录于此。整体方案见墨灵主仓 `docs/presenton-app-integration-plan.md`。
>
> 基线 upstream commit：`4ca60de`（Merge PR #698）。

## F-A：用户自带 token（按请求取 key）—— 已完成

让 presenton 内部 LLM 调用使用「当前墨灵用户的 token_gateway 个人 key」，按本人计费，
替代原本进程级全局的 `os.environ` key（并发会串户）。

| 文件 | 改动 | 性质 |
|---|---|---|
| `servers/fastapi/utils/molin_context.py` | **新增**：请求级身份 ContextVar（user_id + llm_api_key + llm_base_url）及 set/get/reset | 新增，无侵入 |
| `servers/fastapi/api/molin_middleware.py` | **新增**：纯 ASGI 中间件，从注入头构造身份写入 ContextVar | 新增，无侵入 |
| `servers/fastapi/utils/llm_config.py` | **改**：`get_llm_config()` 顶部短路——请求带身份时强制走 token_gateway + 本人 key | 1 处插入 |
| `servers/fastapi/api/main.py` | **改**：注册 `MolinIdentityMiddleware`（最外层） | 2 行 |
| `servers/fastapi/tests/unit/test_molin_context.py` | **新增**：隔离/异步继承/中间件单元测试 | 新增 |

**请求头约定**（墨灵 BFF 注入，浏览器不可见）：
- `X-Molin-User-Id`：墨灵用户 ID（存在即视为墨灵请求）
- `X-Molin-LLM-Key`：该用户在 token_gateway 的个人 key
- `X-Molin-LLM-Base-Url`：token_gateway 入口（可选，缺省用 `CUSTOM_LLM_URL`）

**异步透传**：身份用 ContextVar 承载；FastAPI BackgroundTasks 在 ASGI 调用窗口内执行、
`asyncio.create_task` 子任务创建时自动复制 context，故异步生成链路无需额外透传。
前提是注入用**纯 ASGI 中间件**（非 BaseHTTPMiddleware，后者会断 ContextVar 传播）。

## F-B：多租户存储 + 记忆（加 user_id）—— 已完成

让每个墨灵用户只能访问自己的演示文稿 / 幻灯片 / 对话历史（记忆）/ 图片。
隔离信任边界：**presentation 为数据根**（slide/chat 经 presentation_id 间接受保护），
**image 独立加 user_id**（图片库原为全局共享，会泄漏他人上传的 logo）。

| 文件 | 改动 |
|---|---|
| `models/sql/presentation.py` | **改**：加 `user_id`（可空，index）；`get_new_presentation` 复制归属 |
| `models/sql/image_asset.py` | **改**：加 `user_id`（可空，index） |
| `utils/molin_tenancy.py` | **新增**：`current_owner_id` / `stamp_owner`（创建盖章）/ `require_owner`（非本人→404，不泄漏存在性）；无身份时全 no-op |
| `alembic/versions/b7c1a9d2e3f4_*.py` | **新增**：给 presentations + imageasset 加 user_id 列 + 索引（幂等） |
| `api/v1/ppt/endpoints/presentation.py` | **改**：列表按 owner 过滤；create/generate/derive 盖章；get/delete/prepare/stream/update/edit 校验归属 |
| `api/v1/ppt/endpoints/slide.py` | **改**：两处经父 presentation 校验归属 |
| `api/v1/ppt/endpoints/outlines.py` | **改**：get/update/stream 三处校验归属 |
| `api/v1/ppt/endpoints/chat.py` | **改**：对话历史 4 端点经 presentation 归属隔离（记忆隔离核心） |
| `api/v1/ppt/endpoints/images.py` | **改**：generated/uploaded 列表按 owner 过滤；upload 盖章；delete 校验归属（并修 except 吞 404） |
| `api/v1/ppt/endpoints/theme.py` | **改**：logo 图片校验归属 |
| `services/image_generation_service.py` | **改**：生成图片盖章归属 |
| `tests/unit/test_molin_tenancy.py` | **新增**：盖章/归属/无身份兼容，6 项全过 |

**兼容性**：无墨灵身份（独立部署）时全部 no-op，保持 presenton 原行为；老数据 user_id=None
对墨灵用户视作不可见（404）。

**遗留**：slide/chat_history 表本身未加 user_id（经 presentation 间接隔离已足够）；如需
防御纵深可后续补列。

## F-C：鉴权改信任墨灵 SSO —— 已完成

presenton 原为单管理员 session/basic 登录（`SessionAuthMiddleware`）。墨灵接入后，
请求由墨灵 BFF 完成鉴权并注入身份，presenton **信任之、跳过原登录**；并加共享密钥防伪造。

| 文件 | 改动 |
|---|---|
| `api/middlewares.py` | **改**：`SessionAuthMiddleware.dispatch` 在 `get_molin_identity()` 非空时跳过单管理员校验，放行并回写 `request.state.auth_username = user_id` |
| `api/molin_middleware.py` | **改**：加 `MOLIN_TRUST_SECRET` 校验——配置后注入头须带匹配的 `X-Molin-Auth-Secret` 才被接受，否则视作普通请求（防伪造） |
| `tests/unit/test_molin_auth.py` | **新增**：密钥校验 + 信任放行，3 项全过 |

**安全模型（务必满足其一，建议都做）**：
1. presenton 只在内网、仅墨灵 BFF 可达（网络隔离）；
2. 配置环境变量 `MOLIN_TRUST_SECRET`，BFF 注入 `X-Molin-Auth-Secret` 匹配——
   即使 presenton 意外可达也无法伪造身份绕过鉴权。

未配置 `MOLIN_TRUST_SECRET` 且无墨灵头时，保持 presenton 原单管理员登录行为。

## F-D：用户选择模型（按请求取 model）—— 已完成

presenton 原本模型来自全局 env（CUSTOM 走 `CUSTOM_MODEL`），全实例只能用一个模型。
墨灵接入后，让用户在墨灵侧选模型，经请求头注入，presenton 按请求用该模型（墨灵 logical_model_code）。

| 文件 | 改动 |
|---|---|
| `utils/molin_context.py` | **改**：`MolinIdentity` 加 `llm_model` |
| `api/molin_middleware.py` | **改**：读 `X-Molin-LLM-Model` 头填充 `llm_model` |
| `utils/llm_provider.py` | **改**：`get_model()` 顶部短路——请求带 `llm_model` 时优先用它，否则回退原 env 逻辑 |
| `tests/unit/test_molin_auth.py` | **改**：加 model 头注入测试 |

请求头：`X-Molin-LLM-Model`（墨灵 D2 反代从会话注入；缺省回退 `CUSTOM_MODEL` env，不改原行为）。

## 环境变量（墨灵接入新增）

| 变量 | 说明 |
|---|---|
| `MOLIN_TRUST_SECRET` | BFF↔presenton 共享密钥（F-C 防伪造）。不设则仅靠网络隔离 |
| `CUSTOM_LLM_URL` | token_gateway OpenAI 兼容入口（F-A base_url 缺省值） |
| `CUSTOM_MODEL` | 默认模型（墨灵 logical_model_code）；F-D 注入头缺省时的回退值 |

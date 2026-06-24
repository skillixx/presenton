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

## F-B：多租户存储 + 记忆（加 user_id）—— 待开发

## F-C：鉴权改信任墨灵 SSO —— 待开发

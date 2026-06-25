"""墨灵多租户请求上下文（F-A：用户自带 token）。

presenton 原生把用户的模型 key 写进 ``os.environ``（见 UserConfigEnvUpdateMiddleware），
属进程级全局，并发请求会互相串户——这是接入墨灵做多租户时必须改掉的根因。

墨灵接入后，每个请求的用户身份与模型凭证改用 ``ContextVar`` 承载，实现**请求级隔离**：
- 由墨灵 BFF 反代时注入的请求头填充（见 ``api.molin_middleware.MolinIdentityMiddleware``）；
- ``get_llm_config`` 在请求带身份时短路走 token_gateway，并用该用户的个人 key 计费。

异步透传：本上下文用 ContextVar 承载，FastAPI BackgroundTasks 在 ASGI 调用窗口内执行、
``asyncio.create_task`` 创建子任务时会自动复制当前 context，故异步生成链路无需额外透传。
（前提：注入用纯 ASGI 中间件，而非会断 contextvar 传播的 BaseHTTPMiddleware。）
"""

from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class MolinIdentity:
    """单次请求的墨灵身份与模型凭证。"""

    # 墨灵用户 ID（用于 F-B 多租户数据归属与 F-C 鉴权）。
    user_id: str
    # 用户在 token_gateway 的个人 API key；presenton 内部 LLM 调用据此按本人计费。
    llm_api_key: Optional[str] = None
    # token_gateway 的 OpenAI 兼容入口（可选；缺省回退到 CUSTOM_LLM_URL 环境变量）。
    llm_base_url: Optional[str] = None
    # 用户选择的模型（墨灵 logical_model_code；F-D）。缺省回退到 CUSTOM_MODEL 环境变量。
    llm_model: Optional[str] = None


_molin_identity: ContextVar[Optional[MolinIdentity]] = ContextVar(
    "molin_identity", default=None
)


def set_molin_identity(identity: Optional[MolinIdentity]) -> Token:
    """设置当前请求的墨灵身份，返回 token 供 ``reset_molin_identity`` 还原。"""
    return _molin_identity.set(identity)


def reset_molin_identity(token: Token) -> None:
    """还原 contextvar，避免请求间状态泄漏。"""
    _molin_identity.reset(token)


def get_molin_identity() -> Optional[MolinIdentity]:
    """取当前请求的墨灵身份；非墨灵请求（无注入头）返回 None。"""
    return _molin_identity.get()

"""墨灵身份注入中间件（F-A）。

从墨灵 BFF 反代注入的请求头解析用户身份与模型凭证，写入请求级 ContextVar，
供 ``get_llm_config`` 按本人 key 计费、后续 F-B/F-C 做数据归属与鉴权。

为何用纯 ASGI 中间件而非 ``BaseHTTPMiddleware``：
Starlette 的 ``BaseHTTPMiddleware`` 在独立的执行上下文里运行下游，导致在其中
设置的 ContextVar **无法传播到 endpoint**。纯 ASGI 中间件在同一上下文链中 await
下游，ContextVar 可达 endpoint、FastAPI BackgroundTasks 以及 ``asyncio.create_task``
派生的子任务（创建时自动复制 context），从而保证异步生成链路也用对用户的 key。

请求头约定（均由墨灵 BFF 注入，浏览器侧不可见）：
- ``X-Molin-User-Id``：墨灵用户 ID（存在即视为墨灵请求）。
- ``X-Molin-LLM-Key``：该用户在 token_gateway 的个人 key。
- ``X-Molin-LLM-Base-Url``：token_gateway 入口（可选，缺省用 CUSTOM_LLM_URL）。
- ``X-Molin-Auth-Secret``：BFF↔presenton 共享密钥（F-C 防伪造）。

安全（F-C）：身份头一旦被接受，下游即信任并跳过 presenton 原登录校验，故必须确保
**只有墨灵 BFF 能注入这些头**。两道防线：① presenton 只在内网、仅 BFF 可达；
② 若配置了环境变量 ``MOLIN_TRUST_SECRET``，则注入头必须带匹配的 ``X-Molin-Auth-Secret``
才被接受，否则视作普通请求（身份为 None，回落原鉴权）——可防 presenton 万一可达时的伪造。
"""

import os

from utils.molin_context import (
    MolinIdentity,
    reset_molin_identity,
    set_molin_identity,
)

_HDR_USER = b"x-molin-user-id"
_HDR_KEY = b"x-molin-llm-key"
_HDR_BASE_URL = b"x-molin-llm-base-url"
_HDR_SECRET = b"x-molin-auth-secret"


def _decode(value: bytes | None) -> str | None:
    return value.decode("latin-1") if value else None


def _trust_secret_ok(headers: dict) -> bool:
    """校验 BFF↔presenton 共享密钥。

    未配置 ``MOLIN_TRUST_SECRET`` 时返回 True（信任网络隔离，开发/独立部署友好）；
    配置后则必须请求头匹配，否则拒绝接受墨灵身份。
    """
    expected = os.getenv("MOLIN_TRUST_SECRET")
    if not expected:
        return True
    return _decode(headers.get(_HDR_SECRET)) == expected


class MolinIdentityMiddleware:
    """纯 ASGI 中间件：把墨灵注入头转为请求级 MolinIdentity。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        headers = dict(scope.get("headers") or [])
        user_id = headers.get(_HDR_USER)

        token = None
        if user_id and _trust_secret_ok(headers):
            identity = MolinIdentity(
                user_id=_decode(user_id),
                llm_api_key=_decode(headers.get(_HDR_KEY)),
                llm_base_url=_decode(headers.get(_HDR_BASE_URL)),
            )
            token = set_molin_identity(identity)

        try:
            await self.app(scope, receive, send)
        finally:
            if token is not None:
                reset_molin_identity(token)

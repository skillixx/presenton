"""墨灵 F-A（用户自带 token）单元测试。

覆盖：请求级身份隔离、异步子任务继承、ASGI 中间件头解析与退出后清理。
不依赖 llmai/DB，纯机制测试，可独立运行。
"""

import asyncio

from api.molin_middleware import MolinIdentityMiddleware
from utils.molin_context import (
    MolinIdentity,
    get_molin_identity,
    reset_molin_identity,
    set_molin_identity,
)


def test_set_get_reset_isolation():
    """set/get/reset 基本语义：初始空、设置可读、reset 后清空。"""
    assert get_molin_identity() is None
    token = set_molin_identity(MolinIdentity(user_id="u1", llm_api_key="sk-1"))
    got = get_molin_identity()
    assert got is not None and got.user_id == "u1" and got.llm_api_key == "sk-1"
    reset_molin_identity(token)
    assert get_molin_identity() is None


def test_async_child_task_inherits_identity():
    """asyncio.create_task 子任务继承父上下文身份（异步生成透传的基础）。"""

    async def child():
        return get_molin_identity()

    async def main():
        token = set_molin_identity(
            MolinIdentity(user_id="u123", llm_api_key="sk-user")
        )
        got = await asyncio.create_task(child())
        reset_molin_identity(token)
        return got

    got = asyncio.run(main())
    assert got is not None
    assert got.user_id == "u123"
    assert got.llm_api_key == "sk-user"


def test_middleware_injects_identity_and_cleans_up():
    """中间件从注入头构造身份，下游与子任务可读，退出后 reset 不泄漏。"""
    seen = {}

    async def fake_app(scope, receive, send):
        seen["identity"] = get_molin_identity()

        async def sub():
            return get_molin_identity()

        seen["child"] = await asyncio.create_task(sub())

    mw = MolinIdentityMiddleware(fake_app)

    async def call(headers):
        await mw({"type": "http", "headers": headers}, None, None)

    async def main():
        await call(
            [
                (b"x-molin-user-id", b"u777"),
                (b"x-molin-llm-key", b"sk-abc"),
                (b"x-molin-llm-base-url", b"http://token-gateway/v1"),
            ]
        )
        identity = seen["identity"]
        child = seen["child"]
        assert identity.user_id == "u777"
        assert identity.llm_api_key == "sk-abc"
        assert identity.llm_base_url == "http://token-gateway/v1"
        assert child.user_id == "u777"
        # 中间件退出后上下文已清理
        assert get_molin_identity() is None

    asyncio.run(main())


def test_middleware_non_molin_request_has_no_identity():
    """无墨灵注入头的普通请求：身份为 None（不影响 presenton 原行为）。"""
    seen = {}

    async def fake_app(scope, receive, send):
        seen["identity"] = get_molin_identity()

    mw = MolinIdentityMiddleware(fake_app)

    async def main():
        await mw({"type": "http", "headers": [(b"host", b"x")]}, None, None)
        assert seen["identity"] is None
        assert get_molin_identity() is None

    asyncio.run(main())


def test_middleware_passes_through_non_http_scope():
    """非 http scope（如 lifespan/websocket）直接透传，不触碰上下文。"""
    called = {}

    async def fake_app(scope, receive, send):
        called["ok"] = True

    mw = MolinIdentityMiddleware(fake_app)
    asyncio.run(mw({"type": "lifespan"}, None, None))
    assert called.get("ok") is True

"""墨灵 F-C（信任 SSO + 共享密钥防伪造）单元测试。

覆盖：
- MolinIdentityMiddleware 的 MOLIN_TRUST_SECRET 校验（未配置放行 / 配置后须匹配）；
- SessionAuthMiddleware 在带墨灵身份时跳过单管理员登录、放行并回写 auth_username。
"""

import asyncio
from types import SimpleNamespace

from api.molin_middleware import MolinIdentityMiddleware
from utils.molin_context import (
    MolinIdentity,
    get_molin_identity,
    reset_molin_identity,
    set_molin_identity,
)


def _identity_after_middleware(headers):
    seen = {}

    async def app(scope, receive, send):
        seen["identity"] = get_molin_identity()

    mw = MolinIdentityMiddleware(app)
    asyncio.run(mw({"type": "http", "headers": headers}, None, None))
    return seen["identity"]


def test_secret_not_configured_accepts(monkeypatch):
    monkeypatch.delenv("MOLIN_TRUST_SECRET", raising=False)
    identity = _identity_after_middleware([(b"x-molin-user-id", b"u1")])
    assert identity is not None and identity.user_id == "u1"


def test_secret_configured_requires_match(monkeypatch):
    monkeypatch.setenv("MOLIN_TRUST_SECRET", "s3cret")

    # 匹配 → 接受
    ok = _identity_after_middleware(
        [(b"x-molin-user-id", b"u1"), (b"x-molin-auth-secret", b"s3cret")]
    )
    assert ok is not None and ok.user_id == "u1"

    # 不匹配 → 拒绝（视作普通请求）
    wrong = _identity_after_middleware(
        [(b"x-molin-user-id", b"u1"), (b"x-molin-auth-secret", b"nope")]
    )
    assert wrong is None

    # 缺失密钥头 → 拒绝
    missing = _identity_after_middleware([(b"x-molin-user-id", b"u1")])
    assert missing is None


def test_session_auth_trusts_molin_identity(monkeypatch):
    # 延迟导入：middlewares 依赖较多，放在用例内避免影响其它轻量用例收集。
    from api.middlewares import SessionAuthMiddleware

    monkeypatch.delenv("MOLIN_TRUST_SECRET", raising=False)
    mw = SessionAuthMiddleware(lambda scope, receive, send: None)

    called = {}

    async def call_next(request):
        called["ok"] = True
        return "RESPONSE"

    request = SimpleNamespace(
        state=SimpleNamespace(),
        url=SimpleNamespace(path="/api/v1/ppt/presentation/all"),
        method="GET",
    )

    async def main():
        token = set_molin_identity(MolinIdentity(user_id="u9", llm_api_key="sk"))
        try:
            return await mw.dispatch(request, call_next)
        finally:
            reset_molin_identity(token)

    resp = asyncio.run(main())
    assert resp == "RESPONSE"          # 放行
    assert called.get("ok") is True    # 未走原登录校验，直接 call_next
    assert request.state.auth_username == "u9"  # 回写墨灵用户名

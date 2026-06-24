from fastapi import Request
from starlette.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from utils.get_env import get_can_change_keys_env, is_disable_auth_enabled
from utils.molin_context import get_molin_identity
from utils.simple_auth import (
    get_auth_status,
    get_basic_auth_credentials_from_request,
    get_session_token_from_request,
    verify_credentials,
)
from utils.user_config import update_env_with_user_config


class UserConfigEnvUpdateMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if get_can_change_keys_env() != "false":
            update_env_with_user_config()
        return await call_next(request)


class SessionAuthMiddleware(BaseHTTPMiddleware):
    _EXEMPT_PREFIXES = (
        "/api/v1/auth/",
    )
    _PROTECTED_NON_API_PATHS = {
        "/docs",
        "/openapi.json",
        "/redoc",
    }

    def _is_exempt(self, path: str) -> bool:
        return any(path.startswith(prefix) for prefix in self._EXEMPT_PREFIXES)

    def _requires_auth(self, path: str) -> bool:
        if path.startswith("/api/"):
            return True
        # PPTX export may re-fetch slide images without session/basic headers.
        if path.startswith("/app_data/images/"):
            return False
        if path.startswith("/app_data/"):
            return True
        return path in self._PROTECTED_NON_API_PATHS

    async def dispatch(self, request: Request, call_next):
        if is_disable_auth_enabled():
            return await call_next(request)

        # 墨灵接入（F-C）：请求已由墨灵 BFF 完成鉴权（并经 MOLIN_TRUST_SECRET 校验后）
        # 注入身份，presenton 信任之，跳过原单管理员登录校验。身份由 MolinIdentityMiddleware
        # 写入 ContextVar（其为最外层中间件，故此处必能读到）。
        molin = get_molin_identity()
        if molin is not None:
            request.state.auth_username = molin.user_id
            return await call_next(request)

        path = request.url.path

        if (
            request.method == "OPTIONS"
            or not self._requires_auth(path)
            or self._is_exempt(path)
        ):
            return await call_next(request)

        auth_status = get_auth_status(get_session_token_from_request(request))
        if not auth_status["configured"]:
            return JSONResponse(
                status_code=428,
                content={
                    "detail": "Login setup is required",
                    "setup_required": True,
                },
            )

        if not auth_status["authenticated"]:
            basic_credentials = get_basic_auth_credentials_from_request(request)
            if basic_credentials and verify_credentials(
                basic_credentials[0], basic_credentials[1]
            ):
                request.state.auth_username = basic_credentials[0].strip()
                return await call_next(request)

            return JSONResponse(
                status_code=401,
                content={"detail": "Unauthorized"},
            )

        request.state.auth_username = auth_status.get("username")
        return await call_next(request)

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from starlette.responses import JSONResponse, Response

from app.core.auth import verify_access_token
from app.core.config import get_settings


PUBLIC_PATHS = {
    "/health",
    "/api/auth/status",
    "/api/auth/login",
}


def install_auth_middleware(app: FastAPI) -> None:
    settings = get_settings()
    if not settings.finwise_auth_enabled:
        return

    @app.middleware("http")
    async def require_auth(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        path = request.url.path.rstrip("/") or "/"
        if request.method == "OPTIONS" or path in PUBLIC_PATHS or not path.startswith("/api"):
            return await call_next(request)

        username = _extract_username(request)
        if not username:
            return JSONResponse({"detail": "登录已过期，请重新登录"}, status_code=401)

        request.state.current_user = username
        return await call_next(request)


def _extract_username(request: Request) -> str:
    settings = get_settings()
    auth_header = request.headers.get("authorization", "")
    scheme, _, token = auth_header.partition(" ")
    if scheme.lower() != "bearer" or not token or not settings.finwise_jwt_secret:
        return ""
    return verify_access_token(token, settings.finwise_jwt_secret) or ""

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from app.core.auth import create_access_token, hash_password, read_password_hash, verify_password, write_password_hash
from app.core.config import get_settings


router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    expires_in_hours: int


class AuthStatusResponse(BaseModel):
    enabled: bool


class CurrentUserResponse(BaseModel):
    username: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class ChangePasswordResponse(BaseModel):
    ok: bool


@router.get("/status", response_model=AuthStatusResponse)
def get_auth_status() -> AuthStatusResponse:
    settings = get_settings()
    return AuthStatusResponse(enabled=settings.finwise_auth_enabled)


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest) -> LoginResponse:
    settings = get_settings()
    if not settings.finwise_auth_enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="登录鉴权未启用")
    password_hash = read_password_hash(settings.finwise_admin_password_hash, settings.finwise_password_hash_file)
    if not password_hash or not settings.finwise_jwt_secret:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="登录鉴权未正确配置")
    if payload.username != settings.finwise_admin_username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    if not verify_password(payload.password, password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")

    token = create_access_token(
        payload.username,
        settings.finwise_jwt_secret,
        settings.finwise_token_expire_hours,
    )
    return LoginResponse(
        access_token=token,
        username=payload.username,
        expires_in_hours=settings.finwise_token_expire_hours,
    )


@router.get("/me", response_model=CurrentUserResponse)
def get_current_user(request: Request) -> CurrentUserResponse:
    username = getattr(request.state, "current_user", "")
    if not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已过期，请重新登录")
    return CurrentUserResponse(username=username)


@router.post("/change-password", response_model=ChangePasswordResponse)
def change_password(payload: ChangePasswordRequest, request: Request) -> ChangePasswordResponse:
    settings = get_settings()
    username = getattr(request.state, "current_user", "")
    if not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已过期，请重新登录")
    if username != settings.finwise_admin_username:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="当前用户无权修改密码")
    if len(payload.new_password) < 8:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="新密码至少需要 8 位")

    password_hash = read_password_hash(settings.finwise_admin_password_hash, settings.finwise_password_hash_file)
    if not password_hash or not settings.finwise_jwt_secret:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="登录鉴权未正确配置")
    if not verify_password(payload.old_password, password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="当前密码错误")
    if verify_password(payload.new_password, password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="新密码不能与当前密码相同")

    try:
        write_password_hash(hash_password(payload.new_password), settings.finwise_password_hash_file)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="未配置密码持久化，无法在线修改密码") from exc
    return ChangePasswordResponse(ok=True)

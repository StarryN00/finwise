"""
Auth Router - handles login, logout, and current user info using JSONStore.
"""
import uuid
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt

from backend.core.config import settings
from backend.storage.manager import user_store
from backend.schemas.user import (
    LoginRequest, LoginResponse, UserResponse, UserStatus, UserRole, UserCreate
)

router = APIRouter(prefix="/api/auth", tags=["auth"])
security = HTTPBearer()


def _verify_password(plain: str, hashed: str) -> bool:
    """Simple password verification. In production use bcrypt."""
    return plain == hashed  # TODO: use bcrypt


def _hash_password(plain: str) -> str:
    """Hash password. In production use bcrypt."""
    return plain  # TODO: use bcrypt


def _create_token(user_id: str) -> str:
    """Create JWT access token."""
    expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "exp": expire,
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def _decode_token(token: str) -> Optional[str]:
    """Decode and validate JWT token."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload["sub"]
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


def _get_user(user_id: str) -> Optional[dict]:
    """Get user by ID from store."""
    return user_store.get_by_id(user_id)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """Get current authenticated user from JWT token."""
    user_id = _decode_token(credentials.credentials)
    user = _get_user(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if user.get("status") != UserStatus.ACTIVE.value:
        raise HTTPException(status_code=403, detail="User is inactive")
    return user


@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest):
    """Authenticate user and return JWT token."""
    user = user_store.first(username=req.username)

    if not user or not _verify_password(req.password, user.get("password_hash", "")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    if user.get("status") != UserStatus.ACTIVE.value:
        raise HTTPException(status_code=403, detail="User is inactive")

    token = _create_token(user["id"])

    return LoginResponse(
        access_token=token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=UserResponse(
            id=user["id"],
            username=user["username"],
            real_name=user.get("real_name"),
            role=UserRole(user["role"]),
            status=UserStatus(user["status"]),
            created_at=user["created_at"],
        ),
    )


@router.post("/logout")
async def logout(current_user: dict = Depends(get_current_user)):
    """Logout current user. Client should discard token."""
    return {"message": "Logged out successfully"}


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: dict = Depends(get_current_user)):
    """Get current user info."""
    return UserResponse(
        id=current_user["id"],
        username=current_user["username"],
        real_name=current_user.get("real_name"),
        role=UserRole(current_user["role"]),
        status=UserStatus(current_user["status"]),
        created_at=current_user["created_at"],
    )


@router.post("/register", response_model=UserResponse)
async def register(req: UserCreate):
    """Register a new user (for demo/seed purposes)."""
    # Check if username exists
    existing = user_store.first(username=req.username)
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")

    user = user_store.create(
        id=str(uuid.uuid4()),
        username=req.username,
        password_hash=_hash_password(req.password),
        real_name=req.real_name or req.username,
        role=UserRole.OPERATOR.value,
        status=UserStatus.ACTIVE.value,
    )

    return UserResponse(
        id=user["id"],
        username=user["username"],
        real_name=user.get("real_name"),
        role=UserRole(user["role"]),
        status=UserStatus(user["status"]),
        created_at=user["created_at"],
    )
"""
User schemas
"""
from datetime import datetime
from typing import Optional
from enum import Enum
from pydantic import BaseModel, Field


class UserRole(str, Enum):
    OPERATOR = "OPERATOR"
    ADMIN = "ADMIN"


class UserStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class UserBase(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    real_name: Optional[str] = Field(None, max_length=100)
    role: UserRole = UserRole.OPERATOR


class UserCreate(UserBase):
    password: str = Field(..., min_length=6)


class UserUpdate(BaseModel):
    real_name: Optional[str] = Field(None, max_length=100)
    role: Optional[UserRole] = None
    status: Optional[UserStatus] = None


class UserResponse(UserBase):
    id: str
    status: UserStatus = UserStatus.ACTIVE
    created_at: datetime

    class Config:
        from_attributes = True


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse

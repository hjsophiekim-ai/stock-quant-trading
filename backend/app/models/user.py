from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field

UserRole = Literal["admin", "user"]


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=64)
    role: UserRole = "user"


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserEntity(BaseModel):
    id: str
    email: EmailStr
    display_name: str
    role: UserRole
    password_hash: str
    settings: dict[str, str] = Field(default_factory=dict)
    broker_accounts: list[str] = Field(default_factory=list)
    created_at: datetime


class UserPublic(BaseModel):
    id: str
    email: EmailStr
    display_name: str
    role: UserRole
    settings: dict[str, str] = Field(default_factory=dict)
    broker_accounts: list[str] = Field(default_factory=list)
    created_at: datetime


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    access_expires_in_sec: int
    refresh_expires_in_sec: int


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str

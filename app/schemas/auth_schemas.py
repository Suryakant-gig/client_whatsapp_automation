"""Pydantic schemas for Authentication and User management."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    """Schema for user login credentials."""

    username: str = Field(..., min_length=1, max_length=50, description="Unique account username")
    password: str = Field(..., min_length=1, max_length=128, description="User password")


class SetupRequest(BaseModel):
    """Schema for one-time initial administrator bootstrap."""

    username: str = Field(..., min_length=3, max_length=50, description="Administrator username")
    password: str = Field(..., min_length=8, max_length=128, description="Strong administrator password")
    setup_secret: str = Field(..., min_length=8, description="One-time system setup authorization secret")


class UserResponse(BaseModel):
    """Schema for public user identity representation (no sensitive fields)."""

    id: int
    username: str
    role: str
    is_active: bool
    created_at: datetime
    csrf_token: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class AuthStatusResponse(BaseModel):
    """Schema for public system initialization and authentication state."""

    initialized: bool
    authenticated: bool
    user: Optional[UserResponse] = None


class LogoutResponse(BaseModel):
    """Schema for logout confirmation."""

    message: str = "Logged out successfully"


class ChangePasswordRequest(BaseModel):
    """Schema for changing authenticated user password."""

    current_password: str = Field(..., min_length=1, description="Current password")
    new_password: str = Field(..., min_length=8, max_length=128, description="New strong password")

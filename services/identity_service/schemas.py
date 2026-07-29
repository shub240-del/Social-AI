"""Request and response models.

Validation lives here so a malformed body is rejected with a 422 before any
handler runs. Password rules are enforced in one place — ``PasswordMixin`` —
so registration, reset and change cannot drift apart.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_BYTES = 72


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


def _validate_password(value: str) -> str:
    if len(value) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if len(value.encode("utf-8")) > MAX_PASSWORD_BYTES:
        # bcrypt silently ignores anything past 72 bytes.
        raise ValueError(f"Password must be at most {MAX_PASSWORD_BYTES} bytes.")
    if value.strip() != value:
        raise ValueError("Password must not start or end with whitespace.")
    return value


# ---- auth -------------------------------------------------------------


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: Annotated[str, Field(min_length=1, max_length=200)] = "New User"

    _check = field_validator("password")(_validate_password)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: Annotated[str, Field(min_length=10, max_length=512)]


class LogoutRequest(BaseModel):
    refresh_token: str | None = None
    all_sessions: bool = False


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class WorkspaceSummary(ORMModel):
    id: str
    name: str
    slug: str
    role: str = "member"


class UserResponse(ORMModel):
    id: str
    email: str
    full_name: str
    is_active: bool
    is_superuser: bool
    email_verified_at: datetime | None = None
    created_at: datetime | None = None


class MeResponse(UserResponse):
    workspaces: list[WorkspaceSummary] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)


class RegisterResponse(TokenResponse):
    user: UserResponse


class MessageResponse(BaseModel):
    message: str


# ---- account ----------------------------------------------------------


class VerifyRequestRequest(BaseModel):
    email: EmailStr


class VerifyConfirmRequest(BaseModel):
    token: Annotated[str, Field(min_length=10, max_length=512)]


class PasswordForgotRequest(BaseModel):
    email: EmailStr


class PasswordResetRequest(BaseModel):
    token: Annotated[str, Field(min_length=10, max_length=512)]
    new_password: str

    _check = field_validator("new_password")(_validate_password)


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str

    _check = field_validator("new_password")(_validate_password)


# ---- workspaces & members ---------------------------------------------


class WorkspaceCreate(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=160)]
    description: Annotated[str, Field(max_length=2000)] = ""


class WorkspaceUpdate(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=160)] | None = None
    description: Annotated[str, Field(max_length=2000)] | None = None


class WorkspaceResponse(ORMModel):
    id: str
    name: str
    slug: str
    description: str
    owner_id: str
    created_at: datetime | None = None
    role: str | None = None


class MemberResponse(BaseModel):
    user_id: str
    email: str
    full_name: str
    role: str
    joined_at: datetime | None = None


class MemberInvite(BaseModel):
    email: EmailStr
    role: Literal["owner", "admin", "editor", "member", "viewer"] = "member"


class MemberRoleUpdate(BaseModel):
    role: Literal["owner", "admin", "editor", "member", "viewer"]


# ---- brands & campaigns -----------------------------------------------


class BrandCreate(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=160)]
    description: Annotated[str, Field(max_length=4000)] = ""
    tone: Annotated[str, Field(max_length=80)] = "professional"
    audience: Annotated[str, Field(max_length=300)] = ""
    keywords: Annotated[str, Field(max_length=2000)] = ""


class BrandUpdate(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=160)] | None = None
    description: Annotated[str, Field(max_length=4000)] | None = None
    tone: Annotated[str, Field(max_length=80)] | None = None
    audience: Annotated[str, Field(max_length=300)] | None = None
    keywords: Annotated[str, Field(max_length=2000)] | None = None


class BrandResponse(ORMModel):
    id: str
    workspace_id: str
    name: str
    description: str
    tone: str
    audience: str
    keywords: str
    created_at: datetime | None = None


class CampaignCreate(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=160)]
    objective: Annotated[str, Field(max_length=4000)] = ""
    channel: Annotated[str, Field(max_length=60)] = "twitter"
    brand_id: str | None = None


class CampaignUpdate(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=160)] | None = None
    objective: Annotated[str, Field(max_length=4000)] | None = None
    channel: Annotated[str, Field(max_length=60)] | None = None
    status: Literal["draft", "active", "paused", "archived"] | None = None
    brand_id: str | None = None


class CampaignResponse(ORMModel):
    id: str
    workspace_id: str
    brand_id: str | None
    name: str
    objective: str
    status: str
    channel: str
    created_at: datetime | None = None


# ---- chat --------------------------------------------------------------


class ChatRequest(BaseModel):
    prompt: Annotated[str, Field(min_length=1, max_length=8000)]
    conversation_id: str | None = None
    campaign_id: str | None = None
    brand_id: str | None = None
    temperature: Annotated[float, Field(ge=0.0, le=2.0)] = 0.7


class MessageResponseModel(ORMModel):
    id: str
    role: str
    content: str
    sequence: int
    model: str | None = None
    created_at: datetime | None = None


class ChatResponse(BaseModel):
    conversation_id: str
    message: MessageResponseModel
    model: str
    provider: str
    latency_ms: int
    total_tokens: int


class ConversationSummary(ORMModel):
    id: str
    title: str
    campaign_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    message_count: int = 0


class ConversationDetail(ConversationSummary):
    messages: list[MessageResponseModel] = Field(default_factory=list)


__all__ = [name for name in dir() if name[0].isupper()]

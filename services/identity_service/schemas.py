"""Request/response models. These define the public API contract."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from packages.shared_core.security.roles import Role


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- auth ------------------------------------------------------------


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=72)
    full_name: str = Field(default="", max_length=200)
    # Optional: created and owned by the new user during registration.
    workspace_name: str | None = Field(default=None, max_length=200)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=72)


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class UserOut(ORMModel):
    id: str
    email: EmailStr
    full_name: str
    is_active: bool
    created_at: datetime


class MeResponse(BaseModel):
    user: UserOut
    workspaces: list[WorkspaceOut]


# ---- workspaces ------------------------------------------------------


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class WorkspaceUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class WorkspaceOut(ORMModel):
    id: str
    name: str
    slug: str
    owner_id: str
    created_at: datetime
    role: str | None = None


class MemberOut(BaseModel):
    user_id: str
    email: EmailStr
    full_name: str
    role: str
    joined_at: datetime


class MemberInvite(BaseModel):
    email: EmailStr
    role: Role = Role.MEMBER


class MemberRoleUpdate(BaseModel):
    role: Role


# ---- brands ----------------------------------------------------------


class BrandCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    tone_of_voice: str = Field(default="", max_length=4000)
    target_audience: str = Field(default="", max_length=4000)


class BrandUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    tone_of_voice: str | None = Field(default=None, max_length=4000)
    target_audience: str | None = Field(default=None, max_length=4000)


class BrandOut(ORMModel):
    id: str
    workspace_id: str
    name: str
    description: str
    tone_of_voice: str
    target_audience: str
    created_at: datetime


# ---- campaigns (projects) -------------------------------------------


class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    objective: str = Field(default="", max_length=4000)
    brand_id: str | None = None
    status: str = Field(default="draft", pattern="^(draft|active|paused|completed)$")


class CampaignUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    objective: str | None = Field(default=None, max_length=4000)
    brand_id: str | None = None
    status: str | None = Field(default=None, pattern="^(draft|active|paused|completed)$")


class CampaignOut(ORMModel):
    id: str
    workspace_id: str
    brand_id: str | None
    name: str
    objective: str
    status: str
    created_at: datetime


# ---- chat ------------------------------------------------------------


class ChatRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=8000)
    conversation_id: str | None = None
    brand_id: str | None = None
    campaign_id: str | None = None


class MessageOut(ORMModel):
    id: str
    role: str
    content: str
    model: str | None
    created_at: datetime


class ChatResponse(BaseModel):
    conversation_id: str
    message: MessageOut
    provider: str


class ConversationOut(ORMModel):
    id: str
    workspace_id: str
    title: str
    campaign_id: str | None
    brand_id: str | None
    created_at: datetime
    updated_at: datetime


class ConversationDetail(ConversationOut):
    messages: list[MessageOut] = []


# ---- pagination ------------------------------------------------------


class Page(BaseModel):
    total: int
    limit: int
    offset: int


class PagedBrands(BaseModel):
    items: list[BrandOut]
    page: Page


class PagedCampaigns(BaseModel):
    items: list[CampaignOut]
    page: Page


class PagedConversations(BaseModel):
    items: list[ConversationOut]
    page: Page


MeResponse.model_rebuild()


class MessageResponse(BaseModel):
    message: str


class VerifyRequestRequest(BaseModel):
    email: EmailStr


class VerifyConfirmRequest(BaseModel):
    token: str = Field(min_length=16, max_length=256)


class PasswordForgotRequest(BaseModel):
    email: EmailStr


class PasswordResetRequest(BaseModel):
    token: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=12, max_length=72)


class PasswordChangeRequest(BaseModel):
    """Authenticated change: proves intent with the current password."""

    current_password: str = Field(min_length=1, max_length=72)
    new_password: str = Field(min_length=12, max_length=72)

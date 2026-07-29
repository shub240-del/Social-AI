"""Single source of truth for the persisted domain model."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from packages.shared_core.db.base import Base, TimestampMixin, UUIDMixin


class User(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # Null for federated (Auth0) users who never set a local password.
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    auth0_sub: Mapped[str | None] = mapped_column(
        String(255), unique=True, index=True, nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    memberships: Mapped[list[Membership]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )


class Workspace(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "workspaces"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), unique=True, index=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    memberships: Mapped[list[Membership]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan", lazy="selectin"
    )
    brands: Mapped[list[Brand]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )


class Membership(UUIDMixin, TimestampMixin, Base):
    """Join table between users and workspaces. The tenancy boundary."""

    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "workspace_id", name="uq_membership_user_workspace"),
        Index("ix_membership_workspace_user", "workspace_id", "user_id"),
    )

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Stored as the Role enum's string value; see security/roles.py.
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="member")

    user: Mapped[User] = relationship(back_populates="memberships", lazy="joined")
    workspace: Mapped[Workspace] = relationship(back_populates="memberships", lazy="joined")


class Brand(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "brands"
    __table_args__ = (Index("ix_brand_workspace_name", "workspace_id", "name"),)

    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # Injected into the LLM system prompt so stored brand voice actually
    # conditions generated content.
    tone_of_voice: Mapped[str] = mapped_column(Text, default="", nullable=False)
    target_audience: Mapped[str] = mapped_column(Text, default="", nullable=False)

    workspace: Mapped[Workspace] = relationship(back_populates="brands")
    campaigns: Mapped[list[Campaign]] = relationship(
        back_populates="brand", cascade="all, delete-orphan"
    )


class Campaign(UUIDMixin, TimestampMixin, Base):
    """A project: a unit of content work belonging to a brand."""

    __tablename__ = "campaigns"
    __table_args__ = (Index("ix_campaign_workspace_status", "workspace_id", "status"),)

    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    brand_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("brands.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    objective: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)

    brand: Mapped[Brand | None] = relationship(back_populates="campaigns")


class Conversation(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversation_workspace_created", "workspace_id", "created_at"),)

    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    campaign_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True
    )
    brand_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("brands.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(300), default="New conversation", nullable=False)

    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )


class Message(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_message_conversation_created", "conversation_id", "created_at"),)

    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # user | assistant | system
    content: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class RefreshToken(UUIDMixin, TimestampMixin, Base):
    """Opaque refresh tokens, stored hashed and individually revocable.

    Tokens issued by rotating an existing token inherit its ``family_id``.
    Presenting a token that has already been consumed means two parties hold
    the same secret, so the whole family is revoked (OAuth 2.0 Security BCP,
    "refresh token replay detection"). Without the family link, a stolen token
    could be rotated once and the thief's descendant would live forever.
    """

    __tablename__ = "refresh_tokens"

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    family_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UsageRecord(UUIDMixin, TimestampMixin, Base):
    """Per-workspace AI metering. The floor under runaway LLM spend."""

    __tablename__ = "usage_records"
    __table_args__ = (Index("ix_usage_workspace_created", "workspace_id", "created_at"),)

    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), default="chat_completion", nullable=False)
    model: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class VerificationToken(UUIDMixin, TimestampMixin, Base):
    """Single-use, hashed tokens for email verification and password reset.

    Stored hashed for the same reason as refresh tokens: a database leak must
    not hand the attacker a working password-reset link.
    """

    __tablename__ = "verification_tokens"
    __table_args__ = (Index("ix_verification_user_purpose", "user_id", "purpose"),)

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

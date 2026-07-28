"""ORM models.

Tenancy rule: everything a user can reach hangs off a Workspace, and every
query is filtered by a membership in that workspace. There is no global
"list all brands" path, because the moment one exists a missing filter becomes
a cross-tenant leak.
"""

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

from packages.shared_core.db.base import Base, Timestamps, UUIDPrimaryKey


class User(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # Nullable: an Auth0/SSO user never has a local password.
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    external_id: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)

    memberships: Mapped[list[Membership]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )
    refresh_tokens: Mapped[list[RefreshToken]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    @property
    def is_verified(self) -> bool:
        return self.email_verified_at is not None


class RefreshToken(UUIDPrimaryKey, Timestamps, Base):
    """One row per issued refresh token. Only the SHA-256 hash is stored.

    ``family_id`` links every token descended from one login. Rotation issues a
    new token in the same family; presenting an already-rotated token means the
    value leaked, so the whole family is revoked rather than just that row.
    """

    __tablename__ = "refresh_tokens"

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    family_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rotated_to: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(400))
    ip_address: Mapped[str | None] = mapped_column(String(64))

    user: Mapped[User] = relationship(back_populates="refresh_tokens")

    __table_args__ = (Index("ix_refresh_tokens_user_family", "user_id", "family_id"),)


class VerificationToken(UUIDPrimaryKey, Timestamps, Base):
    """Single-use, expiring, purpose-scoped token for email flows."""

    __tablename__ = "verification_tokens"

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    # 'email_verify' | 'password_reset' — a token minted for one purpose must
    # never be accepted for the other.
    purpose: Mapped[str] = mapped_column(String(40), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_verification_user_purpose", "user_id", "purpose"),)


class Workspace(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "workspaces"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(160), index=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    owner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), index=True, nullable=False
    )

    memberships: Mapped[list[Membership]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )
    brands: Mapped[list[Brand]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )

    __table_args__ = (UniqueConstraint("owner_id", "slug", name="uq_workspace_owner_slug"),)


class Membership(UUIDPrimaryKey, Timestamps, Base):
    """Join row carrying the user's role inside one workspace."""

    __tablename__ = "memberships"

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False
    )
    role: Mapped[str] = mapped_column(String(40), nullable=False, default="member")

    user: Mapped[User] = relationship(back_populates="memberships")
    workspace: Mapped[Workspace] = relationship(back_populates="memberships", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("user_id", "workspace_id", name="uq_membership_user_workspace"),
    )


class Brand(UUIDPrimaryKey, Timestamps, Base):
    """Voice and audience settings the AI conditions on."""

    __tablename__ = "brands"

    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    tone: Mapped[str] = mapped_column(String(80), default="professional", nullable=False)
    audience: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    keywords: Mapped[str] = mapped_column(Text, default="", nullable=False)

    workspace: Mapped[Workspace] = relationship(back_populates="brands")
    campaigns: Mapped[list[Campaign]] = relationship(
        back_populates="brand", cascade="all, delete-orphan"
    )


class Campaign(UUIDPrimaryKey, Timestamps, Base):
    """The "project" a user works inside."""

    __tablename__ = "campaigns"

    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False
    )
    brand_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("brands.id", ondelete="SET NULL"), index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    objective: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="draft", nullable=False)
    channel: Mapped[str] = mapped_column(String(60), default="twitter", nullable=False)

    brand: Mapped[Brand | None] = relationship(back_populates="campaigns")


class Conversation(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "conversations"

    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    campaign_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str] = mapped_column(String(200), default="New conversation", nullable=False)

    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.sequence",
    )

    __table_args__ = (
        Index("ix_conversations_workspace_user", "workspace_id", "user_id"),
    )


class Message(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "messages"

    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # user | assistant | system
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Monotonic per conversation: ordering by created_at alone ties when a
    # prompt and its reply are written in the same transaction.
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    model: Mapped[str | None] = mapped_column(String(120))
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")

    __table_args__ = (
        Index("ix_messages_conversation_sequence", "conversation_id", "sequence"),
    )


__all__ = [
    "Brand",
    "Campaign",
    "Conversation",
    "Membership",
    "Message",
    "RefreshToken",
    "User",
    "VerificationToken",
    "Workspace",
]

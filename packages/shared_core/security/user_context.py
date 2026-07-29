"""Request-scoped identity of the caller."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class UserContext:
    user_id: str
    email: str
    is_superuser: bool = False
    # workspace_id -> role, populated from the caller's memberships.
    memberships: dict[str, str] = field(default_factory=dict)

    def role_in(self, workspace_id: str) -> str | None:
        return self.memberships.get(workspace_id)

    def is_member_of(self, workspace_id: str) -> bool:
        return workspace_id in self.memberships

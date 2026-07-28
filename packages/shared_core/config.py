"""Application settings with production fail-fast guards.

Configuration that is merely inconvenient in development is fatal in
production: a SQLite file that vanishes on redeploy, a wildcard CORS policy,
an email backend that prints to stdout, a mock LLM. Each of those looks like a
working system right up until it costs real data or real users.

``_validate_production`` therefore collects *every* problem and raises once, so
a deploy reveals the whole list instead of failing one variable at a time.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Values that appear in .env.example. A copied example file is the single most
# likely way a placeholder reaches production.
PLACEHOLDERS = frozenset(
    {
        "changeme",
        "change_me",
        "your_key_here",
        "mock_nvidia_api_key",
        "REQUIRED_FROM_VAULT",
        "",
    }
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- core ----------------------------------------------------------
    environment: Literal["development", "test", "staging", "production"] = "development"
    log_level: str = "INFO"
    release_version: str = "1.0.0"
    api_v1_prefix: str = "/api/v1"

    # ---- database ------------------------------------------------------
    database_url: str = "sqlite+aiosqlite:///./socialai_dev.db"
    # DDL must bypass a transaction pooler; Supabase :6543 cannot run it.
    migration_database_url: str | None = None
    postgres_pool_size: int = 5
    postgres_max_overflow: int = 5
    db_echo: bool = False

    # ---- auth ----------------------------------------------------------
    jwt_private_key: str | None = None
    jwt_public_key: str | None = None
    jwt_issuer: str = "https://api.socialai.io"
    jwt_audience: str = "https://api.socialai.io"
    access_token_ttl_seconds: int = 900          # 15 minutes
    refresh_token_ttl_seconds: int = 60 * 60 * 24 * 30
    require_email_verification: bool = False
    email_verify_ttl_seconds: int = 60 * 60 * 24
    password_reset_ttl_seconds: int = 60 * 60

    # Legacy Auth0 support. Kept because the original deployment used it; a
    # half-configured tenant is worse than none, so both must be present.
    auth0_domain: str | None = None
    auth0_issuer: str | None = None
    auth0_audience: str | None = None

    # ---- transport -----------------------------------------------------
    allowed_origins: str = "http://127.0.0.1:3000,http://localhost:3000"
    frontend_base_url: str = "http://127.0.0.1:3000"

    # ---- ai ------------------------------------------------------------
    nvidia_api_key: str | None = None
    nvidia_api_base_url: str = "https://integrate.api.nvidia.com/v1"
    default_llm_model: str = "meta/llama-3.1-70b-instruct"
    llm_timeout_seconds: float = 60.0
    llm_max_retries: int = 3
    llm_max_output_tokens: int = 1024
    allow_mock_llm: bool = True

    # ---- email ---------------------------------------------------------
    email_backend: Literal["console", "smtp", "memory"] = "console"
    email_from: str = "Social AI <no-reply@socialai.io>"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = True

    # ---- limits & observability ----------------------------------------
    rate_limit_enabled: bool = True
    rate_limit_per_minute: int = 120
    auth_rate_limit_per_minute: int = 10
    sentry_dsn: str | None = None
    sentry_traces_sample_rate: float = 0.1

    # ---- derived --------------------------------------------------------
    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def is_test(self) -> bool:
        return self.environment == "test"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def llm_enabled(self) -> bool:
        """True when a real provider call can be made."""
        return bool(self.nvidia_api_key) and self.nvidia_api_key not in PLACEHOLDERS

    @property
    def docs_url(self) -> str | None:
        return None if self.is_production else "/docs"

    @property
    def openapi_url(self) -> str | None:
        # A public schema in production hands an attacker the full attack
        # surface, including every field name and validation rule.
        return None if self.is_production else f"{self.api_v1_prefix}/openapi.json"

    @property
    def sync_database_url(self) -> str:
        """Alembic drives DDL synchronously."""
        url = self.migration_database_url or self.database_url
        return url.replace("+asyncpg", "+psycopg2").replace("+aiosqlite", "")

    @field_validator("allowed_origins")
    @classmethod
    def _strip_origins(cls, v: str) -> str:
        return v.strip()

    def model_post_init(self, __context: object) -> None:
        if self.is_production:
            self._validate_production()

    # ---- the guard ------------------------------------------------------
    def _validate_production(self) -> None:
        problems: list[str] = []

        if self.database_url.startswith("sqlite"):
            problems.append(
                "DATABASE_URL points at SQLite. Production data must live in "
                "Postgres; a container-local file is lost on every redeploy."
            )

        if not self.jwt_private_key:
            problems.append(
                "JWT_PRIVATE_KEY is not set. The development fallback writes a "
                "keypair to the temp directory, so anyone who can read it could "
                "mint valid tokens."
            )
        if not self.jwt_public_key:
            problems.append("JWT_PUBLIC_KEY is not set; tokens could not be verified.")

        if self.allow_mock_llm:
            problems.append(
                "ALLOW_MOCK_LLM is enabled. Production would serve canned text "
                "that looks like a working AI product."
            )

        if not self.nvidia_api_key:
            problems.append("NVIDIA_API_KEY is not set, so no completion can be generated.")
        elif self.nvidia_api_key in PLACEHOLDERS:
            problems.append(
                f"NVIDIA_API_KEY is the placeholder {self.nvidia_api_key!r}; "
                "a .env.example was probably copied verbatim."
            )

        origins = self.cors_origins
        if not origins:
            problems.append("ALLOWED_ORIGINS is empty; the frontend could not call the API.")
        if "*" in origins:
            problems.append(
                "ALLOWED_ORIGINS contains '*'. With credentialed requests this "
                "lets any site act on behalf of a logged-in user."
            )
        for origin in origins:
            if origin.startswith("http://"):
                problems.append(f"ALLOWED_ORIGINS contains a plaintext origin: {origin}")

        if self.email_backend == "console":
            problems.append(
                "EMAIL_BACKEND is 'console'. Verification and reset mail would be "
                "printed to the log and never delivered."
            )
        if self.email_backend == "smtp" and not self.smtp_host:
            problems.append("EMAIL_BACKEND is 'smtp' but SMTP_HOST is not set.")

        if not self.frontend_base_url.startswith("https://"):
            problems.append(
                "FRONTEND_BASE_URL must be https; verification links are sent by "
                f"email and must not travel over plaintext (got {self.frontend_base_url!r})."
            )

        # Partial Auth0 config silently disables validation of the very tokens
        # it is meant to check.
        if self.auth0_domain and not self.auth0_issuer:
            problems.append("AUTH0_DOMAIN is set but AUTH0_ISSUER is missing.")
        if self.auth0_issuer and not self.auth0_domain:
            problems.append("AUTH0_ISSUER is set but AUTH0_DOMAIN is missing.")

        if problems:
            raise ValueError(
                "Refusing to start in production; fix all of the following:\n"
                + "\n".join(f"  - {p}" for p in problems)
            )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached so a request never pays for environment parsing.

    Tests call ``get_settings.cache_clear()`` after monkeypatching the
    environment.
    """
    return Settings()


__all__ = ["Settings", "get_settings", "PLACEHOLDERS", "Field"]

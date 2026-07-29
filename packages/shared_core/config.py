"""Central application settings.

Fail-fast by design: production boots are rejected when a required secret is
missing or still holds a placeholder value. The original repository shipped
``REQUIRED_FROM_VAULT`` placeholders with no mechanism to replace them, which
meant the app could start with literal placeholder strings as credentials.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

PLACEHOLDERS = {
    "",
    "REQUIRED_FROM_VAULT",
    "changeme",
    "your_key_here",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- environment -------------------------------------------------
    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    service_name: str = "socialai-api"

    # ---- server ------------------------------------------------------
    host: str = "0.0.0.0"
    port: int = 8000
    # Comma-separated in the environment, parsed to a list below.
    allowed_origins: str = "http://localhost:3000"

    # ---- database ----------------------------------------------------
    # SQLite keeps local development and CI dependency-free. Supabase/Postgres
    # is selected purely by changing this URL; no code path differs.
    database_url: str = "sqlite+aiosqlite:///./socialai.db"
    migration_database_url: str | None = None
    postgres_pool_size: int = 5
    postgres_max_overflow: int = 5
    db_echo: bool = False

    # ---- auth --------------------------------------------------------
    # Local RS256 issuance. Keys are generated on first boot in development;
    # in production they must be supplied via the environment.
    jwt_algorithm: str = "RS256"
    jwt_private_key: str | None = None
    jwt_public_key: str | None = None
    jwt_issuer: str = "https://api.socialai.io"
    jwt_audience: str = "https://api.socialai.io"
    access_token_ttl_seconds: int = 900          # 15 minutes
    refresh_token_ttl_seconds: int = 60 * 60 * 24 * 14   # 14 days

    # Optional Auth0 federation. When auth0_domain is set, tokens issued by
    # Auth0 are accepted alongside locally issued ones.
    auth0_domain: str | None = None
    auth0_audience: str | None = None
    auth0_issuer: str | None = None

    # ---- AI ----------------------------------------------------------
    nvidia_api_key: str | None = None
    nvidia_api_base_url: str = "https://integrate.api.nvidia.com/v1"
    default_llm_model: str = "meta/llama-3.1-70b-instruct"
    llm_timeout_seconds: float = 60.0
    llm_max_retries: int = 2
    llm_max_output_tokens: int = 1024
    # When no API key is configured the deterministic echo provider is used so
    # the full product flow remains exercisable without credentials.
    allow_mock_llm: bool = True

    # ---- observability ------------------------------------------------
    sentry_dsn: str | None = None
    sentry_traces_sample_rate: float = 0.1
    release_version: str = "unknown"

    # ---- email / account verification --------------------------------
    email_backend: Literal["console", "smtp"] = "console"
    email_from: str = "Social AI <no-reply@socialai.io>"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = True
    # Public URL of the web app, used to build the links inside emails.
    frontend_base_url: str = "http://localhost:3000"
    require_email_verification: bool = False
    email_verify_ttl_seconds: int = 60 * 60 * 24      # 24 hours
    password_reset_ttl_seconds: int = 60 * 60         # 1 hour

    # ---- limits ------------------------------------------------------
    rate_limit_enabled: bool = True
    rate_limit_auth_per_minute: int = 10
    rate_limit_chat_per_minute: int = 20
    rate_limit_default_per_minute: int = 120
    max_chat_prompt_chars: int = 8000

    @field_validator("log_level")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def effective_migration_url(self) -> str:
        return self.migration_database_url or self.database_url

    @property
    def llm_enabled(self) -> bool:
        return bool(self.nvidia_api_key and self.nvidia_api_key not in PLACEHOLDERS)

    @model_validator(mode="after")
    def _production_guards(self) -> Settings:
        if not self.is_production:
            return self

        problems: list[str] = []

        if self.database_url.startswith("sqlite"):
            problems.append("DATABASE_URL must not be SQLite in production")
        for name in ("jwt_private_key", "jwt_public_key"):
            if (getattr(self, name) or "") in PLACEHOLDERS:
                problems.append(f"{name.upper()} is required in production")
        # The mock provider returns deterministic canned text. Shipping that to
        # real users looks like a working product while producing nothing of
        # value, so production must use a real provider.
        if self.allow_mock_llm:
            problems.append("ALLOW_MOCK_LLM must be false in production")
        if not self.llm_enabled:
            problems.append("NVIDIA_API_KEY is required in production")
        if any(o == "*" for o in self.cors_origins):
            problems.append("ALLOWED_ORIGINS must not contain '*' in production")
        if self.auth0_domain and not self.auth0_issuer:
            problems.append("AUTH0_ISSUER is required whenever AUTH0_DOMAIN is set")
        # A console backend in production means verification and password-reset
        # emails are written to the log and never delivered. Users would be
        # unable to reset a password and would never receive a verify link,
        # with no error anywhere to indicate it.
        if self.email_backend == "console":
            problems.append("EMAIL_BACKEND must be 'smtp' in production")
        elif not self.smtp_host:
            problems.append("SMTP_HOST is required when EMAIL_BACKEND is 'smtp'")
        if self.frontend_base_url.startswith("http://"):
            problems.append("FRONTEND_BASE_URL must be https in production")

        if problems:
            raise ValueError(
                "Invalid production configuration:\n  - " + "\n  - ".join(problems)
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

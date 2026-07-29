"""The production fail-fast guards.

These guards are the last thing between a mistyped environment and a live
boot, and until now nothing tested them. Each case below is a configuration
that must refuse to start, plus one fully-valid production config that must.
"""

from __future__ import annotations

import pytest

from packages.shared_core.config import Settings

# A production environment with nothing wrong with it. Individual tests break
# exactly one thing so a failure names the guard that is missing.
VALID: dict[str, str] = {
    "ENVIRONMENT": "production",
    "DATABASE_URL": "postgresql+asyncpg://u:p@db.example.com:6543/postgres",
    "JWT_PRIVATE_KEY": "-----BEGIN PRIVATE KEY-----\nrealkey\n-----END PRIVATE KEY-----",
    "JWT_PUBLIC_KEY": "-----BEGIN PUBLIC KEY-----\nrealkey\n-----END PUBLIC KEY-----",
    "ALLOW_MOCK_LLM": "false",
    "SAKANA_API_KEY": "sk-a-real-looking-key",
    "ALLOWED_ORIGINS": "https://app.socialai.io",
    "EMAIL_BACKEND": "smtp",
    "SMTP_HOST": "smtp.provider.com",
    "FRONTEND_BASE_URL": "https://app.socialai.io",
}


def build(monkeypatch: pytest.MonkeyPatch, **overrides: str | None) -> Settings:
    """Construct Settings from VALID plus overrides. None removes a variable."""
    env = dict(VALID)
    for key, value in overrides.items():
        if value is None:
            env.pop(key, None)  # genuinely absent, not just overridden
        else:
            env[key] = value
    for key in (*VALID, *overrides):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    # Settings reads .env too; ignore it so the developer's file cannot make a
    # test pass or fail by accident.
    return Settings(_env_file=None)


def refuses(monkeypatch: pytest.MonkeyPatch, expected: str, **overrides: str | None) -> None:
    with pytest.raises(ValueError) as err:
        build(monkeypatch, **overrides)
    assert expected in str(err.value), f"guard did not mention {expected!r}: {err.value}"


def test_a_correct_production_config_boots(monkeypatch):
    settings = build(monkeypatch)
    assert settings.is_production
    assert settings.llm_enabled


def test_sqlite_is_refused(monkeypatch):
    refuses(monkeypatch, "DATABASE_URL", DATABASE_URL="sqlite+aiosqlite:///./prod.db")


@pytest.mark.parametrize("key", ["JWT_PRIVATE_KEY", "JWT_PUBLIC_KEY"])
def test_missing_signing_keys_are_refused(monkeypatch, key):
    """Falling back to the dev keypair in production would let anyone who can
    read the temp directory mint tokens."""
    refuses(monkeypatch, key, **{key: None})


def test_mock_llm_is_refused(monkeypatch):
    refuses(monkeypatch, "ALLOW_MOCK_LLM", ALLOW_MOCK_LLM="true")


def test_missing_llm_key_is_refused(monkeypatch):
    refuses(monkeypatch, "SAKANA_API_KEY", SAKANA_API_KEY=None)


def test_placeholder_llm_key_is_refused(monkeypatch):
    """A copied .env.example is the most likely way this goes wrong."""
    refuses(monkeypatch, "SAKANA_API_KEY", SAKANA_API_KEY="changeme")


def test_wildcard_cors_is_refused(monkeypatch):
    refuses(monkeypatch, "ALLOWED_ORIGINS", ALLOWED_ORIGINS="*")


def test_wildcard_hidden_in_a_list_is_refused(monkeypatch):
    refuses(monkeypatch, "ALLOWED_ORIGINS", ALLOWED_ORIGINS="https://app.socialai.io,*")


def test_console_email_backend_is_refused(monkeypatch):
    """Console email in production looks identical to a working system until
    users report that no mail ever arrives."""
    refuses(monkeypatch, "EMAIL_BACKEND", EMAIL_BACKEND="console")


def test_smtp_without_a_host_is_refused(monkeypatch):
    refuses(monkeypatch, "SMTP_HOST", SMTP_HOST=None)


def test_plaintext_frontend_url_is_refused(monkeypatch):
    """Verification links must not be sent over http."""
    refuses(monkeypatch, "FRONTEND_BASE_URL", FRONTEND_BASE_URL="http://app.socialai.io")


def test_auth0_domain_without_issuer_is_refused(monkeypatch):
    refuses(monkeypatch, "AUTH0_ISSUER", AUTH0_DOMAIN="tenant.eu.auth0.com")


def test_every_problem_is_reported_at_once(monkeypatch):
    """One boot should reveal the whole list, not fail a deploy per mistake."""
    with pytest.raises(ValueError) as err:
        build(
            monkeypatch,
            DATABASE_URL="sqlite+aiosqlite:///./prod.db",
            ALLOW_MOCK_LLM="true",
            ALLOWED_ORIGINS="*",
            EMAIL_BACKEND="console",
        )
    message = str(err.value)
    for expected in ("DATABASE_URL", "ALLOW_MOCK_LLM", "ALLOWED_ORIGINS", "EMAIL_BACKEND"):
        assert expected in message, f"{expected} was not reported alongside the others"


def test_development_stays_permissive(monkeypatch):
    """The same configuration that is fatal in production must be fine locally,
    or nobody can run the app without a paid provider."""
    settings = build(
        monkeypatch,
        ENVIRONMENT="development",
        DATABASE_URL="sqlite+aiosqlite:///./dev.db",
        JWT_PRIVATE_KEY=None,
        JWT_PUBLIC_KEY=None,
        ALLOW_MOCK_LLM="true",
        SAKANA_API_KEY=None,
        EMAIL_BACKEND="console",
        SMTP_HOST=None,
        FRONTEND_BASE_URL="http://127.0.0.1:3000",
    )
    assert not settings.is_production
    assert settings.allow_mock_llm


def test_api_docs_are_hidden_in_production(monkeypatch):
    """A public schema hands an attacker every field name and validation rule.

    post_deploy_verify.py checks this too, but only against a live deployment,
    so nothing caught a regression here until after a release.
    """
    settings = build(monkeypatch)
    assert settings.is_production
    assert settings.openapi_url is None
    assert settings.docs_url is None


def test_api_docs_are_available_outside_production(monkeypatch):
    settings = build(
        monkeypatch,
        ENVIRONMENT="development",
        DATABASE_URL="sqlite+aiosqlite:///./dev.db",
        JWT_PRIVATE_KEY=None,
        JWT_PUBLIC_KEY=None,
        ALLOW_MOCK_LLM="true",
        SAKANA_API_KEY=None,
        EMAIL_BACKEND="console",
        SMTP_HOST=None,
        FRONTEND_BASE_URL="http://127.0.0.1:3000",
    )
    assert settings.openapi_url is not None
    assert settings.docs_url == "/docs"

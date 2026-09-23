from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # "dev" (default, local/college-project use) or anything else (e.g.
    # "production", "staging") -- controls whether the hardcoded
    # secret_key default below is allowed. See _require_secret_key_in_non_dev.
    env: str = "dev"

    database_url: str = (
        "postgresql+asyncpg://sentinelx:sentinelx_dev_pw@postgres:5432/sentinelx"
    )

    # Used to sign login tokens. Fine as a default for a college project running
    # only on localhost -- if this were a real product, every teammate would set
    # their own random value in their own .env instead. Outside ENV=dev this
    # default is refused at startup; see _require_secret_key_in_non_dev.
    secret_key: str = "sentinelx-dev-secret-change-me"
    access_token_expire_minutes: int = 60 * 12  # 12 hours

    # SMTP settings for sending email-verification codes at registration.
    # Left blank by default -- set these in backend/.env (see SMTP_USER /
    # SMTP_PASSWORD). When blank, the backend just prints the code to the
    # server console instead of emailing it, so registration still works
    # during local development before SMTP is configured.
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from_name: str = "SentinelX"

    # Base URL of the deployed frontend -- used to build the link inside
    # invitation emails ({frontend_url}/accept-invite?token=...). The dev
    # default matches Vite's default port, same as CORS in app/main.py.
    # The dev launcher's share mode (npm run dev:share) overrides this for
    # one session only (LAN IP or tunnel URL) so emailed invitation links
    # open from other devices -- see README "Sharing the dev environment".
    frontend_url: str = "http://localhost:5173"

    # Comma-separated extra CORS origins for dev sharing ONLY, e.g.
    # "http://192.168.1.20:5173,https://random-name.trycloudflare.com".
    # Set by the dev launcher (npm run dev:share) for that session alone;
    # never set it permanently and never use "*" -- main.py only applies
    # these when ENV=dev and always keeps the localhost origin allowed.
    dev_share_origins: str = ""

    # Redis used by the background worker (docs/DECISIONS.md -- Arq over
    # RQ). The docker-compose default matches the launcher's container;
    # the worker and the API's enqueue pool both connect here, and the
    # worker prints a clear startup error if this is unreachable.
    redis_url: str = "redis://localhost:6379/0"


DEFAULT_SECRET_KEY = "sentinelx-dev-secret-change-me"


def _require_secret_key_in_non_dev(settings: "Settings") -> None:
    """
    The hardcoded secret_key default above is only safe on localhost, where
    ENV defaults to "dev". Anywhere else (ENV=production, staging, ...) a
    real SECRET_KEY must be set in the environment/.env, or every login
    token this server issues could be forged by anyone who reads this
    source file. Fails fast at import time rather than silently signing
    tokens with a public default.
    """
    if settings.env.lower() == "dev":
        return
    if not settings.secret_key or settings.secret_key == DEFAULT_SECRET_KEY:
        raise RuntimeError(
            "SECRET_KEY must be set to a real, private value when ENV is not "
            "'dev' (current ENV=" + repr(settings.env) + "). Set SECRET_KEY "
            "in the environment or backend/.env before starting the server."
        )


settings = Settings()
_require_secret_key_in_non_dev(settings)

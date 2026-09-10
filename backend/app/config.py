from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = (
        "postgresql+asyncpg://sentinelx:sentinelx_dev_pw@postgres:5432/sentinelx"
    )

    # Used to sign login tokens. Fine as a default for a college project running
    # only on localhost -- if this were a real product, every teammate would set
    # their own random value in their own .env instead.
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


settings = Settings()

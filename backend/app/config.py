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


settings = Settings()

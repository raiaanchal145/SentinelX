from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = (
        "postgresql+asyncpg://sentinelx:sentinelx_dev_pw@postgres:5432/sentinelx"
    )


settings = Settings()

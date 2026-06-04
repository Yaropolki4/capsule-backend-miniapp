from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    bot_token: str
    open_router_key: str
    s3_access_key_id: str
    s3_secret_access_key_id: str
    miniapp_url: str | None = None
    environment: str = "development"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def async_database_url(self) -> str:
        url = self.database_url
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url


settings = Settings()

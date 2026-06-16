from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AA_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./adaptive_academy.db"


settings = Settings()

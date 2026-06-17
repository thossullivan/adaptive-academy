from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AA_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./adaptive_academy.db"
    # Default Obsidian vault path (env AA_OBSIDIAN_VAULT_PATH); API calls may override per-request.
    obsidian_vault_path: str = ""


settings = Settings()

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AA_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./adaptive_academy.db"
    retriever: str = "hybrid"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_cache_dir: str = ""
    # Default Obsidian vault path (env AA_OBSIDIAN_VAULT_PATH); API calls may override per-request.
    obsidian_vault_path: str = ""
    # Static frontend build to serve at / (env AA_FRONTEND_DIST). The Docker image
    # points this at the baked-in SvelteKit build; absent in host dev, so no-op there.
    frontend_dist: str = "frontend/build"


settings = Settings()

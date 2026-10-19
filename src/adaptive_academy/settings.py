from pydantic import AliasChoices, Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Current Claude 5 family. Override per install with AA_MODEL_REASONING / AA_MODEL_COPY when
# Anthropic retires a model, instead of waiting for a code release.
DEFAULT_MODEL_REASONING = "claude-sonnet-5-5"
DEFAULT_MODEL_COPY = "claude-haiku-5-5"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AA_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./adaptive_academy.db"
    retriever: str = "hybrid"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_cache_dir: str = ""
    embedding_allow_download: bool = True
    # Default Obsidian vault path (env AA_OBSIDIAN_VAULT_PATH); API calls may override per-request.
    obsidian_vault_path: str = ""
    # Static frontend build to serve at / (env AA_FRONTEND_DIST). The Docker image
    # points this at the baked-in SvelteKit build; absent in host dev, so no-op there.
    frontend_dist: str = "frontend/build"
    # Model ids by role (env AA_MODEL_REASONING / AA_MODEL_COPY), resolved per call by
    # llm.registry.get_model. Blank means "use the default". The fields are not named
    # model_* because `model_copy` would shadow pydantic's BaseModel.model_copy().
    reasoning_model: str = Field(
        DEFAULT_MODEL_REASONING,
        validation_alias=AliasChoices("AA_MODEL_REASONING", "reasoning_model"))
    copy_model: str = Field(
        DEFAULT_MODEL_COPY, validation_alias=AliasChoices("AA_MODEL_COPY", "copy_model"))

    @field_validator("reasoning_model", "copy_model", mode="before")
    @classmethod
    def _blank_model_is_default(cls, v: object, info: ValidationInfo) -> object:
        # compose passes `${AA_MODEL_REASONING:-}` through, so "unset" arrives as "".
        if v is None or (isinstance(v, str) and not v.strip()):
            return cls.model_fields[info.field_name].default
        return v.strip() if isinstance(v, str) else v

    # --- Usage & cost --------------------------------------------------------------------
    # Daily spending limit for API-key model calls, in USD (env AA_DAILY_BUDGET_USD). Unset =
    # no limit. Checked before every API-key call against today's recorded spend (server's
    # local calendar day); Agent SDK (subscription) calls are never blocked. See llm/usage.py.
    daily_budget_usd: float | None = None

    @field_validator("daily_budget_usd", mode="before")
    @classmethod
    def _blank_budget_is_no_limit(cls, value):
        # `AA_DAILY_BUDGET_USD=` (blank, as when copied from .env.example) means "no limit",
        # not a startup crash on float("").
        if isinstance(value, str) and not value.strip():
            return None
        return value


settings = Settings()

import math

from pydantic import Field, ValidationInfo, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

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
    # The alias is the only env / .env name read (an alias bypasses env_prefix). Neither the
    # bare field name nor populate_by_name is used: the first lets a stray REASONING_MODEL in
    # the shell beat .env, the second makes AA_REASONING_MODEL work too. Code and tests can
    # still pass `reasoning_model=` to the constructor (see settings_customise_sources).
    reasoning_model: str = Field(DEFAULT_MODEL_REASONING, validation_alias="AA_MODEL_REASONING")
    copy_model: str = Field(DEFAULT_MODEL_COPY, validation_alias="AA_MODEL_COPY")

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

    @field_validator("daily_budget_usd")
    @classmethod
    def _budget_is_finite_and_non_negative(cls, value: float | None) -> float | None:
        # float("nan") never compares >= anything, so a NaN limit would never trip; inf is
        # "no limit" in disguise and a negative one is a typo. 0 is allowed: it blocks every
        # API-key call.
        if value is not None and (not math.isfinite(value) or value < 0):
            raise ValueError(
                f"AA_DAILY_BUDGET_USD must be a finite number of dollars >= 0 (got {value!r}). "
                "Use 0 to block every API-key call, or leave it blank for no limit."
            )
        return value

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ):
        def init_by_field_name() -> dict:
            # Constructor kwargs only: `Settings(reasoning_model=...)` means the aliased field.
            data = dict(init_settings())
            for name, alias in _ENV_ONLY_ALIASES.items():
                if name in data:
                    data.setdefault(alias, data.pop(name))
            return data

        return init_by_field_name, env_settings, dotenv_settings, file_secret_settings


# Fields whose only env / .env name is their alias (field name → alias).
_ENV_ONLY_ALIASES = {"reasoning_model": "AA_MODEL_REASONING", "copy_model": "AA_MODEL_COPY"}


settings = Settings()

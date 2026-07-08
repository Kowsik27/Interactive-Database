"""
config.py — Centralised Application Configuration
===================================================
All runtime settings are loaded from environment variables (via .env).
Using Pydantic BaseSettings gives us:
  - Automatic type coercion  (string "8000" → int 8000)
  - Validation at startup     (app crashes fast if config is wrong)
  - A single source of truth  (no os.environ scattered through the code)

Architectural decision: every other module imports `settings` from here.
No module touches os.environ directly.
"""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator
from typing import List


class Settings(BaseSettings):
    """
    Typed configuration object.
    All fields map 1-to-1 to entries in .env.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,         # WATSONX_API_KEY == watsonx_api_key
        extra="ignore",               # silently ignore unrecognised keys
    )

    # ------------------------------------------------------------------
    # IBM watsonx.ai
    # ------------------------------------------------------------------
    watsonx_api_key: str = Field(..., description="IBM Cloud API key")
    watsonx_project_id: str = Field(..., description="watsonx.ai project ID")
    watsonx_url: str = Field(
        default="https://us-south.ml.cloud.ibm.com",
        description="watsonx.ai regional endpoint",
    )
    granite_model_id: str = Field(
        default="ibm/granite-13b-chat-v2",
        description="Granite model identifier",
    )

    # ------------------------------------------------------------------
    # Application Server
    # ------------------------------------------------------------------
    app_host: str = Field(default="0.0.0.0")
    app_port: int = Field(default=8000, ge=1, le=65535)
    debug: bool = Field(default=False)

    # ------------------------------------------------------------------
    # Query Safety & Performance
    # ------------------------------------------------------------------
    max_rows_returned: int = Field(
        default=500,
        ge=1,
        le=10_000,
        description="Cap on rows returned per SELECT",
    )
    chat_history_window: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Conversation turns injected into LLM context",
    )
    max_execution_time_seconds: int = Field(
        default=30,
        ge=1,
        le=300,
        description="Hard SQL execution timeout",
    )
    extra_blocked_keywords: str = Field(
        default="",
        description="Comma-separated extra SQL keywords to block",
    )

    # ------------------------------------------------------------------
    # Derived helpers
    # ------------------------------------------------------------------
    @field_validator("watsonx_url")
    @classmethod
    def strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")

    def get_extra_blocked_keywords(self) -> List[str]:
        """Parse the comma-separated extra blocked keywords into a list."""
        if not self.extra_blocked_keywords:
            return []
        return [kw.strip().upper() for kw in self.extra_blocked_keywords.split(",") if kw.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Return a cached singleton Settings instance.
    lru_cache ensures .env is read only once for the entire process lifetime.
    Call `get_settings.cache_clear()` in tests to reload config.
    """
    return Settings()


# Module-level singleton — import this everywhere
settings = get_settings()

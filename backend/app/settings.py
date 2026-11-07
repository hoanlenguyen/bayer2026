"""Runtime configuration from environment variables (see .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    openai_api_key: str | None = field(default_factory=lambda: os.getenv("OPENAI_API_KEY") or None)
    openai_base_url: str | None = field(default_factory=lambda: os.getenv("OPENAI_BASE_URL") or None)
    model_reasoning: str = field(default_factory=lambda: os.getenv("MODEL_REASONING", "gpt-6-astra"))
    model_fast: str = field(default_factory=lambda: os.getenv("MODEL_FAST", "gpt-6-luna"))
    embed_model: str = field(default_factory=lambda: os.getenv("EMBED_MODEL", "text-embedding-3-small"))
    embed_dims: int = field(default_factory=lambda: int(os.getenv("EMBED_DIMS", "1536")))
    llm_provider_raw: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "auto").lower())
    mongodb_uri: str | None = field(default_factory=lambda: os.getenv("MONGODB_URI") or None)
    mongodb_db: str = field(default_factory=lambda: os.getenv("MONGODB_DB", "analytics_manager"))
    output_dir: Path = field(default_factory=lambda: BACKEND_DIR / os.getenv("OUTPUT_DIR", "output"))
    cors_origins: list[str] = field(
        default_factory=lambda: os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
    )
    # Small pause between pipeline stages in mock mode so the flow is visible in the UI.
    stage_delay: float = field(default_factory=lambda: float(os.getenv("STAGE_DELAY", "0.35")))

    @property
    def llm_provider(self) -> str:
        if self.llm_provider_raw in ("openai", "mock"):
            return self.llm_provider_raw
        return "openai" if self.openai_api_key else "mock"


settings = Settings()

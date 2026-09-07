"""Application configuration.

All runtime configuration is environment-driven. Nothing here contains secrets;
secrets arrive through the environment (locally via ``.env``, in AWS via
Secrets Manager injected as task environment variables).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Environment = Literal["local", "test", "staging", "production"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- app ---------------------------------------------------------------
    app_name: str = "Japan Second Trip API"
    environment: Environment = "local"
    debug: bool = False
    api_prefix: str = "/api/v1"
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"]
    )
    """Browser origins allowed to call the API. Both spellings of localhost are
    permitted by default because they are different origins to a browser and
    hitting that as a CORS failure wastes an afternoon. Deployed environments
    must set CORS_ORIGINS explicitly — the default is not a production value."""

    # ---- database ----------------------------------------------------------
    database_url: str = "postgresql+asyncpg://jst:jst@localhost:5433/jst"
    db_echo: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # ---- embeddings / vectors ---------------------------------------------
    embedding_provider: Literal["demo", "openai"] = "demo"
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 384
    """Vector width. The demo provider is deterministic at any width; the OpenAI
    adapter projects/validates against this value so the pgvector column type
    never has to change between demo and live mode."""

    # ---- LLM ---------------------------------------------------------------
    llm_provider: Literal["demo", "openai", "anthropic"] = "demo"
    llm_model_reasoning: str = "gpt-4o"
    llm_model_fast: str = "gpt-4o-mini"
    llm_fallback_provider: Literal["demo", "openai", "anthropic"] | None = "demo"
    llm_timeout_seconds: float = 45.0
    llm_max_retries: int = 2
    llm_temperature: float = 0.1

    openai_api_key: str | None = None
    anthropic_api_key: str | None = None

    # ---- external providers ------------------------------------------------
    place_provider: Literal["demo", "google"] = "demo"
    transport_provider: Literal["demo", "google"] = "demo"
    weather_provider: Literal["demo", "openmeteo"] = "demo"
    google_maps_api_key: str | None = None
    external_timeout_seconds: float = 10.0
    external_max_retries: int = 2

    # ---- retrieval strategy ------------------------------------------------
    retrieval_strategy: Literal["keyword", "vector", "hybrid", "hybrid_rerank"] = "hybrid"
    """Chosen by measurement, not by architecture (docs/evals/retrieval-comparison.md).

    Hybrid has the best MRR (0.887) and ties keyword on NDCG@8 and primary-in-top-5.
    Reranking is deliberately NOT the default: on a corpus this size it costs a
    case and adds latency for no measurable gain. Reranking earns its place on a
    large candidate set, which 43 chunks is not — re-evaluate as the corpus grows.
    """

    # ---- reranking ---------------------------------------------------------
    reranker: Literal["heuristic", "llm"] = "heuristic"
    retrieval_candidate_k: int = 24
    retrieval_final_k: int = 6
    rrf_k: int = 5
    """RRF damping. The paper's 60 flattens the top ranks on a corpus this size —
    1/61 and 1/67 are near-identical — so being confidently first is barely worth
    more than being seventh. 5 was chosen by sweep; see
    docs/evals/retrieval-comparison.md."""
    retrieval_dense_weight: float = 0.5
    """Weight of the dense retriever in fusion, relative to lexical. Below 1.0
    because on this corpus the lexical retriever is the stronger signal once its
    query semantics are correct — the earlier 1.5 was tuned against a lexical
    retriever crippled by plainto_tsquery's AND semantics. Re-sweep after any
    change to the embedding provider or the corpus size."""

    # ---- cache -------------------------------------------------------------
    redis_url: str | None = None
    cache_ttl_seconds: int = 900
    cache_max_entries: int = 2048

    # ---- observability -----------------------------------------------------
    otel_enabled: bool = False
    otel_exporter_otlp_endpoint: str | None = None
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str = "https://cloud.langfuse.com"
    log_level: str = "INFO"
    log_json: bool = True

    # ---- security ----------------------------------------------------------
    admin_token: str = "dev-admin-token"
    jwt_secret: str = "dev-insecure-secret-change-me"
    rate_limit_per_minute: int = 60
    ingest_domain_allowlist: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "japan.travel",
            "jnto.go.jp",
            "jrailpass.com",
            "tohokukanko.jp",
            "go-tohoku.jp",
            "visitkyushu.com",
            "go-nagano.net",
            "shikoku.gr.jp",
            "hokuriku-w.com",
        ]
    )

    # ---- checkpointing -----------------------------------------------------
    durable_checkpoints: bool = True
    """Persist LangGraph state to PostgreSQL so a graph paused on interrupt() can
    be resumed by a different process. Falls back to an in-process saver on
    SQLite or if the Postgres saver cannot start — the graphs run either way."""

    # ---- agent limits ------------------------------------------------------
    agent_max_steps: int = 24
    agent_max_tool_calls: int = 40
    agent_recursion_limit: int = 40
    context_token_budget: int = 6000

    # ---- freshness ---------------------------------------------------------
    default_freshness_ttl_days: int = 180
    critical_freshness_ttl_days: int = 90

    # ---- confidence gates --------------------------------------------------
    min_evidence_for_confident_answer: int = 2
    min_confidence_for_auto_answer: float = 0.55

    # ---- billing -----------------------------------------------------------
    stripe_secret_key: str | None = None
    price_where_next_aud: int = 0
    price_verified_route_aud: int = 59
    price_route_check_aud: int = 129

    @field_validator("cors_origins", "ingest_domain_allowlist", mode="before")
    @classmethod
    def _split_csv(cls, v: object) -> object:
        """Accept a comma-separated env var, which is how humans and
        docker-compose write lists.

        The ``NoDecode`` annotation on these fields is load-bearing: without it
        pydantic-settings JSON-decodes the raw env value *before* this validator
        runs, so ``CORS_ORIGINS=http://localhost:3000`` crashes the process at
        startup with a JSON error. A JSON array is still accepted.
        """
        if isinstance(v, str):
            text = v.strip()
            if text.startswith("["):
                import json

                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    pass
            return [item.strip() for item in text.split(",") if item.strip()]
        return v

    # ---- derived -----------------------------------------------------------
    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def demo_mode(self) -> bool:
        """True when no live external AI/data credentials are configured.

        Demo mode is a first-class supported state: the whole product works,
        but every fact produced by a demo provider is labelled as such.
        """
        return self.llm_provider == "demo" or self.embedding_provider == "demo"


@lru_cache
def get_settings() -> Settings:
    return Settings()

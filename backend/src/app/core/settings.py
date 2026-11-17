from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.enums import LogLevel

# backend/ (this file lives at backend/src/app/core/settings.py)
_BACKEND_ROOT = Path(__file__).resolve().parents[3]
_JWT_PLACEHOLDER = "CHANGE_ME_generate_a_secure_random_key_here"


class AppMeta(BaseModel):
    title: str = "Aztec List"
    description: str = "API for an OfferUp-style marketplace for college students"
    version: str = "0.1.0"
    docs_url: str | None = "/docs"
    redoc_url: str | None = "/redoc"
    environment: str = Field(
        default="development",
        description=(
            "Deployment environment. Set to 'production' to disable interactive API docs "
            "(/docs, /redoc, /openapi.json) regardless of the docs_url/redoc_url settings."
        ),
    )

    expose_docs: bool = Field(
        default=False,
        description=(
            "Keep /docs, /redoc and /openapi.json available in production (e.g. for a public "
            "portfolio demo). Off by default so production hides the API surface."
        ),
    )

    @model_validator(mode="after")
    def _hide_docs_in_prod(self) -> "AppMeta":
        """In production, force-disable interactive docs unless explicitly exposed."""
        if self.environment.lower() == "production" and not self.expose_docs:
            self.docs_url = None
            self.redoc_url = None
        return self

    @property
    def is_production(self) -> bool:
        """Whether the app is running in a production deployment."""
        return self.environment.lower() == "production"

    @property
    def openapi_enabled(self) -> bool:
        """Whether the OpenAPI schema (backing /docs and /redoc) should be served."""
        return not self.is_production or self.expose_docs


class JWTSettings(BaseModel):
    secret_key: str = Field(
        default=_JWT_PLACEHOLDER,
        min_length=32,
        description="The secret key for JWT (configure via environment variable)",
    )
    algorithm: str = Field(
        default="HS256",
        description="The algorithm used for JWT",
    )
    access_token_expire_minutes: int = Field(
        # 8h = a full work session. Long enough that buyers/sellers don't have to log
        # back in mid-task, short enough that a stolen token from a public machine has
        # a finite lifetime. Tighten for higher-risk environments.
        default=480,
        ge=1,
        description="Access token expiration time in minutes",
    )


class DatabaseSettings(BaseModel):
    database_url: str = Field(
        default="sqlite:///./aztec_list.db",
        description="Database connection URL (PostgreSQL, SQLite, etc.)",
    )

    @field_validator("database_url")
    @classmethod
    def _pin_postgres_driver(cls, url: str) -> str:
        """
        Point plain Postgres URLs at the installed psycopg2 driver.

        SQLAlchemy 2.1 made psycopg (v3) the default driver for ``postgresql://`` URLs, but
        this project ships ``psycopg2-binary``. Hosts (Neon, Heroku, docker-compose) hand
        out plain ``postgresql://`` or ``postgres://`` URLs, so map both to
        ``postgresql+psycopg2://``. URLs that already name a driver are left alone.
        """
        for prefix in ("postgresql://", "postgres://"):
            if url.startswith(prefix):
                return "postgresql+psycopg2://" + url.removeprefix(prefix)
        return url

    echo: bool = Field(
        default=False,
        description="Echo SQL statements to console (useful for debugging)",
    )
    pool_size: int = Field(
        default=10,
        ge=1,
        le=100,
        description="SQLAlchemy connection pool size (ignored for SQLite).",
    )
    max_overflow: int = Field(
        default=10,
        ge=0,
        le=100,
        description="Extra connections allowed beyond pool_size under bursty load.",
    )
    pool_recycle_seconds: int = Field(
        default=1800,
        ge=60,
        description=(
            "Recycle connections after this many seconds to avoid stale handles "
            "after upstream proxy/idle timeouts (ignored for SQLite)."
        ),
    )


class ModerationSettings(BaseModel):
    strike_auto_ban_threshold: int = Field(
        default=3,
        ge=1,
        description="Number of strikes before automatic permanent ban",
    )
    ai_review_enabled: bool = Field(
        default=False,
        description=(
            "Enable the AI second-pass that flags borderline new listings for human review "
            "(requires AI__ENABLED). The keyword filter still hard-blocks known violations."
        ),
    )
    ai_image_review_enabled: bool = Field(
        default=False,
        description=(
            "Enable AI image moderation on listing photo uploads (requires AI__ENABLED and an "
            "Anthropic API key for Claude vision). Flags borderline images to the review queue."
        ),
    )


class ListingSettings(BaseModel):
    max_images_per_listing: int = Field(
        default=10,
        ge=1,
        description="Maximum number of images allowed per listing",
    )


class StorageSettings(BaseModel):
    """File storage configuration for uploaded images."""

    root: str = Field(
        default=str(_BACKEND_ROOT / "uploads"),
        description=(
            "Root directory served at /uploads. Listing images and profile pictures live in "
            "its images/ and profiles/ subdirectories unless overridden below. Point this at "
            "a persistent volume in production (e.g. /data/uploads)."
        ),
    )
    upload_dir: str = Field(
        default="",
        description="Directory for listing images (default: {root}/images)",
    )
    profile_upload_dir: str = Field(
        default="",
        description="Directory for profile pictures (default: {root}/profiles)",
    )
    max_file_size_mb: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Maximum file size in megabytes for image uploads",
    )
    allowed_extensions: list[str] = Field(
        default=[".jpg", ".jpeg", ".png", ".webp", ".gif"],
        description="Allowed file extensions for image uploads",
    )
    allowed_mime_types: list[str] = Field(
        default=["image/jpeg", "image/png", "image/webp", "image/gif"],
        description="Allowed MIME types for image uploads",
    )

    @model_validator(mode="after")
    def _derive_subdirs(self) -> "StorageSettings":
        """Default the image/profile directories to subdirectories of ``root``."""
        if not self.upload_dir:
            self.upload_dir = str(Path(self.root) / "images")
        if not self.profile_upload_dir:
            self.profile_upload_dir = str(Path(self.root) / "profiles")
        return self


class CORSSettings(BaseModel):
    """
    Cross-Origin Resource Sharing (CORS) configuration.

    Configure allowed origins, methods, and headers for cross-origin requests.

    SECURITY NOTE:
    - The default localhost origins are suitable for DEVELOPMENT ONLY
    - In PRODUCTION, override these with actual frontend domains
    - Never use wildcard "*" with allow_credentials=True (security risk)
    """

    allowed_origins: list[str] = Field(
        default=["http://localhost:3000"],
        min_length=1,
        description="List of allowed origins for CORS (frontend URLs). Override in production!",
    )
    allow_credentials: bool = Field(
        default=True,
        description="Allow cookies and authentication headers in CORS requests",
    )
    allowed_methods: list[str] = Field(
        default=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        description="HTTP methods allowed for CORS requests",
    )
    allowed_headers: list[str] = Field(
        default=["*"],
        description="HTTP headers allowed in CORS requests (* allows all)",
    )
    frontend_url: str = Field(
        default="http://localhost:3000",
        description="Primary frontend URL for email links and redirects. Should match production frontend domain.",
    )

    @model_validator(mode="after")
    def validate_credentials_with_wildcard(self) -> "CORSSettings":
        """
        Prevent dangerous combination of wildcard origins with credentials.

        Security Issue: Using allow_credentials=True with allowed_origins=["*"]
        creates a security vulnerability where any website can make authenticated
        requests to your API.

        Raises:
            ValueError: If wildcard origin is used with credentials enabled
        """
        if self.allow_credentials and "*" in self.allowed_origins:
            msg = (
                "Security Error: Cannot use wildcard origin '*' with allow_credentials=True. "
                "This allows ANY website to make authenticated requests to your API. "
                "Either set allow_credentials=False or specify explicit origins."
            )
            raise ValueError(msg)

        return self


class LoggingSettings(BaseModel):
    """Application logging configuration."""

    level: LogLevel = Field(
        default=LogLevel.INFO,
        description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
    )
    format: str = Field(
        default="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        description="Log message format string",
    )
    use_json: bool = Field(
        default=False,
        description="Use JSON formatting for logs (recommended for production)",
    )
    uvicorn_access_level: LogLevel = Field(
        default=LogLevel.WARNING,
        description="Logging level for Uvicorn access logs",
    )
    uvicorn_error_level: LogLevel = Field(
        default=LogLevel.INFO,
        description="Logging level for Uvicorn error logs",
    )
    excluded_paths: list[str] = Field(
        default=["/health", "/ready", "/docs", "/redoc", "/openapi.json"],
        description="Paths to exclude from detailed request logging",
    )


class EmailSettings(BaseModel):
    """Email service configuration using Resend."""

    resend_api_key: str = Field(
        default="",
        description="Resend API key (configure via RESEND_API_KEY environment variable)",
    )
    from_email: str = Field(
        default="support@yourdomain.com",
        description="From email address for outgoing emails",
    )
    support_email: str = Field(
        default="support@yourdomain.com",
        description="Email address where support tickets are sent",
    )
    enabled: bool = Field(
        default=True,
        description="Enable/disable email sending (useful for testing)",
    )


class RateLimitSettings(BaseModel):
    """Rate limiting configuration."""

    enabled: bool = Field(
        default=True,
        description="Master switch to enable/disable all rate limiting (useful for emergencies or testing)",
    )


class WebSocketSettings(BaseModel):
    """Real-time messaging WebSocket guardrails."""

    rate_limit_messages: int = Field(
        default=20,
        ge=1,
        description="Max messages a single user can send through one conversation per window.",
    )
    rate_limit_window_seconds: float = Field(
        default=10.0,
        ge=1.0,
        description="Rolling window length (seconds) for the per-user/per-conversation rate limit.",
    )
    max_connections_per_user: int = Field(
        default=8,
        ge=1,
        description="Maximum concurrent WebSocket connections a single user may hold.",
    )
    idle_timeout_seconds: float = Field(
        default=300.0,
        ge=10.0,
        description="Close any WebSocket that has not received a frame within this many seconds.",
    )


class TestSettings(BaseModel):
    """Test mode configuration."""

    test_mode: bool = Field(
        default=False,
        description="Enable test-only endpoints (NEVER enable in production)",
    )


class SentrySettings(BaseModel):
    """Optional Sentry error tracking. A complete no-op when ``dsn`` is empty."""

    dsn: str = Field(
        default="",
        description="Sentry DSN. Leave empty in dev/tests; set in prod to enable error reporting.",
    )
    environment: str = Field(
        default="",
        description=(
            "Sentry environment tag (e.g. 'production', 'staging'). Empty falls back to "
            "APP__ENVIRONMENT so you only set it in one place."
        ),
    )
    traces_sample_rate: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Performance trace sample rate (0.0 disables tracing; 0.1 = 10% of requests).",
    )


class AISettings(BaseModel):
    """Master switch and shared config for AI features (semantic search, assistant)."""

    enabled: bool = Field(
        default=False,
        description=(
            "Master switch for AI features. When false, search falls back to keyword "
            "matching and no embedding model is loaded (no startup cost)."
        ),
    )


class EmbeddingSettings(BaseModel):
    """
    Text-embedding configuration.

    ``fastembed`` (default) runs the model locally and offline but needs ~1 GB of RAM
    with onnxruntime. ``cloudflare`` calls the same BGE model hosted on Cloudflare
    Workers AI, so a small production machine needs no local model at all.
    """

    provider: Literal["fastembed", "cloudflare"] = Field(
        default="fastembed",
        description="Embedding backend: 'fastembed' (local) or 'cloudflare' (Workers AI)",
    )
    model: str = Field(
        default="BAAI/bge-small-en-v1.5",
        description="fastembed model used to embed listing text; runs locally and offline",
    )
    cloudflare_model: str = Field(
        default="@cf/baai/bge-small-en-v1.5",
        description="Workers AI model id; keep it the same model family as `model`",
    )
    cloudflare_account_id: str = Field(default="", description="Cloudflare account id")
    cloudflare_api_token: str = Field(
        default="", description="Cloudflare API token with Workers AI read access"
    )
    request_timeout_seconds: float = Field(
        default=10.0, gt=0, description="Timeout for one hosted embedding request"
    )


class VectorStoreSettings(BaseModel):
    """Vector store (Qdrant) configuration for listing embeddings."""

    qdrant_url: str = Field(
        default="",
        description=(
            "Qdrant server URL (e.g. http://localhost:6333). When empty, an embedded "
            "on-disk Qdrant at `path` is used (single-process, development only)."
        ),
    )
    qdrant_api_key: str = Field(
        default="",
        description=(
            "API key for a managed Qdrant server (e.g. Qdrant Cloud). Only used when "
            "`qdrant_url` is set; leave empty for a local/unauthenticated server."
        ),
    )
    path: str = Field(
        default="./qdrant_data",
        description="On-disk path for the embedded Qdrant used when no server URL is set",
    )
    collection: str = Field(
        default="listings",
        description="Qdrant collection name holding listing vectors",
    )
    score_floor: float = Field(
        default=0.40,
        ge=0.0,
        le=1.0,
        description=(
            "Absolute minimum cosine similarity for a semantic match. If even the best hit "
            "scores below this, the query is treated as matching nothing. Keep low; the "
            "relative margin does most of the trimming."
        ),
    )
    relative_margin: float = Field(
        default=0.05,
        ge=0.0,
        le=2.0,
        description=(
            "Keep only listings scoring within this cosine margin of the best hit. Adapts to "
            "each query's score scale (unlike a fixed threshold). Smaller = stricter; set high "
            "(e.g. 2.0) to disable relative trimming. 0.05 calibrated for bge-small's tight "
            "score clustering on short listings."
        ),
    )


class LLMSettings(BaseModel):
    """Generative LLM configuration (provider abstraction for the AI assistant)."""

    provider: str = Field(
        default="ollama",
        description="Chat model provider: 'ollama' (local, default, no key) or 'anthropic' (Claude).",
    )
    assist_provider: str = Field(
        default="",
        description=(
            "Provider for assist and moderation tasks (auto-description, auto-categorize, "
            "listing moderation). Empty falls back to `provider`. Set 'anthropic' to power "
            "these with Claude while the chat assistant stays on another provider."
        ),
    )
    ollama_model: str = Field(default="qwen3.5:4b", description="Ollama chat model name")
    ollama_base_url: str = Field(default="http://localhost:11434", description="Ollama server URL")
    anthropic_model: str = Field(
        default="claude-haiku-5-5", description="Anthropic model id (provider=anthropic)"
    )
    anthropic_api_key: str = Field(
        default="", description="Anthropic API key (required when provider=anthropic)"
    )
    anthropic_effort: Literal["low", "medium", "high", "xhigh", "max"] = Field(
        default="low",
        description=(
            "Claude effort level (output_config.effort). Claude Haiku 5.5 thinks by default and "
            "bills thinking as output; 'low' keeps marketplace chat and keyword expansion cheap "
            "and fast."
        ),
    )
    anthropic_max_tokens: int = Field(
        default=1024, ge=64, le=16000, description="Per-response output cap for Claude calls"
    )
    temperature: float = Field(
        default=0.2,
        ge=0.0,
        le=2.0,
        description=(
            "Sampling temperature (lower = steadier). Applies to Ollama only: current Claude "
            "models reject non-default sampling parameters, so it is never sent to Anthropic."
        ),
    )
    retrieval_k: int = Field(
        default=6, ge=1, le=20, description="How many listings to ground the assistant with"
    )
    expand_queries: bool = Field(
        default=True,
        description="Use the LLM to expand vague searches into product keywords before embedding.",
    )
    expansion_timeout_seconds: float = Field(
        default=4.0,
        gt=0,
        le=30.0,
        description=(
            "Timeout for one query-expansion call. Expansion runs inline on every smart search, "
            "so on timeout the raw query is used rather than stalling the request."
        ),
    )
    request_timeout_seconds: float = Field(
        default=25.0,
        ge=1.0,
        le=120.0,
        description=(
            "Per-request timeout for one-shot LLM/vision calls (moderation, auto-description). "
            "On timeout the call fails open so a slow provider does not hang the API."
        ),
    )


class DemoSettings(BaseModel):
    """
    Public sandbox demo mode (portfolio deployments).

    When enabled: visitors log in as seeded personas via ``POST /auth/demo/{persona}``
    (no signup, no email), account-destroying actions return 403, and all data resets to
    the seed on a fixed schedule. Never enable this on a real deployment with real users:
    every reset deletes all rows.
    """

    enabled: bool = Field(default=False, description="Turn on sandbox demo mode")
    reset_interval_hours: float = Field(
        default=6.0,
        gt=0,
        le=168,
        description="Reset to the seed data every N hours (aligned to UTC boundaries)",
    )
    reset_token: str = Field(
        default="",
        description=(
            "Shared secret for POST /demo/reset (manual reset, e.g. scripts/reset_demo.py). "
            "Empty disables the endpoint."
        ),
    )


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.

    Settings can be configured via:
    - .env file (loaded automatically from backend/ directory)
    - Environment variables with nested structure using __ delimiter
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",  # allows APP__TITLE style vars
        case_sensitive=False,
        extra="ignore",  # ignore extra fields from .env
    )

    app: AppMeta = Field(default_factory=AppMeta)
    db: DatabaseSettings = Field(default_factory=DatabaseSettings)
    jwt: JWTSettings = Field(default_factory=JWTSettings)
    moderation: ModerationSettings = Field(default_factory=ModerationSettings)
    listing: ListingSettings = Field(default_factory=ListingSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    cors: CORSSettings = Field(default_factory=CORSSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    email: EmailSettings = Field(default_factory=EmailSettings)
    rate_limit: RateLimitSettings = Field(default_factory=RateLimitSettings)
    websocket: WebSocketSettings = Field(default_factory=WebSocketSettings)
    test: TestSettings = Field(default_factory=TestSettings)
    ai: AISettings = Field(default_factory=AISettings)
    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)
    vector: VectorStoreSettings = Field(default_factory=VectorStoreSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    sentry: SentrySettings = Field(default_factory=SentrySettings)
    demo: DemoSettings = Field(default_factory=DemoSettings)

    @model_validator(mode="after")
    def _refuse_unsafe_production(self) -> "Settings":
        """Fail fast instead of booting production with dev-only defaults."""
        if not self.app.is_production:
            return self
        problems = []
        if self.jwt.secret_key == _JWT_PLACEHOLDER:
            problems.append("JWT__SECRET_KEY is still the placeholder")
        if self.test.test_mode:
            problems.append(
                "TEST__TEST_MODE must be false (it exposes unauthenticated admin promotion)"
            )
        local = ("http://localhost", "http://127.0.0.1")
        if any(origin.startswith(local) for origin in self.cors.allowed_origins):
            problems.append("CORS__ALLOWED_ORIGINS still contains a localhost origin")
        if problems:
            msg = "Refusing to start in production: " + "; ".join(problems)
            raise ValueError(msg)
        return self


@lru_cache
def get_settings() -> Settings:
    """
    Get cached settings instance.

    Uses lru_cache to ensure settings are loaded only once.
    This is the recommended pattern for FastAPI dependency injection.

    Returns:
        Settings: Application settings instance
    """
    return Settings()


# Global settings instance
settings = get_settings()

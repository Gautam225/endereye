"""Typed application settings, read from environment variables and the project-root `.env`.

Real environment variables win over `.env`. Empty values count as "not set".
"""

import os
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

from dotenv import dotenv_values
from pydantic import (
    BeforeValidator,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_settings import (
    BaseSettings,
    NoDecode,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)
from sqlalchemy import URL, make_url
from sqlalchemy.exc import ArgumentError

from app.core.vault import Vault, check_key

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = PROJECT_ROOT / ".env"


class ConfigError(RuntimeError):
    """Settings are missing or invalid. The message is written for humans."""


def _split_commas(value: Any) -> Any:
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return value


# A list written in .env as "a,b,c".
CommaList = Annotated[list[str], NoDecode, BeforeValidator(_split_commas)]
SecretList = Annotated[list[SecretStr], NoDecode, BeforeValidator(_split_commas)]

# Numbered variables collected into one list field, e.g. OPENROUTER_API_KEY_1, _2, ...
NUMBERED_KEYS = {
    "openrouter_api_keys": "OPENROUTER_API_KEY_",
    "groq_api_keys": "GROQ_API_KEY_",
}


class NumberedKeysSource(PydanticBaseSettingsSource):
    """Collects OPENROUTER_API_KEY_1..N and GROQ_API_KEY_1..N into ordered lists.

    Reads the same `.env` file as the normal dotenv source; real environment variables win.
    Blank values are skipped, so unused slots in `.env` are fine.
    """

    def __init__(self, settings_cls: type[BaseSettings], env_file: Any) -> None:
        super().__init__(settings_cls)
        self._env_file = env_file

    def get_field_value(self, field: Any, field_name: str) -> tuple[Any, str, bool]:
        return None, field_name, False  # unused: __call__ builds the values directly

    def __call__(self) -> dict[str, Any]:
        raw: dict[str, str] = {}
        for path in _env_paths(self._env_file):
            if path.is_file():
                for name, value in dotenv_values(path, encoding="utf-8").items():
                    if value is not None:
                        raw[name.upper()] = value
        raw.update({name.upper(): value for name, value in os.environ.items()})

        values: dict[str, Any] = {}
        for field_name, prefix in NUMBERED_KEYS.items():
            numbered = {
                int(name.removeprefix(prefix)): value.strip()
                for name, value in raw.items()
                if name.startswith(prefix) and name.removeprefix(prefix).isdigit() and value.strip()
            }
            if numbered:
                values[field_name] = [numbered[number] for number in sorted(numbered)]
        return values


def _env_paths(env_file: Any) -> list[Path]:
    if env_file is None:
        return []
    if isinstance(env_file, str | Path):
        return [Path(env_file)]
    if isinstance(env_file, Sequence):
        return [Path(item) for item in env_file]
    return []


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    # App
    app_name: str = "Eye of Ender"
    app_env: Literal["development", "production", "test"] = "development"
    app_debug: bool = False
    cors_origins: CommaList = ["http://localhost:5173"]

    # Sign-in. SECRET_KEY signs access tokens: changing it signs everyone out.
    secret_key: SecretStr
    access_token_minutes: int = Field(default=15, ge=1, le=120)
    refresh_token_days: int = Field(default=7, ge=1, le=90)

    # PostgreSQL (app data + pgvector). One URL:
    #   DATABASE_URL=postgresql://USER:PASSWORD@HOST:PORT/DATABASE
    database_url: SecretStr | None = None
    # ...or the same thing in parts. Used only when DATABASE_URL is not set.
    postgres_host: str = "localhost"
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    postgres_db: str = "eye_of_ender"
    postgres_user: str = "eoe_app"
    postgres_password: SecretStr | None = None

    # LLM primary: OpenRouter. Keys come from OPENROUTER_API_KEY_1..N.
    openrouter_api_keys: SecretList = []
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_models_smart: CommaList = Field(
        default=["thinkingmachines/inkling:free", "nvidia/nemotron-3-ultra-550b-a55b:free"],
        min_length=1,
    )
    openrouter_models_fast: CommaList = Field(
        default=["thinkingmachines/inkling-small:free", "nvidia/nemotron-3.5-lightning:free"],
        min_length=1,
    )

    # LLM fallback: Groq. Keys come from GROQ_API_KEY_1..N.
    groq_api_keys: SecretList = []
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_models_smart: CommaList = Field(
        default=["openai/gpt-oss-120b", "llama-3.3-70b-versatile"], min_length=1
    )
    groq_models_fast: CommaList = Field(default=["openai/gpt-oss-20b"], min_length=1)
    # Groq's free plan allows 8,000 tokens/minute per model; bigger prompts skip Groq.
    groq_max_prompt_tokens: int = Field(default=6000, ge=500)

    # LLM behaviour
    llm_attempt_timeout_seconds: float = Field(default=60, gt=0)
    llm_total_timeout_seconds: float = Field(default=120, gt=0)
    llm_rate_limit_cooldown_seconds: float = Field(default=60, gt=0)

    # Data: uploaded files are stored (as Parquet) under DATA_DIR, relative to the project.
    data_dir: Path = Path("data")
    max_upload_mb: int = Field(default=200, ge=1, le=10_000)
    # Folders that Delta tables may be added from (comma-separated). DATA_DIR always counts.
    local_data_roots: CommaList = []
    query_timeout_seconds: float = Field(default=60, gt=0)
    query_max_rows: int = Field(default=10_000, ge=1, le=1_000_000)
    # Profiling reads a whole table (counts, distinct values), so it gets longer than a query
    profile_timeout_seconds: float = Field(default=120, gt=0)

    # External databases ("connections"). CONNECTION_ENCRYPTION_KEY encrypts the stored passwords;
    # make one with: python -c "from app.core.vault import generate_key; print(generate_key())"
    # After changing it, keep the old one in CONNECTION_ENCRYPTION_KEY_PREVIOUS until every
    # connection has been saved again.
    connection_encryption_key: SecretStr | None = None
    connection_encryption_key_previous: SecretStr | None = None
    # When set, a connection may only use these host names (comma-separated).
    external_db_allowed_hosts: CommaList = []
    external_db_allow_private: bool = True  # hosts on private networks (10.x, 192.168.x, 172.16.x)
    external_db_allow_loopback: bool = False  # this machine itself: for development only
    external_db_connect_timeout_seconds: float = Field(default=5, gt=0, le=60)

    # Benchmark questions per space (each run asks the AI service about each of them).
    benchmark_max_items: int = Field(default=50, ge=1, le=500)

    # Single sign-on (OpenID Connect: Okta, Entra ID, Google Workspace, Keycloak, Auth0...).
    # Off until SSO_ISSUER, SSO_CLIENT_ID and SSO_CLIENT_SECRET are set. PUBLIC_URL is the address
    # people open the app at; the provider sends them back to PUBLIC_URL/api/v1/auth/sso/callback.
    public_url: str = "http://localhost:5173"
    sso_issuer: str = ""
    sso_client_id: str = ""
    sso_client_secret: SecretStr | None = None
    sso_name: str = "Single sign-on"
    sso_scopes: str = "openid email profile"
    sso_allowed_domains: CommaList = []  # empty = any email the provider vouches for
    sso_auto_create: bool = True  # make an account the first time someone signs in
    sso_default_role: Literal["admin", "editor", "viewer"] = "viewer"
    sso_password_login: bool = True  # False: the email-and-password form is turned off

    # Dashboards and scheduled reports. Email is off until SMTP_HOST is set: reports are still made
    # and can be downloaded. REPORT_ALLOWED_EMAIL_DOMAINS limits who a report may be sent to.
    smtp_host: str = ""
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str = ""
    smtp_password: SecretStr | None = None
    smtp_from: str = ""
    smtp_security: Literal["starttls", "ssl", "none"] = "starttls"
    smtp_timeout_seconds: float = Field(default=20, gt=0, le=120)
    report_allowed_email_domains: CommaList = []
    report_max_recipients: int = Field(default=10, ge=1, le=100)
    report_max_per_person: int = Field(default=20, ge=1, le=200)
    alert_max_per_person: int = Field(default=20, ge=1, le=200)
    report_pdf_rows: int = Field(default=100, ge=1, le=2000)  # rows of each result in the PDF
    report_poll_seconds: float = Field(
        default=30, ge=1, le=600
    )  # how often due reports are looked for
    report_scheduler: bool = True  # turn off on all but one server if several share a database
    report_keep_runs: int = Field(default=10, ge=1, le=200)  # runs (and files) kept per report
    dashboard_max_items: int = Field(default=30, ge=1, le=200)  # kept answers per dashboard

    # Knowledge search (Step 6). Models run locally on the CPU.
    embedding_model: str = "BAAI/bge-small-en-v1.5"  # 384 dimensions; changing it needs a migration
    rerank_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"
    # Model files are cached here, a short path on purpose (see docs/ROADMAP.md, Step 6)
    models_dir: Path = Path("data/models")
    document_parser: Literal["markitdown", "docling"] = "markitdown"
    # Reading pictures (OCR) on this server: scanned pages, the words in charts, image files.
    document_ocr: bool = True
    document_ocr_max_pages: int = Field(default=100, ge=0, le=2000)  # per document, to bound time
    # Text per chunk, measured with the embedder's own tokenizer. The header must fit as well:
    # bge-small reads at most 512 tokens and silently cuts off the rest.
    chunk_tokens: int = Field(default=450, ge=64, le=480)
    chunk_overlap_tokens: int = Field(default=40, ge=0, le=50)
    # Passages scoring below this are dropped (at least 5 are always kept)
    rerank_threshold: float = 0.0

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        numbered = NumberedKeysSource(settings_cls, getattr(dotenv_settings, "env_file", None))
        return init_settings, numbered, env_settings, dotenv_settings, file_secret_settings

    @field_validator("connection_encryption_key", "connection_encryption_key_previous")
    @classmethod
    def _usable_vault_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and value.get_secret_value():
            try:
                check_key(value.get_secret_value())
            except ValueError as exc:
                raise ValueError(f"not a valid key: {exc}") from None  # never echo the key
        return value or None

    def vault(self) -> Vault:
        """The vault for connection passwords (raises when no key is configured)."""
        return Vault.from_keys(
            self.connection_encryption_key.get_secret_value()
            if self.connection_encryption_key
            else None,
            self.connection_encryption_key_previous.get_secret_value()
            if self.connection_encryption_key_previous
            else None,
        )

    @field_validator("secret_key")
    @classmethod
    def _strong_secret(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError(
                "must be at least 32 characters; generate one with: "
                'python -c "import secrets; print(secrets.token_urlsafe(64))"'
            )
        return value

    @field_validator("database_url")
    @classmethod
    def _check_database_url(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None:
            parse_database_url(value.get_secret_value())  # raises a readable ValueError
        return value

    @model_validator(mode="after")
    def _database_configured(self) -> "Settings":
        if self.database_url is None and self.postgres_password is None:
            raise ValueError(
                "DATABASE_URL is missing. Set it in .env, for example "
                "DATABASE_URL=postgresql://postgres:your-password@localhost:5432/eye_of_ender "
                "(or run: python scripts/setup_database.py in the backend folder)"
            )
        return self

    @field_validator("cors_origins")
    @classmethod
    def _clean_origins(cls, value: list[str]) -> list[str]:
        if "*" in value:
            raise ValueError("'*' is not allowed; list the exact frontend URLs")
        return [origin.rstrip("/") for origin in value]

    @field_validator(
        "openrouter_models_smart", "openrouter_models_fast", "groq_models_smart", "groq_models_fast"
    )
    @classmethod
    def _check_model_ids(cls, value: list[str]) -> list[str]:
        for model in value:
            if " " in model:
                raise ValueError(
                    f"model id {model!r} contains a space; separate models with commas"
                )
        return value

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def data_path(self) -> Path:
        """DATA_DIR as an absolute path (relative paths start at the project folder)."""
        path = self.data_dir if self.data_dir.is_absolute() else PROJECT_ROOT / self.data_dir
        return path.resolve()

    @property
    def allowed_data_roots(self) -> list[Path]:
        return [
            self.data_path,
            *(Path(root).expanduser().resolve() for root in self.local_data_roots),
        ]

    @property
    def sqlalchemy_url(self) -> URL:
        """Where the app's database is, as SQLAlchemy needs it. repr() hides the password."""
        if self.database_url is not None:
            return parse_database_url(self.database_url.get_secret_value())
        # URL.create escapes special characters in the password itself.
        return URL.create(
            drivername=ASYNC_DRIVER,
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value() if self.postgres_password else None,
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )


ASYNC_DRIVER = "postgresql+asyncpg"


def parse_database_url(raw: str) -> URL:
    """Read a DATABASE_URL like postgresql://user:password@localhost:5432/eye_of_ender.

    `postgres://` and `postgresql+<driver>://` are accepted too; the app always uses asyncpg.
    Error messages never repeat the URL, because it contains the password.
    """
    example = "expected postgresql://user:password@host:5432/database"
    try:
        url = make_url(raw.strip())
        port = url.port  # a non-numeric port fails here
    except (ArgumentError, ValueError):
        raise ValueError(f"is not a valid URL ({example})") from None
    if port is not None and not 1 <= port <= 65535:
        raise ValueError(f"has an invalid port ({example})")
    scheme = url.drivername.split("+", 1)[0]
    if scheme not in ("postgres", "postgresql"):
        raise ValueError(f"must start with postgresql:// (it starts with {scheme}://)")
    if not url.username:
        raise ValueError(f"has no user name ({example})")
    if not url.database:
        raise ValueError(f"has no database name at the end ({example})")
    return url.set(drivername=ASYNC_DRIVER)


def load_settings(**overrides: Any) -> Settings:
    """Build settings, turning validation errors into one readable ConfigError."""
    try:
        return Settings(**overrides)
    except ValidationError as exc:
        problems = []
        for error in exc.errors():
            name = ".".join(str(part) for part in error["loc"]).upper()
            if error["type"] == "missing":
                reason = "missing - set it in .env"
            else:
                reason = error["msg"].removeprefix("Value error, ")
            problems.append(f"  - {name}: {reason}" if name else f"  - {reason}")
        raise ConfigError(f"Invalid settings ({ENV_FILE}):\n" + "\n".join(problems)) from None


@lru_cache
def get_settings() -> Settings:
    return load_settings()

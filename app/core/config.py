from typing import Annotated, Literal

from pydantic import BeforeValidator, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _parse_list(v: object) -> list[str]:
    if isinstance(v, str):
        if not v.strip():
            return []
        return [item.strip() for item in v.split(",") if item.strip()]
    if isinstance(v, list):
        return [str(item).strip() for item in v]
    return []


StringList = Annotated[list[str], BeforeValidator(_parse_list)]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ENVIRONMENT: Literal["dev", "test", "prod"] = "dev"

    POSTGRES_USER: str = "secureapi"
    POSTGRES_PASSWORD: str = ""
    POSTGRES_DB: str = "secureapi"
    DATABASE_URL: str = "postgresql+psycopg://secureapi:secureapi@localhost:5432/secureapi"

    JWT_SECRET: str = "default-dev-secret-change-in-production-minimum-32-chars"  # noqa: S105
    JWT_ISSUER: str = "secureapi"
    JWT_AUDIENCE: str = "secureapi-clients"
    ACCESS_TOKEN_TTL_MINUTES: int = 15
    REFRESH_TOKEN_TTL_DAYS: int = 7

    ARGON2_TIME_COST: int = 3
    ARGON2_MEMORY_KIB: int = 65536
    ARGON2_PARALLELISM: int = 4

    LOGIN_MAX_ATTEMPTS: int = 5
    LOGIN_LOCK_MINUTES: int = 15
    REQUIRE_VERIFIED_EMAIL: bool = True

    CORS_ORIGINS: StringList = Field(default_factory=lambda: ["http://localhost:3000"])
    TRUSTED_PROXIES: StringList = Field(default_factory=list)

    RATE_LIMIT_LOGIN: str = "5/minute"
    RATE_LIMIT_DEFAULT: str = "100/minute"
    MAX_BODY_BYTES: int = 1048576  # 1 MB
    DOCS_ENABLED: bool = True
    DEMO_PASSWORD: str = ""

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        if self.ENVIRONMENT == "prod":
            example_secrets = [
                "",
                "default-dev-secret-change-in-production-minimum-32-chars",
                "ci-only-secret-ci-only-secret-ci-only-secret",
                "secret",
                "changeme",
            ]
            secret_bytes = self.JWT_SECRET.encode("utf-8")
            if not self.JWT_SECRET or len(secret_bytes) < 32 or self.JWT_SECRET in example_secrets:
                raise ValueError(
                    "Production configuration error: JWT_SECRET must be at least 32 bytes "
                    "and not use an example value."
                )
        return self


settings = Settings()

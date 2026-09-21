from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # DB (ton projet utilise POSTGRES_* dans .env)
    postgres_user: str = "postgres"
    postgres_password: str = "postgres"
    postgres_server: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "postgres"

    # Auth (si tu l'as)
    jwt_secret: str = "changethis_secret_key"

    # Google compare (Option A)
    google_routes_api_key: str | None = None

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def db_url(self) -> str:
        # SQLAlchemy psycopg (Python 3.12)
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_server}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()

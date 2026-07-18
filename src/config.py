from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql://postgres:postgres@localhost:5432/postgres"

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        # Render (and others) often provide postgres://; asyncpg expects postgresql://
        if isinstance(value, str) and value.startswith("postgres://"):
            return "postgresql://" + value.removeprefix("postgres://")
        return value
    use_mock_sources: bool = True

    hubspot_access_token: str = ""
    stripe_secret_key: str = ""
    google_calendar_id: str = "primary"
    google_service_account_json: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""
    google_refresh_token: str = ""


settings = Settings()

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    api_key: SecretStr
    broker_url: str = "amqp://webhook:webhook@127.0.0.1:5672/webhook"
    allowed_webhook_hosts: list[str] = ["example.com"]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, JsonValue, field_validator

from app.config import settings


class SubscriptionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: str = Field(
        min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_.-]*$"
    )
    url: HttpUrl = Field(max_length=2048)

    @field_validator("url")
    @classmethod
    def validate_url(cls, url: HttpUrl) -> HttpUrl:
        if url.scheme != "https":
            raise ValueError("Webhook URL must use HTTPS")
        if url.username is not None or url.password is not None:
            raise ValueError("Webhook URL must not contain credentials")
        if url.fragment is not None:
            raise ValueError("Webhook URL must not contain a fragment")
        if url.host not in settings.allowed_webhook_hosts:
            raise ValueError("Webhook host is not allowed")
        return url


class SubscriptionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(strict=True)


class SubscriptionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_type: str
    url: str
    enabled: bool
    created_at: datetime


class EventCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = Field(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_.-]*$")
    data: dict[str, JsonValue]


class EventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    type: str
    data: dict[str, JsonValue]
    created_at: datetime

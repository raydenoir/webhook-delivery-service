from pydantic import HttpUrl

from app.config import settings


def validate_webhook_url(url: HttpUrl) -> HttpUrl:
    if url.scheme != "https":
        raise ValueError("Webhook URL must use HTTPS")
    if url.username is not None or url.password is not None:
        raise ValueError("Webhook URL must not contain credentials")
    if url.fragment is not None:
        raise ValueError("Webhook URL must not contain a fragment")
    if url.host not in settings.allowed_webhook_hosts:
        raise ValueError("Webhook host is not allowed")
    return url

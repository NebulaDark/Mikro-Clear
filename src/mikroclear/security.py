import re
from typing import Any


TELEGRAM_BOT_TOKEN_RE = re.compile(r"/bot[0-9]+:[A-Za-z0-9_-]+/")


def mask_telegram_bot_token(text: Any) -> str:
    return TELEGRAM_BOT_TOKEN_RE.sub("/bot***MASKED***/", str(text))


def mask_known_secret(text: Any, secret: str | None, label: str = "SECRET") -> str:
    value = mask_telegram_bot_token(text)
    if secret:
        value = value.replace(secret, "***MASKED***")
    return value


def sanitize_exception_text(exc: BaseException, *secrets: str) -> str:
    value = f"{type(exc).__name__}: {exc}"
    for secret in secrets:
        value = mask_known_secret(value, secret)
    return mask_telegram_bot_token(value)

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    session_ttl_seconds: int


def load_settings() -> Settings:
    session_ttl_raw = os.getenv("SESSION_TTL_SECONDS", "1800")
    try:
        session_ttl = max(60, int(session_ttl_raw))
    except ValueError:
        session_ttl = 1800

    return Settings(session_ttl_seconds=session_ttl)

from __future__ import annotations

import os
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


class ConfigurationError(RuntimeError):
    """Raised when required runtime configuration is absent."""


def configure_root_certificate(database_url: str, certificate_path: str) -> str:
    if not certificate_path:
        return database_url
    parsed = urlparse(database_url)
    query = [item for item in parse_qsl(parsed.query) if item[0] != "sslrootcert"]
    query.append(("sslrootcert", certificate_path))
    return urlunparse(parsed._replace(query=urlencode(query)))


@dataclass(frozen=True)
class Settings:
    database_url: str = field(repr=False)
    groq_api_key: str = field(repr=False)
    groq_model: str = "llama-3.3-70b-versatile"

    @classmethod
    def from_env(cls) -> Settings:
        database_url = os.environ.get("DATABASE_URL", "").strip()
        groq_api_key = os.environ.get("GROQ_API_KEY", "").strip()
        missing = [
            name
            for name, value in (
                ("DATABASE_URL", database_url),
                ("GROQ_API_KEY", groq_api_key),
            )
            if not value
        ]
        if missing:
            raise ConfigurationError(f"missing required configuration: {', '.join(missing)}")
        return cls(
            database_url=configure_root_certificate(
                database_url,
                os.environ.get("DATABASE_CA_CERT", "").strip(),
            ),
            groq_api_key=groq_api_key,
            groq_model=os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile").strip(),
        )

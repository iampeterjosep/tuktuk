from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    supabase_url: str
    supabase_service_role_key: str
    # No longer used for verification (Supabase signs tokens with ES256 via
    # JWKS now, see dependencies.py), kept optional so old .env files with
    # this key set don't break startup.
    supabase_jwt_secret: Optional[str] = None
    allowed_origins: str = "*"

    class Config:
        env_file = ".env"

    @property
    def cors_origins(self) -> list[str]:
        if self.allowed_origins == "*":
            return ["*"]
        return [o.strip() for o in self.allowed_origins.split(",")]


settings = Settings()
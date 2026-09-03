from functools import lru_cache
from supabase import create_client, Client
from app.config import settings


@lru_cache
def get_supabase() -> Client:
    """
    Server-side Supabase client using the SERVICE ROLE key.
    This bypasses Row Level Security entirely - only ever used
    from within FastAPI (never exposed to Flutter), and only for
    the specific privileged operations this backend is trusted with.
    """
    return create_client(settings.supabase_url, settings.supabase_service_role_key)

from fastapi import APIRouter, Depends

from app.dependencies import require_role, CurrentUser
from app.services.supabase_client import get_supabase
from app.models import OvertakeRequest

router = APIRouter(prefix="/queue", tags=["queue"])


@router.post("/overtake")
def overtake(
    payload: OvertakeRequest,
    user: CurrentUser = Depends(require_role("admin", "monitor")),
):
    """
    Called when a driver in line isn't ready to carry passengers yet.
    Marks them 'not_ready' and moves them to the back of their own line,
    giving everyone behind them the privilege to move up. This calls the
    overtake_driver() Postgres function (see tuktuk_schema.sql) so the
    "find max position, reassign, log" sequence happens atomically in
    the database rather than as separate round trips from here.
    """
    supabase = get_supabase()
    supabase.rpc(
        "overtake_driver",
        {"p_queue_entry_id": payload.queue_entry_id, "p_actor": user.id},
    ).execute()

    return {"detail": "Driver marked not ready and moved to back of line"}

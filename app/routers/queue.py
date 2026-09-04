from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import require_role, CurrentUser
from app.services.supabase_client import get_supabase
from app.models import OvertakeRequest, ReinstateRequest

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


@router.post("/reinstate")
def reinstate(
    payload: ReinstateRequest,
    user: CurrentUser = Depends(require_role("admin", "monitor")),
):
    """
    Brings a 'not_ready' tuktuk back into active rotation once it's ready
    to carry passengers again. Rejoins at the back of its current line -
    same rule as a fresh join, so nobody who's been waiting gets skipped.
    """
    supabase = get_supabase()

    existing = (
        supabase.table("queue_entries")
        .select("line_id, status")
        .eq("id", payload.queue_entry_id)
        .maybe_single()
        .execute()
    )
    existing_data = existing.data if existing is not None else None
    if not existing_data:
        raise HTTPException(status_code=404, detail="Queue entry not found")

    if existing_data["status"] != "not_ready":
        raise HTTPException(
            status_code=409, detail="Only 'not ready' entries can be reinstated"
        )

    line_id = existing_data["line_id"]

    last = (
        supabase.table("queue_entries")
        .select("position")
        .eq("line_id", line_id)
        .in_("status", ["waiting", "loading", "not_ready"])
        .order("position", desc=True)
        .limit(1)
        .execute()
    )
    next_position = (last.data[0]["position"] + 1) if last.data else 1

    supabase.table("queue_entries").update(
        {"status": "waiting", "position": next_position, "updated_by": user.id}
    ).eq("id", payload.queue_entry_id).execute()

    supabase.table("audit_logs").insert(
        {
            "queue_entry_id": payload.queue_entry_id,
            "action": "reinstated",
            "performed_by": user.id,
            "from_status": "not_ready",
            "to_status": "waiting",
            "to_position": next_position,
        }
    ).execute()

    return {"detail": "Driver reinstated to waiting", "position": next_position}

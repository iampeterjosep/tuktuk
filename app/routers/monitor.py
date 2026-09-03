from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import require_role, CurrentUser
from app.services.supabase_client import get_supabase
from app.models import UpdateStatusRequest

router = APIRouter(prefix="/monitor", tags=["monitor"])


@router.patch("/queue/{queue_entry_id}/status")
def update_status(
    queue_entry_id: str,
    payload: UpdateStatusRequest,
    user: CurrentUser = Depends(require_role("monitor", "admin")),
):
    """
    Monitors use this to flip a tuktuk's status as it fills with passengers
    (waiting -> loading -> completed). Position/line are never touched here -
    the database itself (guard_monitor_update trigger) would reject it even
    if this endpoint tried, but we also just never send it.
    """
    supabase = get_supabase()

    existing = (
        supabase.table("queue_entries")
        .select("status")
        .eq("id", queue_entry_id)
        .single()
        .execute()
    )
    if not existing.data:
        raise HTTPException(status_code=404, detail="Queue entry not found")

    old_status = existing.data["status"]

    supabase.table("queue_entries").update(
        {"status": payload.status.value, "updated_by": user.id}
    ).eq("id", queue_entry_id).execute()

    supabase.table("audit_logs").insert(
        {
            "queue_entry_id": queue_entry_id,
            "action": "status_changed",
            "performed_by": user.id,
            "from_status": old_status,
            "to_status": payload.status.value,
        }
    ).execute()

    return {"detail": "Status updated", "status": payload.status.value}

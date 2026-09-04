from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import require_role, CurrentUser
from app.services.supabase_client import get_supabase
from app.models import (
    JoinQueueRequest,
    JoinQueueResponse,
    ReorderRequest,
    MoveLineRequest,
    VoidRequest,
)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/queue/join", response_model=JoinQueueResponse)
def join_queue(
    payload: JoinQueueRequest,
    user: CurrentUser = Depends(require_role("admin")),
):
    """
    Registers a tuktuk into a line when it enters the station lot.
    Creates the driver record if the plate isn't known yet, then
    appends them to the back of the chosen line.
    """
    supabase = get_supabase()

    # 1. Find or create the driver by plate number
    existing = (
        supabase.table("drivers")
        .select("id")
        .eq("plate_number", payload.plate_number)
        .maybe_single()
        .execute()
    )
    existing_data = existing.data if existing is not None else None

    if existing_data:
        driver_id = existing_data["id"]
    else:
        created = (
            supabase.table("drivers")
            .insert(
                {
                    "plate_number": payload.plate_number,
                    "name": payload.driver_name,
                    "phone": payload.driver_phone,
                }
            )
            .execute()
        )
        driver_id = created.data[0]["id"]

    # 2. Reject if this driver already has an active queue entry somewhere
    active = (
        supabase.table("queue_entries")
        .select("id")
        .eq("driver_id", driver_id)
        .in_("status", ["waiting", "loading", "not_ready"])
        .execute()
    )
    if active.data:
        raise HTTPException(
            status_code=409,
            detail="This driver already has an active queue entry",
        )

    # 3. Compute next position at the back of the chosen line
    last = (
        supabase.table("queue_entries")
        .select("position")
        .eq("line_id", payload.line_id)
        .in_("status", ["waiting", "loading", "not_ready"])
        .order("position", desc=True)
        .limit(1)
        .execute()
    )
    next_position = (last.data[0]["position"] + 1) if last.data else 1

    entry = (
        supabase.table("queue_entries")
        .insert(
            {
                "line_id": payload.line_id,
                "driver_id": driver_id,
                "position": next_position,
                "status": "waiting",
                "updated_by": user.id,
            }
        )
        .execute()
    )
    entry_row = entry.data[0]

    supabase.table("audit_logs").insert(
        {
            "queue_entry_id": entry_row["id"],
            "action": "joined",
            "performed_by": user.id,
            "to_status": "waiting",
            "to_position": next_position,
        }
    ).execute()

    return JoinQueueResponse(
        queue_entry_id=entry_row["id"],
        driver_id=driver_id,
        line_id=payload.line_id,
        position=next_position,
        status="waiting",
    )


@router.post("/queue/reorder")
def reorder_line(
    payload: ReorderRequest,
    user: CurrentUser = Depends(require_role("admin")),
):
    """
    Persists a new drag-and-drop order for a line. Flutter sends the full
    list of entries in that line with their new position values; we update
    each row and log every change that actually moved.
    """
    supabase = get_supabase()

    current = (
        supabase.table("queue_entries")
        .select("id, position")
        .eq("line_id", payload.line_id)
        .execute()
    )
    current_positions = {row["id"]: row["position"] for row in current.data}

    for item in payload.items:
        old_position = current_positions.get(item.queue_entry_id)
        if old_position == item.position:
            continue

        supabase.table("queue_entries").update(
            {"position": item.position, "updated_by": user.id}
        ).eq("id", item.queue_entry_id).execute()

        supabase.table("audit_logs").insert(
            {
                "queue_entry_id": item.queue_entry_id,
                "action": "reordered",
                "performed_by": user.id,
                "from_position": old_position,
                "to_position": item.position,
            }
        ).execute()

    return {"detail": "Line reordered", "line_id": payload.line_id}


@router.post("/queue/move")
def move_line(
    payload: MoveLineRequest,
    user: CurrentUser = Depends(require_role("admin")),
):
    """
    Reassigns a tuktuk from its current line to a different one - this is
    what powers dragging a card between line columns on the admin board.
    Only touches this entry; the Flutter client follows up with a
    /admin/queue/reorder call for the affected line(s) to keep positions
    a clean 1..n sequence.
    """
    supabase = get_supabase()

    existing = (
        supabase.table("queue_entries")
        .select("line_id, position, status")
        .eq("id", payload.queue_entry_id)
        .maybe_single()
        .execute()
    )
    existing_data = existing.data if existing is not None else None
    if not existing_data:
        raise HTTPException(status_code=404, detail="Queue entry not found")

    if existing_data["status"] not in ("waiting", "loading", "not_ready"):
        raise HTTPException(
            status_code=409, detail="Only active entries can be moved between lines"
        )

    old_line_id = existing_data["line_id"]
    old_position = existing_data["position"]

    supabase.table("queue_entries").update(
        {
            "line_id": payload.target_line_id,
            "position": payload.target_position,
            "updated_by": user.id,
        }
    ).eq("id", payload.queue_entry_id).execute()

    supabase.table("audit_logs").insert(
        {
            "queue_entry_id": payload.queue_entry_id,
            "action": "moved_line",
            "performed_by": user.id,
            "from_position": old_position,
            "to_position": payload.target_position,
            "note": f"Moved from line {old_line_id} to {payload.target_line_id}",
        }
    ).execute()

    return {"detail": "Entry moved to new line"}


@router.post("/queue/void")
def void_entry(
    payload: VoidRequest,
    user: CurrentUser = Depends(require_role("admin")),
):
    """Removes a driver from the queue entirely (left / no-show)."""
    supabase = get_supabase()

    existing = (
        supabase.table("queue_entries")
        .select("status")
        .eq("id", payload.queue_entry_id)
        .single()
        .execute()
    )
    if not existing.data:
        raise HTTPException(status_code=404, detail="Queue entry not found")

    old_status = existing.data["status"]

    supabase.table("queue_entries").update(
        {"status": "void", "updated_by": user.id}
    ).eq("id", payload.queue_entry_id).execute()

    supabase.table("audit_logs").insert(
        {
            "queue_entry_id": payload.queue_entry_id,
            "action": "voided",
            "performed_by": user.id,
            "from_status": old_status,
            "to_status": "void",
            "note": payload.note,
        }
    ).execute()

    return {"detail": "Entry voided"}

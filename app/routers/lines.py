from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import require_role, CurrentUser
from app.services.supabase_client import get_supabase
from app.models import LineCreateRequest, LineUpdateRequest, LineResponse

router = APIRouter(prefix="/admin/lines", tags=["lines"])


@router.get("", response_model=list[LineResponse])
def list_lines(
    station_id: str,
    user: CurrentUser = Depends(require_role("admin")),
):
    """
    Lists every line for a station, active and inactive, for the "Manage
    Lines" screen. (The public/realtime read Flutter uses for the queue
    tabs only ever sees active lines - this is the admin-only view that
    also surfaces closed ones so they can be reopened.)
    """
    supabase = get_supabase()
    rows = (
        supabase.table("lines")
        .select("id, station_id, line_number, is_active")
        .eq("station_id", station_id)
        .order("line_number")
        .execute()
    )
    return [LineResponse(**row) for row in rows.data]


@router.post("", response_model=LineResponse)
def create_line(
    payload: LineCreateRequest,
    user: CurrentUser = Depends(require_role("admin")),
):
    supabase = get_supabase()

    existing = (
        supabase.table("lines")
        .select("id")
        .eq("station_id", payload.station_id)
        .eq("line_number", payload.line_number)
        .maybe_single()
        .execute()
    )
    existing_data = existing.data if existing is not None else None
    if existing_data:
        raise HTTPException(
            status_code=409, detail="A line with that number already exists"
        )

    created = (
        supabase.table("lines")
        .insert(
            {
                "station_id": payload.station_id,
                "line_number": payload.line_number,
                "is_active": True,
            }
        )
        .execute()
    )
    return LineResponse(**created.data[0])


@router.patch("/{line_id}", response_model=LineResponse)
def update_line(
    line_id: str,
    payload: LineUpdateRequest,
    user: CurrentUser = Depends(require_role("admin")),
):
    supabase = get_supabase()

    existing = (
        supabase.table("lines").select("id").eq("id", line_id).maybe_single().execute()
    )
    existing_data = existing.data if existing is not None else None
    if not existing_data:
        raise HTTPException(status_code=404, detail="Line not found")

    update_fields = payload.model_dump(exclude_none=True)
    if not update_fields:
        raise HTTPException(status_code=400, detail="Nothing to update")

    updated = (
        supabase.table("lines").update(update_fields).eq("id", line_id).execute()
    )
    return LineResponse(**updated.data[0])


@router.delete("/{line_id}")
def delete_line(
    line_id: str,
    user: CurrentUser = Depends(require_role("admin")),
):
    """
    Deletes a line outright. Blocked if any tuktuk currently sits in it
    (waiting/loading/not_ready) - a beginner-friendly admin should never
    be able to accidentally erase a driver's spot in the queue.
    """
    supabase = get_supabase()

    active = (
        supabase.table("queue_entries")
        .select("id")
        .eq("line_id", line_id)
        .in_("status", ["waiting", "loading", "not_ready"])
        .execute()
    )
    if active.data:
        raise HTTPException(
            status_code=409,
            detail="This line still has tuktuks in it - clear the line first",
        )

    supabase.table("lines").delete().eq("id", line_id).execute()
    return {"detail": "Line deleted"}

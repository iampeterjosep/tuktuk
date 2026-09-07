from typing import Optional

from fastapi import APIRouter, HTTPException

from app.services.supabase_client import get_supabase
from app.models import DriverSearchResult

router = APIRouter(prefix="/driver", tags=["driver"])


@router.get("/search/{plate_number}", response_model=DriverSearchResult)
def search_by_plate(plate_number: str):
    """
    Public endpoint - no login. A driver types their plate and sees only
    their own line number, how far up the queue they are, how many
    vehicles are still ahead of them, and the plate of the single
    vehicle directly ahead. They cannot see anyone else's contact
    details, so this returns a narrow, purpose-built shape rather than
    raw queue_entries rows.
    """
    supabase = get_supabase()

    driver = (
        supabase.table("drivers")
        .select("id, name")
        .eq("plate_number", plate_number)
        .maybe_single()
        .execute()
    )
    driver_data = driver.data if driver is not None else None
    if not driver_data:
        raise HTTPException(status_code=404, detail="Plate number not found")

    entry = (
        supabase.table("queue_entries")
        .select("id, line_id, status, position, lines(line_number)")
        .eq("driver_id", driver_data["id"])
        .in_("status", ["waiting", "loading", "not_ready"])
        .maybe_single()
        .execute()
    )
    entry_data = entry.data if entry is not None else None
    if not entry_data:
        raise HTTPException(
            status_code=404, detail="This driver is not currently in a queue"
        )

    line_id = entry_data["line_id"]
    my_position = entry_data["position"]

    # Pull every active entry in this line together with its driver's
    # plate, ordered by position, so we can identify just the single
    # vehicle immediately ahead of this one - not the whole line.
    same_line = (
        supabase.table("queue_entries")
        .select("position, drivers(plate_number)")
        .eq("line_id", line_id)
        .in_("status", ["waiting", "loading", "not_ready"])
        .order("position")
        .execute()
    )
    rows = same_line.data
    positions = [row["position"] for row in rows]
    position_in_line = positions.index(my_position) + 1
    total_in_line = len(positions)
    vehicles_ahead = position_in_line - 1

    vehicle_ahead_plate: Optional[str] = None
    if position_in_line > 1:
        # rows is sorted by position ascending, so the row immediately
        # before ours in the list is the vehicle directly ahead.
        preceding = rows[position_in_line - 2]
        vehicle_ahead_plate = (preceding.get("drivers") or {}).get("plate_number")

    return DriverSearchResult(
        plate_number=plate_number,
        driver_name=driver_data.get("name"),
        line_number=entry_data["lines"]["line_number"],
        status=entry_data["status"],
        position_in_line=position_in_line,
        total_in_line=total_in_line,
        vehicles_ahead=vehicles_ahead,
        vehicle_ahead_plate=vehicle_ahead_plate,
    )

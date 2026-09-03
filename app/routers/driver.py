from fastapi import APIRouter, HTTPException

from app.services.supabase_client import get_supabase
from app.models import DriverSearchResult

router = APIRouter(prefix="/driver", tags=["driver"])


@router.get("/search/{plate_number}", response_model=DriverSearchResult)
def search_by_plate(plate_number: str):
    """
    Public endpoint - no login. A driver types their plate and sees only
    their own line number and how far up the queue they are. They cannot
    see other drivers' names/phones, so this endpoint returns a narrow,
    purpose-built shape rather than raw queue_entries rows.
    """
    supabase = get_supabase()

    # NOTE: supabase-py's .maybe_single().execute() returns None outright
    # (not a response object with data=None) when zero rows match - guard
    # against that here rather than assuming a response object always comes back.
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

    # Everyone ahead of this driver (lower position) still active in the line
    same_line = (
        supabase.table("queue_entries")
        .select("position")
        .eq("line_id", line_id)
        .in_("status", ["waiting", "loading", "not_ready"])
        .execute()
    )
    ahead_or_equal = sorted(row["position"] for row in same_line.data)
    position_in_line = ahead_or_equal.index(my_position) + 1
    total_in_line = len(ahead_or_equal)

    return DriverSearchResult(
        plate_number=plate_number,
        driver_name=driver_data.get("name"),
        line_number=entry_data["lines"]["line_number"],
        status=entry_data["status"],
        position_in_line=position_in_line,
        total_in_line=total_in_line,
    )
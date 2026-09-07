from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import require_role, CurrentUser
from app.services.supabase_client import get_supabase
from app.models import DriverUpdateRequest, DriverResponse, DriverLookupResponse

router = APIRouter(prefix="/admin/drivers", tags=["drivers"])


@router.get("", response_model=list[DriverResponse])
def list_drivers(
    search: Optional[str] = None,
    user: CurrentUser = Depends(require_role("admin")),
):
    """
    Lists drivers for the "Manage Drivers" screen, optionally filtered by
    a plate-or-name search. Kept as a simple substring match (via
    Postgres ILIKE through supabase-py's `.or_()`) since the driver table
    is station-scale, not something that needs full-text search.
    """
    supabase = get_supabase()
    query = supabase.table("drivers").select("id, plate_number, name, phone")

    if search:
        pattern = f"%{search}%"
        query = query.or_(f"plate_number.ilike.{pattern},name.ilike.{pattern}")

    rows = query.order("plate_number").limit(200).execute()
    return [DriverResponse(**row) for row in rows.data]


@router.get("/lookup/{plate_number}", response_model=DriverLookupResponse)
def lookup_driver(
    plate_number: str,
    user: CurrentUser = Depends(require_role("admin")),
):
    """
    Used by the "Register Tuktuk" dialog: as staff type a plate number,
    the client calls this to check whether we already know this driver.
    If we do, name/phone are prefilled automatically so staff aren't
    retyping contact details every time a regular comes back for another
    ride - the same driver row is reused (see join_queue's find-or-create
    logic in routers/admin.py), only a new queue_entries ride record is
    created.

    Returns a plain 404 (not a 200 with a null body) for an unknown
    plate, so the client can distinguish "new driver, nothing to
    prefill" from "known driver with blank contact fields" without
    special-casing an empty response body.
    """
    supabase = get_supabase()
    result = (
        supabase.table("drivers")
        .select("id, plate_number, name, phone")
        .eq("plate_number", plate_number)
        .maybe_single()
        .execute()
    )
    data = result.data if result is not None else None
    if not data:
        raise HTTPException(status_code=404, detail="Plate number not known yet")
    return DriverLookupResponse(**data)


@router.patch("/{driver_id}", response_model=DriverResponse)
def update_driver(
    driver_id: str,
    payload: DriverUpdateRequest,
    user: CurrentUser = Depends(require_role("admin")),
):
    supabase = get_supabase()

    existing = (
        supabase.table("drivers")
        .select("id")
        .eq("id", driver_id)
        .maybe_single()
        .execute()
    )
    existing_data = existing.data if existing is not None else None
    if not existing_data:
        raise HTTPException(status_code=404, detail="Driver not found")

    update_fields = payload.model_dump(exclude_none=True)
    if not update_fields:
        raise HTTPException(status_code=400, detail="Nothing to update")

    updated = (
        supabase.table("drivers").update(update_fields).eq("id", driver_id).execute()
    )
    return DriverResponse(**updated.data[0])


@router.delete("/{driver_id}")
def delete_driver(
    driver_id: str,
    user: CurrentUser = Depends(require_role("admin")),
):
    """
    Deletes a driver record. Blocked if they currently have an active
    queue entry, so admins can't accidentally erase someone who's
    actively waiting in line.
    """
    supabase = get_supabase()

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
            detail="This driver is currently in a queue - remove them from the line first",
        )

    supabase.table("drivers").delete().eq("id", driver_id).execute()
    return {"detail": "Driver deleted"}

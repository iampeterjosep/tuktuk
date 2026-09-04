from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class QueueStatus(str, Enum):
    waiting = "waiting"
    loading = "loading"
    completed = "completed"
    not_ready = "not_ready"
    void = "void"


class JoinQueueRequest(BaseModel):
    line_id: str
    plate_number: str = Field(..., min_length=2)
    driver_name: Optional[str] = None
    driver_phone: Optional[str] = None


class JoinQueueResponse(BaseModel):
    queue_entry_id: str
    driver_id: str
    line_id: str
    position: float
    status: QueueStatus


class UpdateStatusRequest(BaseModel):
    status: QueueStatus


class ReorderItem(BaseModel):
    queue_entry_id: str
    position: float


class ReorderRequest(BaseModel):
    line_id: str
    items: list[ReorderItem]


class OvertakeRequest(BaseModel):
    queue_entry_id: str


class VoidRequest(BaseModel):
    queue_entry_id: str
    note: Optional[str] = None


class DriverSearchResult(BaseModel):
    plate_number: str
    driver_name: Optional[str]
    line_number: int
    status: QueueStatus
    position_in_line: int
    total_in_line: int


# ---- Line management (admin CRUD) ----


class LineCreateRequest(BaseModel):
    station_id: str
    line_number: int = Field(..., gt=0)


class LineUpdateRequest(BaseModel):
    line_number: Optional[int] = Field(None, gt=0)
    is_active: Optional[bool] = None


class LineResponse(BaseModel):
    id: str
    station_id: str
    line_number: int
    is_active: bool


# ---- Driver management (admin CRUD) ----


class DriverUpdateRequest(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None


class DriverResponse(BaseModel):
    id: str
    plate_number: str
    name: Optional[str] = None
    phone: Optional[str] = None

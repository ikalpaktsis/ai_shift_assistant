from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, ConfigDict


class ServiceRequest(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str = Field(..., alias="sr_id")
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    owner: Optional[str] = None
    last_update: Optional[str] = None
    notes: Optional[str] = None
    escalation_flag: Optional[bool] = None
    age_hours: Optional[float] = None
    site: Optional[str] = None
    node: Optional[str] = None
    customer: Optional[str] = None
    vendor: Optional[str] = None


class ShiftRequest(BaseModel):
    srs: List[ServiceRequest]
    shift_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    notify_email: bool = False
    email_to: Optional[str] = None


class ReportResponse(BaseModel):
    shift_id: Optional[str]
    summary: str
    stats: Dict[str, Any]
    classifications: Dict[str, Any]
    actions: List[Dict[str, Any]]
    persistent_sites: List[str]
    email: Optional[Dict[str, Any]] = None
    memory_updated: bool = False

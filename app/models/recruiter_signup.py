"""
Models for recruiter self-service signup flow.
"""

from pydantic import BaseModel, EmailStr, Field
from typing import Optional, Literal
from datetime import date, time


class SchoolListItem(BaseModel):
    """School item for dropdown list."""
    id: str
    name: str
    city: Optional[str] = None
    state: Optional[str] = None


class SchoolListResponse(BaseModel):
    """Response for public schools list."""
    schools: list[SchoolListItem]
    total: int


class UniversalEventItem(BaseModel):
    """Universal event item for search results."""
    id: str
    name: str
    event_date: date
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    location: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    venue: Optional[str] = None
    description: Optional[str] = None


class UniversalEventSearchResponse(BaseModel):
    """Response for universal event search."""
    events: list[UniversalEventItem]
    total: int
    page: int
    pages: int


class SchoolSelection(BaseModel):
    """School selection for recruiter signup."""
    type: Literal["existing", "new"]
    school_id: Optional[str] = None  # Required if type is "existing"
    school_name: Optional[str] = None  # Required if type is "new"
    is_self_admin: bool = False  # True if recruiter IS the admin (no invite needed)
    admin_email: Optional[EmailStr] = None  # Required if is_self_admin=False for new schools
    admin_first_name: Optional[str] = None  # Optional admin first name
    admin_last_name: Optional[str] = None  # Optional admin last name


class RecruiterSignupRequest(BaseModel):
    """Request body for recruiter self-signup."""
    email: EmailStr
    password: str = Field(..., min_length=8)
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    school_selection: SchoolSelection
    universal_event_ids: list[str] = Field(..., min_length=1, max_length=10, description="List of universal event IDs to purchase")


class RecruiterSignupResponse(BaseModel):
    """Response for successful recruiter signup initiation."""
    user_id: str
    checkout_session_id: str
    checkout_url: str
    access_token: str
    refresh_token: str


class EventPurchaseRequest(BaseModel):
    """Request for purchasing additional events (authenticated users)."""
    universal_event_id: str


class EventPurchaseResponse(BaseModel):
    """Response for event purchase initiation."""
    checkout_session_id: str
    checkout_url: str
    purchase_id: str

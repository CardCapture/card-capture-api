"""
Pydantic models for universal event submission.
"""

from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional
from datetime import date, time
import re


class UniversalEventSubmissionRequest(BaseModel):
    """Request model for submitting a new universal event."""

    # Required fields
    name: str
    event_date: date
    contact_name: str
    contact_email: EmailStr
    contact_phone: str

    # Optional fields
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    location: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = "TX"
    zip: Optional[str] = None
    description: Optional[str] = None

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Event name is required")
        return v.strip()

    @field_validator("contact_name")
    @classmethod
    def contact_name_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Contact name is required")
        return v.strip()

    @field_validator("contact_phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Contact phone is required")
        # Remove all non-digit characters for storage
        digits = re.sub(r"\D", "", v)
        if len(digits) < 10:
            raise ValueError("Phone number must have at least 10 digits")
        return digits

    @field_validator("zip")
    @classmethod
    def validate_zip(cls, v: Optional[str]) -> Optional[str]:
        if v is None or not v.strip():
            return None
        digits = re.sub(r"\D", "", v)
        if len(digits) not in (5, 9):
            raise ValueError("ZIP code must be 5 or 9 digits")
        return digits[:5]  # Store just 5-digit ZIP

    @field_validator("state")
    @classmethod
    def validate_state(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return "TX"
        return v.upper()[:2]


class UniversalEventSubmissionResponse(BaseModel):
    """Response model for event submission."""

    success: bool
    event_id: str
    message: str

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
    needs_inquiry_cards: Optional[bool] = False
    expected_students: Optional[int] = None

    # Secondary contact (optional)
    contact_name_secondary: Optional[str] = None
    contact_email_secondary: Optional[EmailStr] = None
    contact_phone_secondary: Optional[str] = None

    # CAPTCHA
    captcha_token: Optional[str] = None

    # Inquiry cards mailing address (when needs_inquiry_cards is True)
    inquiry_cards_same_as_event_address: Optional[bool] = True
    inquiry_cards_address: Optional[str] = None
    inquiry_cards_city: Optional[str] = None
    inquiry_cards_state: Optional[str] = None
    inquiry_cards_zip: Optional[str] = None
    inquiry_cards_attention: Optional[str] = None

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

    @field_validator("expected_students")
    @classmethod
    def validate_expected_students(cls, v: Optional[int]) -> Optional[int]:
        if v is None:
            return None
        if v < 1:
            raise ValueError("Expected students must be at least 1")
        if v > 50000:
            raise ValueError("Expected students seems unreasonably high")
        return v

    @field_validator("contact_phone_secondary")
    @classmethod
    def validate_secondary_phone(cls, v: Optional[str]) -> Optional[str]:
        if v is None or not v.strip():
            return None
        # Remove all non-digit characters for storage
        digits = re.sub(r"\D", "", v)
        if len(digits) < 10:
            raise ValueError("Secondary phone must have at least 10 digits")
        return digits

    @field_validator("inquiry_cards_zip")
    @classmethod
    def validate_inquiry_cards_zip(cls, v: Optional[str]) -> Optional[str]:
        if v is None or not v.strip():
            return None
        digits = re.sub(r"\D", "", v)
        if len(digits) not in (5, 9):
            raise ValueError("Mailing ZIP code must be 5 or 9 digits")
        return digits[:5]

    @field_validator("inquiry_cards_state")
    @classmethod
    def validate_inquiry_cards_state(cls, v: Optional[str]) -> Optional[str]:
        if v is None or not v.strip():
            return None
        return v.upper()[:2]


class UniversalEventSubmissionResponse(BaseModel):
    """Response model for event submission."""

    success: bool
    event_id: str
    message: str

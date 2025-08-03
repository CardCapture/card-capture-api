"""
Address Suggestions Models for Real-time Validation
"""

from typing import List, Optional
from pydantic import BaseModel, Field


class AddressSuggestionsRequest(BaseModel):
    """Request model for real-time address validation"""
    address: Optional[str] = Field(default="", description="Street address")
    city: Optional[str] = Field(default="", description="City name") 
    state: Optional[str] = Field(default="", description="State abbreviation")
    zip_code: Optional[str] = Field(default="", description="ZIP code")
    
    class Config:
        json_schema_extra = {
            "example": {
                "address": "9905 Genoa",
                "city": "Plano", 
                "state": "TX",
                "zip_code": ""
            }
        }


class AddressSuggestion(BaseModel):
    """Individual address suggestion"""
    formatted_address: str = Field(description="Complete formatted address")
    address: str = Field(description="Street address")
    city: str = Field(description="City name")
    state: str = Field(description="State abbreviation") 
    zip_code: str = Field(description="ZIP code")
    confidence: str = Field(description="Confidence level: high, medium, low")
    source: str = Field(description="Validation source: google_maps, zip_validation, smart_correction")
    changes_made: List[str] = Field(default=[], description="List of fields that were changed")
    enhancement_notes: str = Field(default="", description="Human-readable explanation of changes")
    
    class Config:
        json_schema_extra = {
            "example": {
                "formatted_address": "9905 Genoa Ct, Plano, TX 75093, USA",
                "address": "9905 Genoa Court",
                "city": "Plano",
                "state": "TX", 
                "zip_code": "75093",
                "confidence": "high",
                "source": "google_maps",
                "changes_made": ["address", "zip_code"],
                "enhancement_notes": "Enhanced street name and auto-filled ZIP code"
            }
        }


class AddressSuggestionsResponse(BaseModel):
    """Response model for address suggestions"""
    success: bool = Field(description="Whether the request was successful")
    has_suggestions: bool = Field(description="Whether any suggestions were found") 
    suggestions: List[AddressSuggestion] = Field(default=[], description="List of address suggestions")
    original_input: dict = Field(description="Original input for reference")
    validation_attempted: bool = Field(default=True, description="Whether validation was attempted")
    error: Optional[str] = Field(default=None, description="Error message if validation failed")
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "has_suggestions": True,
                "suggestions": [
                    {
                        "formatted_address": "9905 Genoa Ct, Plano, TX 75093, USA",
                        "address": "9905 Genoa Court", 
                        "city": "Plano",
                        "state": "TX",
                        "zip_code": "75093",
                        "confidence": "high",
                        "source": "google_maps",
                        "changes_made": ["address", "zip_code"],
                        "enhancement_notes": "Enhanced street name and auto-filled ZIP code"
                    }
                ],
                "original_input": {
                    "address": "9905 Genoa",
                    "city": "Plano",
                    "state": "TX", 
                    "zip_code": ""
                },
                "validation_attempted": True,
                "error": None
            }
        }
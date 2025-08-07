"""
Consolidated Address Validation Service
Handles both pipeline and real-time address validation with 4-state system
"""

import json
from typing import Dict, Any, Optional, Tuple, Literal
from app.core.clients import gmaps_client
from app.utils.retry_utils import log_debug

# Type definitions for validation states
ValidationState = Literal["verified", "can_be_verified", "no_house_number", "not_verified"]

class AddressValidationResult:
    """Standardized result for all address validation operations"""
    
    def __init__(
        self, 
        state: ValidationState,
        is_valid: bool = False,
        suggestion: Optional[Dict[str, str]] = None,
        error: Optional[str] = None,
        original_query: Optional[Dict[str, str]] = None
    ):
        self.state = state
        self.is_valid = is_valid
        self.suggestion = suggestion
        self.error = error
        self.original_query = original_query or {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses"""
        return {
            "state": self.state,
            "is_valid": self.is_valid,
            "suggestion": self.suggestion,
            "error": self.error,
            "original_query": self.original_query
        }


def validate_address(
    address: str, 
    city: str = "", 
    state: str = "", 
    zip_code: str = ""
) -> AddressValidationResult:
    """
    Main address validation function - handles all validation scenarios
    
    Returns one of 4 states:
    - verified: Google Maps confirmed exact match
    - can_be_verified: Google Maps found suggestion but not exact match
    - no_house_number: Address missing house number
    - not_verified: Could not validate address
    """
    
    log_debug("=== ADDRESS VALIDATION START ===", {
        "address": address,
        "city": city,
        "state": state,
        "zip_code": zip_code
    }, service="address_validation")
    
    original_query = {
        "address": address,
        "city": city,
        "state": state,
        "zip_code": zip_code
    }
    
    # Input validation - be more flexible about what we can validate
    if not address or not address.strip():
        log_debug("No address provided", service="address_validation")
        return AddressValidationResult("not_verified", original_query=original_query)
    
    # Check for house number first
    if not _has_house_number(address):
        log_debug("Address missing house number", service="address_validation")
        return AddressValidationResult(
            "no_house_number", 
            error="Please add a house number to validate the address",
            original_query=original_query
        )
    
    # Check if we have enough info to make a useful query
    # We can validate with:
    # 1. Address + ZIP (Google can find city/state)
    # 2. Address + City + State (Google can find ZIP)  
    # 3. All fields
    has_zip = zip_code and zip_code.strip()
    has_city_state = city and city.strip() and state and state.strip()
    
    if not has_zip and not has_city_state:
        log_debug("Not enough location context - need either ZIP or City+State", service="address_validation")
        return AddressValidationResult(
            "not_verified",
            error="Need either ZIP code or City + State for validation",
            original_query=original_query
        )
    
    # Try Google Maps validation
    try:
        google_result = _validate_with_google_maps(address, city, state, zip_code)
        
        if google_result:
            # First check if it's a complete address with house number
            is_complete_address = _is_complete_deliverable_address(google_result)
            
            if not is_complete_address:
                log_debug("Google Maps result lacks house number - treating as NOT_VERIFIED", {
                    "formatted_address": google_result.get('formatted_address'),
                    "street_number": google_result.get('street_number'),
                    "street_address": google_result.get('street_address')
                }, service="address_validation")
                return AddressValidationResult(
                    "not_verified",
                    error="Address not found in Google Maps",
                    original_query=original_query
                )
            
            # Check if it's an exact match or close suggestion
            is_exact_match = _is_exact_match(original_query, google_result)
            
            # Check if we're filling in missing fields (helpful mode)
            # If user provided partial info and we found the rest, show as "can_be_verified"
            # so they can review and confirm the complete address
            is_filling_blanks = False
            if google_result:
                # Check if Google filled in fields that were empty in the original query
                if (not city.strip() and google_result.get('city')) or \
                   (not state.strip() and google_result.get('state')) or \
                   (not zip_code.strip() and google_result.get('zip_code')):
                    is_filling_blanks = True
                    log_debug("Google Maps filled in missing fields - showing as CAN BE VERIFIED for user confirmation", service="address_validation")
            
            if is_exact_match and not is_filling_blanks:
                log_debug("Exact match found with all fields provided - VERIFIED", service="address_validation")
                return AddressValidationResult(
                    "verified",
                    is_valid=True,
                    suggestion=_format_suggestion(google_result),
                    original_query=original_query
                )
            else:
                log_debug("Address suggestion found - CAN BE VERIFIED", service="address_validation")
                return AddressValidationResult(
                    "can_be_verified",
                    is_valid=True,
                    suggestion=_format_suggestion(google_result),
                    original_query=original_query
                )
        else:
            log_debug("No Google Maps results found - NOT VERIFIED", service="address_validation")
            return AddressValidationResult(
                "not_verified",
                error="Address not found in Google Maps",
                original_query=original_query
            )
            
    except Exception as e:
        log_debug(f"Google Maps validation error: {str(e)}", service="address_validation")
        
        # Return user-friendly error
        error_message = _get_friendly_error_message(str(e))
        
        return AddressValidationResult(
            "not_verified",
            error=error_message,
            original_query=original_query
        )


def _is_complete_deliverable_address(google_result: Dict[str, Any]) -> bool:
    """
    Check if Google Maps result contains a complete deliverable street address
    
    Must have:
    1. Street number (house number) 
    2. Street name
    3. City and state
    4. Formatted address that starts with a number
    
    This prevents false positives like "Chamblin Dr" without house numbers.
    """
    if not google_result:
        return False
    
    # Must have both street number AND street name components
    has_street_number = bool(google_result.get('street_number'))
    has_street_name = bool(google_result.get('street_name'))
    has_street_components = has_street_number and has_street_name
    
    # Check if we have a complete street address field  
    street_address = google_result.get('street_address', '')
    has_complete_street_address = bool(street_address and _has_house_number(street_address))
    
    # Must have location components
    has_location = google_result.get('city') and google_result.get('state')
    
    # Formatted address should start with a number (house number)
    formatted = google_result.get('formatted_address', '')
    starts_with_number = bool(formatted and formatted.strip() and formatted.strip()[0].isdigit())
    
    # For extra validation, check that formatted address contains actual house number
    has_house_number_in_formatted = _has_house_number(formatted) if formatted else False
    
    # Address is only complete if it has ALL required components
    is_complete = (
        (has_street_components or has_complete_street_address) and
        has_location and
        starts_with_number and
        has_house_number_in_formatted
    )
    
    log_debug("Checking if Google Maps result is complete deliverable address", {
        "has_street_number": has_street_number,
        "has_street_name": has_street_name,
        "has_complete_street_address": has_complete_street_address, 
        "has_location": has_location,
        "starts_with_number": starts_with_number,
        "has_house_number_in_formatted": has_house_number_in_formatted,
        "is_complete": is_complete,
        "formatted_address": formatted,
        "street_address": street_address
    }, service="address_validation")
    
    return is_complete


def _has_house_number(address: str) -> bool:
    """Check if address contains a house number at the beginning"""
    import re
    
    if not address or not address.strip():
        return False
    
    # Look for digits at the start, optionally followed by letter (123A)
    # Allow for fractions like 123 1/2 or ranges like 123-125
    pattern = r'^\s*\d+[A-Za-z]?(\s*[-/]\s*\d+)*\s+'
    
    has_number = bool(re.match(pattern, address.strip()))
    
    log_debug("House number check", {
        "address": address,
        "has_house_number": has_number
    }, service="address_validation")
    
    return has_number


def _validate_with_google_maps(address: str, city: str, state: str, zip_code: str) -> Optional[Dict[str, Any]]:
    """Call Google Maps API for validation"""
    
    if not gmaps_client:
        log_debug("Google Maps client not initialized", service="address_validation")
        return None
    
    # Build query string
    query_parts = [address]
    if city.strip():
        query_parts.append(city.strip())
    if state.strip():
        query_parts.append(state.strip())
    if zip_code.strip():
        query_parts.append(zip_code.strip())
    
    full_query = ", ".join(query_parts)
    
    log_debug(f"Google Maps query: {full_query}", service="address_validation")
    
    try:
        geocode_results = gmaps_client.geocode(full_query)
        
        if not geocode_results:
            return None
        
        # Use first result
        result = geocode_results[0]
        formatted_address = result.get('formatted_address', '')
        geometry = result.get('geometry', {})
        location = geometry.get('location', {})
        components = result.get('address_components', [])
        
        # Extract components
        extracted = {}
        for component in components:
            types = component.get('types', [])
            if 'street_number' in types:
                extracted['street_number'] = component['long_name']
            elif 'route' in types:
                extracted['street_name'] = component['long_name']
            elif 'locality' in types:
                extracted['city'] = component['long_name']
            elif 'administrative_area_level_1' in types:
                extracted['state'] = component['short_name']
            elif 'postal_code' in types:
                extracted['zip_code'] = component['long_name']
        
        # Build complete street address
        if 'street_number' in extracted and 'street_name' in extracted:
            extracted['address'] = f"{extracted['street_number']} {extracted['street_name']}"
        
        log_debug("Google Maps validation successful", {
            "formatted_address": formatted_address,
            "extracted_components": extracted
        }, service="address_validation")
        
        return {
            "formatted_address": formatted_address,
            "latitude": location.get('lat'),
            "longitude": location.get('lng'),
            "place_id": result.get('place_id'),
            **extracted
        }
        
    except Exception as e:
        log_debug(f"Google Maps API error: {str(e)}", service="address_validation")
        raise  # Re-raise to handle in main function


def _is_exact_match(original: Dict[str, str], google_result: Dict[str, Any]) -> bool:
    """
    Determine if Google result is an exact match vs a suggestion
    
    Exact match criteria:
    - Address components match (allowing for minor formatting differences)
    - Provided components match what Google found
    - Empty fields don't count against the match
    """
    
    def normalize_string(s: str) -> str:
        """Normalize string for comparison"""
        if not s:
            return ""
        return s.strip().lower().replace('.', '').replace(',', '')
    
    # Compare address (most important)
    original_addr = normalize_string(original.get("address", ""))
    google_addr = normalize_string(google_result.get("address", ""))
    
    # Allow some flexibility in address matching
    # If the core parts match (number + street name), consider it exact
    if original_addr and google_addr:
        # Extract just the meaningful parts for comparison
        import re
        
        def extract_core_address(addr: str) -> str:
            # Remove common suffixes and normalize
            addr = re.sub(r'\b(st|street|ave|avenue|rd|road|dr|drive|ct|court|ln|lane|way|pl|place)\b', '', addr)
            return re.sub(r'\s+', ' ', addr).strip()
        
        original_core = extract_core_address(original_addr)
        google_core = extract_core_address(google_addr)
        
        address_matches = original_core == google_core or original_addr == google_addr
    else:
        address_matches = False
    
    # For partial inputs, only check the fields that were provided
    # If user only gave address + ZIP, we verify those match and consider it exact
    # The missing city/state will be filled in as a helpful suggestion
    
    # Compare city (only if provided)
    original_city = original.get("city", "")
    if original_city.strip():
        city_matches = (
            normalize_string(original_city) == 
            normalize_string(google_result.get("city", ""))
        )
    else:
        city_matches = True  # Empty city doesn't count against match
    
    # Compare state (only if provided)
    original_state = original.get("state", "")
    if original_state.strip():
        state_matches = (
            normalize_string(original_state) == 
            normalize_string(google_result.get("state", ""))
        )
    else:
        state_matches = True  # Empty state doesn't count against match
    
    # Compare ZIP (only if provided)
    original_zip = original.get("zip_code", "")
    if original_zip.strip():
        zip_matches = (
            normalize_string(original_zip) == 
            normalize_string(google_result.get("zip_code", ""))
        )
    else:
        zip_matches = True  # Empty ZIP doesn't count against match
    
    is_exact = address_matches and city_matches and state_matches and zip_matches
    
    log_debug("Exact match evaluation", {
        "address_matches": address_matches,
        "city_matches": city_matches,
        "state_matches": state_matches,
        "zip_matches": zip_matches,
        "is_exact_match": is_exact,
        "original": original,
        "google": {
            "address": google_result.get("address"),
            "city": google_result.get("city"),
            "state": google_result.get("state"),
            "zip_code": google_result.get("zip_code")
        }
    }, service="address_validation")
    
    return is_exact


def _format_suggestion(google_result: Dict[str, Any]) -> Dict[str, str]:
    """Format Google result as a clean suggestion"""
    return {
        "formatted_address": google_result.get("formatted_address", ""),
        "address": google_result.get("address", ""),
        "city": google_result.get("city", ""),
        "state": google_result.get("state", ""),
        "zip_code": google_result.get("zip_code", "")
    }


def _get_friendly_error_message(error: str) -> str:
    """Convert technical errors to user-friendly messages"""
    error_lower = error.lower()
    
    if 'network' in error_lower or 'fetch' in error_lower or 'connection' in error_lower:
        return "Network error - please check connection and try again"
    elif 'quota' in error_lower or 'limit' in error_lower:
        return "Validation temporarily unavailable - please try again later"
    elif 'api' in error_lower:
        return "Validation service temporarily unavailable"
    else:
        return "Address validation failed - please verify manually"


# Pipeline-specific helper functions
def validate_address_for_pipeline(fields: Dict[str, Any]) -> Tuple[Dict[str, Any], ValidationState]:
    """
    Special function for pipeline processing
    
    Returns:
    - Updated fields dictionary  
    - ValidationState indicating what happened: "verified", "can_be_verified", "no_house_number", "not_verified"
    """
    
    # Extract address components from fields
    address = fields.get('address', {}).get('value', '')
    city = fields.get('city', {}).get('value', '')
    state = fields.get('state', {}).get('value', '')
    zip_code = fields.get('zip_code', {}).get('value', '')
    
    log_debug("Pipeline address validation", {
        "address": address,
        "city": city, 
        "state": state,
        "zip_code": zip_code
    }, service="address_validation")
    
    # Run validation to get actual Google Maps response
    result = validate_address(address, city, state, zip_code)
    
    log_debug(f"Pipeline validation result: {result.state}", {
        "has_suggestion": bool(result.suggestion),
        "is_valid": result.is_valid,
        "error": result.error
    }, service="address_validation")
    
    # Store validation state and suggestion in address field data
    if 'address' in fields:
        fields['address']['validation_state'] = result.state
        if result.suggestion:
            fields['address']['validation_suggestion'] = result.suggestion

    # Handle each validation state appropriately for pipeline
    if result.state == "verified":
        # Perfect Google Maps match - update fields with verified data
        if result.suggestion:
            suggestion = result.suggestion
            
            if 'address' in fields:
                fields['address']['value'] = suggestion.get('address', address)
                fields['address']['requires_human_review'] = False
                fields['address']['review_notes'] = 'Verified by Google Maps during processing'
                fields['address']['source'] = 'google_maps_verified'  # Set source for verified addresses
                
            if 'city' in fields:
                fields['city']['value'] = suggestion.get('city', city)
                fields['city']['requires_human_review'] = False
                fields['city']['review_notes'] = 'Verified by Google Maps during processing'
                fields['city']['source'] = 'google_maps_verified'
                
            if 'state' in fields:
                fields['state']['value'] = suggestion.get('state', state)
                fields['state']['requires_human_review'] = False
                fields['state']['review_notes'] = 'Verified by Google Maps during processing'
                fields['state']['source'] = 'google_maps_verified'
                
            if 'zip_code' in fields:
                fields['zip_code']['value'] = suggestion.get('zip_code', zip_code)
                fields['zip_code']['requires_human_review'] = False
                fields['zip_code']['review_notes'] = 'Verified by Google Maps during processing'
                fields['zip_code']['source'] = 'google_maps_verified'
        
        log_debug("Pipeline: VERIFIED - Google Maps confirmed exact match", service="address_validation")
        return fields, "verified"
        
    elif result.state == "can_be_verified":
        # Google Maps has suggestions but not perfect match
        log_debug("Pipeline: CAN_BE_VERIFIED - Google Maps has suggestions", service="address_validation")
        
        # Mark for review so user can see suggestions
        if 'address' in fields:
            fields['address']['requires_human_review'] = True
            fields['address']['review_notes'] = 'Address can be improved with Google Maps suggestions'
        
        return fields, "can_be_verified"
        
    elif result.state == "no_house_number":
        # Missing house number
        log_debug("Pipeline: NO_HOUSE_NUMBER - Address missing street number", service="address_validation")
        
        if 'address' in fields:
            fields['address']['requires_human_review'] = True
            fields['address']['review_notes'] = 'Address missing house number'
            
        return fields, "no_house_number"
        
    else:  # not_verified
        # Google Maps couldn't validate at all
        log_debug("Pipeline: NOT_VERIFIED - Google Maps found no suggestions", service="address_validation")
        
        # Mark address fields for review if they're required
        for field_name in ['address', 'city', 'state', 'zip_code']:
            if field_name in fields:
                field_data = fields[field_name]
                if field_data.get('required', False):
                    if not field_data.get('value', '').strip():
                        field_data['requires_human_review'] = True
                        field_data['review_notes'] = f"Required {field_name} field is empty"
                    elif field_name == 'address':
                        field_data['requires_human_review'] = True
                        field_data['review_notes'] = 'Address could not be verified by Google Maps'
        
        return fields, "not_verified"


# Real-time API endpoint function  
def validate_address_realtime(
    address: str,
    city: str = "",
    state: str = "",
    zip_code: str = ""
) -> Dict[str, Any]:
    """
    Function for real-time API endpoints
    Returns standardized API response
    """
    
    result = validate_address(address, city, state, zip_code)
    
    # Convert to API response format
    response = {
        "success": True,
        "validation": result.to_dict()
    }
    
    log_debug("Real-time validation response", response, service="address_validation")
    
    return response
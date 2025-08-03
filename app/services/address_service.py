import json
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from app.services.document_service import validate_address_with_google, validate_zip_code
from app.core.clients import gmaps_client
from app.utils.retry_utils import log_debug

def validate_and_enhance_address(fields: Dict[str, Any]) -> Dict[str, Any]:
    """
    Post-processing address validation that enhances but never overwrites good data
    
    Args:
        fields: Field data after Gemini processing
        
    Returns:
        Enhanced field data with validated address components
    """
    log_debug("=== ADDRESS VALIDATION START ===", service="address")
    
    # Add unique session ID for tracking this specific validation run  
    import uuid
    session_id = str(uuid.uuid4())[:8]
    
    # Extract current address components
    address = fields.get('address', {}).get('value', '')
    city = fields.get('city', {}).get('value', '')
    state = fields.get('state', {}).get('value', '')
    zip_code = fields.get('zip_code', {}).get('value', '')
    
    log_debug("Current address components", {
        "address": address,
        "city": city,
        "state": state,
        "zip_code": zip_code
    }, service="address")
    
    # Check required fields first
    for field_name in ['address', 'city', 'state', 'zip_code']:
        if field_name in fields:
            field_data = fields[field_name]
            # Only mark required fields for review
            if field_data.get('required', False):
                if not field_data.get('value') or field_data.get('value', '').strip() == '':
                    field_data['requires_human_review'] = True
                    field_data['review_notes'] = f"Required {field_name} field is empty"
                    field_data['review_confidence'] = 0.3
                else:
                    # If field has a value, don't mark for review based on confidence
                    field_data['requires_human_review'] = False
                    field_data['review_notes'] = ""
            else:
                # Clear any review flags for non-required fields
                field_data['requires_human_review'] = False
                field_data['review_notes'] = ""
    
    # Check for obviously invalid addresses FIRST, regardless of zip code
    _check_for_invalid_addresses(fields)
    
    # If address was flagged as invalid, don't proceed with Google validation
    if fields.get('address', {}).get('requires_human_review', False):
        log_debug("Address was flagged as invalid, skipping Google validation", service="address")
        return fields
    
    # Try Google Maps validation if we have zip code OR if we have address+city+state (to auto-fill missing zip)
    if zip_code or (address and city and state):
        try:
            # First try zip code validation to get city and state (only if we have a zip code)
            zip_validation = None
            if zip_code:
                zip_validation = validate_zip_code(zip_code)
            if zip_validation:
                # Enhance city if missing or low confidence
                if 'city' in zip_validation and _should_enhance_field(fields.get('city', {}), zip_validation['city']):
                    log_debug(f"Enhancing city: '{city}' -> '{zip_validation['city']}'", service="address")
                    original_city = fields.get('city', {})
                    fields['city'] = _create_enhanced_field(
                        zip_validation['city'],
                        "zip_validation",
                        "City validated from zip code",
                        preserve_field_requirements=original_city
                    )
                    # Clear review flag since we validated it
                    fields['city']['requires_human_review'] = False
                    fields['city']['review_notes'] = ""
                
                # Enhance state if missing or low confidence
                if 'state' in zip_validation and _should_enhance_field(fields.get('state', {}), zip_validation['state']):
                    log_debug(f"Enhancing state: '{state}' -> '{zip_validation['state']}'", service="address")
                    original_state = fields.get('state', {})
                    fields['state'] = _create_enhanced_field(
                        zip_validation['state'],
                        "zip_validation",
                        "State validated from zip code",
                        preserve_field_requirements=original_state
                    )
                    # Clear review flag since we validated it
                    fields['state']['requires_human_review'] = False
                    fields['state']['review_notes'] = ""
            
            # Then try full address validation
            validated_address = validate_address_with_google(
                address,
                city or (zip_validation.get('city', '') if zip_validation else ''),
                state or (zip_validation.get('state', '') if zip_validation else ''),
                zip_code
            )
            
            # Check if we got a valid street address (not just area info)
            has_street_address = (validated_address and 
                                ('street_address' in validated_address or 
                                 ('street_number' in validated_address and 'street_name' in validated_address)))
            
            if has_street_address and _should_enhance_field(fields.get('address', {}), validated_address):
                log_debug(f"Enhancing address: '{address}' -> '{validated_address}'", service="address")
                fields['address'] = _create_enhanced_field(
                    validated_address,
                    "address_validation",
                    "Address validated from Google Maps"
                )
                # Clear review flag since we validated it
                fields['address']['requires_human_review'] = False
                fields['address']['review_notes'] = ""
                
                # Sync corrected components (city, state, zip) from Google Maps back to individual fields
                _sync_corrected_components(fields, validated_address, city, state, zip_code)
                
                # If zip code was missing but Google Maps found one, update the zip_code field
                if not zip_code and 'zip' in validated_address and validated_address['zip']:
                    log_debug(f"Auto-filling missing zip code: {validated_address['zip']}", service="address")
                    original_zip_field = fields.get('zip_code', {})
                    fields['zip_code'] = _create_enhanced_field(
                        validated_address['zip'],
                        "google_maps_autofill",
                        f"ZIP code auto-filled by Google Maps: {validated_address['zip']}",
                        preserve_field_requirements=original_zip_field
                    )
                    # Clear review flag since we auto-filled it
                    fields['zip_code']['requires_human_review'] = False
                    fields['zip_code']['review_notes'] = ""
            elif address:
                # We have an address but Google Maps couldn't validate it
                log_debug(f"Address '{address}' could not be validated by Google Maps", service="address")
                
                # Try smart address validation as a fallback only if we have a zip code
                if zip_code:
                    smart_result = _try_smart_address_validation(
                        address, 
                        city or (zip_validation.get('city', '') if zip_validation else ''),
                        state or (zip_validation.get('state', '') if zip_validation else ''),
                        zip_code,
                        fields
                    )
                    
                    if not smart_result and 'address' in fields and fields['address'].get('required', False):
                        fields['address']['requires_human_review'] = True
                        fields['address']['review_notes'] = "Required address field could not be validated by Google Maps or smart validation"
                        fields['address']['review_confidence'] = 0.3
                else:
                    # No zip code and address validation failed - flag for review
                    if 'address' in fields and fields['address'].get('required', False):
                        fields['address']['requires_human_review'] = True
                        fields['address']['review_notes'] = f"Address could not be validated - please verify '{address}' in '{city}', {state}"
                        fields['address']['review_confidence'] = 0.3
                        log_debug(f"Address flagged for review: no zip code and validation failed", service="address")
        except Exception as e:
            log_debug(f"Google Maps validation failed: {str(e)}", service="address")
            
            # Try smart address validation as a fallback if we have an address
            if address:
                smart_result = _try_smart_address_validation(
                    address,
                    city or (zip_validation.get('city', '') if 'zip_validation' in locals() and zip_validation else ''),
                    state or (zip_validation.get('state', '') if 'zip_validation' in locals() and zip_validation else ''),
                    zip_code,
                    fields
                )
                
                if not smart_result and 'address' in fields and fields['address'].get('required', False):
                    fields['address']['requires_human_review'] = True
                    fields['address']['review_notes'] = "Required address field could not be validated by Google Maps or smart validation"
                    fields['address']['review_confidence'] = 0.3
            else:
                # If validation failed and address is required, mark it for review
                if 'address' in fields and fields['address'].get('required', False):
                    fields['address']['requires_human_review'] = True
                    fields['address']['review_notes'] = "Required address field could not be validated by Google Maps"
                    fields['address']['review_confidence'] = 0.3
            
            _mark_address_fields_for_review_if_missing(fields)
            # Also check for obviously invalid addresses
            _check_for_invalid_addresses(fields)
    else:
        log_debug("No valid zip code for validation", service="address")
        _mark_address_fields_for_review_if_missing(fields)
        # Also check for obviously invalid addresses
        _check_for_invalid_addresses(fields)
    
    log_debug("=== ADDRESS VALIDATION COMPLETE ===", service="address")
    return fields


# Removed problematic smart Google queries approach
# Now using conservative validation: require valid city OR zip code

def _should_enhance_field(current_field: Dict[str, Any], new_value: str) -> bool:
    """
    Determine if we should enhance a field with a new value
    
    Args:
        current_field: Current field data
        new_value: New value from validation
        
    Returns:
        True if we should enhance the field
    """
    if not new_value:
        return False
        
    current_value = current_field.get('value', '')
    current_confidence = current_field.get('confidence', 0.0)
    current_review_confidence = current_field.get('review_confidence', 0.0)
    
    # Use the higher confidence score
    effective_confidence = max(current_confidence, current_review_confidence)
    
    # Enhance if field is empty
    if not current_value or current_value.strip() == "":
        return True
        
    # Enhance if field has low confidence
    if effective_confidence < 0.8:
        return True
        
    # Don't enhance if we have good data
    return False

def _sync_corrected_components(fields: Dict[str, Any], validated_address: Dict[str, Any], 
                               original_city: str, original_state: str, original_zip: str) -> None:
    """
    Sync corrected address components from Google Maps back to individual fields.
    This ensures consistency when Google Maps corrects typos in city, state, or ZIP.
    
    Args:
        fields: The fields dictionary to update
        validated_address: Google Maps validation result containing corrected components
        original_city: Original city value before validation
        original_state: Original state value before validation  
        original_zip: Original ZIP value before validation
    """
    log_debug("Syncing corrected components from Google Maps", {
        "original": {"city": original_city, "state": original_state, "zip": original_zip},
        "corrected": {
            "city": validated_address.get('city'),
            "state": validated_address.get('state'), 
            "zip": validated_address.get('zip')
        }
    }, service="address")
    
    # Sync corrected city if Google Maps provided one and it's different from current field value
    if 'city' in validated_address and validated_address['city']:
        corrected_city = validated_address['city']
        current_city = fields.get('city', {}).get('value', '')
        if corrected_city != current_city:
            log_debug(f"Syncing corrected city: '{current_city}' -> '{corrected_city}' (was originally '{original_city}')", service="address")
            original_city_field = fields.get('city', {})
            fields['city'] = _create_enhanced_field(
                corrected_city,
                "google_maps_correction",
                f"City corrected by Google Maps to '{corrected_city}'",
                preserve_field_requirements=original_city_field
            )
    
    # Sync corrected state if Google Maps provided one and it's different from current field value
    if 'state' in validated_address and validated_address['state']:
        corrected_state = validated_address['state']
        current_state = fields.get('state', {}).get('value', '')
        if corrected_state != current_state:
            log_debug(f"Syncing corrected state: '{current_state}' -> '{corrected_state}' (was originally '{original_state}')", service="address")
            original_state_field = fields.get('state', {})
            fields['state'] = _create_enhanced_field(
                corrected_state,
                "google_maps_correction",
                f"State corrected by Google Maps to '{corrected_state}'",
                preserve_field_requirements=original_state_field
            )
    
    # Sync corrected ZIP if Google Maps provided one and it's different from current field value
    if 'zip' in validated_address and validated_address['zip']:
        corrected_zip = validated_address['zip']
        current_zip = fields.get('zip_code', {}).get('value', '')
        if corrected_zip != current_zip:
            log_debug(f"Syncing corrected ZIP: '{current_zip}' -> '{corrected_zip}' (was originally '{original_zip}')", service="address")
            original_zip_field = fields.get('zip_code', {})
            fields['zip_code'] = _create_enhanced_field(
                corrected_zip,
                "google_maps_correction",
                f"ZIP code corrected by Google Maps to '{corrected_zip}'",
                preserve_field_requirements=original_zip_field
            )

def _create_enhanced_field(value: str, source: str, notes: str, preserve_field_requirements: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Create a field with enhanced data
    
    Args:
        value: The enhanced value
        source: Where the enhancement came from
        notes: Notes about the enhancement
        preserve_field_requirements: Original field data to preserve enabled/required status
        
    Returns:
        Enhanced field data
    """
    enhanced_field = {
        'value': value,
        'confidence': 0.95,  # High confidence for validated data
        'source': source,
        'notes': notes,
        'requires_human_review': False,
        'review_notes': ""
    }
    
    # Preserve enabled and required status from original field
    if preserve_field_requirements:
        if 'enabled' in preserve_field_requirements:
            enhanced_field['enabled'] = preserve_field_requirements['enabled']
        if 'required' in preserve_field_requirements:
            enhanced_field['required'] = preserve_field_requirements['required']
    
    return enhanced_field

def _mark_address_fields_for_review_if_missing(fields: Dict[str, Any]) -> None:
    """
    Mark address-related fields for review if they're missing and required
    
    Args:
        fields: Field data to check and update
    """
    address_fields = ['address', 'city', 'state', 'zip_code']
    
    for field_name in address_fields:
        if field_name not in fields:
            continue
            
        field_data = fields[field_name]
        field_value = field_data.get('value', '')
        is_required = field_data.get('required', False)
        
        # Only mark for review if required and empty
        if is_required and (not field_value or field_value.strip() == ""):
            field_data['requires_human_review'] = True
            field_data['review_notes'] = f"Required {field_name} field could not be validated"
            log_debug(f"Marked {field_name} for review: required but missing", service="address")

def _check_for_invalid_addresses(fields: Dict[str, Any]) -> None:
    """
    Check for obviously invalid street addresses that should be flagged for review
    
    Args:
        fields: Field data to check and update
    """
    if 'address' not in fields:
        log_debug("No address field found", service="address")
        return
        
    address_field = fields['address']
    
    # Handle case where address_field is None
    if address_field is None:
        log_debug("Address field is None", service="address")
        return
        
    # Get the address value and handle None case
    raw_address_value = address_field.get('value', '')
    if raw_address_value is None:
        log_debug("Address value is None", service="address")
        return
        
    address_value = raw_address_value.strip()
    address_lower = address_value.lower()
    
    log_debug(f"Checking address for invalid patterns: '{address_value}'", service="address")
    
    # Common patterns that indicate invalid addresses
    invalid_patterns = [
        'n/a', 'na', 'none', 'unknown', 'null', 'nil',
        'see above', 'same as above', 'ditto',
        '123 main st', '123 main street',  # Generic placeholder addresses
        'test', 'testing', 'example'
    ]
    
    # Check if address contains invalid patterns
    for pattern in invalid_patterns:
        if pattern in address_lower:
            address_field['requires_human_review'] = True
            address_field['review_notes'] = f"Address appears to be placeholder or invalid: '{address_value}'"
            address_field['review_confidence'] = 0.2
            log_debug(f"Address flagged for invalid pattern '{pattern}': {address_value}", service="address")
            return
    
    # Check for incomplete addresses missing street numbers
    import re
    
    # Look for street number at the beginning OR end of the address
    # Street number patterns: digits (possibly followed by letter like 123A)
    street_number_start = r'^\s*\d+[A-Za-z]?\s+'  # Number at start: "1234 Main St"
    street_number_end = r'\s+\d+[A-Za-z]?\s*$'    # Number at end: "Main St 1234"
    
    has_street_number = (re.search(street_number_start, address_value) or 
                        re.search(street_number_end, address_value))
    
    if not has_street_number:
        # No street number found anywhere - this is likely an incomplete address
        address_field['requires_human_review'] = True
        address_field['review_notes'] = f"Address appears incomplete - missing street number: '{address_value}'"
        address_field['review_confidence'] = 0.3
        log_debug(f"Address flagged: missing street number - '{address_value}'", service="address")
        return
    else:
        log_debug(f"Address passed: has street number - '{address_value}'", service="address")
    
    # Additional check for very short addresses that are likely incomplete
    if len(address_value.strip()) < 5:
        address_field['requires_human_review'] = True
        address_field['review_notes'] = f"Address too short or incomplete: '{address_value}'"
        address_field['review_confidence'] = 0.2
        log_debug(f"Address flagged for being too short: {address_value}", service="address")
        return

def validate_address_with_google_maps(address: str, city: str, state: str, zip_code: str):
    if not gmaps_client:
        log_debug("Google Maps client not initialized", service="address")
        return None

    # Allow validation without zip code - Google Maps can find it
    if not zip_code:
        log_debug("No zip code provided - will try to get it from Google Maps", service="address")
    
    # Construct full address string for validation  
    if zip_code:
        full_address_query = f"{address}, {city}, {state} {zip_code}"
    else:
        full_address_query = f"{address}, {city}, {state}"
    log_debug(f"Validating via Google Maps (Primary): {full_address_query}", service="address")

    try:
        # Use geocoding to validate the address
        geocode_result = gmaps_client.geocode(full_address_query)
        
        if geocode_result:
            # Extract the first result
            result = geocode_result[0]
            formatted_address = result.get('formatted_address', '')
            geometry = result.get('geometry', {})
            location = geometry.get('location', {})
            components = result.get('address_components', [])
            
            # Extract components including zip code if not provided
            extracted_data = {}
            for component in components:
                types = component.get('types', [])
                if 'postal_code' in types:
                    extracted_data['zip'] = component['long_name']
                elif 'locality' in types:
                    extracted_data['city'] = component['long_name']
                elif 'administrative_area_level_1' in types:
                    extracted_data['state'] = component['short_name']
                elif 'street_number' in types:
                    extracted_data['street_number'] = component['long_name']
                elif 'route' in types:
                    extracted_data['street_name'] = component['long_name']
            
            log_debug("Google Maps validation successful", {
                "original_query": full_address_query,
                "formatted_address": formatted_address,
                "lat": location.get('lat'),
                "lng": location.get('lng'),
                "extracted_components": extracted_data
            }, service="address")
            
            return {
                "is_valid": True,
                "formatted_address": formatted_address,
                "latitude": location.get('lat'),
                "longitude": location.get('lng'),
                "place_id": result.get('place_id'),
                "confidence": "high",  # Google Maps geocoding generally has high confidence
                **extracted_data  # Include extracted components like zip code
            }
        else:
            log_debug("Google Maps found no results for address", {"query": full_address_query}, service="address")
            return {
                "is_valid": False,
                "error": "Address not found in Google Maps",
                "confidence": "low"
            }
            
    except Exception as e:
        log_debug(f"Google Maps validation error: {str(e)}", {"query": full_address_query}, service="address")
        return {
            "is_valid": False,
            "error": f"Google Maps API error: {str(e)}",
            "confidence": "unknown"
        }


def _try_smart_address_validation(address: str, city: str, state: str, zip_code: str, fields: Dict[str, Any]) -> bool:
    """
    Try smart address validation as a fallback when regular validation fails
    
    Args:
        address: Street address to validate
        city: City name
        state: State abbreviation
        zip_code: ZIP code
        fields: Field data dictionary to update
        
    Returns:
        True if smart validation succeeded and updated the fields, False otherwise
    """
    try:
        # Import the smart validation function
        from app.services.smart_address_service import smart_address_validation
        
        log_debug("Attempting smart address validation", {
            "address": address,
            "city": city,
            "state": state,
            "zip_code": zip_code
        }, service="address")
        
        # Run smart validation
        smart_result = smart_address_validation(address, city, state, zip_code)
        
        if smart_result.get('is_valid') and smart_result.get('correction_made'):
            # Smart validation found a correction
            corrected_address = smart_result.get('corrected_address')
            confidence = smart_result.get('confidence')
            auto_correct = smart_result.get('auto_correct', False)
            similarity_score = smart_result.get('similarity_score', 0)
            
            log_debug("Smart validation successful", {
                "original": address,
                "corrected": corrected_address,
                "confidence": confidence,
                "auto_correct": auto_correct,
                "similarity_score": similarity_score
            }, service="address")
            
            # Update the address field
            if 'address' in fields:
                fields['address']['value'] = corrected_address
                fields['address']['source'] = "smart_validation"
                fields['address']['notes'] = f"Smart corrected from '{address}' (confidence: {confidence})"
                
                if auto_correct:
                    # High confidence - auto-correct without review
                    fields['address']['requires_human_review'] = False
                    fields['address']['review_notes'] = f"Auto-corrected: {address} → {corrected_address}"
                    fields['address']['review_confidence'] = similarity_score
                else:
                    # Medium confidence - suggest correction for review
                    fields['address']['requires_human_review'] = True
                    fields['address']['review_notes'] = f"Suggested correction: {address} → {corrected_address} (confidence: {confidence})"
                    fields['address']['review_confidence'] = similarity_score
                    
                    # Store the suggestion for the UI
                    fields['address']['suggested_value'] = corrected_address
                    fields['address']['suggestion_confidence'] = confidence
            
            # Handle corrected ZIP code if smart validation found one
            if 'corrected_zip' in smart_result and smart_result['corrected_zip']:
                corrected_zip = smart_result['corrected_zip']
                original_zip_field = fields.get('zip_code', {})
                
                log_debug(f"Smart validation found correct ZIP: '{zip_code}' -> '{corrected_zip}'", service="address")
                
                fields['zip_code'] = _create_enhanced_field(
                    corrected_zip,
                    "smart_validation_zip_correction",
                    f"ZIP code corrected by smart validation from '{zip_code}' to '{corrected_zip}'",
                    preserve_field_requirements=original_zip_field
                )
            
            # Handle corrected city if smart validation found one
            if 'corrected_city' in smart_result and smart_result['corrected_city']:
                corrected_city = smart_result['corrected_city']
                current_city = fields.get('city', {}).get('value', '')
                
                if corrected_city != current_city:
                    log_debug(f"Smart validation found correct city: '{current_city}' -> '{corrected_city}'", service="address")
                    original_city_field = fields.get('city', {})
                    
                    fields['city'] = _create_enhanced_field(
                        corrected_city,
                        "smart_validation_city_correction",
                        f"City corrected by smart validation to '{corrected_city}'",
                        preserve_field_requirements=original_city_field
                    )
            
            # Handle corrected state if smart validation found one
            if 'corrected_state' in smart_result and smart_result['corrected_state']:
                corrected_state = smart_result['corrected_state']
                current_state = fields.get('state', {}).get('value', '')
                
                if corrected_state != current_state:
                    log_debug(f"Smart validation found correct state: '{current_state}' -> '{corrected_state}'", service="address")
                    original_state_field = fields.get('state', {})
                    
                    fields['state'] = _create_enhanced_field(
                        corrected_state,
                        "smart_validation_state_correction",
                        f"State corrected by smart validation to '{corrected_state}'",
                        preserve_field_requirements=original_state_field
                    )
            
            return True
            
        elif smart_result.get('is_valid') and not smart_result.get('correction_made'):
            # Smart validation confirmed the address is valid (exact match found)
            log_debug("Smart validation confirmed address is valid", {"address": address}, service="address")
            
            if 'address' in fields:
                fields['address']['requires_human_review'] = False
                fields['address']['review_notes'] = "Address confirmed valid by smart validation"
                fields['address']['source'] = "smart_validation"
            
            return True
            
        else:
            # Smart validation also failed
            log_debug("Smart validation failed", {
                "address": address,
                "error": smart_result.get('error', 'Unknown error'),
                "method": smart_result.get('method', 'unknown')
            }, service="address")
            
            return False
            
    except Exception as e:
        log_debug(f"Smart address validation failed with exception: {e}", service="address")
        return False 
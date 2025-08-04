import json
import traceback
from typing import Dict, Any, Optional
from app.core.clients import gmaps_client
from app.utils.retry_utils import log_debug

# --- Address Validation ---
def validate_address_with_google(address_str: str, city: str = '', state: str = '', zip_code: str = ''):
    """
    Validate an address using Google Maps Places API
    Enhanced version with zip-based validation
    """
    if not gmaps_client:
        log_debug("Google Maps client not initialized", service="document")
        return None
    
    # Allow validation without zip code - Google Maps can find it
    if not zip_code:
        log_debug("No zip code provided - will try to get it from Google Maps", service="document")
    
    try:
        # Enhanced address validation 
        full_address_query = f"{address_str}"
        if city:
            full_address_query += f", {city}"
        if state:
            full_address_query += f", {state}"
        if zip_code:
            full_address_query += f", {zip_code}"
        
        log_debug(f"Validating via Google Maps (Primary): {full_address_query}", service="document")
        
        # Geocoding to get precise coordinates and components
        geocoding_result = gmaps_client.geocode(full_address_query)
        
        if geocoding_result:
            place = geocoding_result[0]
            formatted_address = place.get('formatted_address', '')
            geometry = place.get('geometry', {})
            location = geometry.get('location', {})
            components = place.get('address_components', [])
            
            # Extract components for better validation
            extracted_data = {}
            for component in components:
                types = component.get('types', [])
                if 'locality' in types:
                    extracted_data['city'] = component['long_name']
                elif 'administrative_area_level_1' in types:
                    extracted_data['state'] = component['short_name']
                elif 'postal_code' in types:
                    extracted_data['zip'] = component['long_name']
                elif 'street_number' in types:
                    extracted_data['street_number'] = component['long_name']
                elif 'route' in types:
                    extracted_data['street_name'] = component['long_name']
            
            # Combine street number and name for full street address
            if 'street_number' in extracted_data and 'street_name' in extracted_data:
                extracted_data['street_address'] = f"{extracted_data['street_number']} {extracted_data['street_name']}"
            
            log_debug("Google Maps validation successful", {
                "formatted_address": formatted_address,
                "extracted_components": extracted_data,
                "coordinates": location
            }, service="document")
            
            return {
                "formatted_address": formatted_address,
                "latitude": location.get('lat'),
                "longitude": location.get('lng'),
                **extracted_data
            }
        else:
            log_debug("Google Maps returned no results", {"query": full_address_query}, service="document")
            return None
            
    except Exception as e:
        log_debug(f"Google Maps validation error: {str(e)}", {"query": full_address_query}, service="document")
        return None

def validate_zip_code(zip_code: str):
    """
    Validate a zip code using Google Maps Geocoding API
    Returns city and state if valid
    """
    if not gmaps_client:
        log_debug("Google Maps client not initialized", service="document")
        return None
        
    if not zip_code or len(zip_code.strip()) < 5:
        log_debug("Invalid zip code format", {"zip_code": zip_code}, service="document")
        return None
    
    try:
        log_debug(f"Validating zip code: {zip_code}", service="document")
        
        # Geocode the zip code
        geocoding_result = gmaps_client.geocode(zip_code)
        
        if geocoding_result:
            place = geocoding_result[0]
            components = place.get('address_components', [])
            
            extracted_data = {}
            for component in components:
                types = component.get('types', [])
                if 'locality' in types:
                    extracted_data['city'] = component['long_name']
                elif 'administrative_area_level_1' in types:
                    extracted_data['state'] = component['short_name']
                elif 'postal_code' in types:
                    extracted_data['zip'] = component['long_name']
            
            log_debug("Zip code validation successful", extracted_data, service="document")
            return extracted_data
        else:
            log_debug("Google Maps found no results for zip code", {"zip_code": zip_code}, service="document")
            return None
            
    except Exception as e:
        log_debug(f"Zip code validation error: {str(e)}", {"zip_code": zip_code}, service="document")
        return None

def validate_address_components(address: Optional[str], city: Optional[str], state: Optional[str], zip_code: Optional[str]) -> Dict[str, Any]:
    if not gmaps_client:
        return {
            "validated": {},
            "confidence": 0.30,
            "requires_review": True,
            "review_notes": "Google Maps client not available",
            "auto_filled": []
        }
    
    auto_filled = []
    validated_data = {
        "street_address": "",
        "city": "",
        "state": "",
        "zip": ""
    }
    
    try:
        # First try zip code validation if available
        if zip_code and len(zip_code.strip()) >= 5:
            log_debug(f"Validating via zip code: {zip_code}", service="document")
            zip_validation = validate_zip_code(zip_code)
            log_debug(f"Zip validation response: {json.dumps(zip_validation, indent=2)}", service="document")
            
            if zip_validation:
                if not city and zip_validation.get('city'):
                    validated_data['city'] = zip_validation['city']
                    auto_filled.append('city')
                if not state and zip_validation.get('state'):
                    validated_data['state'] = zip_validation['state']
                    auto_filled.append('state')
        
        # Then try full address validation if we have an address
        if address:
            log_debug(f"Validating full address: {address}", service="document")
            location_context = f"{city or validated_data['city']}, {state or validated_data['state']} {zip_code}".strip()
            
            full_validation = validate_address_with_google(address, city, state, zip_code)
            if not full_validation and location_context:
                log_debug(f"Primary validation failed, trying with context: {location_context}", service="document")
                full_validation = validate_address_with_google(address, location_context)
            
            if full_validation and full_validation.get('street_address'):
                validated_data['street_address'] = full_validation['street_address']
                log_debug(f"Full address validated: {full_validation['street_address']}", service="document")
            else:
                validated_data['street_address'] = address
                log_debug(f"Could not verify street address, preserving original: {address}", service="document")
        
        # Fill in any missing data
        validated_data['city'] = validated_data['city'] or city or ""
        validated_data['state'] = validated_data['state'] or state or ""
        validated_data['zip'] = zip_code or ""
        
        # Calculate confidence based on validation success
        confidence = 0.50  # Base confidence
        if zip_validation:
            confidence += 0.20
        if full_validation:
            confidence += 0.20
        
        requires_review = confidence < 0.70 or not all([
            validated_data['street_address'],
            validated_data['city'], 
            validated_data['state'],
            validated_data['zip']
        ])
        
        review_notes = []
        if not validated_data['street_address']:
            review_notes.append("Street address missing")
        if not validated_data['city']:
            review_notes.append("City missing")
        if not validated_data['state']:
            review_notes.append("State missing")
        if not validated_data['zip']:
            review_notes.append("Zip code missing")
        
        return {
            "validated": validated_data,
            "confidence": min(confidence, 0.95),
            "requires_review": requires_review,
            "review_notes": "; ".join(review_notes) if review_notes else "Address validation complete",
            "auto_filled": auto_filled
        }
        
    except Exception as e:
        log_debug(f"Address validation error: {str(e)}", service="document")
        return {
            "validated": {
                "street_address": address or "",
                "city": city or "",
                "state": state or "",
                "zip": zip_code or ""
            },
            "confidence": 0.30,
            "requires_review": True,
            "review_notes": f"Validation error: {str(e)}",
            "auto_filled": []
        }

def apply_field_requirements_to_document(fields: dict, requirements: dict) -> dict:
    """
    Apply field requirements from school settings to document fields
    """
    log_debug("Applying field requirements to document", {
        "fields_count": len(fields),
        "requirements_count": len(requirements)
    }, service="document")
    
    # Update existing fields with requirements
    for field_name, field_data in fields.items():
        if field_name in requirements:
            field_settings = requirements[field_name]
            field_data["enabled"] = field_settings.get("enabled", True)
            field_data["required"] = field_settings.get("required", False)
        else:
            # Default settings for fields not in requirements
            field_data["enabled"] = True
            field_data["required"] = False
    
    # Add missing required fields that weren't detected
    for field_name, field_settings in requirements.items():
        if field_settings.get("required", False) and field_name not in fields:
            log_debug(f"Adding missing required field: {field_name}", service="document")
            fields[field_name] = {
                "value": "",
                "confidence": 0.0,
                "bounding_box": [],
                "source": "missing_required",
                "enabled": field_settings.get("enabled", True),
                "required": True,
                "requires_human_review": True,
                "review_notes": "Required field not detected",
                "review_confidence": 0.0
            }
    
    log_debug("Field requirements applied successfully", {"final_fields_count": len(fields)}, service="document")
    return fields 
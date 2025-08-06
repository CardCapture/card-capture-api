"""
Address Suggestions Service for Real-time Validation
Provides multiple suggestions ranked by confidence and completeness
"""

from typing import List, Dict, Any, Optional
from app.models.address_suggestions import AddressSuggestionsRequest, AddressSuggestion, AddressSuggestionsResponse
from app.services.document_service import validate_address_with_google, validate_zip_code
from app.utils.retry_utils import log_debug


async def get_address_suggestions(request: AddressSuggestionsRequest) -> AddressSuggestionsResponse:
    """
    Generate multiple address suggestions using different validation strategies
    
    Args:
        request: Address fields to validate
        
    Returns:
        Response with ranked suggestions
    """
    log_debug("=== ADDRESS SUGGESTIONS START ===", {
        "input": request.dict()
    }, service="address_suggestions")
    
    try:
        suggestions = []
        
        # Check for missing street number before attempting any validation
        if (request.address and request.address.strip() and 
            request.state and request.state.strip() and
            ((request.city and request.city.strip()) or (request.zip_code and request.zip_code.strip())) and
            not _has_street_number(request.address)):
            
            # Return helpful error message for missing street number
            log_debug("Address missing street number, returning helpful error", {
                "address": request.address
            }, service="address_suggestions")
            
            return AddressSuggestionsResponse(
                success=False,
                has_suggestions=False,
                suggestions=[],
                original_input=request.dict(),
                validation_attempted=True,
                error="Please add a house number to validate the address"
            )
        
        # Strategy 1: Direct Google Maps validation (highest priority)
        if _has_sufficient_info_for_google(request):
            google_suggestion = await _validate_with_google_maps_strategy(request)
            if google_suggestion:
                suggestions.append(google_suggestion)
                log_debug("Google Maps suggestion found", {"suggestion": google_suggestion.dict()}, service="address_suggestions")
        
        # Strategy 2: ZIP-based validation (if ZIP provided and different from Google result)
        if request.zip_code and request.zip_code.strip():
            zip_suggestion = await _validate_with_zip_strategy(request)
            if zip_suggestion and not _is_duplicate_suggestion(zip_suggestion, suggestions):
                suggestions.append(zip_suggestion)
                log_debug("ZIP-based suggestion found", {"suggestion": zip_suggestion.dict()}, service="address_suggestions")
        
        # Strategy 3: Smart address correction (if no ZIP and Google failed)
        if not request.zip_code and len(suggestions) == 0 and request.address and request.state:
            smart_suggestions = await _smart_address_correction_strategy(request)
            suggestions.extend(smart_suggestions)
            log_debug(f"Smart correction found {len(smart_suggestions)} suggestions", service="address_suggestions")
        
        # Rank suggestions by confidence and completeness
        ranked_suggestions = _rank_suggestions(suggestions, request)
        
        # Limit to top 3 suggestions
        final_suggestions = ranked_suggestions[:3]
        
        log_debug("=== ADDRESS SUGGESTIONS COMPLETE ===", {
            "total_found": len(suggestions),
            "final_count": len(final_suggestions),
            "has_suggestions": len(final_suggestions) > 0
        }, service="address_suggestions")
        
        return AddressSuggestionsResponse(
            success=True,
            has_suggestions=len(final_suggestions) > 0,
            suggestions=final_suggestions,
            original_input=request.dict(),
            validation_attempted=True
        )
        
    except Exception as e:
        log_debug(f"Address suggestions failed: {str(e)}", service="address_suggestions")
        return AddressSuggestionsResponse(
            success=False,
            has_suggestions=False,
            suggestions=[],
            original_input=request.dict(),
            validation_attempted=True,
            error=str(e)
        )


def _has_street_number(address: str) -> bool:
    """Check if address contains a street number"""
    if not address or not address.strip():
        return False
    
    import re
    # Look for numbers at the beginning of the address
    # This regex matches: 
    # - One or more digits at the start (optionally followed by letter like 123A)
    # - Optionally followed by a dash or space and more digits (like 123-45 or 123 1/2)
    street_number_pattern = r'^\s*\d+[A-Za-z]?(\s*[-/]\s*\d+)*\s+'
    
    has_number = bool(re.match(street_number_pattern, address.strip()))
    
    log_debug("Checking for street number in address", {
        "address": address,
        "has_street_number": has_number
    }, service="address_suggestions")
    
    return has_number


def _has_sufficient_info_for_google(request: AddressSuggestionsRequest) -> bool:
    """Check if we have enough information for Google Maps validation"""
    has_address = bool(request.address and request.address.strip())
    has_state = bool(request.state and request.state.strip())
    has_location_context = bool(request.city and request.city.strip()) or bool(request.zip_code and request.zip_code.strip())
    has_street_number = _has_street_number(request.address or "")
    
    sufficient = has_address and has_state and has_location_context and has_street_number
    
    log_debug("Checking sufficiency for Google validation", {
        "has_address": has_address,
        "has_state": has_state, 
        "has_location_context": has_location_context,
        "has_street_number": has_street_number,
        "sufficient": sufficient
    }, service="address_suggestions")
    
    return sufficient


async def _validate_with_google_maps_strategy(request: AddressSuggestionsRequest) -> Optional[AddressSuggestion]:
    """Validate using Google Maps API"""
    try:
        # Build full address query
        query_parts = [request.address]
        if request.city:
            query_parts.append(request.city)
        if request.state:
            query_parts.append(request.state)
        if request.zip_code:
            query_parts.append(request.zip_code)
        
        result = validate_address_with_google(
            request.address,
            request.city or "",
            request.state or "",
            request.zip_code or ""
        )
        
        if result and _is_complete_address_result(result):
            return _create_suggestion_from_google_result(result, request)
            
    except Exception as e:
        log_debug(f"Google Maps strategy failed: {str(e)}", service="address_suggestions")
    
    return None


async def _validate_with_zip_strategy(request: AddressSuggestionsRequest) -> Optional[AddressSuggestion]:
    """Validate using ZIP code lookup"""
    try:
        zip_result = validate_zip_code(request.zip_code)
        if not zip_result:
            return None
        
        # Try to validate the full address with ZIP-corrected city/state
        corrected_city = zip_result.get('city', request.city)
        corrected_state = zip_result.get('state', request.state)
        
        google_result = validate_address_with_google(
            request.address,
            corrected_city,
            corrected_state, 
            request.zip_code
        )
        
        if google_result and _is_complete_address_result(google_result):
            return _create_suggestion_from_google_result(google_result, request, source="zip_validation")
        else:
            # Don't create fallback suggestions if Google Maps can't validate the full address
            log_debug("Skipping ZIP suggestion - Google Maps could not validate complete address", {
                "address": request.address,
                "google_result": google_result
            }, service="address_suggestions")
            return None
            
    except Exception as e:
        log_debug(f"ZIP strategy failed: {str(e)}", service="address_suggestions")
    
    return None


async def _smart_address_correction_strategy(request: AddressSuggestionsRequest) -> List[AddressSuggestion]:
    """Try smart address corrections when other methods fail"""
    suggestions = []
    
    try:
        # Try common street suffixes if address seems incomplete
        if request.address and request.state:
            parts = request.address.split()
            if len(parts) >= 2 and parts[0].isdigit():
                house_num = parts[0]
                street_base = ' '.join(parts[1:])
                
                # Try common suffixes
                suffixes = ['Court', 'Ct', 'Drive', 'Dr', 'Street', 'St', 'Lane', 'Ln', 'Way', 'Place', 'Pl']
                
                for suffix in suffixes:
                    if suffix.lower() in street_base.lower():
                        continue  # Skip if suffix already present
                    
                    enhanced_address = f"{house_num} {street_base} {suffix}"
                    
                    result = validate_address_with_google(
                        enhanced_address,
                        request.city or "",
                        request.state,
                        ""
                    )
                    
                    if result and _is_complete_address_result(result):
                        suggestion = _create_suggestion_from_google_result(
                            result, 
                            request, 
                            source="smart_correction"
                        )
                        suggestions.append(suggestion)
                        
                        # Only return first successful match to avoid too many options
                        break
                        
    except Exception as e:
        log_debug(f"Smart correction strategy failed: {str(e)}", service="address_suggestions")
    
    return suggestions


def _is_complete_address_result(result: Dict[str, Any]) -> bool:
    """Check if Google Maps result contains a complete street address"""
    if not result:
        return False
    
    # Must have street components
    has_street_components = (
        result.get('street_number') and result.get('street_name')
    ) or result.get('street_address')
    
    # Must have location components  
    has_location = result.get('city') and result.get('state')
    
    # Formatted address should look complete
    formatted = result.get('formatted_address', '')
    has_good_format = (
        formatted and 
        any(char.isdigit() for char in formatted) and  # Has numbers
        ',' in formatted  # Has address structure
    )
    
    is_complete = has_street_components and has_location and has_good_format
    
    log_debug("Checking address completeness", {
        "has_street_components": has_street_components,
        "has_location": has_location,
        "has_good_format": has_good_format,
        "is_complete": is_complete,
        "formatted_address": formatted
    }, service="address_suggestions")
    
    return is_complete


def _create_suggestion_from_google_result(result: Dict[str, Any], original: AddressSuggestionsRequest, source: str = "google_maps") -> AddressSuggestion:
    """Create a suggestion from Google Maps validation result"""
    
    # Extract enhanced address
    enhanced_address = result.get('street_address', result.get('formatted_address', '').split(',')[0])
    enhanced_city = result.get('city', original.city)
    enhanced_state = result.get('state', original.state)
    enhanced_zip = result.get('zip', original.zip_code)
    
    # Determine what changed
    changes_made = []
    enhancement_notes = []
    
    if enhanced_address != original.address:
        changes_made.append("address")
        enhancement_notes.append(f"enhanced street address")
    
    if enhanced_city != original.city:
        changes_made.append("city")
        enhancement_notes.append(f"corrected city")
        
    if enhanced_state != original.state:
        changes_made.append("state")
        enhancement_notes.append(f"corrected state")
        
    if enhanced_zip != original.zip_code and enhanced_zip:
        changes_made.append("zip_code")
        enhancement_notes.append(f"auto-filled ZIP code")
    
    # Determine confidence
    confidence = "high" if source == "google_maps" else "medium"
    
    notes = " and ".join(enhancement_notes).capitalize() if enhancement_notes else "Verified address"
    
    return AddressSuggestion(
        formatted_address=result.get('formatted_address', f"{enhanced_address}, {enhanced_city}, {enhanced_state} {enhanced_zip}"),
        address=enhanced_address,
        city=enhanced_city,
        state=enhanced_state,
        zip_code=enhanced_zip,
        confidence=confidence,
        source=source,
        changes_made=changes_made,
        enhancement_notes=notes
    )


def _create_suggestion_from_zip_result(zip_result: Dict[str, Any], original: AddressSuggestionsRequest) -> AddressSuggestion:
    """Create a suggestion from ZIP validation result"""
    
    enhanced_city = zip_result.get('city', original.city)
    enhanced_state = zip_result.get('state', original.state)
    enhanced_zip = zip_result.get('zip', original.zip_code)
    
    changes_made = []
    enhancement_notes = []
    
    if enhanced_city != original.city:
        changes_made.append("city")
        enhancement_notes.append(f"corrected city from ZIP code")
        
    if enhanced_state != original.state:
        changes_made.append("state")
        enhancement_notes.append(f"corrected state from ZIP code")
    
    notes = " and ".join(enhancement_notes) if enhancement_notes else "Verified from ZIP code"
    
    return AddressSuggestion(
        formatted_address=f"{original.address}, {enhanced_city}, {enhanced_state} {enhanced_zip}",
        address=original.address,
        city=enhanced_city,
        state=enhanced_state,
        zip_code=enhanced_zip,
        confidence="medium",
        source="zip_validation",
        changes_made=changes_made,
        enhancement_notes=notes
    )


def _is_duplicate_suggestion(new_suggestion: AddressSuggestion, existing_suggestions: List[AddressSuggestion]) -> bool:
    """Check if a suggestion is substantially the same as an existing one"""
    for existing in existing_suggestions:
        if (new_suggestion.formatted_address == existing.formatted_address or
            (new_suggestion.address == existing.address and 
             new_suggestion.city == existing.city and
             new_suggestion.zip_code == existing.zip_code)):
            return True
    return False


def _rank_suggestions(suggestions: List[AddressSuggestion], original: AddressSuggestionsRequest) -> List[AddressSuggestion]:
    """Rank suggestions by confidence, completeness, and relevance"""
    
    def suggestion_score(suggestion: AddressSuggestion) -> float:
        score = 0.0
        
        # Confidence scoring
        confidence_scores = {"high": 3.0, "medium": 2.0, "low": 1.0}
        score += confidence_scores.get(suggestion.confidence, 0.0)
        
        # Source scoring (Google Maps is most reliable)
        source_scores = {"google_maps": 2.0, "zip_validation": 1.5, "smart_correction": 1.0}
        score += source_scores.get(suggestion.source, 0.0)
        
        # Completeness scoring
        if suggestion.zip_code:
            score += 1.0
        if suggestion.address and any(char.isdigit() for char in suggestion.address):
            score += 1.0
        if len(suggestion.changes_made) > 0:  # Actual improvements made
            score += 0.5
            
        # Prefer fewer but meaningful changes
        if len(suggestion.changes_made) <= 2:
            score += 0.5
        
        return score
    
    ranked = sorted(suggestions, key=suggestion_score, reverse=True)
    
    log_debug("Ranked suggestions", {
        "original_count": len(suggestions),
        "ranked_scores": [suggestion_score(s) for s in ranked]
    }, service="address_suggestions")
    
    return ranked
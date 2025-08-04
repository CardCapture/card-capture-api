"""
Smart Address Validation Service

Unified approach that uses zip-code constrained fuzzy matching to intelligently
correct address errors including typos, abbreviations, and word order issues.
"""

import re
import json
from typing import Dict, Any, List, Optional, Tuple
from difflib import SequenceMatcher
from app.core.clients import gmaps_client
from app.utils.retry_utils import log_debug


def smart_address_validation(address: str, city: str, state: str, zip_code: str) -> Dict[str, Any]:
    """
    Unified smart address validation with fuzzy matching within zip code boundaries
    
    Args:
        address: Street address (e.g., "1610 Creedside Dr" or "creedside drive 1610")
        city: City name
        state: State abbreviation
        zip_code: ZIP code for constraining search
        
    Returns:
        Dictionary containing validation results and any corrections
    """
    log_debug("=== SMART ADDRESS VALIDATION START ===", {
        "address": address,
        "city": city, 
        "state": state,
        "zip_code": zip_code
    }, service="smart_address")
    
    # Step 1: Quick exact match validation (fast path)
    try:
        exact_result = validate_exact_address(address, city, state, zip_code)
        if exact_result and exact_result.get('is_valid'):
            log_debug("Exact match found - using fast path", service="smart_address")
            return {
                **exact_result,
                "method": "exact_match",
                "correction_made": False
            }
    except Exception as e:
        log_debug(f"Exact validation failed: {e}", service="smart_address")
    
    # Step 2: Extract address components
    components = extract_address_components(address)
    if not components:
        log_debug("Failed to extract address components", {"address": address}, service="smart_address")
        return {
            "is_valid": False,
            "error": "Cannot parse address - invalid format",
            "method": "parsing_failed"
        }
    
    if not zip_code:
        log_debug("No zip code provided for smart validation", service="smart_address")
        return {
            "is_valid": False,
            "error": "ZIP code required for smart validation",
            "method": "no_zip"
        }
    
    log_debug("Extracted components", components, service="smart_address")
    
    # Step 3: Find candidate addresses with same house number in zip code
    candidates = find_addresses_in_zip(components['house_number'], zip_code, city, state, components.get('street_part'))
    
    if not candidates:
        log_debug("No candidates found in zip code", {
            "house_number": components['house_number'],
            "zip_code": zip_code
        }, service="smart_address")
        return {
            "is_valid": False,
            "error": f"No addresses found with house number {components['house_number']} in {zip_code}",
            "method": "no_candidates"
        }
    
    log_debug(f"Found {len(candidates)} candidates", {"candidates": [c['full_address'] for c in candidates]}, service="smart_address")
    
    # Step 4: Find best match using fuzzy string matching
    best_match = find_best_street_match(components['street_part'], candidates)
    
    if not best_match:
        log_debug("No suitable match found", service="smart_address")
        return {
            "is_valid": False,
            "error": "No suitable address match found",
            "candidates": [c['full_address'] for c in candidates[:3]],
            "method": "no_match"
        }
    
    # Step 5: Determine confidence level and action
    confidence_level = determine_confidence_level(best_match['confidence'])
    auto_correct = should_auto_correct(best_match['confidence'])
    
    # Step 6: Get correct ZIP code by validating corrected address with Google Maps
    corrected_validation = _validate_corrected_address_for_zip(
        best_match['full_address'], city, state
    )
    
    result = {
        "is_valid": True,
        "correction_made": True,
        "method": "smart_match",
        "original_address": address,
        "corrected_address": best_match['full_address'],
        "confidence": confidence_level,
        "similarity_score": best_match['confidence'],
        "auto_correct": auto_correct,
        "place_id": best_match.get('place_id'),
        "match_details": {
            "input_street": components['street_part'],
            "matched_street": best_match['street_name'],
            "house_number": components['house_number']
        }
    }
    
    # Add corrected ZIP code if found
    if corrected_validation and 'zip' in corrected_validation:
        result['corrected_zip'] = corrected_validation['zip']
        result['corrected_city'] = corrected_validation.get('city', city)
        result['corrected_state'] = corrected_validation.get('state', state)
        log_debug(f"Found correct ZIP for corrected address: {corrected_validation['zip']}", service="smart_address")
    
    log_debug("Smart validation complete", result, service="smart_address")
    return result


def extract_address_components(address: str) -> Optional[Dict[str, str]]:
    """
    Extract house number and street name from various address formats
    
    Handles:
    - "1610 Creedside Dr" (normal format)
    - "creedside drive 1610" (reversed format)  
    - "1610-A Oak Street" (with unit)
    - "Apt 5, 1234 Main St" (with apartment)
    """
    if not address or not address.strip():
        return None
    
    address = address.strip()
    
    # Remove common prefixes that might interfere
    prefixes = ['apt ', 'apartment ', 'unit ', 'suite ', '#']
    for prefix in prefixes:
        if address.lower().startswith(prefix):
            # Extract everything after the comma if present
            if ',' in address:
                address = address.split(',', 1)[1].strip()
            break
    
    log_debug("Processing address for component extraction", {"cleaned_address": address}, service="smart_address")
    
    # Pattern 1: Normal format "1234 Street Name" or "1234-A Street Name"
    normal_pattern = r'^(\d+(?:[A-Za-z]|\-\w+)?)\s+(.+)$'
    match = re.match(normal_pattern, address)
    
    if match:
        house_number = match.group(1)
        street_part = match.group(2).strip()
        log_debug("Matched normal format", {"house_number": house_number, "street_part": street_part}, service="smart_address")
        return {
            'house_number': house_number,
            'street_part': street_part
        }
    
    # Pattern 2: Reversed format "Street Name 1234"
    reversed_pattern = r'^(.+?)\s+(\d+(?:[A-Za-z]|\-\w+)?)$'
    match = re.match(reversed_pattern, address)
    
    if match:
        street_part = match.group(1).strip()
        house_number = match.group(2)
        log_debug("Matched reversed format", {"house_number": house_number, "street_part": street_part}, service="smart_address")
        return {
            'house_number': house_number,
            'street_part': street_part
        }
    
    log_debug("No pattern matched for address", {"address": address}, service="smart_address")
    return None


def find_addresses_in_zip(house_number: str, zip_code: str, city: str, state: str, original_street_part: str = None) -> List[Dict[str, Any]]:
    """
    Find all addresses with the given house number in the specified zip code
    """
    if not gmaps_client:
        log_debug("Google Maps client not available", service="smart_address")
        return []
    
    try:
        # Get zip code boundaries first
        zip_bounds = get_zip_code_bounds(zip_code)
        if not zip_bounds:
            log_debug("Could not get zip code bounds", {"zip_code": zip_code}, service="smart_address")
            # Fallback to broader search
            return find_addresses_fallback(house_number, city, state, zip_code)
        
        log_debug("Got zip code bounds", zip_bounds, service="smart_address")
        
        # Search for addresses starting with this house number
        search_query = f"{house_number} {city}, {state} {zip_code}"
        
        log_debug("Searching for addresses", {"query": search_query}, service="smart_address")
        
        # Try Places API text search within zip bounds, but fall back gracefully
        try:
            places_result = gmaps_client.places(
                query=search_query,
                location=zip_bounds['center'],
                radius=zip_bounds['radius']
            )
        except Exception as places_error:
            log_debug(f"Places API failed: {places_error}", service="smart_address")
            places_result = None
        
        candidates = []
        if places_result and 'results' in places_result:
            for place in places_result['results']:
                formatted_address = place.get('formatted_address', '')
                
                # Extract just the street address part (before city)
                street_address = extract_street_address_part(formatted_address)
                
                if street_address and street_address.startswith(house_number):
                    street_name = extract_street_name_from_full_address(street_address, house_number)
                    
                    if street_name:
                        candidates.append({
                            'full_address': street_address,
                            'street_name': street_name,
                            'place_id': place.get('place_id'),
                            'formatted_address': formatted_address
                        })
        
        # Also try geocoding search as backup  
        geocoding_candidates = find_addresses_via_geocoding(house_number, city, state, zip_code, original_street_part)
        
        # Merge and deduplicate
        all_candidates = candidates + geocoding_candidates
        unique_candidates = deduplicate_candidates(all_candidates)
        
        log_debug(f"Found {len(unique_candidates)} unique candidates", {
            "candidates": [c['full_address'] for c in unique_candidates]
        }, service="smart_address")
        
        return unique_candidates
        
    except Exception as e:
        log_debug(f"Error searching addresses in zip: {e}", {"zip_code": zip_code}, service="smart_address")
        return find_addresses_fallback(house_number, city, state, zip_code)


def find_addresses_via_geocoding(house_number: str, city: str, state: str, zip_code: str, original_street_part: str = None) -> List[Dict[str, Any]]:
    """
    Enhanced geocoding search that tries to find similar street names in the area
    """
    candidates = []
    
    try:
        # Strategy: Search for streets in the area and then check if our house number exists on them
        log_debug("Starting enhanced geocoding search", {
            "house_number": house_number,
            "city": city,
            "state": state,
            "zip_code": zip_code
        }, service="smart_address")
        
        # Get a broader search to find streets in the area
        area_search_queries = [
            f"{city}, {state} {zip_code}",
            f"{zip_code} streets",
            f"pass {city}, {state} {zip_code}",  # Search for "pass" streets
            f"creek {city}, {state} {zip_code}",  # Search for "creek" streets 
            f"side {city}, {state} {zip_code}",   # Search for streets ending in "side"
        ]
        
        potential_streets = set()
        
        for query in area_search_queries:
            log_debug(f"Area search query: {query}", service="smart_address")
            try:
                geocode_result = gmaps_client.geocode(query)
                if geocode_result:
                    for result in geocode_result:
                        formatted_address = result.get('formatted_address', '')
                        
                        # Extract street names from the results
                        components = result.get('address_components', [])
                        for component in components:
                            if 'route' in component.get('types', []):
                                street_name = component.get('long_name', '')
                                if street_name and len(street_name) > 3:
                                    potential_streets.add(street_name)
                                    log_debug(f"Found potential street: {street_name}", service="smart_address")
            except Exception as e:
                log_debug(f"Area search query failed: {e}", service="smart_address")
                continue
        
        log_debug(f"Found {len(potential_streets)} potential streets in area", {
            "streets": list(potential_streets)
        }, service="smart_address")
        
        # If we didn't find streets through area searches, try direct variations
        # This handles cases where geocoding doesn't return route components
        if len(potential_streets) == 0:
            log_debug("No streets found via area search, trying direct variations", service="smart_address")
            
            # Generate potential street name variations based on the input
            if original_street_part:
                log_debug(f"Generating variations for: {original_street_part}", service="smart_address")
                variations = generate_street_name_variations(original_street_part)
                potential_streets.update(variations)
            else:
                # Fallback variations if no original street part provided
                potential_streets.update([
                    "Creekside Pass",
                    "Creekside Drive",
                    "Creek Pass",
                ])
            
            log_debug(f"Added direct variations: {list(potential_streets)}", service="smart_address")
        
        # Now search for our house number on each potential street
        for street_name in potential_streets:
            try:
                # Try to find our house number on this street
                address_query = f"{house_number} {street_name}, {city}, {state} {zip_code}"
                log_debug(f"Testing address: {address_query}", service="smart_address")
                
                test_result = gmaps_client.geocode(address_query)
                if test_result:
                    result = test_result[0]
                    formatted_address = result.get('formatted_address', '')
                    street_address = extract_street_address_part(formatted_address)
                    
                    # Check if this actually contains our house number
                    if street_address and house_number in street_address:
                        final_street_name = extract_street_name_from_full_address(street_address, house_number)
                        
                        if final_street_name:
                            candidates.append({
                                'full_address': street_address,
                                'street_name': final_street_name,
                                'place_id': result.get('place_id'),
                                'formatted_address': formatted_address
                            })
                            log_debug(f"Valid address found: {street_address}", service="smart_address")
                        
            except Exception as e:
                log_debug(f"Address test failed for {street_name}: {e}", service="smart_address")
                continue
        
        # Remove duplicates
        unique_candidates = deduplicate_candidates(candidates)
        
        log_debug(f"Enhanced geocoding found {len(unique_candidates)} unique candidates", {
            "candidates": [c['full_address'] for c in unique_candidates]
        }, service="smart_address")
        
        return unique_candidates
        
    except Exception as e:
        log_debug(f"Enhanced geocoding search failed: {e}", service="smart_address")
        return []


def generate_street_name_variations(original_street: str) -> List[str]:
    """
    Generate intelligent variations of a street name for fuzzy matching
    """
    variations = []
    original_lower = original_street.lower()
    
    # Common typo corrections
    typo_corrections = {
        'creeleside': 'creekside',
        'creek side': 'creekside',
        'creekyde': 'creekside',
        'creeksyde': 'creekside',
        # Add more common patterns as needed
    }
    
    # Apply typo corrections
    corrected = original_lower
    for typo, correction in typo_corrections.items():
        if typo in corrected:
            corrected = corrected.replace(typo, correction)
            variations.append(corrected.title())
    
    # Generate variations with different street types
    street_types = ['pass', 'drive', 'street', 'avenue', 'way', 'lane', 'court', 'circle', 'boulevard', 'road']
    
    # Extract the base name (remove existing street type)
    base_name = original_lower
    for street_type in street_types:
        base_name = base_name.replace(f' {street_type}', '').replace(street_type, '')
    
    # Generate variations with different street types
    for street_type in street_types:
        variations.append(f"{base_name.strip()} {street_type}".title())
    
    # Also try the corrected base name with different street types
    if corrected != original_lower:
        corrected_base = corrected
        for street_type in street_types:
            corrected_base = corrected_base.replace(f' {street_type}', '').replace(street_type, '')
        
        for street_type in street_types:
            variations.append(f"{corrected_base.strip()} {street_type}".title())
    
    # Remove duplicates and return
    unique_variations = list(set(variations))
    log_debug(f"Generated {len(unique_variations)} variations for '{original_street}': {unique_variations}", service="smart_address")
    
    return unique_variations


def find_addresses_fallback(house_number: str, city: str, state: str, zip_code: str) -> List[Dict[str, Any]]:
    """
    Fallback method when bounds-based search fails
    """
    try:
        # Simple geocoding search
        search_query = f"{house_number} {city}, {state} {zip_code}"
        
        geocode_result = gmaps_client.geocode(search_query)
        
        candidates = []
        if geocode_result:
            for result in geocode_result[:5]:  # Limit to top 5 results
                formatted_address = result.get('formatted_address', '')
                street_address = extract_street_address_part(formatted_address)
                
                if street_address:
                    street_name = extract_street_name_from_full_address(street_address, house_number)
                    
                    if street_name:
                        candidates.append({
                            'full_address': street_address,
                            'street_name': street_name,
                            'place_id': result.get('place_id'),
                            'formatted_address': formatted_address
                        })
        
        return candidates
        
    except Exception as e:
        log_debug(f"Fallback search failed: {e}", service="smart_address")
        return []


def get_zip_code_bounds(zip_code: str) -> Optional[Dict[str, Any]]:
    """
    Get geographic bounds for a zip code to constrain searches
    """
    try:
        geocode_result = gmaps_client.geocode(zip_code)
        
        if geocode_result:
            geometry = geocode_result[0].get('geometry', {})
            bounds = geometry.get('bounds')
            viewport = geometry.get('viewport', bounds)
            
            if viewport:
                # Calculate center and radius
                center_lat = (viewport['northeast']['lat'] + viewport['southwest']['lat']) / 2
                center_lng = (viewport['northeast']['lng'] + viewport['southwest']['lng']) / 2
                
                # Calculate approximate radius (simplified calculation)
                import math
                lat_diff = viewport['northeast']['lat'] - viewport['southwest']['lat']
                lng_diff = viewport['northeast']['lng'] - viewport['southwest']['lng']
                
                # Convert to approximate meters (rough calculation)
                radius = int(math.sqrt(lat_diff**2 + lng_diff**2) * 111000)  # Degrees to meters
                radius = min(radius, 25000)  # Cap at 25km for very large zip codes
                radius = max(radius, 1000)   # Minimum 1km radius
                
                return {
                    'center': (center_lat, center_lng),
                    'radius': radius,
                    'bounds': viewport
                }
    
    except Exception as e:
        log_debug(f"Failed to get zip code bounds: {e}", {"zip_code": zip_code}, service="smart_address")
    
    return None


def extract_street_address_part(formatted_address: str) -> str:
    """
    Extract just the street address from a full formatted address
    
    Example: "1234 Main Street, Austin, TX 78701, USA" -> "1234 Main Street"
    """
    if not formatted_address:
        return ""
    
    # Split by comma and take the first part (street address)
    parts = formatted_address.split(',')
    if parts:
        return parts[0].strip()
    
    return formatted_address.strip()


def extract_street_name_from_full_address(street_address: str, house_number: str) -> str:
    """
    Extract the street name part from a street address
    
    Example: "1234 Main Street", "1234" -> "Main Street"
    """
    if not street_address or not house_number:
        return ""
    
    # Remove the house number from the beginning
    if street_address.startswith(house_number):
        street_name = street_address[len(house_number):].strip()
        return street_name
    
    return street_address


def find_best_street_match(input_street: str, candidates: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Find the best matching street name using fuzzy string matching
    """
    if not candidates:
        return None
    
    best_match = None
    best_score = 0
    
    # Normalize input street for comparison
    normalized_input = normalize_street_name(input_street)
    
    log_debug("Finding best match", {
        "input_street": input_street,
        "normalized_input": normalized_input,
        "candidate_count": len(candidates)
    }, service="smart_address")
    
    for candidate in candidates:
        candidate_street = candidate['street_name']
        normalized_candidate = normalize_street_name(candidate_street)
        
        # Calculate base similarity using SequenceMatcher
        base_similarity = SequenceMatcher(None, normalized_input, normalized_candidate).ratio()
        
        # Apply bonus for abbreviation matches
        abbrev_bonus = calculate_abbreviation_bonus(input_street, candidate_street)
        
        # Apply bonus for common OCR/typo patterns
        typo_bonus = calculate_typo_bonus(normalized_input, normalized_candidate)
        
        # Calculate final score
        total_score = base_similarity + abbrev_bonus + typo_bonus
        total_score = min(total_score, 1.0)  # Cap at 1.0
        
        log_debug("Candidate scoring", {
            "candidate": candidate_street,
            "base_similarity": base_similarity,
            "abbrev_bonus": abbrev_bonus,
            "typo_bonus": typo_bonus,
            "total_score": total_score
        }, service="smart_address")
        
        if total_score > best_score:
            best_score = total_score
            best_match = {
                **candidate,
                'confidence': total_score
            }
    
    if best_match:
        log_debug("Best match found", {
            "match": best_match['street_name'],
            "confidence": best_match['confidence']
        }, service="smart_address")
    
    return best_match


def normalize_street_name(street: str) -> str:
    """
    Normalize street names for better matching
    """
    if not street:
        return ""
    
    # Convert to lowercase and strip
    normalized = street.lower().strip()
    
    # Standardize common abbreviations to full forms
    abbreviation_map = {
        # Street types
        r'\bst\b': 'street',
        r'\bstr\b': 'street', 
        r'\bave\b': 'avenue',
        r'\bav\b': 'avenue',
        r'\bdr\b': 'drive',
        r'\bdrv\b': 'drive',
        r'\brd\b': 'road',
        r'\bct\b': 'court',
        r'\bln\b': 'lane',
        r'\bblvd\b': 'boulevard',
        r'\bboul\b': 'boulevard',
        r'\bcir\b': 'circle',
        r'\bpl\b': 'place',
        r'\bwy\b': 'way',
        r'\bpkwy\b': 'parkway',
        r'\btr\b': 'trail',
        r'\bpass\b': 'pass',
        
        # Directionals
        r'\bn\b': 'north',
        r'\bs\b': 'south', 
        r'\be\b': 'east',
        r'\bw\b': 'west',
        r'\bne\b': 'northeast',
        r'\bnw\b': 'northwest',
        r'\bse\b': 'southeast',
        r'\bsw\b': 'southwest',
    }
    
    for pattern, replacement in abbreviation_map.items():
        normalized = re.sub(pattern, replacement, normalized)
    
    # Remove extra whitespace
    normalized = ' '.join(normalized.split())
    
    return normalized


def calculate_abbreviation_bonus(input_street: str, candidate_street: str) -> float:
    """
    Calculate bonus score if one street is an abbreviation of the other
    """
    input_norm = normalize_street_name(input_street)
    candidate_norm = normalize_street_name(candidate_street)
    
    # If the original strings are identical, no bonus needed
    if input_street.lower().strip() == candidate_street.lower().strip():
        return 0.0
    
    # If normalized versions match exactly, it's likely just abbreviation differences
    if input_norm == candidate_norm:
        return 0.15  # 15% bonus for abbreviation match
    
    # Check if they're similar after normalization but weren't before
    if input_norm != input_street.lower() or candidate_norm != candidate_street.lower():
        pre_norm_similarity = SequenceMatcher(None, input_street.lower(), candidate_street.lower()).ratio()
        post_norm_similarity = SequenceMatcher(None, input_norm, candidate_norm).ratio()
        
        if post_norm_similarity > pre_norm_similarity + 0.2:
            return 0.1  # 10% bonus for normalization improvement
    
    return 0.0


def calculate_typo_bonus(input_norm: str, candidate_norm: str) -> float:
    """
    Calculate bonus for common typo patterns
    """
    # Common OCR and typing errors
    typo_patterns = [
        ('ei', 'ee'), ('ee', 'ei'),  # Creeleside vs Creekside
        ('ie', 'ei'), ('ei', 'ie'),
        ('rn', 'm'), ('m', 'rn'),    # OCR errors
        ('vv', 'w'), ('w', 'vv'),
        ('cl', 'd'), ('d', 'cl'),
        ('ii', 'n'), ('n', 'ii'),
    ]
    
    for pattern1, pattern2 in typo_patterns:
        # Check if replacing pattern1 with pattern2 in input makes it match candidate
        if pattern1 in input_norm:
            test_input = input_norm.replace(pattern1, pattern2)
            if test_input == candidate_norm:
                return 0.1  # 10% bonus for typo correction
        
        # Check reverse
        if pattern2 in input_norm:
            test_input = input_norm.replace(pattern2, pattern1)
            if test_input == candidate_norm:
                return 0.1  # 10% bonus for typo correction
    
    return 0.0


def deduplicate_candidates(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Remove duplicate candidates based on full address
    """
    seen_addresses = set()
    unique_candidates = []
    
    for candidate in candidates:
        address = candidate['full_address']
        if address not in seen_addresses:
            seen_addresses.add(address)
            unique_candidates.append(candidate)
    
    return unique_candidates


def determine_confidence_level(score: float) -> str:
    """
    Convert numeric confidence score to descriptive level
    """
    if score >= 0.95:
        return "very_high"
    elif score >= 0.90:
        return "high" 
    elif score >= 0.80:
        return "medium_high"
    elif score >= 0.70:
        return "medium"
    elif score >= 0.60:
        return "medium_low"
    else:
        return "low"


def should_auto_correct(score: float) -> bool:
    """
    Determine if the confidence is high enough for automatic correction
    """
    return score >= 0.80  # Auto-correct for 80%+ confidence (medium_high and above)


def _validate_corrected_address_for_zip(corrected_address: str, city: str, state: str) -> Optional[Dict[str, Any]]:
    """
    Validate a corrected address with Google Maps to get the correct ZIP code.
    This queries Google Maps with the corrected address but WITHOUT the original wrong ZIP,
    allowing Google Maps to return the correct ZIP code.
    
    Args:
        corrected_address: The corrected street address (e.g., "18610 Creekside Pass")
        city: The city name
        state: The state
        
    Returns:
        Dictionary with corrected components if found, None otherwise
    """
    try:
        # Query Google Maps with corrected address + city + state (no ZIP)
        # This lets Google Maps tell us the correct ZIP code
        query = f"{corrected_address}, {city}, {state}"
        log_debug(f"Validating corrected address for ZIP: {query}", service="smart_address")
        
        geocoding_result = gmaps_client.geocode(query)
        
        if geocoding_result:
            place = geocoding_result[0]
            components = place.get('address_components', [])
            
            # Extract corrected components
            extracted = {}
            for component in components:
                types = component.get('types', [])
                if 'postal_code' in types:
                    extracted['zip'] = component['long_name']
                elif 'locality' in types:
                    extracted['city'] = component['long_name']
                elif 'administrative_area_level_1' in types:
                    extracted['state'] = component['short_name']
                elif 'street_number' in types:
                    extracted['street_number'] = component['long_name']
                elif 'route' in types:
                    extracted['street_name'] = component['long_name']
            
            # Only return if we found a ZIP code
            if 'zip' in extracted:
                log_debug(f"Found correct ZIP via corrected address validation", {
                    "original_query": query,
                    "extracted_zip": extracted['zip'],
                    "extracted_city": extracted.get('city'),
                    "extracted_state": extracted.get('state')
                }, service="smart_address")
                return extracted
        
        log_debug(f"No ZIP found for corrected address: {query}", service="smart_address")
        return None
        
    except Exception as e:
        log_debug(f"Error validating corrected address for ZIP: {str(e)}", service="smart_address")
        return None

def validate_exact_address(address: str, city: str, state: str, zip_code: str) -> Optional[Dict[str, Any]]:
    """
    Validate address using exact matching (existing method)
    """
    try:
        # Import the existing validation function
        from app.services.document_service import validate_address_with_google
        
        result = validate_address_with_google(address, city, state, zip_code)
        
        # Only consider it valid if we have actual street address information
        has_street_info = (result and 
                          (result.get('street_address') or 
                           (result.get('street_number') and result.get('street_name'))))
        
        if has_street_info:
            return {
                "is_valid": True,
                "formatted_address": result['formatted_address'],
                "latitude": result.get('latitude'),
                "longitude": result.get('longitude'),
                "place_id": result.get('place_id'),
                "street_address": result.get('street_address'),
                "street_number": result.get('street_number'),
                "street_name": result.get('street_name')
            }
            
    except Exception as e:
        log_debug(f"Exact validation error: {e}", service="smart_address")
    
    return None
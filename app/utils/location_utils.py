"""
Location utilities for enhanced high school matching
"""
import math
from typing import Optional, Tuple, Dict, Any
import re

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate the great circle distance between two points 
    on the earth (specified in decimal degrees)
    Returns distance in miles
    """
    # Convert decimal degrees to radians
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    
    # Haversine formula
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    
    # Radius of earth in miles
    r = 3959
    return c * r

def normalize_city_state(city: str, state: str) -> Tuple[str, str]:
    """Normalize city and state for comparison"""
    city = city.strip().title() if city else ""
    state = state.strip().upper() if state else ""
    return city, state

def get_proximity_boost(
    student_city: Optional[str], 
    student_state: Optional[str],
    school_city: str, 
    school_state: str,
    student_coords: Optional[Tuple[float, float]] = None,
    school_coords: Optional[Tuple[float, float]] = None
) -> float:
    """
    Calculate proximity boost for high school matching
    
    Returns:
        0.0 - 0.3: Boost factor to add to base similarity score
    """
    if not student_city or not student_state:
        return 0.0
    
    # Normalize inputs
    student_city_norm, student_state_norm = normalize_city_state(student_city, student_state)
    school_city_norm, school_state_norm = normalize_city_state(school_city, school_state)
    
    # Different states = no boost (unless border cities)
    if student_state_norm != school_state_norm:
        return 0.0
    
    # Same city = strong boost for local matches
    if student_city_norm == school_city_norm:
        return 0.25  # Strong local match - prioritize local schools
    
    # Use coordinates if available
    if student_coords and school_coords:
        distance = haversine_distance(
            student_coords[0], student_coords[1],
            school_coords[0], school_coords[1]
        )
        
        if distance <= 10:  # Within 10 miles
            return 0.08
        elif distance <= 25:  # Within 25 miles  
            return 0.06
        elif distance <= 50:  # Within 50 miles
            return 0.04
        else:
            return 0.0
    
    # Fall back to city name matching for regional proximity
    # Texas metro areas
    dfw_cities = {'dallas', 'fort worth', 'plano', 'frisco', 'mckinney', 'allen', 'wylie', 'richardson', 'garland', 'irving', 'arlington', 'grand prairie'}
    houston_cities = {'houston', 'katy', 'sugar land', 'the woodlands', 'pasadena', 'pearland', 'spring', 'conroe'}
    austin_cities = {'austin', 'round rock', 'cedar park', 'pflugerville', 'georgetown', 'leander'}
    san_antonio_cities = {'san antonio', 'new braunfels', 'seguin', 'schertz', 'universal city'}
    
    metro_areas = [dfw_cities, houston_cities, austin_cities, san_antonio_cities]
    
    student_lower = student_city_norm.lower()
    school_lower = school_city_norm.lower()
    
    for metro in metro_areas:
        if student_lower in metro and school_lower in metro:
            return 0.05  # Same metro area (reduced from 0.15)
    
    return 0.0

def extract_location_from_address(address: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Extract city and state from address string
    
    Args:
        address: Full address string
        
    Returns:
        Tuple of (city, state) or (None, None) if not found
    """
    if not address:
        return None, None
    
    # Pattern to match city, state at end of address
    # Examples: "123 Main St, Dallas, TX" or "Dallas TX 75001"
    patterns = [
        r',\s*([^,]+),\s*([A-Z]{2})\s*(?:\d{5})?(?:-\d{4})?\s*$',  # ", City, TX 12345"
        r'\s+([^,\d]+),?\s+([A-Z]{2})\s+\d{5}',  # "City TX 12345" or "City, TX 12345"
        r',\s*([^,]+)\s+([A-Z]{2})\s*$',  # ", City TX"
    ]
    
    for pattern in patterns:
        match = re.search(pattern, address.strip(), re.IGNORECASE)
        if match:
            city = match.group(1).strip()
            state = match.group(2).upper()
            return city, state
    
    return None, None

def get_student_location_context(fields: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract location context from student fields
    
    Args:
        fields: Student field data
        
    Returns:
        Dict with location context including city, state, full_address
    """
    context = {
        'city': None,
        'state': None,
        'full_address': None,
        'coordinates': None
    }
    
    # Get state from dedicated field
    state_field = fields.get('state', {})
    if state_field and state_field.get('value'):
        context['state'] = state_field['value'].strip().upper()
    
    # Get city from dedicated field if available
    city_field = fields.get('city', {})
    if city_field and city_field.get('value'):
        context['city'] = city_field['value'].strip().title()
    
    # Fallback: Check city_state field if individual fields are missing
    if not context['city'] or not context['state']:
        city_state_field = fields.get('city_state', {})
        if city_state_field and city_state_field.get('value'):
            city_state_value = city_state_field['value'].strip()
            # Try to parse "City, State" format
            match = re.match(r'^([^,]+),\s*([A-Za-z]{2})$', city_state_value)
            if match:
                if not context['city']:
                    context['city'] = match.group(1).strip().title()
                if not context['state']:
                    context['state'] = match.group(2).strip().upper()
    
    # Get full address
    address_field = fields.get('address', {})
    if address_field and address_field.get('value'):
        context['full_address'] = address_field['value'].strip()
        
        # If we still don't have city from dedicated field, try to extract from address
        if not context['city']:
            addr_city, addr_state = extract_location_from_address(context['full_address'])
            if addr_city:
                context['city'] = addr_city
            if addr_state and not context['state']:
                context['state'] = addr_state
    
    return context
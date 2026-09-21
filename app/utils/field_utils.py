# Field utilities for processing card data

def filter_combined_fields(fields: dict) -> dict:
    """
    Remove combined fields that have been split into individual components.
    These fields should not be saved to the final reviewed_data table.

    Args:
        fields: Dictionary of field data

    Returns:
        Filtered dictionary with combined fields removed
    """
    # Use the centralized exclusion list
    combined_fields_to_exclude = get_combined_fields_to_exclude()

    # Create a copy of fields without the combined fields
    filtered_fields = {}

    for field_name, field_data in fields.items():
        if field_name not in combined_fields_to_exclude:
            filtered_fields[field_name] = field_data

    return filtered_fields

def get_individual_address_fields():
    """
    Get the list of individual address fields that should be preserved.
    
    Returns:
        List of individual address field names
    """
    return ['address', 'city', 'state', 'zip_code']

def get_combined_fields_to_exclude():
    """
    Get the list of combined fields that should be excluded from final data.

    Returns:
        List of combined field names to exclude
    """
    return [
        'city_state',
        'city_state_zip',
        'citystatezip',
        'address_line',
        'high_school_class_rank',
        'city_state_country',
        'full_address',
        'address_combined',
        'academic_scores',  # Combined field that gets split into gpa, act_score, sat_score
    ]

# Combined name fields that were later split into first/last. Cards scanned
# before the split only carry the combined value, so exports fill the split
# columns from it rather than writing blanks. Stored card data is left alone;
# this is a read-time fallback only.
SPLIT_NAME_FALLBACKS = {
    "parent_guardian_first_name": ("parent_guardian_name", "first_name"),
    "parent_guardian_last_name": ("parent_guardian_name", "last_name"),
}


def split_full_name(full_name) -> dict:
    """
    Split a full name into first and last name.

    A single word is treated as a first name, and everything after the first
    word becomes the last name so multi-word surnames stay intact.
    """
    if not full_name or not isinstance(full_name, str):
        return {"first_name": "", "last_name": ""}

    name_parts = [part for part in full_name.strip().split() if part]

    if not name_parts:
        return {"first_name": "", "last_name": ""}
    if len(name_parts) == 1:
        return {"first_name": name_parts[0], "last_name": ""}
    return {"first_name": name_parts[0], "last_name": " ".join(name_parts[1:])}


def read_field_value(fields: dict, key: str) -> str:
    """Read a card field's value, tolerating both dict and bare value formats"""
    if not isinstance(fields, dict):
        return ""
    data = fields.get(key)
    if isinstance(data, dict):
        return str(data.get("value", "") or "")
    return str(data) if data else ""


def resolve_split_name_value(fields: dict, field_key: str) -> str:
    """
    Value for a split name column: prefer the split field, then fall back to
    splitting the combined field that older cards still carry.
    """
    direct = read_field_value(fields, field_key)
    if direct:
        return direct

    source_key, part = SPLIT_NAME_FALLBACKS[field_key]
    return split_full_name(read_field_value(fields, source_key)).get(part, "")


def generate_field_label(field_key: str) -> str:
    """Convert field keys to user-friendly display labels for DocAI field names"""
    
    # Comprehensive mapping for all possible DocAI field names
    field_label_mapping = {
        # Phone variations
        'cell': 'Phone Number',
        'cell_phone': 'Phone Number',
        'phone': 'Phone Number', 
        'phone_number': 'Phone Number',
        'mobile': 'Phone Number',
        'mobile_phone': 'Phone Number',
        'cellphone': 'Phone Number',
        
        # Date/Birthday variations
        'date_of_birth': 'Birthday',
        'birthdate': 'Birthday',
        'dob': 'Birthday',
        'birth_date': 'Birthday',
        'birthday': 'Birthday',
        
        # Email variations
        'email': 'Email',
        'email_address': 'Email',
        'e_mail': 'Email',
        'emailaddress': 'Email',
        
        # Address variations
        'address': 'Address',
        'street_address': 'Address',
        'home_address': 'Address',
        'mailing_address': 'Address',
        
        # Name variations
        'name': 'Name',
        'student_name': 'Name',
        'full_name': 'Name',
        'fullname': 'Name',
        
        # Common fields
        'zip_code': 'Zip Code',
        'high_school': 'High School',
        'highschool': 'High School',
        'high_school_name': 'High School',
        'entry_term': 'Entry Term',
        'entryterm': 'Entry Term',
        'entry_semester': 'Entry Term',
        'permission_to_text': 'Permission to Text',
        'preferred_first_name': 'Preferred Name',
        'students_in_class': 'Students in Class',
        'class_rank': 'Class Rank',
        'student_type': 'Student Type',
        'studenttype': 'Student Type',
        'student_category': 'Student Type',
        'mapped_major': 'Mapped Major',
        'gpa': 'GPA',
        'act_score': 'ACT Score',
        'sat_score': 'SAT Score',

        # Major variations
        'major': 'Major',
        'program': 'Major',
        'degree': 'Major',
        'field_of_study': 'Major',
        'major_program': 'Major',
        
        # City/State
        'city': 'City',
        'state': 'State',
        
        # Gender
        'gender': 'Gender'
    }
    
    # Return specific mapping if it exists
    if field_key in field_label_mapping:
        return field_label_mapping[field_key]
    
    # Convert snake_case to Title Case as fallback
    # Replace underscores with spaces and capitalize each word
    words = field_key.replace('_', ' ').split()
    return ' '.join(word.capitalize() for word in words)


def validate_field_key(field_key: str) -> bool:
    """Validate that a field key is properly formatted"""
    if not field_key or not isinstance(field_key, str):
        return False
    
    # Field keys should be lowercase, alphanumeric, with underscores
    import re
    return bool(re.match(r'^[a-z][a-z0-9_]*$', field_key))


# Canonicalization functions removed - DocAI field names now flow through unchanged 
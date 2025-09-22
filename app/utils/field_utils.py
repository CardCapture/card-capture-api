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
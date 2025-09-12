"""
Fix JSON corruption detection and improve field validation
"""

def sanitize_json_field(field_data):
    """
    Sanitize a field data object to prevent JSON corruption
    """
    if not isinstance(field_data, dict):
        return field_data
    
    sanitized = {}
    for key, value in field_data.items():
        if isinstance(value, str):
            # Fix common JSON corruption patterns
            value = value.replace('{{', '{').replace('}}', '}')
            # Remove any malformed JSON patterns
            value = ''.join(c for c in value if ord(c) >= 32 or c in '\n\r\t')
        sanitized[key] = value
    
    return sanitized

def validate_and_fix_review_data(review_data):
    """
    Validate and fix review data before database operations
    Returns cleaned data or raises exception if unfixable
    """
    import json
    
    try:
        # Deep copy to avoid modifying original
        import copy
        cleaned_data = copy.deepcopy(review_data)
        
        # Fix fields if they exist
        if 'fields' in cleaned_data and isinstance(cleaned_data['fields'], dict):
            for field_name, field_data in cleaned_data['fields'].items():
                cleaned_data['fields'][field_name] = sanitize_json_field(field_data)
        
        # Test JSON serialization
        serialized = json.dumps(cleaned_data)
        json.loads(serialized)  # Verify it can be parsed back
        
        return cleaned_data
        
    except Exception as e:
        raise ValueError(f"JSON validation failed: {str(e)}")

def improved_json_validation(review_data, critical_fields=None):
    """
    Improved JSON validation with better error handling
    """
    if critical_fields is None:
        critical_fields = ["cell", "date_of_birth", "email", "name"]
    
    issues = []
    
    try:
        import json
        
        # First, try to serialize the entire object
        serialized = json.dumps(review_data)
        
        # Check specific fields
        fields_data = review_data.get('fields', {})
        for field_name in critical_fields:
            if field_name in fields_data:
                field_data = fields_data[field_name]
                field_str = json.dumps(field_data)
                
                # Check for corruption patterns
                if '{{' in field_str or '}}' in field_str:
                    issues.append(f"Double braces in {field_name}")
                
                if field_str.count('{') != field_str.count('}'):
                    issues.append(f"Brace mismatch in {field_name}")
                
                # Check for invalid characters
                if any(ord(c) < 32 and c not in '\n\r\t' for c in field_str):
                    issues.append(f"Invalid characters in {field_name}")
        
        return {
            'valid': len(issues) == 0,
            'issues': issues,
            'serialized_length': len(serialized)
        }
        
    except Exception as e:
        return {
            'valid': False,
            'issues': [f"JSON serialization failed: {str(e)}"],
            'serialized_length': 0
        }
"""
Canonical field mapper enhancer - maps legacy field names to canonical format
"""
from typing import Dict, Any
from app.pipeline.enhancers.base import FieldEnhancer
from app.pipeline.models import FieldData, PipelineContext
from app.utils.retry_utils import log_debug


class CanonicalFieldMapperEnhancer(FieldEnhancer):
    """
    Maps legacy field names to canonical field names and ensures name splitting.
    
    This enhancer:
    1. Maps legacy field names (mobile -> cell, zip -> zip_code, etc.)
    2. Splits combined name fields into first_name/last_name
    3. Ensures all fields use canonical naming convention
    4. Preserves original field metadata (confidence, source, etc.)
    """
    
    def get_description(self) -> str:
        return "Map legacy field names to canonical format and split name fields"
    
    def enhance(self, fields: Dict[str, FieldData], context: PipelineContext) -> Dict[str, FieldData]:
        """Apply canonical field mapping and name splitting"""
        
        # Step 1: Apply field name mapping
        fields = self._apply_field_mapping(fields)
        
        # Step 2: Ensure name components exist
        fields = self._ensure_name_components(fields)
        
        return fields
    
    def _apply_field_mapping(self, fields: Dict[str, FieldData]) -> Dict[str, FieldData]:
        """
        Map legacy field names to canonical field names.
        Based on the mapping from students_service.py _normalize_student_payload
        """
        # Canonical field mapping
        field_mapping = {
            "mobile": "cell",
            "phone": "cell", 
            "phone_number": "cell",
            "cellphone": "cell",
            "address1": "address",
            "street_address": "address",
            "home_address": "address",
            "mailing_address": "address",
            "address2": "address_2",
            "zip": "zip_code",
            "zipcode": "zip_code",
            "postal_code": "zip_code",
            "dob": "date_of_birth",
            "birthdate": "date_of_birth",
            "birth_date": "date_of_birth",
            "birthday": "date_of_birth",
            "start_term": "entry_term",
            "entry_semester": "entry_term",
            "start_year": "entry_year",
            "sms_opt_in": "permission_to_text",
            "text_permission": "permission_to_text",
            "highschool": "high_school",
            "high_school_name": "high_school",
            "school_name": "high_school",
            "name_of_high_school": "high_school",
            "name_of_high_school_college": "high_school",
            "student_name": "name",
            "full_name": "name",
            "fullname": "name",
            "email_address": "email",
            "e_mail": "email",
            "emailaddress": "email",
            "program": "major",
            "degree": "major",
            "field_of_study": "major",
            "major_program": "major",
            "studenttype": "student_type",
            "student_category": "student_type",
            "entryterm": "entry_term",
        }
        
        mapped_fields = {}
        
        for field_name, field_data in fields.items():
            # Get canonical field name
            canonical_name = field_mapping.get(field_name.lower(), field_name)
            
            # If this is a mapping, log it
            if canonical_name != field_name:
                log_debug(f"Mapped field: '{field_name}' -> '{canonical_name}'", service="pipeline")
            
            # If canonical field already exists, merge intelligently
            if canonical_name in mapped_fields:
                # Keep the field with higher confidence or non-empty value
                existing_field = mapped_fields[canonical_name]
                if (not existing_field.value and field_data.value) or \
                   (field_data.confidence > existing_field.confidence):
                    mapped_fields[canonical_name] = field_data
                    log_debug(f"Replaced '{canonical_name}' with better data from '{field_name}'", service="pipeline")
            else:
                mapped_fields[canonical_name] = field_data
        
        return mapped_fields
    
    def _ensure_name_components(self, fields: Dict[str, FieldData]) -> Dict[str, FieldData]:
        """
        Ensure first_name and last_name exist if only a combined name is present.
        Based on ensure_name_components from student-app worker_v2.py
        """
        try:
            # Check if canonical name parts already present
            first_present = 'first_name' in fields and fields['first_name'].value
            last_present = 'last_name' in fields and fields['last_name'].value
            
            if first_present and last_present:
                return fields
            
            name_field = fields.get('name')
            if not name_field or not name_field.value:
                return fields
            
            full_name = str(name_field.value).strip()
            if not full_name:
                return fields
            
            parts = [p for p in full_name.split() if p]
            if len(parts) == 1:
                first_val, last_val = parts[0], ""
            else:
                first_val, last_val = parts[0], " ".join(parts[1:])
            
            # Create first_name field if needed
            if not first_present and first_val:
                fields['first_name'] = self._create_field(
                    first_val,
                    source_field=name_field,
                    source='name_split',
                    confidence=name_field.confidence * 0.95  # Slightly lower confidence for derived field
                )
                log_debug(f"Split name field: created first_name = '{first_val}'", service="pipeline")
            
            # Create last_name field if needed  
            if not last_present and last_val:
                fields['last_name'] = self._create_field(
                    last_val,
                    source_field=name_field,
                    source='name_split',
                    confidence=name_field.confidence * 0.95
                )
                log_debug(f"Split name field: created last_name = '{last_val}'", service="pipeline")
                
        except Exception as e:
            # Best-effort; never fail pipeline on name split
            log_debug(f"Name splitting failed (continuing): {e}", service="pipeline")
        
        return fields

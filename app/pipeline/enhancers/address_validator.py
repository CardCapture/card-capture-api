"""
Address validation enhancer - validates and enriches address fields with Google Maps
"""
from typing import Dict, Optional
from app.pipeline.enhancers.base import FieldEnhancer
from app.pipeline.models import FieldData, PipelineContext
from app.services.address_validation_service import validate_address
from app.utils.retry_utils import log_debug


class AddressValidationEnhancer(FieldEnhancer):
    """
    Validates and enhances address fields using Google Maps API.
    
    Updates address components based on validation results and
    marks fields for review if validation fails.
    """
    
    def get_description(self) -> str:
        return "Validate and enhance addresses with Google Maps"
    
    def should_run(self, fields: Dict[str, FieldData], context: PipelineContext) -> bool:
        """Only run if we have at least some address fields"""
        address_fields = ['address', 'city', 'state', 'zip_code']
        return any(field in fields and fields[field].value for field in address_fields)
    
    def enhance(self, fields: Dict[str, FieldData], context: PipelineContext) -> Dict[str, FieldData]:
        """Validate address and enhance fields based on results"""
        
        # Extract current address components
        address = self._get_field_value(fields, 'address')
        city = self._get_field_value(fields, 'city')
        state = self._get_field_value(fields, 'state')
        zip_code = self._get_field_value(fields, 'zip_code')
        
        # Skip if we don't have enough to validate
        if not address and not (city and state):
            log_debug("Skipping address validation: insufficient address data", service="pipeline")
            return fields
        
        # Validate with Google Maps
        log_debug(f"Validating address: {address}, {city}, {state} {zip_code}", service="pipeline")
        result = validate_address(address, city, state, zip_code)
        
        # Process based on validation state
        if result.state == "verified":
            # Perfect match - update fields with verified data
            fields = self._apply_verified_address(fields, result)
            log_debug("Address VERIFIED by Google Maps", {
                "suggestion": result.suggestion
            }, service="pipeline")
            
        elif result.state == "can_be_verified":
            # Has suggestions but not auto-applied
            fields = self._apply_address_suggestions(fields, result)
            log_debug("Address CAN BE VERIFIED - suggestions available", {
                "suggestion": result.suggestion
            }, service="pipeline")
            
        elif result.state == "no_house_number":
            # Missing house number
            fields = self._mark_needs_house_number(fields, result)
            log_debug("Address missing house number", service="pipeline")
            
        else:  # not_verified
            # Could not validate
            fields = self._mark_not_verified(fields, result)
            log_debug("Address could not be verified", {
                "error": result.error
            }, service="pipeline")
        
        return fields
    
    def _get_field_value(self, fields: Dict[str, FieldData], key: str) -> str:
        """Safely get field value"""
        if key in fields and fields[key].value:
            return fields[key].value.strip()
        return ""
    
    def _apply_verified_address(self, fields: Dict[str, FieldData], result) -> Dict[str, FieldData]:
        """
        Apply verified address data from Google Maps.
        Sets high confidence and marks as verified.
        """
        if not result.suggestion:
            return fields
        
        # Update each address component if present in suggestion
        address_fields = {
            'address': 'address',
            'city': 'city', 
            'state': 'state',
            'zip_code': 'zip_code'
        }
        
        for field_key, suggestion_key in address_fields.items():
            if suggestion_key in result.suggestion:
                suggested_value = result.suggestion[suggestion_key]
                
                if field_key not in fields:
                    # Create new field if doesn't exist
                    fields[field_key] = FieldData(
                        value=suggested_value,
                        confidence=1.0,
                        source='google_maps_verified',
                        validation_status='verified',
                        requires_human_review=False
                    )
                else:
                    # Update existing field
                    fields[field_key].value = suggested_value
                    fields[field_key].confidence = 1.0
                    fields[field_key].source = 'google_maps_verified'
                    fields[field_key].validation_status = 'verified'
                    fields[field_key].requires_human_review = False
                    fields[field_key].review_notes = ""
        
        return fields
    
    def _apply_address_suggestions(self, fields: Dict[str, FieldData], result) -> Dict[str, FieldData]:
        """
        Add suggestions to address fields without auto-applying.
        Marks fields as needing validation.
        """
        if not result.suggestion:
            return fields
        
        # Add suggestions to each address field
        address_fields = ['address', 'city', 'state', 'zip_code']
        
        for field_key in address_fields:
            if field_key in fields:
                fields[field_key].validation_status = 'can_be_verified'
                fields[field_key].suggestions = [result.suggestion]
                
                # Mark for review if this is a required field
                if fields[field_key].required:
                    fields[field_key].requires_human_review = True
                    fields[field_key].review_notes = "Address can be verified - review suggestions"
        
        return fields
    
    def _mark_needs_house_number(self, fields: Dict[str, FieldData], result) -> Dict[str, FieldData]:
        """
        Mark address as needing house number.
        But still populate city/state/zip if Google Maps found them.
        Also clean up the address field by removing city/state if they're at the end.
        """
        # Even though address is invalid, populate city/state/zip if Google found them
        extracted_city = None
        extracted_state = None

        if result.suggestion:
            suggestion = result.suggestion

            # Populate city if found
            if suggestion.get('city'):
                extracted_city = suggestion['city']
                if 'city' not in fields:
                    fields['city'] = FieldData(
                        value=extracted_city,
                        confidence=0.8,
                        source='google_maps_partial',
                        validation_status='partial',
                        requires_human_review=False
                    )
                elif not fields['city'].value:  # Only update if empty
                    fields['city'].value = extracted_city
                    fields['city'].source = 'google_maps_partial'
                    fields['city'].validation_status = 'partial'

            # Populate state if found
            if suggestion.get('state'):
                extracted_state = suggestion['state']
                if 'state' not in fields:
                    fields['state'] = FieldData(
                        value=extracted_state,
                        confidence=0.8,
                        source='google_maps_partial',
                        validation_status='partial',
                        requires_human_review=False
                    )
                elif not fields['state'].value:  # Only update if empty
                    fields['state'].value = extracted_state
                    fields['state'].source = 'google_maps_partial'
                    fields['state'].validation_status = 'partial'

            # Populate zip if found
            if suggestion.get('zip_code'):
                if 'zip_code' not in fields:
                    fields['zip_code'] = FieldData(
                        value=suggestion['zip_code'],
                        confidence=0.8,
                        source='google_maps_partial',
                        validation_status='partial',
                        requires_human_review=False
                    )
                elif not fields['zip_code'].value:  # Only update if empty
                    fields['zip_code'].value = suggestion['zip_code']
                    fields['zip_code'].source = 'google_maps_partial'
                    fields['zip_code'].validation_status = 'partial'

        # Clean up address field by removing city/state if they appear at the end
        if 'address' in fields and extracted_city and extracted_state:
            original_address = fields['address'].value
            cleaned_address = self._remove_city_state_from_address(
                original_address,
                extracted_city,
                extracted_state
            )

            if cleaned_address != original_address:
                log_debug(f"Cleaned address: '{original_address}' → '{cleaned_address}'", service="pipeline")
                fields['address'].value = cleaned_address

        # Mark address as needing review
        if 'address' in fields:
            fields['address'].validation_status = 'no_house_number'
            fields['address'].requires_human_review = True
            fields['address'].review_notes = "Address missing house number"

            # Add error message if provided
            if result.error:
                fields['address'].review_notes = result.error

        return fields

    def _remove_city_state_from_address(self, address: str, city: str, state: str) -> str:
        """
        Remove city and state from the end of an address string.

        Examples:
        - "PO Box 854 Lambert ms" → "PO Box 854"
        - "POBox 854 Lambert MS" → "POBox 854"
        - "123 Main St Austin TX" → "123 Main St"
        """
        import re

        # Normalize for comparison
        address_lower = address.lower().strip()
        city_lower = city.lower().strip()
        state_lower = state.lower().strip()

        # Pattern 1: "city state" at end (with or without space/punctuation)
        # Match variations like: "Lambert ms", "Lambert MS", "Lambert, MS"
        pattern1 = re.compile(
            rf'\s*[,\s]*{re.escape(city_lower)}\s*,?\s*{re.escape(state_lower)}\s*$',
            re.IGNORECASE
        )

        if pattern1.search(address_lower):
            cleaned = pattern1.sub('', address).strip()
            return cleaned

        # Pattern 2: Try state only at the end (if city wasn't found)
        pattern2 = re.compile(
            rf'\s+{re.escape(state_lower)}\s*$',
            re.IGNORECASE
        )

        if pattern2.search(address_lower):
            cleaned = pattern2.sub('', address).strip()
            return cleaned

        return address
    
    def _mark_not_verified(self, fields: Dict[str, FieldData], result) -> Dict[str, FieldData]:
        """
        Mark address fields as not verified.
        """
        address_fields = ['address', 'city', 'state', 'zip_code']
        
        for field_key in address_fields:
            if field_key in fields and fields[field_key].value:
                fields[field_key].validation_status = 'not_verified'
                
                # Mark required fields for review
                if fields[field_key].required:
                    fields[field_key].requires_human_review = True
                    fields[field_key].review_notes = "Address could not be verified"
        
        # Add error message to address field if provided
        if 'address' in fields and result.error:
            fields['address'].review_notes = f"Validation error: {result.error}"
        
        return fields
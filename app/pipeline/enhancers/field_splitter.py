"""
Field splitter enhancer - splits combined fields into individual components
"""
import re
from typing import Dict
from app.pipeline.enhancers.base import FieldEnhancer
from app.pipeline.models import FieldData, PipelineContext
from app.utils.retry_utils import log_debug


class FieldSplitterEnhancer(FieldEnhancer):
    """
    Splits combined address fields into their individual components.
    
    Handles:
    - city_state_zip -> city, state, zip_code
    - city_state -> city, state
    - Other combined address fields
    
    Note: Name splitting (name -> first_name, last_name) is now handled 
    by CanonicalFieldMapperEnhancer.
    """
    
    def get_description(self) -> str:
        return "Split combined address fields into components"
    
    def enhance(self, fields: Dict[str, FieldData], context: PipelineContext) -> Dict[str, FieldData]:
        """Split combined address fields into individual components"""
        # Make a copy to avoid modifying during iteration
        fields = dict(fields)
        
        # Split address fields only (name splitting now handled by CanonicalFieldMapperEnhancer)
        fields = self._split_address_fields(fields, context)
        
        return fields
    
    def _split_address_fields(self, fields: Dict[str, FieldData], context: PipelineContext) -> Dict[str, FieldData]:
        """
        Split combined address fields like city_state_zip into components.
        """
        # List of combined fields to check
        combined_fields = ['city_state_zip', 'citystatezip', 'city_state', 'address_line']
        
        for field_key in combined_fields:
            if field_key not in fields:
                continue
                
            field = fields[field_key]
            if not field.value:
                continue
                
            value = field.value.replace('\n', ' ').replace('\r', ' ').strip()
            
            # Try different patterns to split the combined field
            
            # Pattern 1: City, State, Zip (with commas)
            match = re.match(r'^([^,]+),\s*([A-Za-z]{2})(?:,\s*|\s+)(\d{5}(?:-\d{4})?)[.,;:]*?$', value)
            if match:
                self._set_address_components(
                    fields,
                    city=match.group(1).strip(),
                    state=match.group(2).strip().upper(),
                    zip_code=match.group(3).strip(),
                    source_field=field,
                    source_key=field_key
                )
                continue
            
            # Pattern 2: City, State (no zip)
            match = re.match(r'^([^,]+),\s*([A-Za-z]{2})[.,;:]*?$', value)
            if match:
                self._set_address_components(
                    fields,
                    city=match.group(1).strip(),
                    state=match.group(2).strip().upper(),
                    source_field=field,
                    source_key=field_key
                )
                continue
            
            # Pattern 3: City State Zip (no commas)
            match = re.match(r'^(.+?)\s+([A-Za-z]{2})\s+(\d{5}(?:-\d{4})?)[.,;:]*?$', value)
            if match:
                self._set_address_components(
                    fields,
                    city=match.group(1).strip(),
                    state=match.group(2).strip().upper(),
                    zip_code=match.group(3).strip(),
                    source_field=field,
                    source_key=field_key
                )
                continue
            
            # Pattern 4: City State (no commas, no zip)
            match = re.match(r'^(.+?)\s+([A-Za-z]{2})[.,;:]*?$', value)
            if match:
                # Make sure the last part is actually a state code
                potential_state = match.group(2).strip()
                if len(potential_state) == 2:
                    self._set_address_components(
                        fields,
                        city=match.group(1).strip(),
                        state=potential_state.upper(),
                        source_field=field,
                        source_key=field_key
                    )
                    continue
            
            # Fallback: Try to extract state code and split around it
            state_match = re.search(r'\b([A-Za-z]{2})\b', value)
            if state_match:
                state_pos = state_match.start()
                city_part = value[:state_pos].strip().rstrip(',')
                state_part = state_match.group(1).upper()
                zip_part = value[state_match.end():].strip().lstrip(',').strip()
                
                # Extract zip if present
                zip_match = re.search(r'\b(\d{5}(?:-\d{4})?)\b', zip_part)
                if zip_match:
                    zip_code = zip_match.group(1)
                else:
                    zip_code = None
                
                if city_part:  # Only split if we found a city
                    self._set_address_components(
                        fields,
                        city=city_part,
                        state=state_part,
                        zip_code=zip_code,
                        source_field=field,
                        source_key=field_key
                    )
        
        return fields
    
    def _split_name_fields(self, fields: Dict[str, FieldData], context: PipelineContext) -> Dict[str, FieldData]:
        """
        Split combined name field into first_name and last_name.
        Only splits if the individual components don't already exist.
        """
        # Check if we already have first and last name
        has_first = 'first_name' in fields and fields['first_name'].value
        has_last = 'last_name' in fields and fields['last_name'].value
        
        # If we have both, nothing to do
        if has_first and has_last:
            return fields
        
        # Check if we have a combined name field
        if 'name' not in fields or not fields['name'].value:
            return fields
        
        name_field = fields['name']
        full_name = name_field.value.strip()
        
        # Split the name
        parts = full_name.split()
        if not parts:
            return fields
        
        # Handle different name formats
        if len(parts) == 1:
            # Single name - use as first name
            first_name = parts[0]
            last_name = ""
        elif len(parts) == 2:
            # Simple first last
            first_name = parts[0]
            last_name = parts[1]
        else:
            # Multiple parts - take first as first name, rest as last name
            first_name = parts[0]
            last_name = " ".join(parts[1:])
        
        # Create the fields if they don't exist
        if not has_first and first_name:
            fields['first_name'] = self._create_field(
                first_name,
                source_field=name_field,
                source='name_split',
                confidence=name_field.confidence * 0.95  # Slightly lower confidence for derived field
            )
            log_debug(f"Split name field: created first_name = '{first_name}'", service="pipeline")
        
        if not has_last and last_name:
            fields['last_name'] = self._create_field(
                last_name,
                source_field=name_field,
                source='name_split',
                confidence=name_field.confidence * 0.95
            )
            log_debug(f"Split name field: created last_name = '{last_name}'", service="pipeline")
        
        return fields
    
    def _set_address_components(self, fields: Dict[str, FieldData], 
                                city: str = None, 
                                state: str = None, 
                                zip_code: str = None,
                                source_field: FieldData = None,
                                source_key: str = None) -> None:
        """
        Helper to set address component fields.
        Only creates fields that don't already exist or are empty.
        """
        # Set city if provided and field doesn't exist or is empty
        if city and ('city' not in fields or not fields['city'].value):
            fields['city'] = self._create_field(
                city,
                source_field=source_field,
                source='address_split',
                confidence=source_field.confidence if source_field else 0.8
            )
            log_debug(f"Split {source_key}: created city = '{city}'", service="pipeline")
        
        # Set state if provided and field doesn't exist or is empty  
        if state and ('state' not in fields or not fields['state'].value):
            fields['state'] = self._create_field(
                state,
                source_field=source_field,
                source='address_split',
                confidence=source_field.confidence if source_field else 0.8
            )
            log_debug(f"Split {source_key}: created state = '{state}'", service="pipeline")
        
        # Set zip if provided and field doesn't exist or is empty
        if zip_code and ('zip_code' not in fields or not fields['zip_code'].value):
            fields['zip_code'] = self._create_field(
                zip_code,
                source_field=source_field,
                source='address_split',
                confidence=source_field.confidence if source_field else 0.8
            )
            log_debug(f"Split {source_key}: created zip_code = '{zip_code}'", service="pipeline")
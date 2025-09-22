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
        """Split combined fields into individual components"""
        # Make a copy to avoid modifying during iteration
        fields = dict(fields)

        # Split address fields only (name splitting now handled by CanonicalFieldMapperEnhancer)
        fields = self._split_address_fields(fields, context)

        # Split academic scores into individual GPA, ACT, SAT fields
        fields = self._split_academic_scores(fields, context)

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
            
            # Use smart city/state splitting instead of complex regex patterns
            result = self._smart_split_city_state(value)
            if result:
                city, state, zip_code = result
                self._set_address_components(
                    fields,
                    city=city,
                    state=state,
                    zip_code=zip_code,
                    source_field=field,
                    source_key=field_key
                )
                log_debug(f"Smart split {field_key}: city='{city}', state='{state}', zip='{zip_code or 'None'}'", service="pipeline")
                continue
            
            # Fallback: Try legacy regex patterns for edge cases
            
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
            
            # Pattern 2: City, State (no zip) - handles both abbreviations and full names
            match = re.match(r'^([^,]+),\s*([A-Za-z]{2,})[.,;:]*?$', value)
            if match:
                city_part = match.group(1).strip()
                state_part = match.group(2).strip()
                # Handle both full state names and abbreviations
                if len(state_part) == 2:
                    state_code = state_part.upper()
                else:
                    # Convert full state name to abbreviation
                    state_map = {
                        'texas': 'TX', 'california': 'CA', 'florida': 'FL', 'new york': 'NY',
                        'pennsylvania': 'PA', 'illinois': 'IL', 'ohio': 'OH', 'georgia': 'GA',
                        'north carolina': 'NC', 'michigan': 'MI', 'new jersey': 'NJ', 'virginia': 'VA',
                        'washington': 'WA', 'arizona': 'AZ', 'massachusetts': 'MA', 'tennessee': 'TN',
                        'indiana': 'IN', 'missouri': 'MO', 'maryland': 'MD', 'wisconsin': 'WI',
                        'colorado': 'CO', 'minnesota': 'MN', 'south carolina': 'SC', 'alabama': 'AL',
                        'louisiana': 'LA', 'kentucky': 'KY', 'oregon': 'OR', 'oklahoma': 'OK',
                        'connecticut': 'CT', 'utah': 'UT', 'iowa': 'IA', 'nevada': 'NV',
                        'arkansas': 'AR', 'mississippi': 'MS', 'kansas': 'KS', 'new mexico': 'NM',
                        'nebraska': 'NE', 'west virginia': 'WV', 'idaho': 'ID', 'hawaii': 'HI',
                        'new hampshire': 'NH', 'maine': 'ME', 'montana': 'MT', 'rhode island': 'RI',
                        'delaware': 'DE', 'south dakota': 'SD', 'north dakota': 'ND', 'alaska': 'AK',
                        'vermont': 'VT', 'wyoming': 'WY'
                    }
                    state_code = state_map.get(state_part.lower(), state_part[:2].upper())
                
                self._set_address_components(
                    fields,
                    city=city_part,
                    state=state_code,
                    source_field=field,
                    source_key=field_key
                )
                log_debug(f"Split {field_key}: created city = '{city_part}', state = '{state_code}'", service="pipeline")
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
            
            # Pattern 4: City / State (with forward slash)
            match = re.match(r'^([^/]+)/\s*([A-Za-z]{2,})[.,;:]*?$', value)
            if match:
                city_part = match.group(1).strip()
                state_part = match.group(2).strip()
                # Handle both full state names and abbreviations
                if len(state_part) == 2:
                    state_code = state_part.upper()
                else:
                    # Convert full state name to abbreviation if needed
                    state_map = {
                        'texas': 'TX', 'california': 'CA', 'florida': 'FL', 'new york': 'NY',
                        'pennsylvania': 'PA', 'illinois': 'IL', 'ohio': 'OH', 'georgia': 'GA',
                        'north carolina': 'NC', 'michigan': 'MI', 'new jersey': 'NJ', 'virginia': 'VA',
                        'washington': 'WA', 'arizona': 'AZ', 'massachusetts': 'MA', 'tennessee': 'TN',
                        'indiana': 'IN', 'missouri': 'MO', 'maryland': 'MD', 'wisconsin': 'WI',
                        'colorado': 'CO', 'minnesota': 'MN', 'south carolina': 'SC', 'alabama': 'AL',
                        'louisiana': 'LA', 'kentucky': 'KY', 'oregon': 'OR', 'oklahoma': 'OK',
                        'connecticut': 'CT', 'utah': 'UT', 'iowa': 'IA', 'nevada': 'NV',
                        'arkansas': 'AR', 'mississippi': 'MS', 'kansas': 'KS', 'new mexico': 'NM',
                        'nebraska': 'NE', 'west virginia': 'WV', 'idaho': 'ID', 'hawaii': 'HI',
                        'new hampshire': 'NH', 'maine': 'ME', 'montana': 'MT', 'rhode island': 'RI',
                        'delaware': 'DE', 'south dakota': 'SD', 'north dakota': 'ND', 'alaska': 'AK',
                        'vermont': 'VT', 'wyoming': 'WY'
                    }
                    state_code = state_map.get(state_part.lower(), state_part[:2].upper())
                
                self._set_address_components(
                    fields,
                    city=city_part,
                    state=state_code,
                    source_field=field,
                    source_key=field_key
                )
                continue
            
            # Pattern 5: City State (no commas, no zip)
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
    
    def _smart_split_city_state(self, value: str) -> tuple:
        """
        Smart city/state splitting that handles various formats and full state names.
        Returns (city, state_code, zip_code) or None if can't parse.
        """
        # Comprehensive state mapping (both full names and abbreviations)
        state_mapping = {
            # Full state names to abbreviations
            'alabama': 'AL', 'alaska': 'AK', 'arizona': 'AZ', 'arkansas': 'AR', 'california': 'CA',
            'colorado': 'CO', 'connecticut': 'CT', 'delaware': 'DE', 'florida': 'FL', 'georgia': 'GA',
            'hawaii': 'HI', 'idaho': 'ID', 'illinois': 'IL', 'indiana': 'IN', 'iowa': 'IA',
            'kansas': 'KS', 'kentucky': 'KY', 'louisiana': 'LA', 'maine': 'ME', 'maryland': 'MD',
            'massachusetts': 'MA', 'michigan': 'MI', 'minnesota': 'MN', 'mississippi': 'MS', 'missouri': 'MO',
            'montana': 'MT', 'nebraska': 'NE', 'nevada': 'NV', 'new hampshire': 'NH', 'new jersey': 'NJ',
            'new mexico': 'NM', 'new york': 'NY', 'north carolina': 'NC', 'north dakota': 'ND', 'ohio': 'OH',
            'oklahoma': 'OK', 'oregon': 'OR', 'pennsylvania': 'PA', 'rhode island': 'RI', 'south carolina': 'SC',
            'south dakota': 'SD', 'tennessee': 'TN', 'texas': 'TX', 'utah': 'UT', 'vermont': 'VT',
            'virginia': 'VA', 'washington': 'WA', 'west virginia': 'WV', 'wisconsin': 'WI', 'wyoming': 'WY',
            # Abbreviations (already correct)
            'al': 'AL', 'ak': 'AK', 'az': 'AZ', 'ar': 'AR', 'ca': 'CA', 'co': 'CO', 'ct': 'CT',
            'de': 'DE', 'fl': 'FL', 'ga': 'GA', 'hi': 'HI', 'id': 'ID', 'il': 'IL', 'in': 'IN',
            'ia': 'IA', 'ks': 'KS', 'ky': 'KY', 'la': 'LA', 'me': 'ME', 'md': 'MD', 'ma': 'MA',
            'mi': 'MI', 'mn': 'MN', 'ms': 'MS', 'mo': 'MO', 'mt': 'MT', 'ne': 'NE', 'nv': 'NV',
            'nh': 'NH', 'nj': 'NJ', 'nm': 'NM', 'ny': 'NY', 'nc': 'NC', 'nd': 'ND', 'oh': 'OH',
            'ok': 'OK', 'or': 'OR', 'pa': 'PA', 'ri': 'RI', 'sc': 'SC', 'sd': 'SD', 'tn': 'TN',
            'tx': 'TX', 'ut': 'UT', 'vt': 'VT', 'va': 'VA', 'wa': 'WA', 'wv': 'WV', 'wi': 'WI', 'wy': 'WY'
        }
        
        # Try different delimiters
        delimiters = [',', '/', '|', '-', '\\']
        
        for delimiter in delimiters:
            if delimiter in value:
                parts = [part.strip() for part in value.split(delimiter)]
                if len(parts) >= 2:
                    result = self._parse_parts_for_city_state(parts, state_mapping)
                    if result:
                        return result
        
        # Try space-separated (for formats like "Abilene TX 79606")
        parts = value.split()
        if len(parts) >= 2:
            result = self._parse_parts_for_city_state(parts, state_mapping)
            if result:
                return result
        
        return None
    
    def _parse_parts_for_city_state(self, parts: list, state_mapping: dict) -> tuple:
        """Parse a list of parts to extract city, state, and optional zip."""
        city = None
        state = None
        zip_code = None
        
        # Look for zip code first (5 or 9 digit format)
        zip_pattern = re.compile(r'^\d{5}(-\d{4})?$')
        for i, part in enumerate(parts):
            if zip_pattern.match(part):
                zip_code = part
                parts = parts[:i] + parts[i+1:]  # Remove zip from parts
                break
        
        # Simple approach: for comma-separated, last part is likely state, first part(s) are city
        if len(parts) == 2:
            # Common case: "City, State" or "Multi Word City, State"
            potential_city = parts[0].strip('.,;:!?')
            potential_state = parts[1].lower().strip('.,;:!?')
            
            if potential_state in state_mapping:
                return (potential_city, state_mapping[potential_state], zip_code)
        
        # For space-separated or other formats, try each part as potential state
        for i, part in enumerate(parts):
            normalized_part = part.lower().strip('.,;:!?')
            if normalized_part in state_mapping:
                state = state_mapping[normalized_part]
                # Everything before the state is the city
                if i > 0:
                    city = ' '.join(parts[:i]).strip('.,;:!?')
                else:
                    # State is first, everything after is city
                    remaining_parts = parts[i+1:]
                    if remaining_parts:
                        city = ' '.join(remaining_parts).strip('.,;:!?')
                break
        
        # If we found both city and state, return the result
        if city and state:
            return (city, state, zip_code)
        
        return None
    
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

    def _split_academic_scores(self, fields: Dict[str, FieldData], context: PipelineContext) -> Dict[str, FieldData]:
        """
        Split academic_scores field into individual gpa, act_score, and sat_score fields.

        Uses value ranges to determine which score type:
        - GPA: 0.0-5.0 (decimal values)
        - ACT: 1-36 (integer values)
        - SAT: 400-1600 (integer values)
        """
        if 'academic_scores' not in fields or not fields['academic_scores'].value:
            return fields

        academic_field = fields['academic_scores']
        value = str(academic_field.value).strip()

        if not value:
            return fields

        log_debug(f"Splitting academic_scores field: '{value}'", service="pipeline")

        # Extract all numeric values from the field
        import re
        # Match integers and decimals
        number_pattern = r'\d+\.?\d*'
        numbers = re.findall(number_pattern, value)

        scores_found = {'gpa': None, 'act_score': None, 'sat_score': None}

        for num_str in numbers:
            try:
                num = float(num_str)

                # Classify based on value ranges
                # Check for SAT first (highest range, most specific)
                if 400 <= num <= 1600 and num == int(num):
                    # SAT range - must be whole number
                    if not scores_found['sat_score']:  # Only take first SAT found
                        scores_found['sat_score'] = str(int(num))
                        log_debug(f"Detected SAT: {int(num)}", service="pipeline")

                # Check for ACT (must be whole number and in range)
                elif 1 <= num <= 36 and num == int(num) and not ('.' in num_str):
                    # ACT range - must be whole number (no decimal points)
                    if not scores_found['act_score']:  # Only take first ACT found
                        scores_found['act_score'] = str(int(num))
                        log_debug(f"Detected ACT: {int(num)}", service="pipeline")

                # Check for GPA last (lowest range, most general)
                elif 0.0 <= num <= 5.0:
                    # GPA range - can have decimal
                    if not scores_found['gpa']:  # Only take first GPA found
                        scores_found['gpa'] = num_str
                        log_debug(f"Detected GPA: {num_str}", service="pipeline")

            except ValueError:
                log_debug(f"Could not parse number: {num_str}", service="pipeline")
                continue

        # Create individual fields for each detected score
        # Only create fields that don't already exist or are empty
        for field_name, score_value in scores_found.items():
            if score_value and (field_name not in fields or not fields[field_name].value):
                fields[field_name] = self._create_field(
                    score_value,
                    source_field=academic_field,
                    source='academic_score_split',
                    confidence=academic_field.confidence * 0.95  # Slightly lower confidence for derived field
                )
                log_debug(f"Created {field_name} field with value: {score_value}", service="pipeline")

        # Log summary of what was extracted
        extracted_count = sum(1 for v in scores_found.values() if v)
        log_debug(f"Academic score splitting complete. Extracted {extracted_count} scores from: '{value}'", {
            'gpa': scores_found['gpa'],
            'act_score': scores_found['act_score'],
            'sat_score': scores_found['sat_score']
        }, service="pipeline")

        return fields
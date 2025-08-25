"""
High school matcher enhancer - matches high schools and adds CEEB codes
"""
from typing import Dict, Optional
from app.pipeline.enhancers.base import FieldEnhancer
from app.pipeline.models import FieldData, PipelineContext
from app.services.enhanced_high_school_matching_service import EnhancedHighSchoolMatchingService
from app.utils.retry_utils import log_debug


class HighSchoolMatcherEnhancer(FieldEnhancer):
    """
    Matches high schools to directory and adds CEEB codes.
    
    Uses location context for improved matching accuracy.
    """
    
    def __init__(self):
        super().__init__()
        self.matcher = EnhancedHighSchoolMatchingService()
    
    def get_description(self) -> str:
        return "Match high schools to directory and add CEEB codes"
    
    def should_run(self, fields: Dict[str, FieldData], context: PipelineContext) -> bool:
        """Only run if we have a high school field with a value"""
        # Check both possible high school field names
        high_school_fields = ['high_school', 'name_of_high_school']
        for field_name in high_school_fields:
            if field_name in fields and fields[field_name].value and fields[field_name].value.strip():
                return True
        return False
    
    def enhance(self, fields: Dict[str, FieldData], context: PipelineContext) -> Dict[str, FieldData]:
        """Match high school and enhance with CEEB code if found"""
        
        # Find which high school field has data
        high_school_field = None
        high_school_name = None
        high_school_field_name = None
        
        for field_name in ['high_school', 'name_of_high_school']:
            if field_name in fields and fields[field_name].value and fields[field_name].value.strip():
                high_school_field = fields[field_name]
                high_school_name = high_school_field.value.strip()
                high_school_field_name = field_name
                break
        
        if not high_school_name:
            return fields
        
        # Get location context for better matching
        location_context = self._build_location_context(fields)
        
        log_debug(f"Matching high school: '{high_school_name}' from field '{high_school_field_name}'", {
            "location_context": location_context,
            "source_field": high_school_field_name
        }, service="pipeline")
        
        try:
            # Run the enhanced matching service with location context
            validated_fields = self.matcher.validate_and_enhance_high_school_with_location(
                self._convert_to_legacy_format(fields),
                confidence_threshold=0.85
            )
            
            # Convert back to new format and extract results
            fields = self._apply_matching_results(fields, validated_fields)
            
        except Exception as e:
            log_debug(f"High school matching failed: {str(e)}", service="pipeline")
            # Continue without failing the pipeline
            
        return fields
    
    def _build_location_context(self, fields: Dict[str, FieldData]) -> Dict[str, str]:
        """Build location context from address fields"""
        return {
            'city': self._get_field_value(fields, 'city'),
            'state': self._get_field_value(fields, 'state'),
            'zip_code': self._get_field_value(fields, 'zip_code')
        }
    
    def _get_field_value(self, fields: Dict[str, FieldData], key: str) -> str:
        """Safely get field value"""
        if key in fields and fields[key].value:
            return fields[key].value.strip()
        return ""
    
    def _convert_to_legacy_format(self, fields: Dict[str, FieldData]) -> Dict[str, Dict]:
        """Convert new FieldData format to legacy dict format for existing service"""
        legacy_fields = {}
        high_school_data = None
        
        # First pass: find the high school field with actual data
        for field_name in ['high_school', 'name_of_high_school']:
            if field_name in fields and fields[field_name].value and fields[field_name].value.strip():
                high_school_data = fields[field_name].to_dict()
                break
        
        # Second pass: convert all fields, using the high school data we found
        for key, field_data in fields.items():
            if key == 'name_of_high_school':
                # Skip this - we'll map it to high_school below
                continue
            elif key == 'high_school':
                # Use the data we found (either from high_school or name_of_high_school)
                if high_school_data:
                    legacy_fields['high_school'] = high_school_data
                else:
                    legacy_fields[key] = field_data.to_dict()
            else:
                legacy_fields[key] = field_data.to_dict()
        
        # If we found high school data in name_of_high_school but no high_school field existed
        if high_school_data and 'high_school' not in legacy_fields:
            legacy_fields['high_school'] = high_school_data
            
        return legacy_fields
    
    def _apply_matching_results(self, fields: Dict[str, FieldData], validated_fields: Dict[str, Dict]) -> Dict[str, FieldData]:
        """
        Apply results from the high school matching service.
        
        The service returns fields in the old dict format, so we need to convert back.
        """
        # Get validation status
        validation_status = validated_fields.get('high_school_validation', {})
        status = validation_status.get('status', 'unknown')
        
        log_debug(f"High school validation result: {status}", {
            "match_type": validation_status.get('match_type'),
            "confidence": f"{validation_status.get('confidence', 0):.1%}",
            "suggestions_count": len(validation_status.get('suggestions', []))
        }, service="pipeline")
        
        if status == 'verified':
            # Auto-matched with high confidence
            self._apply_verified_high_school(fields, validated_fields, validation_status)
            
        elif status == 'needs_validation':
            # Has suggestions but needs manual validation
            self._apply_high_school_suggestions(fields, validated_fields, validation_status)
            
        elif status == 'no_matches':
            # No matches found
            self._mark_high_school_no_matches(fields, validation_status)
            
        # Add the validation metadata to the high school field (whichever one has data)
        high_school_field_with_data = None
        for field_name in ['high_school', 'name_of_high_school']:
            if field_name in fields and fields[field_name].value and fields[field_name].value.strip():
                high_school_field_with_data = field_name
                break
        
        if high_school_field_with_data:
            fields[high_school_field_with_data].validation_status = status
            if validation_status.get('suggestions'):
                fields[high_school_field_with_data].suggestions = validation_status['suggestions']
        
        # Create the high_school_validation field that the frontend expects
        if validation_status:
            fields['high_school_validation'] = FieldData(
                value=status,
                confidence=1.0,
                source='high_school_matcher',
                validation_status=status,
                requires_human_review=False,
                suggestions=validation_status.get('suggestions', [])
            )
        
        return fields
    
    def _apply_verified_high_school(self, fields: Dict[str, FieldData], 
                                   validated_fields: Dict[str, Dict],
                                   validation_status: Dict) -> None:
        """
        Apply verified high school match.
        Updates high school name and adds CEEB code.
        """
        # Update high school name with matched name
        if 'high_school' in validated_fields:
            hs_data = validated_fields['high_school']
            fields['high_school'].value = hs_data.get('value', fields['high_school'].value)
            fields['high_school'].source = 'high_school_directory_verified'
            fields['high_school'].confidence = validation_status.get('confidence', 0.9)
            fields['high_school'].requires_human_review = False
            fields['high_school'].review_notes = ""
            
            # Add metadata that frontend expects for verified schools
            if not hasattr(fields['high_school'], 'metadata'):
                fields['high_school'].metadata = {}
            
            # Extract school info from the enhanced high school service data
            hs_metadata = hs_data.get('metadata', {})
            
            if hs_metadata:
                # Use metadata from the enhanced service directly
                fields['high_school'].metadata.update(hs_metadata)
            else:
                # Fallback for backward compatibility
                fields['high_school'].metadata.update({
                    'original_value': fields['high_school'].value
                })
        
        # Add CEEB code if provided
        if 'ceeb_code' in validated_fields:
            ceeb_data = validated_fields['ceeb_code']
            ceeb_value = ceeb_data.get('value', '')
            
            if ceeb_value:
                fields['ceeb_code'] = FieldData(
                    value=ceeb_value,
                    confidence=1.0,
                    source='high_school_directory',
                    validation_status='verified',
                    requires_human_review=False
                )
                log_debug(f"Added CEEB code: {ceeb_value}", service="pipeline")
    
    def _apply_high_school_suggestions(self, fields: Dict[str, FieldData],
                                     validated_fields: Dict[str, Dict],
                                     validation_status: Dict) -> None:
        """
        Apply high school suggestions for manual validation.
        """
        suggestions = validation_status.get('suggestions', [])
        
        if 'high_school' in fields:
            fields['high_school'].suggestions = suggestions
            fields['high_school'].validation_status = 'needs_validation'
            
            # Mark for review if it's a required field
            if fields['high_school'].required:
                fields['high_school'].requires_human_review = True
                fields['high_school'].review_notes = f"High school needs validation - {len(suggestions)} suggestions available"
        
        log_debug(f"High school needs validation: {len(suggestions)} suggestions", service="pipeline")
    
    def _mark_high_school_no_matches(self, fields: Dict[str, FieldData], validation_status: Dict) -> None:
        """
        Mark high school as having no matches.
        """
        if 'high_school' in fields:
            fields['high_school'].validation_status = 'no_matches'
            
            # Mark for review if it's a required field
            if fields['high_school'].required:
                fields['high_school'].requires_human_review = True
                fields['high_school'].review_notes = "High school not found in directory"
        
        log_debug("High school: no matches found", service="pipeline")
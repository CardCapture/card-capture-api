"""
Field requirements enhancer - applies school-specific field requirements
"""
from typing import Dict
from app.pipeline.enhancers.base import FieldEnhancer
from app.pipeline.models import FieldData, PipelineContext
from app.services.settings_service import apply_field_requirements
from app.utils.retry_utils import log_debug


class FieldRequirementsEnhancer(FieldEnhancer):
    """
    Applies school-specific field requirements.
    
    Sets enabled/disabled status and required flags based on
    school configuration.
    """
    
    def get_description(self) -> str:
        return "Apply school-specific field requirements and settings"
    
    def enhance(self, fields: Dict[str, FieldData], context: PipelineContext) -> Dict[str, FieldData]:
        """Apply field requirements from school settings"""
        
        if not context.field_requirements:
            log_debug("No field requirements in context", service="pipeline")
            return fields
        
        log_debug(f"Applying field requirements for {len(context.field_requirements)} fields", {
            "school_id": context.school_id,
            "requirements": {k: v for k, v in list(context.field_requirements.items())[:5]}  # Log first 5
        }, service="pipeline")
        
        # Convert FieldData to legacy format for existing service
        legacy_fields = self._convert_to_legacy_format(fields)
        
        # Apply requirements using existing service
        enhanced_fields = apply_field_requirements(legacy_fields, context.field_requirements)
        
        # Convert back to FieldData format
        fields = self._convert_from_legacy_format(enhanced_fields, fields)
        
        # Log what changed
        enabled_count = sum(1 for f in fields.values() if f.enabled)
        required_count = sum(1 for f in fields.values() if f.required)
        
        log_debug("Field requirements applied", {
            "total_fields": len(fields),
            "enabled_fields": enabled_count,
            "required_fields": required_count
        }, service="pipeline")
        
        return fields
    
    def _convert_to_legacy_format(self, fields: Dict[str, FieldData]) -> Dict[str, Dict]:
        """Convert FieldData format to legacy dict format"""
        legacy_fields = {}
        for key, field_data in fields.items():
            legacy_fields[key] = field_data.to_dict()
        return legacy_fields
    
    def _convert_from_legacy_format(self, legacy_fields: Dict[str, Dict], 
                                   original_fields: Dict[str, FieldData]) -> Dict[str, FieldData]:
        """
        Convert legacy dict format back to FieldData format.
        Preserves any additional metadata that wasn't in the legacy format.
        """
        new_fields = {}
        
        for key, legacy_data in legacy_fields.items():
            if key in original_fields:
                # Update existing field
                field = original_fields[key]
                field.enabled = legacy_data.get('enabled', field.enabled)
                field.required = legacy_data.get('required', field.required)
                
                # Update other properties that might have changed
                field.value = legacy_data.get('value', field.value)
                field.confidence = legacy_data.get('confidence', field.confidence)
                field.source = legacy_data.get('source', field.source)
                
                new_fields[key] = field
            else:
                # Create new field from legacy data
                new_fields[key] = FieldData.from_dict(legacy_data)
        
        # Add any fields that weren't in the requirements
        for key, field in original_fields.items():
            if key not in new_fields:
                new_fields[key] = field
        
        return new_fields
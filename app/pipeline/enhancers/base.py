"""
Base class for all field enhancers
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple
import time
from app.pipeline.models import FieldData, PipelineContext, EnhancerResult
from app.utils.retry_utils import log_debug


class FieldEnhancer(ABC):
    """
    Base class for all field enhancers.
    
    Enhancers are responsible for transforming, validating, or enriching
    field data in a specific way. Each enhancer should do one thing well.
    """
    
    def __init__(self):
        """Initialize the enhancer with a logger"""
        self.name = self.__class__.__name__
        
    @abstractmethod
    def enhance(self, fields: Dict[str, FieldData], context: PipelineContext) -> Dict[str, FieldData]:
        """
        Apply enhancement to fields.
        
        Args:
            fields: Current field data
            context: Pipeline context with school settings, etc.
            
        Returns:
            Enhanced field data (can be modified in place or new dict)
        """
        pass
    
    @abstractmethod
    def get_description(self) -> str:
        """
        Return human-readable description of what this enhancer does.
        
        Returns:
            Description string for logging/debugging
        """
        pass
    
    def should_run(self, fields: Dict[str, FieldData], context: PipelineContext) -> bool:
        """
        Determine if this enhancer should run.
        
        Override this method to conditionally skip the enhancer based on
        field contents or context.
        
        Args:
            fields: Current field data
            context: Pipeline context
            
        Returns:
            True if enhancer should run, False to skip
        """
        return True
    
    def execute(self, fields: Dict[str, FieldData], context: PipelineContext) -> Tuple[Dict[str, FieldData], EnhancerResult]:
        """
        Execute the enhancer with timing and error handling.
        
        This is the main entry point that the pipeline calls.
        
        Args:
            fields: Current field data
            context: Pipeline context
            
        Returns:
            Tuple of (enhanced fields, execution result)
        """
        start_time = time.time()
        
        # Track original field keys for comparison
        original_keys = set(fields.keys())
        original_values = {k: v.value for k, v in fields.items()}
        
        try:
            # Check if should run
            if not self.should_run(fields, context):
                log_debug(f"Skipping {self.name}: should_run returned False", service="pipeline")
                return fields, EnhancerResult(
                    enhancer_name=self.name,
                    fields_modified=[],
                    fields_added=[],
                    success=True,
                    duration_ms=0
                )
            
            # Log start
            log_debug(f"Running enhancer: {self.name}", {
                "description": self.get_description(),
                "field_count": len(fields)
            }, service="pipeline")
            
            # Run the enhancement
            enhanced_fields = self.enhance(fields, context)
            
            # Track what changed
            new_keys = set(enhanced_fields.keys())
            fields_added = list(new_keys - original_keys)
            fields_modified = []
            
            for key in original_keys:
                if key in enhanced_fields:
                    if enhanced_fields[key].value != original_values[key]:
                        fields_modified.append(key)
            
            # Calculate duration
            duration_ms = (time.time() - start_time) * 1000
            
            # Log completion
            log_debug(f"Completed {self.name}", {
                "fields_added": fields_added,
                "fields_modified": fields_modified,
                "duration_ms": f"{duration_ms:.2f}"
            }, service="pipeline")
            
            return enhanced_fields, EnhancerResult(
                enhancer_name=self.name,
                fields_modified=fields_modified,
                fields_added=fields_added,
                success=True,
                duration_ms=duration_ms
            )
            
        except Exception as e:
            # Log error
            duration_ms = (time.time() - start_time) * 1000
            error_msg = f"Error in {self.name}: {str(e)}"
            log_debug(error_msg, {"error": str(e)}, service="pipeline")
            
            # Return original fields on error (fail gracefully)
            return fields, EnhancerResult(
                enhancer_name=self.name,
                fields_modified=[],
                fields_added=[],
                success=False,
                error=error_msg,
                duration_ms=duration_ms
            )
    
    def _copy_field_metadata(self, source: FieldData, target: FieldData) -> FieldData:
        """
        Helper to copy metadata from source field to target field.
        
        Useful when creating derived fields.
        
        Args:
            source: Source field to copy metadata from
            target: Target field to update
            
        Returns:
            Updated target field
        """
        target.enabled = source.enabled
        target.required = source.required
        if not target.source:
            target.source = source.source
        if not target.confidence:
            target.confidence = source.confidence
        return target
    
    def _create_field(self, value: str, source_field: Optional[FieldData] = None, **kwargs) -> FieldData:
        """
        Helper to create a new field with optional metadata from source.
        
        Args:
            value: Field value
            source_field: Optional source field to copy metadata from
            **kwargs: Additional field attributes
            
        Returns:
            New FieldData instance
        """
        # If we have a source field, use its attributes as defaults
        if source_field:
            # Start with source field's attributes
            field_attrs = {
                'enabled': source_field.enabled,
                'required': source_field.required,
                'source': source_field.source,
                'confidence': source_field.confidence,
                'original_value': source_field.original_value
            }
            # Override with any explicitly provided kwargs
            field_attrs.update(kwargs)
            field = FieldData(value=value, **field_attrs)
        else:
            field = FieldData(value=value, **kwargs)
        return field
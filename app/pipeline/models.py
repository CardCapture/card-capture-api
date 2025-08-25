"""
Data models for the pipeline processing system
"""
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from enum import Enum
from datetime import datetime


class ProcessingStage(Enum):
    """Stages of pipeline processing"""
    EXTRACTION = "extraction"
    ENHANCEMENT = "enhancement"
    REVIEW = "review"


@dataclass
class FieldData:
    """
    Single source of truth for field structure.
    Represents a single field's data and metadata.
    """
    value: str
    confidence: float = 0.0
    source: str = ""
    enabled: bool = True
    required: bool = False
    original_value: Optional[str] = None
    validation_status: Optional[str] = None
    suggestions: Optional[List[Dict]] = None
    requires_human_review: bool = False
    review_notes: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for compatibility with existing code"""
        return {
            'value': self.value,
            'confidence': self.confidence,
            'source': self.source,
            'enabled': self.enabled,
            'required': self.required,
            'original_value': self.original_value,
            'validation_status': self.validation_status,
            'suggestions': self.suggestions or [],
            'requires_human_review': self.requires_human_review,
            'review_notes': self.review_notes,
            'metadata': self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'FieldData':
        """Create FieldData from dictionary"""
        return cls(
            value=data.get('value', ''),
            confidence=data.get('confidence', 0.0),
            source=data.get('source', ''),
            enabled=data.get('enabled', True),
            required=data.get('required', False),
            original_value=data.get('original_value'),
            validation_status=data.get('validation_status'),
            suggestions=data.get('suggestions'),
            requires_human_review=data.get('requires_human_review', False),
            review_notes=data.get('review_notes', ''),
            metadata=data.get('metadata', {})
        )


@dataclass
class PipelineContext:
    """
    Carries all context through the pipeline.
    Immutable context that enhancers can read but not modify.
    """
    school_id: str
    user_id: str
    event_id: Optional[str]
    image_path: str
    valid_majors: List[str] = field(default_factory=list)
    field_requirements: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def with_metadata(self, **kwargs) -> 'PipelineContext':
        """Create a new context with additional metadata"""
        new_metadata = {**self.metadata, **kwargs}
        return PipelineContext(
            school_id=self.school_id,
            user_id=self.user_id,
            event_id=self.event_id,
            image_path=self.image_path,
            valid_majors=self.valid_majors,
            field_requirements=self.field_requirements,
            metadata=new_metadata
        )


@dataclass
class ProcessingResult:
    """
    Result from each pipeline stage.
    Contains the processed fields and stage metadata.
    """
    fields: Dict[str, FieldData]
    stage: ProcessingStage
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.utcnow())
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage/API responses"""
        return {
            'fields': {k: v.to_dict() for k, v in self.fields.items()},
            'stage': self.stage.value,
            'metadata': self.metadata,
            'timestamp': self.timestamp.isoformat()
        }
    
    def get_field_values(self) -> Dict[str, str]:
        """Get just the field values for quick access"""
        return {k: v.value for k, v in self.fields.items()}
    
    def get_fields_needing_review(self) -> List[str]:
        """Get list of fields that need human review"""
        return [k for k, v in self.fields.items() if v.requires_human_review]


@dataclass
class EnhancerResult:
    """
    Result from a single enhancer operation.
    Tracks what changed and why.
    """
    enhancer_name: str
    fields_modified: List[str]
    fields_added: List[str]
    success: bool = True
    error: Optional[str] = None
    duration_ms: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/debugging"""
        return {
            'enhancer_name': self.enhancer_name,
            'fields_modified': self.fields_modified,
            'fields_added': self.fields_added,
            'success': self.success,
            'error': self.error,
            'duration_ms': self.duration_ms
        }
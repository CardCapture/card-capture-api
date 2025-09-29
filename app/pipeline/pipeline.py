"""
Main card processing pipeline
"""
import os
import tempfile
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

from app.pipeline.models import (
    PipelineContext, ProcessingResult, ProcessingStage, 
    FieldData, EnhancerResult
)
from app.pipeline.enhancers.base import FieldEnhancer
from app.pipeline.enhancers.canonical_field_mapper import CanonicalFieldMapperEnhancer
from app.pipeline.enhancers.field_splitter import FieldSplitterEnhancer
from app.pipeline.enhancers.address_validator import AddressValidationEnhancer
from app.pipeline.enhancers.high_school_matcher import HighSchoolMatcherEnhancer
from app.pipeline.enhancers.data_cleaner import DataCleanerEnhancer
from app.pipeline.enhancers.field_requirements import FieldRequirementsEnhancer

from app.services.docai_service import process_image_with_docai
from app.services.gemini_service import process_card_with_gemini_v2
from app.services.settings_service import get_field_requirements, sync_field_requirements
from app.services.review_service import determine_review_status, validate_field_data
from app.core.clients import get_supabase_client
from app.utils.field_utils import filter_combined_fields
from app.utils.retry_utils import log_debug


class CardProcessingPipeline:
    """
    Main card processing pipeline.
    
    Orchestrates the three-stage processing:
    1. Extraction (DocAI + Gemini)
    2. Enhancement (Field processing via enhancers)
    3. Review (Final validation and review determination)
    """
    
    def __init__(self):
        self.enhancers = self._initialize_enhancers()
        
    def _initialize_enhancers(self) -> List[FieldEnhancer]:
        """
        Initialize enhancers in the correct order.
        
        Order matters! Some enhancers depend on others:
        1. Map field names to canonical format first
        2. Split combined fields into components
        3. Apply field requirements to know what's enabled/required
        4. Clean data before validation
        5. Validate addresses and schools
        """
        return [
            CanonicalFieldMapperEnhancer(),  # Map legacy field names to canonical format
            FieldSplitterEnhancer(),         # Split combined fields into components
            FieldRequirementsEnhancer(),     # Apply school settings for enabled/required
            DataCleanerEnhancer(),           # Clean and format data
            AddressValidationEnhancer(),     # Validate addresses with Google Maps
            HighSchoolMatcherEnhancer(),     # Match high schools and add CEEB codes
        ]
    
    def process(self, image_path: str, school_id: str, user_id: str,
                event_id: Optional[str] = None, original_storage_path: Optional[str] = None) -> ProcessingResult:
        """
        Main processing entry point.
        
        Args:
            image_path: Path to the image to process
            school_id: School ID for settings
            user_id: User ID
            event_id: Optional event ID
            
        Returns:
            ProcessingResult with final processed fields
        """
        log_debug("=== CARD PROCESSING PIPELINE START ===", {
            "school_id": school_id,
            "user_id": user_id,
            "event_id": event_id,
            "image_path": os.path.basename(image_path)
        }, service="pipeline")
        
        # Build processing context
        context = self._build_context(school_id, user_id, event_id, image_path, original_storage_path)
        
        # Stage 1: Extraction
        log_debug("=== STAGE 1: EXTRACTION ===", service="pipeline")
        extraction_result = self._extract(image_path, context)
        
        # Stage 2: Enhancement 
        log_debug("=== STAGE 2: ENHANCEMENT ===", service="pipeline")
        enhanced_result = self._enhance(extraction_result, context)
        
        # Stage 3: Review Preparation
        log_debug("=== STAGE 3: REVIEW PREPARATION ===", service="pipeline")
        final_result = self._prepare_for_review(enhanced_result, context)
        
        log_debug("=== CARD PROCESSING PIPELINE COMPLETE ===", {
            "review_status": final_result.metadata.get("review_status"),
            "fields_needing_review": final_result.metadata.get("fields_needing_review"),
            "total_fields": len(final_result.fields)
        }, service="pipeline")
        
        return final_result
        
    def _build_context(self, school_id: str, user_id: str, event_id: Optional[str],
                      image_path: str, original_storage_path: Optional[str] = None) -> PipelineContext:
        """Build pipeline context with school settings and requirements"""
        
        # Get school data
        supabase = get_supabase_client()
        school_query = supabase.table("schools").select("majors").eq("id", school_id).maybe_single().execute()
        valid_majors = school_query.data.get("majors", []) if school_query.data else []
        
        # Get field requirements
        field_requirements = get_field_requirements(school_id)
        
        log_debug("Built pipeline context", {
            "valid_majors_count": len(valid_majors),
            "field_requirements_count": len(field_requirements)
        }, service="pipeline")
        
        return PipelineContext(
            school_id=school_id,
            user_id=user_id,
            event_id=event_id,
            image_path=image_path,
            original_storage_path=original_storage_path,
            valid_majors=valid_majors,
            field_requirements=field_requirements
        )
    
    def _extract(self, image_path: str, context: PipelineContext) -> ProcessingResult:
        """
        Extraction stage - get raw data from DocAI and Gemini.
        
        This stage does minimal processing, just extracts data.
        """
        # Get DocAI processor ID for school
        supabase = get_supabase_client()
        school_query = supabase.table("schools").select("docai_processor_id").eq("id", context.school_id).maybe_single().execute()
        from app.config import DOCAI_PROCESSOR_ID
        processor_id = school_query.data.get("docai_processor_id") if school_query.data else DOCAI_PROCESSOR_ID
        
        # Run DocAI
        log_debug("Running DocAI extraction", {"processor_id": processor_id}, service="pipeline")
        docai_fields, cropped_image_path = process_image_with_docai(
            image_path,
            processor_id,
            original_storage_path=context.original_storage_path
        )
        
        # Run Gemini for enhancement
        log_debug("Running Gemini enhancement", {
            "docai_field_count": len(docai_fields),
            "valid_majors_count": len(context.valid_majors)
        }, service="pipeline")
        
        # Convert DocAI fields to proper format for Gemini
        docai_for_gemini = {}
        for key, data in docai_fields.items():
            if isinstance(data, dict):
                docai_for_gemini[key] = data
        
        gemini_fields = process_card_with_gemini_v2(
            cropped_image_path,
            docai_for_gemini,
            context.valid_majors
        )
        
        # Convert to FieldData objects (prefer Gemini over DocAI)
        fields = {}
        
        # Start with DocAI fields as base
        for key, data in docai_fields.items():
            if isinstance(data, dict):
                fields[key] = FieldData(
                    value=data.get('value', ''),
                    confidence=data.get('confidence', 0.0),
                    source=data.get('source', 'docai'),
                    enabled=data.get('enabled', True),
                    required=data.get('required', False),
                    original_value=data.get('original_value')
                )
        
        # Override with Gemini fields (they're usually better)
        for key, data in gemini_fields.items():
            if isinstance(data, dict):
                fields[key] = FieldData(
                    value=data.get('value', ''),
                    confidence=data.get('confidence', 0.0),
                    source=data.get('source', 'gemini'),
                    enabled=data.get('enabled', True),
                    required=data.get('required', False),
                    original_value=data.get('original_value')
                )
        
        log_debug("Extraction complete", {
            "total_fields": len(fields),
            "field_names": list(fields.keys())[:10]  # Log first 10
        }, service="pipeline")
        
        return ProcessingResult(
            fields=fields,
            stage=ProcessingStage.EXTRACTION,
            metadata={
                "cropped_image_path": cropped_image_path,
                "docai_field_count": len(docai_fields),
                "gemini_field_count": len(gemini_fields)
            }
        )
    
    def _enhance(self, extraction_result: ProcessingResult, context: PipelineContext) -> ProcessingResult:
        """
        Enhancement stage - apply all enhancers in sequence.
        """
        fields = extraction_result.fields.copy()
        enhancer_results = []
        
        # Sync field requirements based on discovered fields
        discovered_fields = list(fields.keys())
        log_debug("Syncing field requirements", {
            "discovered_field_count": len(discovered_fields)
        }, service="pipeline")
        
        try:
            updated_requirements = sync_field_requirements(context.school_id, discovered_fields)
            # Update context with latest requirements
            context = context.with_metadata(updated_field_requirements=updated_requirements)
        except Exception as e:
            log_debug(f"Failed to sync field requirements: {e}", service="pipeline")
        
        # Run each enhancer
        for enhancer in self.enhancers:
            try:
                fields, result = enhancer.execute(fields, context)
                enhancer_results.append(result)
                
                if not result.success:
                    log_debug(f"Enhancer {enhancer.name} failed but pipeline continues", {
                        "error": result.error
                    }, service="pipeline")
                    
            except Exception as e:
                log_debug(f"Enhancer {enhancer.name} crashed: {e}", service="pipeline")
                # Continue with other enhancers
                enhancer_results.append(EnhancerResult(
                    enhancer_name=enhancer.name,
                    fields_modified=[],
                    fields_added=[],
                    success=False,
                    error=str(e)
                ))
        
        # Calculate total enhancement stats
        total_modified = sum(len(r.fields_modified) for r in enhancer_results)
        total_added = sum(len(r.fields_added) for r in enhancer_results)
        successful_enhancers = sum(1 for r in enhancer_results if r.success)
        
        log_debug("Enhancement stage complete", {
            "enhancers_run": len(enhancer_results),
            "enhancers_successful": successful_enhancers,
            "total_fields_modified": total_modified,
            "total_fields_added": total_added,
            "final_field_count": len(fields)
        }, service="pipeline")
        
        return ProcessingResult(
            fields=fields,
            stage=ProcessingStage.ENHANCEMENT,
            metadata={
                **extraction_result.metadata,
                "enhancer_results": [r.to_dict() for r in enhancer_results],
                "enhancement_stats": {
                    "total_modified": total_modified,
                    "total_added": total_added,
                    "successful_enhancers": successful_enhancers
                }
            }
        )
    
    def _prepare_for_review(self, enhanced_result: ProcessingResult, context: PipelineContext) -> ProcessingResult:
        """
        Review preparation stage - final validation and review determination.
        """
        fields = enhanced_result.fields
        
        # Convert to legacy format for existing review service
        fields_dict = {}
        for key, field_data in fields.items():
            fields_dict[key] = field_data.to_dict()
        
        # Run final field validation
        log_debug("Running final field validation", service="pipeline")
        validated_fields_dict = validate_field_data(fields_dict)
        
        # Determine review status
        log_debug("Determining review status", service="pipeline")
        review_status, fields_needing_review = determine_review_status(validated_fields_dict)
        
        # Filter out combined fields that shouldn't be saved
        log_debug("Filtering combined fields", service="pipeline")
        log_debug("Fields before filtering", {
            "count": len(validated_fields_dict),
            "has_ceeb": "ceeb_code" in validated_fields_dict,
            "field_names": list(validated_fields_dict.keys())
        }, service="pipeline")
        final_fields_dict = filter_combined_fields(validated_fields_dict)
        log_debug("Fields after filtering", {
            "count": len(final_fields_dict),
            "has_ceeb": "ceeb_code" in final_fields_dict,
            "filtered_out_count": len(validated_fields_dict) - len(final_fields_dict)
        }, service="pipeline")
        
        # Convert back to FieldData objects
        final_fields = {}
        for key, data in final_fields_dict.items():
            final_fields[key] = FieldData.from_dict(data)
        
        log_debug("Review preparation complete", {
            "review_status": review_status,
            "fields_needing_review": fields_needing_review,
            "final_field_count": len(final_fields),
            "filtered_out_count": len(validated_fields_dict) - len(final_fields_dict)
        }, service="pipeline")
        
        return ProcessingResult(
            fields=final_fields,
            stage=ProcessingStage.REVIEW,
            metadata={
                **enhanced_result.metadata,
                "review_status": review_status,
                "fields_needing_review": fields_needing_review,
                "validation_applied": True,
                "combined_fields_filtered": True
            }
        )
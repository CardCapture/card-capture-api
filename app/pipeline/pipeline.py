"""
Main card processing pipeline
"""
import os
import tempfile
from typing import List, Dict, Any, Optional, Tuple
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

        # If we found an existing student, skip enhancers and return as-is
        # The existing student data is already validated and clean
        if extraction_result.metadata.get("skipped_gemini"):
            log_debug("=== SKIPPING ENHANCEMENT & REVIEW (Existing Student) ===", {
                "student_id": extraction_result.metadata.get("student_id"),
                "reason": "Using existing student data from database"
            }, service="pipeline")

            # Existing students still need manual review approval
            extraction_result.metadata["review_status"] = "needs_review"
            extraction_result.metadata["fields_needing_review"] = []

            log_debug("=== CARD PROCESSING PIPELINE COMPLETE ===", {
                "review_status": "needs_review",
                "fields_needing_review": [],
                "total_fields": len(extraction_result.fields),
                "skipped_stages": ["enhancement", "review"]
            }, service="pipeline")

            return extraction_result

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

        For universal cards with serial numbers:
        1. DocAI extracts serial number from OCR
        2. Check if student exists by serial
        3. If exists → Skip Gemini, use existing data
        4. If not exists → Run Gemini as normal
        """
        # Read school extraction settings (resilient to the vision-only columns
        # not existing yet, so the DocAI path is unaffected before migration).
        school_row, _vision_columns_available = self._get_school_extraction_settings(context.school_id)

        # Feature flag: per-school vision-only extraction (DocAI removal).
        from app.config import VISION_ONLY_EXTRACTION_DEFAULT
        use_vision_only = school_row.get("use_vision_only_extraction")
        if use_vision_only is None:
            use_vision_only = VISION_ONLY_EXTRACTION_DEFAULT

        if use_vision_only:
            return self._extract_vision_only(image_path, context, school_row)

        # ---- DocAI + Gemini path (unchanged when the flag is off) ----
        # Get DocAI processor ID for school (fall back to default universal card processor if not set)
        from app.config import DOCAI_PROCESSOR_ID
        processor_id = school_row.get("docai_processor_id") or DOCAI_PROCESSOR_ID

        # Run DocAI (now returns 4 values including serial number)
        log_debug("Running DocAI extraction", {"processor_id": processor_id}, service="pipeline")
        docai_fields, cropped_image_path, ocr_text, serial_number = process_image_with_docai(
            image_path,
            processor_id,
            original_storage_path=context.original_storage_path
        )

        # Check for existing student if serial number found
        if serial_number:
            from app.repositories.students_repository import get_student_by_serial

            log_debug(f"🔍 Serial number detected: {serial_number}, checking for existing student", service="pipeline")
            existing_student = get_student_by_serial(serial_number)

            if existing_student:
                # JACKPOT! Use existing student data, skip Gemini
                log_debug(f"🎯 Found existing student! Skipping Gemini to save cost.", {
                    "serial": serial_number,
                    "student_id": existing_student["id"],
                    "name": f"{existing_student.get('first_name')} {existing_student.get('last_name')}"
                }, service="pipeline")

                return self._create_result_from_existing_student(existing_student, serial_number, cropped_image_path, context)
            else:
                log_debug(f"Serial {serial_number} not in database - will run full pipeline and create student", service="pipeline")
                # Store serial in context for later use
                context.metadata["serial_number"] = serial_number
        
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

        # Build extraction metadata
        extraction_metadata = {
            "cropped_image_path": cropped_image_path,
            "docai_field_count": len(docai_fields),
            "gemini_field_count": len(gemini_fields)
        }

        # Include serial number if found
        if serial_number:
            extraction_metadata["serial_number"] = serial_number

        return ProcessingResult(
            fields=fields,
            stage=ProcessingStage.EXTRACTION,
            metadata=extraction_metadata
        )

    def _get_school_extraction_settings(self, school_id: str) -> Tuple[Dict[str, Any], bool]:
        """
        Read extraction-related school settings.

        Resilient to the vision-only columns (use_vision_only_extraction,
        suggested_card_fields) not existing yet, so the DocAI path is completely
        unaffected before the migration runs. Returns (row, vision_columns_available).
        """
        supabase = get_supabase_client()
        try:
            res = (
                supabase.table("schools")
                .select("docai_processor_id, card_fields, use_vision_only_extraction, suggested_card_fields")
                .eq("id", school_id)
                .maybe_single()
                .execute()
            )
            return (res.data or {}), True
        except Exception as e:
            log_debug(f"Vision-only columns unavailable, falling back to DocAI settings: {e}", service="pipeline")
            res = (
                supabase.table("schools")
                .select("docai_processor_id, card_fields")
                .eq("id", school_id)
                .maybe_single()
                .execute()
            )
            return (res.data or {}), False

    def _extract_vision_only(self, image_path: str, context: PipelineContext, school_row: Dict[str, Any]) -> ProcessingResult:
        """
        Vision-only extraction (DocAI removal path), gated by the per-school
        use_vision_only_extraction flag.

        Sends the card image to Gemini with the streamlined prompt, corrects
        orientation, and returns the same FieldData shape as the DocAI path so
        the enhancement and review stages are unaffected. No serial-number
        short-circuit (Option A): repeat cards pay full Gemini cost.
        """
        from app.utils.image_processing import ensure_proper_orientation
        from app.services.gemini_vision_service import (
            process_card_with_gemini_vision,
            apply_orientation_correction,
        )

        card_fields = school_row.get("card_fields") or []

        # Layer 1: bake in EXIF orientation / HEIC conversion (no DocAI needed).
        working_path = ensure_proper_orientation(image_path)

        log_debug("Running vision-only extraction", {
            "configured_field_count": len(card_fields),
            "valid_majors_count": len(context.valid_majors),
        }, service="pipeline")

        vision_result = process_card_with_gemini_vision(
            working_path,
            card_fields,
            context.valid_majors,
        )
        gemini_fields = vision_result.get("fields", {})
        rotation_degrees = vision_result.get("image_rotation_degrees", 0)
        discovered_keys = vision_result.get("discovered_keys", [])

        # Layer 2: content-based orientation correction (replaces DocAI OCR
        # rotation). First-pass rotation from extraction is verified with a
        # cheap second pass (catches the 180 flip), then the upright image is
        # re-saved so the review modal displays it correctly. The modal also has
        # a manual rotate control as a final fallback.
        orientation_info = apply_orientation_correction(
            working_path, rotation_degrees, context.original_storage_path
        )
        orientation_corrected = orientation_info.get("uploaded", False)
        applied_rotation = orientation_info.get("applied_degrees", rotation_degrees)

        # Convert to FieldData objects (same mapping as the DocAI path so
        # downstream behavior is identical).
        fields: Dict[str, FieldData] = {}
        for key, data in gemini_fields.items():
            if isinstance(data, dict):
                fields[key] = FieldData(
                    value=data.get("value", ""),
                    confidence=data.get("confidence", 0.0),
                    source=data.get("source", "gemini"),
                    enabled=data.get("enabled", True),
                    required=data.get("required", False),
                    original_value=data.get("original_value"),
                )

        # Capture discovered (unconfigured) fields as onboarding suggestions.
        if discovered_keys:
            try:
                self._record_field_suggestions(context.school_id, school_row, discovered_keys, gemini_fields)
            except Exception as e:
                log_debug(f"Failed to record field suggestions: {e}", service="pipeline")

        log_debug("Vision-only extraction complete", {
            "total_fields": len(fields),
            "first_pass_rotation": rotation_degrees,
            "applied_rotation": applied_rotation,
            "orientation_corrected": orientation_corrected,
            "discovered_keys": discovered_keys,
        }, service="pipeline")

        return ProcessingResult(
            fields=fields,
            stage=ProcessingStage.EXTRACTION,
            metadata={
                "extraction_mode": "vision_only",
                "gemini_field_count": len(gemini_fields),
                "image_rotation_degrees": rotation_degrees,
                "applied_rotation_degrees": applied_rotation,
                "orientation": orientation_info,
                "orientation_corrected": orientation_corrected,
                "discovered_field_keys": discovered_keys,
            },
        )

    def _record_field_suggestions(
        self,
        school_id: str,
        school_row: Dict[str, Any],
        discovered_keys: list,
        gemini_fields: Dict[str, Any],
    ) -> None:
        """
        Persist discovered (unconfigured) fields to schools.suggested_card_fields
        so they can be reviewed and accepted into card_fields later. Never adds a
        field already configured or already suggested.
        """
        from app.utils.field_utils import generate_field_label

        supabase = get_supabase_client()
        existing = school_row.get("suggested_card_fields") or []
        if not isinstance(existing, list):
            existing = []
        existing_keys = {s.get("key") for s in existing if isinstance(s, dict)}
        configured_keys = {
            f.get("key") for f in (school_row.get("card_fields") or []) if isinstance(f, dict)
        }

        added = False
        for key in discovered_keys:
            if not key or key in existing_keys or key in configured_keys:
                continue
            fd = gemini_fields.get(key, {}) or {}
            existing.append({
                "key": key,
                "label": generate_field_label(key),
                "field_type": fd.get("field_type", "text"),
                "sample_value": fd.get("value", ""),
            })
            existing_keys.add(key)
            added = True

        if added:
            supabase.table("schools").update(
                {"suggested_card_fields": existing}
            ).eq("id", school_id).execute()
            log_debug("Recorded new field suggestions", {"keys": sorted(existing_keys)}, service="pipeline")

    def _create_result_from_existing_student(
        self,
        student: Dict[str, Any],
        serial_number: str,
        cropped_image_path: Optional[str],
        context: PipelineContext
    ) -> ProcessingResult:
        """
        Create extraction result from existing student record.
        This is used when we find a universal card with a serial that already exists.
        Skips Gemini to save cost and time.
        """
        from app.services.students_service import _student_to_reviewed_fields

        log_debug("Converting existing student to field structure", {
            "student_id": student["id"]
        }, service="pipeline")

        # Convert student columns to field dict
        fields_dict = _student_to_reviewed_fields(student)

        # Convert to FieldData objects for pipeline
        fields = {}
        for field_name, field_value in fields_dict.items():
            if isinstance(field_value, dict) and "value" in field_value:
                fields[field_name] = FieldData(
                    value=field_value["value"],
                    confidence=field_value.get("confidence", 1.0),
                    source=field_value.get("source", "student_self"),
                    enabled=field_value.get("enabled", True),
                    required=field_value.get("required", False),
                    requires_human_review=field_value.get("requires_review", False),
                    original_value=field_value.get("original_value")
                )

        # Add serial number field if not present
        if "serial_number" not in fields:
            fields["serial_number"] = FieldData(
                value=serial_number,
                confidence=1.0,
                source="docai_ocr",
                enabled=True,
                required=False,
                requires_human_review=False,
                original_value=serial_number
            )

        return ProcessingResult(
            fields=fields,
            stage=ProcessingStage.EXTRACTION,
            metadata={
                "source": "existing_student",
                "student_id": student["id"],
                "serial_number": serial_number,
                "skipped_gemini": True,
                "cropped_image_path": cropped_image_path,
                "cost_saved": "$0.003"  # Typical Gemini API call cost
            }
        )

    def _enhance(self, extraction_result: ProcessingResult, context: PipelineContext) -> ProcessingResult:
        """
        Enhancement stage - apply all enhancers in sequence.
        """
        fields = extraction_result.fields.copy()
        enhancer_results = []
        
        # DISABLED: Auto-discovery of new fields
        # This was automatically adding every detected field to school's card_fields,
        # causing junk fields to appear in settings. Schools will now manage their
        # field list manually via settings UI.
        #
        # discovered_fields = list(fields.keys())
        # log_debug("Syncing field requirements", {
        #     "discovered_field_count": len(discovered_fields)
        # }, service="pipeline")
        #
        # try:
        #     updated_requirements = sync_field_requirements(context.school_id, discovered_fields)
        #     # Update context with latest requirements
        #     context = context.with_metadata(updated_field_requirements=updated_requirements)
        # except Exception as e:
        #     log_debug(f"Failed to sync field requirements: {e}", service="pipeline")
        
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
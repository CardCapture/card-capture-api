"""
Sign-up sheet processing pipeline.

Integrates sign-up sheet data into the same 6-stage enhancement pipeline
as inquiry cards for consistent data quality.
"""

from typing import List, Dict, Any
from app.pipeline.models import FieldData, ProcessingResult, ProcessingStage, PipelineContext
from app.pipeline.enhancers.canonical_field_mapper import CanonicalFieldMapperEnhancer
from app.pipeline.enhancers.field_splitter import FieldSplitterEnhancer
from app.pipeline.enhancers.field_requirements import FieldRequirementsEnhancer
from app.pipeline.enhancers.data_cleaner import DataCleanerEnhancer
from app.pipeline.enhancers.address_validator import AddressValidationEnhancer
from app.pipeline.enhancers.high_school_matcher import HighSchoolMatcherEnhancer
from app.utils.retry_utils import log_debug


class SignupSheetPipeline:
    """
    Pipeline for processing sign-up sheets through the same
    enhancement pipeline as inquiry cards.

    Converts Gemini two-pass output → FieldData → Enhanced via 6 enhancers → ProcessingResult
    """

    def __init__(self):
        """Initialize enhancer chain (same as inquiry cards)"""
        self.enhancers = [
            CanonicalFieldMapperEnhancer(),  # 1. Standardize field names
            FieldSplitterEnhancer(),         # 2. Split combined fields
            FieldRequirementsEnhancer(),     # 3. Apply school settings
            DataCleanerEnhancer(),           # 4. Clean/format data
            AddressValidationEnhancer(),     # 5. Google Maps validation
            HighSchoolMatcherEnhancer(),     # 6. CEEB code matching
        ]

    async def process_records(
        self,
        enhanced_records: List[Dict],
        image_path: str,
        event_id: str,
        school_id: str,
        user_id: str,
        valid_majors: List[str],
        field_requirements: Dict[str, Any] = None
    ) -> List[ProcessingResult]:
        """
        Process enhanced sign-up sheet records through the pipeline.

        Args:
            enhanced_records: List of student records from second-pass Gemini
            image_path: Path to original sign-up sheet image
            event_id: Event ID for these records
            school_id: School ID
            user_id: User ID who uploaded
            valid_majors: List of valid majors
            field_requirements: School field configuration

        Returns:
            List of ProcessingResult objects, one per student
        """
        log_debug("=== SIGNUP PIPELINE START ===", {
            "records_count": len(enhanced_records),
            "school_id": school_id
        }, service="signup_pipeline")

        results = []

        for i, record in enumerate(enhanced_records):
            row_number = record.get('row_number', i + 1)

            log_debug(f"Processing row {row_number}...", service="signup_pipeline")

            # Process this single record through pipeline
            result = await self._process_single_record(
                record,
                row_number,
                image_path,
                event_id,
                school_id,
                user_id,
                valid_majors,
                field_requirements or {}
            )

            results.append(result)

        log_debug(f"=== SIGNUP PIPELINE COMPLETE ===", {
            "records_processed": len(results)
        }, service="signup_pipeline")

        return results

    async def _process_single_record(
        self,
        record: Dict,
        row_number: int,
        image_path: str,
        event_id: str,
        school_id: str,
        user_id: str,
        valid_majors: List[str],
        field_requirements: Dict[str, Any]
    ) -> ProcessingResult:
        """Process a single sign-up sheet row through enhancement pipeline"""

        # Step 1: Convert Gemini enhanced record to FieldData format
        fields = self._convert_record_to_fields(record)

        # Step 2: Build pipeline context
        context = PipelineContext(
            school_id=school_id,
            user_id=user_id,
            event_id=event_id,
            image_path=image_path,
            valid_majors=valid_majors,
            field_requirements=field_requirements,
            metadata={
                "source": "signup_sheet",
                "row_number": row_number,
                "upload_type": "signup_sheet"
            }
        )

        # Step 3: Create extraction result (simulating DocAI extraction stage)
        extraction_result = ProcessingResult(
            fields=fields,
            stage=ProcessingStage.EXTRACTION,
            metadata={
                "source": "gemini_two_pass",
                "row_number": row_number,
                "enhancer_results": []
            }
        )

        # Step 4: Run through enhancement pipeline
        enhanced_result = await self._enhance(extraction_result, context)

        # Step 5: Prepare for review (determine review status)
        final_result = self._prepare_for_review(enhanced_result, context)

        return final_result

    def _convert_record_to_fields(self, record: Dict) -> Dict[str, FieldData]:
        """
        Convert Gemini enhanced record to FieldData objects.

        Input format (from second-pass Gemini):
        {
            "row_number": 1,
            "first_name": {
                "value": "John",
                "edit_made": true,
                "edit_type": "ocr_correction",
                "original_value": "J0hn",
                "text_clarity": "clear",
                "certainty": "certain",
                "notes": "Fixed OCR error",
                "confidence": 0.95,
                "requires_human_review": false
            }
        }

        Output format (FieldData):
        {
            "first_name": FieldData(
                value="John",
                confidence=0.95,
                source="gemini_signup",
                original_value="J0hn",
                requires_human_review=false,
                metadata={...quality indicators...}
            )
        }
        """
        fields = {}

        for field_name, field_value in record.items():
            # Skip row_number (metadata, not a data field)
            if field_name == 'row_number':
                continue

            # Handle enhanced field objects (from second pass)
            if isinstance(field_value, dict) and 'value' in field_value:
                # Extract quality indicators for metadata
                quality_metadata = {
                    'edit_made': field_value.get('edit_made', False),
                    'edit_type': field_value.get('edit_type', 'none'),
                    'text_clarity': field_value.get('text_clarity', 'clear'),
                    'certainty': field_value.get('certainty', 'certain'),
                    'notes': field_value.get('notes', ''),
                    'gemini_confidence': field_value.get('confidence', 0.85)
                }

                # Create FieldData object
                fields[field_name] = FieldData(
                    value=field_value.get('value', ''),
                    confidence=field_value.get('confidence', 0.85),
                    source="gemini_signup",
                    original_value=field_value.get('original_value', field_value.get('value', '')),
                    requires_human_review=field_value.get('requires_human_review', True),
                    review_notes=field_value.get('review_notes', field_value.get('notes', '')),
                    metadata=quality_metadata
                )

            # Handle simple string values (shouldn't happen with second pass, but safeguard)
            elif isinstance(field_value, str):
                fields[field_name] = FieldData(
                    value=field_value,
                    confidence=0.85,
                    source="gemini_signup",
                    requires_human_review=True,
                    review_notes="Extracted from handwritten signup sheet"
                )

        return fields

    async def _enhance(
        self,
        extraction_result: ProcessingResult,
        context: PipelineContext
    ) -> ProcessingResult:
        """
        Run through enhancement stage (6 enhancers).
        Same logic as inquiry card pipeline.
        """
        log_debug("Running enhancement pipeline...", {
            "row_number": context.metadata.get('row_number'),
            "enhancer_count": len(self.enhancers)
        }, service="signup_pipeline")

        fields = extraction_result.fields.copy()
        enhancer_results = []

        # Run each enhancer in sequence
        for enhancer in self.enhancers:
            try:
                log_debug(f"Running {enhancer.__class__.__name__}...", service="signup_pipeline")

                # Execute enhancer
                fields, result = enhancer.execute(fields, context)
                enhancer_results.append(result)

                log_debug(f"✅ {enhancer.__class__.__name__} complete", {
                    "fields_modified": len(result.fields_modified),
                    "fields_added": len(result.fields_added)
                }, service="signup_pipeline")

            except Exception as e:
                log_debug(f"❌ {enhancer.__class__.__name__} failed: {str(e)}", service="signup_pipeline")
                # Continue with other enhancers even if one fails
                continue

        # Create enhancement result
        enhanced_result = ProcessingResult(
            fields=fields,
            stage=ProcessingStage.ENHANCEMENT,
            metadata={
                **extraction_result.metadata,
                "enhancer_results": [r.to_dict() for r in enhancer_results],
                "enhancement_stats": {
                    "total_modified": sum(len(r.fields_modified) for r in enhancer_results),
                    "total_added": sum(len(r.fields_added) for r in enhancer_results),
                    "successful_enhancers": sum(1 for r in enhancer_results if r.success)
                }
            }
        )

        return enhanced_result

    def _prepare_for_review(
        self,
        enhanced_result: ProcessingResult,
        context: PipelineContext
    ) -> ProcessingResult:
        """
        Prepare for review stage - determine review status.
        Same logic as inquiry card pipeline.
        """
        log_debug("Preparing for review...", {
            "row_number": context.metadata.get('row_number')
        }, service="signup_pipeline")

        fields = enhanced_result.fields
        fields_needing_review = []

        # Check which fields need human review
        for field_name, field_data in fields.items():
            if field_data.requires_human_review:
                fields_needing_review.append(field_name)

        # Determine overall review status - always require manual review
        review_status = "needs_review"

        # Create final result
        final_result = ProcessingResult(
            fields=fields,
            stage=ProcessingStage.REVIEW,
            metadata={
                **enhanced_result.metadata,
                "review_status": review_status,
                "fields_needing_review": fields_needing_review,
                "review_field_count": len(fields_needing_review),
                "total_field_count": len(fields)
            }
        )

        log_debug(f"Review status: {review_status}", {
            "fields_needing_review": len(fields_needing_review),
            "total_fields": len(fields)
        }, service="signup_pipeline")

        return final_result

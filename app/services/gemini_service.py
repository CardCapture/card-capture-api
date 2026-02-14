from datetime import datetime, timezone
import os
from app.core.clients import supabase_client
from app.repositories.reviewed_data_repository import upsert_reviewed_data
from app.repositories.extracted_data_repository import get_extracted_data_by_document_id
import traceback
import json
import re
import time
from typing import Dict, Any, Tuple, Callable
from app.core.gemini_prompt import GEMINI_PROMPT_TEMPLATE
from app.config import GEMINI_MODEL, GEMINI_GENERATION_CONFIG
from app.utils.retry_utils import retry_with_exponential_backoff, log_debug
import mimetypes

def process_card_with_gemini_v2(image_path: str, docai_fields: Dict[str, Any], valid_majors: list = None) -> Dict[str, Any]:
    """
    Enhanced Gemini processing that uses quality indicators instead of confidence self-assessment
    
    Args:
        image_path: Path to the cropped image
        docai_fields: Fields from DocAI with requirements applied
        valid_majors: List of valid majors for mapped_major logic
        
    Returns:
        Enhanced field data with computed confidence scores
    """
    log_debug("=== GEMINI PROCESSING V2 START ===", service="gemini")
    log_debug(f"Image path: {image_path}", service="gemini")
    log_debug("Input DocAI fields", {
        field_name: {
            "value": field_data.get("value", ""),
            "required": field_data.get("required", False),
            "enabled": field_data.get("enabled", True)
        }
        for field_name, field_data in docai_fields.items()
    }, service="gemini")
    
    # Track critical fields before processing
    critical_fields = ["cell", "date_of_birth"]
    log_debug("🔍 CRITICAL FIELDS BEFORE GEMINI", {
        field: {
            "value": docai_fields.get(field, {}).get("value"),
            "original_value": docai_fields.get(field, {}).get("original_value"),
            "source": docai_fields.get(field, {}).get("source")
        }
        for field in critical_fields
    }, service="gemini")
    
    if valid_majors is None:
        valid_majors = []
    try:
        # Configure Gemini
        api_key = os.getenv("GEMINI_API_KEY")
        log_debug(f"GEMINI_API_KEY present: {bool(api_key)}", service="gemini")
        if not api_key:
            raise Exception("GEMINI_API_KEY not found in environment variables")
            
        log_debug("Configuring Gemini with API key...", service="gemini")
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        log_debug("Gemini configured successfully", service="gemini")
        
        log_debug("Initializing Gemini model...", service="gemini")
        log_debug(f"Using model: {GEMINI_MODEL}", service="gemini")
        model = genai.GenerativeModel(GEMINI_MODEL, generation_config=GEMINI_GENERATION_CONFIG)
        log_debug("Gemini model initialized successfully", service="gemini")
        
        # Prepare input for Gemini (fields + valid_majors)
        log_debug("Preparing input for Gemini...", service="gemini")
        gemini_input = {
            "fields": {
                field_name: {
                    "value": field_data.get("value", ""),
                    "confidence": field_data.get("confidence", 0.0),
                    "required": field_data.get("required", False),
                    "enabled": field_data.get("enabled", True)
                }
                for field_name, field_data in docai_fields.items() if field_data.get("enabled", True)
            },
            "valid_majors": valid_majors
        }
        
        log_debug("Gemini input prepared", gemini_input, service="gemini")
        
        # 🔍 TRACK CRITICAL FIELDS: Log what's being sent to Gemini
        log_debug("🔍 CRITICAL FIELDS BEING SENT TO GEMINI", {
            field_name: gemini_input["fields"].get(field_name)
            for field_name in critical_fields
            if field_name in gemini_input["fields"]
        }, service="gemini")
        
        # Create prompt
        log_debug("Creating prompt for Gemini...", service="gemini")
        
        # Conditionally modify prompt based on whether school has majors
        if valid_majors:
            # Use full prompt with mapped_major instructions
            prompt = GEMINI_PROMPT_TEMPLATE.format(
                all_fields_json=json.dumps(gemini_input["fields"], indent=2).replace("{", "{{").replace("}", "}}"),
                list_of_valid_majors=json.dumps(valid_majors, indent=2).replace("{", "{{").replace("}", "}}")
            )
        else:
            # Use modified prompt without mapped_major instructions
            modified_template = GEMINI_PROMPT_TEMPLATE.replace(
                "✅ Always include the mapped_major field.", 
                "✅ Only include fields that are relevant to this card."
            ).replace(
                "**Mapped Major** – Use the provided valid_majors list to match the `mapped_major` to the major on the card. IMPORTANT: Always preserve the original `major` field value exactly as written on the card - do not change or null it out. Only update the separate `mapped_major` field. If no close match exists in valid_majors, leave `mapped_major` blank (the system will automatically set it to \"Undecided\"). If the original `major` field is empty, default `mapped_major` to \"Undecided\".",
                "**Major Field** – Extract the major exactly as written on the card. Do not modify or map the value."
            )
            prompt = modified_template.format(
                all_fields_json=json.dumps(gemini_input["fields"], indent=2).replace("{", "{{").replace("}", "}}"),
                list_of_valid_majors="[]"
            )
        
        log_debug("Prompt created successfully", service="gemini")

        # Read image data directly (avoids upload_file API issues)
        log_debug("Reading image data for Gemini...", service="gemini")

        # Determine MIME type
        mime_type, _ = mimetypes.guess_type(image_path)
        if not mime_type:
            # Default to JPEG if we can't determine the type
            file_ext = os.path.splitext(image_path)[1].lower()
            if file_ext in ['.jpg', '.jpeg']:
                mime_type = 'image/jpeg'
            elif file_ext in ['.png']:
                mime_type = 'image/png'
            elif file_ext in ['.gif']:
                mime_type = 'image/gif'
            elif file_ext in ['.bmp']:
                mime_type = 'image/bmp'
            elif file_ext in ['.tiff', '.tif']:
                mime_type = 'image/tiff'
            else:
                mime_type = 'image/jpeg'  # Default fallback

        log_debug(f"Detected MIME type: {mime_type} for file: {image_path}", service="gemini")

        try:
            log_debug("Reading image file data...", service="gemini")
            with open(image_path, 'rb') as f:
                image_data = f.read()
            log_debug(f"Image data read successfully ({len(image_data)} bytes)", service="gemini")
        except Exception as e:
            log_debug(f"Failed to read image file: {str(e)}", service="gemini")
            log_debug("Full traceback:", traceback.format_exc(), service="gemini")
            raise

        log_debug("Sending request to Gemini...", service="gemini")
        log_debug("Prompt being sent:", prompt, service="gemini")

        try:
            # Generate content with retry logic - pass image data directly
            log_debug("Attempting to generate content with Gemini...", service="gemini")
            response = retry_with_exponential_backoff(
                func=lambda: model.generate_content([
                    prompt,
                    {"mime_type": mime_type, "data": image_data}
                ]),
                max_retries=3,
                operation_name="Gemini content generation",
                service="gemini"
            )
            log_debug("Received response from Gemini", service="gemini")
        except Exception as e:
            log_debug(f"Failed to generate content with Gemini: {str(e)}", service="gemini")
            log_debug("Full traceback:", traceback.format_exc(), service="gemini")
            raise
        
        if not response or not response.text:
            log_debug("Empty response from Gemini", service="gemini")
            raise Exception("No response from Gemini")
        
        log_debug("Raw Gemini response", response.text, service="gemini")
        
        # 🔍 TRACK CRITICAL FIELDS: Log raw response for critical fields
        log_debug("🔍 RAW GEMINI RESPONSE - SEARCHING FOR CRITICAL FIELDS", {
            "cell_in_response": "cell" in response.text.lower(),
            "date_of_birth_in_response": "date_of_birth" in response.text.lower(),
            "birthday_in_response": "birthday" in response.text.lower(),
            "phone_in_response": "phone" in response.text.lower(),
            "response_length": len(response.text)
        }, service="gemini")
        
        # Parse response with quality indicators
        try:
            log_debug("Parsing Gemini response...", service="gemini")
            enhanced_fields = parse_gemini_quality_response(response.text, docai_fields)
            log_debug("Successfully parsed Gemini response", service="gemini")
            
            # Track critical fields after Gemini processing
            log_debug("🔍 CRITICAL FIELDS AFTER GEMINI", {
                field: {
                    "value": enhanced_fields.get(field, {}).get("value"),
                    "original_value": enhanced_fields.get(field, {}).get("original_value"),
                    "source": enhanced_fields.get(field, {}).get("source")
                }
                for field in critical_fields
            }, service="gemini")
            
            # Backend safeguard: ensure mapped_major is present only if school has majors configured
            if valid_majors and 'mapped_major' not in enhanced_fields:
                enhanced_fields['mapped_major'] = {
                    "value": "Undecided",  # Default to Undecided if missing
                    "edit_made": False,
                    "edit_type": "mapped_value",
                    "original_value": "",
                    "text_clarity": "clear",
                    "certainty": "certain",
                    "notes": "Field was missing - defaulted to Undecided",
                    "review_confidence": 0.0,
                    "requires_human_review": False,
                    "review_notes": "Automatically set to Undecided - mapped_major field was missing"
                }
                log_debug("Created missing mapped_major field with 'Undecided' default", service="gemini")
            # Backend safeguard: ensure major is user's input, not mapped value (only if school has majors)
            if valid_majors and 'major' in enhanced_fields and 'mapped_major' in enhanced_fields:
                user_major_original = (docai_fields.get('major', {}).get('value') or '').strip().lower()
                gemini_major = (enhanced_fields['major'].get('value') or '').strip().lower()
                mapped_major = (enhanced_fields['mapped_major'].get('value') or '').strip().lower()
                # If Gemini set major to a mapped value, but user input was different, restore user input
                if mapped_major and gemini_major == mapped_major and user_major_original and user_major_original != mapped_major:
                    enhanced_fields['major']['value'] = docai_fields['major']['value']
                    
                # Backend safeguard: If mapped_major is blank/empty but we have valid majors, 
                # always default to "Undecided" for unmappable majors
                if not mapped_major and valid_majors:
                    enhanced_fields['mapped_major']['value'] = "Undecided"
                    enhanced_fields['mapped_major']['review_notes'] = "Automatically set to Undecided - major could not be mapped to available options"
                    log_debug("Set mapped_major to 'Undecided' for unmappable major", {
                        "original_major": enhanced_fields['major'].get('value', ''),
                        "available_majors_count": len(valid_majors)
                    }, service="gemini")
        except json.JSONDecodeError as e:
            log_debug(f"JSON parsing error: {str(e)}", service="gemini")
            log_debug("Failed to parse response as JSON. Response text:", response.text, service="gemini")
            raise Exception(f"Invalid JSON response from Gemini: {str(e)}")
        except Exception as e:
            log_debug(f"Error parsing Gemini response: {str(e)}", service="gemini")
            log_debug("Response that caused error:", response.text, service="gemini")
            raise
        
        log_debug("Enhanced fields created", {
            field_name: {
                "value": field_data.get("value", ""),
                "confidence_score": field_data.get("review_confidence", 0.0),
                "requires_review": field_data.get("requires_human_review", False),
                "review_notes": field_data.get("review_notes", "")
            }
            for field_name, field_data in enhanced_fields.items()
        }, service="gemini")
        
        # 🔍 TRACK CRITICAL FIELDS: Final output summary
        log_debug("🔍 CRITICAL FIELDS - FINAL GEMINI OUTPUT", {
            field_name: enhanced_fields.get(field_name, "FIELD_NOT_FOUND")
            for field_name in critical_fields
        }, service="gemini")
        
        log_debug("=== GEMINI PROCESSING V2 COMPLETE ===", service="gemini")
        return enhanced_fields
        
    except Exception as e:
        log_debug(f"ERROR in Gemini processing: {str(e)}", service="gemini")
        log_debug("Full traceback:", traceback.format_exc(), service="gemini")
        # Return original fields with error flags
        for field_name, field_data in docai_fields.items():
            field_data["requires_human_review"] = True
            field_data["review_notes"] = "This field needs manual review due to a processing issue"
            field_data["review_confidence"] = 0.1
        return docai_fields

def parse_gemini_quality_response(response_text: str, docai_fields: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse Gemini's quality assessment response and enhance field data
    
    Args:
        response_text: Raw response from Gemini
        docai_fields: Original field data from DocAI
        
    Returns:
        Enhanced field data with quality assessments
    """
    log_debug("=== PARSING GEMINI QUALITY RESPONSE ===", service="gemini")
    log_debug("Raw Gemini response for parsing", response_text, service="gemini")
    
    # Track critical fields before parsing
    critical_fields = ["cell", "date_of_birth"]
    log_debug("🔍 CRITICAL FIELDS BEFORE PARSING", {
        field: {
            "value": docai_fields.get(field, {}).get("value"),
            "original_value": docai_fields.get(field, {}).get("original_value")
        }
        for field in critical_fields
    }, service="gemini")
    
    try:
        # Clean the response text by removing markdown code block markers
        cleaned_text = response_text.strip()
        if cleaned_text.startswith("```json"):
            cleaned_text = cleaned_text[7:]  # Remove ```json
        elif cleaned_text.startswith("```"):
            cleaned_text = cleaned_text[3:]   # Remove ```
        if cleaned_text.endswith("```"):
            cleaned_text = cleaned_text[:-3]  # Remove trailing ```
        cleaned_text = cleaned_text.strip()
        
        log_debug("Cleaned response text for parsing", cleaned_text, service="gemini")
        
        # 🔍 TRACK CRITICAL FIELDS: Check if fields exist in cleaned text
        log_debug("🔍 PARSER - CRITICAL FIELDS IN CLEANED TEXT", {
            "cell_in_cleaned": "cell" in cleaned_text.lower(),
            "date_of_birth_in_cleaned": "date_of_birth" in cleaned_text.lower(),
            "cleaned_text_length": len(cleaned_text),
            "cleaned_text_preview": cleaned_text[:500] + "..." if len(cleaned_text) > 500 else cleaned_text
        }, service="gemini")
        
        # Parse the response text into a dictionary
        gemini_data = json.loads(cleaned_text)
        log_debug("Parsed Gemini response", gemini_data, service="gemini")
        
        # 🔍 TRACK CRITICAL FIELDS: Check if fields exist in parsed JSON
        log_debug("🔍 PARSER - CRITICAL FIELDS IN PARSED JSON", {
            field_name: {
                "exists_in_json": field_name in gemini_data,
                "json_value": gemini_data.get(field_name, "FIELD_NOT_FOUND")
            }
            for field_name in critical_fields
        }, service="gemini")
        
        enhanced_fields = {}
        
        # Process each field from Gemini response
        for field_name, quality_info in gemini_data.items():
            # 🔍 TRACK CRITICAL FIELDS: Log processing of critical fields
            if field_name in critical_fields:
                log_debug(f"🔍 PARSER - PROCESSING CRITICAL FIELD: {field_name}", {
                    "quality_info": quality_info,
                    "docai_field_exists": field_name in docai_fields,
                    "docai_field_data": docai_fields.get(field_name, "FIELD_NOT_IN_DOCAI")
                }, service="gemini")
            
            # Start with DocAI field data if it exists
            if field_name in docai_fields:
                enhanced_field = docai_fields[field_name].copy()
            else:
                # Create new field for data not detected by DocAI
                enhanced_field = {
                    "value": "",
                    "confidence": 0.0,
                    "bounding_box": [],
                    "source": "docai",
                    "enabled": True,
                    "required": False,
                }
            
            # Update with Gemini data and preserve all quality indicators
            # Calculate enhanced confidence score
            enhanced_confidence = calculate_confidence_from_quality(quality_info)
            
            enhanced_field.update({
                "value": quality_info.get("value", ""),
                "source": "gemini",
                "confidence": enhanced_confidence,  # Use our enhanced confidence calculation
                "edit_made": quality_info.get("edit_made", False),
                "edit_type": quality_info.get("edit_type", "none"),
                "original_value": quality_info.get("original_value", ""),
                "text_clarity": quality_info.get("text_clarity", "unclear"),
                "certainty": quality_info.get("certainty", "uncertain"),
                "notes": quality_info.get("notes", ""),
                "field_type": quality_info.get("field_type", "text"),
                "detected_options": quality_info.get("detected_options", []),
                "review_confidence": enhanced_confidence,
                "requires_human_review": False,
                "review_notes": ""
            })
            
            # 🔍 TRACK CRITICAL FIELDS: Log the enhanced field for critical fields
            if field_name in critical_fields:
                log_debug(f"🔍 PARSER - ENHANCED CRITICAL FIELD: {field_name}", {
                    "final_value": enhanced_field.get("value"),
                    "final_original_value": enhanced_field.get("original_value"),
                    "final_edit_made": enhanced_field.get("edit_made"),
                    "final_source": enhanced_field.get("source"),
                    "review_confidence": enhanced_field.get("review_confidence")
                }, service="gemini")
            
            # Only determine review status for required fields
            if enhanced_field.get("required", False):
                needs_review, review_notes = determine_review_from_quality(
                    quality_info, enhanced_field
                )
                enhanced_field["requires_human_review"] = needs_review
                enhanced_field["review_notes"] = review_notes or ""
            
            enhanced_fields[field_name] = enhanced_field

        # 🔍 TRACK CRITICAL FIELDS: Final summary of critical fields from parser
        log_debug("🔍 PARSER - FINAL CRITICAL FIELDS OUTPUT", {
            field_name: {
                "found_in_output": field_name in enhanced_fields,
                "final_value": enhanced_fields.get(field_name, {}).get("value", "FIELD_NOT_FOUND"),
                "final_original_value": enhanced_fields.get(field_name, {}).get("original_value", "FIELD_NOT_FOUND")
            }
            for field_name in critical_fields
        }, service="gemini")

        log_debug("Enhanced fields after parsing Gemini response", enhanced_fields, service="gemini")
        
        # Track critical fields after parsing
        log_debug("🔍 CRITICAL FIELDS AFTER PARSING", {
            field: {
                "value": enhanced_fields.get(field, {}).get("value"),
                "original_value": enhanced_fields.get(field, {}).get("original_value")
            }
            for field in critical_fields
        }, service="gemini")
        
        return enhanced_fields
    except Exception as e:
        log_debug(f"Error parsing Gemini response: {str(e)}", service="gemini")
        log_debug("Response that caused error:", response_text, service="gemini")
        
        # 🔍 TRACK CRITICAL FIELDS: Log fallback for critical fields
        log_debug("🔍 PARSER - ERROR FALLBACK - CRITICAL FIELDS", {
            field_name: docai_fields.get(field_name, "FIELD_NOT_FOUND")
            for field_name in critical_fields
        }, service="gemini")
        
        # Fallback: return docai_fields with required keys
        for field_name, field_data in docai_fields.items():
            field_data["review_confidence"] = 0.0
            field_data["requires_human_review"] = False
            field_data["review_notes"] = ""
            field_data["edit_made"] = False
            field_data["edit_type"] = "none"
            field_data["original_value"] = field_data.get("value", "")
            field_data["text_clarity"] = "unclear"
            field_data["certainty"] = "uncertain"
            field_data["notes"] = ""
        return docai_fields

def calculate_confidence_from_quality(quality_info: Dict[str, Any]) -> float:
    """
    Convert Gemini quality indicators to a reliable confidence score
    
    Args:
        quality_info: Quality indicators from Gemini
        
    Returns:
        Confidence score between 0.0 and 1.0
    """
    text_clarity = quality_info.get("text_clarity", "unclear")
    certainty = quality_info.get("certainty", "uncertain")
    edit_type = quality_info.get("edit_type", "none")
    value = quality_info.get("value", "")
    
    # Base confidence from text clarity
    clarity_scores = {
        "clear": 0.95,
        "mostly_clear": 0.85,
        "unclear": 0.40,
        "unreadable": 0.10
    }
    
    # Certainty modifiers
    certainty_modifiers = {
        "certain": 1.0,
        "mostly_certain": 0.9,
        "uncertain": 0.5
    }
    
    # Edit type modifiers - updated to be more generous for obvious corrections
    edit_modifiers = {
        "format_correction": 1.0,        # High confidence for obvious fixes
        "ocr_correction": 0.95,          # Good confidence for clear OCR fixes
        "typo_fix": 0.95,               # High confidence for obvious typo fixes (was 0.9)
        "cross_validation_fix": 1.0,     # High confidence for fixes based on other fields
        "missing_data": 0.75,            # Medium confidence for new data
        "unclear_text": 0.3,            # Low confidence for unclear text
        "none": 1.0,                      # No penalty for no edits
        "mapped_value": 0.9 
    }
    
    # Calculate base score
    base_score = clarity_scores.get(text_clarity, 0.5)
    certainty_mod = certainty_modifiers.get(certainty, 0.5)
    edit_mod = edit_modifiers.get(edit_type, 0.5)
    
    # Empty values get low confidence
    if not value or value.strip() == "":
        return 0.1
    
    # Special boost for obvious corrections with good text clarity
    # If it's a typo_fix or format_correction with mostly_clear+ text, boost confidence
    if edit_type in ["typo_fix", "format_correction", "cross_validation_fix"] and text_clarity in ["clear", "mostly_clear"]:
        # For obvious corrections, treat "mostly_certain" as "certain"
        if certainty == "mostly_certain":
            certainty_mod = 1.0
    
    # Calculate base final score
    final_score = base_score * certainty_mod * edit_mod
    
    # Special domain-specific confidence boosting for emails
    # Valid email patterns should get high confidence regardless of OCR quality
    if "@" in value and "." in value:
        # Basic email pattern detected
        email_parts = value.split("@")
        if len(email_parts) == 2 and email_parts[1]:
            domain = email_parts[1].lower()
            # Known school domains get very high confidence
            if any(school_domain in domain for school_domain in ["wyliebulldogs.org", "mcm.edu", "acu.edu", "umhb.edu"]):
                return 0.95  # Very high confidence for school email patterns
            # Any reasonable email pattern gets decent confidence
            elif len(domain) > 3 and "." in domain:
                return max(final_score, 0.75)  # Boost to at least 75% for valid email patterns
    
    # Ensure score is between 0.0 and 1.0
    return min(max(final_score, 0.0), 1.0)

def determine_review_from_quality(quality_info: Dict[str, Any], field_data: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Determine if field needs human review based on quality indicators
    
    Args:
        quality_info: Quality indicators from Gemini
        field_data: Enhanced field data with requirements
        
    Returns:
        Tuple of (needs_review: bool, review_notes: str)
    """
    value = quality_info.get("value", "")
    certainty = quality_info.get("certainty", "uncertain")
    text_clarity = quality_info.get("text_clarity", "unclear")
    edit_type = quality_info.get("edit_type", "none")
    is_required = field_data.get("required", False)
    gemini_notes = quality_info.get("notes", "")
    confidence_score = calculate_confidence_from_quality(quality_info)
    
    # Always review if marked as uncertain
    if certainty == "uncertain":
        if gemini_notes:
            return True, gemini_notes
        return True, "This field needs a closer look - the text wasn't clear enough to read confidently"
    
    # Always review unreadable text
    if text_clarity == "unreadable":
        if gemini_notes:
            return True, gemini_notes
        return True, "The text here is too unclear to read"
    
    # Always review unclear text edits
    if edit_type == "unclear_text":
        if gemini_notes:
            return True, gemini_notes
        return True, "The handwriting here is difficult to make out clearly"
    
    # Review required fields that are empty
    if is_required and (not value or value.strip() == ""):
        if gemini_notes:
            return True, gemini_notes
        return True, "This required field appears to be empty"
    
    # Review required fields with low confidence
    if is_required and confidence_score < 0.7:
        if gemini_notes:
            return True, gemini_notes
        return True, "This required field could use a second look to make sure it's accurate"
    
    # Review if Gemini notes indicate uncertainty (check for uncertainty keywords)
    if gemini_notes and any(word in gemini_notes.lower() for word in ["unclear", "unsure", "hard to", "difficult", "might", "could be", "ambiguous", "faded", "messy"]):
        return True, gemini_notes
    
    # Field looks good
    return False, "" 
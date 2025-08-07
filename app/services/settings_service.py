import json
from datetime import datetime, timezone
from typing import Dict, Any, List
from app.core.clients import get_supabase_client
from app.utils.retry_utils import log_debug
from app.utils.field_utils import get_combined_fields_to_exclude, generate_field_label

def get_field_requirements(school_id: str) -> Dict[str, Dict[str, bool]]:
    """
    Get field requirements from school settings (now as an array)
    """
    log_debug("=== GETTING FIELD REQUIREMENTS ===", service="settings")
    log_debug(f"School ID: {school_id}", service="settings")

    try:
        supabase_client = get_supabase_client()
        school_query = supabase_client.table("schools").select("card_fields").eq("id", school_id).maybe_single().execute()
        if school_query and school_query.data:
            card_fields_array = school_query.data.get("card_fields") or []
            
            # Filter out combined fields that should not be in final data
            combined_fields = get_combined_fields_to_exclude()
            filtered_card_fields_array = [f for f in card_fields_array if f["key"] not in combined_fields]
            
            # Convert array to dict for internal use
            card_fields = {f["key"]: {"enabled": f.get("enabled", True), "required": f.get("required", False)} for f in filtered_card_fields_array}
            
            log_debug("Found school settings (after filtering combined fields)", card_fields, service="settings")
            if len(card_fields_array) != len(filtered_card_fields_array):
                log_debug(f"Filtered out {len(card_fields_array) - len(filtered_card_fields_array)} combined fields", service="settings")
            
            return card_fields
        else:
            log_debug("No school settings found, returning empty dict", service="settings")
            return {}
    except Exception as e:
        log_debug(f"ERROR getting field requirements: {str(e)}", service="settings")
        return {}

def apply_field_requirements(fields: Dict[str, Any], requirements: Dict[str, Dict[str, bool]]) -> Dict[str, Any]:
    """
    Apply school requirements to field data and add missing enabled fields
    
    Args:
        fields: Field data from DocAI processing
        requirements: Field requirements from school settings
        
    Returns:
        Updated field data with requirements applied
    """
    log_debug("=== APPLYING FIELD REQUIREMENTS ===", service="settings")
    log_debug("Input fields", list(fields.keys()), service="settings")
    log_debug("Requirements", requirements, service="settings")
    
    # Validate inputs to prevent errors
    if not isinstance(fields, dict):
        log_debug("ERROR: fields is not a dict", {"type": type(fields)}, service="settings")
        fields = {}
        
    if not isinstance(requirements, dict):
        log_debug("ERROR: requirements is not a dict", {"type": type(requirements)}, service="settings")
        requirements = {}
    
    # Update existing fields with requirements
    for field_name, field_data in fields.items():
        # Ensure field_data is a dict
        if not isinstance(field_data, dict):
            log_debug(f"WARNING: field_data for {field_name} is not a dict, converting", {"type": type(field_data)}, service="settings")
            fields[field_name] = {
                "value": str(field_data) if field_data is not None else "",
                "confidence": 0.0,
                "bounding_box": [],
                "source": "converted",
                "enabled": True,
                "required": False,
                "requires_human_review": False,
                "review_notes": "",
                "review_confidence": 0.0
            }
            field_data = fields[field_name]
        
        if field_name in requirements:
            field_settings = requirements[field_name]
            # Preserve original field data while updating requirements
            original_value = field_data.get("value", "")
            original_confidence = field_data.get("confidence", 0.0)
            
            field_data["enabled"] = field_settings.get("enabled", True)
            field_data["required"] = field_settings.get("required", False)
            
            # Smart review logic for mapped_major: only flag for review if no value (regardless of required status)
            if field_name == "mapped_major":
                current_value = (field_data.get("value") or "").strip()
                if current_value:
                    # Gemini successfully mapped a major - no review needed
                    field_data["requires_human_review"] = False
                    field_data["review_notes"] = ""
                    log_debug(f"mapped_major has value '{current_value}' - no review needed", service="settings")
                else:
                    # Gemini couldn't map a major - needs review if required
                    is_required = field_settings.get("required", False)
                    field_data["requires_human_review"] = is_required
                    field_data["review_notes"] = "Required field: Gemini unable to map major from card" if is_required else ""
                    log_debug(f"mapped_major is empty - flagging for review: {is_required} (required: {is_required})", service="settings")
            
            # Log if we're about to overwrite existing field values (this should not happen)
            if original_value and field_data.get("value", "") != original_value:
                log_debug(f"WARNING: Field value changed during requirements application", {
                    "field": field_name,
                    "original_value": original_value,
                    "new_value": field_data.get("value", "")
                }, service="settings")
            
            log_debug(f"Updated {field_name}", {
                "enabled": field_data["enabled"],
                "required": field_data["required"],
                "value_preserved": bool(original_value)
            }, service="settings")
        else:
            # Default settings for fields not in requirements
            field_data["enabled"] = True
            field_data["required"] = False
            log_debug(f"Default settings for {field_name}", service="settings")
    
    # Add missing enabled fields (both required and optional)
    for field_name, field_settings in requirements.items():
        if field_settings.get("enabled", True) and field_name not in fields:
            is_required = field_settings.get("required", False)
            
            # Smart review logic for mapped_major: only flag for review if required (when missing)
            needs_review = is_required
            review_notes = "Required field not detected by DocAI" if is_required else ""
            
            if field_name == "mapped_major":
                # mapped_major only needs review if it's required and missing
                # If not required, don't flag for review even if missing
                needs_review = is_required
                review_notes = "Required field: Gemini unable to map major from card" if is_required else ""
            
            log_debug(f"Adding missing {'required' if is_required else 'enabled'} field: {field_name}", service="settings")
            fields[field_name] = {
                "value": "",
                "confidence": 0.0,
                "bounding_box": [],
                "source": "missing_required" if is_required else "missing_enabled",
                "enabled": field_settings.get("enabled", True),
                "required": is_required,
                "requires_human_review": needs_review,
                "review_notes": review_notes,
                "review_confidence": 0.0
            }
    
    log_debug("Final fields", list(fields.keys()), service="settings")
    return fields

def sync_field_requirements(school_id: str, detected_fields: list) -> Dict[str, Dict[str, bool]]:
    """
    Sync detected fields with school settings, adding any new fields with intelligent defaults
    """
    log_debug("=== SYNCING FIELD REQUIREMENTS ===", service="settings")
    log_debug(f"School ID: {school_id}", service="settings")
    log_debug("Detected fields", detected_fields, service="settings")

    try:
        supabase_client = get_supabase_client()
        # Initialize updated flag
        updated = False
        
        # Get current school settings as array
        school_query = supabase_client.table("schools").select("card_fields").eq("id", school_id).maybe_single().execute()
        card_fields_array = school_query.data.get("card_fields") or []
        
        # Get existing field keys
        existing_keys = {f["key"] for f in card_fields_array}

        # Filter detected fields to exclude combined fields
        combined_fields = get_combined_fields_to_exclude()
        filtered_detected_fields = [f for f in detected_fields if f not in combined_fields]
        
        log_debug(f"Detected fields (after filtering combined): {filtered_detected_fields}", service="settings")

        # Add any new detected fields at the end (excluding combined fields)
        # Use simple defaults for all DocAI-detected fields
        for field_name in filtered_detected_fields:
            if field_name not in existing_keys:
                card_fields_array.append({
                    "key": field_name,
                    "label": generate_field_label(field_name),
                    "enabled": True,  # All detected fields enabled by default
                    "required": False  # No fields required by default - let schools decide
                })
                updated = True
                log_debug(f"Added new DocAI-detected field {field_name} with default settings", service="settings")

        # Remove any combined fields from existing settings
        original_length = len(card_fields_array)
        card_fields_array = [f for f in card_fields_array if f["key"] not in combined_fields]
        if len(card_fields_array) < original_length:
            updated = True
            log_debug(f"Removed {original_length - len(card_fields_array)} combined fields from school settings", service="settings")



        # Conditionally add mapped_major if school has majors configured
        majors_query = supabase_client.table("schools").select("majors").eq("id", school_id).maybe_single().execute()
        school_has_majors = bool(majors_query and majors_query.data and majors_query.data.get("majors"))
        
        mapped_major_exists = "mapped_major" in existing_keys or "mapped_major" in [f["key"] for f in card_fields_array]
        
        if school_has_majors and not mapped_major_exists:
            card_fields_array.append({
                "key": "mapped_major",
                "label": generate_field_label("mapped_major"),
                "enabled": True,
                "required": False
            })
            updated = True
            log_debug("Added mapped_major field since school has majors configured", service="settings")
        elif not school_has_majors and mapped_major_exists:
            # Remove mapped_major if school no longer has majors
            card_fields_array = [f for f in card_fields_array if f["key"] != "mapped_major"]
            updated = True
            log_debug("Removed mapped_major field since school has no majors configured", service="settings")

        if updated:
            update_payload = {
                "id": school_id,
                "card_fields": card_fields_array
            }
            result = supabase_client.table("schools").update(update_payload).eq("id", school_id).execute()
            if result.data:
                log_debug("Successfully updated school settings in database", service="settings")
            else:
                log_debug("Warning: School settings update returned no data", service="settings")

        # Return as dict for internal use (already filtered)
        return {f["key"]: {"enabled": f.get("enabled", True), "required": f.get("required", False)} for f in card_fields_array}

    except Exception as e:
        log_debug(f"ERROR syncing field requirements: {str(e)}", service="settings")
        import traceback
        log_debug("Full sync error traceback:", traceback.format_exc(), service="settings")
        return {}





# get_canonical_field_list function removed - DocAI determines field names now

def sync_field_types_and_options(school_id: str, detected_field_info: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, bool]]:
    """
    Sync detected field types and options with school settings
    
    Args:
        school_id: School ID
        detected_field_info: Field information from Gemini with field_type and detected_options
        
    Returns:
        Updated field requirements dict
    """
    log_debug("=== SYNCING FIELD TYPES AND OPTIONS ===", service="settings")
    log_debug(f"School ID: {school_id}", service="settings")
    log_debug("Detected field info", {
        field_name: {
            "field_type": info.get("field_type", "text"),
            "options_count": len(info.get("detected_options", []))
        }
        for field_name, info in detected_field_info.items()
    }, service="settings")

    try:
        supabase_client = get_supabase_client()
        # Get current school settings as array
        school_query = supabase_client.table("schools").select("card_fields").eq("id", school_id).maybe_single().execute()
        card_fields_array = school_query.data.get("card_fields") or []
        
        updated = False
        
        # Update existing fields with type information and options
        for field_config in card_fields_array:
            field_key = field_config["key"]
            if field_key in detected_field_info:
                field_info = detected_field_info[field_key]
                
                # Update field type if not already set
                detected_type = field_info.get("field_type", "text")
                if not field_config.get("field_type") and detected_type != "text":
                    field_config["field_type"] = detected_type
                    updated = True
                    log_debug(f"Updated field type for {field_key}: {detected_type}", service="settings")
                
                # Update options for select fields
                detected_options = field_info.get("detected_options", [])
                if detected_type in ["select", "checkbox"] and detected_options:
                    current_options = field_config.get("options", [])
                    # Merge new options with existing ones (preserve user customizations)
                    merged_options = list(set(current_options + detected_options))
                    if merged_options != current_options:
                        field_config["options"] = sorted(merged_options)  # Sort for consistency
                        updated = True
                        log_debug(f"Updated options for {field_key}: {merged_options}", service="settings")
        
        # Add any new fields with their type information
        existing_keys = {f["key"] for f in card_fields_array}
        combined_fields = get_combined_fields_to_exclude()
        
        for field_name, field_info in detected_field_info.items():
            if field_name not in existing_keys and field_name not in combined_fields:
                new_field = {
                    "key": field_name,
                    "enabled": True,
                    "required": False,
                    "field_type": field_info.get("field_type", "text"),
                }
                
                # Add options for select/checkbox fields
                detected_options = field_info.get("detected_options", [])
                if detected_options and field_info.get("field_type") in ["select", "checkbox"]:
                    new_field["options"] = sorted(detected_options)
                
                card_fields_array.append(new_field)
                updated = True
                log_debug(f"Added new field {field_name} with type {new_field['field_type']}", service="settings")
        
        # Save if updated
        if updated:
            update_payload = {
                "id": school_id,
                "card_fields": card_fields_array
            }
            supabase_client.table("schools").update(update_payload).eq("id", school_id).execute()
            log_debug("Updated school card_fields with type information", service="settings")
        
        # Return as dict for internal use
        return {f["key"]: {"enabled": f.get("enabled", True), "required": f.get("required", False)} for f in card_fields_array}
        
    except Exception as e:
        log_debug(f"ERROR syncing field types and options: {str(e)}", service="settings")
        return {}

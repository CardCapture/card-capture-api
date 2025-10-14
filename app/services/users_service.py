from fastapi.responses import JSONResponse
from fastapi import HTTPException
from app.repositories.users_repository import (
    get_user_profile_by_id,
    list_users_db,
    invite_user_db,
    update_user_db,
    delete_user_db,
    parse_pg_array
)
from app.core.clients import get_supabase_client, get_supabase_auth
from app.utils.retry_utils import log_debug
import traceback

async def get_user_profile(user_id: str):
    """
    Get user profile by ID
    """
    try:
        log_debug(f"Fetching user profile for user_id: {user_id}", service="users")
        supabase = get_supabase_client()
        result = supabase.table("users").select("*").eq("id", user_id).execute()
        log_debug(f"User profile fetched for user_id: {user_id}", service="users")
        return result.data[0] if result.data else None
    except Exception as e:
        raise e

async def get_users(user):
    try:
        # Get the logged-in user's school_id
        user_school_id = user.get("school_id")
        if not user_school_id:
            log_debug("User does not have a school_id", service="users")
            return []
        
        # Use the user_profiles_with_login view which now includes school_id
        # This gives us both last_sign_in_at from users table and school_id from profiles table
        supabase = get_supabase_client()
        result = supabase.table("user_profiles_with_login").select("id, email, first_name, last_name, role, school_id, last_sign_in_at").eq("school_id", user_school_id).execute()
        
        users = result.data or []
        # Handle role parsing (same as existing logic)
        for user_item in users:
            role = user_item.get("role")
            if isinstance(role, str) and role.startswith("{") and role.endswith("}"):
                user_item["role"] = parse_pg_array(role)
            elif role is None:
                user_item["role"] = []
            # If already a list, leave as is
        
        log_debug(f"Fetched {len(users)} users for school_id: {user_school_id}", service="users")
        return users
    except Exception as e:
        log_debug(f"Error fetching users: {e}", service="users")
        raise e

async def invite_user_service(payload, user):
    log_debug("\n=== INVITE USER SERVICE START ===", service="users")
    log_debug(f"Service called by user: {user.get('email')} (ID: {user.get('id')})", service="users")
    log_debug(f"User object keys: {list(user.keys())}", service="users")
    log_debug(f"User object full: {user}", service="users")
    
    try:
        # Check admin permissions (allow SuperAdmins and regular admins)
        user_roles = user.get("role", [])
        user_school_id = user.get("school_id")
        is_superadmin = user_school_id is None
        
        log_debug(f"User roles: {user_roles}", service="users")
        log_debug(f"User school_id: {user_school_id}", service="users")
        log_debug(f"Is SuperAdmin: {is_superadmin}", service="users")
        log_debug("Checking permissions...", service="users")
        
        if not is_superadmin and "admin" not in user_roles:
            log_debug("Only admins and SuperAdmins can invite users", service="users")
            raise HTTPException(status_code=403, detail="Only admins can invite users")
        
        if is_superadmin:
            log_debug("User is SuperAdmin - invitation allowed", service="users")
        else:
            log_debug("User has admin role - invitation allowed", service="users")
        
        # Extract payload data (handle both dict and object)
        if isinstance(payload, dict):
            email = payload.get("email")
            first_name = payload.get("first_name")
            last_name = payload.get("last_name")
            role = payload.get("role")
            school_id = payload.get("school_id")
        else:
            email = payload.email
            first_name = payload.first_name
            last_name = payload.last_name
            role = payload.role
            school_id = payload.school_id
        
        log_debug("Processing invitation for:", {
            "email": email,
            "name": f"{first_name} {last_name}",
            "roles": role,
            "school_id": school_id
        }, service="users")
        
        # Validate required fields
        if not all([email, first_name, last_name, role]):
            log_debug("Missing required fields", service="users")
            missing_fields = []
            if not email: missing_fields.append("email")
            if not first_name: missing_fields.append("first_name")
            if not last_name: missing_fields.append("last_name")
            if not role: missing_fields.append("role")
            log_debug(f"Missing fields: {missing_fields}", service="users")
            raise HTTPException(status_code=400, detail=f"Missing required fields: {', '.join(missing_fields)}")
        
        # Validate role
        valid_roles = ["admin", "user", "recruiter", "reviewer"]
        log_debug(f"Validating roles: {role}", service="users")
        log_debug(f"Valid roles allowed: {valid_roles}", service="users")
        
        invalid_roles = [r for r in role if r not in valid_roles]
        if invalid_roles:
            log_debug(f"Invalid roles specified: {invalid_roles}", service="users")
            raise HTTPException(status_code=400, detail=f"Invalid roles: {', '.join(invalid_roles)}")
        
        log_debug(f"Attempting to invite user: {email}", service="users")
        log_debug("User metadata being sent:", {
            "first_name": first_name,
            "last_name": last_name,
            "role": role,
            "school_id": school_id
        }, service="users")
        
        # Use the proper invite_user_db function that handles metadata correctly
        user_data = invite_user_db(email, first_name, last_name, role, school_id)
        log_debug(f"Successfully invited user: {email}", service="users")
        
        log_debug("Created user metadata:", {
            "user_data": user_data
        }, service="users")
        log_debug("=== INVITE USER SERVICE END ===\n", service="users")
        
        return {"success": True, "user": user_data}
        
    except HTTPException:
        # Re-raise HTTPExceptions as is
        raise
    except Exception as e:
        log_debug("\n❌ ERROR IN INVITE USER SERVICE:", service="users")
        log_debug(f"Error type: {type(e)}", service="users")
        log_debug(f"Error message: {str(e)}", service="users")
        if hasattr(e, 'message'):
            log_debug(f"Error message attribute: {e.message}", service="users")
        if hasattr(e, 'details'):
            log_debug(f"Error details: {e.details}", service="users")
        if hasattr(e, '__dict__'):
            log_debug(f"Error dict: {e.__dict__}", service="users")
        
        log_debug("Stack trace:", service="users")
        log_debug(traceback.format_exc(), service="users")
        log_debug("=== INVITE USER SERVICE END WITH ERROR ===\n", service="users")
        
        raise HTTPException(status_code=500, detail=str(e))

async def update_user_service(user_id: str, payload):
    try:
        # Convert Pydantic model to dictionary if needed
        if hasattr(payload, 'model_dump'):
            # For Pydantic v2
            update_data = payload.model_dump()
        elif hasattr(payload, 'dict'):
            # For Pydantic v1
            update_data = payload.dict()
        else:
            # Already a dictionary
            update_data = payload
        
        log_debug(f"Updating user {user_id} with data: {update_data}", service="users")
        
        # Update the profiles table (not users table)
        supabase = get_supabase_client()
        result = supabase.table("profiles").update(update_data).eq("id", user_id).execute()
        
        if hasattr(result, 'error') and result.error:
            log_debug(f"Error updating user {user_id}: {result.error}", service="users")
            raise Exception(f"Database error: {result.error}")
        
        log_debug(f"User updated successfully: {user_id}", service="users")
        return result
    except Exception as e:
        log_debug(f"Error updating user {user_id}: {e}", service="users")
        raise e

async def delete_user_service(user_id: str, user):
    log_debug(f"Delete user request - User object: {user}", service="users")
    log_debug(f"User role: {user.get('role')}", service="users")
    log_debug(f"User keys: {list(user.keys()) if user else 'None'}", service="users")
    
    try:
        # Check admin permissions (allow SuperAdmins and regular admins)
        user_roles = user.get("role", [])
        user_school_id = user.get("school_id")
        is_superadmin = user_school_id is None
        
        log_debug(f"Delete permission check - Is SuperAdmin: {is_superadmin}", service="users")
        
        if not is_superadmin and "admin" not in user_roles:
            log_debug("Only admins and SuperAdmins can delete users", service="users")
            raise HTTPException(status_code=403, detail="Only admins can delete users")
        
        # Prevent self-deletion
        if user.get("id") == user_id:
            log_debug("Users cannot delete themselves", service="users")
            raise HTTPException(status_code=400, detail="Users cannot delete themselves")
        
        log_debug(f"Attempting to delete user: {user_id}", service="users")
        # Use the proper delete_user_db function which handles profiles cleanup first
        result = delete_user_db(get_supabase_auth(), get_supabase_client(), user_id)
        log_debug(f"Successfully deleted user: {user_id}", service="users")
        return {"success": True}
        
    except HTTPException:
        # Re-raise HTTPExceptions as is
        raise
    except Exception as e:
        log_debug(f"Error deleting user {user_id}: {str(e)}", service="users")
        log_debug(f"Error type: {type(e)}", service="users")
        log_debug(f"Error details: {e.__dict__ if hasattr(e, '__dict__') else 'No details available'}", service="users")

        # Note: Foreign key constraint errors should no longer occur since we added CASCADE DELETE
        # to all relevant tables (processing_jobs, user_mfa_settings, trusted_devices, etc.)

        raise HTTPException(status_code=500, detail=f"Database error deleting user: {str(e)}") 
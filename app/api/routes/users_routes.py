from fastapi import APIRouter, Depends, Body, HTTPException, status
from app.controllers.users_controller import (
    get_current_user_controller,
    list_users_controller,
    invite_user_controller,
    update_user_controller,
    delete_user_controller
)
from app.core.auth import get_current_user
from app.models.user import UserUpdateRequest  # Adjust import if needed
from app.utils.authorization import is_superadmin
from app.utils.retry_utils import log_debug

router = APIRouter(tags=["Users"])

@router.get("/me")
async def read_current_user(user=Depends(get_current_user)):
    return await get_current_user_controller(user)

@router.get("/users")
async def list_users(user=Depends(get_current_user)):
    return await list_users_controller(user)

@router.post("/invite-user")
async def invite_user(user=Depends(get_current_user), payload: dict = Body(...)):
    """
    Invite a new user to the school.

    SECURITY:
    - Non-SuperAdmin: school_id in payload must match user's school (or is forced)
    - SuperAdmin: Can invite to any school (must provide school_id)
    """
    try:
        log_debug(f"Invite user request from: {user.get('email')}", service="users")

        # Trim whitespace from string fields (defensive programming)
        if "email" in payload and isinstance(payload["email"], str):
            payload["email"] = payload["email"].strip()
        if "first_name" in payload and isinstance(payload["first_name"], str):
            payload["first_name"] = payload["first_name"].strip()
        if "last_name" in payload and isinstance(payload["last_name"], str):
            payload["last_name"] = payload["last_name"].strip()

        # SECURITY: Handle school_id based on user type
        if is_superadmin(user):
            # SuperAdmin must provide school_id
            if "school_id" not in payload or not payload["school_id"]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="SuperAdmin must provide school_id for invitation"
                )
        else:
            # Non-SuperAdmin: Force user's school_id, ignore payload value
            user_school_id = user.get("school_id")
            if not user_school_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="User has no school association"
                )
            # Override any school_id in payload with user's school
            if payload.get("school_id") and str(payload["school_id"]) != str(user_school_id):
                log_debug(
                    f"Overriding school_id in invite: {payload['school_id']} -> {user_school_id}",
                    service="users"
                )
            payload["school_id"] = user_school_id

        # Validate required fields (school_id now guaranteed to be present)
        required_fields = ["email", "first_name", "last_name", "role", "school_id"]
        for field in required_fields:
            if field not in payload:
                log_debug(f"Missing required field: {field}", service="users")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Missing required field: {field}"
                )

        # Check for empty strings after trimming
        if not payload["email"] or not payload["first_name"] or not payload["last_name"]:
            log_debug("Required fields cannot be empty after trimming whitespace", service="users")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email, first name, and last name cannot be empty"
            )

        # Validate roles array
        roles = payload["role"] if isinstance(payload["role"], list) else [payload["role"]]
        valid_roles = ["admin", "recruiter", "reviewer"]

        # Check if all roles are valid
        invalid_roles = [role for role in roles if role not in valid_roles]
        if invalid_roles:
            log_debug(f"Invalid roles found: {invalid_roles}", service="users")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid roles: {', '.join(invalid_roles)}. Must be one of: {', '.join(valid_roles)}"
            )

        # Update the payload with validated roles
        payload["role"] = roles

        # Call the service to handle the invitation
        result = await invite_user_controller(user, payload)
        log_debug(f"User invitation completed for: {payload['email']}", service="users")
        return result
    except HTTPException:
        raise  # Re-raise HTTP exceptions as-is
    except Exception as e:
        log_debug(f"Error in invite user endpoint: {str(e)}", service="users")
        import traceback
        log_debug(f"Stack trace: {traceback.format_exc()}", service="users")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

@router.put("/users/{user_id}")
async def update_user(user_id: str, update: UserUpdateRequest, user=Depends(get_current_user)):
    """
    Update a user's profile.

    SECURITY:
    - Users can only update their own profile
    - SuperAdmins can update any user
    """
    current_user_id = user.get("id")

    # Users can only update their own profile unless they're SuperAdmin
    if not is_superadmin(user) and str(user_id) != str(current_user_id):
        log_debug(
            f"Access denied: User {current_user_id} tried to update user {user_id}",
            service="users"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: You can only update your own profile"
        )

    return await update_user_controller(user_id, update)

@router.delete("/users/{user_id}")
async def delete_user(user_id: str, user=Depends(get_current_user)):
    return await delete_user_controller(user, user_id) 
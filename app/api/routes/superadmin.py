from fastapi import APIRouter, Depends, HTTPException, Body
from fastapi.responses import JSONResponse
from typing import List, Dict, Any
from datetime import datetime, timezone
import logging
import traceback

from app.models.superadmin import SchoolCreate, SchoolResponse, SuperAdminCheck, InviteAdminRequest
from app.core.superadmin_auth import verify_superadmin
from app.core.clients import get_supabase_client
from app.controllers.users_controller import invite_user_controller
from app.utils.retry_utils import log_debug

router = APIRouter(prefix="/superadmin", tags=["SuperAdmin"])

def log(msg):
    log_debug(f"[superadmin] {msg}", service="superadmin")

@router.get("/health")
async def superadmin_health():
    """Health check for SuperAdmin system"""
    try:
        # Test database connection
        supabase_client = get_supabase_client()
        result = supabase_client.table("schools").select("id").limit(1).execute()
        
        return {
            "status": "healthy",
            "message": "SuperAdmin system is operational",
            "database_connection": "ok",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        log(f"❌ Health check failed: {e}")
        raise HTTPException(status_code=503, detail="SuperAdmin system unavailable")

@router.get("/check", response_model=SuperAdminCheck)
async def check_superadmin_status(current_user: Dict[str, Any] = Depends(verify_superadmin)):
    """Check if current user is SuperAdmin"""
    log(f"✅ SuperAdmin status check for user: {current_user['email']}")
    return SuperAdminCheck(is_superadmin=True, user_id=current_user["id"])

@router.get("/schools", response_model=List[SchoolResponse])
async def get_schools(current_user: Dict[str, Any] = Depends(verify_superadmin)):
    """Get all schools with user counts"""
    try:
        log(f"📊 Getting all schools for SuperAdmin: {current_user['email']}")
        
        # Get all schools using service role
        supabase_client = get_supabase_client()
        schools_result = supabase_client.table("schools").select("*").order("created_at", desc=True).execute()
        
        if not schools_result.data:
            log("ℹ️ No schools found")
            return []
        
        schools_with_counts = []
        for school in schools_result.data:
            # Get user count for each school
            count_result = supabase_client.table("profiles").select("*", count="exact").eq("school_id", school["id"]).execute()
            
            schools_with_counts.append(SchoolResponse(
                id=school["id"],
                name=school["name"],
                docai_processor_id=school.get("docai_processor_id"),
                created_at=school["created_at"],
                user_count=count_result.count or 0
            ))
        
        log(f"✅ Retrieved {len(schools_with_counts)} schools")
        return schools_with_counts
    
    except Exception as e:
        log(f"❌ Error fetching schools: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to fetch schools")

@router.post("/schools")
async def create_school(school: SchoolCreate, current_user: Dict[str, Any] = Depends(verify_superadmin)):
    """Create a new school"""
    try:
        log(f"🏫 Creating new school: {school.name} by {current_user['email']}")
        
        # Create the school record (with trimmed values)
        school_data = {
            "name": school.name.strip(),
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        
        # Add docai_processor_id if provided
        if school.docai_processor_id:
            school_data["docai_processor_id"] = school.docai_processor_id.strip()
        
        supabase_client = get_supabase_client()
        result = supabase_client.table("schools").insert(school_data).execute()
        
        if result.data:
            created_school = result.data[0]
            log(f"✅ School created successfully: {created_school['id']}")
            
            # Log the action for audit trail
            try:
                audit_data = {
                    "user_id": current_user["id"],
                    "action": "create_school",
                    "details": {
                        "school_name": school.name,
                        "school_id": created_school["id"],
                        "docai_processor_id": school.docai_processor_id
                    }
                }
                audit_result = supabase_client.table("audit_log").insert(audit_data).execute()
                if audit_result.data:
                    log("✅ Audit log created")
                else:
                    log("⚠️ Audit log insert returned no data")
            except Exception as audit_error:
                log(f"⚠️ Failed to create audit log (table may not exist yet): {audit_error}")
                # Don't fail the request if audit logging fails
            
            return JSONResponse(
                status_code=201, 
                content={
                    "message": "School created successfully", 
                    "school": created_school
                }
            )
        else:
            log("❌ Failed to create school - no data returned")
            raise HTTPException(status_code=500, detail="Failed to create school")
    
    except Exception as e:
        log(f"❌ Error creating school: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to create school")

@router.post("/schools/{school_id}/invite-admin")
async def invite_school_admin(
    school_id: str, 
    invite_request: InviteAdminRequest,
    current_user: Dict[str, Any] = Depends(verify_superadmin)
):
    """Invite a school administrator"""
    try:
        log(f"📧 Inviting admin for school {school_id}: {invite_request.email} by {current_user['email']}")
        
        # Verify school exists
        supabase_client = get_supabase_client()
        school_result = supabase_client.table("schools").select("name").eq("id", school_id).execute()
        if not school_result.data:
            log(f"❌ School not found: {school_id}")
            raise HTTPException(status_code=404, detail="School not found")
        
        school_name = school_result.data[0]["name"]
        
        # Prepare payload for existing invite_user endpoint (with trimmed values)
        invite_payload = {
            "email": invite_request.email.strip(),
            "first_name": invite_request.first_name.strip(),
            "last_name": invite_request.last_name.strip(),
            "role": ["admin"],  # Always admin role for school administrators
            "school_id": school_id
        }
        
        log(f"📝 Calling invite_user_controller with payload: {invite_payload}")
        
        # Use the existing invite user controller
        result = await invite_user_controller(current_user, invite_payload)
        
        log(f"✅ Admin invitation sent successfully to {invite_request.email}")
        
        # Log the action for audit trail
        try:
            # Check if audit_log table exists and has correct structure
            audit_data = {
                "user_id": current_user["id"],
                "action": "invite_school_admin",
                "details": {
                    "school_id": school_id,
                    "school_name": school_name,
                    "invited_email": invite_request.email,
                    "invited_name": f"{invite_request.first_name} {invite_request.last_name}"
                }
            }
            
            # Try to insert audit log, but don't fail if table doesn't exist yet
            audit_result = supabase_client.table("audit_log").insert(audit_data).execute()
            if audit_result.data:
                log("✅ Audit log created for admin invitation")
            else:
                log("⚠️ Audit log insert returned no data")
        except Exception as audit_error:
            log(f"⚠️ Failed to create audit log (table may not exist yet): {audit_error}")
            # Don't fail the request if audit logging fails - table might not be created yet
        
        return JSONResponse(
            status_code=200,
            content={
                "message": f"Admin invitation sent successfully to {invite_request.email}",
                "school_name": school_name,
                "result": result
            }
        )
    
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        log(f"❌ Error inviting school admin: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to invite school admin") 
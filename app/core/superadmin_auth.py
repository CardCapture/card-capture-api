from fastapi import HTTPException, status, Depends
from fastapi.security import HTTPBearer
from jose import JWTError, jwt
import os
import logging
from app.core.clients import get_supabase_client

security = HTTPBearer()

def log(msg):
    print(f"[superadmin_auth] {msg}")

async def verify_superadmin(token: str = Depends(security)):
    """Verify JWT token and check if user is SuperAdmin"""
    try:
        log(f"🔐 Verifying SuperAdmin token")
        
        # Verify JWT token with Supabase
        payload = jwt.decode(
            token.credentials, 
            os.getenv("SUPABASE_JWT_SECRET"), 
            algorithms=[os.getenv("SUPABASE_JWT_ALGORITHM", "HS256")],
            audience=os.getenv("SUPABASE_JWT_AUDIENCE", "authenticated")
        )
        user_id = payload.get("sub")
        
        if not user_id:
            log("❌ User ID not found in token")
            raise HTTPException(status_code=401, detail="Invalid token")
        
        log(f"👤 Token verified for user_id: {user_id}")
        
        # Check if user is SuperAdmin using service role
        # Note: Using the existing supabase_client which is already configured with service role key
        supabase_client = get_supabase_client()
        result = supabase_client.table("profiles").select("school_id, email, first_name, last_name, role").eq("id", user_id).execute()
        
        if not result.data:
            log(f"❌ User profile not found for user_id: {user_id}")
            raise HTTPException(status_code=404, detail="User profile not found")
        
        profile = result.data[0]
        
        if profile["school_id"] is not None:
            log(f"❌ User {user_id} is not a SuperAdmin (has school_id: {profile['school_id']})")
            raise HTTPException(status_code=403, detail="Not a SuperAdmin")
        
        log(f"✅ SuperAdmin verified: {profile['email']}")
        
        # Return the user profile for use in endpoints
        return {
            "id": user_id,
            "email": profile["email"],
            "first_name": profile["first_name"],
            "last_name": profile["last_name"],
            "role": profile["role"],
            "school_id": profile["school_id"]
        }
    
    except JWTError:
        log("❌ Invalid JWT token")
        raise HTTPException(status_code=401, detail="Invalid token")
    except HTTPException:
        # Re-raise HTTP exceptions (like 403, 404)
        raise
    except Exception as e:
        log(f"❌ Error verifying SuperAdmin: {e}")
        raise HTTPException(status_code=500, detail="Authentication error") 
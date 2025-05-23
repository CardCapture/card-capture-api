from fastapi import Request, HTTPException
from app.core.clients import supabase_auth, supabase_client
import os
from jose import jwt, JWTError
from app.repositories.auth_repository import login_db, get_user_profile_db

async def login_service(credentials: dict):
    try:
        print("🔐 Login attempt for:", credentials.get("email"))
        response = login_db(supabase_auth, credentials)
        print("✅ Login successful")
        return response
    except Exception as e:
        print("❌ Login error:", str(e))
        raise HTTPException(status_code=401, detail=str(e))

async def read_current_user_service(request: Request):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        print("❌ Missing or invalid Authorization header")
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = auth_header.split(" ", 1)[1]
    print(f"🔍 Token: {token}")
    try:
        payload = jwt.decode(
            token,
            os.getenv("SUPABASE_JWT_SECRET"),
            algorithms=[os.getenv("SUPABASE_JWT_ALGORITHM")],
            audience=os.getenv("SUPABASE_JWT_AUDIENCE", "authenticated")
        )
        user_id = payload.get("sub")
        print(f"🔍 User ID: {user_id}")
        if not user_id:
            print("❌ User ID not found in token")
            raise HTTPException(status_code=400, detail="User ID not found in token")
        print(f"🔍 Fetching user profile for user_id: {user_id}")
        profile = get_user_profile_db(supabase_client, user_id)
        print(f"✅ User profile fetched for user_id: {user_id}")
        return {"profile": profile}
    except JWTError as e:
        print(f"❌ JWTError: {e}")
        print("❌ Invalid or expired token")
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    except Exception as e:
        print(f"❌ Error fetching user profile: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching user profile: {e}") 
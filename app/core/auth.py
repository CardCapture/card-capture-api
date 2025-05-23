from fastapi import Request, HTTPException
from jose import jwt, JWTError
import os
from app.repositories.auth_repository import get_user_profile_db
from app.core.clients import supabase_client

def log(msg):
    print(f"[auth] {msg}")

async def get_current_user(request: Request):
    auth_header = request.headers.get("Authorization")
    print(f"🔍 Auth header: {auth_header}")
    if not auth_header or not auth_header.startswith("Bearer "):
        log("❌ Missing or invalid Authorization header")
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
        if not user_id:
            log("❌ User ID not found in token")
            raise HTTPException(status_code=400, detail="User ID not found in token")
        # Fetch the user's profile from the database using the repository
        profile = get_user_profile_db(supabase_client, user_id)
        log(f"✅ Authenticated user_id: {user_id}")
        return profile
    except JWTError as e:
        log(f"❌ JWTError: {e}")
        log("❌ Invalid or expired token")
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    except Exception as e:
        log(f"❌ Error decoding token or fetching user: {e}")
        raise HTTPException(status_code=500, detail=f"Error decoding token or fetching user: {e}")

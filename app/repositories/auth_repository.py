from fastapi import HTTPException
import os
import secrets
import hashlib
from datetime import datetime, timedelta
from jose import jwt, JWTError

def login_db(supabase_auth, credentials: dict):
    print("🔐 Login attempt for:", credentials.get("email"))
    response = supabase_auth.auth.sign_in_with_password({
        "email": credentials.get("email"),
        "password": credentials.get("password")
    })
    print("✅ Login successful")
    return response

def get_user_profile_db(supabase_client, user_id: str):
    response = supabase_client.table("profiles").select("id, email, first_name, last_name, role, school_id").eq("id", user_id).maybe_single().execute()
    if not response or not response.data:
        raise HTTPException(status_code=404, detail="User profile not found")
    return response.data

# Magic Link Functions
def generate_secure_token(length: int = 32) -> str:
    """Generate a cryptographically secure random token"""
    return secrets.token_urlsafe(length)

def create_magic_link_db(supabase_client, email: str, link_type: str, metadata: dict = None):
    """Create a magic link token and store it in the database"""
    print(f"🪄 Creating magic link for: {email} (type: {link_type})")
    
    # Generate secure token
    token = generate_secure_token(32)
    
    # Set expiry to 24 hours from now with consistent formatting
    expires_at = datetime.utcnow() + timedelta(hours=24)
    expires_at_str = expires_at.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + '+00:00'
    
    try:
        # Insert magic link into database
        magic_link_data = {
            "token": token,
            "email": email,
            "type": link_type,
            "metadata": metadata or {},
            "expires_at": expires_at_str,
            "used": False
        }
        
        response = supabase_client.table("magic_links").insert(magic_link_data).execute()
        
        if not response.data:
            raise Exception("Failed to create magic link")
        
        print(f"✅ Magic link created with token: {token[:8]}...")
        return token
        
    except Exception as e:
        print(f"❌ Error creating magic link: {str(e)}")
        raise Exception(f"Error creating magic link: {str(e)}")

def validate_magic_link_db(supabase_client, token: str):
    """Validate a magic link token and return the link data"""
    print(f"🔍 Validating magic link token: {token[:8]}...")
    
    try:
        # Fetch the magic link
        response = supabase_client.table("magic_links").select("*").eq("token", token).eq("used", False).execute()
        
        if not response.data:
            print("❌ Magic link not found or already used")
            return None
        
        magic_link = response.data[0]
        
        # Check if expired - robust datetime parsing
        expires_at_str = magic_link["expires_at"]
        try:
            # Normalize the datetime string for consistent parsing
            normalized_dt_str = expires_at_str
            
            # Remove timezone suffixes for normalization
            if normalized_dt_str.endswith("+00:00"):
                normalized_dt_str = normalized_dt_str.replace("+00:00", "")
            elif normalized_dt_str.endswith("Z"):
                normalized_dt_str = normalized_dt_str.replace("Z", "")
            
            # Handle microseconds - ensure they're 6 digits for Python compatibility
            if "." in normalized_dt_str:
                date_part, microsec_part = normalized_dt_str.split(".")
                # Pad or truncate microseconds to exactly 6 digits
                microsec_part = microsec_part.ljust(6, '0')[:6]
                normalized_dt_str = f"{date_part}.{microsec_part}"
            
            # Parse the normalized datetime
            expires_at = datetime.fromisoformat(normalized_dt_str)
            
        except Exception as parse_error:
            print(f"❌ Failed to parse expires_at: {expires_at_str}, error: {str(parse_error)}")
            # Fallback - try a simpler parsing approach
            try:
                # Strip everything after the seconds and try again
                simple_dt_str = expires_at_str.split(".")[0] if "." in expires_at_str else expires_at_str
                simple_dt_str = simple_dt_str.replace("+00:00", "").replace("Z", "")
                expires_at = datetime.fromisoformat(simple_dt_str)
                print(f"✅ Fallback parsing successful for: {simple_dt_str}")
            except:
                print(f"❌ All datetime parsing failed, treating as not expired")
                # If we still can't parse, assume it's valid (not expired)
                expires_at = datetime.utcnow() + timedelta(hours=1)
        
        if datetime.utcnow() > expires_at:
            print("❌ Magic link has expired")
            return None
        
        print(f"✅ Magic link validated for: {magic_link['email']} (type: {magic_link['type']})")
        return magic_link
        
    except Exception as e:
        print(f"❌ Error validating magic link: {str(e)}")
        return None

def consume_magic_link_db(supabase_client, token: str):
    """Mark a magic link as used atomically.

    SECURITY: Uses .eq("used", False) to prevent race conditions.
    Only succeeds if token exists AND hasn't been used yet.
    """
    print(f"🔄 Consuming magic link token: {token[:8]}...")

    try:
        # Mark as used with timezone-aware timestamp
        used_at_timestamp = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + '+00:00'

        # SECURITY: Atomic update - only succeeds if token is not already used
        # This prevents race conditions where two requests validate simultaneously
        response = supabase_client.table("magic_links").update({
            "used": True,
            "used_at": used_at_timestamp
        }).eq("token", token).eq("used", False).execute()

        if response.data:
            print("✅ Magic link consumed successfully")
            return True
        print("⚠️ Magic link already consumed or not found")
        return False
        
    except Exception as e:
        print(f"❌ Error consuming magic link: {str(e)}")
        return False

def create_temporary_session_db(supabase_client, email: str):
    """Create a temporary Supabase session for the user"""
    print(f"🔑 Creating temporary session for: {email}")
    
    try:
        # Check if user exists
        user_response = supabase_client.auth.admin.list_users()
        user = None
        
        for u in user_response:
            if u.email == email:
                user = u
                break
        
        if not user:
            print(f"❌ User not found: {email}")
            return None
        
        # Generate a magic link that contains session tokens
        # This is more reliable than trying to create sessions directly
        session_response = supabase_client.auth.admin.generate_link(
            type="magiclink",
            email=email,
            options={"redirect_to": get_frontend_url() + "/"}
        )
        
        if hasattr(session_response, 'error') and session_response.error:
            print(f"❌ Session generation error: {session_response.error}")
            return None
        
        # Extract the tokens from the magic link URL if available
        generated_at_str = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + '+00:00'
        session_data = {
            "user_id": user.id,
            "email": email,
            "magic_link_url": getattr(session_response, 'action_link', ''),
            "generated_at": generated_at_str
        }
        
        print(f"✅ Temporary session created for: {email}")
        return session_data
        
    except Exception as e:
        print(f"❌ Error creating temporary session: {str(e)}")
        import traceback
        print(f"Stack trace: {traceback.format_exc()}")
        return None

def get_frontend_url():
    """Get the frontend URL from environment variables"""
    frontend_url = os.getenv('FRONTEND_URL')
    if frontend_url:
        return frontend_url.strip()
    
    # Environment-specific defaults
    env = os.getenv('ENVIRONMENT', '').strip()
    if env == 'production':
        return 'https://cardcapture.io'
    elif env == 'staging':
        return 'https://staging.cardcapture.io'
    else:
        return 'http://localhost:3000'

def send_magic_link_email_db(supabase_client, email: str, link_type: str, metadata: dict = None):
    """Create magic link and send email"""
    print(f"📧 Sending magic link email to: {email} (type: {link_type})")
    
    try:
        # Create magic link token
        token = create_magic_link_db(supabase_client, email, link_type, metadata)
        
        # Get frontend URL
        frontend_url = get_frontend_url()
        
        # Create magic link URL with query parameters (Outlook-friendly)
        magic_url = f"{frontend_url}/magic-link?token={token}&type={link_type}"
        
        print(f"🔗 Magic link URL: {magic_url}")
        
        # For now, we'll use Supabase's email system to send a custom email
        # In a production system, you might want to use a dedicated email service
        
        # Send email using Supabase's reset password mechanism as a template
        # but we'll customize the redirect URL to point to our magic link handler
        
        if link_type == "password_reset":
            # Use Supabase's password reset but redirect to our magic link handler
            response = supabase_client.auth.reset_password_for_email(
                email,
                {"redirect_to": magic_url}
            )
        elif link_type == "invite":
            # Use Supabase's invite but redirect to our magic link handler
            response = supabase_client.auth.admin.invite_user_by_email(
                email,
                options={
                    "data": metadata or {},
                    "redirect_to": magic_url
                }
            )
        else:
            # For other types, we'll need to implement custom email sending
            # For now, just return the URL
            return {"magic_url": magic_url, "token": token}
        
        if hasattr(response, 'error') and response.error:
            print(f"❌ Email sending error: {response.error}")
            raise Exception(f"Failed to send email: {response.error}")
        
        print(f"✅ Magic link email sent to: {email}")
        return {"success": True, "magic_url": magic_url, "token": token}
        
    except Exception as e:
        print(f"❌ Error sending magic link email: {str(e)}")
        raise Exception(f"Error sending magic link email: {str(e)}")

# Legacy functions updated to use magic links
def reset_password_db(supabase_client, email: str):
    """Send password reset email using magic links"""
    print(f"🚨 RESET_PASSWORD_DB FUNCTION CALLED - Magic Link Version - Email: {email}")
    return send_magic_link_email_db(supabase_client, email, "password_reset") 
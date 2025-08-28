from fastapi import APIRouter, Depends, HTTPException, Request, Body, Header, Cookie
from fastapi.responses import JSONResponse
from typing import Optional
import secrets
import hashlib
from datetime import datetime, timedelta, timezone
from app.core.clients import supabase_client
from app.core.auth import get_current_user

router = APIRouter(prefix="/mfa", tags=["MFA"])

def hash_token(token: str) -> str:
    """Hash a token for secure storage"""
    return hashlib.sha256(token.encode()).hexdigest()

def generate_device_token() -> tuple[str, str]:
    """Generate a secure device token and its hash"""
    token = secrets.token_urlsafe(32)
    token_hash = hash_token(token)
    return token, token_hash

@router.post("/enroll")
async def enroll_mfa(
    request: Request,
    phone_number: str = Body(..., embed=True),
    current_user: dict = Depends(get_current_user)
):
    """
    Start MFA enrollment by sending verification code to phone
    """
    try:
        user_id = current_user['id']
        
        # Check if user already has MFA enabled
        result = supabase_client.table('user_mfa_settings').select('*').eq('user_id', user_id).single().execute()
        
        if result.data and result.data.get('mfa_enabled'):
            raise HTTPException(status_code=400, detail="MFA is already enabled for this account")
        
        # Start phone verification with Supabase Auth
        auth_response = supabase_client.auth.mfa.enroll({
            'factor_type': 'phone',
            'phone': phone_number
        })
        
        if auth_response.error:
            raise HTTPException(status_code=400, detail=str(auth_response.error))
        
        # Store phone number in our settings table (not verified yet)
        if result.data:
            # Update existing record
            supabase_client.table('user_mfa_settings').update({
                'phone_number': phone_number,
                'updated_at': datetime.now(timezone.utc).isoformat()
            }).eq('user_id', user_id).execute()
        else:
            # Create new record
            supabase_client.table('user_mfa_settings').insert({
                'user_id': user_id,
                'phone_number': phone_number,
                'mfa_enabled': False,
                'phone_verified': False
            }).execute()
        
        return JSONResponse(content={
            "success": True,
            "factor_id": auth_response.data.get('id'),
            "message": "Verification code sent to your phone"
        })
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/verify-enrollment")
async def verify_enrollment(
    request: Request,
    factor_id: str = Body(...),
    code: str = Body(...),
    current_user: dict = Depends(get_current_user)
):
    """
    Complete MFA enrollment by verifying the code
    """
    try:
        user_id = current_user['id']
        
        # Verify the code with Supabase Auth
        auth_response = supabase_client.auth.mfa.verify({
            'factor_id': factor_id,
            'code': code
        })
        
        if auth_response.error:
            raise HTTPException(status_code=400, detail="Invalid verification code")
        
        # Mark MFA as enabled in our settings
        supabase_client.table('user_mfa_settings').update({
            'mfa_enabled': True,
            'phone_verified': True,
            'enrollment_completed_at': datetime.now(timezone.utc).isoformat(),
            'updated_at': datetime.now(timezone.utc).isoformat()
        }).eq('user_id', user_id).execute()
        
        # Generate backup codes
        backup_codes = []
        for _ in range(8):
            code = secrets.token_hex(4).upper()  # 8 character hex codes
            code_hash = hash_token(code)
            backup_codes.append(code)
            
            # Store hashed backup code
            supabase_client.table('user_mfa_backup_codes').insert({
                'user_id': user_id,
                'code_hash': code_hash
            }).execute()
        
        return JSONResponse(content={
            "success": True,
            "message": "MFA enrollment completed successfully",
            "backup_codes": backup_codes,
            "warning": "Save these backup codes in a safe place. They can be used to access your account if you lose your phone."
        })
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/challenge")
async def create_mfa_challenge(
    request: Request,
    user_id: str = Body(..., embed=True)
):
    """
    Create MFA challenge (send code to phone)
    """
    try:
        # Get user's MFA settings
        result = supabase_client.table('user_mfa_settings').select('*').eq('user_id', user_id).single().execute()
        
        if not result.data or not result.data.get('mfa_enabled'):
            return JSONResponse(content={"mfa_required": False})
        
        # Get user's enrolled factors
        factors_response = supabase_client.auth.mfa.list_factors()
        
        if not factors_response.data:
            raise HTTPException(status_code=400, detail="No MFA factors enrolled")
        
        # Find phone factor
        phone_factor = next((f for f in factors_response.data if f['factor_type'] == 'phone'), None)
        
        if not phone_factor:
            raise HTTPException(status_code=400, detail="Phone MFA not enrolled")
        
        # Create challenge (sends SMS)
        challenge_response = supabase_client.auth.mfa.challenge({
            'factor_id': phone_factor['id']
        })
        
        if challenge_response.error:
            raise HTTPException(status_code=400, detail=str(challenge_response.error))
        
        # Update last challenge timestamp
        supabase_client.table('user_mfa_settings').update({
            'last_challenge_at': datetime.now(timezone.utc).isoformat()
        }).eq('user_id', user_id).execute()
        
        return JSONResponse(content={
            "mfa_required": True,
            "factor_id": phone_factor['id'],
            "challenge_id": challenge_response.data.get('id'),
            "phone_masked": phone_factor.get('phone', '')[-4:]  # Last 4 digits
        })
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/verify")
async def verify_mfa(
    request: Request,
    factor_id: str = Body(...),
    code: str = Body(...),
    remember_device: bool = Body(default=False),
    device_name: Optional[str] = Body(default=None)
):
    """
    Verify MFA code and optionally remember device
    """
    try:
        # Verify the code
        auth_response = supabase_client.auth.mfa.verify({
            'factor_id': factor_id,
            'code': code
        })
        
        if auth_response.error:
            raise HTTPException(status_code=400, detail="Invalid verification code")
        
        user = auth_response.data.get('user')
        if not user:
            raise HTTPException(status_code=400, detail="Authentication failed")
        
        response_data = {
            "success": True,
            "user": user,
            "session": auth_response.data.get('session')
        }
        
        # If remember device is requested, create a device token
        if remember_device:
            token, token_hash = generate_device_token()
            
            # Get device info from request
            user_agent = request.headers.get('user-agent', '')
            ip_address = request.client.host if request.client else None
            
            # Store device token (expires in 30 days)
            expires_at = datetime.now(timezone.utc) + timedelta(days=30)
            
            supabase_client.table('user_trusted_devices').insert({
                'user_id': user['id'],
                'device_token_hash': token_hash,
                'device_name': device_name or 'Unknown Device',
                'user_agent': user_agent,
                'ip_address': ip_address,
                'expires_at': expires_at.isoformat()
            }).execute()
            
            response_data['device_token'] = token
            response_data['device_expires_at'] = expires_at.isoformat()
        
        return JSONResponse(content=response_data)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/check-device")
async def check_device_trust(
    request: Request,
    device_token: Optional[str] = Cookie(default=None)
):
    """
    Check if current device is trusted
    """
    try:
        if not device_token:
            return JSONResponse(content={"trusted": False})
        
        token_hash = hash_token(device_token)
        
        # Check if token exists and is not expired
        result = supabase_client.rpc('is_device_trusted', {
            'p_user_id': request.state.user['id'],
            'p_device_token_hash': token_hash
        }).execute()
        
        return JSONResponse(content={"trusted": result.data})
        
    except Exception as e:
        return JSONResponse(content={"trusted": False})

@router.get("/settings")
async def get_mfa_settings(
    current_user: dict = Depends(get_current_user)
):
    """
    Get user's MFA settings
    """
    try:
        user_id = current_user['id']
        
        # Get MFA settings
        settings_result = supabase_client.table('user_mfa_settings').select('*').eq('user_id', user_id).single().execute()
        
        # Get trusted devices
        devices_result = supabase_client.table('user_trusted_devices').select('*').eq('user_id', user_id).gte('expires_at', datetime.now(timezone.utc).isoformat()).execute()
        
        return JSONResponse(content={
            "mfa_enabled": settings_result.data.get('mfa_enabled', False) if settings_result.data else False,
            "phone_number": settings_result.data.get('phone_number') if settings_result.data else None,
            "trusted_devices": devices_result.data if devices_result.data else []
        })
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/disable")
async def disable_mfa(
    current_user: dict = Depends(get_current_user)
):
    """
    Disable MFA for user
    """
    try:
        user_id = current_user['id']
        
        # Update MFA settings
        supabase_client.table('user_mfa_settings').update({
            'mfa_enabled': False,
            'updated_at': datetime.now(timezone.utc).isoformat()
        }).eq('user_id', user_id).execute()
        
        # Remove all trusted devices
        supabase_client.table('user_trusted_devices').delete().eq('user_id', user_id).execute()
        
        # Remove backup codes
        supabase_client.table('user_mfa_backup_codes').delete().eq('user_id', user_id).execute()
        
        return JSONResponse(content={
            "success": True,
            "message": "MFA has been disabled"
        })
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/device/{device_id}")
async def revoke_device(
    device_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Revoke a trusted device
    """
    try:
        user_id = current_user['id']
        
        # Delete the device
        supabase_client.table('user_trusted_devices').delete().eq('id', device_id).eq('user_id', user_id).execute()
        
        return JSONResponse(content={
            "success": True,
            "message": "Device access revoked"
        })
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
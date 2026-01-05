"""
Unified MFA Implementation - Simple, Robust, Reliable
This is the single source of truth for all MFA operations.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Body
from fastapi.responses import JSONResponse
from typing import Optional, Dict, Any, Tuple
import httpx
import os
import secrets
import hashlib
from datetime import datetime, timezone, timedelta
from app.core.clients import get_supabase_client
from app.core.auth import get_current_user
from app.utils.retry_utils import log_debug

router = APIRouter(prefix="/mfa", tags=["MFA"])

# Configuration
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
MAX_ATTEMPTS = 5
RATE_LIMIT_WINDOW_MINUTES = 15
DEVICE_TRUST_DAYS = 30


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def hash_token(token: str) -> str:
    """Hash a token using SHA-256 for secure storage"""
    return hashlib.sha256(token.encode()).hexdigest()


def generate_device_token() -> Tuple[str, str]:
    """Generate a secure device token and its hash"""
    token = secrets.token_urlsafe(32)  # 256-bit token
    token_hash = hash_token(token)
    return token, token_hash


def get_client_ip(request: Request) -> str:
    """Extract real client IP address from request"""
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # Get first IP in case of multiple proxies
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


def get_user_token(request: Request) -> str:
    """Extract JWT token from Authorization header"""
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization")
    return auth_header.split(" ", 1)[1]


# ============================================================================
# RATE LIMITING
# ============================================================================

def check_rate_limit(
    user_id: str,
    attempt_type: str,
    max_attempts: int = MAX_ATTEMPTS,
    window_minutes: int = RATE_LIMIT_WINDOW_MINUTES
) -> Tuple[bool, int, Optional[float]]:
    """
    Check if user has exceeded rate limit

    Returns:
        tuple: (is_allowed: bool, attempts_remaining: int, retry_after_minutes: float|None)
    """
    try:
        supabase = get_supabase_client()
        now = datetime.now(timezone.utc)

        # Get current rate limit record
        result = supabase.table('mfa_rate_limits') \
            .select('*') \
            .eq('user_id', user_id) \
            .eq('attempt_type', attempt_type) \
            .execute()

        if not result.data:
            # First attempt - create record
            supabase.table('mfa_rate_limits').insert({
                'user_id': user_id,
                'attempt_type': attempt_type,
                'attempt_count': 1,
                'window_start': now.isoformat()
            }).execute()
            log_debug(f"Rate Limit: First {attempt_type} attempt for user {user_id}", service="mfa")
            return True, max_attempts - 1, None

        record = result.data[0]
        window_start = datetime.fromisoformat(record['window_start'].replace('Z', '+00:00'))
        window_end = window_start + timedelta(minutes=window_minutes)

        # Check if window has expired
        if now > window_end:
            # Reset counter for new window
            supabase.table('mfa_rate_limits') \
                .update({
                    'attempt_count': 1,
                    'window_start': now.isoformat()
                }) \
                .eq('user_id', user_id) \
                .eq('attempt_type', attempt_type) \
                .execute()
            log_debug(f"Rate Limit: Window expired - reset counter for user {user_id}", service="mfa")
            return True, max_attempts - 1, None

        current_count = record['attempt_count']

        # Check if limit exceeded
        if current_count >= max_attempts:
            retry_after = (window_end - now).total_seconds() / 60.0
            log_debug(f"Rate Limit: EXCEEDED for user {user_id} - {current_count}/{max_attempts} attempts, retry in {retry_after:.1f}min", service="mfa")
            return False, 0, retry_after

        # Increment attempt count
        supabase.table('mfa_rate_limits') \
            .update({'attempt_count': current_count + 1}) \
            .eq('user_id', user_id) \
            .eq('attempt_type', attempt_type) \
            .execute()

        remaining = max_attempts - (current_count + 1)
        log_debug(f"Rate Limit: {attempt_type} attempt {current_count + 1}/{max_attempts} for user {user_id}, {remaining} remaining", service="mfa")
        return True, remaining, None

    except Exception as e:
        log_debug(f"Rate Limit: Check failed: {e} - failing open (allowing request)", service="mfa")
        return True, max_attempts, None


# ============================================================================
# SUPABASE AUTH API HELPERS
# ============================================================================

async def get_user_factors(token: str) -> list:
    """Get MFA factors for the authenticated user from Supabase Auth"""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{SUPABASE_URL}/auth/v1/user",
            headers={
                "Authorization": f"Bearer {token}",
                "apikey": SUPABASE_ANON_KEY
            }
        )

        if response.status_code != 200:
            log_debug(f"Auth API: Failed to get user factors: {response.text}", service="mfa")
            return []

        user_data = response.json()
        return user_data.get('factors', [])


async def create_phone_factor(token: str, phone_number: str) -> Dict[str, Any]:
    """Create a new phone MFA factor via Supabase Auth"""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{SUPABASE_URL}/auth/v1/factors",
            headers={
                "Authorization": f"Bearer {token}",
                "apikey": SUPABASE_ANON_KEY,
                "Content-Type": "application/json"
            },
            json={
                "factor_type": "phone",
                "friendly_name": "Phone",
                "phone": phone_number
            }
        )

        if response.status_code not in [200, 201]:
            log_debug(f"Auth API: Failed to create phone factor: {response.text}", service="mfa")
            raise HTTPException(
                status_code=response.status_code,
                detail="Failed to create MFA factor. Please check your phone number."
            )

        return response.json()


async def delete_phone_factor(token: str, factor_id: str) -> bool:
    """Delete an MFA factor"""
    async with httpx.AsyncClient() as client:
        response = await client.delete(
            f"{SUPABASE_URL}/auth/v1/factors/{factor_id}",
            headers={
                "Authorization": f"Bearer {token}",
                "apikey": SUPABASE_ANON_KEY
            }
        )
        return response.status_code in [200, 204]


async def create_mfa_challenge(token: str, factor_id: str, user_ip: str) -> Dict[str, Any]:
    """Create an MFA challenge (sends SMS code)"""
    async with httpx.AsyncClient() as client:
        headers = {
            "Authorization": f"Bearer {token}",
            "apikey": SUPABASE_ANON_KEY,
            "Content-Type": "application/json",
            "X-Forwarded-For": user_ip  # Prevent IP mismatch errors
        }

        response = await client.post(
            f"{SUPABASE_URL}/auth/v1/factors/{factor_id}/challenge",
            headers=headers,
            json={}
        )

        if response.status_code != 200:
            log_debug(f"Auth API: Failed to create challenge: {response.text}", service="mfa")
            raise HTTPException(
                status_code=response.status_code,
                detail="Failed to send verification code. Please try again."
            )

        return response.json()


async def verify_mfa_challenge(
    token: str,
    factor_id: str,
    challenge_id: str,
    code: str,
    user_ip: str
) -> Dict[str, Any]:
    """Verify an MFA challenge with the user's code"""
    async with httpx.AsyncClient() as client:
        headers = {
            "Authorization": f"Bearer {token}",
            "apikey": SUPABASE_ANON_KEY,
            "Content-Type": "application/json",
            "X-Forwarded-For": user_ip  # Prevent IP mismatch errors
        }

        response = await client.post(
            f"{SUPABASE_URL}/auth/v1/factors/{factor_id}/verify",
            headers=headers,
            json={
                "challenge_id": challenge_id,
                "code": code
            }
        )

        if response.status_code != 200:
            error_text = response.text.lower()
            if "invalid" in error_text or "incorrect" in error_text:
                raise HTTPException(status_code=400, detail="INVALID_CODE")
            elif "expired" in error_text:
                raise HTTPException(status_code=400, detail="CODE_EXPIRED")
            else:
                log_debug(f"Auth API: Verification failed: {response.text}", service="mfa")
                raise HTTPException(status_code=response.status_code, detail="Verification failed")

        return response.json()


# ============================================================================
# DATABASE HELPERS
# ============================================================================

def get_mfa_settings(user_id: str) -> Optional[Dict]:
    """Get user's MFA settings from database"""
    result = get_supabase_client().table('user_mfa_settings') \
        .select('*') \
        .eq('user_id', user_id) \
        .execute()

    return result.data[0] if result.data else None


def update_mfa_verified_timestamp(user_id: str) -> None:
    """Mark MFA as verified for this session"""
    try:
        get_supabase_client().table('profiles').update({
            'mfa_verified_at': datetime.now(timezone.utc).isoformat()
        }).eq('id', user_id).execute()
        log_debug(f"MFA] Set mfa_verified_at for user {user_id}", service="mfa")
    except Exception as e:
        log_debug(f"MFA] Warning: Failed to set mfa_verified_at: {e}", service="mfa")
        # Don't fail the request


def save_trusted_device(user_id: str, device_token_hash: str, device_name: str) -> datetime:
    """Save a trusted device token"""
    expires_at = datetime.now(timezone.utc) + timedelta(days=DEVICE_TRUST_DAYS)

    get_supabase_client().table('trusted_devices').insert({
        'user_id': user_id,
        'device_token_hash': device_token_hash,
        'device_name': device_name,
        'expires_at': expires_at.isoformat()
    }).execute()

    log_debug(f"Device Trust] Saved new trusted device for user {user_id} (expires in {DEVICE_TRUST_DAYS} days)", service="mfa")
    return expires_at


def is_device_trusted(user_id: str, device_token_hash: str) -> bool:
    """Check if device token is valid and not expired"""
    result = get_supabase_client().table('trusted_devices') \
        .select('*') \
        .eq('user_id', user_id) \
        .eq('device_token_hash', device_token_hash) \
        .execute()

    if not result.data:
        return False

    device = result.data[0]
    expires_at = datetime.fromisoformat(device['expires_at'].replace('Z', '+00:00'))

    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    return expires_at > datetime.now(timezone.utc)


# ============================================================================
# API ENDPOINTS
# ============================================================================

@router.post("/check-device")
async def check_device(
    request: Request,
    device_token: str = Body(..., embed=True),
    current_user: dict = Depends(get_current_user)
) -> JSONResponse:
    """
    Check if device is trusted (30-day exemption)

    This should be called FIRST before any MFA challenge.
    If device is trusted, set mfa_verified_at and skip MFA.
    """
    try:
        user_id = current_user['id']

        if not device_token:
            return JSONResponse(content={
                "trusted": False,
                "needs_mfa": True
            })

        token_hash = hash_token(device_token)
        trusted = is_device_trusted(user_id, token_hash)

        log_debug(f"Device Check] User {user_id} - Trusted: {trusted}", service="mfa")

        if trusted:
            # Device is trusted - mark session as MFA verified
            update_mfa_verified_timestamp(user_id)
            return JSONResponse(content={
                "trusted": True,
                "needs_mfa": False
            })

        return JSONResponse(content={
            "trusted": False,
            "needs_mfa": True
        })

    except Exception as e:
        log_debug(f"Device Check] Error: {e}", service="mfa")
        return JSONResponse(content={
            "trusted": False,
            "needs_mfa": True,
            "error": "CHECK_FAILED"
        })


@router.post("/enroll")
async def enroll(
    request: Request,
    phone_number: str = Body(..., embed=True),
    current_user: dict = Depends(get_current_user)
) -> JSONResponse:
    """
    Enroll user in MFA with phone number

    This endpoint:
    1. Creates/updates user_mfa_settings with phone number (but MFA not enabled yet)
    2. Deletes any old unverified factors
    3. Creates new phone factor in Supabase Auth
    4. Sends SMS verification code
    """
    try:
        user_id = current_user['id']
        token = get_user_token(request)
        user_ip = get_client_ip(request)

        # Rate limit enrollment attempts
        allowed, remaining, retry_after = check_rate_limit(user_id, 'enroll')
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail=f"RATE_LIMITED|{int(retry_after or 15)}"
            )

        log_debug(f"MFA Enroll] User {user_id} enrolling with phone {phone_number}", service="mfa")

        # Check if user already has verified factors
        existing_factors = await get_user_factors(token)
        verified_phone_factors = [
            f for f in existing_factors
            if f.get('factor_type') == 'phone' and f.get('status') == 'verified'
        ]

        if verified_phone_factors:
            # User already enrolled - just send a new challenge
            log_debug(f"MFA Enroll] User already has verified factor, sending challenge", service="mfa")
            factor = verified_phone_factors[0]
            challenge = await create_mfa_challenge(token, factor['id'], user_ip)

            # Update phone number in settings if different
            get_supabase_client().table('user_mfa_settings').upsert({
                'user_id': user_id,
                'phone_number': phone_number,
                'updated_at': datetime.now(timezone.utc).isoformat()
            }).execute()

            return JSONResponse(content={
                "success": True,
                "factor_id": factor['id'],
                "challenge_id": challenge['id'],
                "message": "Code sent to your phone"
            })

        # Delete any old unverified factors
        unverified_factors = [
            f for f in existing_factors
            if f.get('factor_type') == 'phone' and f.get('status') == 'unverified'
        ]
        for old_factor in unverified_factors:
            log_debug(f"MFA Enroll] Deleting old unverified factor {old_factor['id']}", service="mfa")
            await delete_phone_factor(token, old_factor['id'])

        # Create new phone factor
        factor = await create_phone_factor(token, phone_number)
        log_debug(f"MFA Enroll] Created new factor {factor['id']}", service="mfa")

        # Send verification code
        challenge = await create_mfa_challenge(token, factor['id'], user_ip)

        # Save phone number to database (but don't enable MFA yet)
        get_supabase_client().table('user_mfa_settings').upsert({
            'user_id': user_id,
            'phone_number': phone_number,
            'mfa_enabled': False,  # Will be set to true after verification
            'phone_verified': False,
            'updated_at': datetime.now(timezone.utc).isoformat()
        }).execute()

        return JSONResponse(content={
            "success": True,
            "factor_id": factor['id'],
            "challenge_id": challenge['id'],
            "message": "Code sent to your phone"
        })

    except HTTPException:
        raise
    except Exception as e:
        log_debug(f"MFA Enroll] Error: {e}", service="mfa")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/verify-enrollment")
async def verify_enrollment(
    request: Request,
    factor_id: str = Body(...),
    challenge_id: str = Body(...),
    code: str = Body(...),
    remember_device: bool = Body(default=True),
    device_name: str = Body(default="Device"),
    current_user: dict = Depends(get_current_user)
) -> JSONResponse:
    """
    Verify enrollment code and enable MFA

    This endpoint:
    1. Verifies the SMS code
    2. Enables MFA in database
    3. Marks session as MFA verified
    4. Optionally creates trusted device token (30-day exemption)
    """
    try:
        user_id = current_user['id']
        token = get_user_token(request)
        user_ip = get_client_ip(request)

        # Rate limit verification attempts
        allowed, remaining, retry_after = check_rate_limit(user_id, 'verify')
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail=f"RATE_LIMITED|{int(retry_after or 15)}"
            )

        log_debug(f"MFA Verify Enrollment] User {user_id} verifying code ({remaining} attempts remaining)", service="mfa")

        # Verify the code
        verify_result = await verify_mfa_challenge(token, factor_id, challenge_id, code, user_ip)

        # Get phone number from settings
        settings = get_mfa_settings(user_id)
        phone_number = settings.get('phone_number') if settings else None

        if not phone_number:
            raise HTTPException(
                status_code=400,
                detail="PHONE_REQUIRED|Phone number missing, please re-enroll"
            )

        # Enable MFA in database
        get_supabase_client().table('user_mfa_settings').upsert({
            'user_id': user_id,
            'phone_number': phone_number,
            'mfa_enabled': True,
            'phone_verified': True,
            'enrollment_completed_at': datetime.now(timezone.utc).isoformat(),
            'updated_at': datetime.now(timezone.utc).isoformat()
        }).execute()

        # Mark session as MFA verified
        update_mfa_verified_timestamp(user_id)

        log_debug(f"MFA Verify Enrollment] Successfully enrolled user {user_id}", service="mfa")

        response_data = {
            "success": True,
            "message": "MFA enabled successfully"
        }

        # Create trusted device if requested
        if remember_device:
            device_token, token_hash = generate_device_token()
            expires_at = save_trusted_device(user_id, token_hash, device_name)

            response_data['device_token'] = device_token
            response_data['device_expires_at'] = expires_at.isoformat()

        # Include new session if provided
        if 'access_token' in verify_result:
            response_data['session'] = {
                'access_token': verify_result.get('access_token'),
                'refresh_token': verify_result.get('refresh_token'),
                'expires_at': verify_result.get('expires_at'),
                'expires_in': verify_result.get('expires_in')
            }

        return JSONResponse(content=response_data)

    except HTTPException:
        raise
    except Exception as e:
        log_debug(f"MFA Verify Enrollment] Error: {e}", service="mfa")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/challenge")
async def challenge(
    request: Request,
    current_user: dict = Depends(get_current_user)
) -> JSONResponse:
    """
    Create MFA challenge for login

    This endpoint:
    1. Checks if user has MFA enabled
    2. Validates user has phone number
    3. Sends SMS code to user's phone
    """
    try:
        user_id = current_user['id']
        token = get_user_token(request)
        user_ip = get_client_ip(request)

        # Rate limit challenge requests
        allowed, remaining, retry_after = check_rate_limit(user_id, 'challenge')
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail=f"RATE_LIMITED|{int(retry_after or 15)}"
            )

        log_debug(f"MFA Challenge] User {user_id} requesting challenge", service="mfa")

        # Get MFA settings
        settings = get_mfa_settings(user_id)

        if not settings or not settings.get('mfa_enabled'):
            return JSONResponse(content={
                "mfa_required": False,
                "needs_enrollment": True
            })

        # Validate phone number exists
        phone_number = settings.get('phone_number', '')
        if not phone_number or phone_number.strip() == '':
            log_debug(f"MFA Challenge] ERROR: MFA enabled but no phone number for user {user_id}", service="mfa")
            return JSONResponse(content={
                "mfa_required": True,
                "error": "PHONE_REQUIRED",
                "needs_enrollment": True
            })

        # Get verified phone factors
        factors = await get_user_factors(token)
        verified_factors = [
            f for f in factors
            if f.get('factor_type') == 'phone' and f.get('status') == 'verified'
        ]

        if not verified_factors:
            log_debug(f"MFA Challenge] No verified factors for user {user_id}", service="mfa")
            return JSONResponse(content={
                "mfa_required": True,
                "error": "NO_VERIFIED_FACTOR",
                "needs_enrollment": True
            })

        # Send challenge
        factor = verified_factors[0]
        challenge_result = await create_mfa_challenge(token, factor['id'], user_ip)

        # Update last challenge timestamp
        get_supabase_client().table('user_mfa_settings').update({
            'last_challenge_at': datetime.now(timezone.utc).isoformat()
        }).eq('user_id', user_id).execute()

        log_debug(f"MFA Challenge] Challenge sent to user {user_id}", service="mfa")

        return JSONResponse(content={
            "mfa_required": True,
            "factor_id": factor['id'],
            "challenge_id": challenge_result['id'],
            "phone_masked": phone_number[-4:] if len(phone_number) >= 4 else "***"
        })

    except HTTPException:
        raise
    except Exception as e:
        log_debug(f"MFA Challenge] Error: {e}", service="mfa")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/verify")
async def verify(
    request: Request,
    factor_id: str = Body(...),
    challenge_id: str = Body(...),
    code: str = Body(...),
    remember_device: bool = Body(default=False),
    device_name: str = Body(default="Device"),
    current_user: dict = Depends(get_current_user)
) -> JSONResponse:
    """
    Verify MFA challenge for login

    This endpoint:
    1. Verifies the SMS code
    2. Marks session as MFA verified
    3. Optionally creates trusted device token
    """
    try:
        user_id = current_user['id']
        token = get_user_token(request)
        user_ip = get_client_ip(request)

        # Rate limit verification attempts
        allowed, remaining, retry_after = check_rate_limit(user_id, 'verify')
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail=f"RATE_LIMITED|{int(retry_after or 15)}"
            )

        log_debug(f"MFA Verify] User {user_id} verifying code ({remaining} attempts remaining)", service="mfa")

        # Verify the code
        verify_result = await verify_mfa_challenge(token, factor_id, challenge_id, code, user_ip)

        # Mark session as MFA verified
        update_mfa_verified_timestamp(user_id)

        log_debug(f"MFA Verify] Successfully verified user {user_id}", service="mfa")

        response_data = {
            "success": True,
            "user": current_user
        }

        # Create trusted device if requested
        if remember_device:
            device_token, token_hash = generate_device_token()
            expires_at = save_trusted_device(user_id, token_hash, device_name)

            response_data['device_token'] = device_token
            response_data['device_expires_at'] = expires_at.isoformat()

        # Include new session if provided
        if 'access_token' in verify_result:
            response_data['session'] = {
                'access_token': verify_result.get('access_token'),
                'refresh_token': verify_result.get('refresh_token'),
                'expires_at': verify_result.get('expires_at'),
                'expires_in': verify_result.get('expires_in')
            }

        return JSONResponse(content=response_data)

    except HTTPException:
        raise
    except Exception as e:
        log_debug(f"MFA Verify] Error: {e}", service="mfa")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/status")
async def status(
    request: Request,
    current_user: dict = Depends(get_current_user)
) -> JSONResponse:
    """
    Get MFA status for current user

    Returns information about whether user has MFA enabled and properly configured
    """
    try:
        user_id = current_user['id']
        token = get_user_token(request)

        # Get database settings
        settings = get_mfa_settings(user_id)

        # Get Supabase Auth factors
        factors = await get_user_factors(token)
        verified_factors = [
            f for f in factors
            if f.get('factor_type') == 'phone' and f.get('status') == 'verified'
        ]

        mfa_enabled = settings.get('mfa_enabled', False) if settings else False
        has_verified_factor = len(verified_factors) > 0
        has_phone_number = bool(settings and settings.get('phone_number'))

        # MFA is truly enabled only if all conditions are met
        fully_configured = mfa_enabled and has_verified_factor and has_phone_number

        return JSONResponse(content={
            "mfa_enabled": mfa_enabled,
            "has_verified_factor": has_verified_factor,
            "has_phone_number": has_phone_number,
            "fully_configured": fully_configured,
            "needs_enrollment": not fully_configured,
            "phone_number": settings.get('phone_number', '') if settings else ''
        })

    except Exception as e:
        log_debug(f"MFA Status] Error: {e}", service="mfa")
        return JSONResponse(content={
            "error": str(e),
            "needs_enrollment": True
        })

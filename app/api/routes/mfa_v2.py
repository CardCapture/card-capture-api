"""
Robust MFA implementation for Supabase
This is a complete rewrite with proper error handling and state management
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Body, Header
from fastapi.responses import JSONResponse
from typing import Optional, Dict, Any, Tuple
import httpx
import os
import secrets
import hashlib
from datetime import datetime, timezone, timedelta
from app.core.clients import get_supabase_client
from app.core.auth import get_current_user

router = APIRouter(prefix="/mfa2", tags=["MFA-V2"])

# Configuration
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")

def hash_token(token: str) -> str:
    """Hash a token for secure storage"""
    return hashlib.sha256(token.encode()).hexdigest()

def generate_device_token() -> Tuple[str, str]:
    """Generate a secure device token and its hash"""
    token = secrets.token_urlsafe(32)
    token_hash = hash_token(token)
    return token, token_hash

class MFAService:
    """Centralized MFA service for all operations"""
    
    @staticmethod
    def get_user_token(request: Request) -> str:
        """Extract user token from request"""
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing or invalid authorization")
        return auth_header.split(" ", 1)[1]
    
    @staticmethod
    async def get_user_factors(token: str) -> list:
        """Get MFA factors for the authenticated user"""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{SUPABASE_URL}/auth/v1/user",
                headers={
                    "Authorization": f"Bearer {token}",
                    "apikey": SUPABASE_ANON_KEY
                }
            )
            
            if response.status_code != 200:
                print(f"[MFA] Failed to get user factors: {response.text}")
                return []
            
            user_data = response.json()
            return user_data.get('factors', [])
    
    @staticmethod
    async def delete_factor(token: str, factor_id: str) -> bool:
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
    
    @staticmethod
    async def create_factor(token: str, phone_number: str) -> Dict[str, Any]:
        """Create a new MFA factor"""
        print(f"[MFA Service] Creating factor with phone: {repr(phone_number)}")
        print(f"[MFA Service] Phone number length: {len(phone_number)}")
        for i, char in enumerate(phone_number):
            print(f"[MFA Service] Phone char {i}: {repr(char)} (ord: {ord(char)})")
        
        async with httpx.AsyncClient() as client:
            payload = {
                "factor_type": "phone",
                "friendly_name": "Phone",
                "phone": phone_number
            }
            print(f"[MFA Service] Payload being sent: {payload}")
            
            response = await client.post(
                f"{SUPABASE_URL}/auth/v1/factors",
                headers={
                    "Authorization": f"Bearer {token}",
                    "apikey": SUPABASE_ANON_KEY,
                    "Content-Type": "application/json"
                },
                json=payload
            )
            
            if response.status_code not in [200, 201]:
                print(f"[MFA] Failed to create factor: {response.text}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to create MFA factor: {response.text}"
                )
            
            return response.json()
    
    @staticmethod
    async def create_challenge(token: str, factor_id: str) -> Dict[str, Any]:
        """Create a challenge for a factor"""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{SUPABASE_URL}/auth/v1/factors/{factor_id}/challenge",
                headers={
                    "Authorization": f"Bearer {token}",
                    "apikey": SUPABASE_ANON_KEY,
                    "Content-Type": "application/json"
                },
                json={}
            )
            
            if response.status_code != 200:
                print(f"[MFA] Failed to create challenge: {response.text}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to create challenge: {response.text}"
                )
            
            return response.json()
    
    @staticmethod
    async def verify_challenge(token: str, factor_id: str, challenge_id: str, code: str) -> Dict[str, Any]:
        """Verify a challenge with a code"""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{SUPABASE_URL}/auth/v1/factors/{factor_id}/verify",
                headers={
                    "Authorization": f"Bearer {token}",
                    "apikey": SUPABASE_ANON_KEY,
                    "Content-Type": "application/json"
                },
                json={
                    "challenge_id": challenge_id,
                    "code": code
                }
            )
            
            if response.status_code != 200:
                print(f"[MFA] Verification failed: {response.text}")
                # Check if it's an invalid code
                if "invalid" in response.text.lower() or "incorrect" in response.text.lower():
                    raise HTTPException(status_code=400, detail="Invalid verification code")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Verification failed: {response.text}"
                )
            
            return response.json()


@router.post("/status")
async def check_mfa_status(
    request: Request,
    current_user: dict = Depends(get_current_user)
) -> JSONResponse:
    """Check if MFA is enabled and properly configured for the user"""
    try:
        user_id = current_user['id']
        token = MFAService.get_user_token(request)
        
        # Check database settings
        db_settings = get_supabase_client().table('user_mfa_settings') \
            .select('*') \
            .eq('user_id', user_id) \
            .single() \
            .execute()
        
        # Check actual factors
        factors = await MFAService.get_user_factors(token)
        phone_factors = [f for f in factors if f.get('factor_type') == 'phone']
        verified_factors = [f for f in phone_factors if f.get('status') == 'verified']
        
        return JSONResponse(content={
            "has_mfa_settings": bool(db_settings.data),
            "mfa_enabled": db_settings.data.get('mfa_enabled', False) if db_settings.data else False,
            "has_factors": len(factors) > 0,
            "has_verified_factors": len(verified_factors) > 0,
            "factors_count": len(factors),
            "verified_factors_count": len(verified_factors),
            "needs_enrollment": len(verified_factors) == 0
        })
        
    except Exception as e:
        print(f"[MFA Status] Error: {e}")
        return JSONResponse(content={
            "error": str(e),
            "needs_enrollment": True
        })


@router.post("/enroll")
async def enroll_mfa(
    request: Request,
    phone_number: str = Body(..., embed=True),
    current_user: dict = Depends(get_current_user)
) -> JSONResponse:
    """Start MFA enrollment"""
    try:
        user_id = current_user['id']
        token = MFAService.get_user_token(request)
        
        print(f"[MFA Enroll] Starting for user {user_id} with phone {phone_number}")
        print(f"[MFA Enroll] Phone number type: {type(phone_number)}")
        print(f"[MFA Enroll] Phone number repr: {repr(phone_number)}")
        print(f"[MFA Enroll] Phone number length: {len(phone_number)}")
        for i, char in enumerate(phone_number):
            print(f"[MFA Enroll] Phone char {i}: {repr(char)} (ord: {ord(char)})")
        
        # Check if user already has verified factors
        existing_factors = await MFAService.get_user_factors(token)
        verified_phone_factors = [
            f for f in existing_factors 
            if f.get('factor_type') == 'phone' and f.get('status') == 'verified'
        ]
        
        if verified_phone_factors:
            print(f"[MFA Enroll] User already has verified phone factor")
            # Just create a challenge for the existing factor
            factor = verified_phone_factors[0]
            challenge = await MFAService.create_challenge(token, factor['id'])
            
            return JSONResponse(content={
                "success": True,
                "factor_id": factor['id'],
                "challenge_id": challenge['id'],
                "message": "Verification code sent to your enrolled phone"
            })
        
        # Check for unverified factors and delete them
        unverified_phone_factors = [
            f for f in existing_factors
            if f.get('factor_type') == 'phone' and f.get('status') == 'unverified'
        ]
        
        # Delete all existing unverified factors before creating a new one
        for old_factor in unverified_phone_factors:
            print(f"[MFA Enroll] Deleting old unverified factor: {old_factor['id']}")
            await MFAService.delete_factor(token, old_factor['id'])
        
        # Now create a new factor with the provided phone number
        print(f"[MFA Enroll] Creating new factor with phone: {phone_number}")
        factor = await MFAService.create_factor(token, phone_number)
        
        # Create challenge
        print(f"[MFA Enroll] Creating challenge for factor {factor['id']}")
        challenge = await MFAService.create_challenge(token, factor['id'])
        
        # Update database settings
        existing_settings = get_supabase_client().table('user_mfa_settings') \
            .select('*') \
            .eq('user_id', user_id) \
            .execute()
        
        if existing_settings.data:
            get_supabase_client().table('user_mfa_settings').update({
                'phone_number': phone_number,
                'updated_at': datetime.now(timezone.utc).isoformat()
            }).eq('user_id', user_id).execute()
        else:
            get_supabase_client().table('user_mfa_settings').insert({
                'user_id': user_id,
                'phone_number': phone_number,
                'mfa_enabled': False,
                'phone_verified': False
            }).execute()
        
        return JSONResponse(content={
            "success": True,
            "factor_id": factor['id'],
            "challenge_id": challenge['id'],
            "message": "Verification code sent to your phone"
        })
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"[MFA Enroll] Exception: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/verify-enrollment")
async def verify_enrollment(
    request: Request,
    factor_id: str = Body(...),
    challenge_id: str = Body(...),
    code: str = Body(...),
    remember_device: bool = Body(default=True),  # Default to true for enrollment
    device_name: str = Body(default="Device"),
    current_user: dict = Depends(get_current_user)
) -> JSONResponse:
    """Verify MFA enrollment"""
    try:
        user_id = current_user['id']
        token = MFAService.get_user_token(request)
        
        print(f"[MFA Verify] User {user_id} verifying factor {factor_id}")
        
        # Verify the challenge
        verify_result = await MFAService.verify_challenge(token, factor_id, challenge_id, code)
        
        # Update database to mark MFA as enabled (use upsert to handle missing rows)
        print(f"[MFA Verify] Updating database for user {user_id}")
        
        # Get the phone number from the MFA factor or from the request
        # First try to get existing settings
        existing_settings = get_supabase_client().table('user_mfa_settings') \
            .select('*') \
            .eq('user_id', user_id) \
            .execute()
        
        phone_number = existing_settings.data[0]['phone_number'] if existing_settings.data else None
        
        get_supabase_client().table('user_mfa_settings').upsert({
            'user_id': user_id,
            'phone_number': phone_number,
            'mfa_enabled': True,
            'phone_verified': True,
            'enrollment_completed_at': datetime.now(timezone.utc).isoformat(),
            'updated_at': datetime.now(timezone.utc).isoformat()
        }).execute()
        
        # Return the new session if provided
        response_data = {
            "success": True,
            "message": "MFA enrollment completed successfully"
        }
        
        # Handle remember device with smart token generation (after successful enrollment)
        if remember_device:
            # Check if current device already has a valid token
            current_device_token = request.headers.get('X-Device-Token')
            device_token_to_use = None
            
            if current_device_token:
                # Check if current token exists and is not expired
                existing_token_hash = hashlib.sha256(current_device_token.encode()).hexdigest()
                existing_device = get_supabase_client().table('trusted_devices') \
                    .select('*') \
                    .eq('user_id', user_id) \
                    .eq('device_token_hash', existing_token_hash) \
                    .gte('expires_at', datetime.now(timezone.utc).isoformat()) \
                    .execute()
                
                if existing_device.data:
                    # Current token is valid, extend its expiry instead of generating new token
                    new_expires_at = datetime.now(timezone.utc) + timedelta(days=30)
                    get_supabase_client().table('trusted_devices') \
                        .update({
                            'expires_at': new_expires_at.isoformat(),
                            'updated_at': datetime.now(timezone.utc).isoformat(),
                            'device_name': device_name  # Update device name if needed
                        }) \
                        .eq('id', existing_device.data[0]['id']) \
                        .execute()
                    
                    device_token_to_use = current_device_token
                    expires_at = new_expires_at
                    print(f"[MFA Verify Enrollment] Extended existing device token expiry for 30 days")
                else:
                    print(f"[MFA Verify Enrollment] Current device token not found or expired, generating new one")
                    # Current token is expired/invalid, generate new token
                    device_token_to_use, token_hash = generate_device_token()
                    expires_at = datetime.now(timezone.utc) + timedelta(days=30)
                    
                    # Store new device token in database
                    try:
                        get_supabase_client().table('trusted_devices').insert({
                            'user_id': user_id,
                            'device_token_hash': token_hash,
                            'device_name': device_name,
                            'expires_at': expires_at.isoformat()
                        }).execute()
                        print(f"[MFA Verify Enrollment] New device token generated for 30-day trust")
                    except Exception as device_error:
                        print(f"[MFA Verify Enrollment] Error saving new device token: {device_error}")
                        # Don't fail enrollment if device trust fails
                        device_token_to_use = None
            else:
                # No current device token, generate new one
                device_token_to_use, token_hash = generate_device_token()
                expires_at = datetime.now(timezone.utc) + timedelta(days=30)
                
                # Store device token in database
                try:
                    get_supabase_client().table('trusted_devices').insert({
                        'user_id': user_id,
                        'device_token_hash': token_hash,
                        'device_name': device_name,
                        'expires_at': expires_at.isoformat()
                    }).execute()
                    print(f"[MFA Verify Enrollment] New device token generated for 30-day trust")
                except Exception as device_error:
                    print(f"[MFA Verify Enrollment] Error saving device token: {device_error}")
                    # Don't fail enrollment if device trust fails
                    device_token_to_use = None
            
            # Add device token to response if successfully generated/extended
            if device_token_to_use:
                response_data['device_token'] = device_token_to_use
                response_data['device_expires_at'] = expires_at.isoformat()
        
        if 'access_token' in verify_result:
            response_data['session'] = {
                'access_token': verify_result.get('access_token'),
                'refresh_token': verify_result.get('refresh_token'),
                'expires_at': verify_result.get('expires_at'),
                'expires_in': verify_result.get('expires_in')
            }
            print(f"[MFA Verify] New session provided")
        
        return JSONResponse(content=response_data)
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"[MFA Verify] Exception: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/challenge")
async def create_challenge(
    request: Request,
    current_user: dict = Depends(get_current_user)
) -> JSONResponse:
    """Create MFA challenge for login"""
    try:
        user_id = current_user['id']
        token = MFAService.get_user_token(request)
        
        print(f"[MFA Challenge] Creating for user {user_id}")
        
        # Check if MFA is enabled
        settings = get_supabase_client().table('user_mfa_settings') \
            .select('*') \
            .eq('user_id', user_id) \
            .single() \
            .execute()
        
        if not settings.data or not settings.data.get('mfa_enabled'):
            print(f"[MFA Challenge] MFA not enabled for user {user_id}")
            return JSONResponse(content={"mfa_required": False})
        
        # Get verified factors
        factors = await MFAService.get_user_factors(token)
        phone_factors = [
            f for f in factors 
            if f.get('factor_type') == 'phone' and f.get('status') == 'verified'
        ]
        
        if not phone_factors:
            print(f"[MFA Challenge] No verified phone factors for user {user_id}")
            return JSONResponse(content={
                "mfa_required": True,
                "error": "No verified MFA factors found. Please re-enroll.",
                "needs_enrollment": True
            })
        
        # Create challenge for the first phone factor
        factor = phone_factors[0]
        challenge = await MFAService.create_challenge(token, factor['id'])
        
        # Update last challenge timestamp
        get_supabase_client().table('user_mfa_settings').update({
            'last_challenge_at': datetime.now(timezone.utc).isoformat()
        }).eq('user_id', user_id).execute()
        
        # Get phone number for masking
        phone_number = settings.data.get('phone_number', '')
        
        return JSONResponse(content={
            "mfa_required": True,
            "factor_id": factor['id'],
            "challenge_id": challenge['id'],
            "phone_masked": phone_number[-4:] if phone_number else ''
        })
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"[MFA Challenge] Exception: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/verify")
async def verify_mfa(
    request: Request,
    factor_id: str = Body(...),
    challenge_id: str = Body(...),
    code: str = Body(...),
    remember_device: bool = Body(default=False),
    current_user: dict = Depends(get_current_user)
) -> JSONResponse:
    """Verify MFA for login"""
    try:
        user_id = current_user['id']
        token = MFAService.get_user_token(request)
        
        print(f"[MFA Verify Login] User {user_id} verifying")
        
        # Verify the challenge
        verify_result = await MFAService.verify_challenge(token, factor_id, challenge_id, code)
        
        response_data = {
            "success": True,
            "user": current_user
        }
        
        # Include new session if provided
        if 'access_token' in verify_result:
            response_data['session'] = {
                'access_token': verify_result.get('access_token'),
                'refresh_token': verify_result.get('refresh_token'),
                'expires_at': verify_result.get('expires_at'),
                'expires_in': verify_result.get('expires_in')
            }
        
        # Handle remember device with smart token generation
        if remember_device:
            # Check if current device already has a valid token
            current_device_token = request.headers.get('X-Device-Token')
            device_token_to_use = None
            expires_at = datetime.now(timezone.utc) + timedelta(days=30)
            
            if current_device_token:
                print(f"[MFA Verify] Checking if current device token is valid")
                current_token_hash = hash_token(current_device_token)
                
                # Check if current token exists and is not expired
                existing_device = get_supabase_client().table('trusted_devices') \
                    .select('*') \
                    .eq('user_id', user_id) \
                    .eq('device_token_hash', current_token_hash) \
                    .execute()

                print(f"[MFA Verify] Found existing device records: {len(existing_device.data)}")

                if existing_device.data:
                    device = existing_device.data[0]
                    try:
                        # Parse timestamp with better error handling
                        timestamp_str = device['expires_at']
                        try:
                            device_expires_at = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                        except ValueError:
                            from dateutil import parser
                            device_expires_at = parser.parse(timestamp_str)

                        # Ensure timezone-aware comparison
                        if device_expires_at.tzinfo is None:
                            device_expires_at = device_expires_at.replace(tzinfo=timezone.utc)

                        current_time = datetime.now(timezone.utc)
                        print(f"[MFA Verify] Device expiry: {device_expires_at.isoformat()}, Current time: {current_time.isoformat()}")

                        if device_expires_at > current_time:
                            # Current token is still valid, just extend its expiry
                            print(f"[MFA Verify] Current device token is valid, extending expiry by 30 days")
                            device_token_to_use = current_device_token

                            # Update expiry date
                            update_result = get_supabase_client().table('trusted_devices').update({
                                'expires_at': expires_at.isoformat(),
                                'updated_at': datetime.now(timezone.utc).isoformat()
                            }).eq('user_id', user_id).eq('device_token_hash', current_token_hash).execute()
                            print(f"[MFA Verify] Updated device token expiry: success")
                        else:
                            print(f"[MFA Verify] Current device token expired ({device_expires_at} < {current_time}), generating new one")
                    except Exception as date_error:
                        print(f"[MFA Verify] Error parsing device expiry: {date_error}")
            
            # If no valid existing token, generate a new one
            if device_token_to_use is None:
                print(f"[MFA Verify] Generating new device token")
                device_token_to_use, token_hash = generate_device_token()
                
                try:
                    # Check if user has any existing trusted devices
                    existing = get_supabase_client().table('trusted_devices').select('*') \
                        .eq('user_id', user_id) \
                        .execute()
                    
                    if existing.data:
                        # Update the first existing device record (maintain single device per user for now)
                        get_supabase_client().table('trusted_devices').update({
                            'device_token_hash': token_hash,
                            'expires_at': expires_at.isoformat(),
                            'updated_at': datetime.now(timezone.utc).isoformat()
                        }).eq('user_id', user_id).execute()
                    else:
                        # Insert new device token
                        get_supabase_client().table('trusted_devices').insert({
                            'user_id': user_id,
                            'device_token_hash': token_hash,
                            'expires_at': expires_at.isoformat(),
                            'created_at': datetime.now(timezone.utc).isoformat()
                        }).execute()
                        
                except Exception as e:
                    print(f"[MFA Verify] Failed to store new device token: {e}")
                    # Continue without device trust if storage fails
                    device_token_to_use = None
            
            if device_token_to_use:
                response_data['device_token'] = device_token_to_use
                response_data['device_expires_at'] = expires_at.isoformat()
                print(f"[MFA Verify] Device token provided for user {user_id}")
        
        return JSONResponse(content=response_data)
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"[MFA Verify Login] Exception: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/check-device")
async def check_device_trust(
    request: Request,
    device_token: str = Body(..., embed=True),
    current_user: dict = Depends(get_current_user)
) -> JSONResponse:
    """Check if a device token is trusted"""
    try:
        user_id = current_user['id']
        
        print(f"[Device Trust] Checking device trust for user {user_id}")
        print(f"[Device Trust] Device token: {device_token[:8]}...")
        
        if not device_token:
            print(f"[Device Trust] No device token provided")
            return JSONResponse(content={"trusted": False})
        
        token_hash = hash_token(device_token)
        print(f"[Device Trust] Token hash: {token_hash[:16]}...")
        
        # First check all devices for this user (debugging)
        all_devices = get_supabase_client().table('trusted_devices') \
            .select('*') \
            .eq('user_id', user_id) \
            .execute()
        print(f"[Device Trust] Found {len(all_devices.data)} total devices for user")
        for device in all_devices.data:
            print(f"[Device Trust] Device: hash={device['device_token_hash'][:16]}... expires={device['expires_at']}")
        
        # Check trusted devices
        result = get_supabase_client().table('trusted_devices') \
            .select('*') \
            .eq('user_id', user_id) \
            .eq('device_token_hash', token_hash) \
            .execute()
        
        print(f"[Device Trust] Query result: {len(result.data)} matching devices")
        
        if not result.data:
            print(f"[Device Trust] No matching device found")
            return JSONResponse(content={"trusted": False})
        
        device = result.data[0]
        
        # Handle timestamp parsing with various formats
        timestamp_str = device['expires_at']
        try:
            # Try direct parsing first
            expires_at = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        except ValueError:
            try:
                # Handle microseconds precision issues
                import re
                # Remove extra precision beyond 6 digits for microseconds
                timestamp_str = re.sub(r'\.(\d{6})\d*([+-]\d{2}:\d{2})$', r'.\1\2', timestamp_str)
                expires_at = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            except ValueError:
                # If all else fails, try parsing without microseconds
                from dateutil import parser
                expires_at = parser.parse(timestamp_str)

        # Ensure both datetimes are timezone-aware for proper comparison
        current_time = datetime.now(timezone.utc)
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        print(f"[Device Trust] Expiry check - expires_at: {expires_at.isoformat()}, current_time: {current_time.isoformat()}")
        print(f"[Device Trust] Is expired: {expires_at < current_time}")

        if expires_at < current_time:
            # Token expired
            print(f"[Device Trust] Token expired")
            return JSONResponse(content={"trusted": False, "expired": True})
        
        return JSONResponse(content={"trusted": True})
        
    except Exception as e:
        print(f"[Check Device] Error: {e}")
        return JSONResponse(content={"trusted": False})


@router.post("/disable")
async def disable_mfa(
    request: Request,
    current_user: dict = Depends(get_current_user)
) -> JSONResponse:
    """Disable MFA for user"""
    try:
        user_id = current_user['id']
        
        # Update database
        get_supabase_client().table('user_mfa_settings').update({
            'mfa_enabled': False,
            'phone_verified': False,
            'updated_at': datetime.now(timezone.utc).isoformat()
        }).eq('user_id', user_id).execute()
        
        # Note: We can't delete the factor from Supabase Auth via API
        # The user will need to re-enroll if they want to use MFA again
        
        return JSONResponse(content={
            "success": True,
            "message": "MFA has been disabled"
        })
        
    except Exception as e:
        print(f"[MFA Disable] Exception: {e}")
        raise HTTPException(status_code=500, detail=str(e))
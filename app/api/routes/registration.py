from fastapi import APIRouter, Request, Response, HTTPException, Depends
from pydantic import BaseModel, EmailStr
from typing import Optional, Dict, Any
from app.core.captcha import captcha_service
from app.core.rate_limiter import email_start_limiter, email_hourly_limiter, code_verify_limiter, form_submit_limiter
from app.core.session_manager import form_session_manager
from app.services.registration_service import registration_service
from app.repositories.auth_repository import validate_magic_link_db, consume_magic_link_db
from app.core.clients import get_supabase_client
from app.utils.retry_utils import log_debug


router = APIRouter(prefix="/api/register", tags=["registration"])


class EmailStartRequest(BaseModel):
    email: EmailStr
    captcha_token: Optional[str] = None


class EventCodeRequest(BaseModel):
    code: str
    captcha_token: Optional[str] = None


class RegistrationFormRequest(BaseModel):
    first_name: str
    last_name: str
    preferred_first_name: Optional[str] = None
    email: EmailStr
    cell: Optional[str] = None
    email_opt_in: Optional[bool] = True
    permission_to_text: Optional[bool] = False
    address: Optional[str] = None
    address_2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    date_of_birth: Optional[str] = None
    high_school: Optional[str] = None
    grade_level: Optional[str] = None
    grad_year: Optional[str] = None
    gpa: Optional[float] = None
    gpa_scale: Optional[float] = None
    sat_score: Optional[int] = None
    act_score: Optional[int] = None
    student_type: Optional[str] = None
    entry_term: Optional[str] = None
    entry_year: Optional[int] = None
    major: Optional[str] = None
    academic_interests: Optional[list] = None


class EmailVerificationRequest(BaseModel):
    token: str


class ResendVerificationRequest(BaseModel):
    email: EmailStr


@router.post("/start-email")
async def start_email_registration(
    request: Request,
    body: EmailStartRequest
):
    """Start registration with email (magic link)"""
    try:
        # Rate limiting
        await email_start_limiter.check_and_record(request, "email_start", body.email)
        await email_hourly_limiter.check_and_record(request, "email_start", body.email)
        
        # CAPTCHA verification
        client_ip = request.client.host if request.client else None
        log_debug(f"CAPTCHA token received: {body.captcha_token is not None}, IP: {client_ip}", service="registration_api")
        await captcha_service.verify(body.captcha_token, client_ip, required=False)
        
        # Start registration
        result = await registration_service.start_email_registration(body.email)
        
        log_debug(f"Email registration started for {body.email}", service="registration_api")
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        log_debug(f"Email registration error: {str(e)}", service="registration_api")
        raise HTTPException(status_code=500, detail="Failed to start registration")


@router.post("/verify-event-code")
async def verify_event_code(
    request: Request,
    response: Response,
    body: EventCodeRequest
):
    """Verify event code and create form session"""
    try:
        # Rate limiting
        await code_verify_limiter.check_and_record(request, "code_verify")
        
        # CAPTCHA verification
        client_ip = request.client.host if request.client else None
        await captcha_service.verify(body.captcha_token, client_ip, required=True)
        
        # Verify event code
        code_result = await registration_service.verify_event_code(body.code)
        
        # Create form session
        session_token = await form_session_manager.create_session(
            session_type="event_code",
            event_code_id=code_result["event_code_id"],
            metadata=code_result.get("metadata", {})
        )
        
        # Set session cookie
        form_session_manager.set_session_cookie(response, session_token)
        
        log_debug(f"Event code verified: {body.code}", service="registration_api")
        return {
            "success": True,
            "event": code_result.get("event"),
            "redirect": "/register/form"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        log_debug(f"Event code verification error: {str(e)}", service="registration_api")
        raise HTTPException(status_code=500, detail="Failed to verify event code")


@router.get("/verify-magic-link")
async def verify_magic_link(
    token: str,
    response: Response
):
    """Verify magic link and create form session"""
    try:
        supabase = get_supabase_client()
        
        # Validate magic link
        magic_link = validate_magic_link_db(supabase, token)
        if not magic_link or magic_link["type"] != "registration":
            raise HTTPException(status_code=400, detail="Invalid or expired registration link")
        
        # Create form session
        session_token = await form_session_manager.create_session(
            session_type="magic_link",
            email=magic_link["email"],
            metadata=magic_link.get("metadata", {})
        )
        
        # Consume magic link
        consume_magic_link_db(supabase, token)
        
        # Set session cookie
        form_session_manager.set_session_cookie(response, session_token)
        
        log_debug(f"Magic link verified for {magic_link['email']}", service="registration_api")
        return {
            "success": True,
            "email": magic_link["email"],
            "redirect": "/register/form"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        log_debug(f"Magic link verification error: {str(e)}", service="registration_api")
        raise HTTPException(status_code=500, detail="Failed to verify magic link")


@router.get("/form-session")
async def get_form_session(request: Request):
    """Get current form session data"""
    try:
        log_debug(f"Form session request from {request.client.host if request.client else 'unknown'}", service="registration_api")
        session = await form_session_manager.get_session_from_request(request)
        log_debug(f"Session retrieved: {session is not None}", service="registration_api")
        if not session:
            raise HTTPException(status_code=401, detail="No valid session")
        
        return {
            "session_type": session["session_type"],
            "email": session.get("email"),
            "metadata": session.get("metadata", {})
        }
        
    except HTTPException:
        raise
    except Exception as e:
        log_debug(f"Form session error: {str(e)}", service="registration_api")
        raise HTTPException(status_code=500, detail="Failed to get session")


@router.post("/submit")
async def submit_registration(
    request: Request,
    response: Response,
    body: RegistrationFormRequest
):
    """Submit registration form"""
    try:
        # Require valid session
        session = await form_session_manager.require_session(request)
        
        # Rate limiting
        await form_submit_limiter.check_and_record(request, "form_submit", body.email)
        
        # Submit registration
        result = await registration_service.submit_registration(
            session_data=session,
            form_data=body.dict(exclude_none=True)
        )
        
        # Consume session
        await form_session_manager.consume_session(session["token"])
        
        # Clear session cookie
        form_session_manager.clear_session_cookie(response)
        
        log_debug(f"Registration submitted: {result['student_id']}", service="registration_api")
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        log_debug(f"Registration submission error: {str(e)}", service="registration_api")
        raise HTTPException(status_code=500, detail="Failed to submit registration")


@router.post("/verify-email")
async def verify_email(body: EmailVerificationRequest):
    """Verify email from verification link"""
    try:
        result = await registration_service.verify_email(body.token)
        log_debug("Email verified successfully", service="registration_api")
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        log_debug(f"Email verification error: {str(e)}", service="registration_api")
        raise HTTPException(status_code=500, detail="Failed to verify email")


@router.post("/resend-verification")
async def resend_verification(
    request: Request,
    body: ResendVerificationRequest
):
    """Resend verification email"""
    try:
        # Rate limiting
        await email_hourly_limiter.check_and_record(request, "resend_verification", body.email)
        
        result = await registration_service.resend_verification(body.email)
        log_debug(f"Verification resent for {body.email}", service="registration_api")
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        log_debug(f"Resend verification error: {str(e)}", service="registration_api")
        raise HTTPException(status_code=500, detail="Failed to resend verification")
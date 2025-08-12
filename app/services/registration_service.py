import re
import os
import resend
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from fastapi import HTTPException
from app.core.clients import get_supabase_client
from app.repositories.students_repository import get_student_by_email, upsert_student
from app.repositories.auth_repository import create_magic_link_db, validate_magic_link_db, consume_magic_link_db
from app.utils.retry_utils import log_debug
from app.utils.qr_utils import qr_png_data_uri


class RegistrationService:
    """Service for handling student registration flows"""
    
    # Disposable email domains to block
    DISPOSABLE_DOMAINS = {
        "10minutemail.com", "guerrillamail.com", "mailinator.com",
        "temp-mail.org", "throwaway.email", "yopmail.com",
        "tempmail.com", "trashmail.com", "getnada.com", "sharklasers.com"
    }
    
    def __init__(self):
        self.supabase = get_supabase_client()
        self.frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")
        self.resend_api_key = os.getenv("RESEND_API_KEY")
        if self.resend_api_key:
            resend.api_key = self.resend_api_key
    
    def _validate_email(self, email: str) -> bool:
        """Validate email format and check for disposable domains"""
        if not email:
            return False
        
        # Basic email regex
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, email):
            return False
        
        # Check for disposable domain
        domain = email.lower().split('@')[-1]
        if domain in self.DISPOSABLE_DOMAINS:
            log_debug(f"Blocked disposable email domain: {domain}", service="registration")
            return False
        
        return True
    
    def _validate_name(self, name: str) -> bool:
        """Validate name field"""
        if not name or len(name.strip()) < 1:
            return False
        
        # Check for obvious junk (all numbers, special chars, etc)
        if re.match(r'^[0-9!@#$%^&*()_+=\[\]{};:,.<>?/\\|`~-]+$', name):
            return False
        
        return True
    
    def _validate_phone(self, phone: str) -> bool:
        """Validate phone number"""
        if not phone:
            return True  # Phone is optional
        
        # Remove common formatting
        cleaned = re.sub(r'[\s\-\(\)\+\.]', '', phone)
        
        # Check if it's a valid length (10-15 digits)
        if not cleaned.isdigit() or len(cleaned) < 10 or len(cleaned) > 15:
            return False
        
        return True
    
    async def start_email_registration(self, email: str) -> Dict[str, Any]:
        """Start registration via email/magic link
        
        Returns:
            Success status and message
        """
        # Validate email
        if not self._validate_email(email):
            raise HTTPException(status_code=400, detail="Invalid or disposable email address")
        
        # Create magic link for registration
        token = create_magic_link_db(
            self.supabase,
            email,
            "registration",
            {"purpose": "student_registration"}
        )
        
        # Send magic link email
        if self.resend_api_key:
            await self._send_registration_magic_link(email, token)
        else:
            log_debug(f"Email service not configured, magic link: {self.frontend_url}/register/verify?token={token}", service="registration")
        
        # Log metric
        await self._log_metric(
            funnel_step="email_started",
            source_method="magic_link",
            metadata={"email": email}
        )
        
        return {
            "success": True,
            "message": "Check your email for the registration link"
        }
    
    async def verify_event_code(self, code: str) -> Dict[str, Any]:
        """Verify an event code
        
        Returns:
            Event code data if valid
        """
        if not code or not re.match(r'^\d{6}$', code):
            raise HTTPException(status_code=400, detail="Invalid event code format")
        
        try:
            # Look up event code
            response = self.supabase.table("event_codes").select(
                "*, events(*)"
            ).eq(
                "code", code
            ).eq(
                "active", True
            ).gte(
                "valid_until", datetime.utcnow().isoformat()
            ).lte(
                "valid_from", datetime.utcnow().isoformat()
            ).limit(1).execute()
            
            if not response.data:
                raise HTTPException(status_code=400, detail="Invalid or expired event code")
            
            event_code = response.data[0]
            
            # Check usage limits
            if event_code["max_uses"] and event_code["current_uses"] >= event_code["max_uses"]:
                raise HTTPException(status_code=400, detail="Event code has reached maximum uses")
            
            # Increment usage counter
            self.supabase.table("event_codes").update({
                "current_uses": event_code["current_uses"] + 1
            }).eq("id", event_code["id"]).execute()
            
            # Log metric
            await self._log_metric(
                funnel_step="code_verified",
                source_method="event_code",
                event_code_id=event_code["id"],
                metadata={"code": code}
            )
            
            return {
                "success": True,
                "event_code_id": event_code["id"],
                "event": event_code.get("events"),
                "metadata": event_code.get("metadata", {})
            }
            
        except HTTPException:
            raise
        except Exception as e:
            log_debug(f"Event code verification error: {str(e)}", service="registration")
            raise HTTPException(status_code=500, detail="Failed to verify event code")
    
    async def submit_registration(
        self,
        session_data: Dict[str, Any],
        form_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Submit registration form
        
        Args:
            session_data: Valid form session data
            form_data: Registration form fields
            
        Returns:
            Registration result with student ID
        """
        # Validate required fields
        if not form_data.get("first_name") or not form_data.get("last_name"):
            raise HTTPException(status_code=400, detail="First and last name are required")
        
        if not form_data.get("email"):
            raise HTTPException(status_code=400, detail="Email is required")
        
        # Validate field formats
        if not self._validate_email(form_data["email"]):
            raise HTTPException(status_code=400, detail="Invalid email address")
        
        if not self._validate_name(form_data["first_name"]) or not self._validate_name(form_data["last_name"]):
            raise HTTPException(status_code=400, detail="Invalid name format")
        
        if form_data.get("cell") and not self._validate_phone(form_data["cell"]):
            raise HTTPException(status_code=400, detail="Invalid phone number format")
        
        # Determine verification status based on session type
        verified = session_data["session_type"] == "magic_link"
        source_method = session_data["session_type"]
        
        # For magic link sessions, email should match session email
        if source_method == "magic_link" and session_data.get("email") != form_data["email"]:
            raise HTTPException(status_code=400, detail="Email mismatch with session")
        
        # Prepare student data
        student_data = self._normalize_student_data(form_data)
        student_data["verified"] = verified
        student_data["source_method"] = source_method
        
        # Check for existing student
        existing = get_student_by_email(student_data["email"])
        if existing:
            # Update existing record
            student_data["id"] = existing["id"]
            log_debug(f"Updating existing student: {existing['id']}", service="registration")
        
        # Upsert student
        student = upsert_student(student_data)
        
        # Send verification email if not verified (event code path)
        if not verified:
            await self._send_verification_email(student["email"], student["id"])
        
        # Log metrics
        await self._log_metric(
            funnel_step="registration_completed",
            source_method=source_method,
            student_id=student["id"],
            session_id=session_data["id"],
            event_code_id=session_data.get("event_code_id"),
            metadata={"verified": verified}
        )
        
        return {
            "success": True,
            "student_id": student["id"],
            "verified": verified,
            "message": "Registration successful!" if verified else "Registration successful! Check your email to verify your address."
        }
    
    async def verify_email(self, token: str) -> Dict[str, Any]:
        """Verify email from verification link
        
        Returns:
            Verification result
        """
        # Validate magic link token
        magic_link = validate_magic_link_db(self.supabase, token)
        if not magic_link or magic_link["type"] != "email_verification":
            raise HTTPException(status_code=400, detail="Invalid or expired verification link")
        
        student_id = magic_link["metadata"].get("student_id")
        if not student_id:
            raise HTTPException(status_code=400, detail="Invalid verification link")
        
        # Mark student as verified
        try:
            response = self.supabase.table("students").update({
                "verified": True
            }).eq("id", student_id).execute()
            
            if not response.data:
                raise HTTPException(status_code=404, detail="Student not found")
            
            # Consume the magic link
            consume_magic_link_db(self.supabase, token)
            
            # Log metric
            await self._log_metric(
                funnel_step="email_verified",
                student_id=student_id,
                metadata={"token": token[:8] + "..."}
            )
            
            return {
                "success": True,
                "message": "Email verified successfully!"
            }
            
        except HTTPException:
            raise
        except Exception as e:
            log_debug(f"Email verification error: {str(e)}", service="registration")
            raise HTTPException(status_code=500, detail="Failed to verify email")
    
    async def resend_verification(self, email: str) -> Dict[str, Any]:
        """Resend verification email
        
        Returns:
            Success status
        """
        # Find student
        student = get_student_by_email(email)
        if not student:
            # Don't reveal if email exists
            return {"success": True, "message": "If an account exists, a verification email has been sent"}
        
        if student.get("verified"):
            return {"success": True, "message": "Email is already verified"}
        
        # Send new verification email
        await self._send_verification_email(email, student["id"])
        
        return {"success": True, "message": "Verification email sent"}
    
    def _normalize_student_data(self, form_data: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize form data to match students table schema"""
        # Map frontend field names to database columns
        field_mapping = {
            "mobile": "cell",
            "address1": "address",
            "address2": "address_2",
            "zip": "zip_code",
            "dob": "date_of_birth",
            "start_term": "entry_term",
            "start_year": "entry_year",
            "sms_opt_in": "permission_to_text"
        }
        
        normalized = {}
        extras = {}
        
        # Known database columns
        db_columns = {
            "first_name", "last_name", "preferred_first_name", "email", "cell",
            "email_opt_in", "permission_to_text", "address", "address_2",
            "city", "state", "zip_code", "date_of_birth", "high_school",
            "grade_level", "grad_year", "gpa", "gpa_scale", "sat_score",
            "act_score", "student_type", "entry_term", "entry_year",
            "major", "academic_interests", "intended_majors"
        }
        
        for key, value in form_data.items():
            # Skip empty values
            if value is None or value == "":
                continue
            
            # Map field name if needed
            db_key = field_mapping.get(key, key)
            
            # Place in appropriate location
            if db_key in db_columns:
                normalized[db_key] = value
            else:
                # Unknown fields go to extras
                extras[key] = value
        
        # Add extras if any
        if extras:
            normalized["extras"] = extras
        
        return normalized
    
    async def _send_registration_magic_link(self, email: str, token: str):
        """Send registration magic link email"""
        if not self.resend_api_key:
            return
        
        magic_url = f"{self.frontend_url}/register/verify?token={token}"
        
        try:
            params = {
                "from": "CardCapture <no-reply@cardcapture.io>",
                "to": [email],
                "subject": "Complete your CardCapture registration",
                "html": f"""
                <h2>Complete your registration</h2>
                <p>Click the link below to securely complete your CardCapture registration:</p>
                <p><a href="{magic_url}" style="display: inline-block; padding: 12px 24px; background-color: #3B82F6; color: white; text-decoration: none; border-radius: 6px;">Complete Registration</a></p>
                <p>This link expires in 24 hours.</p>
                <p>If you didn't request this, you can safely ignore this email.</p>
                """
            }
            
            resend.Emails.send(params)
            log_debug(f"Registration magic link sent to {email}", service="registration")
            
        except Exception as e:
            log_debug(f"Failed to send registration email: {str(e)}", service="registration")
            log_debug(f"📧 Manual registration link: {magic_url}", service="registration")
    
    async def _send_verification_email(self, email: str, student_id: str):
        """Send email verification link"""
        if not self.resend_api_key:
            return
        
        # Create verification magic link
        token = create_magic_link_db(
            self.supabase,
            email,
            "email_verification",
            {"student_id": student_id}
        )
        
        verification_url = f"{self.frontend_url}/register/verify-email?token={token}"
        
        try:
            params = {
                "from": "CardCapture <no-reply@cardcapture.io>",
                "to": [email],
                "subject": "Verify your CardCapture email",
                "html": f"""
                <h2>Verify your email</h2>
                <p>Thanks for registering with CardCapture! Please verify your email address:</p>
                <p><a href="{verification_url}" style="display: inline-block; padding: 12px 24px; background-color: #3B82F6; color: white; text-decoration: none; border-radius: 6px;">Verify Email</a></p>
                <p>This link expires in 24 hours.</p>
                """
            }
            
            resend.Emails.send(params)
            log_debug(f"Verification email sent to {email}", service="registration")
            
        except Exception as e:
            log_debug(f"Failed to send verification email: {str(e)}", service="registration")
    
    async def _log_metric(
        self,
        funnel_step: str,
        source_method: Optional[str] = None,
        session_id: Optional[str] = None,
        student_id: Optional[str] = None,
        event_code_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Log registration metrics"""
        try:
            data = {
                "funnel_step": funnel_step,
                "metadata": metadata or {}
            }
            
            if source_method:
                data["source_method"] = source_method
            if session_id:
                data["session_id"] = session_id
            if student_id:
                data["student_id"] = student_id
            if event_code_id:
                data["event_code_id"] = event_code_id
            
            self.supabase.table("registration_metrics").insert(data).execute()
            
        except Exception as e:
            log_debug(f"Failed to log metric: {str(e)}", service="registration")


# Singleton instance
registration_service = RegistrationService()
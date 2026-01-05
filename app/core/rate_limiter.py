from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from fastapi import Request, HTTPException
from app.core.clients import get_supabase_client
from app.utils.retry_utils import log_debug
import hashlib


class RateLimiter:
    """Database-backed rate limiter for registration endpoints"""
    
    def __init__(self, max_attempts: int, window_minutes: int):
        self.max_attempts = max_attempts
        self.window_minutes = window_minutes
        self.supabase = get_supabase_client()
    
    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP from request, handling proxies"""
        # Check for X-Forwarded-For header (common in proxies)
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # Take the first IP in the chain
            return forwarded_for.split(",")[0].strip()
        
        # Check for X-Real-IP header
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip
        
        # Fall back to direct client IP
        if request.client:
            return request.client.host
        
        return "unknown"
    
    def _hash_email(self, email: str) -> str:
        """Hash email for privacy in logs"""
        return hashlib.sha256(email.lower().encode()).hexdigest()[:16]
    
    async def check_ip_limit(self, request: Request, attempt_type: str) -> bool:
        """Check if IP has exceeded rate limit
        
        Returns:
            True if within limits, False if exceeded
        """
        ip_address = self._get_client_ip(request)
        window_start = datetime.utcnow() - timedelta(minutes=self.window_minutes)
        
        try:
            # Count recent attempts from this IP
            response = self.supabase.table("registration_attempts").select(
                "id", count="exact"
            ).eq(
                "ip_address", ip_address
            ).eq(
                "attempt_type", attempt_type
            ).gte(
                "created_at", window_start.isoformat()
            ).execute()
            
            count = response.count or 0
            
            if count >= self.max_attempts:
                log_debug(
                    f"Rate limit exceeded for IP {ip_address}: {count}/{self.max_attempts} in {self.window_minutes}min",
                    service="rate_limiter"
                )
                return False
            
            return True
            
        except Exception as e:
            log_debug(f"Rate limit check error: {str(e)}", service="rate_limiter")
            # Fail open on database errors
            return True
    
    async def check_email_limit(self, email: str, attempt_type: str) -> bool:
        """Check if email has exceeded rate limit
        
        Returns:
            True if within limits, False if exceeded
        """
        window_start = datetime.utcnow() - timedelta(minutes=self.window_minutes)
        email_hash = self._hash_email(email)
        
        try:
            # Count recent attempts for this email
            response = self.supabase.table("registration_attempts").select(
                "id", count="exact"
            ).eq(
                "email", email
            ).eq(
                "attempt_type", attempt_type
            ).gte(
                "created_at", window_start.isoformat()
            ).execute()
            
            count = response.count or 0
            
            if count >= self.max_attempts:
                log_debug(
                    f"Rate limit exceeded for email {email_hash}: {count}/{self.max_attempts} in {self.window_minutes}min",
                    service="rate_limiter"
                )
                return False
            
            return True
            
        except Exception as e:
            log_debug(f"Rate limit check error: {str(e)}", service="rate_limiter")
            # Fail open on database errors
            return True
    
    async def record_attempt(
        self, 
        request: Request, 
        attempt_type: str,
        email: Optional[str] = None,
        success: bool = False,
        error_reason: Optional[str] = None
    ):
        """Record an attempt for rate limiting"""
        ip_address = self._get_client_ip(request)
        
        try:
            data = {
                "ip_address": ip_address,
                "attempt_type": attempt_type,
                "success": success,
                "error_reason": error_reason
            }
            
            if email:
                data["email"] = email
            
            self.supabase.table("registration_attempts").insert(data).execute()
            
            log_debug(
                f"Recorded {attempt_type} attempt from {ip_address} (success={success})",
                service="rate_limiter"
            )
            
        except Exception as e:
            log_debug(f"Failed to record attempt: {str(e)}", service="rate_limiter")
    
    async def check_and_record(
        self,
        request: Request,
        attempt_type: str,
        email: Optional[str] = None
    ):
        """Check rate limits and record attempt if within limits
        
        Raises:
            HTTPException: If rate limit exceeded
        """
        # Check IP limit
        if not await self.check_ip_limit(request, attempt_type):
            await self.record_attempt(
                request, attempt_type, email, 
                success=False, error_reason="ip_rate_limit"
            )
            raise HTTPException(
                status_code=429,
                detail="Too many attempts. Please wait a few minutes and try again."
            )
        
        # Check email limit if email provided
        if email and not await self.check_email_limit(email, attempt_type):
            await self.record_attempt(
                request, attempt_type, email,
                success=False, error_reason="email_rate_limit"
            )
            raise HTTPException(
                status_code=429,
                detail="Too many attempts for this email. Please wait a few minutes and try again."
            )
        
        # Record successful check (attempt will be marked success/fail later)
        await self.record_attempt(request, attempt_type, email, success=True)


# Rate limiter instances for different endpoints
email_start_limiter = RateLimiter(max_attempts=20, window_minutes=1)  # 20 per minute per IP (increased for staging)
email_hourly_limiter = RateLimiter(max_attempts=10, window_minutes=60)  # 10 per hour per email (increased for testing)
code_verify_limiter = RateLimiter(max_attempts=20, window_minutes=1)  # 20 per minute per IP
form_submit_limiter = RateLimiter(max_attempts=5, window_minutes=10)  # 5 per 10 minutes
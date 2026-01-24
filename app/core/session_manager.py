import os
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from fastapi import Request, Response, HTTPException
from app.core.clients import get_supabase_client
from app.utils.retry_utils import log_debug


class FormSessionManager:
    """Manages secure form sessions for registration"""
    
    COOKIE_NAME = "cc_form_session"
    SESSION_TTL_MINUTES = 30  # 30 minutes to complete form
    
    def __init__(self):
        self.supabase = get_supabase_client()
    
    def _generate_token(self) -> str:
        """Generate a secure session token"""
        return secrets.token_urlsafe(32)
    
    async def create_session(
        self,
        session_type: str,
        email: Optional[str] = None,
        event_code_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Create a new form session
        
        Returns:
            Session token
        """
        token = self._generate_token()
        expires_at = datetime.utcnow() + timedelta(minutes=self.SESSION_TTL_MINUTES)
        
        try:
            data = {
                "token": token,
                "session_type": session_type,
                "expires_at": expires_at.isoformat(),
                "metadata": metadata or {}
            }
            
            if email:
                data["email"] = email
            
            if event_code_id:
                data["event_code_id"] = event_code_id
            
            self.supabase.table("form_sessions").insert(data).execute()
            
            log_debug(
                f"Created {session_type} session for {email or 'event_code'}",
                service="session_manager"
            )
            
            return token
            
        except Exception as e:
            log_debug(f"Failed to create session: {str(e)}", service="session_manager")
            raise HTTPException(status_code=500, detail="Failed to create session")
    
    async def validate_session(self, token: str) -> Optional[Dict[str, Any]]:
        """Validate a session token
        
        Returns:
            Session data if valid, None otherwise
        """
        try:
            response = self.supabase.table("form_sessions").select(
                "*"
            ).eq(
                "token", token
            ).eq(
                "consumed", False
            ).gte(
                "expires_at", datetime.utcnow().isoformat()
            ).limit(1).execute()
            
            if not response.data:
                log_debug("Session not found or expired", service="session_manager")
                return None
            
            session = response.data[0]
            log_debug(f"Session validated: {session['session_type']}", service="session_manager")
            
            return session
            
        except Exception as e:
            log_debug(f"Session validation error: {str(e)}", service="session_manager")
            return None
    
    async def consume_session(self, token: str) -> bool:
        """Mark a session as consumed
        
        Returns:
            True if successful, False otherwise
        """
        try:
            response = self.supabase.table("form_sessions").update({
                "consumed": True,
                "consumed_at": datetime.utcnow().isoformat()
            }).eq(
                "token", token
            ).execute()
            
            if response.data:
                log_debug("Session consumed", service="session_manager")
                return True
            
            return False
            
        except Exception as e:
            log_debug(f"Failed to consume session: {str(e)}", service="session_manager")
            return False
    
    def set_session_cookie(self, response: Response, token: str):
        """Set session cookie in response"""
        # Use secure cookies in production/staging (HTTPS), allow HTTP in development
        environment = os.getenv("ENVIRONMENT", "development")
        is_deployed = environment in ("production", "staging")

        response.set_cookie(
            key=self.COOKIE_NAME,
            value=token,
            max_age=self.SESSION_TTL_MINUTES * 60,
            httponly=True,
            secure=is_deployed,  # True in production/staging (HTTPS), False in dev (HTTP)
            samesite="none" if is_deployed else "lax",  # Cross-origin requires "none"
            path="/"
        )
        log_debug(f"Session cookie set (secure={is_deployed}, samesite={'none' if is_deployed else 'lax'})", service="session_manager")
    
    def get_session_from_cookie(self, request: Request) -> Optional[str]:
        """Get session token from cookie"""
        token = request.cookies.get(self.COOKIE_NAME)
        log_debug(f"Cookie lookup: {self.COOKIE_NAME}={token}, all_cookies={dict(request.cookies)}", service="session_manager")
        return token
    
    def clear_session_cookie(self, response: Response):
        """Clear session cookie"""
        environment = os.getenv("ENVIRONMENT", "development")
        is_deployed = environment in ("production", "staging")

        response.delete_cookie(
            key=self.COOKIE_NAME,
            path="/",
            secure=is_deployed,
            samesite="none" if is_deployed else "lax"
        )
        log_debug("Session cookie cleared", service="session_manager")
    
    async def get_session_from_request(self, request: Request) -> Optional[Dict[str, Any]]:
        """Get and validate session from request cookie
        
        Returns:
            Session data if valid, None otherwise
        """
        token = self.get_session_from_cookie(request)
        if not token:
            return None
        
        return await self.validate_session(token)
    
    async def require_session(self, request: Request) -> Dict[str, Any]:
        """Require a valid session, raise exception if not found
        
        Returns:
            Session data
            
        Raises:
            HTTPException: If no valid session
        """
        session = await self.get_session_from_request(request)
        if not session:
            raise HTTPException(
                status_code=401,
                detail="Valid session required. Please start the registration process again."
            )
        
        return session


# Singleton instance
form_session_manager = FormSessionManager()
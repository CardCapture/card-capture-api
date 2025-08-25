from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
import os
import httpx
from fastapi import HTTPException
from app.utils.retry_utils import log_debug


class CaptchaProvider(ABC):
    """Abstract base class for CAPTCHA providers"""
    
    @abstractmethod
    async def verify(self, token: str, remote_ip: Optional[str] = None) -> bool:
        """Verify a CAPTCHA token"""
        pass


class NoopCaptchaProvider(CaptchaProvider):
    """No-op CAPTCHA provider for development"""
    
    async def verify(self, token: str, remote_ip: Optional[str] = None) -> bool:
        log_debug("NoopCaptcha: Auto-approving token", service="captcha")
        return True


class HCaptchaProvider(CaptchaProvider):
    """hCaptcha provider for invisible CAPTCHA"""
    
    def __init__(self):
        self.secret_key = os.getenv("HCAPTCHA_SECRET_KEY")
        self.verify_url = "https://hcaptcha.com/siteverify"
        
    async def verify(self, token: str, remote_ip: Optional[str] = None) -> bool:
        if not self.secret_key:
            log_debug("HCaptcha: No secret key configured, falling back to noop", service="captcha")
            return True
            
        try:
            async with httpx.AsyncClient() as client:
                data = {
                    "secret": self.secret_key,
                    "response": token
                }
                if remote_ip:
                    data["remoteip"] = remote_ip
                    
                response = await client.post(self.verify_url, data=data)
                result = response.json()
                
                success = result.get("success", False)
                if not success:
                    log_debug(f"HCaptcha verification failed: {result.get('error-codes', [])}", service="captcha")
                    
                return success
                
        except Exception as e:
            log_debug(f"HCaptcha verification error: {str(e)}", service="captcha")
            # Fail open in case of network issues
            return True


class RecaptchaV3Provider(CaptchaProvider):
    """Google reCAPTCHA v3 provider for invisible CAPTCHA"""
    
    def __init__(self):
        self.secret_key = os.getenv("RECAPTCHA_SECRET_KEY")
        self.verify_url = "https://www.google.com/recaptcha/api/siteverify"
        self.min_score = float(os.getenv("RECAPTCHA_MIN_SCORE", "0.5"))
        
    async def verify(self, token: str, remote_ip: Optional[str] = None) -> bool:
        if not self.secret_key:
            log_debug("ReCaptcha: No secret key configured, falling back to noop", service="captcha")
            return True
            
        try:
            async with httpx.AsyncClient() as client:
                data = {
                    "secret": self.secret_key,
                    "response": token
                }
                if remote_ip:
                    data["remoteip"] = remote_ip
                    
                response = await client.post(self.verify_url, data=data)
                result = response.json()
                
                success = result.get("success", False)
                score = result.get("score", 0)
                
                if not success:
                    log_debug(f"ReCaptcha verification failed: {result.get('error-codes', [])}", service="captcha")
                    return False
                    
                if score < self.min_score:
                    log_debug(f"ReCaptcha score too low: {score} < {self.min_score}", service="captcha")
                    return False
                    
                return True
                
        except Exception as e:
            log_debug(f"ReCaptcha verification error: {str(e)}", service="captcha")
            # Fail open in case of network issues
            return True


class CaptchaService:
    """Service for managing CAPTCHA verification"""
    
    _instance = None
    _provider = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if self._provider is None:
            self._provider = self._get_provider()
    
    def _get_provider(self) -> CaptchaProvider:
        """Get the configured CAPTCHA provider"""
        provider_type = os.getenv("CAPTCHA_PROVIDER", "noop").lower()
        
        if provider_type == "hcaptcha":
            return HCaptchaProvider()
        elif provider_type == "recaptcha":
            return RecaptchaV3Provider()
        else:
            return NoopCaptchaProvider()
    
    async def verify(self, token: Optional[str], remote_ip: Optional[str] = None, required: bool = True) -> bool:
        """Verify a CAPTCHA token
        
        Args:
            token: The CAPTCHA response token from the client
            remote_ip: The client's IP address
            required: Whether CAPTCHA is required (raises exception if fails)
            
        Returns:
            True if verification passes, False otherwise
            
        Raises:
            HTTPException: If required=True and verification fails
        """
        if not token and required:
            raise HTTPException(status_code=400, detail="CAPTCHA token required")
        
        if not token:
            return True
        
        result = await self._provider.verify(token, remote_ip)
        
        if not result and required:
            raise HTTPException(status_code=400, detail="CAPTCHA verification failed")
        
        return result


# Singleton instance
captcha_service = CaptchaService()
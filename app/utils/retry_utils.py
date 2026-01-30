import time
from typing import Callable, Any
from datetime import datetime, timezone
import json
import os

# Log levels: DEBUG=10, INFO=20, WARNING=30, ERROR=40
LOG_LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40}
LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG").upper()
LOG_LEVEL_NUM = LOG_LEVELS.get(LOG_LEVEL, 10)
DEBUG_ENABLED = LOG_LEVEL == "DEBUG"


def mask_email(email: str) -> str:
    """Mask email for logging (show first 2 chars + domain)."""
    if not email or "@" not in email:
        return "[invalid-email]"
    local, domain = email.split("@", 1)
    if len(local) <= 2:
        masked_local = local[0] + "*" if local else "*"
    else:
        masked_local = local[:2] + "*" * (len(local) - 2)
    return f"{masked_local}@{domain}"


def mask_token(token: str, visible_chars: int = 8) -> str:
    """Mask token for logging (show first N chars)."""
    if not token:
        return "[no-token]"
    if len(token) <= visible_chars:
        return token
    return f"{token[:visible_chars]}..."


def mask_pii(data: Any) -> Any:
    """
    Recursively mask PII in data structures.
    Masks emails, tokens, passwords, phone numbers.
    """
    if isinstance(data, str):
        # Check if it looks like an email
        if "@" in data and "." in data:
            return mask_email(data)
        return data
    elif isinstance(data, dict):
        masked = {}
        for key, value in data.items():
            key_lower = key.lower()
            if any(pii in key_lower for pii in ["password", "secret", "token", "api_key", "apikey"]):
                masked[key] = "[REDACTED]"
            elif any(pii in key_lower for pii in ["email", "phone"]):
                masked[key] = mask_email(str(value)) if "email" in key_lower else "[REDACTED]"
            else:
                masked[key] = mask_pii(value)
        return masked
    elif isinstance(data, list):
        return [mask_pii(item) for item in data]
    return data


def _log(message: str, level: str = "DEBUG", data: Any = None, service: str = "general", verbose: bool = True):
    """
    Internal logging function with level support.

    Args:
        message: The message to log
        level: Log level (DEBUG, INFO, WARNING, ERROR)
        data: Optional data to log (dict, list, or string)
        service: Service name for log file and context
        verbose: Whether to log detailed data
    """
    level_num = LOG_LEVELS.get(level.upper(), 10)

    timestamp = datetime.now(timezone.utc).isoformat()
    log_entry = f"[{timestamp}] [{level}] [{service}] {message}"

    if data is not None:
        if verbose:
            if isinstance(data, (dict, list)):
                log_entry += "\n" + json.dumps(data, indent=2, default=str)
            else:
                log_entry += f" | {str(data)}"
        else:
            # For non-verbose, just log summary
            if isinstance(data, dict):
                log_entry += f" | Keys: {list(data.keys())}"
            elif isinstance(data, list):
                log_entry += f" | List length: {len(data)}"
            else:
                log_entry += f" | {str(data)}"

    # Always write to service-specific log file
    try:
        os.makedirs("logs", exist_ok=True)
        log_file = f"logs/{service}_debug.log"
        with open(log_file, "a") as f:
            f.write(log_entry + "\n")
    except Exception:
        pass  # Don't fail on log write errors

    # Print to stdout based on log level
    if level_num >= LOG_LEVEL_NUM:
        print(log_entry, flush=True)


def log_debug(message: str, data: Any = None, service: str = "general", verbose: bool = True):
    """
    Log a DEBUG level message. Shown only when LOG_LEVEL=DEBUG.

    Args:
        message: The message to log
        data: Optional data to log (dict, list, or string)
        service: Service name for log file and context (e.g., "gemini", "docai")
        verbose: Whether to log detailed data
    """
    _log(message, level="DEBUG", data=data, service=service, verbose=verbose)


def log_info(message: str, data: Any = None, service: str = "general", verbose: bool = True):
    """
    Log an INFO level message. Shown when LOG_LEVEL is DEBUG or INFO.

    Args:
        message: The message to log
        data: Optional data to log
        service: Service name for log file and context
        verbose: Whether to log detailed data
    """
    _log(message, level="INFO", data=data, service=service, verbose=verbose)


def log_warn(message: str, data: Any = None, service: str = "general", verbose: bool = True):
    """
    Log a WARNING level message. Shown unless LOG_LEVEL=ERROR.

    Args:
        message: The message to log
        data: Optional data to log
        service: Service name for log file and context
        verbose: Whether to log detailed data
    """
    _log(message, level="WARNING", data=data, service=service, verbose=verbose)


def log_error(message: str, data: Any = None, service: str = "general", verbose: bool = True):
    """
    Log an ERROR level message. Always shown.

    Args:
        message: The message to log
        data: Optional data to log
        service: Service name for log file and context
        verbose: Whether to log detailed data
    """
    _log(message, level="ERROR", data=data, service=service, verbose=verbose)


def retry_with_exponential_backoff(
    func: Callable,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    operation_name: str = "API call",
    service: str = "general"
) -> Any:
    """
    Generic retry function with exponential backoff for transient failures.
    
    Args:
        func: Function to retry
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay between retries in seconds
        max_delay: Maximum delay between retries in seconds
        operation_name: Name of operation for logging
        service: Service name for logging context
        
    Returns:
        Result of successful function call
        
    Raises:
        Last exception if all retries fail
    """
    last_exception = None
    
    for attempt in range(max_retries + 1):  # +1 for initial attempt
        try:
            if attempt > 0:
                log_debug(f"Retry attempt {attempt} for {operation_name}", service=service)
            
            result = func()
            
            if attempt > 0:
                log_debug(f"✅ {operation_name} succeeded on attempt {attempt + 1}", service=service)
            
            return result
            
        except Exception as e:
            last_exception = e
            
            # Smart retry logic - only retry transient 3rd party errors
            is_retryable = _is_error_retryable(e, operation_name, service)
            
            if not is_retryable:
                log_debug(f"❌ Non-retryable error in {operation_name}: {str(e)}", service=service)
                raise e
            
            if attempt < max_retries:
                # Calculate delay with exponential backoff
                delay = min(base_delay * (2 ** attempt), max_delay)
                log_debug(
                    f"⚠️ {operation_name} failed (attempt {attempt + 1}), retrying in {delay:.1f}s: {str(e)}",
                    service=service
                )
                time.sleep(delay)
            else:
                log_debug(f"❌ {operation_name} failed after {max_retries + 1} attempts: {str(e)}", service=service)
    
    # If we get here, all retries failed
    raise last_exception


def _is_error_retryable(error: Exception, operation_name: str, service: str) -> bool:
    """
    Determine if an error is worth retrying based on its type and message.
    Only retry transient errors from service providers, not client/data errors.
    
    Args:
        error: The exception that occurred
        operation_name: Name of operation for context
        service: Service name for logging context
        
    Returns:
        True if error should be retried, False otherwise
    """
    error_message = str(error).lower()
    error_type = type(error).__name__.lower()
    
    # Non-retryable errors (client-side, data, or permanent issues)
    non_retryable_indicators = [
        # Authentication/Authorization
        'unauthorized', 'forbidden', 'api key', 'authentication', 'permission denied',
        'invalid credentials', 'access denied', '401', '403',
        
        # Bad input/data errors
        'bad request', 'invalid input', 'invalid format', 'malformed', 'corrupted',
        'unsupported format', 'invalid file', 'decode error', 'parsing error',
        'missing required', 'validation error', '400',
        
        # Resource not found (wrong config)
        'not found', 'does not exist', 'invalid processor', 'invalid model',
        'invalid project', '404',
        
        # Configuration errors (wrong URLs, invalid endpoints)
        'invalid url', 'invalid host', 'name resolution', 'no route to host',
        'invalid endpoint',
        
        # File/Path errors
        'file not found', 'no such file', 'permission denied', 'disk full',
        
        # Programming errors (our bugs)
        'attributeerror', 'typeerror', 'valueerror', 'keyerror',
        'indexerror', 'nameerror'
    ]
    
    # Check if this is clearly a non-retryable error
    for indicator in non_retryable_indicators:
        if indicator in error_message or indicator in error_type:
            log_debug(f"🚫 Non-retryable error detected ({indicator}): {error_message}", service=service)
            return False
    
    # Retryable errors (transient service provider issues)
    retryable_indicators = [
        # Network/Connection issues
        'timeout', 'connection refused', 'connection reset', 'network unreachable',
        'connection timeout', 'read timeout', 'dns', 'socket', 'connection error',
        'host unreachable', 'connection aborted', 'connection failed',
        
        # Rate limiting
        'rate limit', 'quota exceeded', 'too many requests', '429',
        
        # Server errors (5xx)
        'internal server error', 'bad gateway', 'service unavailable', 
        'gateway timeout', 'server error', '500', '502', '503', '504',
        
        # Service-specific transient errors
        'service temporarily unavailable', 'temporarily unavailable',
        'server is overloaded', 'try again later', 'deadline exceeded',
        'resource exhausted'
    ]
    
    # Check if this is a retryable error
    for indicator in retryable_indicators:
        if indicator in error_message:
            log_debug(f"🔄 Retryable error detected ({indicator}): {error_message}", service=service)
            return True
    
    # Special handling for specific exception types
    if any(t in error_type for t in ['timeout', 'connection', 'socket', 'http']):
        log_debug(f"🔄 Retryable error type detected: {error_type}", service=service)
        return True
    
    # Default to non-retryable for unknown errors (conservative approach)
    log_debug(f"❓ Unknown error type, defaulting to non-retryable: {error_message}", service=service)
    return False 
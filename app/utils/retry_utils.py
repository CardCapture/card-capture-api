import time
from typing import Callable, Any
from datetime import datetime, timezone
import json
import os

# Log levels: DEBUG=10, INFO=20, WARNING=30, ERROR=40
# Only show console output if LOG_LEVEL is DEBUG (default for development)
LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG").upper()
DEBUG_ENABLED = LOG_LEVEL == "DEBUG"

def log_debug(message: str, data: Any = None, service: str = "general", verbose: bool = True):
    """
    Common logging function for all services.

    Args:
        message: The message to log
        data: Optional data to log (dict, list, or string)
        service: Service name for log file and context (e.g., "gemini", "docai")
        verbose: Whether to log detailed data

    Environment:
        LOG_LEVEL: Set to INFO/WARNING/ERROR in production to suppress console debug output
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    log_entry = f"[{timestamp}] [{service}] {message}"

    if data is not None:
        if verbose:
            if isinstance(data, (dict, list)):
                log_entry += "\n" + json.dumps(data, indent=2)
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

    # Only print to stdout if DEBUG is enabled
    if DEBUG_ENABLED:
        print(log_entry, flush=True)


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
"""
Simple in-memory rate limiter for Google Maps API calls
"""
import time
from collections import defaultdict, deque
from typing import Optional
import hashlib
import json

class RateLimiter:
    def __init__(self, max_requests_per_minute: int = 10, max_requests_per_hour: int = 100):
        self.max_per_minute = max_requests_per_minute
        self.max_per_hour = max_requests_per_hour
        self.requests_per_ip = defaultdict(lambda: {"minute": deque(), "hour": deque()})
        self.cache = {}  # Simple cache for identical requests
        self.cache_ttl = 3600  # 1 hour cache

    def is_allowed(self, identifier: str, request_data: Optional[dict] = None) -> bool:
        """Check if request is allowed based on rate limits"""
        now = time.time()

        # Check cache first
        if request_data:
            cache_key = self._get_cache_key(request_data)
            if cache_key in self.cache:
                cached_time, _ = self.cache[cache_key]
                if now - cached_time < self.cache_ttl:
                    return True  # Cached response available, no API call needed

        # Clean old requests
        minute_ago = now - 60
        hour_ago = now - 3600

        # Get request history for this identifier
        history = self.requests_per_ip[identifier]

        # Remove old requests
        while history["minute"] and history["minute"][0] < minute_ago:
            history["minute"].popleft()
        while history["hour"] and history["hour"][0] < hour_ago:
            history["hour"].popleft()

        # Check limits
        if len(history["minute"]) >= self.max_per_minute:
            return False
        if len(history["hour"]) >= self.max_per_hour:
            return False

        # Record this request
        history["minute"].append(now)
        history["hour"].append(now)

        return True

    def _get_cache_key(self, request_data: dict) -> str:
        """Generate cache key from request data"""
        # Sort keys for consistent hashing
        sorted_data = json.dumps(request_data, sort_keys=True)
        return hashlib.md5(sorted_data.encode()).hexdigest()

    def cache_response(self, request_data: dict, response: Any):
        """Cache a response"""
        if request_data:
            cache_key = self._get_cache_key(request_data)
            self.cache[cache_key] = (time.time(), response)

    def get_cached_response(self, request_data: dict) -> Optional[Any]:
        """Get cached response if available and not expired"""
        if not request_data:
            return None

        cache_key = self._get_cache_key(request_data)
        if cache_key in self.cache:
            cached_time, response = self.cache[cache_key]
            if time.time() - cached_time < self.cache_ttl:
                return response
        return None

    def cleanup_old_cache(self):
        """Remove expired cache entries"""
        now = time.time()
        expired_keys = [
            key for key, (cached_time, _) in self.cache.items()
            if now - cached_time > self.cache_ttl
        ]
        for key in expired_keys:
            del self.cache[key]

# Global rate limiter instance
google_maps_rate_limiter = RateLimiter(
    max_requests_per_minute=20,  # Conservative limit
    max_requests_per_hour=500    # Prevent runaway costs
)
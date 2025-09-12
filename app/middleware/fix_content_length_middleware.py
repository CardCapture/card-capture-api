"""
Middleware to fix Content-Length header issues with large responses
"""
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import StreamingResponse, JSONResponse
import json
from typing import Any

class ContentLengthFixMiddleware(BaseHTTPMiddleware):
    """
    Middleware to fix Content-Length header calculation for large responses
    that are causing 'Too much data for declared Content-Length' errors
    """
    
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        
        # Only process JSON responses that might have Content-Length issues
        if (hasattr(response, 'media_type') and 
            response.media_type == 'application/json' and
            hasattr(response, 'body')):
            
            try:
                # Get the actual body content
                body = response.body
                if body:
                    actual_length = len(body)
                    
                    # Check if Content-Length header exists and matches
                    content_length = response.headers.get('content-length')
                    if content_length and int(content_length) != actual_length:
                        # Fix the Content-Length header
                        response.headers['content-length'] = str(actual_length)
                        
                    # For very large responses (>50KB), use streaming
                    if actual_length > 50000:
                        def generate():
                            yield body
                        
                        return StreamingResponse(
                            generate(),
                            media_type=response.media_type,
                            status_code=response.status_code,
                            headers=dict(response.headers)
                        )
                        
            except Exception as e:
                # Log the error but don't break the response
                print(f"[ContentLengthFixMiddleware] Error processing response: {e}")
                
        return response
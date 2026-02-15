from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import sentry_sdk
import traceback
from app.utils.retry_utils import log_error

def register_exception_handlers(app: FastAPI):
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.detail}
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        log_error(f"Unhandled exception: {exc}", data={"traceback": traceback.format_exc()}, service="error_handler")
        sentry_sdk.capture_exception(exc)
        return JSONResponse(
            status_code=500,
            content={"error": "Internal server error"}
        ) 
import os
import sentry_sdk
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from app.api.routes import cards_router, auth_router, uploads_router, events_router, users_router, schools_router, stripe_router, superadmin_router, sftp_router, demo_router, crm_events_router, students_router, registration_router, qr_router, high_schools_router, majors_router, notifications_router, public_router, account_linking_router
from app.api.routes.mfa import router as mfa_router
from app.api.routes.webhooks import router as webhooks_router
from app.config import ALLOWED_ORIGINS
from app.core.error_handling import register_exception_handlers

sentry_dsn = os.getenv("SENTRY_DSN")
if sentry_dsn:
    sentry_sdk.init(
        dsn=sentry_dsn,
        traces_sample_rate=0.1,
        environment=os.getenv("ENVIRONMENT", "development"),
    )

ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

# F7: Disable API docs in non-development environments
docs_kwargs = {}
if ENVIRONMENT != "development":
    docs_kwargs = {"docs_url": None, "redoc_url": None, "openapi_url": None}

app = FastAPI(title="Card Scanner API", **docs_kwargs)

register_exception_handlers(app)

# F17: Security headers middleware
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if ENVIRONMENT != "development":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
            response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        return response

app.add_middleware(SecurityHeadersMiddleware)

# Add Content-Length fix middleware to prevent protocol errors
from app.middleware.fix_content_length_middleware import ContentLengthFixMiddleware
app.add_middleware(ContentLengthFixMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=3600,
)

app.include_router(cards_router)
app.include_router(auth_router)
app.include_router(uploads_router)
app.include_router(events_router)
app.include_router(users_router)
app.include_router(schools_router)
app.include_router(stripe_router)
app.include_router(superadmin_router)
app.include_router(sftp_router, prefix="/sftp")
app.include_router(demo_router)
app.include_router(crm_events_router)
app.include_router(students_router)
app.include_router(registration_router)
app.include_router(qr_router)
app.include_router(high_schools_router, prefix="/high_schools")
app.include_router(majors_router, prefix="/majors")
app.include_router(mfa_router)
app.include_router(notifications_router)
app.include_router(public_router)
app.include_router(webhooks_router)
app.include_router(account_linking_router)

@app.get("/")
async def root():
    """Root endpoint for health check."""
    return {
        "message": "Card Scanner API is running",
        "status": "healthy",
        "version": "1.0.0"
    }

@app.get("/health")
async def health():
    """Dedicated health check endpoint for container orchestration."""
    return {"status": "healthy", "service": "card-capture-api"}

 
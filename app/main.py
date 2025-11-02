from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import cards_router, auth_router, uploads_router, events_router, users_router, schools_router, stripe_router, superadmin_router, sftp_router, demo_router, crm_events_router, students_router, registration_router, qr_router, high_schools_router, majors_router, notifications_router
from app.api.routes.mfa import router as mfa_router
from app.config import ALLOWED_ORIGINS
from app.core.error_handling import register_exception_handlers

# Trigger build - reverted to working state
app = FastAPI(title="Card Scanner API")

register_exception_handlers(app)

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

@app.get("/")
async def root():
    """Root endpoint for health check."""
    return {
        "message": "Card Scanner API is running",
        "status": "healthy",
        "version": "1.0.0"
    }

 
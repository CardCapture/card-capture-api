# This file marks the routes directory as a Python package. 

from .cards import router as cards_router
from .auth import router as auth_router
from .uploads import router as uploads_router
from .events import router as events_router
from .users_routes import router as users_router
from .schools_routes import router as schools_router
from .stripe_routes import router as stripe_router
from .superadmin import router as superadmin_router
from .sftp import router as sftp_router
from .demo import router as demo_router
from .crm_events import router as crm_events_router
from .students import router as students_router

__all__ = [
    'cards_router',
    'auth_router',
    'uploads_router',
    'events_router',
    'users_router',
    'schools_router',
    'stripe_router',
    'superadmin_router',
    'sftp_router',
    'demo_router',
    'crm_events_router',
    'students_router',
] 
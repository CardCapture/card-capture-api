from app.services.schools_service import get_school_service

async def get_school_controller(school_id, user):
    # Extract user's school_id for tenant isolation
    user_school_id = user.get("school_id") if user else None
    return await get_school_service(school_id, user_school_id) 
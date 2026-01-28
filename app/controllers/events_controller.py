from app.services.events_service import (
    create_event_service,
    update_event_service,
    archive_events_service,
    delete_event_service
)

async def create_event_controller(payload, user):
    return await create_event_service(payload, user)

async def update_event_controller(event_id: str, payload, user):
    return await update_event_service(event_id, payload, user)

async def archive_events_controller(payload):
    return await archive_events_service(payload)

async def delete_event_controller(event_id: str, user):
    return await delete_event_service(event_id, user) 
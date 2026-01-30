from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from app.core.auth import get_current_user
from app.services.notification_service import process_notifications
from app.utils.retry_utils import log_debug
from typing import Optional

router = APIRouter(tags=["Notifications"])


@router.post("/notifications/process-hourly")
async def process_hourly_notifications():
    """
    Process hourly card scan notifications.
    This endpoint is called by the Supabase edge function on a cron schedule.

    No authentication required as this is called by the edge function.
    """
    try:
        # Process notifications for all schools
        summary = process_notifications()

        return JSONResponse(status_code=200, content={
            "message": "Notifications processed successfully",
            "summary": summary
        })

    except Exception as e:
        log_debug(f"Error processing hourly notifications: {e}", service="notifications")
        return JSONResponse(status_code=500, content={
            "error": "Failed to process notifications",
            "details": str(e)
        })


@router.post("/notifications/test")
async def test_notification(user=Depends(get_current_user)):
    """
    Test endpoint to send a test notification email.
    Only sends if the user's school has notifications enabled.
    """
    try:
        from app.services.notification_service import NotificationService

        user_school_id = user.get("school_id") if user else None
        if not user_school_id:
            return JSONResponse(status_code=403, content={
                "error": "User must be associated with a school"
            })

        service = NotificationService()

        # Check if notifications are enabled for this school
        if not service.should_send_notification(user_school_id):
            return JSONResponse(status_code=400, content={
                "error": "Notifications are not enabled for your school or no email is configured"
            })

        # Get school info
        school_response = service.supabase.table("schools").select(
            "id, name, notification_email"
        ).eq("id", user_school_id).single().execute()

        if not school_response.data:
            return JSONResponse(status_code=404, content={"error": "School not found"})

        school = school_response.data

        # Create a test event summary
        test_events = [{
            "event_id": "test-event-123",
            "event_name": "Test Event (Sample)",
            "card_count": 5
        }]

        # Send test email
        success = service.send_card_scan_digest(
            email=school["notification_email"],
            school_name=school["name"],
            events_summary=test_events
        )

        if success:
            return JSONResponse(status_code=200, content={
                "message": f"Test notification sent successfully to {school['notification_email']}"
            })
        else:
            return JSONResponse(status_code=500, content={
                "error": "Failed to send test notification"
            })

    except Exception as e:
        log_debug(f"Error sending test notification: {e}", service="notifications")
        return JSONResponse(status_code=500, content={
            "error": "Failed to send test notification",
            "details": str(e)
        })

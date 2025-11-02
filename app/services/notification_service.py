import os
import resend
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from app.core.clients import get_supabase_client
from app.utils.retry_utils import log_debug


class NotificationService:
    """Service for handling email notifications"""

    def __init__(self):
        self.supabase = get_supabase_client()
        self.frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")
        self.resend_api_key = os.getenv("RESEND_API_KEY")
        if self.resend_api_key:
            resend.api_key = self.resend_api_key

    def get_schools_with_notifications_enabled(self) -> List[Dict[str, Any]]:
        """Get all schools that have notifications enabled with valid email"""
        try:
            response = self.supabase.table("schools").select(
                "id, name, notification_email, notifications_enabled"
            ).eq("notifications_enabled", True).not_.is_("notification_email", "null").execute()

            return response.data or []
        except Exception as e:
            log_debug(f"Error fetching schools with notifications: {str(e)}", service="notifications")
            return []

    def get_card_scan_summary(
        self,
        school_id: str,
        since: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """
        Get summary of card scans by event for a school since a given time.
        Returns list of events with new card counts.
        """
        if since is None:
            # Default to last hour
            since = datetime.utcnow() - timedelta(hours=1)

        try:
            # Query cards created since the given time for this school
            response = self.supabase.table("reviewed_data").select(
                "id, event_id, events(id, name)"
            ).eq("school_id", school_id).gte(
                "created_at", since.isoformat()
            ).not_.is_("event_id", "null").execute()

            cards = response.data or []

            if not cards:
                return []

            # Group by event and count
            event_summary = {}
            for card in cards:
                event = card.get("events")
                if event:
                    event_id = event["id"]
                    event_name = event["name"]

                    if event_id not in event_summary:
                        event_summary[event_id] = {
                            "event_id": event_id,
                            "event_name": event_name,
                            "card_count": 0
                        }
                    event_summary[event_id]["card_count"] += 1

            # Convert to list and sort by card count (descending)
            summary_list = list(event_summary.values())
            summary_list.sort(key=lambda x: x["card_count"], reverse=True)

            return summary_list

        except Exception as e:
            log_debug(f"Error getting card scan summary: {str(e)}", service="notifications")
            return []

    def send_card_scan_digest(
        self,
        email: str,
        school_name: str,
        events_summary: List[Dict[str, Any]]
    ) -> bool:
        """
        Send digest email with summary of new card scans.

        Args:
            email: Recipient email address
            school_name: Name of the school
            events_summary: List of dicts with event_id, event_name, card_count

        Returns:
            True if email sent successfully, False otherwise
        """
        if not self.resend_api_key:
            log_debug("Resend API key not configured, skipping email", service="notifications")
            return False

        if not events_summary:
            log_debug("No events to notify about, skipping email", service="notifications")
            return False

        try:
            # Load and populate the email template
            html_content = self._load_notification_email_template(
                school_name=school_name,
                events_summary=events_summary
            )

            # Calculate total cards
            total_cards = sum(event["card_count"] for event in events_summary)
            event_count = len(events_summary)

            # Create subject line
            subject = f"New Cards to Review - {school_name}"
            if event_count == 1:
                subject = f"New Cards to Review: {events_summary[0]['event_name']}"

            params = {
                "from": "CardCapture <no-reply@cardcapture.io>",
                "to": [email],
                "subject": subject,
                "html": html_content
            }

            response = resend.Emails.send(params)
            log_debug(
                f"Card scan notification sent to {email}. "
                f"{total_cards} cards from {event_count} event(s). "
                f"Response ID: {response.get('id', 'unknown')}",
                service="notifications"
            )

            return True

        except Exception as e:
            log_debug(f"Failed to send notification email: {str(e)}", service="notifications")
            log_debug(f"Error type: {type(e).__name__}", service="notifications")
            return False

    def _load_notification_email_template(
        self,
        school_name: str,
        events_summary: List[Dict[str, Any]]
    ) -> str:
        """Load and populate the notification email template"""
        template_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "card_scan_notification_template.html"
        )

        try:
            with open(template_path, 'r') as f:
                template = f.read()

            # Calculate totals
            total_cards = sum(event["card_count"] for event in events_summary)
            event_count = len(events_summary)

            # Build events HTML list
            events_html = self._build_events_html(events_summary)

            # Replace template variables
            logo_url = "https://assets.cardcapture.io/storage/v1/object/public/assets/cc-logo-transparent-min.png"
            html_content = template.replace("{{SCHOOL_NAME}}", school_name)
            html_content = html_content.replace("{{TOTAL_CARDS}}", str(total_cards))
            html_content = html_content.replace("{{EVENT_COUNT}}", str(event_count))
            html_content = html_content.replace("{{EVENTS_LIST}}", events_html)
            html_content = html_content.replace("{{CURRENT_YEAR}}", str(datetime.now().year))
            html_content = html_content.replace("{{FRONTEND_URL}}", self.frontend_url)
            html_content = html_content.replace("{{LOGO_URL}}", logo_url)

            return html_content

        except FileNotFoundError:
            # Fallback to simple HTML if template not found
            log_debug("Template file not found, using fallback HTML", service="notifications")
            return self._build_fallback_email(school_name, events_summary)
        except Exception as e:
            log_debug(f"Error loading email template: {str(e)}", service="notifications")
            return self._build_fallback_email(school_name, events_summary)

    def _build_events_html(self, events_summary: List[Dict[str, Any]]) -> str:
        """Build HTML list of events for email"""
        html_parts = []

        for event in events_summary:
            event_name = event["event_name"]
            event_id = event["event_id"]
            card_count = event["card_count"]
            card_text = "card" if card_count == 1 else "cards"

            # Build review link - goes directly to event page
            review_url = f"{self.frontend_url}/events/{event_id}"

            html_parts.append(f"""
            <tr>
                <td style="padding: 12px; border-bottom: 1px solid #e5e7eb;">
                    <strong style="color: #1f2937;">{event_name}</strong>
                </td>
                <td style="padding: 12px; border-bottom: 1px solid #e5e7eb; text-align: center;">
                    <span style="color: #4f46e5; font-weight: 600;">{card_count} {card_text}</span>
                </td>
                <td style="padding: 12px; border-bottom: 1px solid #e5e7eb; text-align: right;">
                    <a href="{review_url}"
                       style="color: #4f46e5; text-decoration: none; font-weight: 500;">
                        Review →
                    </a>
                </td>
            </tr>
            """)

        return "".join(html_parts)

    def _build_fallback_email(
        self,
        school_name: str,
        events_summary: List[Dict[str, Any]]
    ) -> str:
        """Build a simple fallback email if template is not available"""
        total_cards = sum(event["card_count"] for event in events_summary)
        event_count = len(events_summary)

        events_list = []
        for event in events_summary:
            event_name = event["event_name"]
            event_id = event["event_id"]
            card_count = event["card_count"]
            review_url = f"{self.frontend_url}/events/{event_id}"
            card_text = "card" if card_count == 1 else "cards"

            events_list.append(
                f'<li><strong>{event_name}</strong>: {card_count} {card_text} '
                f'<a href="{review_url}">Review</a></li>'
            )

        events_html = "".join(events_list)
        event_text = "event" if event_count == 1 else "events"
        logo_url = "https://assets.cardcapture.io/storage/v1/object/public/assets/cc-logo-transparent-min.png"

        return f"""
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="text-align: center; margin-bottom: 20px;">
                <img src="{logo_url}" alt="CardCapture" style="max-width: 180px; height: auto;">
            </div>
            <h2>New Cards to Review</h2>
            <p>Hello {school_name},</p>
            <p>You have <strong>{total_cards} new cards</strong> to review from {event_count} {event_text}:</p>
            <ul>{events_html}</ul>
            <p>
                <a href="{self.frontend_url}"
                   style="background-color: #3b82f6; color: white; padding: 10px 20px;
                          text-decoration: none; border-radius: 5px; display: inline-block;">
                    Go to CardCapture
                </a>
            </p>
            <p style="color: #6b7280; font-size: 12px; margin-top: 30px;">
                To manage notification settings, visit your Account Settings page.
            </p>
        </body>
        </html>
        """

    def should_send_notification(self, school_id: str) -> bool:
        """
        Check if a school should receive notifications.
        Validates that notifications are enabled and email is configured.
        """
        try:
            response = self.supabase.table("schools").select(
                "notifications_enabled, notification_email"
            ).eq("id", school_id).single().execute()

            school = response.data
            if not school:
                return False

            return (
                school.get("notifications_enabled") == True and
                school.get("notification_email") is not None and
                school.get("notification_email").strip() != ""
            )

        except Exception as e:
            log_debug(f"Error checking notification settings: {str(e)}", service="notifications")
            return False

    def process_hourly_notifications(self) -> Dict[str, Any]:
        """
        Main function to process hourly notifications for all schools.
        This should be called by the edge function on a cron schedule.

        Returns summary of notifications sent.
        """
        log_debug("Starting hourly notification processing", service="notifications")

        schools = self.get_schools_with_notifications_enabled()

        summary = {
            "schools_checked": len(schools),
            "emails_sent": 0,
            "errors": 0,
            "timestamp": datetime.utcnow().isoformat()
        }

        for school in schools:
            school_id = school["id"]
            school_name = school["name"]
            notification_email = school["notification_email"]

            log_debug(f"Processing notifications for school: {school_name}", service="notifications")

            # Get card scan summary for last hour
            events_summary = self.get_card_scan_summary(school_id)

            if events_summary:
                # Send notification email
                success = self.send_card_scan_digest(
                    email=notification_email,
                    school_name=school_name,
                    events_summary=events_summary
                )

                if success:
                    summary["emails_sent"] += 1
                else:
                    summary["errors"] += 1
            else:
                log_debug(f"No new cards for {school_name}, skipping notification", service="notifications")

        log_debug(
            f"Hourly notification processing complete. "
            f"Checked {summary['schools_checked']} schools, "
            f"sent {summary['emails_sent']} emails, "
            f"{summary['errors']} errors",
            service="notifications"
        )

        return summary


# Convenience function for edge function
def process_notifications():
    """Convenience function to be called from edge function"""
    service = NotificationService()
    return service.process_hourly_notifications()

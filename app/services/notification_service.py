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


    # =====================================================
    # Account Linking Notifications
    # =====================================================

    def get_school_admins(self, school_id: str) -> List[Dict[str, Any]]:
        """Get all admin users for a school."""
        try:
            response = (
                self.supabase.table("profiles")
                .select("id, email, first_name, last_name")
                .eq("school_id", school_id)
                .contains("role", ["admin"])
                .execute()
            )
            return response.data or []
        except Exception as e:
            log_debug(f"Error fetching school admins: {str(e)}", service="notifications")
            return []

    def send_link_request_to_admins(
        self,
        school_id: str,
        school_name: str,
        recruiter_name: str,
        recruiter_email: str,
        event_name: str,
        event_date: str,
        amount_paid: int,
        request_id: str
    ) -> Dict[str, Any]:
        """
        Send notification email to all school admins about a new link request.
        Returns summary of emails sent.
        """
        if not self.resend_api_key:
            log_debug("Resend API key not configured, skipping admin notification", service="notifications")
            return {"success": False, "reason": "email_not_configured"}

        admins = self.get_school_admins(school_id)
        if not admins:
            log_debug(f"No admins found for school {school_id}", service="notifications")
            return {"success": False, "reason": "no_admins_found"}

        # Build the approval URL
        approval_url = f"{self.frontend_url}/settings/user-management?merge_request={request_id}"

        # Format amount
        amount_display = f"${amount_paid / 100:.2f}"

        sent_count = 0
        errors = []

        for admin in admins:
            admin_email = admin.get("email")
            admin_name = admin.get("first_name", "Admin")

            if not admin_email:
                continue

            try:
                html_content = self._build_link_request_email(
                    admin_name=admin_name,
                    school_name=school_name,
                    recruiter_name=recruiter_name,
                    recruiter_email=recruiter_email,
                    event_name=event_name,
                    event_date=event_date,
                    amount_paid=amount_display,
                    approval_url=approval_url
                )

                params = {
                    "from": "CardCapture <no-reply@cardcapture.io>",
                    "to": [admin_email],
                    "subject": f"New Recruiter Signup: {recruiter_name} for {event_name}",
                    "html": html_content
                }

                response = resend.Emails.send(params)
                log_debug(
                    f"Link request notification sent to {admin_email}. Response ID: {response.get('id', 'unknown')}",
                    service="notifications"
                )
                sent_count += 1

            except Exception as e:
                log_debug(f"Failed to send link request email to {admin_email}: {str(e)}", service="notifications")
                errors.append({"email": admin_email, "error": str(e)})

        return {
            "success": sent_count > 0,
            "sent_count": sent_count,
            "total_admins": len(admins),
            "errors": errors
        }

    def send_link_approval_email(
        self,
        recruiter_email: str,
        recruiter_name: str,
        school_name: str,
        event_name: str
    ) -> bool:
        """Send confirmation email to recruiter when their link request is approved."""
        if not self.resend_api_key:
            log_debug("Resend API key not configured, skipping approval email", service="notifications")
            return False

        try:
            html_content = self._build_approval_email(
                recruiter_name=recruiter_name,
                school_name=school_name,
                event_name=event_name
            )

            params = {
                "from": "CardCapture <no-reply@cardcapture.io>",
                "to": [recruiter_email],
                "subject": f"Your account has been linked to {school_name}",
                "html": html_content
            }

            response = resend.Emails.send(params)
            log_debug(
                f"Link approval email sent to {recruiter_email}. Response ID: {response.get('id', 'unknown')}",
                service="notifications"
            )
            return True

        except Exception as e:
            log_debug(f"Failed to send approval email: {str(e)}", service="notifications")
            return False

    def send_link_rejection_email(
        self,
        recruiter_email: str,
        recruiter_name: str,
        school_name: str
    ) -> bool:
        """Send notification email to recruiter when their link request is rejected."""
        if not self.resend_api_key:
            log_debug("Resend API key not configured, skipping rejection email", service="notifications")
            return False

        try:
            html_content = self._build_rejection_email(
                recruiter_name=recruiter_name,
                school_name=school_name
            )

            params = {
                "from": "CardCapture <no-reply@cardcapture.io>",
                "to": [recruiter_email],
                "subject": f"Account link update for {school_name}",
                "html": html_content
            }

            response = resend.Emails.send(params)
            log_debug(
                f"Link rejection email sent to {recruiter_email}. Response ID: {response.get('id', 'unknown')}",
                service="notifications"
            )
            return True

        except Exception as e:
            log_debug(f"Failed to send rejection email: {str(e)}", service="notifications")
            return False

    def _build_link_request_email(
        self,
        admin_name: str,
        school_name: str,
        recruiter_name: str,
        recruiter_email: str,
        event_name: str,
        event_date: str,
        amount_paid: str,
        approval_url: str
    ) -> str:
        """Build HTML email for admin link request notification."""
        logo_url = "https://assets.cardcapture.io/storage/v1/object/public/assets/cc-logo-transparent-min.png"
        current_year = datetime.now().year

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #f9fafb;">
            <div style="background-color: white; border-radius: 8px; padding: 32px; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
                <div style="text-align: center; margin-bottom: 24px;">
                    <img src="{logo_url}" alt="CardCapture" style="max-width: 180px; height: auto;">
                </div>

                <h2 style="color: #1f2937; margin-bottom: 16px;">New Recruiter Signup</h2>

                <p style="color: #4b5563; line-height: 1.6;">Hi {admin_name},</p>

                <p style="color: #4b5563; line-height: 1.6;">
                    A new recruiter has signed up for CardCapture and selected <strong>{school_name}</strong>:
                </p>

                <div style="background-color: #f3f4f6; border-radius: 8px; padding: 20px; margin: 24px 0;">
                    <table style="width: 100%; border-collapse: collapse;">
                        <tr>
                            <td style="color: #6b7280; padding: 8px 0;">Recruiter:</td>
                            <td style="color: #1f2937; font-weight: 600; padding: 8px 0;">{recruiter_name}</td>
                        </tr>
                        <tr>
                            <td style="color: #6b7280; padding: 8px 0;">Email:</td>
                            <td style="color: #1f2937; padding: 8px 0;">{recruiter_email}</td>
                        </tr>
                        <tr>
                            <td style="color: #6b7280; padding: 8px 0;">Event:</td>
                            <td style="color: #1f2937; font-weight: 600; padding: 8px 0;">{event_name}</td>
                        </tr>
                        <tr>
                            <td style="color: #6b7280; padding: 8px 0;">Date:</td>
                            <td style="color: #1f2937; padding: 8px 0;">{event_date}</td>
                        </tr>
                        <tr>
                            <td style="color: #6b7280; padding: 8px 0;">Amount Paid:</td>
                            <td style="color: #059669; font-weight: 600; padding: 8px 0;">{amount_paid}</td>
                        </tr>
                    </table>
                </div>

                <p style="color: #4b5563; line-height: 1.6;">
                    They can start scanning cards immediately. If you'd like to link their account to your main school account, click the button below:
                </p>

                <div style="text-align: center; margin: 32px 0;">
                    <a href="{approval_url}"
                       style="background-color: #2563eb; color: white; padding: 14px 28px; text-decoration: none; border-radius: 8px; font-weight: 600; display: inline-block;">
                        Review &amp; Link Account
                    </a>
                </div>

                <p style="color: #6b7280; font-size: 14px; line-height: 1.6;">
                    If you don't recognize this person, no action is needed. They can continue using CardCapture independently, and their scanned cards from this event will still be accessible.
                </p>

                <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 32px 0;">

                <p style="color: #9ca3af; font-size: 12px; text-align: center;">
                    Questions? Reply to this email or contact support@cardcapture.io<br>
                    &copy; {current_year} CardCapture. All rights reserved.
                </p>
            </div>
        </body>
        </html>
        """

    def _build_approval_email(
        self,
        recruiter_name: str,
        school_name: str,
        event_name: str
    ) -> str:
        """Build HTML email for link approval confirmation."""
        logo_url = "https://assets.cardcapture.io/storage/v1/object/public/assets/cc-logo-transparent-min.png"
        current_year = datetime.now().year

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #f9fafb;">
            <div style="background-color: white; border-radius: 8px; padding: 32px; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
                <div style="text-align: center; margin-bottom: 24px;">
                    <img src="{logo_url}" alt="CardCapture" style="max-width: 180px; height: auto;">
                </div>

                <div style="text-align: center; margin-bottom: 24px;">
                    <table role="presentation" cellpadding="0" cellspacing="0" style="margin: 0 auto;">
                        <tr>
                            <td style="width: 64px; height: 64px; background-color: #d1fae5; border-radius: 50%; text-align: center; vertical-align: middle;">
                                <span style="color: #059669; font-size: 32px; line-height: 64px;">&#10003;</span>
                            </td>
                        </tr>
                    </table>
                </div>

                <h2 style="color: #1f2937; margin-bottom: 16px; text-align: center;">Account Linked!</h2>

                <p style="color: #4b5563; line-height: 1.6;">Hi {recruiter_name},</p>

                <p style="color: #4b5563; line-height: 1.6;">
                    Great news! <strong>{school_name}</strong> has approved your account link request.
                </p>

                <p style="color: #4b5563; line-height: 1.6;">
                    Your account is now connected to {school_name}'s main CardCapture account. This means:
                </p>

                <ul style="color: #4b5563; line-height: 1.8; padding-left: 20px;">
                    <li>Your event (<strong>{event_name}</strong>) is now visible in the school's dashboard</li>
                    <li>Your scanned cards can be processed by the school's team</li>
                    <li>You have access to school resources and settings</li>
                </ul>

                <div style="text-align: center; margin: 32px 0;">
                    <a href="{self.frontend_url}"
                       style="background-color: #2563eb; color: white; padding: 14px 28px; text-decoration: none; border-radius: 8px; font-weight: 600; display: inline-block;">
                        Go to Dashboard
                    </a>
                </div>

                <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 32px 0;">

                <p style="color: #9ca3af; font-size: 12px; text-align: center;">
                    Questions? Contact your school admin or reply to this email.<br>
                    &copy; {current_year} CardCapture. All rights reserved.
                </p>
            </div>
        </body>
        </html>
        """

    def _build_rejection_email(
        self,
        recruiter_name: str,
        school_name: str
    ) -> str:
        """Build HTML email for link rejection notification."""
        logo_url = "https://assets.cardcapture.io/storage/v1/object/public/assets/cc-logo-transparent-min.png"
        current_year = datetime.now().year

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #f9fafb;">
            <div style="background-color: white; border-radius: 8px; padding: 32px; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
                <div style="text-align: center; margin-bottom: 24px;">
                    <img src="{logo_url}" alt="CardCapture" style="max-width: 180px; height: auto;">
                </div>

                <h2 style="color: #1f2937; margin-bottom: 16px;">Account Link Update</h2>

                <p style="color: #4b5563; line-height: 1.6;">Hi {recruiter_name},</p>

                <p style="color: #4b5563; line-height: 1.6;">
                    <strong>{school_name}</strong> has reviewed your account link request and chosen not to link your account at this time.
                </p>

                <div style="background-color: #fef3c7; border-radius: 8px; padding: 16px; margin: 24px 0;">
                    <p style="color: #92400e; margin: 0; font-size: 14px;">
                        <strong>What this means:</strong>
                    </p>
                    <ul style="color: #92400e; font-size: 14px; margin: 8px 0 0 0; padding-left: 20px; line-height: 1.6;">
                        <li>You can continue using CardCapture independently</li>
                        <li>Your scanned cards are still accessible in your dashboard</li>
                        <li>Your event access remains active</li>
                    </ul>
                </div>

                <p style="color: #4b5563; line-height: 1.6;">
                    If you believe this was a mistake, please contact the school directly or reach out to our support team.
                </p>

                <div style="text-align: center; margin: 32px 0;">
                    <a href="{self.frontend_url}"
                       style="background-color: #2563eb; color: white; padding: 14px 28px; text-decoration: none; border-radius: 8px; font-weight: 600; display: inline-block;">
                        Go to Dashboard
                    </a>
                </div>

                <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 32px 0;">

                <p style="color: #9ca3af; font-size: 12px; text-align: center;">
                    Questions? Contact support@cardcapture.io<br>
                    &copy; {current_year} CardCapture. All rights reserved.
                </p>
            </div>
        </body>
        </html>
        """


    # =====================================================
    # Post-Purchase Emails (Welcome, Receipt, Invite)
    # =====================================================

    def send_purchase_receipt_email(
        self,
        recipient_email: str,
        recipient_name: str,
        events: List[Dict[str, Any]],
        total_amount: int,
        checkout_session_id: str,
        purchase_date: str,
        is_new_user: bool = True
    ) -> bool:
        """
        Send receipt email after successful purchase.
        For new users, includes welcome message. For existing users, just the receipt.

        Args:
            recipient_email: User's email
            recipient_name: User's name
            events: List of purchased events with name, date
            total_amount: Total amount in cents
            checkout_session_id: Stripe session ID (serves as receipt number)
            purchase_date: ISO date string of purchase
            is_new_user: If True, shows welcome message; if False, just receipt
        """
        if not self.resend_api_key:
            log_debug("Resend API key not configured, skipping receipt email", service="notifications")
            return False

        try:
            html_content = self._build_receipt_email(
                recipient_name=recipient_name,
                events=events,
                total_amount=total_amount,
                checkout_session_id=checkout_session_id,
                purchase_date=purchase_date,
                is_new_user=is_new_user
            )

            # Different subject lines for new vs existing users
            if is_new_user:
                subject = "Welcome to CardCapture - Your Purchase Receipt"
            else:
                subject = "CardCapture - Your Purchase Receipt"

            params = {
                "from": "CardCapture <no-reply@cardcapture.io>",
                "to": [recipient_email],
                "subject": subject,
                "html": html_content
            }

            response = resend.Emails.send(params)
            log_debug(
                f"Purchase receipt email sent to {recipient_email}. Response ID: {response.get('id', 'unknown')}",
                service="notifications"
            )
            return True

        except Exception as e:
            log_debug(f"Failed to send receipt email: {str(e)}", service="notifications")
            return False

    def send_invite_admins_email(
        self,
        recipient_email: str,
        recipient_name: str,
        school_name: str
    ) -> bool:
        """
        Send email to new school creator encouraging them to invite their admins.
        Only sent when user creates a new school (not standalone).
        """
        if not self.resend_api_key:
            log_debug("Resend API key not configured, skipping invite admins email", service="notifications")
            return False

        try:
            html_content = self._build_invite_admins_email(
                recipient_name=recipient_name,
                school_name=school_name
            )

            params = {
                "from": "CardCapture <no-reply@cardcapture.io>",
                "to": [recipient_email],
                "subject": f"Invite your team to {school_name} on CardCapture",
                "html": html_content
            }

            response = resend.Emails.send(params)
            log_debug(
                f"Invite admins email sent to {recipient_email}. Response ID: {response.get('id', 'unknown')}",
                service="notifications"
            )
            return True

        except Exception as e:
            log_debug(f"Failed to send invite admins email: {str(e)}", service="notifications")
            return False

    def _build_receipt_email(
        self,
        recipient_name: str,
        events: List[Dict[str, Any]],
        total_amount: int,
        checkout_session_id: str,
        purchase_date: str,
        is_new_user: bool = True
    ) -> str:
        """Build HTML receipt email with itemized events."""
        logo_url = "https://assets.cardcapture.io/storage/v1/object/public/assets/cc-logo-transparent-min.png"
        current_year = datetime.now().year

        # Format amount
        total_display = f"${total_amount / 100:.2f}"
        per_event_display = "$25.00"

        # Format date
        try:
            from datetime import datetime as dt
            parsed_date = dt.fromisoformat(purchase_date.replace('Z', '+00:00'))
            formatted_date = parsed_date.strftime("%B %d, %Y")
        except:
            formatted_date = purchase_date

        # Receipt number (use last 8 chars of session ID)
        receipt_number = f"CC-{checkout_session_id[-8:].upper()}"

        # Build line items HTML
        line_items_html = ""
        for event in events:
            event_name = event.get("name", "Event")
            event_date = event.get("event_date", event.get("date", "TBD"))
            line_items_html += f"""
            <tr>
                <td style="padding: 12px 0; border-bottom: 1px solid #e5e7eb;">
                    <strong style="color: #1f2937;">{event_name}</strong>
                    <br><span style="color: #6b7280; font-size: 13px;">{event_date}</span>
                </td>
                <td style="padding: 12px 0; border-bottom: 1px solid #e5e7eb; text-align: right; color: #1f2937;">
                    {per_event_display}
                </td>
            </tr>
            """

        # Different content for new users vs existing users
        if is_new_user:
            title_html = '<h2 style="color: #1f2937; margin-bottom: 8px; text-align: center;">Welcome to CardCapture!</h2>'
            subtitle_html = '<p style="color: #6b7280; text-align: center; margin-bottom: 24px;">Your purchase was successful</p>'
            intro_html = f"""
                <p style="color: #4b5563; line-height: 1.6;">Hi {recipient_name.split()[0] if recipient_name else 'there'},</p>
                <p style="color: #4b5563; line-height: 1.6;">
                    Thank you for signing up for CardCapture! Your event has been created and you're ready to start scanning inquiry cards.
                </p>
            """
        else:
            title_html = '<h2 style="color: #1f2937; margin-bottom: 8px; text-align: center;">Purchase Receipt</h2>'
            subtitle_html = '<p style="color: #6b7280; text-align: center; margin-bottom: 24px;">Your purchase was successful</p>'
            event_word = "event has" if len(events) == 1 else "events have"
            intro_html = f"""
                <p style="color: #4b5563; line-height: 1.6;">Hi {recipient_name.split()[0] if recipient_name else 'there'},</p>
                <p style="color: #4b5563; line-height: 1.6;">
                    Thank you for your purchase! Your {event_word} been added to your account and you're ready to start scanning inquiry cards.
                </p>
            """

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #f9fafb;">
            <div style="background-color: white; border-radius: 8px; padding: 32px; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
                <div style="text-align: center; margin-bottom: 8px;">
                    <img src="{logo_url}" alt="CardCapture" style="max-width: 180px; height: auto;">
                </div>

                {title_html}
                {subtitle_html}

                {intro_html}

                <!-- Receipt Box -->
                <div style="background-color: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px; padding: 24px; margin: 24px 0;">
                    <div style="display: flex; justify-content: space-between; margin-bottom: 16px;">
                        <div>
                            <p style="color: #6b7280; font-size: 12px; margin: 0; text-transform: uppercase; letter-spacing: 0.5px;">Receipt</p>
                            <p style="color: #1f2937; font-weight: 600; margin: 4px 0 0 0;">{receipt_number}</p>
                        </div>
                        <div style="text-align: right;">
                            <p style="color: #6b7280; font-size: 12px; margin: 0; text-transform: uppercase; letter-spacing: 0.5px;">Date</p>
                            <p style="color: #1f2937; font-weight: 600; margin: 4px 0 0 0;">{formatted_date}</p>
                        </div>
                    </div>

                    <table style="width: 100%; border-collapse: collapse; margin-top: 16px;">
                        <thead>
                            <tr>
                                <th style="text-align: left; padding: 8px 0; border-bottom: 2px solid #e5e7eb; color: #6b7280; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px;">Event</th>
                                <th style="text-align: right; padding: 8px 0; border-bottom: 2px solid #e5e7eb; color: #6b7280; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px;">Amount</th>
                            </tr>
                        </thead>
                        <tbody>
                            {line_items_html}
                        </tbody>
                        <tfoot>
                            <tr>
                                <td style="padding: 16px 0 0 0; font-weight: 700; color: #1f2937; font-size: 16px;">Total</td>
                                <td style="padding: 16px 0 0 0; font-weight: 700; color: #1f2937; font-size: 16px; text-align: right;">{total_display}</td>
                            </tr>
                        </tfoot>
                    </table>
                </div>

                <div style="text-align: center; margin: 32px 0;">
                    <a href="{self.frontend_url}"
                       style="background-color: #3b82f6; color: white; padding: 14px 28px; text-decoration: none; border-radius: 8px; font-weight: 600; display: inline-block;">
                        Go to Dashboard
                    </a>
                </div>

                <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 32px 0;">

                <p style="color: #9ca3af; font-size: 12px; text-align: center;">
                    Questions? Reply to this email or contact support@cardcapture.io<br>
                    &copy; {current_year} CardCapture. All rights reserved.
                </p>
            </div>
        </body>
        </html>
        """

    def _build_invite_admins_email(
        self,
        recipient_name: str,
        school_name: str
    ) -> str:
        """Build HTML email encouraging user to invite admins to their school."""
        logo_url = "https://assets.cardcapture.io/storage/v1/object/public/assets/cc-logo-transparent-min.png"
        current_year = datetime.now().year
        invite_url = f"{self.frontend_url}/settings/user-management"

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #f9fafb;">
            <div style="background-color: white; border-radius: 8px; padding: 32px; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
                <div style="text-align: center; margin-bottom: 8px;">
                    <img src="{logo_url}" alt="CardCapture" style="max-width: 180px; height: auto;">
                </div>

                <h2 style="color: #1f2937; margin-bottom: 16px; text-align: center;">Invite Your Team</h2>

                <p style="color: #4b5563; line-height: 1.6;">Hi {recipient_name.split()[0] if recipient_name else 'there'},</p>

                <p style="color: #4b5563; line-height: 1.6;">
                    Congratulations on setting up <strong>{school_name}</strong> on CardCapture! As the account administrator, you can invite other team members to help manage your recruiting events.
                </p>

                <div style="background-color: #f0f9ff; border-radius: 8px; padding: 20px; margin: 24px 0; border-left: 4px solid #2563eb;">
                    <h3 style="color: #1e40af; margin: 0 0 12px 0; font-size: 15px;">Why invite your team?</h3>
                    <ul style="color: #1e40af; margin: 0; padding-left: 20px; line-height: 1.8;">
                        <li>Multiple people can scan cards at events</li>
                        <li>Share access to student data and exports</li>
                        <li>Manage events together</li>
                        <li>Delegate admin responsibilities</li>
                    </ul>
                </div>

                <p style="color: #4b5563; line-height: 1.6;">
                    You can add <strong>Admins</strong> (full access) or <strong>Recruiters</strong> (limited to scanning and viewing) to your account.
                </p>

                <div style="text-align: center; margin: 32px 0;">
                    <a href="{invite_url}"
                       style="background-color: #3b82f6; color: white; padding: 14px 28px; text-decoration: none; border-radius: 8px; font-weight: 600; display: inline-block;">
                        Invite Team Members
                    </a>
                </div>

                <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 32px 0;">

                <p style="color: #9ca3af; font-size: 12px; text-align: center;">
                    Questions? Reply to this email or contact support@cardcapture.io<br>
                    &copy; {current_year} CardCapture. All rights reserved.
                </p>
            </div>
        </body>
        </html>
        """


# Convenience function for edge function
def process_notifications():
    """Convenience function to be called from edge function"""
    service = NotificationService()
    return service.process_hourly_notifications()

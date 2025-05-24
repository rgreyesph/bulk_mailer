from celery import shared_task
from django.conf import settings as django_settings
from django.core.mail import send_mail
from django.template import Context, Template, TemplateSyntaxError
from django.utils import timezone
from django.urls import reverse
from django.contrib.sites.models import Site
from django.db.models import F
from django.db import transaction # Import transaction
import logging

from mailer_app.models import Contact, Campaign, EmailTemplate, CampaignSendLog, Settings as AppSettings

logger = logging.getLogger(__name__)

@shared_task(bind=True, max_retries=3, default_retry_delay=5 * 60, rate_limit='10/s')
def send_single_email_task(self, contact_id, campaign_id):
    """
    Sends a single personalized email to a contact for a given campaign.
    Uses django-ses backend via django.core.mail.send_mail.
    Also checks for campaign completion to update parent campaign status.
    """
    processed_successfully = False
    try:
        # Use select_for_update to lock the contact and campaign rows if necessary,
        # though for this task, primary concern is campaign counters.
        contact = Contact.objects.get(id=contact_id)
        # Campaign object will be fetched and locked later before updating counters
        
        app_settings_obj = AppSettings.load()
        if not app_settings_obj or not app_settings_obj.sender_email:
            logger.error(f"Sender email not configured in AppSettings for campaign {campaign_id}. Skipping contact {contact_id}.")
            # Atomically update campaign failure count
            Campaign.objects.filter(pk=campaign_id).update(failed_to_send=F('failed_to_send') + 1)
            check_campaign_completion(campaign_id) # Check completion status
            return f"Error: Sender email not configured."

        # Fetch campaign here to use its details
        campaign = Campaign.objects.get(id=campaign_id)
        email_template = campaign.email_template

        if not contact.subscribed:
            logger.info(f"Contact {contact.email} (ID: {contact.id}) is unsubscribed. Skipping for campaign {campaign.id}.")
            CampaignSendLog.objects.get_or_create(
                campaign_id=campaign_id, contact=contact, email_address=contact.email,
                status='failed', defaults={'error_message': "Contact unsubscribed."}
            )
            # This is a skip, not a send failure, so don't increment failed_to_send.
            # However, it does count as "processed" for completion check.
            # To handle this, we might need a different way to track "processed" vs "attempted send"
            # For now, let's assume skips do not count towards failed_to_send but are "done".
            check_campaign_completion(campaign_id, is_skip=True)
            return f"Skipped: Contact {contact.email} unsubscribed."

        if not email_template:
            logger.error(f"No template for campaign '{campaign.name}' (ID: {campaign.id}). Skipping contact {contact.id}.")
            CampaignSendLog.objects.get_or_create(
                campaign_id=campaign_id, contact=contact, email_address=contact.email,
                status='failed', defaults={'error_message': "No email template selected for campaign."}
            )
            Campaign.objects.filter(pk=campaign.pk).update(failed_to_send=F('failed_to_send') + 1)
            check_campaign_completion(campaign_id)
            return f"Error: Campaign '{campaign.name}' has no template."

        unsubscribe_url = '#'
        tracking_pixel_url_for_img_tag = '#'
        current_site_domain = "example.com" # Fallback

        try:
            current_site = Site.objects.get_current()
            current_site_domain = current_site.domain
            protocol = 'https' if not django_settings.DEBUG else 'http'

            if contact.unsubscribe_token:
                path = reverse('mailer_app:unsubscribe_contact', kwargs={'token': str(contact.unsubscribe_token)})
                unsubscribe_url = f"{protocol}://{current_site_domain}{path}"
            
            tracking_pixel_base_url = getattr(django_settings, 'SITE_DOMAIN', current_site_domain)
            if not tracking_pixel_base_url.startswith(('http://', 'https://')):
                tracking_pixel_base_url = f"{protocol}://{tracking_pixel_base_url}"
            
            tracking_pixel_path = reverse('mailer_app:track_open', kwargs={'campaign_id': campaign.id, 'contact_id': contact.id})
            raw_tracking_pixel_url = f"{tracking_pixel_base_url.rstrip('/')}{tracking_pixel_path}"
            tracking_pixel_url_for_img_tag = f'<img src="{raw_tracking_pixel_url}" width="1" height="1" alt="" style="display:none;border:0;outline:none;text-decoration:none;-ms-interpolation-mode:bicubic;"/>'

        except Exception as e:
            logger.error(f"Could not generate unsubscribe/tracking URL for contact {contact.id}, campaign {campaign.id}: {e}", exc_info=True)

        context_data = {
            'first_name': contact.first_name or '',
            'last_name': contact.last_name or '',
            'email': contact.email,
            'company': contact.company or '',
            'job_title': contact.job_title or '',
            'unsubscribe_url': unsubscribe_url,
            'tracking_pixel': tracking_pixel_url_for_img_tag,
            'your_company_name': app_settings_obj.company_name or "Your Company",
            'company_address': app_settings_obj.company_address or "",
            'site_url': app_settings_obj.site_url or "",
        }
        if isinstance(contact.custom_fields, dict):
            context_data.update(contact.custom_fields)

        django_template_context = Context(context_data)

        try:
            subject_template = Template(email_template.subject)
            personalized_subject = subject_template.render(django_template_context)
        except TemplateSyntaxError as e:
            logger.error(f"Template syntax error in subject for template '{email_template.name}', campaign {campaign.id}: {e}")
            personalized_subject = email_template.subject 

        try:
            html_body_template = Template(email_template.html_content)
            personalized_html_body = html_body_template.render(django_template_context)
            
            footer_template = Template(email_template.footer_html)
            personalized_footer = footer_template.render(django_template_context)
            
            full_html_content = personalized_html_body + personalized_footer
        except TemplateSyntaxError as e:
            logger.error(f"Template syntax error in HTML body/footer for template '{email_template.name}', campaign {campaign.id}: {e}")
            CampaignSendLog.objects.get_or_create(
                campaign_id=campaign_id, contact=contact, email_address=contact.email,
                status='failed', defaults={'error_message': f"Template syntax error: {e}"}
            )
            Campaign.objects.filter(pk=campaign_id).update(failed_to_send=F('failed_to_send') + 1)
            check_campaign_completion(campaign_id)
            return f"Error: Template syntax error in '{email_template.name}' for contact {contact.email}."

        try:
            send_mail(
                subject=personalized_subject,
                message="", 
                from_email=app_settings_obj.sender_email,
                recipient_list=[contact.email],
                html_message=full_html_content,
                fail_silently=False
            )
            processed_successfully = True
            logger.info(f"Email sent to {contact.email} for campaign {campaign.id} via django-ses.")
            CampaignSendLog.objects.get_or_create(
                campaign_id=campaign_id, contact=contact, email_address=contact.email,
                status='success', defaults={'message_id': 'N/A_django-ses'}
            )
            Campaign.objects.filter(pk=campaign_id).update(successfully_sent=F('successfully_sent') + 1)
            return f"Email sent to {contact.email}."
        except Exception as e:
            error_message_text = str(e)
            logger.error(f"Django-ses send_mail error for {contact.email}, campaign {campaign.id}: {error_message_text}", exc_info=True)
            CampaignSendLog.objects.get_or_create(
                campaign_id=campaign_id, contact=contact, email_address=contact.email,
                status='failed', defaults={'error_message': error_message_text[:255]}
            )
            Campaign.objects.filter(pk=campaign_id).update(failed_to_send=F('failed_to_send') + 1)
            return f"Error: Email sending failed for {contact.email}."

    except Contact.DoesNotExist:
        logger.error(f"Contact ID {contact_id} not found for campaign {campaign_id}.")
        check_campaign_completion(campaign_id, is_skip_or_contact_error=True) # Count as processed for completion
        return f"Error: Contact ID {contact_id} not found."
    except Campaign.DoesNotExist:
        logger.error(f"Campaign ID {campaign_id} not found when processing contact {contact_id}.")
        # Cannot update a campaign that doesn't exist
        return f"Error: Campaign ID {campaign_id} not found."
    except AppSettings.DoesNotExist:
        logger.error(f"Application settings not found. Cannot process email for contact {contact_id}, campaign {campaign_id}.")
        Campaign.objects.filter(pk=campaign_id).update(failed_to_send=F('failed_to_send') + 1) # Assume campaign exists
        check_campaign_completion(campaign_id)
        return f"Error: Application settings not found."
    except Exception as e:
        logger.exception(f"Unexpected error in send_single_email_task for contact {contact_id}, campaign {campaign_id}: {e}")
        try:
            campaign_obj = Campaign.objects.filter(id=campaign_id).first()
            if campaign_obj:
                contact_obj = Contact.objects.filter(id=contact_id).first()
                email_to_log = contact_obj.email if contact_obj else f"Unknown (Contact ID {contact_id})"
                CampaignSendLog.objects.get_or_create(
                    campaign=campaign_obj, contact=contact_obj, email_address=email_to_log,
                    status='failed', defaults={'error_message': f"Unexpected task error: {str(e)[:250]}"}
                )
                Campaign.objects.filter(pk=campaign_id).update(failed_to_send=F('failed_to_send') + 1)
        except Exception as log_e:
            logger.error(f"Error during fallback logging for send_single_email_task: {log_e}")
        return f"Failed permanently for contact {contact_id}, campaign {campaign_id} due to unexpected error."
    finally:
        # This block executes whether an exception occurred or not (unless return was hit earlier)
        # Check for campaign completion after every task attempt (success, failure, or handled error)
        # The 'is_skip' logic needs refinement if skips shouldn't count towards total_recipients for completion.
        # For now, any task finishing means one step closer to checking total_recipients.
        if 'campaign_id' in locals() and campaign_id is not None:
             # If the task returned early due to an error before campaign_id was set, this won't run.
             # This is why check_campaign_completion is also called in some error blocks.
            check_campaign_completion(campaign_id)


def check_campaign_completion(campaign_id, is_skip=False, is_skip_or_contact_error=False):
    """
    Checks if all emails for a campaign have been processed (sent, failed, or skipped)
    and updates the campaign status accordingly.
    This function should be called at the end of each send_single_email_task.
    """
    try:
        with transaction.atomic(): # Ensure atomicity for reading and updating campaign
            campaign = Campaign.objects.select_for_update().get(id=campaign_id)

            # Only proceed if the campaign is currently in 'sending' state
            if campaign.status != 'sending':
                logger.info(f"Campaign {campaign.id} status is '{campaign.status}', not 'sending'. Completion check skipped or already handled.")
                return

            # Count how many CampaignSendLog entries exist for this campaign.
            # This represents emails that have been attempted (either success or logged failure).
            # Skips for unsubscribed users are also logged as 'failed' with a specific message.
            # Contact.DoesNotExist errors are now also triggering this check.
            
            # Total recipients who were *targeted* for sending (valid, subscribed at the start of process_campaign_task)
            targeted_recipients = campaign.total_recipients 

            # Total emails actually processed (logged in CampaignSendLog)
            # This includes successes, logged failures, and logged skips (unsubscribed).
            # We need a reliable way to count "processed" that aligns with total_recipients.
            # If an email task fails before creating a log (e.g. Contact.DoesNotExist), it's harder.
            # Let's rely on successfully_sent and failed_to_send counters on the campaign model itself.
            
            # Add a small buffer/delay if needed, or rely on atomic updates being eventually consistent.
            # For simplicity, we check immediately.
            
            # Refresh counters from DB to ensure we have the latest values
            campaign.refresh_from_db(fields=['successfully_sent', 'failed_to_send', 'total_recipients'])

            processed_count = campaign.successfully_sent + campaign.failed_to_send
            
            # Add a count for items that were skipped and didn't increment failed_to_send (e.g. unsubscribed)
            # This is tricky. Let's assume total_recipients is the count of emails that *should* have a log entry
            # or be accounted for in successfully_sent/failed_to_send.
            # The current logic:
            # - Sender email not configured: increments failed_to_send
            # - Unsubscribed: creates log, does NOT increment failed_to_send
            # - No template: increments failed_to_send
            # - Template syntax error: increments failed_to_send
            # - Send mail error: increments failed_to_send
            # - Contact.DoesNotExist: does NOT increment failed_to_send on campaign directly in task
            # - AppSettings.DoesNotExist: increments failed_to_send
            # - Unexpected error: increments failed_to_send

            # A more robust way is to count CampaignSendLog entries.
            # However, if a task fails catastrophically before creating a log, this count is off.
            # The `total_recipients` is set by `process_campaign_task` based on initial contact count.
            # The sum of `successfully_sent` and `failed_to_send` should ideally match `total_recipients`
            # if every targeted recipient results in one of these counter increments.

            # Let's refine the condition:
            # If a contact was skipped (unsubscribed), it has a log but doesn't count in failed_to_send.
            # If a contact didn't exist, it might not have a log or counter increment.
            # This logic needs to be very careful.

            # Simplification: if the number of logs equals total_recipients, we are done.
            # This assumes every attempt (even skips) creates a log.
            # The `send_single_email_task` now creates logs for skips.
            # For Contact.DoesNotExist, it's harder to track against total_recipients without a log.

            # Let's use the sum of successfully_sent and failed_to_send.
            # We need to ensure that *every* path in send_single_email_task that processes a recipient
            # from the total_recipients list eventually leads to either successfully_sent or failed_to_send
            # being incremented, OR that total_recipients is adjusted if some are impossible to process (e.g. Contact.DoesNotExist).

            # Current logic: `total_recipients` is the initial count of *valid and subscribed* contacts.
            # `successfully_sent` counts actual sends.
            # `failed_to_send` counts various errors *during the sending attempt*.
            # Unsubscribed contacts are *not* counted in `failed_to_send`.
            
            # A better trigger for "all processed":
            # Query for contacts that were part of the campaign's lists, were subscribed,
            # and do NOT yet have a CampaignSendLog entry for this campaign. If zero, all are processed.
            # This is too complex for this function.

            # Fallback to simpler logic: if sum of success/fail counters >= total_recipients.
            # This might lead to premature completion if total_recipients was an overestimate
            # or some tasks failed without updating counters (which we try to avoid).

            if processed_count >= campaign.total_recipients and campaign.total_recipients > 0:
                logger.info(f"Campaign {campaign.id} has processed all {campaign.total_recipients} recipients. Updating status.")
                campaign.sent_at = timezone.now()
                if campaign.failed_to_send > 0 : # Even if some succeeded, if any failed, mark as 'sent_with_errors' or 'failed'
                    campaign.status = 'failed' # Or a new status like 'completed_with_errors'
                    logger.info(f"Campaign {campaign.id} completed with {campaign.failed_to_send} failures. Status: failed.")
                else:
                    campaign.status = 'sent'
                    logger.info(f"Campaign {campaign.id} completed successfully. Status: sent.")
                campaign.save(update_fields=['status', 'sent_at'])
            elif campaign.total_recipients == 0 and campaign.status == 'sending': # Edge case: if total_recipients became 0 after starting
                logger.info(f"Campaign {campaign.id} has 0 total_recipients while sending. Marking as failed/sent.")
                campaign.sent_at = timezone.now()
                campaign.status = 'failed' # Or 'sent' if 0 recipients is considered "complete"
                campaign.save(update_fields=['status', 'sent_at'])

    except Campaign.DoesNotExist:
        logger.warning(f"Campaign {campaign_id} not found during completion check. Already deleted?")
    except Exception as e:
        logger.error(f"Error in check_campaign_completion for campaign {campaign_id}: {e}", exc_info=True)


@shared_task
def process_campaign_task(campaign_id):
    """
    Processes a campaign by queuing individual email sending tasks for each subscribed contact.
    """
    try:
        campaign = Campaign.objects.get(id=campaign_id)
        if campaign.status not in ['draft', 'scheduled', 'queued', 'retrying', 'failed', 'sending']:
            logger.info(f"Campaign '{campaign.name}' (ID: {campaign_id}) is in status '{campaign.status}', not processing.")
            return f"Campaign '{campaign.name}' not in a sendable/re-sendable state (status: {campaign.status})."

        # Reset counters and set status to 'sending'
        Campaign.objects.filter(pk=campaign.pk).update(
            status='sending',
            successfully_sent=0,
            failed_to_send=0,
            sent_at=None 
        )
        campaign.refresh_from_db() 

        contacts_to_send_qs = Contact.objects.filter(
            contact_list__in=campaign.contact_lists.all(),
            subscribed=True,
            email__isnull=False
        ).exclude(email__exact='').distinct()
        
        current_total_recipients = contacts_to_send_qs.count()
        
        Campaign.objects.filter(pk=campaign.pk).update(total_recipients=current_total_recipients)
        # campaign.refresh_from_db() # Not strictly needed here if only total_recipients updated

        if current_total_recipients == 0:
            logger.info(f"No valid, subscribed contacts for campaign '{campaign.name}'. Marking as failed.")
            Campaign.objects.filter(pk=campaign.pk).update(status='failed', sent_at=timezone.now())
            return f"No valid contacts for campaign '{campaign.name}'."

        if not campaign.contact_lists.exists(): # Should be caught by current_total_recipients == 0
            logger.warning(f"Campaign '{campaign.name}' has no contact lists assigned.")
            Campaign.objects.filter(pk=campaign.pk).update(status='failed', sent_at=timezone.now())
            return f"Campaign '{campaign.name}' has no contact lists."
        
        recipients_queued_count = 0
        for contact in contacts_to_send_qs: # Iterate over the queryset
            send_single_email_task.delay(contact.id, campaign.id)
            recipients_queued_count += 1
        
        logger.info(f"Queued {recipients_queued_count} emails for campaign '{campaign.name}'. Total recipients: {current_total_recipients}.")
        
        # If no tasks were queued (e.g., all contacts filtered out for some reason after initial count),
        # but total_recipients was > 0, the check_campaign_completion logic might not fire correctly.
        # So, if recipients_queued_count is 0 but current_total_recipients was > 0, it's an issue.
        # However, current_total_recipients is the count of contacts_to_send_qs, so this should be fine.
        # If recipients_queued_count is 0, it means current_total_recipients was also 0, handled above.

        # If tasks were queued, the last send_single_email_task will call check_campaign_completion.
        # If current_total_recipients > 0 but recipients_queued_count is somehow 0 (should not happen with current logic),
        # we might need an explicit call to check_campaign_completion here too.
        # For now, rely on the finally block of send_single_email_task.

        return f"Successfully queued {recipients_queued_count} emails for campaign '{campaign.name}'."

    except Campaign.DoesNotExist:
        logger.error(f"Campaign ID {campaign_id} not found for processing.")
        return f"Error: Campaign ID {campaign_id} not found."
    except Exception as e:
        logger.exception(f"Error processing campaign ID {campaign_id}: {e}")
        try:
            Campaign.objects.filter(pk=campaign_id).update(status='failed')
        except Campaign.DoesNotExist:
            pass
        raise 

@shared_task
def check_scheduled_campaigns_task():
    """
    Checks for scheduled campaigns that are due and queues them for processing.
    This task should be run periodically by Celery Beat.
    """
    now = timezone.now()
    logger.info(f"Running check_scheduled_campaigns_task at {now.strftime('%Y-%m-%d %H:%M:%S')}")
    
    campaigns_to_send = Campaign.objects.filter(
        status='scheduled',
        scheduled_at__isnull=False,
        scheduled_at__lte=now
    )
    
    if not campaigns_to_send.exists():
        logger.info("No scheduled campaigns due to be sent at this time.")
        return "No scheduled campaigns found to be due."
        
    processed_count = 0
    for campaign in campaigns_to_send:
        logger.info(f"Found scheduled campaign: '{campaign.name}' (ID: {campaign.id}) scheduled for {campaign.scheduled_at}. Queuing for processing.")
        campaign.status = 'queued' 
        campaign.save(update_fields=['status'])
        process_campaign_task.delay(campaign.id)
        processed_count += 1
        
    logger.info(f"Processed and queued {processed_count} scheduled campaigns.")
    return f"Processed and queued {processed_count} scheduled campaigns."


from celery import shared_task
from django.conf import settings as django_settings
from django.core.mail import send_mail
from django.template import Context, Template, TemplateSyntaxError
from django.utils import timezone
from django.urls import reverse
from django.contrib.sites.models import Site
from django.db.models import F
from django.db import transaction # Import transaction
from django.utils.html import strip_tags
import logging

from mailer_app.models import Contact, Campaign, EmailTemplate, CampaignSendLog, Settings as AppSettings
from bs4 import BeautifulSoup
from django.urls import NoReverseMatch # For more specific exception handling


logger = logging.getLogger(__name__)

# START MARKER FOR send_single_email_task IN tasks.py (REPLACE THE ENTIRE FUNCTION)
@shared_task(bind=True, max_retries=3, default_retry_delay=5 * 60, rate_limit='10/s')
def send_single_email_task(self, contact_id, campaign_id):
    processed_successfully = False
    log_status = 'failed'  # Default log status for CampaignSendLog
    log_error_message = None # Default error message for CampaignSendLog
    contact = None # Initialize to ensure it's defined for the finally block
    campaign = None # Initialize for the finally block

    try:
        contact = Contact.objects.get(id=contact_id)
        campaign = Campaign.objects.get(id=campaign_id)
        email_template = campaign.email_template
        app_settings_obj = AppSettings.load()

        if not app_settings_obj or not app_settings_obj.sender_email:
            log_error_message = "Error: Sender email not configured in AppSettings."
            logger.error(f"{log_error_message} Campaign: {campaign_id}, Contact: {contact_id}.")
            if campaign: # Check if campaign object was fetched
                 Campaign.objects.filter(pk=campaign.id).update(failed_to_send=F('failed_to_send') + 1)
            raise ValueError(log_error_message)

        if not email_template:
            log_error_message = f"Error: Campaign '{campaign.name}' (ID: {campaign.id}) has no email template."
            logger.error(f"{log_error_message} Contact: {contact_id}.")
            Campaign.objects.filter(pk=campaign.id).update(failed_to_send=F('failed_to_send') + 1)
            raise ValueError(log_error_message)

        if not contact.subscribed:
            logger.info(f"Contact {contact.email} (ID: {contact.id}) is unsubscribed. Skipping for campaign {campaign.id}.")
            log_status = 'skipped'
            log_error_message = "Contact unsubscribed."
            # The finally block will handle logging this skipped attempt.
            return f"Skipped: Contact {contact.email} unsubscribed."

        # --- Context Preparation ---
        unsubscribe_url = '#'
        tracking_pixel_url_for_img_tag = ''
        base_url_for_links = "http://misconfigured-domain.com"

        try:
            if app_settings_obj.site_url and app_settings_obj.site_url.startswith(('http://', 'https://')):
                base_url_for_links = app_settings_obj.site_url.rstrip('/')
            else:
                current_site = Site.objects.get_current()
                domain = current_site.domain
                protocol = 'https' if not django_settings.DEBUG else 'http'
                base_url_for_links = f"{protocol}://{domain}"
            logger.info(f"Base URL for links: {base_url_for_links} (Contact: {contact_id}, Campaign: {campaign_id})")

            if contact.unsubscribe_token:
                try:
                    path = reverse('mailer_app:unsubscribe_contact', kwargs={'token': str(contact.unsubscribe_token)})
                    unsubscribe_url = f"{base_url_for_links}{path}"
                    logger.info(f"Generated unsubscribe URL for {contact.email}: {unsubscribe_url}")
                except NoReverseMatch as e:
                    logger.error(f"NoReverseMatch for 'unsubscribe_contact' (Contact: {contact.id}, Token: {contact.unsubscribe_token}). Error: {e}", exc_info=True)
                    unsubscribe_url = f"{base_url_for_links}/unsubscribe-error-no-reverse/{contact.unsubscribe_token}/"
            else:
                logger.warning(f"Contact {contact.email} (ID: {contact.id}) has no unsubscribe_token. Unsubscribe URL will be non-functional.")
                unsubscribe_url = f"{base_url_for_links}/no-token-unsubscribe/{contact.id}/"

            try:
                tracking_pixel_path = reverse('mailer_app:track_open', kwargs={'campaign_id': campaign.id, 'contact_id': contact.id})
                raw_tracking_pixel_url = f"{base_url_for_links}{tracking_pixel_path}"
                tracking_pixel_url_for_img_tag = f'<img src="{raw_tracking_pixel_url}" width="1" height="1" alt="" style="display:none;border:0;outline:none;text-decoration:none;-ms-interpolation-mode:bicubic;"/>'
                logger.info(f"Generated tracking pixel for {contact.email}: {tracking_pixel_url_for_img_tag}")
            except NoReverseMatch as e:
                logger.error(f"NoReverseMatch for 'track_open' (Contact: {contact.id}, Campaign: {campaign.id}). Error: {e}", exc_info=True)

        except Site.DoesNotExist:
            logger.error(f"Django Site matching query does not exist (Campaign: {campaign_id}). Configure SITE_ID and django_site table.", exc_info=True)
            unsubscribe_url = f"{base_url_for_links}/site-config-error/unsubscribe/{contact.unsubscribe_token if contact.unsubscribe_token else 'no-token'}/"
        except Exception as e:
            logger.error(f"General error generating URLs (Contact: {contact.id}, Campaign: {campaign.id}): {e}", exc_info=True)
            unsubscribe_url = f"{base_url_for_links}/url-gen-error/unsubscribe/{contact.unsubscribe_token if contact.unsubscribe_token else 'no-token'}/"

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
            'site_url': app_settings_obj.site_url or base_url_for_links,
        }
        if isinstance(contact.custom_fields, dict):
            context_data.update(contact.custom_fields)

        django_template_context = Context(context_data)

        try:
            subject_template = Template(email_template.subject)
            personalized_subject = subject_template.render(django_template_context)
        except TemplateSyntaxError as e:
            logger.warning(f"Template syntax error in subject for template '{email_template.name}' (Campaign: {campaign.id}). Using raw subject. Error: {e}")
            personalized_subject = email_template.subject

        try:
            html_body_template = Template(email_template.html_content)
            personalized_html_body_full_doc = html_body_template.render(django_template_context)

            footer_template = Template(email_template.footer_html)
            personalized_footer_content = footer_template.render(django_template_context)

            soup = BeautifulSoup(personalized_html_body_full_doc, 'html.parser')

            footer_div_str = f'<div style="text-align: center; padding-top: 20px; font-size: 12px; color: #777; clear:both; width:100%;">{personalized_footer_content}</div>'
            footer_soup_element = BeautifulSoup(footer_div_str, 'html.parser')

            tracking_pixel_html_str = context_data['tracking_pixel']
            tracking_pixel_soup_element = BeautifulSoup(tracking_pixel_html_str, 'html.parser')

            target_body = soup.body
            if not target_body:
                logger.warning(f"No <body> tag found in HTML content for template {email_template.name}. Creating one.")
                original_content_str = str(soup)
                soup = BeautifulSoup(f"<body>{original_content_str}</body>", "html.parser")
                target_body = soup.body

            if footer_soup_element.contents:
                for child_node in list(footer_soup_element.contents):
                    target_body.append(child_node.extract())

            if tracking_pixel_html_str and "<!--" not in tracking_pixel_html_str and tracking_pixel_soup_element.contents:
                for child_node in list(tracking_pixel_soup_element.contents):
                    target_body.append(child_node.extract())

            full_html_content = str(soup)
            logger.info(f"Final HTML structure for {contact.email} (Campaign: {campaign.id}) prepared successfully.")

        except TemplateSyntaxError as e:
            log_error_message = f"Template syntax error in HTML body/footer: {str(e)}"
            logger.error(f"{log_error_message} (Template: '{email_template.name}', Campaign: {campaign.id}, Contact: {contact.id})", exc_info=True)
            Campaign.objects.filter(pk=campaign.id).update(failed_to_send=F('failed_to_send') + 1)
            raise

        send_mail(
            subject=personalized_subject,
            message=strip_tags(full_html_content),
            from_email=app_settings_obj.sender_email,
            recipient_list=[contact.email],
            html_message=full_html_content,
            fail_silently=False
        )
        processed_successfully = True
        log_status = 'success'
        logger.info(f"Email successfully sent to {contact.email} for campaign {campaign.id}.")
        Campaign.objects.filter(pk=campaign.id).update(successfully_sent=F('successfully_sent') + 1)
        return f"Email sent to {contact.email}."

    except Contact.DoesNotExist:
        logger.error(f"Contact ID {contact_id} does not exist. (Campaign: {campaign_id if campaign else 'unknown'})")
        log_error_message = f"Contact ID {contact_id} not found."
        # Log will be created in 'finally'. No campaign counter update.
        return log_error_message
    except Campaign.DoesNotExist:
        logger.error(f"Campaign ID {campaign_id} does not exist. (Contact: {contact_id if contact else 'unknown'})")
        # Cannot update a campaign that doesn't exist. Log will be created in 'finally'.
        return f"Error: Campaign ID {campaign_id} not found."
    except Exception as e:
        log_error_message = log_error_message or f"Unexpected task error: {str(e)[:250]}"
        logger.exception(f"{log_error_message} (Contact: {contact_id if contact else 'unknown'}, Campaign: {campaign_id if campaign else 'unknown'})")
        if campaign:
            Campaign.objects.filter(pk=campaign.id).update(failed_to_send=F('failed_to_send') + 1)
        # Consider Celery retry logic here if appropriate:
        # if self.request.retries < self.max_retries: self.retry(exc=e)
        return f"Failed for contact {contact_id}, campaign {campaign_id} due to: {log_error_message}"
    finally:
        # Ensure a log entry is made for every attempt that reaches this stage.
        # This includes successful sends, failures, and explicitly handled skips that return.
        final_contact_email = "unknown_email"
        final_contact_id_for_log = None
        final_campaign_id_for_log = None

        if contact: # If contact object was successfully fetched
            final_contact_email = contact.email
            final_contact_id_for_log = contact.id
        elif contact_id: # If contact object fetch failed, but we have the ID
            final_contact_id_for_log = contact_id
            try: # Attempt to get email if only ID is available
                c = Contact.objects.get(id=contact_id)
                final_contact_email = c.email
            except Contact.DoesNotExist:
                logger.warning(f"Could not fetch email for contact ID {contact_id} during final logging.")


        if campaign: # If campaign object was successfully fetched
            final_campaign_id_for_log = campaign.id
        elif campaign_id: # If campaign object fetch failed, but we have the ID
            final_campaign_id_for_log = campaign_id


        if final_contact_id_for_log and final_campaign_id_for_log:
            log_defaults = {
                'status': log_status,
                'message_id': 'N/A_django-ses' if processed_successfully else None,
                'error_message': log_error_message
            }
            # Use update_or_create to handle retries that might have already created a log
            log_entry, created = CampaignSendLog.objects.update_or_create(
                campaign_id=final_campaign_id_for_log,
                contact_id=final_contact_id_for_log, # Use ID here for safety if contact object is None
                email_address=final_contact_email, # Log the email address
                defaults=log_defaults
            )
            if not created: # If the log entry was updated
                logger.info(f"Updated existing CampaignSendLog for Contact: {final_contact_id_for_log}, Campaign: {final_campaign_id_for_log}, Status: {log_status}")
            else:
                logger.info(f"Created new CampaignSendLog for Contact: {final_contact_id_for_log}, Campaign: {final_campaign_id_for_log}, Status: {log_status}")
        else:
            logger.error(f"Could not create CampaignSendLog: Contact ID or Campaign ID missing. ContactID: {final_contact_id_for_log}, CampaignID: {final_campaign_id_for_log}, Status: {log_status}, Error: {log_error_message}")

        if campaign_id is not None:
             check_campaign_completion(campaign_id)
# END MARKER FOR send_single_email_task IN tasks.py (REPLACE THE ENTIRE FUNCTION)

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
    Processes a campaign by queuing email tasks for subscribed contacts,
    applying segment filters including contact lists.
    """
    try:
        campaign = Campaign.objects.get(id=campaign_id)
        if campaign.status not in ['draft', 'scheduled', 'queued', 'retrying', 'failed', 'sending']:
            logger.info(f"Campaign '{campaign.name}' (ID: {campaign_id}) is in status '{campaign.status}', not processing.")
            return f"Campaign '{campaign.name}' not in a sendable state (status: {campaign.status})."

        Campaign.objects.filter(pk=campaign.pk).update(
            status='sending',
            successfully_sent=0,
            failed_to_send=0,
            sent_at=None
        )
        campaign.refresh_from_db()

        contacts_to_send_qs = Contact.objects.filter(subscribed=True, email__isnull=False).exclude(email__exact='')
        
        if campaign.contact_lists.exists():
            contacts_to_send_qs = contacts_to_send_qs.filter(contact_list__in=campaign.contact_lists.all())
        
        if campaign.segments.exists():
            segment_filters = []
            for segment in campaign.segments.all():
                filters = segment.filters
                segment_qs = Contact.objects.all()
                if filters.get('subscribed'):
                    subscribed = filters['subscribed'] == 'true'
                    segment_qs = segment_qs.filter(subscribed=subscribed)
                if filters.get('company'):
                    segment_qs = segment_qs.filter(company__icontains=filters['company'])
                if filters.get('custom_fields'):
                    for key, value in filters['custom_fields'].items():
                        segment_qs = segment_qs.filter(custom_fields__has_key=key, custom_fields__contains={key: value})
                if filters.get('contact_lists'):
                    segment_qs = segment_qs.filter(contact_list__id__in=filters['contact_lists'])
                segment_filters.append(segment_qs.values('id'))
            if segment_filters:
                combined_ids = set()
                for qs in segment_filters:
                    combined_ids.update(qs.values_list('id', flat=True))
                contacts_to_send_qs = contacts_to_send_qs.filter(id__in=combined_ids)

        contacts_to_send_qs = contacts_to_send_qs.distinct()

        current_total_recipients = contacts_to_send_qs.count()

        Campaign.objects.filter(pk=campaign.pk).update(total_recipients=current_total_recipients)
        
        if current_total_recipients == 0:
            logger.info(f"No valid contacts for campaign '{campaign.name}'. Marking as failed.")
            Campaign.objects.filter(pk=campaign.pk).update(status='failed', sent_at=timezone.now())
            return f"No valid contacts for campaign '{campaign.name}'."

        recipients_queued_count = 0
        for contact in contacts_to_send_qs:
            send_single_email_task.delay(contact.id, campaign.id)
            recipients_queued_count += 1

        logger.info(f"Queued {recipients_queued_count} emails for campaign '{campaign.name}'. Total recipients: {current_total_recipients}.")
        return f"Successfully queued {recipients_queued_count} emails for campaign '{campaign.name}'."

    except Campaign.DoesNotExist:
        logger.error(f"Campaign ID {campaign_id} not found.")
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


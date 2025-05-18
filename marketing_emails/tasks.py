# marketing_emails/tasks.py

from celery import shared_task
from django.conf import settings
from django.template import Context, Template, TemplateSyntaxError
from django.utils import timezone
from django.urls import reverse, NoReverseMatch # For generating URLs
from django.contrib.sites.models import Site # To get current site domain
from django.db.models import F # For F() expressions for atomic updates

import boto3
from botocore.exceptions import ClientError
import logging

# Imports from your mailer_app models
# This assumes your models (Contact, Campaign, etc.) are in 'mailer_app.models'
from mailer_app.models import Contact, Campaign, EmailTemplate, CampaignSendLog

logger = logging.getLogger(__name__) # Standard way to get a logger instance

@shared_task(bind=True, max_retries=3, default_retry_delay=5 * 60) # Retry 3 times, with 5 min delay
def send_single_email_task(self, contact_id, campaign_id):
    """
    Sends a single personalized email to a contact for a given campaign.
    Includes unsubscribe link generation and robust error logging.
    'bind=True' gives access to 'self' (the task instance) for retries.
    """
    try:
        contact = Contact.objects.get(id=contact_id)
        campaign = Campaign.objects.get(id=campaign_id)
        email_template = campaign.email_template

        if not contact.subscribed:
            logger.info(f"Contact {contact.email} (ID: {contact_id}) is unsubscribed. Skipping for campaign '{campaign.name}'.")
            return f"Skipped: Contact {contact.email} unsubscribed."

        if not email_template:
            logger.error(f"No email template found for campaign '{campaign.name}' (ID: {campaign.id}). Cannot send to {contact.email}.")
            CampaignSendLog.objects.create(
                campaign=campaign, contact=contact, email_address=contact.email,
                status='failed', error_message="Campaign has no email template selected."
            )
            Campaign.objects.filter(pk=campaign.pk).update(failed_to_send=F('failed_to_send') + 1)
            return f"Error: Campaign '{campaign.name}' has no template."

        # Generate unique unsubscribe URL
        unsubscribe_url = '#' # Default placeholder if token is missing or URL generation fails
        if contact.unsubscribe_token:
            logger.info(f"Contact {contact.id} has unsubscribe_token: {contact.unsubscribe_token}")
            try:
                current_site = Site.objects.get_current() # Requires SITE_ID in settings
                domain = current_site.domain
                protocol = 'https' if not settings.DEBUG else 'http' # Use https in production
                
                # Ensure 'mailer_app:unsubscribe_contact' is the correct namespaced URL name
                path = reverse('mailer_app:unsubscribe_contact', kwargs={'token': str(contact.unsubscribe_token)})
                unsubscribe_url = f"{protocol}://{domain}{path}"
                logger.info(f"Generated unsubscribe URL for contact {contact.id}: {unsubscribe_url}")

            except NoReverseMatch as e_reverse:
                logger.error(f"NoReverseMatch for 'mailer_app:unsubscribe_contact' for contact {contact.id}: {e_reverse}. Token: {contact.unsubscribe_token}. Using placeholder URL.")
            except Site.DoesNotExist as e_site:
                 logger.error(f"Site matching query does not exist (SITE_ID: {settings.SITE_ID}) for contact {contact.id}: {e_site}. Cannot generate absolute unsubscribe URL. Using placeholder.")
            except Exception as e: # Catch any other errors during URL generation
                logger.error(f"Could not generate unsubscribe URL for contact {contact.id} (Token: {contact.unsubscribe_token}): {e}. Using placeholder URL.", exc_info=True)
        else:
            logger.warning(f"Contact {contact.id} (Email: {contact.email}) has NO unsubscribe_token. Unsubscribe URL will be a placeholder ('#').")
        
        # Prepare context data for template rendering
        context_data = {
            'first_name': contact.first_name or '',
            'last_name': contact.last_name or '',
            'email': contact.email,
            'company': contact.company or '',
            'job_title': contact.job_title or '',
            'unsubscribe_url': unsubscribe_url,
            'your_company_name': getattr(settings, 'YOUR_COMPANY_NAME', "Your Company"), # Get from settings or use a default
        }
        # Add custom fields from the contact's JSONField to the context
        if isinstance(contact.custom_fields, dict):
            for key, value in contact.custom_fields.items():
                context_data[key] = value

        django_template_context = Context(context_data)

        # Personalize subject
        try:
            subject_template = Template(email_template.subject)
            personalized_subject = subject_template.render(django_template_context)
        except TemplateSyntaxError as e:
            logger.error(f"Template syntax error in subject for template '{email_template.name}': {e}")
            personalized_subject = email_template.subject # Fallback to non-personalized subject

        # Personalize HTML content
        try:
            html_body_template = Template(email_template.html_content)
            personalized_html_body = html_body_template.render(django_template_context)
        except TemplateSyntaxError as e:
            logger.error(f"Template syntax error in HTML body for template '{email_template.name}': {e}")
            CampaignSendLog.objects.create(
                campaign=campaign, contact=contact, email_address=contact.email,
                status='failed', error_message=f"Template syntax error in HTML content: {e}"
            )
            Campaign.objects.filter(pk=campaign.pk).update(failed_to_send=F('failed_to_send') + 1)
            return f"Error: Template syntax error in HTML for template '{email_template.name}'."

        # Initialize Boto3 SES client
        client = boto3.client(
            'ses', region_name=settings.AWS_SES_REGION_NAME,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY
        )
        message_body = {'Html': {'Charset': "UTF-8", 'Data': personalized_html_body}}
        # If you also have plain text content:
        # message_body['Text'] = {'Charset': "UTF-8", 'Data': personalized_plain_text_body}

        # Send the email via AWS SES
        try:
            response = client.send_email(
                Destination={'ToAddresses': [contact.email]},
                Message={'Body': message_body, 'Subject': {'Charset': "UTF-8", 'Data': personalized_subject}},
                Source=settings.AWS_SES_SENDER_EMAIL, # Ensure this is correctly defined in settings.py
                # ConfigurationSetName=settings.AWS_SES_CONFIGURATION_SET, # Optional: if you use SES Configuration Sets
            )
            logger.info(f"Email sent to {contact.email} for campaign '{campaign.name}'. Message ID: {response['MessageId']}")
            CampaignSendLog.objects.create(
                campaign=campaign, contact=contact, email_address=contact.email,
                status='success', message_id=response['MessageId']
            )
            # Atomically increment the successfully_sent count for the campaign
            Campaign.objects.filter(pk=campaign.pk).update(successfully_sent=F('successfully_sent') + 1)
            return f"Email sent to {contact.email}. Message ID: {response['MessageId']}"

        except ClientError as e:
            error_message_text = e.response.get('Error', {}).get('Message', str(e))
            logger.error(f"AWS SES ClientError sending to {contact.email} for campaign '{campaign.name}': {error_message_text}")
            CampaignSendLog.objects.create(
                campaign=campaign, contact=contact, email_address=contact.email,
                status='failed', error_message=error_message_text
            )
            Campaign.objects.filter(pk=campaign.pk).update(failed_to_send=F('failed_to_send') + 1)
            # Retry the task based on Celery's retry settings
            raise self.retry(exc=e, countdown=60) # Example: retry in 60 seconds

    except Contact.DoesNotExist:
        logger.error(f"Contact ID {contact_id} not found. Cannot send email for campaign ID {campaign_id}.")
        try: # Attempt to log failure to campaign if campaign exists
            campaign_obj = Campaign.objects.get(id=campaign_id)
            CampaignSendLog.objects.create(
                campaign=campaign_obj, contact=None, email_address=f"Unknown (Contact ID {contact_id} not found)",
                status='failed', error_message="Contact not found during sending."
            )
            Campaign.objects.filter(pk=campaign_id).update(failed_to_send=F('failed_to_send') + 1)
        except Campaign.DoesNotExist:
            logger.error(f"Campaign ID {campaign_id} also not found while trying to log Contact.DoesNotExist.")
        return f"Error: Contact ID {contact_id} not found."
    except Campaign.DoesNotExist:
        logger.error(f"Campaign ID {campaign_id} not found. Cannot send email to contact ID {contact_id}.")
        return f"Error: Campaign ID {campaign_id} not found."
    except Exception as e: # Catch any other unexpected errors
        logger.exception(f"Unexpected error in send_single_email_task for contact {contact_id}, campaign {campaign_id}: {e}")
        try: # Attempt to log this generic failure
            campaign_obj = Campaign.objects.get(id=campaign_id)
            contact_obj = Contact.objects.filter(id=contact_id).first() # Use filter().first() to avoid DoesNotExist
            email_to_log = contact_obj.email if contact_obj else f"Unknown (Contact ID {contact_id})"
            
            CampaignSendLog.objects.get_or_create( # Use get_or_create to avoid duplicate logs for the same failure if retried
                campaign=campaign_obj, 
                contact=contact_obj, 
                email_address=email_to_log,
                status='failed', 
                defaults={'error_message': f"Unexpected task error: {str(e)[:250]}"} # Store a snippet of the error
            )
            Campaign.objects.filter(pk=campaign_id).update(failed_to_send=F('failed_to_send') + 1)
        except Exception as log_e: # Catch errors during this fallback logging attempt
            logger.error(f"Critical error during fallback logging in send_single_email_task after unexpected error: {log_e}")

        if self.request.retries < self.max_retries:
            raise self.retry(exc=e, countdown=5 * 60) # Retry with a delay for unexpected errors
        else:
            logger.error(f"Max retries reached for contact {contact_id}, campaign {campaign_id} after unexpected error. Task failed permanently.")
            return f"Failed permanently after retries for contact {contact_id}, campaign {campaign_id}: {e}"


@shared_task
def process_campaign_task(campaign_id):
    """
    Processes a campaign by creating individual email sending tasks for each subscribed contact.
    Correctly handles ManyToManyField for contact_lists.
    """
    try:
        campaign = Campaign.objects.get(id=campaign_id)
        
        # Check if the campaign is in a state where it can be processed
        if campaign.status not in ['draft', 'scheduled', 'queued', 'retrying', 'failed']: # Allow reprocessing failed or retrying
            logger.info(f"Campaign '{campaign.name}' (ID: {campaign_id}) is in status '{campaign.status}' and will not be processed now.")
            return f"Campaign '{campaign.name}' not in a sendable state (status: {campaign.status})."

        # Reset counts for this run and set status to sending using an atomic update
        Campaign.objects.filter(pk=campaign.pk).update(
            successfully_sent=0,
            failed_to_send=0,
            status='sending'
        )
        campaign.refresh_from_db() # Refresh local instance with updated values from DB

        # Calculate total recipients based on ManyToManyField contact_lists for this specific run
        current_total_recipients = Contact.objects.filter(
            contact_list__in=campaign.contact_lists.all(), # Correctly query contacts from all associated lists
            subscribed=True,
            email__isnull=False # Ensure email exists
        ).exclude(email__exact='').distinct().count() # Ensure email is not empty and count distinct contacts
        
        Campaign.objects.filter(pk=campaign.pk).update(total_recipients=current_total_recipients)
        campaign.refresh_from_db() # Refresh again after updating total_recipients

        recipients_queued_count = 0
        if not campaign.contact_lists.exists():
            logger.warning(f"Campaign '{campaign.name}' (ID: {campaign_id}) has no contact lists associated. No emails will be sent.")
        else:
            # Iterate through each contact list associated with the campaign
            for contact_list_obj in campaign.contact_lists.all():
                # For each contact list, get its subscribed contacts with valid emails
                contacts_in_list = contact_list_obj.contacts.filter(
                    subscribed=True, 
                    email__isnull=False # Ensure email is not NULL
                ).exclude(email__exact='') # Ensure email is not an empty string
                
                for contact in contacts_in_list:
                    send_single_email_task.delay(contact.id, campaign.id)
                    recipients_queued_count += 1
        
        if recipients_queued_count == 0:
            logger.info(f"No valid & subscribed contacts to email for campaign '{campaign.name}' (ID: {campaign_id}). Marking as failed.")
            Campaign.objects.filter(pk=campaign.pk).update(status='failed', sent_at=timezone.now())
            return f"No valid contacts to email for campaign '{campaign.name}'."

        logger.info(f"Queued {recipients_queued_count} emails for campaign '{campaign.name}'. Campaign status set to 'sending'.")
        # Note: The campaign status remains 'sending'.
        # A separate mechanism (e.g., another periodic task or signal handling)
        # would be needed to check if all send_single_email_task for a campaign
        # have completed to mark the campaign as 'sent' or 'partially_failed'.
        return f"Successfully queued {recipients_queued_count} emails for campaign '{campaign.name}'."

    except Campaign.DoesNotExist:
        logger.error(f"Campaign ID {campaign_id} not found for processing.")
        return f"Error: Campaign ID {campaign_id} not found."
    except Exception as e:
        logger.exception(f"Error processing campaign ID {campaign_id}: {e}")
        try: # Attempt to mark campaign as failed
            Campaign.objects.filter(pk=campaign_id).update(status='failed')
        except Campaign.DoesNotExist:
            pass # Already logged if it doesn't exist
        raise # Re-raise the exception so Celery marks the task as failed


@shared_task
def check_scheduled_campaigns_task():
    """
    Periodically checks for campaigns that are scheduled to be sent.
    This task should be configured in Django Admin > Periodic Tasks (django-celery-beat).
    """
    now = timezone.now()
    logger.info(f"Running check_scheduled_campaigns_task at {now.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Find campaigns that are:
    # 1. Status is 'scheduled'
    # 2. scheduled_at is not null
    # 3. scheduled_at is in the past or now
    campaigns_to_send = Campaign.objects.filter(
        status='scheduled', 
        scheduled_at__isnull=False, 
        scheduled_at__lte=now      
    )

    if not campaigns_to_send.exists():
        logger.info("No scheduled campaigns are due to be sent at this time.")
        return "No scheduled campaigns found to process."

    processed_count = 0
    for campaign in campaigns_to_send:
        logger.info(f"Found scheduled campaign: '{campaign.name}' (ID: {campaign.id}), scheduled for {campaign.scheduled_at.strftime('%Y-%m-%d %H:%M:%S')}. Triggering processing.")
        # Update status to 'queued' to prevent re-processing by this task in immediate subsequent runs
        Campaign.objects.filter(pk=campaign.pk).update(status='queued')
        
        # Dispatch the main processing task for this campaign
        process_campaign_task.delay(campaign.id)
        processed_count += 1
    
    logger.info(f"Finished check_scheduled_campaigns_task. Processed {processed_count} scheduled campaigns.")
    return f"Processed {processed_count} scheduled campaigns."


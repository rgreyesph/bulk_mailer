# marketing_emails/tasks.py

from celery import shared_task
from django.conf import settings
from django.template import Context, Template, TemplateSyntaxError
from django.utils import timezone
import boto3
from botocore.exceptions import ClientError
import logging

from .models import Contact, Campaign, EmailTemplate, EmailTracking # Ensure your models are correctly imported

# Get an instance of a logger
logger = logging.getLogger(__name__)

@shared_task(bind=True, max_retries=3, default_retry_delay=5 * 60) # Retry 3 times, with 5 min delay
def send_single_email_task(self, contact_id, campaign_id):
    """
    Sends a single personalized email to a contact for a given campaign.
    This task is intended to be called by process_campaign_task.
    'bind=True' gives access to 'self' (the task instance) for retries.
    """
    try:
        # Retrieve the contact and campaign from the database
        contact = Contact.objects.get(id=contact_id)
        campaign = Campaign.objects.get(id=campaign_id)
        email_template = campaign.email_template

        # Check if the contact is subscribed
        if not contact.subscribed:
            logger.info(f"Contact {contact.email} (ID: {contact_id}) is unsubscribed. Skipping for campaign '{campaign.name}' (ID: {campaign_id}).")
            return f"Skipped: Contact {contact.email} unsubscribed."

        # Check if the campaign has an associated email template
        if not email_template:
            logger.error(f"No email template associated with campaign '{campaign.name}' (ID: {campaign_id}). Cannot send to {contact.email}.")
            # Optionally, update campaign status to reflect this critical error
            # campaign.status = 'failed'
            # campaign.save(update_fields=['status'])
            return f"Error: Campaign '{campaign.name}' has no template."

        # Prepare context data for personalization
        # Basic context fields
        context_data = {
            'first_name': contact.first_name or '', # Use empty string if None
            'last_name': contact.last_name or '',   # Use empty string if None
            'email': contact.email,
        }
        # Add custom fields from the contact's JSONField to the context
        if isinstance(contact.custom_fields, dict):
            for key, value in contact.custom_fields.items():
                # Ensure keys are valid Python identifiers if used directly as template variables
                # For simplicity, we add them as is. Django templates are quite flexible.
                context_data[key] = value

        django_template_context = Context(context_data)

        # Personalize subject
        try:
            subject_template = Template(email_template.subject)
            personalized_subject = subject_template.render(django_template_context)
        except TemplateSyntaxError as e:
            logger.error(f"Template syntax error in subject for template '{email_template.name}': {e}")
            # Potentially skip this email or use a default subject
            personalized_subject = email_template.subject # Fallback to non-personalized
        
        # Personalize HTML content
        try:
            html_body_template = Template(email_template.html_content)
            personalized_html_body = html_body_template.render(django_template_context)
        except TemplateSyntaxError as e:
            logger.error(f"Template syntax error in HTML body for template '{email_template.name}': {e}")
            # This is a more critical error, might want to skip or mark as failed
            return f"Error: Template syntax error in HTML for {email_template.name}."

        # (Optional) Personalize plain text content if you use it
        # personalized_text_body = ""
        # if email_template.text_content:
        #     try:
        #         text_body_template = Template(email_template.text_content)
        #         personalized_text_body = text_body_template.render(django_template_context)
        #     except TemplateSyntaxError as e:
        #         logger.warning(f"Template syntax error in text body for template '{email_template.name}': {e}")
        #         # Fallback or ignore

        # Initialize Boto3 SES client
        client = boto3.client(
            'ses',
            region_name=settings.AWS_SES_REGION_NAME,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY
        )

        # Construct the email message
        message_body = {'Html': {'Charset': "UTF-8", 'Data': personalized_html_body}}
        # if personalized_text_body:
        #     message_body['Text'] = {'Charset': "UTF-8", 'Data': personalized_text_body}

        # Send the email via AWS SES
        try:
            response = client.send_email(
                Destination={'ToAddresses': [contact.email]},
                Message={
                    'Body': message_body,
                    'Subject': {'Charset': "UTF-8", 'Data': personalized_subject},
                },
                Source=settings.AWS_SES_SENDER_EMAIL,
                # If you use SES Configuration Sets for tracking opens, clicks, etc.
                # ConfigurationSetName=settings.AWS_SES_CONFIGURATION_SET_NAME if hasattr(settings, 'AWS_SES_CONFIGURATION_SET_NAME') else None,
            )
            
            # Log success and create a tracking record
            logger.info(f"Email sent to {contact.email} for campaign '{campaign.name}'. Message ID: {response['MessageId']}")
            EmailTracking.objects.create(
                campaign=campaign,
                contact=contact,
                ses_message_id=response['MessageId'],
                sent_time=timezone.now(), # Record actual send time
                # status='Sent' # You might update this based on SES notifications (SNS -> SQS -> YourApp)
            )
            return f"Email sent to {contact.email}. Message ID: {response['MessageId']}"

        except ClientError as e:
            error_message = e.response.get('Error', {}).get('Message', str(e))
            logger.error(f"Failed to send email to {contact.email} for campaign '{campaign.name}': {error_message}")
            # Create a tracking record for the failure
            EmailTracking.objects.create(
                campaign=campaign,
                contact=contact,
                ses_message_id=None, # No message ID on failure
                sent_time=timezone.now(),
                # status=f"Failed: {error_message[:100]}" # Store a snippet of the error
            )
            # Retry the task based on Celery's retry settings (max_retries, default_retry_delay)
            # self.retry(exc=e) will use the default_retry_delay
            # You can customize retry behavior based on the type of error if needed
            raise self.retry(exc=e, countdown=60) # Example: retry in 60 seconds

    except Contact.DoesNotExist:
        logger.error(f"Contact with ID {contact_id} not found. Cannot send email for campaign ID {campaign_id}.")
        return f"Error: Contact ID {contact_id} not found."
    except Campaign.DoesNotExist:
        logger.error(f"Campaign with ID {campaign_id} not found. Cannot send email to contact ID {contact_id}.")
        return f"Error: Campaign ID {campaign_id} not found."
    except Exception as e:
        # Catch any other unexpected errors
        logger.exception(f"An unexpected error occurred in send_single_email_task for contact ID {contact_id}, campaign ID {campaign_id}: {e}")
        # Retry for unexpected errors as well
        # Check if self.request.retries is available and less than max_retries
        if self.request.retries < self.max_retries:
             raise self.retry(exc=e, countdown=5 * 60) # Retry after 5 minutes
        else:
            logger.error(f"Max retries reached for contact ID {contact_id}, campaign ID {campaign_id}. Task failed permanently.")
            # Mark as failed in EmailTracking if not already done
            try:
                contact = Contact.objects.get(id=contact_id)
                campaign = Campaign.objects.get(id=campaign_id)
                EmailTracking.objects.get_or_create(
                    campaign=campaign,
                    contact=contact,
                    defaults={
                        'ses_message_id': None,
                        'sent_time': timezone.now(),
                        # 'status': f"Failed Permanently: {str(e)[:100]}"
                    }
                )
            except (Contact.DoesNotExist, Campaign.DoesNotExist):
                pass # Already logged or handled
            return f"Failed permanently after retries: {e}"


@shared_task
def process_campaign_task(campaign_id):
    """
    Processes a campaign by creating individual email sending tasks for each subscribed contact.
    """
    try:
        campaign = Campaign.objects.get(id=campaign_id)
        
        # Check if the campaign is in a state where it can be processed
        if campaign.status not in ['draft', 'scheduled', 'queued', 'retrying', 'failed']: # Allow reprocessing failed or retrying
            logger.info(f"Campaign '{campaign.name}' (ID: {campaign_id}) is in status '{campaign.status}' and will not be processed now.")
            return f"Campaign '{campaign.name}' not in a sendable state (status: {campaign.status})."

        # Update campaign status to 'sending'
        campaign.status = 'sending'
        campaign.save(update_fields=['status'])

        recipients_count = 0
        # Iterate through all contact lists associated with the campaign
        for contact_list in campaign.contact_lists.all():
            # Iterate through subscribed contacts in each list
            for contact in contact_list.contacts.filter(subscribed=True):
                # Dispatch a separate task for sending email to each contact
                send_single_email_task.delay(contact.id, campaign.id)
                recipients_count += 1
        
        if recipients_count == 0:
            logger.info(f"No subscribed contacts found for campaign '{campaign.name}' (ID: {campaign_id}).")
            # Decide what to do if no recipients: mark as 'sent' or 'failed'?
            campaign.status = 'sent' # Or 'failed' if this is an error condition for you
            campaign.sent_at = timezone.now() # Mark as sent (or processed)
            campaign.save(update_fields=['status', 'sent_at'])
            return f"No subscribed contacts for campaign '{campaign.name}'."

        logger.info(f"Queued {recipients_count} emails for campaign '{campaign.name}' (ID: {campaign_id}). Campaign status set to 'sending'.")
        
        # IMPORTANT: Updating campaign status to 'sent'
        # The campaign status is currently 'sending'. A more robust system would update it to 'sent' 
        # only after all individual email tasks for that campaign have completed successfully.
        # This can be achieved using Celery's more advanced features like groups, chords, 
        # or a separate monitoring task that checks EmailTracking records.
        # For now, the status remains 'sending'. You might need a manual step or a periodic task 
        # to check EmailTracking and update the campaign to 'sent' or 'partially_failed'.
        # A simple approach (though not perfectly accurate if tasks fail) is to set sent_at here.
        # campaign.sent_at = timezone.now() # This is premature for accurate 'sent' time of all emails
        # campaign.save(update_fields=['sent_at'])

        return f"Successfully queued {recipients_count} emails for campaign '{campaign.name}'."

    except Campaign.DoesNotExist:
        logger.error(f"Campaign with ID {campaign_id} not found for processing.")
        return f"Error: Campaign ID {campaign_id} not found."
    except Exception as e:
        logger.exception(f"Error processing campaign ID {campaign_id}: {e}")
        # Optionally, set campaign status back to 'failed' or 'retrying'
        try:
            campaign = Campaign.objects.get(id=campaign_id)
            campaign.status = 'failed'
            campaign.save(update_fields=['status'])
        except Campaign.DoesNotExist:
            pass # Already logged
        # Re-raise the exception so Celery marks the task as failed
        raise


@shared_task
def check_scheduled_campaigns_task():
    """
    Periodically checks for campaigns that are scheduled to be sent.
    This task should be configured in Django Admin > Periodic Tasks (via django-celery-beat).
    Example: Run every 1 or 5 minutes.
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
        # before process_campaign_task changes it to 'sending'.
        campaign.status = 'queued' 
        campaign.save(update_fields=['status'])
        
        # Dispatch the main processing task for this campaign
        process_campaign_task.delay(campaign.id)
        processed_count += 1
    
    logger.info(f"Finished check_scheduled_campaigns_task. Processed {processed_count} scheduled campaigns.")
    return f"Processed {processed_count} scheduled campaigns."


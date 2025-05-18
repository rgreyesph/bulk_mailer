# mailer_app/models.py
from django.db import models
import uuid # For unique identifiers

class ContactList(models.Model):
    """
    Represents a list of contacts, typically imported from a CSV.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, help_text="e.g., 'Newsletter Subscribers Q1 2024'")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['-created_at'] # Order by newest first by default

class Contact(models.Model):
    """
    Represents an individual contact.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    contact_list = models.ForeignKey(ContactList, related_name='contacts', on_delete=models.CASCADE, null=True, blank=True, help_text="The list this contact was originally imported into, if applicable.")
    email = models.EmailField(blank=True, null=True ) # Can be null if a contact is only identified by other means initially
    first_name = models.CharField(max_length=100, blank=True, null=True)
    last_name = models.CharField(max_length=100, blank=True, null=True)
    company = models.CharField(max_length=100, blank=True, null=True)
    job_title = models.CharField(max_length=100, blank=True, null=True)
    custom_fields = models.JSONField(blank=True, null=True, help_text="Stores additional columns from CSV not covered by specific fields.")
    subscribed = models.BooleanField(default=True, help_text="Indicates if the contact is currently subscribed to receive emails.")
    # Temporarily removed default=uuid.uuid4 for the initial migration.
    # The save() method will handle token generation.
    # null=True allows existing rows to have NULL for this new unique field.
    unsubscribe_token = models.UUIDField(editable=False, unique=True, null=True, blank=True, help_text="Unique token for one-click unsubscribe.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        # Ensure an unsubscribe token is generated if it's missing.
        # This will apply to new contacts and existing contacts if their token is None when they are saved.
        if not self.unsubscribe_token:
            self.unsubscribe_token = uuid.uuid4()
        super().save(*args, **kwargs)

    class Meta:
        ordering = ['email', 'created_at']

    def __str__(self):
        if self.email:
            return self.email
        return f"Contact {self.id}"

class EmailTemplate(models.Model):
    """
    Stores HTML email templates.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, unique=True, help_text="e.g., 'Welcome Email Template'")
    subject = models.CharField(max_length=255, help_text="Email subject line. Can include merge tags like {{first_name}}.")
    html_content = models.TextField(help_text="HTML content of the email. Use merge tags like {{first_name}}, {{email}}, {{company}}, {{job_title}}.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['-created_at']

class Campaign(models.Model):
    """
    Represents a bulk email sending campaign.
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('scheduled', 'Scheduled'),
        ('queued', 'Queued'),
        ('sending', 'Sending'),
        ('sent', 'Sent'),
        ('failed', 'Failed'),
        ('archived', 'Archived'), # Optional: for completed campaigns
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, help_text="e.g., 'April Newsletter Campaign'")
    contact_lists = models.ManyToManyField(ContactList, blank=True, related_name="campaigns", help_text="Select one or more contact lists for this campaign.")
    email_template = models.ForeignKey(EmailTemplate, on_delete=models.SET_NULL, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    scheduled_at = models.DateTimeField(null=True, blank=True, help_text="If set, campaign will attempt to send at this time.")
    sent_at = models.DateTimeField(null=True, blank=True, help_text="Timestamp of when the campaign sending was completed or last attempted.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    total_recipients = models.PositiveIntegerField(default=0, help_text="Estimated or actual number of recipients targeted by this campaign run.")
    successfully_sent = models.PositiveIntegerField(default=0, help_text="Number of emails successfully accepted by SES for this campaign run.")
    failed_to_send = models.PositiveIntegerField(default=0, help_text="Number of emails that failed to send for this campaign run.")

    def __str__(self):
        return f"{self.name} ({self.get_status_display()})"

    class Meta:
        ordering = ['-created_at']

class CampaignSendLog(models.Model):
    """
    Logs individual email send attempts for a campaign.
    """
    campaign = models.ForeignKey(Campaign, related_name='logs', on_delete=models.CASCADE)
    contact = models.ForeignKey(Contact, on_delete=models.SET_NULL, null=True)
    email_address = models.EmailField(help_text="The email address the message was sent to.")
    sent_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=[('success', 'Success'), ('failed', 'Failed')])
    message_id = models.CharField(max_length=255, blank=True, null=True, help_text="AWS SES Message ID, if successful.")
    error_message = models.TextField(blank=True, null=True, help_text="Error details, if sending failed.")

    def __str__(self):
        return f"{self.campaign.name} - {self.email_address} - {self.status}"

    class Meta:
        ordering = ['-sent_at']

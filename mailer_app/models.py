from django.db import models
import uuid
from django.conf import settings # For user model AND AUTH_USER_MODEL
import os # For filename
import logging # For logger in MediaAsset delete_from_storage (optional, but good practice)

logger = logging.getLogger(__name__) # Define logger for use in models if needed

# Ensure your existing models (ContactList, Contact, EmailTemplate, Campaign, CampaignSendLog, Settings)
# are present in this file. The code below is for the MediaAsset model.

class ContactList(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, help_text="e.g., 'Newsletter Subscribers Q1 2024'")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Contact List"
        verbose_name_plural = "Contact Lists"

class Contact(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    contact_list = models.ForeignKey(
        ContactList, related_name='contacts', on_delete=models.CASCADE, null=True, blank=True,
        help_text="The list this contact was originally imported into, if applicable."
    )
    email = models.EmailField(db_index=True, default='unknown@example.com')
    first_name = models.CharField(max_length=100, blank=True, null=True)
    last_name = models.CharField(max_length=100, blank=True, null=True)
    company = models.CharField(max_length=100, blank=True, null=True)
    job_title = models.CharField(max_length=100, blank=True, null=True)
    custom_fields = models.JSONField(
        blank=True, null=True, help_text="Stores additional columns from CSV not covered by specific fields."
    )
    subscribed = models.BooleanField(default=True, db_index=True, help_text="Indicates if the contact is currently subscribed.")
    unsubscribe_token = models.UUIDField(editable=False, unique=True, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.unsubscribe_token:
            self.unsubscribe_token = uuid.uuid4()
        super().save(*args, **kwargs)

    class Meta:
        ordering = ['email', 'created_at']
        verbose_name = "Contact"
        verbose_name_plural = "Contacts"

    def __str__(self):
        return self.email or f"Contact {self.id}"

class EmailTemplate(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, unique=True, help_text="e.g., 'Welcome Email Template'")
    subject = models.CharField(max_length=255, help_text="Can include merge tags like {{first_name}}.")
    html_content = models.TextField(help_text="HTML content with merge tags like {{first_name}}.")
    footer_html = models.TextField(
        default='<p style="text-align:center; font-size:12px; color:#777;">'
                '{{your_company_name}}<br>'
                '<a href="{{unsubscribe_url}}" style="color:#777; text-decoration:underline;">Unsubscribe</a>'
                '</p>',
        help_text="Footer HTML with merge tags like {{unsubscribe_url}}, {{your_company_name}}."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Email Template"
        verbose_name_plural = "Email Templates"

class Campaign(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('scheduled', 'Scheduled'),
        ('queued', 'Queued'),
        ('sending', 'Sending'),
        ('sent', 'Sent'),
        ('failed', 'Failed'),
        ('archived', 'Archived'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, help_text="e.g., 'April Newsletter Campaign'")
    contact_lists = models.ManyToManyField(
        ContactList, blank=True, related_name="campaigns", help_text="Select one or more contact lists."
    )
    segments = models.ManyToManyField(
        'Segment', blank=True, related_name="campaigns", help_text="Select one or more segments."
    )
    email_template = models.ForeignKey(EmailTemplate, on_delete=models.SET_NULL, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft', db_index=True)
    scheduled_at = models.DateTimeField(null=True, blank=True, help_text="Send time, if scheduled.")
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    total_recipients = models.PositiveIntegerField(default=0)
    successfully_sent = models.PositiveIntegerField(default=0)
    failed_to_send = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.name} ({self.get_status_display()})"

    @property
    def opened_count(self):
        return self.logs.filter(opened_at__isnull=False).values('contact').distinct().count()

    @property
    def clicked_count(self):
        return self.logs.filter(clicked_at__isnull=False).values('contact').distinct().count()

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Campaign"
        verbose_name_plural = "Campaigns"

class CampaignSendLog(models.Model):
    campaign = models.ForeignKey(Campaign, related_name='logs', on_delete=models.CASCADE)
    contact = models.ForeignKey(Contact, on_delete=models.SET_NULL, null=True, blank=True)
    email_address = models.EmailField(help_text="The email address the message was sent to.")
    sent_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=[('success', 'Success'), ('failed', 'Failed')])
    message_id = models.CharField(max_length=255, blank=True, null=True)
    error_message = models.TextField(blank=True, null=True)
    opened_at = models.DateTimeField(null=True, blank=True)
    clicked_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.campaign.name} - {self.email_address} - {self.status}"

    class Meta:
        ordering = ['-sent_at']
        verbose_name = "Campaign Send Log"
        verbose_name_plural = "Campaign Send Logs"

class Settings(models.Model): # This is your AppSettings model
    sender_email = models.EmailField(help_text="Default email address for sending campaigns")
    company_name = models.CharField(max_length=255, help_text="Company name for email signatures and footers")
    company_address = models.TextField(blank=True, null=True, help_text="Physical company address (for CAN-SPAM compliance)")
    site_url = models.URLField(blank=True, null=True, help_text="Main website URL, e.g., https://www.example.com")
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Application Settings ({self.company_name})"

    class Meta:
        verbose_name = "Application Settings"
        verbose_name_plural = "Application Settings"

    def save(self, *args, **kwargs):
        self.pk = 1 # Enforce singleton via primary key
        super(Settings, self).save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, created = cls.objects.get_or_create(pk=1)
        return obj

class MediaAsset(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,  # Now 'settings' is defined from the import at the top
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='media_assets'
    )
    file_name = models.CharField(max_length=255) # Original filename
    file_path_in_storage = models.CharField(max_length=1024, help_text="Path of the file in storage (e.g., user_media/user/file.jpg)")
    file_url = models.URLField(max_length=1024) # Full accessible URL (local media URL or S3 URL)
    file_type = models.CharField(max_length=100, blank=True) # MIME type
    file_size = models.PositiveIntegerField(null=True, blank=True) # In bytes
    uploaded_at = models.DateTimeField(auto_now_add=True)
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.file_name or str(self.id)

    @property
    def short_url(self):
        try:
            return os.path.basename(self.file_url.split('?')[0])
        except: # Catch generic exception if URL parsing fails for any reason
            return self.file_url[:70] + '...' if len(self.file_url) > 70 else self.file_url

    def delete_from_storage(self):
        """Attempts to delete the actual file from storage."""
        if self.file_path_in_storage:
            try:
                from django.core.files.storage import default_storage
                default_storage.delete(self.file_path_in_storage)
                logger.info(f"Successfully deleted {self.file_path_in_storage} from storage.")
                return True
            except Exception as e:
                logger.error(f"Error deleting {self.file_path_in_storage} from storage: {e}")
        return False

    class Meta:
        ordering = ['-uploaded_at']
        verbose_name = "Media Asset"
        verbose_name_plural = "Media Assets"

class Segment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, unique=True, help_text="e.g., 'Active Subscribers'")
    filters = models.JSONField(
        default=dict,
        help_text="Filter criteria, e.g., {'subscribed': true, 'company': 'Example Inc.', 'custom_fields': {'department': 'Sales'}, 'contact_lists': ['uuid1', 'uuid2']}"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Segment"
        verbose_name_plural = "Segments"
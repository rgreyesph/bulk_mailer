# mailer_app/admin.py
from django.contrib import admin
from .models import ContactList, Contact, EmailTemplate, Campaign, CampaignSendLog

@admin.register(ContactList)
class ContactListAdmin(admin.ModelAdmin):
    list_display = ('name', 'created_at', 'updated_at', 'get_contact_count')
    search_fields = ('name',)
    readonly_fields = ('id', 'created_at', 'updated_at')

    def get_contact_count(self, obj):
        return obj.contacts.count()
    get_contact_count.short_description = 'Contacts'

@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ('email', 'first_name', 'last_name', 'contact_list', 'subscribed', 'created_at', 'updated_at')
    list_filter = ('subscribed', 'contact_list', 'created_at', 'updated_at')
    search_fields = ('email', 'first_name', 'last_name', 'company', 'job_title')
    list_editable = ('subscribed',)
    readonly_fields = ('id', 'unsubscribe_token', 'created_at', 'updated_at')
    fieldsets = (
        (None, {
            'fields': ('email', 'first_name', 'last_name', 'subscribed')
        }),
        ('Optional Details', {
            'classes': ('collapse',),
            'fields': ('company', 'job_title', 'contact_list', 'custom_fields'),
        }),
        ('Metadata', {
            'classes': ('collapse',),
            'fields': ('id', 'unsubscribe_token', 'created_at', 'updated_at'),
        }),
    )

@admin.register(EmailTemplate)
class EmailTemplateAdmin(admin.ModelAdmin):
    list_display = ('name', 'subject', 'created_at', 'updated_at')
    search_fields = ('name', 'subject')
    readonly_fields = ('id', 'created_at', 'updated_at')

@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = ('name', 'email_template', 'display_contact_lists', 'status', 'scheduled_at', 'sent_at', 'total_recipients', 'successfully_sent', 'failed_to_send')
    list_filter = ('status', 'email_template', 'contact_lists', 'scheduled_at', 'sent_at') # Changed 'contact_list__name' to 'contact_lists'
    search_fields = ('name', 'email_template__name', 'contact_lists__name')
    filter_horizontal = ('contact_lists',) # Use this for a better ManyToManyField widget
    readonly_fields = ('id', 'created_at', 'updated_at', 'sent_at', 'total_recipients', 'successfully_sent', 'failed_to_send')
    fieldsets = (
        (None, {
            'fields': ('name', 'email_template', 'contact_lists', 'status', 'scheduled_at')
        }),
        ('Statistics', {
            'classes': ('collapse',),
            'fields': ('total_recipients', 'successfully_sent', 'failed_to_send', 'sent_at'),
        }),
        ('Metadata', {
            'classes': ('collapse',),
            'fields': ('id', 'created_at', 'updated_at'),
        }),
    )
    actions = ['queue_selected_campaigns_for_sending']

    def display_contact_lists(self, obj):
        """Creates a string for the admin list display for contact_lists."""
        return ", ".join([cl.name for cl in obj.contact_lists.all()[:3]]) + ("..." if obj.contact_lists.count() > 3 else "")
    display_contact_lists.short_description = 'Contact Lists'

    def queue_selected_campaigns_for_sending(self, request, queryset):
        """
        Admin action to queue selected draft or scheduled campaigns for immediate sending.
        """
        from marketing_emails.tasks import process_campaign_task # Import task
        count = 0
        for campaign in queryset.filter(status__in=['draft', 'scheduled', 'failed']):
            original_status = campaign.status
            campaign.status = 'queued'
            if original_status == 'scheduled':
                campaign.scheduled_at = None # Clear schedule as we are sending now
            campaign.save(update_fields=['status', 'scheduled_at'])
            process_campaign_task.delay(campaign.id)
            count += 1
        self.message_user(request, f"{count} campaigns have been queued for sending.")
    queue_selected_campaigns_for_sending.short_description = "Queue selected campaigns for sending now"


@admin.register(CampaignSendLog)
class CampaignSendLogAdmin(admin.ModelAdmin):
    list_display = ('campaign', 'contact_email_display', 'status', 'sent_at', 'message_id')
    list_filter = ('status', 'campaign__name', 'sent_at')
    search_fields = ('email_address', 'campaign__name', 'message_id', 'error_message')
    readonly_fields = ('campaign', 'contact', 'email_address', 'sent_at', 'status', 'message_id', 'error_message')

    def contact_email_display(self, obj):
        if obj.contact:
            return obj.contact.email
        return obj.email_address # Fallback to the stored email_address
    contact_email_display.short_description = 'Recipient Email'

    def has_add_permission(self, request): # Prevent adding logs manually
        return False

    def has_change_permission(self, request, obj=None): # Prevent changing logs
        return False

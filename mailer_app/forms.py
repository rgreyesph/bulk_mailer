# mailer_app/forms.py
from django import forms
from .models import EmailTemplate, ContactList, Campaign # Removed Contact as it's not directly used in these forms

class CSVImportForm(forms.Form):
    """
    Form for uploading a CSV file of contacts and naming the new list.
    """
    csv_file = forms.FileField(
        label="Upload CSV File",
        help_text="CSV must contain at least an 'email' column. Optional: 'first_name', 'last_name', 'company', 'job_title'. Other columns will be stored as custom fields.",
        widget=forms.ClearableFileInput(attrs={'class': 'block w-full text-sm text-gray-900 border border-gray-300 rounded-lg cursor-pointer bg-gray-50 focus:outline-none p-2'})
    )
    contact_list_name = forms.CharField(
        max_length=255,
        label="Name for this new Contact List",
        help_text="e.g., 'Newsletter Subscribers Q1 2024'",
        widget=forms.TextInput(attrs={'class': 'mt-1 block w-full px-3 py-2 bg-white border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm'})
    )

class EmailTemplateForm(forms.ModelForm):
    """
    Form for creating and editing EmailTemplates.
    """
    class Meta:
        model = EmailTemplate
        fields = ['name', 'subject', 'html_content']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'mt-1 block w-full px-3 py-2 bg-white border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm'}),
            'subject': forms.TextInput(attrs={'class': 'mt-1 block w-full px-3 py-2 bg-white border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm', 'placeholder': 'e.g., Welcome, {{first_name}}!'}),
            'html_content': forms.Textarea(attrs={'class': 'mt-1 block w-full px-3 py-2 bg-white border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm', 'rows': 15, 'placeholder': '<html><body>Your email content with {{first_name}}, {{email}} tags.</body></html>'}),
        }
        help_texts = {
            'html_content': "Use merge tags like {{first_name}}, {{last_name}}, {{email}}. Any other column header from your CSV can also be used as a merge tag, e.g., {{company_name}}.",
            'subject': "Merge tags like {{first_name}} can be used here too."
        }

class CampaignForm(forms.ModelForm):
    """
    Form for creating/configuring a Campaign.
    """
    # Use ModelMultipleChoiceField for ManyToManyField with a more user-friendly widget
    contact_lists = forms.ModelMultipleChoiceField(
        queryset=ContactList.objects.all().order_by('-created_at'),
        widget=forms.CheckboxSelectMultiple, # Allows selecting multiple lists
        label="Target Contact Lists",
        help_text="Select the contact list(s) for this campaign."
    )
    scheduled_at = forms.DateTimeField(
        label="Schedule for (Optional)",
        required=False, # Make it optional
        widget=forms.DateTimeInput(
            attrs={'type': 'datetime-local', 'class': 'mt-1 block w-full px-3 py-2 bg-white border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm'},
            format='%Y-%m-%dT%H:%M'
        ),
        help_text="If you want to send this campaign at a specific future time."
    )

    class Meta:
        model = Campaign
        # Updated fields to match the Campaign model
        fields = ['name', 'contact_lists', 'email_template', 'scheduled_at', 'status']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'mt-1 block w-full px-3 py-2 bg-white border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm'}),
            'email_template': forms.Select(attrs={'class': 'mt-1 block w-full px-3 py-2 bg-white border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm'}),
            'status': forms.Select(attrs={'class': 'mt-1 block w-full px-3 py-2 bg-white border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Querysets for dropdowns
        self.fields['email_template'].queryset = EmailTemplate.objects.all().order_by('-created_at')
        self.fields['email_template'].empty_label = "Select an Email Template"

        # Set input format for scheduled_at to match the widget
        if 'scheduled_at' in self.fields:
            self.fields['scheduled_at'].input_formats = ('%Y-%m-%dT%H:%M',)


class SendTestEmailForm(forms.Form):
    """
    Form for sending a test email.
    """
    test_email_address = forms.EmailField(
        label="Recipient Email Address",
        widget=forms.EmailInput(attrs={'class': 'mt-1 block w-full px-3 py-2 bg-white border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm', 'placeholder': 'test@example.com'})
    )
    email_template = forms.ModelChoiceField(
        queryset=EmailTemplate.objects.all().order_by('-created_at'),
        label="Email Template to Test",
        widget=forms.Select(attrs={'class': 'mt-1 block w-full px-3 py-2 bg-white border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm'})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['email_template'].empty_label = "Select a Template"


from django import forms
from .models import EmailTemplate, ContactList, Campaign, Contact, Settings, Segment

class CSVImportForm(forms.Form):
    csv_file = forms.FileField(
        label="Upload CSV File",
        help_text="CSV must contain at least an 'email' column.",
        widget=forms.ClearableFileInput(attrs={'class': 'block w-full text-sm text-gray-900 border border-gray-300 rounded-lg cursor-pointer bg-gray-50 focus:outline-none p-2'})
    )
    contact_list_name = forms.CharField(
        max_length=255,
        label="Name for this new Contact List",
        help_text="e.g., 'Newsletter Subscribers Q1 2024'",
        widget=forms.TextInput(attrs={'class': 'mt-1 block w-full px-3 py-2 bg-white border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm'})
    )

class EmailTemplateForm(forms.ModelForm):
    class Meta:
        model = EmailTemplate
        fields = ['name', 'subject', 'html_content', 'footer_html']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'mt-1 block w-full px-3 py-2 bg-white border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm'}),
            'subject': forms.TextInput(attrs={'class': 'mt-1 block w-full px-3 py-2 bg-white border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm', 'placeholder': 'e.g., Welcome, {{first_name}}!'}),
            'html_content': forms.Textarea(attrs={'class': 'mt-1 block w-full px-3 py-2 bg-white border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm', 'rows': 15, 'placeholder': 'Your email content with {{first_name}}, {{email}} tags.'}),
            'footer_html': forms.Textarea(attrs={'class': 'mt-1 block w-full px-3 py-2 bg-white border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm', 'rows': 5}),
        }
        help_texts = {
            'html_content': "Use merge tags like {{first_name}}, {{last_name}}, {{email}}. Any other column header from your CSV can also be used as a merge tag, e.g., {{company_name}}.",
            'subject': "Merge tags like {{first_name}} can be used here too.",
            'footer_html': "Footer with merge tags like {{unsubscribe_url}}, {{your_company_name}}. Must include {{unsubscribe_url}} for unsubscribe functionality."
        }

    def clean_footer_html(self):
        footer_html = self.cleaned_data.get('footer_html', '')
        if not footer_html.strip():
            raise forms.ValidationError("Footer HTML cannot be empty.")
        if '{{unsubscribe_url}}' not in footer_html:
            raise forms.ValidationError("Footer must include the {{unsubscribe_url}} merge tag.")
        return footer_html

class CampaignForm(forms.ModelForm):
    contact_lists = forms.ModelMultipleChoiceField(
        queryset=ContactList.objects.all().order_by('-created_at'),
        widget=forms.CheckboxSelectMultiple,
        label="Target Contact Lists",
        help_text="Select contact list(s) for this campaign (optional if using segments).",
        required=False
    )
    segments = forms.ModelMultipleChoiceField(
        queryset=Segment.objects.all().order_by('-created_at'),
        widget=forms.CheckboxSelectMultiple,
        label="Target Segments",
        help_text="Select segment(s) to target (optional).",
        required=False
    )
    scheduled_at = forms.DateTimeField(
        label="Schedule for (Optional)",
        required=False,
        widget=forms.DateTimeInput(
            attrs={'type': 'datetime-local', 'class': 'mt-1 block w-full px-3 py-2 bg-white border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm'},
            format='%Y-%m-%dT%H:%M'
        ),
        help_text="If you want to send this campaign at a specific future time."
    )

    class Meta:
        model = Campaign
        fields = ['name', 'contact_lists', 'segments', 'email_template', 'scheduled_at', 'status']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'mt-1 block w-full px-3 py-2 bg-white border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm'}),
            'email_template': forms.Select(attrs={'class': 'mt-1 block w-full px-3 py-2 bg-white border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm'}),
            'status': forms.Select(attrs={'class': 'mt-1 block w-full px-3 py-2 bg-white border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['email_template'].queryset = EmailTemplate.objects.all().order_by('-created_at')
        self.fields['email_template'].empty_label = "Select an Email Template"
        if 'scheduled_at' in self.fields:
            self.fields['scheduled_at'].input_formats = ('%Y-%m-%dT%H:%M',)

class SendTestEmailForm(forms.Form):
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

class ContactForm(forms.ModelForm):
    class Meta:
        model = Contact
        fields = ['email', 'first_name', 'last_name', 'company', 'job_title', 'subscribed', 'custom_fields']
        widgets = {
            'email': forms.EmailInput(attrs={'class': 'mt-1 block w-full px-3 py-2 bg-white border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm'}),
            'first_name': forms.TextInput(attrs={'class': 'mt-1 block w-full px-3 py-2 bg-white border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm'}),
            'last_name': forms.TextInput(attrs={'class': 'mt-1 block w-full px-3 py-2 bg-white border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm'}),
            'company': forms.TextInput(attrs={'class': 'mt-1 block w-full px-3 py-2 bg-white border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm'}),
            'job_title': forms.TextInput(attrs={'class': 'mt-1 block w-full px-3 py-2 bg-white border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm'}),
            'subscribed': forms.CheckboxInput(attrs={'class': 'h-4 w-4 text-indigo-600 focus:ring-indigo-500 border-gray-300 rounded'}),
            'custom_fields': forms.Textarea(attrs={'class': 'mt-1 block w-full px-3 py-2 bg-white border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm', 'rows': 4, 'placeholder': 'Enter JSON, e.g., {"department": "Sales"}'}),
        }

class SettingsForm(forms.ModelForm):
    class Meta:
        model = Settings
        fields = ['sender_email', 'company_name', 'company_address', 'site_url']
        widgets = {
            'sender_email': forms.EmailInput(attrs={
                'class': 'mt-1 block w-full px-3 py-2 bg-white border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm',
                'placeholder': 'you@example.com'
            }),
            'company_name': forms.TextInput(attrs={
                'class': 'mt-1 block w-full px-3 py-2 bg-white border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm',
                'placeholder': 'Your Company Inc.'
            }),
            'company_address': forms.Textarea(attrs={
                'class': 'mt-1 block w-full px-3 py-2 bg-white border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm',
                'rows': 3,
                'placeholder': '123 Main St, Any City, Philippines'
            }),
            'site_url': forms.URLInput(attrs={
                'class': 'mt-1 block w-full px-3 py-2 bg-white border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm',
                'placeholder': 'https://www.yourcompany.com'
            }),
        }
        help_texts = {
            'sender_email': "The default email address your campaigns will be sent from.",
            'company_name': "The name of your company, used in email footers.",
            'company_address': "Your company's physical mailing address (important for CAN-SPAM compliance).",
            'site_url': "The main URL of your website (e.g., for branding or links)."
        }

class MediaUploadForm(forms.Form):
    media_file = forms.FileField(
        label="Upload Media File",
        help_text="Images, PDFs, etc. Max size: 5MB. Allowed types: jpg, png, gif, pdf.",
        widget=forms.ClearableFileInput(attrs={'class': 'block w-full text-sm text-gray-900 border border-gray-300 rounded-lg cursor-pointer bg-gray-50 focus:outline-none p-2'})
    )

class ContactFilterForm(forms.Form):
    subscribed = forms.ChoiceField(
        choices=[('', 'All'), ('true', 'Subscribed'), ('false', 'Unsubscribed')],
        required=False,
        label='Subscription Status',
        widget=forms.Select(attrs={
            'class': 'mt-1 block w-full px-3 py-2 bg-white border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm'
        })
    )
    company = forms.CharField(
        max_length=100,
        required=False,
        label='Company',
        widget=forms.TextInput(attrs={
            'class': 'mt-1 block w-full px-3 py-2 bg-white border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm',
            'placeholder': 'e.g., Example Inc.'
        })
    )
    custom_field_key = forms.CharField(
        max_length=100,
        required=False,
        label='Custom Field Key',
        widget=forms.TextInput(attrs={
            'class': 'mt-1 block w-full px-3 py-2 bg-white border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm',
            'placeholder': 'e.g., department'
        })
    )
    custom_field_value = forms.CharField(
        max_length=255,
        required=False,
        label='Custom Field Value',
        widget=forms.TextInput(attrs={
            'class': 'mt-1 block w-full px-3 py-2 bg-white border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm',
            'placeholder': 'e.g., Sales'
        })
    )

class SegmentForm(forms.ModelForm):
    subscribed = forms.ChoiceField(
        choices=[('', 'All'), ('true', 'Subscribed'), ('false', 'Unsubscribed')],
        required=False,
        label='Subscription Status',
        widget=forms.Select(attrs={
            'class': 'mt-1 block w-full px-3 py-2 bg-white border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm'
        }),
        help_text="Filter by subscription status (e.g., Subscribed users only)."
    )
    company = forms.CharField(
        max_length=100,
        required=False,
        label='Company',
        widget=forms.TextInput(attrs={
            'class': 'mt-1 block w-full px-3 py-2 bg-white border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm',
            'placeholder': 'e.g., Example Inc.'
        }),
        help_text="Filter by company name (partial matches allowed)."
    )
    custom_field_key = forms.CharField(
        max_length=100,
        required=False,
        label='Custom Field Key',
        widget=forms.TextInput(attrs={
            'class': 'mt-1 block w-full px-3 py-2 bg-white border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm',
            'placeholder': 'e.g., department'
        }),
        help_text="Enter a custom field key (e.g., 'department')."
    )
    custom_field_value = forms.CharField(
        max_length=255,
        required=False,
        label='Custom Field Value',
        widget=forms.TextInput(attrs={
            'class': 'mt-1 block w-full px-3 py-2 bg-white border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm',
            'placeholder': 'e.g., Sales'
        }),
        help_text="Enter the value for the custom field (e.g., 'Sales')."
    )
    contact_lists = forms.ModelMultipleChoiceField(
        queryset=ContactList.objects.all().order_by('-created_at'),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="Contact Lists",
        help_text="Select contact lists to include in this segment."
    )

    class Meta:
        model = Segment
        fields = ['name']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'mt-1 block w-full px-3 py-2 bg-white border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm',
                'placeholder': 'e.g., Active Subscribers'
            })
        }
        help_texts = {
            'name': "Unique name for the segment (e.g., 'Sales Team')."
        }

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.filters = {
            'subscribed': self.cleaned_data['subscribed'],
            'company': self.cleaned_data['company'],
            'custom_fields': {
                self.cleaned_data['custom_field_key']: self.cleaned_data['custom_field_value']
            } if self.cleaned_data['custom_field_key'] and self.cleaned_data['custom_field_value'] else {},
            'contact_lists': [str(cl.id) for cl in self.cleaned_data['contact_lists']]
        }
        if commit:
            instance.save()
        return instance
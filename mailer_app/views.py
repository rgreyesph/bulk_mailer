# mailer_app/views.py
import csv
import io
import uuid # Import uuid for token generation
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse, Http404 
from django.contrib import messages
from django.core.mail import send_mail, BadHeaderError
from django.template import Context, Template as DjangoTemplate, TemplateSyntaxError
from django.conf import settings
from django.utils.html import strip_tags, escape
from django.utils import timezone
from django.db.models import Count, F
from django.views.decorators.clickjacking import xframe_options_sameorigin # <<< IMPORT ADDED HERE

from .models import Contact, ContactList, EmailTemplate, Campaign, CampaignSendLog
from .forms import CSVImportForm, EmailTemplateForm, CampaignForm, SendTestEmailForm

from django.urls import reverse 
from django.contrib.sites.models import Site 

import logging
logger = logging.getLogger(__name__)

# --- Helper Functions ---
def _render_email_content(template_html, context_data):
    """Renders email HTML content with given context data."""
    django_tpl = DjangoTemplate(template_html)
    context = Context(context_data)
    return django_tpl.render(context)

def _get_sample_context(contact_list_instance=None):
    """Provides sample context data for previews. Includes new fields."""
    sample_data = {
        "email": "john.doe@example.com",
        "first_name": "John",
        "last_name": "Doe",
        "company": "Example Inc.",
        "job_title": "Chief Tester",
        "unsubscribe_url": "#", # Placeholder for unsubscribe URL in previews
        "custom_field_example": "Sample Custom Value",
        "your_company_name": getattr(settings, 'YOUR_COMPANY_NAME', "Your Company")
    }
    if contact_list_instance:
        first_contact = contact_list_instance.contacts.all().first()
        if first_contact:
            sample_data["email"] = first_contact.email or sample_data["email"]
            sample_data["first_name"] = first_contact.first_name or sample_data["first_name"]
            sample_data["last_name"] = first_contact.last_name or sample_data["last_name"]
            sample_data["company"] = first_contact.company or sample_data["company"]
            sample_data["job_title"] = first_contact.job_title or sample_data["job_title"]
            if first_contact.custom_fields:
                for key, value in first_contact.custom_fields.items():
                    if key not in ["email", "first_name", "last_name", "company", "job_title"]:
                        sample_data[key] = value or f"Sample {key.replace('_', ' ').title()}"
    return sample_data


# --- Dashboard ---
def dashboard(request):
    contact_lists_qs = ContactList.objects.all().order_by('-created_at')[:5]
    email_templates_qs = EmailTemplate.objects.all().order_by('-created_at')[:5]
    campaigns_qs = Campaign.objects.all().order_by('-created_at')[:5]
    context = {
        'contact_lists': contact_lists_qs,
        'email_templates': email_templates_qs,
        'campaigns': campaigns_qs,
        'title': "Dashboard",
        'settings_module': settings, # Pass settings module if needed in template for some reason
    }
    return render(request, 'mailer_app/dashboard.html', context)

# --- Contact List Management ---
def manage_contact_lists(request):
    contact_lists_qs = ContactList.objects.all().order_by('-created_at')
    if request.method == 'POST':
        form = CSVImportForm(request.POST, request.FILES)
        if form.is_valid():
            csv_file = request.FILES['csv_file']
            list_name = form.cleaned_data['contact_list_name']

            if not csv_file.name.endswith('.csv'):
                messages.error(request, 'Invalid file type. Please upload a CSV file.')
                return redirect('mailer_app:manage_contact_lists') # Use namespaced redirect

            new_contact_list = None # Initialize to ensure it's defined
            try:
                new_contact_list = ContactList.objects.create(name=list_name)
                decoded_file = csv_file.read().decode('utf-8-sig')
                io_string = io.StringIO(decoded_file)

                # Get original fieldnames robustly
                temp_reader_for_headers = csv.reader(io.StringIO(decoded_file))
                try:
                    original_fieldnames = [h.strip() for h in next(temp_reader_for_headers)]
                    if not original_fieldnames: # Handle case where header row is empty
                        raise StopIteration 
                except StopIteration:
                    if new_contact_list and new_contact_list.pk: new_contact_list.delete()
                    messages.error(request, "CSV file appears to be empty or has no header row.")
                    return redirect('mailer_app:manage_contact_lists')
                del temp_reader_for_headers
                io_string.seek(0) # Reset for DictReader
                
                # Provide fieldnames to DictReader to handle various CSV quirks
                reader = csv.DictReader(io_string, fieldnames=[h.strip() for h in original_fieldnames])
                
                # Normalize headers from the original fieldnames for checking 'email'
                normalized_original_headers = [h.lower().replace(' ', '_').strip() for h in original_fieldnames]
                if 'email' not in normalized_original_headers:
                    if new_contact_list and new_contact_list.pk: new_contact_list.delete()
                    messages.error(request, "CSV file must contain an 'email' column header.")
                    return redirect('mailer_app:manage_contact_lists')

                contacts_to_create = []
                
                first_row = True # To help with skipping header if DictReader didn't
                for row_data in reader:
                    # This check is a bit fragile; relies on DictReader behavior with provided fieldnames
                    if first_row and all(row_data.get(h.strip()) == h.strip() for h in original_fieldnames):
                        first_row = False
                        continue 
                    first_row = False


                    normalized_row = {} # Process current row
                    for original_header, value in row_data.items():
                        # Ensure original_header is a string before calling lower(), replace(), strip()
                        if isinstance(original_header, str):
                            normalized_key = original_header.lower().replace(' ', '_').strip()
                            normalized_row[normalized_key] = value.strip() if value else ''
                        else:
                            # Handle case where a header might not be a string (e.g. None if CSV is malformed)
                            # Or log a warning, skip this header, etc.
                            logger.warning(f"Skipping non-string header in CSV: {original_header}")


                    email = normalized_row.get('email', '').strip()
                    if not email:
                        # messages.warning(request, f"Skipped CSV row due to missing email.") # Avoid too many messages
                        continue
                    
                    # Generate unsubscribe_token before adding to bulk_create list
                    unsubscribe_token = uuid.uuid4()

                    contacts_to_create.append(Contact(
                        contact_list=new_contact_list, email=email,
                        first_name=normalized_row.get('first_name', ''),
                        last_name=normalized_row.get('last_name', ''),
                        company=normalized_row.get('company', ''),
                        job_title=normalized_row.get('job_title', ''),
                        custom_fields={k:v for k,v in normalized_row.items() if k not in ['email','first_name','last_name','company','job_title'] and v},
                        subscribed=True,
                        unsubscribe_token=unsubscribe_token # Assign generated token
                    ))
                if contacts_to_create:
                    Contact.objects.bulk_create(contacts_to_create)
                    messages.success(request, f'{len(contacts_to_create)} contacts imported to "{list_name}".')
                else:
                    messages.warning(request, f"No new contacts imported to '{list_name}'.")
                return redirect('mailer_app:manage_contact_lists')
            except Exception as e:
                if new_contact_list and new_contact_list.pk: new_contact_list.delete()
                messages.error(request, f'Error processing CSV: {e}.')
                return redirect('mailer_app:manage_contact_lists')
    else:
        form = CSVImportForm()

    return render(request, 'mailer_app/contact_list_form.html', {
        'form': form, 'contact_lists': contact_lists_qs, 'title': "Manage Contact Lists"
    })

def view_contact_list(request, list_id):
    contact_list_obj = get_object_or_404(ContactList, id=list_id)
    contacts_qs = contact_list_obj.contacts.all()
    return render(request, 'mailer_app/view_contact_list.html', {
        'contact_list': contact_list_obj, 'contacts': contacts_qs, 'title': f"View List: {contact_list_obj.name}"
    })

def delete_contact_list(request, list_id):
    contact_list_obj = get_object_or_404(ContactList, id=list_id)
    if request.method == 'POST':
        list_name = contact_list_obj.name
        contact_list_obj.delete()
        messages.success(request, f"Contact list '{list_name}' deleted.")
        return redirect('mailer_app:manage_contact_lists')
    messages.warning(request, "Deletion must be confirmed via POST.")
    return redirect('mailer_app:manage_contact_lists')

def manage_email_templates(request):
    templates_qs = EmailTemplate.objects.all().order_by('-created_at')
    if request.method == 'POST':
        form = EmailTemplateForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Email template created.')
            return redirect('mailer_app:manage_email_templates')
        else:
            messages.error(request, "Could not create template. Errors below.")
    else:
        form = EmailTemplateForm()
    return render(request, 'mailer_app/email_template_form.html', {
        'form': form, 'templates': templates_qs,
        'title': "Manage Email Templates", 'form_title': "Create New Template"
    })

def edit_email_template(request, template_id):
    template_instance = get_object_or_404(EmailTemplate, id=template_id)
    templates_qs = EmailTemplate.objects.all().order_by('-created_at')
    if request.method == 'POST':
        form = EmailTemplateForm(request.POST, instance=template_instance)
        if form.is_valid():
            form.save()
            messages.success(request, f"Template '{template_instance.name}' updated.")
            return redirect('mailer_app:manage_email_templates')
        else:
            messages.error(request, f"Could not update '{template_instance.name}'. Errors below.")
    else:
        form = EmailTemplateForm(instance=template_instance)
    return render(request, 'mailer_app/email_template_form.html', {
        'form': form, 'templates': templates_qs, 'instance': template_instance,
        'title': f"Edit: {template_instance.name}", 'form_title': f"Edit: {template_instance.name}"
    })

def delete_email_template(request, template_id):
    template_obj = get_object_or_404(EmailTemplate, id=template_id)
    if request.method == 'POST':
        template_name = template_obj.name
        template_obj.delete()
        messages.success(request, f"Template '{template_name}' deleted.")
        return redirect('mailer_app:manage_email_templates')
    messages.warning(request, "Deletion must be confirmed via POST.")
    return redirect('mailer_app:manage_email_templates')

def preview_email_template_page(request, template_id):
    template_instance = get_object_or_404(EmailTemplate, id=template_id)
    sample_context = _get_sample_context(contact_list_instance=None)
    try:
        rendered_subject = _render_email_content(template_instance.subject, sample_context)
    except TemplateSyntaxError as e:
        rendered_subject = f"Error rendering subject: {escape(str(e))}"
        messages.warning(request, f"Subject has a syntax error: {escape(str(e))}")
        
    return render(request, 'mailer_app/preview_email.html', { # Assuming preview_email.html is in mailer_app/templates/mailer_app/
        'template': template_instance, 'rendered_subject': rendered_subject,
        'title': f"Preview: {template_instance.name}"
    })

@xframe_options_sameorigin 
def get_rendered_email_content(request, template_id):
    template_instance = get_object_or_404(EmailTemplate, id=template_id)
    contact_list_id = request.GET.get('contact_list_id')
    contact_list_for_sample = None
    if contact_list_id:
        contact_list_for_sample = ContactList.objects.filter(id=contact_list_id).first()
    
    sample_context = _get_sample_context(contact_list_instance=contact_list_for_sample)
    sample_context.setdefault('unsubscribe_url', '#') 
    sample_context.setdefault('your_company_name', getattr(settings, 'YOUR_COMPANY_NAME', "Your Company"))

    try:
        rendered_html = _render_email_content(template_instance.html_content, sample_context)
        return HttpResponse(rendered_html)
    except TemplateSyntaxError as e:
        logger.error(f"TemplateSyntaxError rendering template {template_id} for preview: {e}", exc_info=True)
        error_html = f"""
        <div style="font-family: sans-serif; padding: 20px; border: 2px solid red; background-color: #ffe0e0;">
            <h3 style="color: red;">Template Rendering Error</h3>
            <p>There is a syntax error in your email template's HTML content:</p>
            <pre style="background-color: #f0f0f0; padding: 10px; border-radius: 5px; white-space: pre-wrap; word-wrap: break-word;">{escape(str(e))}</pre>
            <p>Please check your template for issues like unclosed tags (e.g., <code>{{% if %}}</code> without <code>{{% endif %}}</code>) or incorrect variable names (e.g., <code>{{{{ variable }}}}</code> instead of <code>{{{{ variable }}}}</code>).</p>
        </div>
        """
        return HttpResponse(error_html, status=200) # Return 200 so iframe displays the error, not a browser error page
    except Exception as e:
        logger.error(f"Unexpected error rendering template {template_id} for preview: {e}", exc_info=True)
        return HttpResponse(f"<p style='color:red; font-family:sans-serif; padding:20px;'>An unexpected error occurred while rendering the template: {escape(str(e))}</p>", status=200)


def manage_campaigns(request):
    campaigns_qs = Campaign.objects.all().order_by('-created_at')
    if request.method == 'POST':
        form = CampaignForm(request.POST)
        if form.is_valid():
            campaign = form.save(commit=False)
            # Status is now part of the form, so it will be in form.cleaned_data
            # campaign.status = form.cleaned_data.get('status', 'draft') # Default to draft if not in form
            campaign.save() # Save the main campaign object
            form.save_m2m() # Save ManyToMany relationships (like contact_lists)

            # Recalculate total_recipients after M2M is saved
            if campaign.contact_lists.exists():
                campaign.total_recipients = Contact.objects.filter(
                    contact_list__in=campaign.contact_lists.all(),
                    subscribed=True, email__isnull=False
                ).exclude(email__exact='').distinct().count()
            else:
                campaign.total_recipients = 0
            # Save again with updated count and potentially status from form
            campaign.save(update_fields=['total_recipients']) 

            messages.success(request, f"Campaign '{campaign.name}' saved as {campaign.get_status_display()}.")
            return redirect('mailer_app:view_campaign', campaign_id=campaign.id)
        else: 
            error_list = []
            for field, errors in form.errors.items():
                field_label = form.fields.get(field).label if form.fields.get(field) and hasattr(form.fields.get(field), 'label') else field
                error_list.append(f"{field_label}: {', '.join(errors)}")
            error_string = "Could not save campaign. Please correct the errors: " + "; ".join(error_list)
            messages.error(request, error_string)
    else: 
        form = CampaignForm()
    return render(request, 'mailer_app/campaign_form.html', {
        'form': form, 'campaigns': campaigns_qs,
        'title': "Manage Campaigns", 'form_title': "Create/Edit Campaign"
    })

def view_campaign(request, campaign_id):
    campaign_obj = get_object_or_404(Campaign, id=campaign_id)
    test_email_form = SendTestEmailForm(initial={'email_template': campaign_obj.email_template})
    merge_tags = ["{{email}}", "{{first_name}}", "{{last_name}}", "{{company}}", "{{job_title}}", "{{unsubscribe_url}}", "{{your_company_name}}"]
    first_contact_list = campaign_obj.contact_lists.all().first()
    if first_contact_list:
        sample_contact_with_custom = first_contact_list.contacts.filter(custom_fields__isnull=False).first()
        if sample_contact_with_custom and sample_contact_with_custom.custom_fields:
            merge_tags.extend([f"{{{{{key}}}}}" for key in sample_contact_with_custom.custom_fields.keys()])
    context = {
        'campaign': campaign_obj, 'test_email_form': test_email_form,
        'title': f"Campaign: {campaign_obj.name}",
        'available_merge_tags': sorted(list(set(merge_tags)))
    }
    return render(request, 'mailer_app/view_campaign_detail.html', context)

def send_test_email_view(request, campaign_id):
    campaign_obj = get_object_or_404(Campaign, id=campaign_id)
    if not campaign_obj.email_template:
        messages.error(request, "Campaign has no email template.")
        return redirect('mailer_app:view_campaign', campaign_id=campaign_obj.id)

    if request.method == 'POST':
        form = SendTestEmailForm(request.POST)
        if form.is_valid():
            test_email = form.cleaned_data['test_email_address']
            template_to_use = form.cleaned_data['email_template']
            first_contact_list_for_sample = campaign_obj.contact_lists.all().first()
            sample_context = _get_sample_context(contact_list_instance=first_contact_list_for_sample)
            sample_context.setdefault('unsubscribe_url', "https://example.com/test-unsubscribe-link") # Placeholder for test
            sample_context.setdefault('your_company_name', getattr(settings, 'YOUR_COMPANY_NAME', "Your Company"))
            subject = _render_email_content(template_to_use.subject, sample_context)
            html_body = _render_email_content(template_to_use.html_content, sample_context)
            plain_body = strip_tags(html_body)
            try:
                send_mail(
                    subject=subject, message=plain_body,
                    from_email=settings.AWS_SES_SENDER_EMAIL, # CORRECTED
                    recipient_list=[test_email],
                    html_message=html_body, fail_silently=False,
                )
                messages.success(request, f"Test email sent to {test_email} using '{template_to_use.name}'.")
            except Exception as e:
                messages.error(request, f"Error sending test email: {e}")
        else:
            error_messages = [f"{form.fields.get(f).label if form.fields.get(f) and f != '__all__' else ''}: {e}" for f, errs in form.errors.items() for e in errs]
            messages.error(request, "Test email not sent. Errors: " + "; ".join(error_messages))
    return redirect('mailer_app:view_campaign', campaign_id=campaign_obj.id)

def execute_send_campaign(request, campaign_id):
    campaign_obj = get_object_or_404(Campaign, id=campaign_id)
    if campaign_obj.status in ['sending', 'sent', 'queued']:
        messages.warning(request, f"Campaign '{campaign_obj.name}' is {campaign_obj.status}.")
        return redirect('mailer_app:view_campaign', campaign_id=campaign_obj.id)

    if not campaign_obj.contact_lists.exists() or not campaign_obj.email_template:
        messages.error(request, "Campaign needs contact list(s) and a template.")
        return redirect('mailer_app:view_campaign', campaign_id=campaign_obj.id)

    from marketing_emails.tasks import process_campaign_task # Import your Celery task
    
    campaign_obj.status = 'queued' 
    campaign_obj.total_recipients = Contact.objects.filter(
        contact_list__in=campaign_obj.contact_lists.all(),
        subscribed=True, email__isnull=False
    ).exclude(email__exact='').distinct().count()
    campaign_obj.successfully_sent = 0 
    campaign_obj.failed_to_send = 0   
    
    if campaign_obj.total_recipients == 0:
        messages.warning(request, "No valid subscribed contacts in selected list(s).")
        campaign_obj.status = 'failed' 
        campaign_obj.save(update_fields=['status', 'total_recipients', 'successfully_sent', 'failed_to_send'])
        return redirect('mailer_app:view_campaign', campaign_id=campaign_obj.id)

    campaign_obj.save(update_fields=['status', 'total_recipients', 'successfully_sent', 'failed_to_send'])
    
    process_campaign_task.delay(campaign_obj.id)
    
    messages.success(request, f"Campaign '{campaign_obj.name}' queued for sending.")
    return redirect('mailer_app:view_campaign', campaign_id=campaign_obj.id)

# --- Unsubscribe View ---
# This view is now correctly placed here as per your views.py structure.
# Ensure its URL is defined in mailer_app/urls.py

# from django.urls import reverse # Already imported at top
# from django.contrib.sites.models import Site # Already imported at top

def unsubscribe_contact_view(request, token): 
    """
    Handles unsubscribe requests.
    Finds the contact by their unique unsubscribe token and updates their status.
    """
    try:
        # Ensure token is a valid UUID before querying to prevent DB errors on malformed tokens
        # uuid.UUID(str(token)) # This would raise ValueError if token is not a valid UUID string
        contact_obj = get_object_or_404(Contact, unsubscribe_token=token)
    except Http404: # Catch if token not found
        messages.error(request, "Invalid unsubscribe link. Link may have expired or is incorrect.")
        return render(request, 'mailer_app/unsubscribe_confirmation.html', {'success': False, 'message': "Invalid unsubscribe link."}) # Adjusted path
    except ValueError: # Catch if token is not a valid UUID format
        messages.error(request, "Malformed unsubscribe link.")
        return render(request, 'mailer_app/unsubscribe_confirmation.html', {'success': False, 'message': "Malformed unsubscribe link."}) # Adjusted path

    if request.method == 'POST':
        if contact_obj.subscribed:
            contact_obj.subscribed = False
            contact_obj.save(update_fields=['subscribed', 'updated_at'])
            # REFINED SUCCESS MESSAGE
            success_message = f"The email address <strong>{contact_obj.email}</strong> has been successfully unsubscribed from our mailing list."
            messages.success(request, success_message, extra_tags='safe') # Using safe if message contains HTML
            return render(request, 'mailer_app/unsubscribe_confirmation.html', {
                'success': True, 
                'confirmation_message': success_message # Pass the message directly
            })
        else:
            # REFINED ALREADY UNSUBSCRIBED MESSAGE
            info_message = f"The email address <strong>{contact_obj.email}</strong> is already unsubscribed."
            messages.info(request, info_message, extra_tags='safe')
            return render(request, 'mailer_app/unsubscribe_confirmation.html', {
                'success': None, # Indicates "already done" status
                'confirmation_message': info_message
            })
    '''
    if request.method == 'POST':
        if contact_obj.subscribed:
            contact_obj.subscribed = False
            contact_obj.save(update_fields=['subscribed', 'updated_at'])
            messages.success(request, f"You have been successfully unsubscribed from {contact_obj.email}.")
            return render(request, 'mailer_app/unsubscribe_confirmation.html', {'success': True, 'email': contact_obj.email}) # Adjusted path
        else:
            messages.info(request, f"{contact_obj.email} is already unsubscribed.")
            return render(request, 'mailer_app/unsubscribe_confirmation.html', {'success': None, 'message': "You are already unsubscribed.", 'email': contact_obj.email}) # Adjusted path

    # For GET request, show the confirmation page
    # Ensure this template path is correct for mailer_app
    '''
    return render(request, 'mailer_app/unsubscribe_page.html', {'contact': contact_obj, 'token': token}) # Adjusted path

def keep_subscribed_thank_you_view(request):
    """
    A simple view to thank the user for choosing to stay subscribed.
    """
    messages.success(request, "Thank you for staying subscribed! We appreciate having you with us.")
    # You can also pass specific context if needed for the thank you page
    return render(request, 'mailer_app/keep_subscribed_thank_you.html', {'title': "Subscription Confirmed"})

# mailer_app/views.py
import csv
import io
import uuid
import os
import logging

from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, Http404
from django.contrib import messages
from django.core.mail import send_mail
from django.template import Context, Template as DjangoTemplate, TemplateSyntaxError
from django.conf import settings as django_settings
from django.utils.html import strip_tags, escape
from django.utils import timezone
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.contrib.auth.decorators import login_required
from django.urls import reverse
from django.contrib.sites.shortcuts import get_current_site
from django.core.files.storage import default_storage
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger

from .models import (
    Contact, ContactList, EmailTemplate, Campaign, CampaignSendLog,
    Settings as AppSettings, MediaAsset, Segment
)
from .forms import (
    CSVImportForm, EmailTemplateForm, CampaignForm, SendTestEmailForm,
    ContactForm, SettingsForm, MediaUploadForm, ContactFilterForm, SegmentForm
)
from bs4 import BeautifulSoup
logger = logging.getLogger(__name__)

# Helper Functions
def _render_email_content(template_html, context_data):
    django_tpl = DjangoTemplate(template_html)
    context = Context(context_data)
    return django_tpl.render(context)

def _get_sample_context(request, contact_list_instance=None):
    settings_obj = AppSettings.load()
    company_name_from_settings = settings_obj.company_name if settings_obj else "Your Company"
    company_address_from_settings = settings_obj.company_address if settings_obj else "123 Main St, Anytown"
    site_url_from_settings = settings_obj.site_url if settings_obj else f"{request.scheme}://{request.get_host()}"

    dummy_token = uuid.uuid4()
    protocol = request.scheme
    domain = request.get_host()

    try:
        path = reverse('mailer_app:unsubscribe_contact', kwargs={'token': str(dummy_token)})
        unsubscribe_url_for_sample = f"{protocol}://{domain}{path}"
    except Exception as e:
        logger.error(f"Error generating unsubscribe URL: {e}", exc_info=True)
        unsubscribe_url_for_sample = f"{protocol}://{domain}/unsubscribe/sample/{dummy_token}/"

    sample_data = {
        "email": "john.doe@example.com", "first_name": "John", "last_name": "Doe",
        "company": "Example Inc.", "job_title": "Chief Tester",
        "unsubscribe_url": unsubscribe_url_for_sample,
        "custom_field_example": "Sample Custom Value",
        "your_company_name": company_name_from_settings,
        "company_address": company_address_from_settings,
        "site_url": site_url_from_settings,
        "tracking_pixel": "#"
    }
    if contact_list_instance:
        first_contact = contact_list_instance.contacts.all().first()
        if first_contact:
            sample_data.update({
                "email": first_contact.email or sample_data["email"],
                "first_name": first_contact.first_name or sample_data["first_name"],
                "last_name": first_contact.last_name or sample_data["last_name"],
                "company": first_contact.company or sample_data["company"],
                "job_title": first_contact.job_title or sample_data["job_title"],
            })
            if first_contact.custom_fields:
                for key, value in first_contact.custom_fields.items():
                    if key not in sample_data:
                        sample_data[key] = value or f"Sample {key.replace('_', ' ').title()}"
    return sample_data


# --- Dashboard ---
@login_required
def dashboard(request):
    contact_lists_qs = ContactList.objects.all().order_by('-created_at')[:5]
    email_templates_qs = EmailTemplate.objects.all().order_by('-created_at')[:5]
    campaigns_qs = Campaign.objects.all().order_by('-created_at')[:5]
    total_contact_lists = ContactList.objects.count()
    total_email_templates = EmailTemplate.objects.count()
    total_campaigns = Campaign.objects.count()
    context = {
        'contact_lists': contact_lists_qs, 'email_templates': email_templates_qs,
        'campaigns': campaigns_qs, 'total_contact_lists': total_contact_lists,
        'total_email_templates': total_email_templates, 'total_campaigns': total_campaigns,
        'title': "Dashboard",
    }
    return render(request, 'mailer_app/dashboard.html', context)

# --- Contact Lists & Contacts ---
@login_required
def manage_contact_lists(request):
    # This view remains unchanged by the current sorting feature for individual contact lists.
    # Its existing logic for listing ContactList objects and CSV import is preserved.
    contact_lists_qs = ContactList.objects.all().order_by('-created_at')
    if request.method == 'POST':
        form = CSVImportForm(request.POST, request.FILES)
        if 'map_fields_submit' in request.POST:
            list_name = request.POST.get('contact_list_name')
            csv_file_content_str = request.POST.get('csv_file_content')

            if not list_name or not csv_file_content_str:
                messages.error(request, "Missing list name or CSV data. Please start over.")
                return redirect('mailer_app:manage_contact_lists')

            io_string = io.StringIO(csv_file_content_str)
            reader = csv.reader(io_string)
            headers = next(reader, None)
            io_string.seek(0) 
            dict_reader = csv.DictReader(io_string)

            new_contact_list, created = ContactList.objects.get_or_create(name=list_name)
            if not created:
                messages.info(request, f"Adding contacts to existing list: '{list_name}'.")
            
            contacts_to_create = []
            contacts_updated_count = 0 # Not currently used for update, but for potential future logic
            contacts_skipped_email_missing = 0
            contacts_skipped_duplicate = 0
            
            field_mappings = {h: request.POST.get(f'map_{h}', 'ignore') for h in headers}
            
            email_header_key = None
            for header, mapped_field in field_mappings.items():
                if mapped_field == 'email':
                    email_header_key = header
                    break
            
            if not email_header_key:
                messages.error(request, "No CSV column was mapped to 'Email Address'. Cannot import.")
                # Consider re-rendering csv_mapping.html with an error message
                # For now, redirecting to the main list management page.
                return redirect('mailer_app:manage_contact_lists')


            for row_index, row in enumerate(dict_reader):
                contact_data = {'contact_list': new_contact_list, 'subscribed': True}
                custom_fields_dict = {}
                email_val = row.get(email_header_key, '').strip()
                
                # Basic email validation could be added here if desired (e.g., using Django's EmailValidator)
                if not email_val: 
                    contacts_skipped_email_missing += 1
                    continue
                contact_data['email'] = email_val

                for header, mapped_field_key in field_mappings.items():
                    if header == email_header_key or mapped_field_key == 'ignore': # Email already handled or field ignored
                        continue
                    original_value = row.get(header, '').strip()
                    if not original_value: # Skip empty values for other fields
                        continue

                    if mapped_field_key in ['first_name', 'last_name', 'company', 'job_title']:
                        contact_data[mapped_field_key] = original_value
                    elif mapped_field_key == 'custom_field':
                        # Sanitize custom field key from header
                        custom_field_name = header.lower().replace(' ', '_').replace('-', '_')
                        # Basic sanitization, ensure it's a valid identifier-like string
                        custom_field_name = ''.join(c if c.isalnum() or c == '_' else '' for c in custom_field_name)
                        if custom_field_name: # Ensure key is not empty after sanitization
                            custom_fields_dict[custom_field_name] = original_value
                
                if custom_fields_dict:
                    contact_data['custom_fields'] = custom_fields_dict

                # Check for existing contact by email in this list to avoid duplicates
                existing_contact = Contact.objects.filter(email=email_val, contact_list=new_contact_list).first()
                if existing_contact:
                    contacts_skipped_duplicate += 1
                    continue # Skip creating a duplicate contact in the same list
                
                contacts_to_create.append(Contact(**contact_data))

            if contacts_to_create:
                Contact.objects.bulk_create(contacts_to_create, ignore_conflicts=False) # ignore_conflicts=False to raise error on DB level if unique constraints violated

            msg_parts = [f'{len(contacts_to_create)} new contacts imported to "{list_name}".']
            if contacts_skipped_email_missing > 0: msg_parts.append(f"{contacts_skipped_email_missing} rows skipped (missing/invalid email).")
            if contacts_skipped_duplicate > 0: msg_parts.append(f"{contacts_skipped_duplicate} skipped (duplicate email in this list).")
            messages.success(request, " ".join(msg_parts))
            return redirect('mailer_app:view_contact_list', list_id=new_contact_list.id)

        elif form.is_valid(): # Initial CSV upload, show mapping form
            csv_file_uploaded = request.FILES['csv_file']
            list_name = form.cleaned_data['contact_list_name']

            if not csv_file_uploaded.name.endswith('.csv'):
                messages.error(request, 'Please upload a valid CSV file.')
                return redirect('mailer_app:manage_contact_lists')
            try:
                decoded_file = csv_file_uploaded.read().decode('utf-8-sig')
            except UnicodeDecodeError:
                messages.error(request, "Could not decode CSV file. Please ensure it's UTF-8 encoded.")
                return redirect('mailer_app:manage_contact_lists')

            io_string = io.StringIO(decoded_file)
            reader = csv.reader(io_string)
            headers = next(reader, None)

            if not headers:
                messages.error(request, "CSV file is empty or has no headers.")
                return redirect('mailer_app:manage_contact_lists')
            
            return render(request, 'mailer_app/csv_mapping.html', {
                'form': form, # Pass the original form to pre-fill list_name and keep file info if needed
                'list_name': list_name,
                'csv_headers': headers,
                'csv_file_content': decoded_file, # Pass content for the mapping step
                'title': "Map CSV Fields"
            })
        else: 
            # Form is invalid (e.g., no file uploaded, or list name missing)
            # Errors will be displayed by the form rendering in the template
            pass # Let it fall through to render the form with errors
    else: # GET request
        form = CSVImportForm()

    return render(request, 'mailer_app/contact_list_form.html', {
        'form': form, 
        'contact_lists': contact_lists_qs, 
        'title': "Manage Contact Lists"
    })


@login_required
def view_contact_list(request, list_id):
    contact_list_obj = get_object_or_404(ContactList, id=list_id)
    logger.info(f"Viewing contact list ID: {list_id}, Name: {contact_list_obj.name}")

    # --- Sorting Logic ---
    allowed_sort_fields = ['email', 'first_name', 'last_name', 'subscribed', 'created_at']
    sort_by_param = request.GET.get('sort_by', 'email')
    order_param = request.GET.get('order', 'asc')

    if sort_by_param not in allowed_sort_fields:
        sort_by = 'email'
        logger.warning(f"Invalid sort_by parameter '{sort_by_param}', defaulting to 'email'.")
    else:
        sort_by = sort_by_param

    if order_param not in ['asc', 'desc']:
        order = 'asc'
        logger.warning(f"Invalid order parameter '{order_param}', defaulting to 'asc'.")
    else:
        order = order_param

    order_prefix = '' if order == 'asc' else '-'
    order_by_field = f"{order_prefix}{sort_by}"

    # --- Filtering Logic ---
    filter_form = ContactFilterForm(request.GET)
    contacts_qs = contact_list_obj.contacts.all()

    if filter_form.is_valid():
        if filter_form.cleaned_data['subscribed']:
            subscribed = filter_form.cleaned_data['subscribed'] == 'true'
            contacts_qs = contacts_qs.filter(subscribed=subscribed)
        if filter_form.cleaned_data['company']:
            contacts_qs = contacts_qs.filter(company__icontains=filter_form.cleaned_data['company'])
        if filter_form.cleaned_data['custom_field_key'] and filter_form.cleaned_data['custom_field_value']:
            key = filter_form.cleaned_data['custom_field_key']
            value = filter_form.cleaned_data['custom_field_value']
            contacts_qs = contacts_qs.filter(custom_fields__has_key=key, custom_fields__contains={key: value})

    contacts_qs = contacts_qs.order_by(order_by_field)

    # --- Pagination ---
    pre_pagination_count = contacts_qs.count()
    logger.info(f"Found {pre_pagination_count} contacts for list {list_id} before pagination (sorted by {order_by_field}).")

    paginator = Paginator(contacts_qs, 25)
    page_number = request.GET.get('page')
    logger.info(f"Requested page number: {page_number}")

    try:
        contacts_page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        contacts_page_obj = paginator.page(1)
    except EmptyPage:
        contacts_page_obj = paginator.page(paginator.num_pages)

    logger.info(f"Serving page {contacts_page_obj.number} with {len(contacts_page_obj.object_list)} contacts. Total pages: {paginator.num_pages}.")

    context = {
        'contact_list': contact_list_obj,
        'contacts_page_obj': contacts_page_obj,
        'filter_form': filter_form,
        'current_sort_by': sort_by,
        'current_order': order,
        'title': f"View List: {contact_list_obj.name}"
    }
    return render(request, 'mailer_app/view_contact_list.html', context)

@login_required
def delete_contact_list(request, list_id):
    contact_list_obj = get_object_or_404(ContactList, id=list_id)
    if request.method == 'POST':
        list_name = contact_list_obj.name
        contact_list_obj.delete()
        messages.success(request, f"Contact list '{list_name}' and all its contacts deleted.")
        return redirect('mailer_app:manage_contact_lists')
    messages.warning(request, "Deletion must be confirmed via POST.")
    return redirect('mailer_app:manage_contact_lists')

@login_required
def add_contact(request, list_id):
    contact_list = get_object_or_404(ContactList, id=list_id)
    if request.method == 'POST':
        form = ContactForm(request.POST)
        if form.is_valid():
            contact = form.save(commit=False)
            contact.contact_list = contact_list
            try:
                contact.save()
                messages.success(request, f"Contact {contact.email} added to {contact_list.name}.")
                return redirect('mailer_app:view_contact_list', list_id=list_id)
            except Exception as e: 
                messages.error(request, f"Could not add contact. Error: {e}")
        else:
            messages.error(request, "Could not add contact. Please check errors below.")
    else:
        form = ContactForm(initial={'contact_list': contact_list})
    return render(request, 'mailer_app/contact_form.html', {
        'form': form, 'contact_list': contact_list, 'title': f"Add Contact to {contact_list.name}"
    })

@login_required
def edit_contact(request, contact_id):
    contact = get_object_or_404(Contact, id=contact_id)
    contact_list_for_redirect = contact.contact_list 
    if request.method == 'POST':
        form = ContactForm(request.POST, instance=contact)
        if form.is_valid():
            form.save()
            messages.success(request, f"Contact {contact.email} updated.")
            if contact_list_for_redirect:
                return redirect('mailer_app:view_contact_list', list_id=contact_list_for_redirect.id)
            return redirect('mailer_app:dashboard') 
        else:
            messages.error(request, "Could not update contact. Please check errors below.")
    else:
        form = ContactForm(instance=contact)
    return render(request, 'mailer_app/contact_form.html', {
        'form': form, 'contact': contact, 'contact_list': contact_list_for_redirect, 
        'title': f"Edit Contact: {contact.email}"
    })

@login_required
def delete_contact(request, contact_id):
    contact = get_object_or_404(Contact, id=contact_id)
    contact_list_id_for_redirect = contact.contact_list.id if contact.contact_list else None
    if request.method == 'POST':
        contact_email = contact.email
        contact.delete()
        messages.success(request, f"Contact '{contact_email}' has been deleted.")
        if contact_list_id_for_redirect:
            return redirect('mailer_app:view_contact_list', list_id=contact_list_id_for_redirect)
        return redirect('mailer_app:manage_contact_lists') 
    messages.warning(request, "Deletion must be confirmed via the delete button.")
    if contact_list_id_for_redirect:
        return redirect('mailer_app:view_contact_list', list_id=contact_list_id_for_redirect)
    return redirect('mailer_app:manage_contact_lists')

# --- Email Templates ---
@login_required
def manage_email_templates(request):
    templates_qs = EmailTemplate.objects.all().order_by('-created_at')
    if request.method == 'POST':
        form = EmailTemplateForm(request.POST)
        if form.is_valid():
            new_template = form.save()
            messages.success(request, f"Email template '{new_template.name}' created. You can now edit or preview it.")
            return redirect('mailer_app:edit_email_template', template_id=new_template.id)
        else:
            messages.error(request, "Could not create template. Please check errors.")
    else:
        form = EmailTemplateForm()
    context = {
        'form': form, 'templates': templates_qs,
        'title': "Manage Email Templates", 'form_title': "Create New Template"
    }
    return render(request, 'mailer_app/email_template_form.html', context)

@login_required
def edit_email_template(request, template_id):
    template_instance = get_object_or_404(EmailTemplate, id=template_id)
    templates_qs = EmailTemplate.objects.all().order_by('-created_at') 
    if request.method == 'POST':
        form = EmailTemplateForm(request.POST, instance=template_instance)
        if form.is_valid():
            form.save()
            messages.success(request, f"Template '{template_instance.name}' updated.")
            return redirect('mailer_app:edit_email_template', template_id=template_instance.id)
        else:
            messages.error(request, f"Could not update '{template_instance.name}'. Check errors.")
    else:
        form = EmailTemplateForm(instance=template_instance)
    context = {
        'form': form, 'instance': template_instance, 'templates': templates_qs,
        'title': f"Edit Template: {template_instance.name}", 'form_title': f"Edit: {template_instance.name}"
    }
    return render(request, 'mailer_app/email_template_form.html', context)

@login_required
def delete_email_template(request, template_id):
    template_obj = get_object_or_404(EmailTemplate, id=template_id)
    if request.method == 'POST':
        template_name = template_obj.name
        template_obj.delete()
        messages.success(request, f"Template '{template_name}' deleted.")
        return redirect('mailer_app:manage_email_templates')
    messages.warning(request, "Deletion must be confirmed via POST.")
    return redirect('mailer_app:manage_email_templates')

@login_required
def preview_email_template_page(request, template_id):
    template_instance = get_object_or_404(EmailTemplate, id=template_id)
    sample_context = _get_sample_context(request, contact_list_instance=None)
    try:
        rendered_subject = _render_email_content(template_instance.subject, sample_context)
    except TemplateSyntaxError as e:
        rendered_subject = f"Error rendering subject: {escape(str(e))}"
        messages.warning(request, f"Subject has a syntax error: {escape(str(e))}")
    return render(request, 'mailer_app/preview_email.html', {
        'template': template_instance, 'rendered_subject': rendered_subject,
        'title': f"Preview: {template_instance.name}"
    })

# START MARKER FOR get_rendered_email_content IN views.py (REPLACE THE ENTIRE FUNCTION)
@xframe_options_sameorigin
@login_required
def get_rendered_email_content(request, template_id):
    template_instance = get_object_or_404(EmailTemplate, id=template_id)
    contact_list_id = request.GET.get('contact_list_id')
    contact_list_for_sample = None
    if contact_list_id:
        try:
            contact_list_for_sample = ContactList.objects.get(id=contact_list_id)
        except ContactList.DoesNotExist:
            pass

    sample_context = _get_sample_context(request, contact_list_instance=contact_list_for_sample)

    try:
        # Render main HTML content and footer content separately
        rendered_html_body_full_doc = _render_email_content(template_instance.html_content, sample_context)
        rendered_footer_content = _render_email_content(template_instance.footer_html, sample_context)

        # Use BeautifulSoup to inject footer
        soup = BeautifulSoup(rendered_html_body_full_doc, 'html.parser')

        # Prepare footer div as a BeautifulSoup object
        # Added clear:both and width:100% for better block behavior within various layouts
        footer_div_str = f'<div style="text-align: center; padding-top: 20px; font-size: 12px; color: #777; clear:both; width:100%;">{rendered_footer_content}</div>'
        footer_soup_element = BeautifulSoup(footer_div_str, 'html.parser')

        # Prepare tracking pixel if available in sample context
        # The tracking_pixel in sample_context should be the raw <img> tag string
        tracking_pixel_html_str = sample_context.get('tracking_pixel', '')
        tracking_pixel_soup_element = BeautifulSoup(tracking_pixel_html_str, 'html.parser')

        if soup.body:
            # Append the actual elements from the parsed footer and tracking pixel
            if footer_soup_element.contents: # Check if footer_soup_element has actual content
                for child in footer_soup_element.contents:
                    soup.body.append(child.extract() if hasattr(child, 'extract') else child) # extract child to move it

            if tracking_pixel_html_str and tracking_pixel_soup_element.contents:
                for child in tracking_pixel_soup_element.contents:
                    soup.body.append(child.extract() if hasattr(child, 'extract') else child)
        else:
            # Fallback if no <body> tag is found (e.g., user provided an HTML fragment)
            # Wrap the fragment and then append footer and tracking pixel
            original_content_str = str(soup)
            soup = BeautifulSoup(f"<body>{original_content_str}</body>", "html.parser") # Create a body

            if footer_soup_element.contents:
                for child in footer_soup_element.contents:
                    soup.body.append(child.extract() if hasattr(child, 'extract') else child)

            if tracking_pixel_html_str and tracking_pixel_soup_element.contents:
                for child in tracking_pixel_soup_element.contents:
                    soup.body.append(child.extract() if hasattr(child, 'extract') else child)

        full_rendered_html = str(soup)

        logger.debug(f"Rendered HTML for template {template_id} preview: {full_rendered_html[:700]}...")
        return HttpResponse(full_rendered_html)
    except TemplateSyntaxError as e:
        logger.error(f"TemplateSyntaxError rendering template {template_id} for preview: {e}", exc_info=True)
        error_html = (
            f"<div style='font-family: sans-serif; padding: 20px; "
            f"border: 2px solid red; background-color: #ffe0e0;'>"
            f"<h3 style='color: red;'>Template Rendering Error</h3>"
            f"<p>Error in HTML content or footer:</p>"
            f"<pre style='background-color: #f0f0f0; padding: 10px; "
            f"border-radius: 5px;'>{escape(str(e))}</pre></div>"
        )
        return HttpResponse(error_html, status=200) # Return 200 so iframe shows error
    except Exception as e:
        logger.error(f"Unexpected error rendering template {template_id} for preview: {e}", exc_info=True)
        return HttpResponse(f"<p style='color:red;'>An unexpected error occurred during preview generation: {escape(str(e))}</p>", status=200)
# END MARKER FOR get_rendered_email_content IN views.py (REPLACE THE ENTIRE FUNCTION)
# --- Campaigns ---
@login_required
def manage_campaigns(request):
    campaigns_qs = Campaign.objects.all().order_by('-created_at')
    if request.method == 'POST':
        form = CampaignForm(request.POST)
        if form.is_valid():
            campaign = form.save(commit=False)
            campaign.save()
            form.save_m2m()
            if campaign.contact_lists.exists() or campaign.segments.exists():
                contacts_qs = Contact.objects.filter(
                    subscribed=True, email__isnull=False
                ).exclude(email__exact='')
                if campaign.contact_lists.exists():
                    contacts_qs = contacts_qs.filter(contact_list__in=campaign.contact_lists.all())
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
                        contacts_qs = contacts_qs.filter(id__in=combined_ids)
                contacts_qs = contacts_qs.distinct()
                campaign.total_recipients = contacts_qs.count()
            else:
                campaign.total_recipients = 0
            campaign.save(update_fields=['total_recipients'])
            messages.success(request, f"Campaign '{campaign.name}' saved as {campaign.get_status_display()}.")
            return redirect('mailer_app:view_campaign', campaign_id=campaign.id)
        else:
            error_list = [f"{(form.fields.get(f).label or f)}: {', '.join(errs)}" for f, errs in form.errors.items()]
            messages.error(request, "Could not save campaign: " + "; ".join(error_list))
    else:
        form = CampaignForm()
    return render(request, 'mailer_app/campaign_form.html', {
        'form': form, 'campaigns': campaigns_qs,
        'title': "Manage Campaigns", 'form_title': "Create/Edit Campaign"
    })

@login_required
def view_campaign(request, campaign_id):
    campaign_obj = get_object_or_404(Campaign, id=campaign_id)
    test_email_form = SendTestEmailForm(initial={'email_template': campaign_obj.email_template})
    app_settings = AppSettings.load()
    merge_tags = [
        "{{email}}", "{{first_name}}", "{{last_name}}", "{{company}}", "{{job_title}}", 
        "{{unsubscribe_url}}", "{{your_company_name}}", "{{company_address}}", "{{site_url}}",
        "{{tracking_pixel}}"
    ]
    first_contact_list = campaign_obj.contact_lists.all().first()
    if first_contact_list:
        sample_contact_with_custom = first_contact_list.contacts.filter(custom_fields__isnull=False).first()
        if sample_contact_with_custom and sample_contact_with_custom.custom_fields:
            merge_tags.extend([f"{{{{{key}}}}}" for key in sample_contact_with_custom.custom_fields.keys()])
    can_send = (
        campaign_obj.status in ['draft', 'failed', 'scheduled'] and
        campaign_obj.email_template and
        (campaign_obj.contact_lists.exists() or campaign_obj.segments.exists())
    )
    context = {
        'campaign': campaign_obj,
        'test_email_form': test_email_form,
        'title': f"Campaign: {campaign_obj.name}",
        'available_merge_tags': sorted(list(set(merge_tags))),
        'can_send': can_send
    }
    return render(request, 'mailer_app/view_campaign_detail.html', context)

@login_required
def send_test_email_view(request, campaign_id):
    campaign_obj = get_object_or_404(Campaign, id=campaign_id)
    if not campaign_obj.email_template:
        messages.error(request, "Campaign has no email template selected.")
        return redirect('mailer_app:view_campaign', campaign_id=campaign_obj.id)
    settings_obj = AppSettings.load()
    if not settings_obj or not settings_obj.sender_email:
        messages.error(request, "Sender email is not configured in settings. Please set it up first.")
        return redirect('mailer_app:manage_settings')

    if request.method == 'POST':
        form = SendTestEmailForm(request.POST)
        if form.is_valid():
            test_email = form.cleaned_data['test_email_address']
            template_to_use = form.cleaned_data['email_template']
            first_contact_list_for_sample = campaign_obj.contact_lists.all().first()
            sample_context = _get_sample_context(request, contact_list_instance=first_contact_list_for_sample)
            sample_context['email'] = test_email 
            subject = _render_email_content(template_to_use.subject, sample_context)
            html_body = _render_email_content(template_to_use.html_content, sample_context)
            html_body += _render_email_content(template_to_use.footer_html, sample_context)
            plain_body = strip_tags(html_body)
            try:
                send_mail(
                    subject=subject, message=plain_body,
                    from_email=settings_obj.sender_email,
                    recipient_list=[test_email],
                    html_message=html_body, fail_silently=False,
                )
                messages.success(request, f"Test email sent to {test_email} using '{template_to_use.name}'.")
            except Exception as e:
                logger.error(f"Error sending test email: {e}", exc_info=True)
                messages.error(request, f"Error sending test email: {str(e)}")
        else:
            error_messages = [f"{(form.fields.get(f).label if form.fields.get(f) else f)}: {e}" for f, errs in form.errors.items() for e in errs]
            messages.error(request, "Test email not sent. Errors: " + "; ".join(error_messages))
    return redirect('mailer_app:view_campaign', campaign_id=campaign_obj.id)

@login_required
def execute_send_campaign(request, campaign_id):
    campaign_obj = get_object_or_404(Campaign, id=campaign_id)
    if campaign_obj.status in ['sending', 'sent', 'queued'] and campaign_obj.status != 'failed':
        messages.warning(request, f"Campaign '{campaign_obj.name}' is already {campaign_obj.get_status_display()} or has been processed.")
        return redirect('mailer_app:view_campaign', campaign_id=campaign_obj.id)
    
    if not (campaign_obj.contact_lists.exists() or campaign_obj.segments.exists()) or not campaign_obj.email_template:
        messages.error(request, "Campaign needs at least one contact list or segment and an email template before sending.")
        return redirect('mailer_app:view_campaign', campaign_id=campaign_obj.id)

    from marketing_emails.tasks import process_campaign_task 
    campaign_obj.status = 'queued' 
    campaign_obj.save(update_fields=['status'])
    process_campaign_task.delay(campaign_obj.id)
    messages.success(request, f"Campaign '{campaign_obj.name}' has been queued for sending.")
    return redirect('mailer_app:view_campaign', campaign_id=campaign_obj.id)

# --- Unsubscribe & Re-subscribe ---
# mailer_app/views.py
def unsubscribe_contact_view(request, token):
    settings_obj = AppSettings.load() # Load settings
    site_url_to_redirect = settings_obj.site_url if settings_obj and settings_obj.site_url else "/" # Fallback to root

    try:
        valid_token = uuid.UUID(str(token))
        contact_obj = get_object_or_404(Contact, unsubscribe_token=valid_token)
    except (Http404, ValueError):
        messages.error(request, "Invalid or malformed unsubscribe link.")
        return render(request, 'mailer_app/unsubscribe_confirmation.html', {
            'success': False, 
            'message': "Invalid or malformed unsubscribe link.",
            'site_home_url': site_url_to_redirect # Pass site_url
        })

    if request.method == 'POST':
        if 'confirm_unsubscribe' in request.POST:
            if contact_obj.subscribed:
                contact_obj.subscribed = False
                contact_obj.save(update_fields=['subscribed', 'updated_at'])
                success_message = f"The email address <strong>{contact_obj.email}</strong> has been successfully unsubscribed."
                messages.success(request, success_message, extra_tags='safe')
                return render(request, 'mailer_app/unsubscribe_confirmation.html', {
                    'success': True, 
                    'confirmation_message': success_message, 
                    'contact_email': contact_obj.email,
                    'site_home_url': site_url_to_redirect # Pass site_url
                })
            else: # Already unsubscribed
                info_message = f"The email address <strong>{contact_obj.email}</strong> is already unsubscribed."
                messages.info(request, info_message, extra_tags='safe')
                return render(request, 'mailer_app/unsubscribe_confirmation.html', {
                    'success': None, 
                    'confirmation_message': info_message, 
                    'contact_email': contact_obj.email,
                    'site_home_url': site_url_to_redirect # Pass site_url
                })
        elif 'keep_subscribed' in request.POST:
            # This now redirects, so the thank you page will handle its own link
            messages.success(request, f"Thank you for staying subscribed, <strong>{contact_obj.email}</strong>!", extra_tags='safe')
            return redirect('mailer_app:keep_subscribed_thank_you')

    # For GET request (initial page load)
    return render(request, 'mailer_app/unsubscribe_page.html', {
        'contact': contact_obj, 
        'token': token,
        'site_home_url': site_url_to_redirect # Pass site_url for any links on the initial page if needed
    })

def keep_subscribed_thank_you_view(request):
    settings_obj = AppSettings.load() # Load settings
    site_url_to_redirect = settings_obj.site_url if settings_obj and settings_obj.site_url else "/" # Fallback
    return render(request, 'mailer_app/keep_subscribed_thank_you.html', {
        'title': "Subscription Confirmed",
        'site_home_url': site_url_to_redirect # Pass site_url
    })

@login_required 
def resubscribe_contact_view(request):
    if request.method == 'POST':
        email_to_resubscribe = request.POST.get('email')
        if not email_to_resubscribe:
            messages.error(request, "Please provide an email address to re-subscribe.")
        else:
            contact_to_resubscribe = Contact.objects.filter(email=email_to_resubscribe).first()
            if contact_to_resubscribe:
                if not contact_to_resubscribe.subscribed:
                    contact_to_resubscribe.subscribed = True
                    contact_to_resubscribe.save(update_fields=['subscribed', 'updated_at'])
                    messages.success(request, f"The email <strong>{email_to_resubscribe}</strong> has been re-subscribed.", extra_tags='safe')
                else:
                    messages.info(request, f"The email <strong>{email_to_resubscribe}</strong> is already subscribed.", extra_tags='safe')
            else:
                messages.warning(request, f"The email <strong>{email_to_resubscribe}</strong> was not found in our records.", extra_tags='safe')
        return redirect(request.POST.get('next', 'mailer_app:dashboard')) 
    return render(request, 'mailer_app/resubscribe_form.html', {'title': "Re-subscribe"})

# --- Settings ---
@login_required
def manage_settings(request):
    settings_obj, created = AppSettings.objects.get_or_create(pk=1) 
    if created: 
        settings_obj.sender_email = django_settings.DEFAULT_FROM_EMAIL if hasattr(django_settings, 'DEFAULT_FROM_EMAIL') else 'noreply@example.com'
        settings_obj.company_name = "My Awesome Company"
        settings_obj.save()
    if request.method == 'POST':
        form = SettingsForm(request.POST, instance=settings_obj)
        if form.is_valid():
            form.save()
            messages.success(request, "Settings updated successfully.")
            return redirect('mailer_app:manage_settings')
        else:
            messages.error(request, "Could not update settings. Please check errors.")
    else:
        form = SettingsForm(instance=settings_obj)
    return render(request, 'mailer_app/settings_form.html', {
        'form': form, 'title': "Manage Settings"
    })

# --- Media Assets ---
@login_required
def upload_media(request):
    uploaded_file_url_for_template = None 
    if request.method == 'POST':
        form = MediaUploadForm(request.POST, request.FILES)
        if form.is_valid():
            media_file = request.FILES['media_file']
            file_name_part = default_storage.get_valid_name(media_file.name)
            file_upload_path = os.path.join(
                'user_media', 
                default_storage.get_valid_name(request.user.username), 
                f"{uuid.uuid4()}_{file_name_part}"
            )
            actual_file_path_in_storage = default_storage.get_available_name(file_upload_path)
            saved_path = default_storage.save(actual_file_path_in_storage, media_file)
            file_s3_url = default_storage.url(saved_path)
            uploaded_file_url_for_template = file_s3_url
            try:
                MediaAsset.objects.create(
                    uploaded_by=request.user,
                    file_name=media_file.name, 
                    file_path_in_storage=saved_path, 
                    file_url=file_s3_url,
                    file_type=media_file.content_type,
                    file_size=media_file.size
                )
                messages.success(request, f"File '{media_file.name}' uploaded successfully.")
            except Exception as e:
                logger.error(f"Error creating MediaAsset record for {media_file.name} after S3 upload: {e}", exc_info=True)
                messages.error(request, "File uploaded to S3, but failed to create database record.")
                if saved_path:
                    default_storage.delete(saved_path)
                    logger.info(f"Cleaned up orphaned S3 file {saved_path} after DB error.")
                uploaded_file_url_for_template = None 
            return render(request, 'mailer_app/media_upload.html', {
                'form': MediaUploadForm(), 
                'uploaded_file_url': uploaded_file_url_for_template, 
                'title': "Upload Media"
            })
        else:
            messages.error(request, "File upload failed. Please check the form for errors.")
    else: 
        form = MediaUploadForm()
    return render(request, 'mailer_app/media_upload.html', {
        'form': form,
        'uploaded_file_url': uploaded_file_url_for_template, 
        'title': "Upload Media"
    })

@login_required
def manage_media_assets(request):
    # Sorting logic
    sort_by = request.GET.get('sort_by', 'file_name')  # Default to file_name
    order = request.GET.get('order', 'asc')  # Default to ascending
    if sort_by != 'file_name':
        sort_by = 'file_name'  # Restrict to file_name
        logger.warning(f"Invalid sort_by parameter '{sort_by}', defaulting to 'file_name'.")
    if order not in ['asc', 'desc']:
        order = 'asc'
        logger.warning(f"Invalid order parameter '{order}', defaulting to 'asc'.")
    
    order_prefix = '' if order == 'asc' else '-'
    media_assets_qs = MediaAsset.objects.all().order_by(f"{order_prefix}{sort_by}")
    
    # Pagination
    paginator = Paginator(media_assets_qs, 15)
    page_number = request.GET.get('page')
    try:
        assets_page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        assets_page_obj = paginator.page(1)
    except EmptyPage:
        assets_page_obj = paginator.page(paginator.num_pages)
    
    context = {
        'assets_page_obj': assets_page_obj,
        'title': "Manage Media Assets",
        'current_sort_by': sort_by,
        'current_order': order
    }
    return render(request, 'mailer_app/manage_media_assets.html', context)

@login_required
def delete_media_asset(request, asset_id):
    asset = get_object_or_404(MediaAsset, id=asset_id)
    if request.method == 'POST':
        asset_name = asset.file_name
        s3_object_key_to_delete = asset.file_path_in_storage
        try:
            if s3_object_key_to_delete:
                default_storage.delete(s3_object_key_to_delete)
                logger.info(f"Successfully deleted '{s3_object_key_to_delete}' from S3 for asset ID {asset.id}.")
            else:
                logger.warning(f"No file_path_in_storage found for asset ID {asset.id}. Cannot delete from storage.")
            asset.delete() 
            messages.success(request, f"Media asset '{asset_name}' and its S3 file (if path was known) have been processed for deletion.")
        except Exception as e:
            logger.error(f"Error deleting media asset {asset_id} or its S3 file: {e}", exc_info=True)
            messages.error(request, f"Could not fully delete media asset. Error: {e}")
        return redirect('mailer_app:manage_media_assets')
    messages.warning(request, "Deletion must be confirmed via POST.")
    return redirect('mailer_app:manage_media_assets') 

# --- Analytics, Tracking, Health Check, 500 ---
@login_required
def analytics(request):
    campaigns = Campaign.objects.all().order_by('-created_at')[:20]
    return render(request, 'mailer_app/analytics.html', {'campaigns': campaigns, 'title': "Campaign Analytics"})

def track_open(request, campaign_id, contact_id):
    try:
        log = CampaignSendLog.objects.filter(campaign_id=campaign_id, contact_id=contact_id).first()
        if log and not log.opened_at: 
            log.opened_at = timezone.now()
            log.save(update_fields=['opened_at'])
    except Exception as e:
        logger.error(f"Error tracking open for c:{campaign_id}, u:{contact_id}: {e}")
    pixel = b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00\x21\xf9\x04\x01\x00\x00\x00\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00\x3b'
    return HttpResponse(pixel, content_type='image/gif')

def custom_500(request):
    return render(request, 'mailer_app/500.html', status=500)

def health_check(request):
    return HttpResponse("OK", status=200)

@login_required
def manage_segments(request):
    segments_qs = Segment.objects.all().order_by('-created_at')
    segments_with_counts = []
    for segment in segments_qs:
        contacts_qs = Contact.objects.all()
        if segment.filters.get('subscribed'):
            subscribed = segment.filters['subscribed'] == 'true'
            contacts_qs = contacts_qs.filter(subscribed=subscribed)
        if segment.filters.get('company'):
            contacts_qs = contacts_qs.filter(company__icontains=segment.filters['company'])
        if segment.filters.get('custom_fields'):
            for key, value in segment.filters['custom_fields'].items():
                contacts_qs = contacts_qs.filter(custom_fields__has_key=key, custom_fields__contains={key: value})
        if segment.filters.get('contact_lists'):
            contacts_qs = contacts_qs.filter(contact_list__id__in=segment.filters['contact_lists'])
        contact_count = contacts_qs.count()
        segments_with_counts.append({
            'segment': segment,
            'contact_count': contact_count
        })
    if request.method == 'POST':
        form = SegmentForm(request.POST)
        if form.is_valid():
            segment = form.save()
            messages.success(request, f"Segment '{segment.name}' created.")
            return redirect('mailer_app:manage_segments')
        else:
            messages.error(request, "Could not create segment. Please check errors.")
    else:
        form = SegmentForm()
    return render(request, 'mailer_app/manage_segments.html', {
        'form': form, 'segments_with_counts': segments_with_counts, 'title': "Manage Segments"
    })

@login_required
def view_segment_contacts(request, segment_id):
    segment = get_object_or_404(Segment, id=segment_id)
    contacts_qs = Contact.objects.all()
    if segment.filters.get('subscribed'):
        subscribed = segment.filters['subscribed'] == 'true'
        contacts_qs = contacts_qs.filter(subscribed=subscribed)
    if segment.filters.get('company'):
        contacts_qs = contacts_qs.filter(company__icontains=segment.filters['company'])
    if segment.filters.get('custom_fields'):
        for key, value in segment.filters['custom_fields'].items():
            contacts_qs = contacts_qs.filter(custom_fields__has_key=key, custom_fields__contains={key: value})
    if segment.filters.get('contact_lists'):
        contacts_qs = contacts_qs.filter(contact_list__id__in=segment.filters['contact_lists'])
    contacts_qs = contacts_qs.order_by('email')
    paginator = Paginator(contacts_qs, 25)
    page_number = request.GET.get('page')
    try:
        contacts_page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        contacts_page_obj = paginator.page(1)
    except EmptyPage:
        contacts_page_obj = paginator.page(paginator.num_pages)
    return render(request, 'mailer_app/view_segment_contacts.html', {
        'segment': segment, 'contacts_page_obj': contacts_page_obj, 'title': f"Contacts in Segment: {segment.name}"
    })

@login_required
def delete_segment(request, segment_id):
    segment = get_object_or_404(Segment, id=segment_id)
    if request.method == 'POST':
        segment_name = segment.name
        segment.delete()
        messages.success(request, f"Segment '{segment_name}' deleted.")
        return redirect('mailer_app:manage_segments')
    messages.warning(request, "Deletion must be confirmed via POST.")
    return redirect('mailer_app:manage_segments')
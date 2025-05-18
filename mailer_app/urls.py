# mailer_app/urls.py
from django.urls import path
from . import views # Assuming unsubscribe_contact_view is in mailer_app.views

app_name = 'mailer_app' # Define an app namespace

urlpatterns = [
    path('', views.dashboard, name='dashboard'),

    # Contact Lists
    path('contacts/', views.manage_contact_lists, name='manage_contact_lists'),
    path('contacts/<uuid:list_id>/', views.view_contact_list, name='view_contact_list'),
    path('contacts/<uuid:list_id>/delete/', views.delete_contact_list, name='delete_contact_list'),

    # Email Templates
    path('templates/', views.manage_email_templates, name='manage_email_templates'),
    path('templates/<uuid:template_id>/edit/', views.edit_email_template, name='edit_email_template'),
    path('templates/<uuid:template_id>/delete/', views.delete_email_template, name='delete_email_template'),
    path('templates/<uuid:template_id>/preview/', views.preview_email_template_page, name='preview_email_template_page'),
    path('templates/<uuid:template_id>/get-rendered-content/', views.get_rendered_email_content, name='get_rendered_email_content'),

    # Campaigns
    path('campaigns/', views.manage_campaigns, name='manage_campaigns'),
    path('campaigns/<uuid:campaign_id>/', views.view_campaign, name='view_campaign'),
    path('campaigns/<uuid:campaign_id>/send-test/', views.send_test_email_view, name='send_test_email_campaign'),
    path('campaigns/<uuid:campaign_id>/execute-send/', views.execute_send_campaign, name='execute_send_campaign'),
    # path('campaigns/<uuid:campaign_id>/delete/', views.delete_campaign, name='delete_campaign'), # Uncomment if you implement delete_campaign view

    # Unsubscribe URL
    # This assumes unsubscribe_contact_view is in mailer_app.views
    # The name 'unsubscribe_contact' is used in tasks.py to reverse this URL
    path('unsubscribe/<uuid:token>/', views.unsubscribe_contact_view, name='unsubscribe_contact'),

    path('keep-subscribed/', views.keep_subscribed_thank_you_view, name='keep_subscribed_thank_you'),
]

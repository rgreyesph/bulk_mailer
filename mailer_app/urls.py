from django.urls import path
from . import views

app_name = 'mailer_app'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('contacts/', views.manage_contact_lists, name='manage_contact_lists'),
    path('contacts/<uuid:list_id>/', views.view_contact_list, name='view_contact_list'),
    path('contacts/<uuid:list_id>/delete/', views.delete_contact_list, name='delete_contact_list'),
    path('contacts/<uuid:list_id>/add/', views.add_contact, name='add_contact'),
    path('contacts/contact/<uuid:contact_id>/edit/', views.edit_contact, name='edit_contact'),
    path('contacts/contact/<uuid:contact_id>/delete/', views.delete_contact, name='delete_contact'),
    path('templates/', views.manage_email_templates, name='manage_email_templates'),
    path('templates/<uuid:template_id>/edit/', views.edit_email_template, name='edit_email_template'),
    path('templates/<uuid:template_id>/delete/', views.delete_email_template, name='delete_email_template'),
    path('templates/<uuid:template_id>/preview/', views.preview_email_template_page, name='preview_email_template_page'),
    path('templates/<uuid:template_id>/get-rendered-content/', views.get_rendered_email_content, name='get_rendered_email_content'),
    path('campaigns/', views.manage_campaigns, name='manage_campaigns'),
    path('campaigns/<uuid:campaign_id>/', views.view_campaign, name='view_campaign'),
    path('campaigns/<uuid:campaign_id>/send-test/', views.send_test_email_view, name='send_test_email_campaign'),
    path('campaigns/<uuid:campaign_id>/execute-send/', views.execute_send_campaign, name='execute_send_campaign'),
    path('unsubscribe/<uuid:token>/', views.unsubscribe_contact_view, name='unsubscribe_contact'),
    path('keep-subscribed/', views.keep_subscribed_thank_you_view, name='keep_subscribed_thank_you'),
    path('settings/', views.manage_settings, name='manage_settings'),
    path('media/upload/', views.upload_media, name='upload_media'),
    path('media/manage/', views.manage_media_assets, name='manage_media_assets'),
    path('media/asset/<uuid:asset_id>/delete/', views.delete_media_asset, name='delete_media_asset'),
    path('analytics/', views.analytics, name='analytics'),
    path('track/open/<uuid:campaign_id>/<uuid:contact_id>/', views.track_open, name='track_open'),
    path('health/', views.health_check, name='health_check'),
    path('segments/', views.manage_segments, name='manage_segments'),
    path('segments/<uuid:segment_id>/delete/', views.delete_segment, name='delete_segment'),
    path('segments/<uuid:segment_id>/contacts/', views.view_segment_contacts, name='view_segment_contacts'),
]
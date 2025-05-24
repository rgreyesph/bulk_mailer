import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'bulk_mailer.settings')

app = Celery('bulk_mailer')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
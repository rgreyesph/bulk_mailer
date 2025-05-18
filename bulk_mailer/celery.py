# bulk_mailer/bulk_mailer/celery.py
import eventlet # Add this line
eventlet.monkey_patch() # Add this line BEFORE other imports

import os
from celery import Celery

# Set the default Django settings module for the 'celery' program.
# This should match your project structure. If settings.py is in 'bulk_mailer/bulk_mailer/settings.py',
# then 'bulk_mailer.settings' is correct.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'bulk_mailer.settings')

# Create a Celery application instance.
# The first argument is the name of the current module, which is 'bulk_mailer'
# if this file is 'bulk_mailer/celery.py' inside the 'bulk_mailer' project directory.
app = Celery('bulk_mailer')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   in settings.py should have a `CELERY_` prefix.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules from all registered Django app configs.
# This tells Celery to look for files named 'tasks.py' in your installed apps
# (e.g., 'marketing_emails/tasks.py').
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f'Request: {self.request!r}')

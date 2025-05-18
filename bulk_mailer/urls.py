# bulk_mailer_project/urls.py (This is the project-level urls.py)

from django.contrib import admin
from django.urls import path, include # Make sure 'include' is imported

urlpatterns = [
    path('admin/', admin.site.urls),
    # This is the crucial line:
    # It tells Django that for any URL that isn't 'admin/',
    # it should look for further URL patterns in 'mailer_app.urls'.
    path('', include('mailer_app.urls')),
]

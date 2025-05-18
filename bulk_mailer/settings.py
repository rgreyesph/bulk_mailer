# bulk_mailer/settings.py
import os
from pathlib import Path
from decouple import config # For environment variables

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = config('DJANGO_SECRET_KEY', default='your-default-secret-key-for-development-make-sure-this-is-strong')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = config('DJANGO_DEBUG', default=True, cast=bool)

# Use decouple for ALLOWED_HOSTS as well for consistency
# ALLOWED_HOSTS_CSV = config('DJANGO_ALLOWED_HOSTS', default='localhost,127.0.0.1')
# ALLOWED_HOSTS = [host.strip() for host in ALLOWED_HOSTS_CSV.split(',') if host.strip()]

ALLOWED_HOSTS_CSV = config('DJANGO_ALLOWED_HOSTS', default='localhost,127.0.0.1')
ALLOWED_HOSTS = [host.strip() for host in ALLOWED_HOSTS_CSV.split(',') if host.strip()]


# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sites',      # For Django Sites framework
    'mailer_app',                # Your mailer application
    'marketing_emails',          # Your tasks app
    'storages',                  # For S3 (if used for media/static)
    'django_ses',                # For AWS SES integration (if using this backend directly)
    'django_celery_beat',        # For Celery Beat (scheduled tasks)
    'django_celery_results',     # To store Celery task results in DB
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'bulk_mailer.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'], # Project-level templates if any
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'bulk_mailer.wsgi.application'


# Database
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = config('TIME_ZONE', default='Asia/Manila') # Make timezone configurable if needed
USE_I18N = True
USE_TZ = True


# Static files (CSS, JavaScript, Images)
STATIC_URL = 'static/'
# STATICFILES_DIRS = [BASE_DIR / "static"] # Uncomment if you have project-wide static files
# STATIC_ROOT = BASE_DIR / "staticfiles_collected" # For collectstatic in production

# Media files (User-uploaded content) - Configure if you use ImageField/FileField
# MEDIA_URL = '/media/'
# MEDIA_ROOT = BASE_DIR / 'mediafiles'


DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# AWS Credentials & SES Configuration
AWS_ACCESS_KEY_ID = config('AWS_ACCESS_KEY_ID', default=None)
AWS_SECRET_ACCESS_KEY = config('AWS_SECRET_ACCESS_KEY', default=None)
AWS_SES_REGION_NAME = config('AWS_SES_REGION_NAME', default='ap-southeast-1')
# Use AWS_SES_SENDER_EMAIL consistently. This is the verified "From" address.
AWS_SES_SENDER_EMAIL = config('AWS_SES_SENDER_EMAIL', default=None)
# AWS_SES_REGION_ENDPOINT = f'email.{AWS_SES_REGION_NAME}.amazonaws.com' # Boto3 usually infers this

# S3 Configuration (if storing media/static files for emails on S3)
AWS_STORAGE_BUCKET_NAME = config('AWS_STORAGE_BUCKET_NAME', default=None)
AWS_S3_REGION_NAME = config('AWS_S3_REGION_NAME', default=AWS_SES_REGION_NAME) # Often same as SES region
# AWS_S3_CUSTOM_DOMAIN = f'{AWS_STORAGE_BUCKET_NAME}.s3.{AWS_S3_REGION_NAME}.amazonaws.com' # If using S3 directly
# DEFAULT_FILE_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage' # If using S3 for media
# MEDIA_URL = f'https://{AWS_S3_CUSTOM_DOMAIN}/media/' # If using S3 for media

# Email Backend
# If you are using Boto3 directly in tasks.py to send emails (as in marketing_emails_tasks_finalized),
# this EMAIL_BACKEND setting is for Django's built-in mail functions (e.g., password reset).
# If you want those to also use SES via django-ses:
EMAIL_BACKEND = 'django_ses.SESBackend'
# If you are *only* using Boto3 in tasks.py, you might not strictly need 'django_ses' in INSTALLED_APPS
# or this EMAIL_BACKEND, unless other parts of Django send mail.
# The tasks.py uses Boto3 directly, so it doesn't rely on Django's EMAIL_BACKEND for its primary function.

# SITE_ID is required for django.contrib.sites
SITE_ID = 1

# Your Company Name (for email footers, etc.)
YOUR_COMPANY_NAME = config('YOUR_COMPANY_NAME', default="Your Awesome Company")

# Celery Configuration
CELERY_BROKER_URL = config('CELERY_BROKER_URL', default='redis://localhost:6379/0')
CELERY_RESULT_BACKEND = 'django-db'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60

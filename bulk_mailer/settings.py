import os
from pathlib import Path
from decouple import config

BASE_DIR = Path(__file__).resolve().parent.parent

SITE_DOMAIN = config('SITE_DOMAIN', default='localhost:8000')

SECRET_KEY = config('DJANGO_SECRET_KEY')
DEBUG = config('DJANGO_DEBUG', default=False, cast=bool)
# It's generally safer to be more specific than '*' in production,
# but for local Docker dev, '*' with DEBUG=True is common.
# Your .env provides 'localhost,127.0.0.1' which is good.
ALLOWED_HOSTS = config('DJANGO_ALLOWED_HOSTS', default='localhost,127.0.0.1').split(',')

INSTALLED_APPS = [
    'jazzmin',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles', # Required for static files handling
    'django.contrib.sites',
    'mailer_app',
    'marketing_emails',
    'django_celery_beat',
    'django_celery_results',
    'storages', # For S3Boto3Storage
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
SITE_ID = 1

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'], # Pointing to <project_root>/templates/
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

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': config('DB_NAME'),
        'USER': config('DB_USER'),
        'PASSWORD': config('DB_PASSWORD'),
        'HOST': config('DB_HOST'), # Should be 'db' for docker-compose from .env or docker-compose env
        'PORT': config('DB_PORT', default='5432'),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = config('TIME_ZONE', default='Asia/Manila')
USE_I18N = True
USE_TZ = True

# --- Email Configuration (Using django-ses) ---
EMAIL_BACKEND = 'django_ses.SESBackend'
# It's good practice to have a distinct AWS_SES_REGION_NAME in .env if it can differ from S3 region
AWS_SES_REGION_NAME = config('AWS_SES_REGION_NAME', default=config('AWS_S3_REGION_NAME'))
AWS_ACCESS_KEY_ID = config('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = config('AWS_SECRET_ACCESS_KEY')
AWS_SES_CONFIGURATION_SET = config('AWS_SES_CONFIGURATION_SET', default=None)
# DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default=f'noreply@{SITE_DOMAIN}') # Define this in .env

# --- AWS S3 Core Configuration ---
# These are loaded from .env by the lines for EMAIL_BACKEND or directly by storages
AWS_STORAGE_BUCKET_NAME = config('AWS_STORAGE_BUCKET_NAME')
AWS_S3_REGION_NAME = config('AWS_S3_REGION_NAME')

# --- STATIC FILES (CSS, JS, UI Images) Configuration for S3 ---
AWS_S3_STATIC_LOCATION = 'static' # All static files will be stored under a 'static/' prefix in your bucket
STATICFILES_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'
STATIC_URL = f'https://{config("AWS_STORAGE_BUCKET_NAME")}.s3.{config("AWS_S3_REGION_NAME")}.amazonaws.com/{AWS_S3_STATIC_LOCATION}/'
STATIC_ROOT = BASE_DIR / 'staticfiles_collected_for_s3' # Local temp directory for collectstatic before S3 upload

# --- MEDIA FILES (User Uploads) Configuration for S3 ---
DEFAULT_FILE_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'
AWS_S3_MEDIA_LOCATION = 'media' # All media files will be stored under a 'media/' prefix in your bucket
MEDIA_URL = f'https://{config("AWS_STORAGE_BUCKET_NAME")}.s3.{config("AWS_S3_REGION_NAME")}.amazonaws.com/{AWS_S3_MEDIA_LOCATION}/'
# MEDIA_ROOT is not typically needed when DEFAULT_FILE_STORAGE uses S3.

# --- AWS S3 General Settings for django-storages ---
AWS_DEFAULT_ACL = config('AWS_DEFAULT_ACL', default='public-read') # Or 'private', None, etc.
AWS_S3_OBJECT_PARAMETERS = {
    'CacheControl': config('AWS_S3_CACHE_CONTROL', default='max-age=86400'), # Cache for 1 day
}
# To ensure files are not overwritten if they have the same name (optional, S3 versioning is another option)
AWS_S3_FILE_OVERWRITE = False # Default is True
AWS_QUERYSTRING_AUTH = False # If using public-read ACL and don't want signed URLs by default for MEDIA_URL

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# --- Celery Configuration ---
CELERY_BROKER_URL = config('CELERY_BROKER_URL', default='redis://redis:6379/0') # Default for docker
CELERY_RESULT_BACKEND = 'django-db'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE

# --- Authentication Settings ---
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/login/'

SESSION_ENGINE = 'django.contrib.sessions.backends.db'
# --- Security Settings (Conditional on DEBUG) ---
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = config('SECURE_HSTS_SECONDS', default=31536000, cast=int)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = config('SECURE_HSTS_INCLUDE_SUBDOMAINS', default=True, cast=bool)
    SECURE_HSTS_PRELOAD = config('SECURE_HSTS_PRELOAD', default=True, cast=bool)
    # SESSION_COOKIE_DOMAIN = config('SESSION_COOKIE_DOMAIN', default=None) # For cross-subdomain sessions if needed
    # CSRF_COOKIE_DOMAIN = config('CSRF_COOKIE_DOMAIN', default=None)
else:
    SECURE_SSL_REDIRECT = False
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False

SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True

# --- Logging Configuration ---
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'simple': {
            'format': '[{asctime}] {levelname} {message}',
            'style': '{',
            'datefmt': '%Y-%m-%d %H:%M:%S'
        },
    },
    'handlers': {
        'file': {
            'level': 'DEBUG',
            'class': 'logging.FileHandler',
            'filename': BASE_DIR / 'debug.log',
            'formatter': 'verbose',
        },
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'file'],
            'level': config('DJANGO_LOG_LEVEL', default='INFO'),
            'propagate': False,
        },
        'mailer_app': {
            'handlers': ['console', 'file'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'marketing_emails': {
            'handlers': ['console', 'file'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'celery': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': False,
        },
        'storages': { # Logger for django-storages
            'handlers': ['console', 'file'],
            'level': 'INFO', # Set to DEBUG for more verbose S3 interactions
            'propagate': False,
        },
        # '': { # Root logger - be careful not to make it too noisy
        #     'handlers': ['console', 'file'],
        #     'level': 'WARNING',
        #     'propagate': True,
        # },
    },
}

# --- Django Jazzmin Settings ---
JAZZMIN_SETTINGS = {
    "site_title": "Bulk Mailer Herkings Admin",
    "site_header": "BulkMailerHerkings",
    "site_brand": "BulkMailerHerkings",
    # "site_logo": "images/logo.png",
    "welcome_sign": "Welcome to the Bulk Mailer Admin", # Corrected missing comma from previous version
    "copyright": "Your Company Name",
    "search_model": ["auth.User", "mailer_app.Contact"],
    "topmenu_links": [
        {"name": "Home",  "url": "admin:index", "permissions": ["auth.view_user"]},
        {"app": "mailer_app"},
    ],
    "show_ui_builder": False,
    "changeform_format": "horizontal_tabs",
    # "language_chooser": True, # If you have multiple languages
}
JAZZMIN_UI_TWEAKS = {
    "navbar_small_text": False,
    "footer_small_text": False,
    "body_small_text": False,
    "brand_small_text": False,
    "brand_colour": "navbar-indigo",
    "accent": "accent-primary",
    "navbar": "navbar-indigo navbar-dark",
    "no_navbar_border": False,
    "navbar_fixed": True,
    "layout_boxed": False,
    "footer_fixed": False,
    "sidebar_fixed": True,
    "sidebar": "sidebar-dark-indigo",
    "sidebar_nav_small_text": False,
    "sidebar_disable_expand": False,
    "sidebar_nav_child_indent": False,
    "sidebar_nav_compact_style": False, # Typo: stijl -> style
    "sidebar_nav_flat_style": False,   # Typo: stijl -> style
    "sidebar_nav_legacy_style": False, # Typo: stijl -> style
    "sidebar_nav_accordion": True,
    "actions_sticky_top": True
}
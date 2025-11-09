# Bulk Mailer Web Application

This is a Django-based web application designed for sending bulk HTML emails for marketing purposes. It uses AWS SES for reliable email delivery, Celery and Redis for asynchronous task processing (so the app doesn't freeze when sending), and AWS S3 for storing media files like images used in email templates.

## Features

  * **Contact List Management:** Upload contacts from CSV files into distinct lists.
  * **Email Template Management:** Create, edit, and delete HTML email templates using a web interface.
  * **Template Preview:** Preview how email templates will look, rendered with sample data.
  * **Campaign Management:** Create campaigns that link an email template to one or more contact lists.
  * **Asynchronous Sending:** Bulk email sends are offloaded to Celery background tasks, so the user interface remains fast and responsive.
  * **Scheduled Sending:** Campaigns can be scheduled to be sent at a future date and time using Celery Beat.
  * **Test Emails:** Send test emails to a specific address before launching a full campaign.
  * **Unsubscribe Functionality:** Automatically generates unique unsubscribe links for each recipient.
  * **Send Logging:** Tracks the status (success/failure) of each individual email sent in a campaign.

## Technology Stack

  * **Backend:** Python, Django
  * **Email Sending:** AWS SES (Simple Email Service)
  * **File Storage:** AWS S3 (Simple Storage Service)
  * **Task Queue:** Celery
  * **Message Broker:** Redis (running via WSL on Windows)
  * **Scheduling:** `django-celery-beat`
  * **Windows Concurrency:** `eventlet` (for Celery)
  * **Frontend:** HTML, Tailwind CSS
  * **Database:** SQLite (for local development)
  * **Environment Variables:** `python-decouple`

-----

## Setup and Installation (For Local Development)

Follow these steps to set up the project on a new machine (or if you need to reset your environment).

### 1\. Initial Setup

1.  **Project Folder:** Ensure your project is located at `C:\Users\roger\dev\bulk_mailer\`.
2.  **Create Virtual Environment:**
    ```bash
    cd C:\Users\roger\dev\bulk_mailer\
    python -m venv venv
    ```
3.  **Activate Virtual Environment:**
    ```bash
    venv\Scripts\activate
    ```
4.  **Install Dependencies:**
    ```bash
    pip install django python-decouple boto3 django-ses celery redis django-celery-beat django-celery-results eventlet django-storages
    ```
    (You may also use a `requirements.txt` file if one is created: `pip install -r requirements.txt`)

### 2\. Configuration File (.env)

1.  **Create the File:** In the project root (`C:\Users\roger\dev\bulk_mailer\`), create a file named `.env`.

2.  **Add Configuration:** Paste the following content into the `.env` file, replacing the placeholder values with your actual keys and settings.

    ```env
    # Django Settings
    DJANGO_SECRET_KEY='your-strong-django-secret-key-here'
    DJANGO_DEBUG=True
    DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
    YOUR_COMPANY_NAME="Your Company Name Here"

    # AWS Credentials (Use an IAM user with SES and S3 permissions)
    AWS_ACCESS_KEY_ID=YOUR_AWS_ACCESS_KEY_ID
    AWS_SECRET_ACCESS_KEY=YOUR_AWS_SECRET_ACCESS_KEY

    # AWS SES Settings
    AWS_SES_REGION_NAME=ap-southeast-1
    AWS_SES_SENDER_EMAIL=your-verified-sender@example.com

    # AWS S3 Settings
    AWS_STORAGE_BUCKET_NAME=your-s3-bucket-name
    AWS_S3_REGION_NAME=ap-southeast-1

    # Celery & Redis Settings
    CELERY_BROKER_URL=redis://localhost:6379/0
    ```

### 3\. Database Setup

1.  **Activate Environment:** Make sure your virtual environment is active (`venv\Scripts\activate`).
2.  **Run Migrations:**
    ```bash
    python manage.py makemigrations mailer_app
    python manage.py migrate
    ```
3.  **Create Superuser:**
    ```bash
    python manage.py createsuperuser
    ```
    (Follow the prompts to create an admin account for yourself).

-----

## Running the Local Development Environment

To run this application, you must start **four separate processes** in **four separate terminals**.

### Terminal 1: Start Redis (via WSL)

This application uses Redis as the message broker for Celery. You are running it inside WSL (Windows Subsystem for Linux).

1.  Open your WSL terminal (e.g., Ubuntu).
2.  Start the Redis server:
    ```bash
    sudo service redis-server start
    ```
3.  (Optional) Check its status:
    ```bash
    sudo service redis-server status
    ```
    It should show as `active (running)`.

### Terminal 2: Start the Celery Worker

The Celery worker picks up and executes tasks (like sending emails).

1.  Open a new terminal (e.g., PowerShell or Command Prompt).
2.  Navigate to the project root:
    ```bash
    cd C:\Users\roger\dev\bulk_mailer\
    ```
3.  Activate the virtual environment:
    ```bash
    venv\Scripts\activate
    ```
4.  Start the Celery worker (using `eventlet` for Windows):
    ```bash
    celery -A bulk_mailer worker -l info -P eventlet
    ```
    Keep this terminal open. You will see task logs here.

### Terminal 3: Start the Celery Beat Scheduler

The Celery Beat scheduler checks for and queues scheduled tasks (like campaigns to be sent at a future time).

1.  Open a *third* terminal.
2.  Navigate to the project root:
    ```bash
    cd C:\Users\roger\dev\bulk_mailer\
    ```
3.  Activate the virtual environment:
    ```bash
    venv\Scripts\activate
    ```
4.  Start the Celery Beat scheduler:
    ```bash
    celery -A bulk_mailer beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
    ```
    Keep this terminal open.

### Terminal 4: Start the Django Development Server

This is the main web application itself.

1.  Open a *fourth* terminal.
2.  Navigate to the project root:
    ```bash
    cd C:\Users\roger\dev\bulk_mailer\
    ```
3.  Activate the virtual environment:
    ```bash
    venv\Scripts\activate
    ```
4.  Start the Django server:
    ```bash
    python manage.py runserver
    ```
5.  **Access the app:** You can now open your web browser and go to `http://127.0.0.1:8000/`.

-----

## Essential Post-Setup Configuration

You must do these steps in the Django Admin for the app to function correctly.

### 1\. Configure Django Site (for Unsubscribe Links)

The app needs to know its own domain to build correct unsubscribe links.

1.  Start your Django server (`python manage.py runserver`).
2.  Go to the admin panel: `http://127.0.0.1:8000/admin/`
3.  Log in as the superuser you created.
4.  On the admin homepage, find "Sites" (at the bottom, under "SITES").
5.  Click on the single entry, which will likely be `example.com`.
6.  Change **Domain name** from `example.com` to `127.0.0.1:8000`.
7.  Change **Display name** from `example.com` to `127.0.0.1:8000`.
8.  Click **Save**.

### 2\. Configure Celery Beat Periodic Task

You need to tell Celery Beat to periodically check for scheduled campaigns.

1.  In the admin panel, find "Periodic Tasks" (under "DJANGO\_CELERY\_BEAT").
2.  Click "Add Periodic Task".
3.  **Name:** Give it a descriptive name, e.g., `Check for Scheduled Campaigns`.
4.  **Task (Registered):** Select `marketing_emails.tasks.check_scheduled_campaigns_task` from the dropdown.
5.  **Interval Schedule:**
      * Click the `+` icon to add a new interval.
      * **Every:** `1`
      * **Period:** `Minutes`
      * Click **Save**.
6.  **Enabled:** Make sure this checkbox is checked.
7.  Click **Save** (at the bottom of the "Add Periodic Task" page).

Your application is now fully configured for local development\!

## Project File Structure

  * `bulk_mailer/`: Project configuration directory.
      * `settings.py`: Main Django settings.
      * `urls.py`: Project-level URL routing.
      * `celery.py`: Celery application instance.
  * `mailer_app/`: Main Django app.
      * `models.py`: Contains all database models (ContactList, Contact, EmailTemplate, Campaign, etc.).
      * `views.py`: Contains all the view logic for the web pages.
      * `forms.py`: Contains all Django forms (CSVImportForm, CampaignForm, etc.).
      * `urls.py`: Contains the URL patterns for the `mailer_app`.
      * `admin.py`: Configures how models appear in the Django admin.
      * `templates/mailer_app/`: Contains all HTML templates for this app.
  * `marketing_emails/`: Separate app for handling background tasks.
      * `tasks.py`: Defines all Celery tasks (e.g., `send_single_email_task`, `process_campaign_task`).
  * `manage.py`: Django's management script.
  * `.env`: Your local configuration (secrets, keys). **DO NOT COMMIT TO GIT.**

<!-- end list -->

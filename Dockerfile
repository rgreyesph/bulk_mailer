# Dockerfile
# Use an official Python runtime as a parent image
FROM python:3.10-slim-buster

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Set work directory
WORKDIR /app

# Install system dependencies (for psycopg2 and other potential needs)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        # Add any other system dependencies here if needed later
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies
# Copy only requirements.txt first to leverage Docker cache
COPY requirements.txt /app/
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Copy project
COPY . /app/

# Expose port (if running Django dev server directly, though Gunicorn/Uvicorn is better for prod-like setup)
EXPOSE 8000

# Add a script to wait for PostgreSQL to be ready (optional but good for robust startup)
# Create a wait-for-postgres.sh script if you want this advanced setup
# COPY wait-for-postgres.sh /usr/local/bin/wait-for-postgres.sh
# RUN chmod +x /usr/local/bin/wait-for-postgres.sh

# Command to run the application (for development)
# For production, you'd use Gunicorn or Uvicorn
# CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
# We will override this command in docker-compose.yml for different services (app, celery, beat)
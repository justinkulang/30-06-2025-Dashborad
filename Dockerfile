# Use an official Python runtime as a parent image
FROM python:3.9-slim-buster AS builder

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Install system dependencies for WeasyPrint and other potential needs
# WeasyPrint dependencies can be extensive. This list covers common ones.
# If PDF export is not strictly needed or causes issues, these can be removed
# or a different strategy (e.g., no PDF support in Docker, or a dedicated image) chosen.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpango-1.0-0 \
    libcairo2 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf2.0-0 \
    libffi-dev \
    shared-mime-info \
    # Clean up APT when done.
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Set the working directory in the container
WORKDIR /app

# Install pip dependencies
# Copy only requirements.txt first to leverage Docker cache
COPY requirements.txt .
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /wheels -r requirements.txt


# --- Final Stage ---
FROM python:3.9-slim-buster

# Create a non-root user and group
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin -c "Docker image user" appuser

# Install system dependencies needed at runtime (subset of build-time for WeasyPrint)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libcairo2 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf2.0-0 \
    libffi-dev \
    shared-mime-info \
    # Clean up APT when done.
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy installed wheels from builder stage and install them
COPY --from=builder /wheels /wheels
COPY requirements.txt .
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt && rm -rf /wheels

# Copy the rest of the application code
COPY . .

# Create directories for logs and database if they are expected to be written inside the container
# (though volume mounting is preferred for persistence)
# Ensure the appuser owns these directories and the app code
RUN mkdir -p /app/logs /app/db_data && \
    chown -R appuser:appuser /app
# Note: The actual paths for logs/db are set in config.json.
# If using volumes, these internal directories might just be placeholders.

# Switch to the non-root user
USER appuser

# Set environment variable to disable file logging within Docker
ENV DISABLE_FILE_LOGGING=true

# Expose the port the app runs on (Gunicorn will bind to this)
# This should match the port in config.json used by gunicorn_config.py
EXPOSE 5000

# Command to run the application using Gunicorn
# gunicorn_config.py should ensure Gunicorn binds to 0.0.0.0
CMD ["gunicorn", "--config", "gunicorn_config.py", "app:app"]

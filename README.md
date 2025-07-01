# Mikrotik Hotspot User Management Dashboard

This project provides a web-based dashboard for managing Mikrotik Hotspot users, including features for user creation, batch generation, profile management, and activity monitoring. It incorporates security best practices like session management, CSRF protection, and guidance for production deployment.

## Features

*   **User Management:** Create, edit, delete, and view hotspot users.
*   **Batch User Creation:** Generate multiple voucher-style users at once.
*   **Profile Management:** Manage hotspot user profiles from the Mikrotik router.
*   **Active Sessions:** View and disconnect active hotspot users.
*   **Voucher Generation:** Export user batches as printable HTML or PDF vouchers with QR codes.
*   **Live Analytics:** Real-time dashboard showing current data usage by profile and top users.
*   **Historical Analytics:**
    *   Logs user activity and system snapshots (e.g., data usage, active user counts) over time to a local SQLite database (`hotspot_analytics.db`).
    *   Provides charts for total data usage and peak concurrent users over selectable time periods (daily, weekly, monthly).
    *   Data logging is managed by a background scheduler, configurable via `config.json`.
*   **Secure Access:**
    *   Web application login system using Flask-Login (session-based).
    *   CSRF protection for all state-changing operations using Flask-WTF.
    *   Secure Admin Password Change: Ability to change the web application admin password via the UI.
*   **Internationalization (i18n):** Support for multiple languages (English, Arabic, French).
*   **Configurable:** Key settings managed via `config.json`.
*   **Production Ready:** Includes Gunicorn configuration and guidance for HTTPS setup.

## Prerequisites

*   Python 3.7+
*   pip (Python package installer)
*   A Mikrotik router with the API service enabled.
*   Network connectivity between the server running this application and the Mikrotik router.
*   (Optional, for PDF export) System dependencies for WeasyPrint (see WeasyPrint documentation for your OS).

## Setup and Installation

1.  **Clone Repository:**
    ```bash
    git clone <repository_url>
    cd <repository_directory>
    ```

2.  **Create Virtual Environment (Recommended):**
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate
    ```

3.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
    The `requirements.txt` file includes all necessary dependencies, including `Flask-SQLAlchemy` for database operations, `Flask-Migrate` for database schema migrations, and `APScheduler` for background data logging. Pinned versions are used for stable builds. You can update these or generate your own environment's specific versions using `pip freeze > requirements.txt` after testing.

4.  **Initial Configuration (`config.json`):**
    *   Upon first run, or if `config.json` is missing, a default configuration file will be created. This file includes settings for the Mikrotik connection, web server, admin user, database, and data logging scheduler.
    *   **Database Setup:** After initial setup and before running the application for the first time in a new environment, or when upgrading, database migrations should be handled (see "Database Migrations" section under "Production Deployment"). For a brand new setup, `db.create_all()` (run when `app.py` is executed directly) will create tables, but migrations should be initialized and applied thereafter.
    *   **Web Application Admin:**
        *   A default admin user for the web dashboard is created with credentials:
            *   Username: `admin`
            *   Password: `changeme`
        *   **IMPORTANT:** Change this default password immediately after the first login! This can be done via the "Settings" tab in the web application dashboard.
        *   Alternatively, for manual updates or if direct file access is preferred, you can generate a new password hash using Python and Werkzeug security:
            ```python
            from werkzeug.security import generate_password_hash
            new_hash = generate_password_hash('your_new_strong_password')
            print(new_hash)
            ```
            Then, update the `password_hash` value in the `app_admin` section of `config.json` with this new hash.
    *   **Mikrotik Connection:**
        *   Configure your Mikrotik router details (host, API username, API password, port) either by:
            1.  Manually editing `config.json` before the first run.
            2.  Using the web application's "Settings" page after logging in with the default admin credentials. The application will not be able to manage the router until these details are correctly configured.
    *   **Database Configuration:**
        *   The application uses an SQLite database (`hotspot_analytics.db` by default, created in the application's root directory) to store historical analytics data.
        *   The database URI can be changed in `config.json` under the `database.uri` key if needed (e.g., to specify a different file path or use another SQLAlchemy-compatible database).
    *   **Scheduler Configuration:**
        *   A background scheduler logs data periodically for historical analytics.
        *   Settings are in `config.json` under the `scheduler` section:
            *   `enabled` (boolean): `true` to enable data logging, `false` to disable.
            *   `job_interval_minutes` (integer): How often (in minutes) the data logging job runs. Default is 60 minutes.
    *   **Log File Location:** The default application log file is `mikrotik_dashboard.log`. You can change this in `config.json` under `server.log_file`.

## Running the Application

### Development

For development purposes, you can use the Flask development server:
```bash
python app.py
```
This server is convenient but not suitable for production. The debug mode is sourced from `config.json` (`server.debug`), which now defaults to `false`.

### Production (Recommended)

For production, it is highly recommended to use a production-grade WSGI server like Gunicorn, and to run the application behind a reverse proxy like Nginx for HTTPS termination and serving static files.

1.  **Using Gunicorn:**
    A `gunicorn_config.py` file is provided. It attempts to load server host and port from `config.json`.
    Run Gunicorn with:
    ```bash
    gunicorn --config gunicorn_config.py app:app
    ```
    Ensure Gunicorn is installed (`pip install gunicorn`).

2.  **Further Production Setup:**
    Refer to the "Production Deployment" section below for crucial details on HTTPS, environment variables, etc.

## Production Deployment

When deploying this application to a production environment, several considerations should be taken into account for security, reliability, and performance.

### Configuration Precedence
The application configuration is loaded in the following order of precedence (later sources override earlier ones):
1.  Default values hardcoded in `app.py`.
2.  Values from `config.json` file (if it exists).
3.  Values from Environment Variables (if set).

### Environment Variable Overrides
Many critical configuration settings can be overridden using environment variables. This is particularly useful for Docker deployments and for managing sensitive data outside of the `config.json` file. Boolean values are generally interpreted from strings like "true", "1", "yes" (case-insensitive) or "false", "0", "no".

**Available Environment Variables:**

*   **Mikrotik Connection:**
    *   `APP_MIKROTIK_HOST`: Mikrotik router IP address or hostname.
    *   `APP_MIKROTIK_PORT`: API port (integer).
    *   `APP_MIKROTIK_USERNAME`: API username.
    *   `APP_MIKROTIK_PASSWORD`: API password.
    *   `APP_MIKROTIK_USE_SSL`: Set to `true` or `false` to enable/disable SSL for API connection.
    *   `APP_MIKROTIK_HOTSPOT_LOGIN_URL`: URL for hotspot login page (used for QR codes).
*   **Server Settings:**
    *   `APP_SERVER_HOST`: Host address for the web server to bind to (e.g., `0.0.0.0`).
    *   `APP_SERVER_PORT`: Port for the web server (integer).
    *   `APP_SERVER_DEBUG`: Set to `true` or `false` to enable/disable Flask debug mode.
    *   `APP_SERVER_LOG_FILE`: Path to the application log file.
    *   `APP_SERVER_LOG_LEVEL_CONSOLE`: Log level for console output (e.g., `INFO`, `DEBUG`, `WARNING`).
    *   `APP_SERVER_LOG_LEVEL_FILE`: Log level for file output.
*   **Database:**
    *   `APP_DATABASE_URI`: SQLAlchemy database URI (e.g., `sqlite:///./db_data/hotspot_analytics.db`).
*   **Scheduler:**
    *   `APP_SCHEDULER_ENABLED`: Set to `true` or `false` to enable/disable the background data logging scheduler.
    *   `APP_SCHEDULER_JOB_INTERVAL_MINUTES`: Interval for scheduler job in minutes (integer).
*   **Application Admin:**
    *   `APP_ADMIN_USERNAME`: Username for the web application admin. (Password is managed via UI or `config.json` hash).
*   **Flask Specific:**
    *   `FLASK_SECRET_KEY`: (Covered below) Crucial for session security.
*   **Logging Control (Docker):**
    *   `DISABLE_FILE_LOGGING`: Set to `true` to disable Flask's file logging (recommended for Docker where logs go to stdout/stderr).

### Database Migrations
This application uses `Flask-Migrate` (which wraps Alembic) to manage database schema changes for the `hotspot_analytics.db`.

**Workflow:**

1.  **Initialization (One-time per project environment):**
    If you are setting up migrations for the first time in your development environment:
    ```bash
    # Ensure your virtual environment is activated
    # export FLASK_APP=app.py  (For Linux/macOS)
    # $env:FLASK_APP = "app.py" (For PowerShell)
    # set FLASK_APP=app.py     (For Windows CMD)
    flask db init
    ```
    This creates a `migrations` directory. Commit this directory to your version control.

2.  **Creating a New Migration:**
    After making changes to your SQLAlchemy models in `app.py` (e.g., adding a new table or column):
    ```bash
    flask db migrate -m "Brief description of model changes"
    ```
    This will auto-generate a new migration script in the `migrations/versions/` directory. Review this script to ensure it correctly reflects your changes.

3.  **Applying Migrations:**
    To apply pending migrations to your database (this actually changes the database schema):
    ```bash
    flask db upgrade
    ```
    This command should be run during deployment when updating the application to a new version with schema changes. For a new database, `flask db upgrade` will apply all migrations, bringing the schema to the latest version.

4.  **Downgrading (if necessary):**
    To revert a migration:
    ```bash
    flask db downgrade
    ```

**Important Notes:**
*   Always run these commands with your application's virtual environment activated.
*   The `FLASK_APP` environment variable must be set to point to your main application file (e.g., `app.py` or `wsgi.py`).
*   When deploying, `flask db upgrade` should typically be run *before* starting the new version of the application server.
*   The `hotspot_analytics.db` file (if using SQLite) should be writable by the user running the Flask commands and the application.

### `SECRET_KEY` Configuration
For session security, Flask uses a `SECRET_KEY`.
*   **Action Required:** Set the `FLASK_SECRET_KEY` environment variable to a strong, unique, and random string. Do not use the default fallback key in production.
*   The application will use the environment variable if set. If not set, it falls back to a hardcoded development key.
*   If the fallback key is used:
    *   A `WARNING` is logged if the application is in debug mode.
    *   A more severe `ERROR` is logged if the application is NOT in debug mode, highlighting a critical security risk.

### Debug Mode
*   **Action Required:** Ensure that `debug` is set to `false` in the `server` section of your `config.json` for production. The application now defaults this to `false` if the key is missing or a new config is generated.

### WSGI Server (Gunicorn)
*   The provided `gunicorn_config.py` sets up Gunicorn to bind to the host and port specified in `config.json` (defaulting to `0.0.0.0:5000`).
*   It also sets a recommended number of worker processes.
*   You can customize `gunicorn_config.py` further for advanced Gunicorn settings (e.g., logging, timeouts).

### HTTPS Setup (Recommended)
For production, it is strongly recommended to serve the application over HTTPS. The typical setup involves running Gunicorn locally and using a reverse proxy like Nginx or Apache in front of it to handle HTTPS termination.

**Why HTTPS is Crucial:**
*   **Security:** Encrypts data between the user's browser and the server.
*   **Data Integrity:** Ensures data is not tampered with during transit.
*   **User Trust:** Browsers mark HTTP sites as "not secure."

**Example Nginx Configuration:**
(This example assumes Gunicorn is listening on `127.0.0.1:5000`)

```nginx
server {
    listen 80;
    server_name your_domain.com; # Replace with your actual domain

    # Redirect all HTTP traffic to HTTPS
    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl http2;
    server_name your_domain.com; # Replace with your actual domain

    # SSL Certificate paths
    ssl_certificate /etc/letsencrypt/live/your_domain.com/fullchain.pem; # Adjust path (e.g., from Let's Encrypt)
    ssl_certificate_key /etc/letsencrypt/live/your_domain.com/privkey.pem; # Adjust path
    
    # Recommended SSL settings (consult current best practices)
    # ssl_protocols TLSv1.2 TLSv1.3;
    # ssl_ciphers 'ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:DHE-RSA-AES128-GCM-SHA256:DHE-RSA-AES256-GCM-SHA384';
    # ssl_prefer_server_ciphers off;
    # Add HSTS header (optional, but recommended)
    # add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;

    # (Optional) Serve static files directly with Nginx for better performance
    # location /static {
    #     alias /path/to/your/project/static; # Adjust to your app's static folder
    #     expires 7d;
    #     access_log off;
    # }

    location / {
        proxy_pass http://127.0.0.1:5000; # Must match Gunicorn's bind address
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```
**Notes for Nginx:**
*   Replace `your_domain.com` with your domain.
*   Adjust SSL certificate paths. Consider using Certbot from Let's Encrypt for free certificates.
*   Ensure Gunicorn (via `gunicorn_config.py` and `config.json`) binds to `127.0.0.1:5000` if Nginx is on the same machine. If Gunicorn binds to `0.0.0.0`, ensure your firewall is configured appropriately.

### Logging
*   The application is configured to log to both the console and a file.
*   The default log file is `mikrotik_dashboard.log` (configurable in `config.json` via `server.log_file`).
*   Console and file log levels are also configurable in `config.json` (`server.log_level_console`, `server.log_level_file`).
*   When using Gunicorn, its own logging mechanisms (e.g., `accesslog`, `errorlog` in `gunicorn_config.py`) can also be used to capture stdout/stderr from the application.

### Pinned Dependencies
*   `requirements.txt` includes pinned versions for all dependencies to ensure stable and reproducible builds.
*   If you modify your environment or update packages, it's good practice to regenerate this file with your current working set: `pip freeze > requirements.txt`.

### Other Production Considerations (from previous README section)
*   **Database:** For more robust data storage than `config.json` (especially for user credentials if not using a fixed admin user), consider using a proper database system.
*   **Backups:** Implement regular backups of your application data and configurations.
*   **Monitoring:** Set up monitoring for your application and server to track performance and errors.
*   **Firewall:** Configure a firewall to only allow necessary traffic to your server (e.g., ports 80 and 443).

## Docker Deployment

This application can be deployed using Docker. A `Dockerfile` is provided to build an image.

### Prerequisites

*   Docker installed on your system.

### Building the Docker Image

1.  **Clone the repository (if you haven't already):**
    ```bash
    git clone <repository_url>
    cd <repository_directory>
    ```
2.  **Build the image:**
    From the root of the project directory (where the `Dockerfile` is located), run:
    ```bash
    docker build -t mikrotik-hotspot-dashboard .
    ```
    You can replace `mikrotik-hotspot-dashboard` with your preferred image name.

### Running the Docker Container

When running the container, you'll need to manage configuration, persistent data, and environment variables.

1.  **Configuration (`config.json`):**
    The application can generate a default `config.json` on first start. However, it's recommended to manage your `config.json` externally and mount it into the container.
    *   Create a `config.json` file on your host system. You can copy and modify the structure from the repository or let the application generate one on first run and then copy it out of a temporary container (`docker cp <container_id>:/app/config.json ./my_config.json`).
    *   Ensure your `config.json` has the correct Mikrotik details, admin credentials, and server settings (especially `host: "0.0.0.0"` for Gunicorn to be accessible).

2.  **Persistent Data:**
    *   **Database (`hotspot_analytics.db`):** To persist analytics data, mount a volume to the path specified for the database in your `config.json`. If using the default path, it's in the application root (e.g., `/app/hotspot_analytics.db` inside the container).
    *   **Logs (`mikrotik_dashboard.log`):** The Docker image is configured to disable file logging by default (`DISABLE_FILE_LOGGING=true`), with logs going to `stdout`/`stderr` (handled by Docker). If you re-enable file logging or want to persist internal logs, mount a volume to the path specified for `log_file` in `config.json`.

3.  **Environment Variables:**
    *   **`FLASK_SECRET_KEY` (Required for Production):** Set this to a strong, random string.
    *   **`DISABLE_FILE_LOGGING` (Optional):** Set to `false` if you want to enable file logging inside the container (default is `true` in the provided Dockerfile, which disables file logs).
    *   Other environment variables could be added in the future to override `config.json` settings.

4.  **Example `docker run` command:**

    Replace placeholders (`/path/to/your/...`, `your_strong_secret_key`, `your_image_name:tag`) with your actual values.

    ```bash
    docker run -d \
        --name hotspot-dashboard-container \
        -p 5000:5000 \
        -v /path/to/your/config.json:/app/config.json \
        -v /path/to/your/data/db:/app/db_data \
        # Example: if your config.json's database.uri is "sqlite:////app/db_data/hotspot_analytics.db"
        # -v /path/to/your/data/logs:/app/logs \
        # Example: if your config.json's server.log_file is "/app/logs/mikrotik_dashboard.log" and file logging is enabled
        -e FLASK_SECRET_KEY="your_strong_secret_key_here" \
        # -e DISABLE_FILE_LOGGING="false" # Uncomment to enable file logging
        mikrotik-hotspot-dashboard
        # Or your_image_name:tag if you used a different one
    ```

    **Explanation:**
    *   `-d`: Run in detached mode.
    *   `--name hotspot-dashboard-container`: Assign a name to the container.
    *   `-p 5000:5000`: Map port 5000 on the host to port 5000 in the container (assuming your `config.json` and `gunicorn_config.py` use port 5000).
    *   `-v /path/to/your/config.json:/app/config.json`: Mounts your local `config.json` into the container at `/app/config.json`. **Important:** The application expects `config.json` to be in its root directory (`/app/` inside the container).
    *   `-v /path/to/your/data/db:/app/db_data`: Mounts a directory from your host to `/app/db_data` inside the container. You would then set `database.uri` in your `config.json` to something like `sqlite:////app/db_data/hotspot_analytics.db`.
    *   `-e FLASK_SECRET_KEY="..."`: Sets the required secret key.

    **Note on Paths in `config.json` for Docker:**
    When running in Docker, paths in `config.json` for `database.uri` (if SQLite) and `server.log_file` should be relative to the container's file system (e.g., `/app/db_data/hotspot_analytics.db`, `/app/logs/mikrotik_dashboard.log`). Match these paths with your volume mounts.

### WeasyPrint Dependencies

The Dockerfile attempts to install system dependencies for WeasyPrint to enable PDF export. If you encounter issues with PDF generation or want a smaller image and don't need PDF export, you can remove the WeasyPrint-related `apt-get install` lines from the `Dockerfile` and rebuild the image. The application will then run with PDF export disabled.

## Translations (i18n)

This application uses Flask-Babel for internationalization.
*   Supported languages: English (default), Arabic, French.
*   Translations are stored in the `translations` directory.
*   To add or update translations:
    1.  Extract messages: `pybabel extract -F babel.cfg -o messages.pot .`
    2.  Initialize a new language (e.g., for Spanish 'es'): `pybabel init -i messages.pot -d translations -l es`
    3.  Update existing languages: `pybabel update -i messages.pot -d translations`
    4.  Compile translations: `pybabel compile -d translations`
    (Ensure you have Babel installed and `babel.cfg` correctly configured if you modify translatable files.)

*(License section would go here if applicable)*
*(Contributing guidelines would go here if applicable)*

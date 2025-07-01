# Agent Instructions for Mikrotik Hotspot User Management Dashboard

This document provides guidance for AI software engineering agents working with this codebase.

## Overview

This is a Flask-based web application for managing Mikrotik Hotspot users. Key components include:
- `app.py`: Main Flask application, API endpoints, business logic.
- `mikrotik_userman_dashboard.html`: Primary frontend (SPA-style) with extensive JavaScript.
- `login.html`: Handles application and Mikrotik login.
- `config.json`: Stores application configuration, including Mikrotik connection details and admin credentials.
- `librouteros`: Python library used for Mikrotik API communication.
- `hotspot_analytics.db`: SQLite database for historical analytics.

## Development Conventions

- **Flask Blueprints are not currently used.** All routes are defined in `app.py`. Consider using Blueprints if the number of routes grows significantly.
- **Error Handling:**
    - Backend: Python exceptions should be caught and appropriate JSON responses returned, often with a `success: false` and `message` field. Use the provided `_()` function for user-facing messages for i18n.
    - Frontend: The `apiCall` JavaScript function is a central place for making backend requests. It includes basic error handling. Alerts are shown using the `showAlert()` function.
- **Translations (i18n):**
    - User-facing strings in Python should be wrapped in `_()`.
    - User-facing strings in JavaScript should use `getTranslation('key')`.
    - New translation keys should be added to the `translations` dictionary in the `get_translations` route in `app.py`.
    - After adding new keys, run `pybabel extract`, `pybabel update`, and `pybabel compile` as described in `README.md` to update translation files.
- **Configuration:**
    - Sensitive information like passwords should be handled carefully. The application admin password is now changeable via the UI.
    - `config.json` now uses a `mikrotik_routers` list for multi-router support. `ConfigLoader` handles this new structure, including migration from the old single `mikrotik` object.
    - Router configurations (add, edit, delete) are managed via API endpoints (`/api/routers/...`) and UI in Settings.
    - **Environment Variables:** Primary Mikrotik env vars (`APP_MIKROTIK_HOST`, etc.) now apply to the first router in the list or initialize one. Refer to `README.md`.
- **Database Migrations:** The application uses `Flask-Migrate`. Historical data in `UserActivityLog` and `SystemSnapshot` is currently aggregated from all routers (schema does not yet include `router_id`).
- **Rate Limiting:** API rate limiting is implemented using `Flask-Limiter`.
- **Error Tracking:** Sentry SDK is integrated.

## Working with the Frontend (`mikrotik_userman_dashboard.html`)

- The dashboard is heavily JavaScript-driven.
- **Multi-Router UI:**
    - A router selector dropdown (`#routerSelector`) is available in the Settings tab.
    - `currentRouterId` global JS variable stores the active router's ID.
    - `allConfiguredRouters` global JS variable stores the list of routers.
    - `handleRouterSelectionChange()` manages loading data for the selected router.
    - The router configuration form in Settings is now used for both adding new and editing existing routers.
- **API Calls:**
    - The `apiCall(endpoint, options, isGlobalApi = false)` JS function now automatically prepends `/api/routers/${currentRouterId}` to relevant (non-global) endpoints.
    - Endpoints that are truly global (e.g., `/api/translations`, `/api/admin/change-password`) or already router-scoped (e.g., `/api/routers/...` for CRUD) should be called with `isGlobalApi = true` or ensure their path starts with `/routers/`.
- UI updates are typically done by directly manipulating the DOM or re-rendering table/list sections.
- Pay attention to existing helper functions in JavaScript.
- When adding new UI elements that require translation, ensure keys are added to `get_translations` in `app.py` and used via `getTranslation()` in JS.

## Security Considerations

- Always validate user input on the server-side, even if there's client-side validation.
- Be mindful of changes to `config.json`, especially the `app_admin` section. The `ConfigLoader` class has specific methods for updating credentials.
- Ensure CSRF protection is maintained for all state-changing operations. Flask-WTF is used.
- Follow best practices for handling passwords (hashing is done by `werkzeug.security`).

## Testing

- No automated test suite currently exists.
- Manual testing is required for all changes. Key areas to test:
    - User authentication and session management.
    - All CRUD operations for users and profiles.
    - Batch user creation and voucher generation (HTML and PDF).
    - Active session management.
    - Settings changes and their effects.
    - Analytics display.
- When making backend changes, consider how they will be reflected or handled in the frontend.

## Future Agent Guidance

- If you significantly refactor `app.py` (e.g., by introducing Blueprints), update this document.
- If a formal testing framework is added, document how to run tests here.

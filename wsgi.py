"""WSGI entry point for production servers (gunicorn, uWSGI, etc.).

Usage:
    gunicorn --workers 3 --bind 0.0.0.0:8080 wsgi:app

The application reads its configuration from environment variables
(see `.env.example`), so no secrets live in this file.
"""
from app import app, init_db

# Ensure the schema exists and the bootstrap admin is seeded before serving.
# Safe to call on every start: it only creates missing tables/columns and
# seeds the admin when the users table is empty.
init_db()

if __name__ == "__main__":
    import os
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
